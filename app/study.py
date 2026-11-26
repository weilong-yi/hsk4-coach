"""Daily session logic: FSRS cards, listen-and-read bundles, lookups, and shadowing attempts."""
import base64, io, re, wave, zlib
from datetime import datetime, timedelta, timezone

from fsrs import Card, Rating, Scheduler
from pypinyin import Style, lazy_pinyin

from . import db
from .corpus import han

SCHED = Scheduler()
PREVIEW = Scheduler(enable_fuzzing=False)
RATINGS = {1: Rating.Again, 2: Rating.Hard, 3: Rating.Good, 4: Rating.Easy}
YOUNG_DAYS = 21
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def new_card(word, due=None):
    return Card(card_id=zlib.crc32(word.encode()), due=due)


def introduced(con):
    return [(r["word"], Card.from_json(r["fsrs_json"]), r["introduced_at"])
            for r in con.execute("SELECT * FROM cards WHERE introduced_at IS NOT NULL")]


def known_set(con):
    return {r[0] for r in con.execute("SELECT word FROM known UNION SELECT word FROM cards WHERE introduced_at IS NOT NULL")}


def today():
    return db.now().date().isoformat()


def interval(td):
    s = td.total_seconds()
    for unit, size in (("mo", 30 * 86400), ("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{s / size:.0f}{unit}"
    return "<1m"


def sentence_payload(c, s):
    return {**{k: s[k] for k in ("id", "zh", "en", "tok", "audio", "lvl")}, "nums": [c.lookup(t)["num"] for t in s["tok"]]}


def card_payload(con, c, word, card, is_new):
    utc = datetime.now(timezone.utc)
    w, ex = c.words[word], c.example(word, known_set(con))
    return {"w": word, "num": w["num"], "en": w["en"], "alt": w.get("alt", []), "lvl": w["lvl"], "new": is_new, "state": card.state.name,
            "intervals": {r: interval(PREVIEW.review_card(card, rating, utc)[0].due - utc) for r, rating in RATINGS.items()},
            "example": ex and sentence_payload(c, ex)}


def queue_counts(con, cfg):
    utc, intro = datetime.now(timezone.utc), introduced(con)
    new_today = sum(i[:10] == today() for _, _, i in intro)
    queued = con.execute("SELECT COUNT(*) FROM cards WHERE introduced_at IS NULL").fetchone()[0]
    return {"due": sum(card.due <= utc for _, card, _ in intro),
            "new": min(queued, max(0, cfg["new_cards_per_day"] - new_today)), "queued": queued}


def next_card(con, c, cfg, exclude=None):
    """Due cards (oldest first), then new cards up to the daily limit (by frequency rank),
    then learning cards due within the learn-ahead window."""
    utc, intro = datetime.now(timezone.utc), introduced(con)
    due = sorted((card.due, w, card) for w, card, _ in intro if card.due <= utc and w != exclude)
    if due:
        return card_payload(con, c, due[0][1], due[0][2], False)
    if sum(i[:10] == today() for _, _, i in intro) < cfg["new_cards_per_day"]:
        queued = [r[0] for r in con.execute("SELECT word FROM cards WHERE introduced_at IS NULL")]
        if queued:
            word = min(queued, key=lambda w: c.words[w]["rank"])
            return card_payload(con, c, word, new_card(word, due=utc), True)
    ahead = sorted((card.due, w, card) for w, card, _ in intro
                   if card.due <= utc + timedelta(minutes=cfg["learn_ahead_min"]))
    return card_payload(con, c, ahead[0][1], ahead[0][2], False) if ahead else None


def snapshot(card):
    return {"state": card.state.name, "step": card.step, "stability": card.stability, "difficulty": card.difficulty,
            "due": card.due.isoformat(), "last_review": card.last_review and card.last_review.isoformat()}


def review(con, session_id, word, rating, ms, extra):
    row = con.execute("SELECT fsrs_json, introduced_at FROM cards WHERE word=?", (word,)).fetchone()
    if row is None:
        raise KeyError(word)
    utc = datetime.now(timezone.utc)
    is_new = row["introduced_at"] is None
    card = new_card(word, due=utc) if is_new else Card.from_json(row["fsrs_json"])
    result = {**extra, "rating": rating, "new": is_new,
              "retrievability": SCHED.get_card_retrievability(card, utc),
              "elapsed_days": card.last_review and (utc - card.last_review).total_seconds() / 86400,
              "before": snapshot(card)}
    after, _ = SCHED.review_card(card, RATINGS[rating], utc, review_duration=ms)
    result["after"] = snapshot(after)
    with con:
        con.execute("UPDATE cards SET fsrs_json=?, introduced_at=COALESCE(introduced_at, ?) WHERE word=?",
                    (after.to_json(), db.now().isoformat(timespec="milliseconds"), word))
        db.log_event(con, session_id, "card", word, result, ms)
    return {"due": after.due.isoformat(), "state": after.state.name}


def focus_words(con):
    """Today's new cards weigh 3, other young cards 1: the bundle prefers sentences that reuse them."""
    out = {}
    for w, card, intro in introduced(con):
        if intro[:10] == today():
            out[w] = 3
        elif card.stability is None or card.stability < YOUNG_DAYS:
            out[w] = 1
    return out


def listen_bundle(con, c, cfg, rng, exclude=()):
    cutoff = (db.now() - timedelta(days=7)).isoformat()
    recent = {int(r[0]) for r in con.execute("SELECT item FROM events WHERE activity='listen' AND item!='block_end' AND ts>=?", (cutoff,))}
    known, focus = known_set(con), focus_words(con)
    sents = c.bundle(known, rng, share=cfg["bundle_known_share"], max_sents=cfg["bundle_sentences"],
                     focus=focus, exclude=recent | set(exclude))
    return [{**sentence_payload(c, s),
             "marks": {t: "new" if t not in known else "focus" for t in s["tok"] if t not in known or focus.get(t) == 3}}
            for s in sents]


def lookup(con, c, session_id, word, ms, extra):
    info = c.lookup(word)
    added = was_known = False
    with con:
        if word in c.words:
            row = con.execute("SELECT introduced_at FROM cards WHERE word=?", (word,)).fetchone()
            was_known = con.execute("SELECT 1 FROM known WHERE word=?", (word,)).fetchone() is not None
            if row is None or row[0] is None:
                con.execute("INSERT OR REPLACE INTO cards(word, fsrs_json, introduced_at) VALUES (?,?,?)",
                            (word, new_card(word).to_json(), db.now().isoformat(timespec="milliseconds")))
                added = True
            con.execute("DELETE FROM known WHERE word=?", (word,))
        db.log_event(con, session_id, "read_lookup", word,
                     {**extra, "hsk": word in c.words, "lvl": info["lvl"], "added": added, "was_known": was_known}, ms)
    return {**info, "added": added}


def shadow_items(con, c, cfg, session_id, rng):
    seen = list(dict.fromkeys(e["item"] for e in db.events(con, session_id, "listen") if e["item"] != "block_end"))
    pool = [c.by_id[int(i)] for i in seen if int(i) in c.by_id]
    if len(pool) < cfg["shadow_sentences"]:
        pool += [c.by_id[s["id"]] for s in listen_bundle(con, c, cfg, rng, exclude={s["id"] for s in pool})]
    pool.sort(key=lambda s: (s["audio"] is None, abs(len(han(s["zh"])) - 10)))
    return [sentence_payload(c, s) for s in pool[:cfg["shadow_sentences"]]]


def match(target, transcript):
    """Which target characters the recognizer understood: LCS alignment over toned pinyin syllables.

    Comparing syllables, not characters, counts a homophone (她 heard as 他, both ta1) as understood.
    This says the speech was understood; it does not judge tones (data/exp_speech.md E1a).
    """
    chars = han(target)
    syl = lambda s: lazy_pinyin(s, style=Style.TONE3, neutral_tone_with_five=True)
    t, h = syl(chars), syl(han(transcript))
    n, m = len(t), len(h)
    lcs = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            lcs[i][j] = lcs[i + 1][j + 1] + 1 if t[i] == h[j] else max(lcs[i + 1][j], lcs[i][j + 1])
    marks, i, j = [], 0, 0
    while i < n:
        if j < m and t[i] == h[j]:
            marks.append(True)
            i, j = i + 1, j + 1
        elif j < m and lcs[i][j + 1] >= lcs[i + 1][j]:
            j += 1
        else:
            marks.append(False)
            i += 1
    return {"chars": chars, "marks": marks, "score": round(sum(marks) / n, 3) if n else None}


def save_shadow(con, c, rec_dir, p):
    session_id, sid, attempt = p["session_id"], int(p["sentence_id"]), int(p["attempt"])
    if not SESSION_ID.match(session_id) or sid not in c.by_id:
        raise ValueError("bad session or sentence")
    path, frames = None, 0
    if p.get("wav_b64"):
        audio = base64.b64decode(p["wav_b64"])
        with wave.open(io.BytesIO(audio)) as wf:
            fmt, frames = (wf.getnchannels(), wf.getframerate(), wf.getsampwidth()), wf.getnframes()
        if fmt != (1, 16000, 2):
            raise ValueError(f"expected 16 kHz mono 16-bit WAV, got {fmt}")
        path = rec_dir / session_id / f"{sid}-{attempt}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
    transcript = p.get("transcript") or ""
    scored = match(c.by_id[sid]["zh"], transcript) if transcript else {"chars": han(c.by_id[sid]["zh"]), "marks": None, "score": None}
    result = {**p.get("extra", {}), "attempt": attempt, "transcript": transcript, "error": p.get("error"),
              "score": scored["score"], "marks": scored["marks"], "wav": path and str(path), "duration_s": round(frames / 16000, 3),
              "native": c.by_id[sid]["audio"] is not None}
    with con:
        db.log_event(con, session_id, "shadow", sid, result, p.get("ms"))
    return {**scored, "wav": result["wav"], "duration_s": result["duration_s"]}
