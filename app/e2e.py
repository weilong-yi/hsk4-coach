"""End-to-end run on the real surface: headless Google Chrome with a fake mic and camera drives the placement,
a 5-minute session, one full daily session (block timers sped up with ?timescale), a reading check, and the stats
page, against a throwaway database. Then it checks the database, the WAV files on disk, and tools/weekly.py.
A second server over a copy of that database, with three weeks of seeded history, a lowered review cap and a temp
LaunchAgents folder, checks the streak calendar, the plan and its reminder plist, and the review cap.

    .venv/bin/python app/e2e.py            # screenshots go to app/screenshots/

Headless Chrome's speech recognition starts but never returns a transcript, so the real recognizer is exercised
only on its empty/error path. One extra attempt swaps in a scripted recognizer that emits Safari-style cumulative
results, to check the merge rule and the scored view. Real-mic transcription is not verified here.
"""
import json, plistlib, re, socket, sqlite3, subprocess, sys, tempfile, time, wave
from collections import Counter
from datetime import datetime, timedelta, timezone
from datetime import time as clock_time
from pathlib import Path

import numpy as np
from fsrs import Card
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import db, momentum, reminder  # noqa: E402

SHOTS = ROOT / "app" / "screenshots"
REAL_AGENT = reminder.plist_path(reminder.AGENTS)  # must never be written by this run
PORT = 8767
TIMESCALE = 30
URL = f"http://localhost:{PORT}/?timescale={TIMESCALE}"

TRACK_STREAMS = """
window.__streams = [];
const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia = async c => { const s = await orig(c); window.__streams.push(s); return s; };
"""
FAKE_RECOGNITION = """finals => {
  class Scripted {
    start() {
      let i = 0;
      const emit = () => {
        if (this.stopped || i >= finals.length) return;
        this.onresult && this.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: finals[i++] }], { isFinal: true })] });
        setTimeout(emit, 250);
      };
      setTimeout(emit, 200);
    }
    stop() { this.stopped = true; setTimeout(() => this.onend && this.onend(), 30); }
    abort() { this.stop(); }
  }
  window.SpeechRecognition = window.webkitSpeechRecognition = Scripted;
}"""


def shot(page, name, full=False):
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=full)
    print("  screenshot", name)


def until(page, done, name, seconds=120):
    t0 = time.time()
    while not done():
        if time.time() - t0 > seconds:
            shot(page, f"stuck-{name}")
            raise RuntimeError(f"stuck in {name}")
        if page.locator("button", has_text="Continue").is_visible():
            page.keyboard.press("Enter")
        yield


def mics_released(page):
    return page.evaluate("window.__streams.length > 0 && window.__streams.every(s => s.getTracks().every(t => t.readyState === 'ended'))")


def wait_port(port, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            socket.create_connection(("127.0.0.1", port), 0.5).close()
            return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("server did not start")


def placement(page):
    page.goto(URL + "#/home")
    expect(page.get_by_text("Start placement")).to_be_visible()
    shot(page, "01-home-first-run")
    page.get_by_text("Start placement").click()
    expect(page.get_by_role("heading", name="Placement test (about 10 minutes)")).to_be_visible()
    shot(page, "02-placement-intro")
    with page.expect_response("**/api/placement/start") as r:
        page.keyboard.press("Enter")
    data = r.value.json()

    pseudo_yes = False
    for i, it in enumerate(data["vocab"]):
        expect(page.locator(".hanzi.xl")).to_have_text(it["w"])
        expect(page.locator(".part .muted")).to_have_text(f"{i + 1} / {len(data['vocab'])}")
        if i == 3:
            shot(page, "03-placement-vocab")
        if it["pseudo"]:
            claim, pseudo_yes = not pseudo_yes, True
        else:
            claim = it["lvl"] <= 2 or (it["lvl"] == 3 and i % 2 == 0)
        page.keyboard.press("y" if claim else "n")

    vocab = {it["w"]: it for it in data["vocab"]}
    for i in range(5):
        expect(page.get_by_text("Quick check: what does this word mean?")).to_be_visible()
        expect(page.locator(".part .muted")).to_have_text(f"{i + 1} / 5")
        it = vocab[page.locator(".hanzi.xl").inner_text()]
        page.keyboard.press(str((it["answer"] + (1 if i == 0 else 0)) % 4 + 1))
        if i == 0:
            shot(page, "04-placement-spot-check")
        page.keyboard.press("Enter")

    expect(page.get_by_role("heading", name="Listening")).to_be_visible()
    page.keyboard.press("Enter")
    for i, it in enumerate(data["listen"]):
        expect(page.locator(".part .muted")).to_have_text(f"{i + 1} / {len(data['listen'])}")
        page.wait_for_timeout(300)
        page.keyboard.press(str(it["answer"] + 1 if it["lvl"] <= 2 else (it["answer"] + 1) % 4 + 1))
        if i == 0:
            shot(page, "05-placement-listening")
        page.keyboard.press("Enter")

    expect(page.get_by_role("heading", name="Tones")).to_be_visible()
    page.keyboard.press("Enter")
    for i, it in enumerate(data["tone"]):
        expect(page.locator(".part .muted")).to_have_text(f"{i + 1} / {len(data['tone'])}")
        a, b = it["tones"]
        page.keyboard.press(str(a))
        page.keyboard.press(str(b if i % 3 else b % 4 + 1))
        if i == 1:
            shot(page, "06-placement-tones")
        if i < len(data["tone"]) - 1:
            page.keyboard.press("Enter")
    with page.expect_response("**/api/placement/reading") as r:
        page.keyboard.press("Enter")
    reading = r.value.json()
    reading_check(page, reading, "07-placement-reading", "08-placement-reading-question")
    expect(page.get_by_role("heading", name="Your starting profile")).to_be_visible(timeout=20000)
    shot(page, "09-placement-results")
    return data, reading


def reading_check(page, reading, text_shot=None, question_shot=None):
    expect(page.get_by_role("heading", name="Timed reading")).to_be_visible()
    page.keyboard.press("Enter")
    expect(page.locator(".reading")).to_be_visible()
    if text_shot:
        shot(page, text_shot)
    page.wait_for_timeout(1500)
    page.keyboard.press("Enter")
    for i, q in enumerate(reading["questions"]):
        expect(page.get_by_text("Which of these did the text say?")).to_be_visible()
        expect(page.locator(".part .muted")).to_have_text(f"{i + 1} / {len(reading['questions'])}")
        page.keyboard.press(str(q["answer"] + 1))
        if i == 0 and question_shot:
            shot(page, question_shot)
        page.keyboard.press("Enter")


def start_block(page, title, name):
    expect(page.get_by_role("heading", name=title)).to_be_visible(timeout=30000)
    shot(page, name)
    page.keyboard.press("Enter")


def session(page):
    page.locator("a.button.primary[href='#/session']").click()  # "Start today's session" after placement, "Start N-minute session" on home
    start_block(page, "Cards · 8 minutes", "10-session-start")
    n, shots = 0, set()
    transition = page.get_by_role("heading", name="Listen & read · 12 minutes")
    for _ in until(page, transition.is_visible, "cards"):
        if page.locator(".card.front").is_visible():
            if "front" not in shots:
                shots.add("front")
                shot(page, "11-cards-front")
            page.keyboard.press("Space")
        elif page.locator(".card.back").is_visible():
            if "back" not in shots:
                shots.add("back")
                shot(page, "12-cards-back")
            if "expired" not in shots and page.locator(".timer.expired").is_visible():
                shots.add("expired")
                shot(page, "13-cards-time-up")
            page.keyboard.press("1" if n % 4 == 0 else "3")
            n += 1
            page.wait_for_timeout(150)
        page.wait_for_timeout(100)
    print(f"  cards rated in block: {n}")

    start_block(page, "Listen & read · 12 minutes", "14-listen-start")
    k = 0
    transition = page.get_by_role("heading", name="Speak · 10 minutes")
    for _ in until(page, transition.is_visible, "listen"):
        if page.locator(".listen.audio").is_visible():
            if k == 0:
                page.wait_for_timeout(600)
                shot(page, "15-listen-audio-first")
            page.keyboard.press("n" if k % 3 == 0 else "y")
        elif page.locator(".listen.text").is_visible():
            if k < 3:
                tok = page.locator(".tok.new").first if page.locator(".tok.new").count() else page.locator(".tok.tap").first
                with page.expect_response("**/api/lookup"):
                    tok.click()
                expect(page.locator(".popover")).to_be_visible()
                if k == 0:
                    shot(page, "16-listen-lookup")
            k += 1
            page.keyboard.press("Enter")
            page.wait_for_timeout(150)
        page.wait_for_timeout(100)
    print(f"  sentences in listen block: {k}")

    with page.expect_response("**/api/shadow/items") as r:
        start_block(page, "Speak · 10 minutes", "17-speak-start")
    items = r.value.json()["sentences"]
    expect(page.locator(".speak")).to_be_visible()
    shot(page, "18-speak-ready")

    page.keyboard.press("r")
    expect(page.get_by_text("Recording… speak now")).to_be_visible()
    page.wait_for_timeout(2500)
    shot(page, "19-speak-recording")
    with page.expect_response("**/api/shadow"):
        page.keyboard.press("r")
    # Headless Chrome's recognizer usually returns nothing, but sometimes transcribes noise from the fake mic tone.
    expect(page.locator(".result .warn, .scored").first).to_be_visible()
    shot(page, "20-speak-result-headless-recognizer")
    released_after_attempt = mics_released(page)

    page.keyboard.press("r")
    expect(page.get_by_text("Recording… speak now")).to_be_visible()
    page.wait_for_timeout(1200)
    page.keyboard.press("Enter")
    expect(page.locator(".speak .sentence")).to_be_visible()
    page.wait_for_timeout(300)
    released_after_next = mics_released(page)

    zh = "".join(t for t in items[1]["tok"])
    finals = [zh[:2], zh[:max(3, len(zh) - 3)], zh[max(3, len(zh) - 3):-1]]
    page.evaluate(FAKE_RECOGNITION, finals)
    page.keyboard.press("r")
    expect(page.get_by_text("Recording… speak now")).to_be_visible()
    page.wait_for_timeout(1500)
    with page.expect_response("**/api/shadow") as r:
        page.keyboard.press("r")
    scored = r.value.json()
    expect(page.locator(".scored")).to_be_visible()
    shot(page, "21-speak-scored-scripted-recognizer")

    expect(page.locator(".timer.expired")).to_be_visible(timeout=30000)
    shot(page, "22-speak-time-up")
    page.keyboard.press("Enter")
    expect(page.get_by_role("heading", name="Session complete")).to_be_visible(timeout=10000)
    shot(page, "23-session-complete")
    return {"cards": n, "sentences": k, "released_after_attempt": released_after_attempt,
            "released_after_next": released_after_next, "scripted_finals": finals, "scripted_target": zh, "scripted": scored}


def momentum_text(page):
    return {"rings": page.locator(".rings .ring-label").all_text_contents(), "streak": page.locator(".streak-n").inner_text(),
            "freezes": page.locator(".freezes").inner_text(), "minimum": page.locator(".minimum").inner_text()}


def quick_session(page, ratings=12, easy=3):
    """The 5-minute session from Home. Rates the first `easy` cards Easy (a new card rated Easy moves straight into
    review) and the rest Again (which keeps a card in learning), then skips the rest of the block. Returns failures
    and what it saw."""
    fails = []
    page.goto(URL.replace(f"timescale={TIMESCALE}", "timescale=10") + "#/home")  # 30 s of block time for 12 cards
    expect(page.get_by_role("heading", name="Today")).to_be_visible()
    before = momentum_text(page)
    with page.expect_response("**/api/session/start") as r:
        page.get_by_role("link", name="5-minute session").click()
    start = r.value.json()
    expect(page.get_by_role("heading", name="Cards · 5 minutes")).to_be_visible()
    page.keyboard.press("Enter")
    easy_words, new_words = [], []
    for n in range(ratings):
        expect(page.locator(".card.front")).to_be_visible()
        page.wait_for_timeout(400)  # let the word start playing, as a learner would; card events log the voice heard
        page.keyboard.press("Space")
        back = page.locator(".card.back")
        expect(back).to_be_visible()
        word = back.locator(".hanzi.xl").inner_text()
        if back.locator(".badge.new").count():
            new_words.append(word)
        with page.expect_response("**/api/cards/review"):
            page.keyboard.press("4" if n < easy else "1")
        if n < easy:
            easy_words.append(word)
    with page.expect_response("**/api/session/summary") as r:
        page.get_by_role("button", name="Skip block →").click()
    feedback = r.value.json()
    expect(page.get_by_role("heading", name="Session complete")).to_be_visible()
    shot(page, "32-quick-session-complete", full=True)
    done = {**momentum_text(page), "moved": page.locator(".progress-item", has_text="Moved forward").inner_text(),
            "new": page.locator(".progress-item", has_text="New words").inner_text(),
            "tiles": page.locator(".tile .label").all_inner_texts()}
    page.goto(URL + "#/home")  # back to the run's timescale for the full session
    expect(page.get_by_role("heading", name="Today")).to_be_visible()
    after = momentum_text(page)
    plan_text = page.locator(".plan").inner_text()
    today_cell = page.locator(".calendar .weeks .day.today").get_attribute("class")

    if not start["session_id"].startswith("Q") or start["blocks"] != [{"id": "cards", "title": "Cards", "minutes": 5}]:
        fails.append(f"quick session start: {start['session_id']} {start['blocks']}")
    if before["rings"] != ["Cards 0/20", "Listen 0/15", "Speak 0/5"] or before["streak"] != "No streak yet" \
            or before["minimum"] != "10 cards would count today.":
        fails.append(f"home before the quick session: {before}")
    if done["rings"][0] != f"Cards {ratings}/20" or "1-day streak" not in done["streak"] or "+1 today" not in done["streak"]:
        fails.append(f"quick session complete: rings/streak {done}")
    if not done["moved"].startswith(f"Moved forward\n{easy} words now in review") or any(w not in done["moved"] for w in easy_words):
        fails.append(f"moved forward should list the {easy} Easy words {easy_words}: {done['moved']!r}")
    if not done["new"].startswith(f"New words\n{len(new_words)} words started") or any(w not in done["new"] for w in new_words):
        fails.append(f"new words should list {new_words}: {done['new']!r}")
    if done["tiles"] != ["Cards"]:
        fails.append(f"quick session tiles should be Cards only: {done['tiles']}")
    if after["rings"][0] != f"Cards {ratings}/20" or after["streak"] != "1-day streak" or after["minimum"] != "Today's minimum is met.":
        fails.append(f"home after the quick session: {after}")
    if "null" in plan_text or "Save plan" not in plan_text:
        fails.append(f"plan box without a plan: {plan_text!r}")
    if "met" not in today_cell.split():
        fails.append(f"today's calendar cell is not met: {today_cell}")
    return fails, {"session_id": start["session_id"], "before": before, "complete": done, "after": after,
                   "easy_words": easy_words, "new_words": new_words, "met_now": feedback["met_now"]}


# Study-day offsets from today with 8 listening answers each (the minimum). Expected walk, oldest first:
# 3 met, a miss with no freeze (reset), 7 met (a freeze), a miss (frozen), 8 met (another freeze), then today.
SEED_MET = [-20, -19, -18, *range(-16, -9), *range(-8, 0)]
LATE_NIGHT = -10  # seeded at 01:30 the next calendar morning, which still belongs to this study day


def seed_history(db_path, start_hour):
    """Past listening days per SEED_MET, and every introduced card made two days overdue, as after a break.
    Returns the size of that review backlog."""
    con = sqlite3.connect(db_path)
    today = momentum.study_day(db.now(), start_hour)
    overdue = datetime.now(timezone.utc) - timedelta(days=2)
    cards = con.execute("SELECT word, fsrs_json FROM cards WHERE introduced_at IS NOT NULL").fetchall()
    with con:
        for word, js in cards:
            card = Card.from_json(js)
            card.due = overdue
            con.execute("UPDATE cards SET fsrs_json=? WHERE word=?", (card.to_json(), word))
        for off in SEED_MET:
            day = today + timedelta(days=off)
            when = datetime.combine(day + timedelta(days=1), clock_time(1, 30)) if off == LATE_NIGHT else datetime.combine(day, clock_time(12))
            for k in range(8):
                con.execute("INSERT INTO events(ts, session_id, activity, item, result_json, ms) VALUES (?,?,?,?,?,?)",
                            (when.astimezone().isoformat(timespec="milliseconds"), f"S{day:%Y%m%d}-120000-seed", "listen", str(k + 1),
                             json.dumps({"understood": k % 4 != 0, "block": "listen", "block_ms": 1000 * k}), 1000))
    con.close()
    return len(cards)


def history_journey(browser, db_path, tmp):
    """A second server over a copy of the run's database plus seeded history and an overdue backlog. Its config caps
    reviews at today's count + 3 and its reminder goes to a temp LaunchAgents folder (launchctl is never called)."""
    fails = []
    home = tmp / "history"
    home.mkdir()
    db2, agents = home / "study.db", home / "LaunchAgents"
    src, dst = sqlite3.connect(db_path), sqlite3.connect(db2)
    src.backup(dst)
    src.close(), dst.close()
    cfg = json.loads((ROOT / "app" / "config.json").read_text())
    m = cfg["momentum"]
    backlog = seed_history(db2, m["day_starts_hour"])
    today = momentum.study_day(db.now(), m["day_starts_hour"])
    con = sqlite3.connect(db2)
    reviewed = sum(momentum.study_day(datetime.fromisoformat(ts), m["day_starts_hour"]) == today for (ts,) in
                   con.execute("SELECT ts FROM events WHERE activity='card' AND item!='block_end'"))
    con.close()
    m["max_reviews_per_day"] = cap = reviewed + 3
    (home / "config.json").write_text(json.dumps(cfg))
    port = PORT + 1
    server = subprocess.Popen([sys.executable, "-m", "app.server", "--db", str(db2), "--config", str(home / "config.json"),
                               "--port", str(port), "--launch-agents", str(agents)],
                              cwd=ROOT, stdout=open(home / "server.log", "w"), stderr=subprocess.STDOUT)
    url = f"http://localhost:{port}/?timescale={TIMESCALE}"
    ctx = browser.new_context(viewport={"width": 1100, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(f"history pageerror: {e}"))
    try:
        wait_port(port)
        page.goto(url + "#/home")
        expect(page.get_by_role("heading", name="Today")).to_be_visible()
        seen = momentum_text(page)
        cells = Counter(c.split()[1] for c in page.locator(".calendar .weeks .day").evaluate_all("els => els.map(e => e.className)"))
        ahead = 6 - today.weekday()
        want = {"none": 7 - ahead, "met": 19, "missed": 1, "frozen": 1, **({"future": ahead} if ahead else {})}
        if dict(cells) != want:
            fails.append(f"calendar cells {dict(cells)}, expected {want}")
        if seen["streak"] != "16-day streak" or seen["freezes"] != "1 freeze saved · next one after 5 more days in a row":
            fails.append(f"seeded streak: {seen}")
        due_tile = page.locator(".tile", has_text="Reviews due").inner_text()
        if due_tile != f"Reviews due\n3\n{backlog - 3} more spread over the next days":
            fails.append(f"reviews due with {backlog} overdue and 3 left under the cap: {due_tile!r}")

        page.locator(".plan input[name=time]").fill("07:15")
        page.locator(".plan input[name=cue]").fill("Before breakfast")
        page.get_by_role("button", name="Save plan").click()
        expect(page.get_by_text("If it's 07:15 before breakfast, I study.")).to_be_visible()
        first = plistlib.loads(reminder.plist_path(agents).read_bytes())
        page.get_by_role("button", name="Edit").click()
        page.get_by_role("button", name="Cancel").click()
        expect(page.get_by_text("If it's 07:15 before breakfast, I study.")).to_be_visible()
        page.get_by_role("button", name="Edit").click()
        page.locator(".plan input[name=time]").fill("19:30")
        page.locator(".plan input[name=cue]").fill("After dinner at my desk")
        shot(page, "33-plan-form")
        page.get_by_role("button", name="Save plan").click()
        expect(page.get_by_text("If it's 19:30 after dinner at my desk, I study.")).to_be_visible()
        plist = plistlib.loads(reminder.plist_path(agents).read_bytes())
        page.reload()
        expect(page.get_by_text("If it's 19:30 after dinner at my desk, I study.")).to_be_visible()
        expect(page.get_by_text("A reminder shows at 19:30 on this Mac if today's minimum isn't met.")).to_be_visible()
        plan_text = page.locator(".plan").inner_text()
        if "null" in plan_text or "undefined" in plan_text:
            fails.append(f"plan box: {plan_text!r}")
        page.wait_for_timeout(300)
        shot(page, "34-home-momentum-light", full=True)
        page.emulate_media(color_scheme="dark")
        page.wait_for_timeout(200)
        shot(page, "35-home-momentum-dark", full=True)
        page.emulate_media(color_scheme="light")
        if first["StartCalendarInterval"] != {"Hour": 7, "Minute": 15}:
            fails.append(f"first plan plist: {first['StartCalendarInterval']}")
        if plist["StartCalendarInterval"] != {"Hour": 19, "Minute": 30} or plist["Label"] != reminder.LABEL \
                or plist["ProgramArguments"][1:] != ["-m", "app.reminder", "--notify", "--db", str(db2)] or plist["WorkingDirectory"] != str(ROOT):
            fails.append(f"reminder plist: {plist}")
        if sorted(p.name for p in agents.iterdir()) != [f"{reminder.LABEL}.plist"]:
            fails.append(f"LaunchAgents folder holds {sorted(p.name for p in agents.iterdir())}")
        lint = subprocess.run(["plutil", "-lint", str(reminder.plist_path(agents))], capture_output=True, text=True)
        if lint.returncode:
            fails.append(f"plutil: {lint.stdout}")
        met = subprocess.run([sys.executable, "-m", "app.reminder", "--notify", "--print", "--db", str(db2)], cwd=ROOT, capture_output=True, text=True)
        unmet_db = home / "unmet.db"
        con = db.connect(unmet_db)
        with con:
            db.set_profile(con, "plan", {"cue": "After dinner at my desk", "time": "19:30"})
        con.close()
        unmet = subprocess.run([sys.executable, "-m", "app.reminder", "--notify", "--print", "--db", str(unmet_db)], cwd=ROOT, capture_output=True, text=True)
        if met.stdout.strip() != "no reminder: no plan, or today's minimum is met":
            fails.append(f"reminder check with today met: {met.stdout!r} {met.stderr[-300:]}")
        if unmet.stdout.strip() != "notify: After dinner at my desk: time for Chinese (http://localhost:8766)":
            fails.append(f"reminder check with today unmet: {unmet.stdout!r} {unmet.stderr[-300:]}")

        page.get_by_role("link", name="5-minute session").click()
        expect(page.get_by_role("heading", name="Cards · 5 minutes")).to_be_visible()
        page.keyboard.press("Enter")
        rated, capped = 0, page.get_by_text("Today's reviews are done")
        for _ in until(page, capped.is_visible, "review-cap", seconds=60):
            if page.locator(".card.front").is_visible():
                page.keyboard.press("Space")
            elif page.locator(".card.back").is_visible():
                with page.expect_response("**/api/cards/review"):
                    page.keyboard.press("3")
                rated += 1
            page.wait_for_timeout(100)
        shot(page, "36-cards-review-cap")
        cap_text = page.locator(".card p").first.inner_text()
        page.keyboard.press("Enter")
        expect(page.get_by_role("heading", name="Session complete")).to_be_visible()
        con = sqlite3.connect(db2)
        after = sum(momentum.study_day(datetime.fromisoformat(ts), m["day_starts_hour"]) == today for (ts,) in
                    con.execute("SELECT ts FROM events WHERE activity='card' AND item!='block_end'"))
        con.close()
        if rated != 3 or after != cap:
            fails.append(f"review cap {cap}: rated {rated} in the capped session, {after} reviews today")
        if cap_text != f"Today's reviews are done; {backlog - 3} more are spread over the next days.":
            fails.append(f"cap message with {backlog} overdue: {cap_text!r}")
    finally:
        ctx.close()
        server.terminate()
    return fails + errors, {"calendar": dict(cells), "home": seen, "plist": {k: plist[k] for k in ("StartCalendarInterval", "ProgramArguments")},
                            "reminder_met": met.stdout.strip(), "reminder_unmet": unmet.stdout.strip(),
                            "backlog": backlog, "reviews_due_tile": due_tile, "cap": cap, "rated_before_cap": rated,
                            "reviews_today": after, "cap_message": cap_text}


def graph_journey(page):
    """Graph page: open by URL, search by pinyin, toggle depth, click a node to recenter. Returns failures."""
    fails = []
    page.goto(URL + "#/graph/" + "学")
    expect(page.get_by_role("img", name="Graph of 学")).to_be_visible()
    n1 = page.locator(".gnode").count()
    shot(page, "29-graph-xue")
    page.get_by_role("searchbox", name="Find a word").fill("qing")
    expect(page.locator(".graph-result").first).to_be_visible()
    page.locator(".graph-result").filter(has=page.locator(".hanzi", has_text=re.compile("^请$"))).click()
    expect(page.get_by_role("img", name="Graph of 请")).to_be_visible()
    page.get_by_role("button", name="2 steps").click()
    expect(page.get_by_role("button", name="2 steps")).to_have_class(re.compile("on"))
    n2 = page.locator(".gnode").count()
    shot(page, "30-graph-qing-2-steps")
    page.locator(".chip", has_text="情").first.click()
    expect(page.get_by_role("img", name="Graph of 情")).to_be_visible()
    page.emulate_media(color_scheme="dark")
    page.wait_for_timeout(200)
    shot(page, "31-graph-dark")
    page.emulate_media(color_scheme="light")
    labels = page.locator(".glabel").count()
    if n1 < 10:
        fails.append(f"graph of 学 drew only {n1} nodes")
    if not 10 <= n2 <= 60:
        fails.append(f"2-step graph of 请 drew {n2} nodes (expected 10-60)")
    if labels != page.locator(".gnode").count():
        fails.append("a graph node has no label")
    return fails, {"xue_nodes": n1, "qing_2step_nodes": n2}


def resume_journey(browser, page, db_path):
    """Leave a session three ways (nav to Home, reload, close the tab) and check it resumes: same session id,
    same block, timer continuing (block_ms never resets), running tally kept. Real-time timers so nothing expires."""
    url = f"http://localhost:{PORT}/?timescale=1"
    session_link = lambda p: p.locator("a.button.primary[href='#/session']")

    def answer(p, n):
        for _ in range(n):
            expect(p.locator(".listen.audio")).to_be_visible(timeout=20000)
            p.keyboard.press("y")
            expect(p.locator(".listen.text")).to_be_visible()
            p.keyboard.press("Enter")
            p.wait_for_timeout(300)

    page.goto(url + "#/home")
    expect(session_link(page)).to_have_text(re.compile(r"Start \d+-minute session"))
    session_link(page).click()
    expect(page.get_by_role("heading", name="Cards · 8 minutes")).to_be_visible()
    page.keyboard.press("Enter")
    page.get_by_role("button", name="Skip block →").click()
    expect(page.get_by_role("heading", name="Listen & read · 12 minutes")).to_be_visible()
    page.keyboard.press("Enter")
    answer(page, 2)
    page.wait_for_timeout(1500)

    page.locator("a[data-route=home]").click()  # 1. click away
    expect(session_link(page)).to_have_text("Resume session · Listen & read")
    shot(page, "26-home-resume-offered")
    session_link(page).click()
    expect(page.get_by_text("Resuming where you left off")).to_be_visible()
    shot(page, "27-resume-note")
    page.keyboard.press("Enter")
    answer(page, 1)

    page.reload()  # 2. reload
    expect(page.get_by_text("Resuming where you left off")).to_be_visible()
    page.close()  # 3. close the tab, open a new one
    ctx2 = browser.new_context(viewport={"width": 1100, "height": 900}, permissions=["microphone"])
    p2 = ctx2.new_page()
    p2.goto(url + "#/session")
    expect(p2.get_by_text("Resuming where you left off")).to_be_visible()
    p2.keyboard.press("Enter")
    answer(p2, 1)
    timer_text = p2.locator(".timer").inner_text()
    p2.get_by_role("button", name="Skip block →").click()
    expect(p2.get_by_role("heading", name="Speak · 10 minutes")).to_be_visible()
    p2.keyboard.press("Enter")
    p2.get_by_role("button", name="Skip block →").click()
    expect(p2.get_by_role("heading", name="Session complete")).to_be_visible()
    shot(p2, "28-resumed-session-complete")
    listening_tile = p2.locator(".tile", has_text="Listening").inner_text()

    con = __import__("sqlite3").connect(db_path)
    sid = con.execute("SELECT session_id FROM events WHERE session_id LIKE 'S%' ORDER BY id DESC LIMIT 1").fetchone()[0]
    listens = [json.loads(r[0])["block_ms"] for r in con.execute(
        "SELECT result_json FROM events WHERE session_id=? AND activity='listen' AND item!='block_end' ORDER BY id", (sid,))]
    fails = []
    if len(listens) != 4:
        fails.append(f"resume: expected 4 listen answers in one session {sid}, got {len(listens)}")
    # The 1.5 s idle before clicking away must carry into the resumed timer: a reset would restart near 0.
    if len(listens) == 4 and (listens != sorted(listens) or listens[2] < listens[1] + 1400):
        fails.append(f"resume: listen block_ms reset or lost the time before leaving: {listens}")
    if "4" not in listening_tile.split():
        fails.append(f"resume: session summary lost the earlier answers: {listening_tile!r}")
    ctx2.close()
    return fails, {"session": sid, "listen_block_ms": listens, "timer_at_end": timer_text, "listening_tile": listening_tile}


def check_db(db_path, reading):
    con = __import__("sqlite3").connect(db_path)
    con.row_factory = __import__("sqlite3").Row
    ev = [dict(r, result=json.loads(r["result_json"])) for r in con.execute("SELECT * FROM events ORDER BY id")]
    by = Counter(e["activity"] for e in ev)
    failures = []
    need = ["placement_vocab", "placement_listen", "placement_tone", "placement_read", "card", "listen", "read_lookup", "shadow"]
    for a in need:
        if not by[a]:
            failures.append(f"no {a} events")
    session_evs = [e for e in ev if e["activity"] in ("card", "listen", "read_lookup", "shadow")]
    ends = {e["result"]["block"]: e["result"]["reason"] for e in session_evs if e["item"] == "block_end"}
    if sorted(ends) != ["cards", "listen", "speak"]:
        failures.append(f"block_end markers: {ends}")
    if any(e["result"].get("block_ms") is None for e in session_evs):
        failures.append("session event without block_ms")
    cards = con.execute("SELECT COUNT(*) FROM cards WHERE introduced_at IS NOT NULL").fetchone()[0]
    queued = con.execute("SELECT COUNT(*) FROM cards WHERE introduced_at IS NULL").fetchone()[0]
    known = con.execute("SELECT COUNT(*) FROM known").fetchone()[0]
    if not cards or not queued or not known:
        failures.append(f"cards/queued/known = {cards}/{queued}/{known}")
    reviewed = [e for e in ev if e["activity"] == "card" and e["item"] != "block_end"]
    if any("retrievability" not in e["result"] or "after" not in e["result"] for e in reviewed):
        failures.append("card event missing FSRS fields")
    lookups = [e for e in ev if e["activity"] == "read_lookup" and e["result"]["hsk"]]
    for e in lookups:
        row = con.execute("SELECT introduced_at FROM cards WHERE word=?", (e["item"],)).fetchone()
        if not row or not row[0]:
            failures.append(f"looked-up HSK word {e['item']} is not an introduced card")
    wavs = []
    for e in (e for e in ev if e["activity"] == "shadow" and e["item"] != "block_end" and e["result"]["wav"]):
        p = Path(e["result"]["wav"])
        if not p.exists():
            failures.append(f"missing {p}")
            continue
        with wave.open(str(p)) as wf:
            fmt = (wf.getnchannels(), wf.getframerate(), wf.getsampwidth())
            x = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype(float)
        rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
        wavs.append({"file": p.name, "format": fmt, "seconds": round(len(x) / 16000, 2), "rms": round(rms, 1),
                     "transcript": e["result"]["transcript"], "error": e["result"]["error"], "score": e["result"]["score"]})
        if fmt != (1, 16000, 2) or len(x) < 16000 or rms < 50:
            failures.append(f"bad wav {p.name}: {fmt} {len(x)} samples rms {rms:.0f}")
    if not wavs:
        failures.append("no WAV saved")
    if not any(w["error"] == "abandoned" for w in wavs):
        failures.append("attempt cut short by Next was not logged with its audio")
    prof = json.loads(con.execute("SELECT value_json FROM profile WHERE key='placement'").fetchone()[0])
    return failures, {"events": dict(by), "block_ends": ends, "introduced_cards": cards, "queued": queued, "known": known,
                      "placement_levels": prof["levels"], "false_alarm": prof["false_alarm"], "spot": prof["spot"],
                      "reading": prof["read"], "wavs": wavs}


def main():
    SHOTS.mkdir(exist_ok=True)
    for old in SHOTS.glob("*.png"):
        old.unlink()
    tmp = Path(tempfile.mkdtemp(prefix="hsk4-e2e-"))
    real_agent = (REAL_AGENT.exists(), REAL_AGENT.exists() and REAL_AGENT.stat().st_mtime)
    db_path = tmp / "study.db"
    server = subprocess.Popen([sys.executable, "-m", "app.server", "--db", str(db_path), "--port", str(PORT)],
                              cwd=ROOT, stdout=open(tmp / "server.log", "w"), stderr=subprocess.STDOUT)
    failures, errors, audio, tts = [], [], [], []
    try:
        wait_port(PORT)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=[
                "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
            ctx = browser.new_context(viewport={"width": 1100, "height": 900}, permissions=["microphone"])
            ctx.add_init_script(TRACK_STREAMS)
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
            page.on("response", lambda r: audio.append(r.status) if "/audio/" in r.url else None)
            page.on("response", lambda r: tts.append(r.status) if "/tts?" in r.url else None)
            print("placement")
            _, reading = placement(page)
            print("quick session")
            quick_fail, quick = quick_session(page)
            failures += quick_fail
            print("session")
            s = session(page)
            merge = page.evaluate("import('/js/speech.js').then(m => [m.mergeFinal('你好', '你好吗'), m.mergeFinal('你好', '，再见')])")
            print("reading check")
            with page.expect_response("**/api/reading/start") as r:
                page.goto(URL + "#/reading")
            reading_check(page, r.value.json())
            expect(page.get_by_role("heading", name="Reading check saved")).to_be_visible()
            print("stats")
            page.goto(URL + "#/stats")
            expect(page.get_by_role("heading", name="Progress")).to_be_visible()
            streak_tile = page.locator(".tile", has_text="Streak").inner_text()
            share_tile = page.locator(".tile", has_text="Minimum met, last 7 days").inner_text()
            page.wait_for_timeout(500)
            page.locator("figure .viz").first.hover(position={"x": 600, "y": 100})
            shot(page, "24-stats", full=True)
            page.goto(URL + "#/home")
            expect(page.get_by_role("heading", name="Today")).to_be_visible()
            shot(page, "25-home-after-session")
            print("graph")
            graph_fail, graph = graph_journey(page)
            failures += graph_fail
            print("resume")
            resume_fail, resume = resume_journey(browser, page, db_path)
            failures += resume_fail
            print("history, plan and review cap")
            history_fail, history = history_journey(browser, db_path, tmp)
            failures += history_fail
            browser.close()
        if not s["released_after_attempt"]:
            failures.append("mic tracks still live after an attempt finished")
        if not s["released_after_next"]:
            failures.append("mic tracks still live after Next during recording")
        if merge != ["你好吗", "你好，再见"]:
            failures.append(f"mergeFinal gave {merge}")
        if s["scripted"]["score"] is None or s["scripted"]["score"] >= 1:
            failures.append(f"scripted recognizer not scored as a partial match: {s['scripted']}")
        db_fail, summary = check_db(db_path, reading)
        failures += db_fail
        weekly = subprocess.run([sys.executable, str(ROOT / "tools" / "weekly.py"), "--db", str(db_path)],
                                capture_output=True, text=True, cwd=ROOT)
        if weekly.returncode or "## Per day" not in weekly.stdout:
            failures.append(f"weekly.py failed: {weekly.stderr[-500:]}")
        if "**Momentum** 1-day streak, 0 freezes saved. **Minimum met** 1 of 1 days in the last 7 (100%)" not in weekly.stdout:
            failures.append("weekly.py momentum line missing or wrong")
        if not streak_tile.startswith("Streak\n1 day") or not share_tile.startswith("Minimum met, last 7 days\n1 of 1 days"):
            failures.append(f"stats momentum tiles: {streak_tile!r} {share_tile!r}")
        if REAL_AGENT.exists() != real_agent[0] or (REAL_AGENT.exists() and REAL_AGENT.stat().st_mtime != real_agent[1]):
            failures.append(f"{REAL_AGENT} changed during the run")
        if not tts or tts.count(200) < 0.9 * len(tts):
            failures.append(f"server TTS not used or failing: {dict(Counter(tts))}")
        voices = Counter(json.loads(r[0]).get("voice") for r in __import__("sqlite3").connect(db_path).execute(
            "SELECT result_json FROM events WHERE activity IN ('card','placement_tone') AND item!='block_end'"))
        # Every logged source must be the server voice; None means the item was answered before audio started.
        if set(voices) - {"server-tts", None} or voices.get("server-tts", 0) < 20:
            failures.append(f"card/tone audio not from server TTS: {dict(voices)}")
        bad_gateway = [e for e in errors if "status of 502" in e]
        if len(bad_gateway) > audio.count(502):
            failures.append("502 responses outside the native-audio proxy")
        failures += [e for e in errors if e not in bad_gateway]
        print(json.dumps({"native_audio_responses": dict(Counter(audio)), "tts_responses": dict(Counter(tts)), "card_tone_voices": dict(voices),
                          "session": {k: v for k, v in s.items() if k != "scripted"}, "scripted_score": s["scripted"]["score"],
                          "quick": quick, "history": history, "stats_tiles": [streak_tile, share_tile],
                          "resume": resume, "graph": graph,
                          "db": summary}, ensure_ascii=False, indent=1))
        print(weekly.stdout)
    finally:
        server.terminate()
    print(f"database and recordings kept in {tmp}")
    if failures:
        print("FAIL\n  " + "\n  ".join(failures))
        sys.exit(1)
    print("PASS")


if __name__ == "__main__":
    main()
