#!/usr/bin/env python3
"""Drive a disposable HSK 4 Coach instance and keep the evidence.

    .venv/bin/python .claude/skills/verify-hsk4-coach/verify.py launch            # prints RUN id
    .venv/bin/python .claude/skills/verify-hsk4-coach/verify.py doctor   RUN
    .venv/bin/python .claude/skills/verify-hsk4-coach/verify.py drive    RUN placement|session|stats
    .venv/bin/python .claude/skills/verify-hsk4-coach/verify.py cleanup  RUN

Evidence: verify-runs/RUN/ (screenshots, *.json proofs, server.log, and at cleanup study.db + recordings/).
Scratch:  a temp dir holding the live DB; removed at cleanup after it is copied into the evidence dir.
"""
import json, os, re, shutil, signal, socket, sqlite3, subprocess, sys, tempfile, time, urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "verify-runs"
PY = ROOT / ".venv" / "bin" / "python"


def run_dir(run):
    d = RUNS / run
    if not (d / "run.json").exists():
        sys.exit(f"no run {run} (expected {d}/run.json)")
    return d, json.loads((d / "run.json").read_text())


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, json.loads(r.read())


def launch():
    for need in ("data/words.json", "data/sentences.json", "data/gloss.json"):
        if not (ROOT / need).exists():
            print(f"{need} missing; building corpus (needs data/raw, ~25 s)")
            subprocess.run([PY, "-W", "ignore", "tools/build_corpus.py"], cwd=ROOT, check=True)
            break
    run = datetime.now().strftime("%Y%m%d-%H%M%S")
    ev = RUNS / run; ev.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix=f"hsk4-verify-{run}-"))
    port, db = free_port(), scratch / "study.db"
    log = ev / "server.log"
    proc = subprocess.Popen([PY, "-m", "app.server", "--db", str(db), "--port", str(port)], cwd=ROOT,
                            stdout=open(log, "w"), stderr=subprocess.STDOUT, start_new_session=True)
    info = {"run": run, "pid": proc.pid, "port": port, "db": str(db), "scratch": str(scratch),
            "url": f"http://localhost:{port}/", "git": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                                                       capture_output=True, text=True).stdout.strip()}
    (ev / "run.json").write_text(json.dumps(info, indent=2))
    t0 = time.time()
    while time.time() - t0 < 30:
        if proc.poll() is not None:
            sys.exit(f"server exited early, see {log}")
        if "HSK 4 coach on" in log.read_text():
            try:
                if get(port, "/api/state")[0] == 200:
                    print(f"RUN={run}\nready at {info['url']}  evidence {ev}")
                    return
            except OSError:
                pass
        time.sleep(0.3)
    sys.exit(f"not ready after 30 s, see {log}")


def doctor(run):
    ev, info = run_dir(run)
    checks = []
    alive = True
    try:
        os.kill(info["pid"], 0)
    except OSError:
        alive = False
    checks.append(("process alive", alive, f"pid {info['pid']}"))
    owner = subprocess.run(["lsof", "-t", "-iTCP:%d" % info["port"], "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
    checks.append(("port owned by this run", str(info["pid"]) in owner, f"port {info['port']} listeners {owner}"))
    m = re.search(r"HSK 4 coach on (\S+)\s+\(db (.+)\)", (ev / "server.log").read_text())
    checks.append(("server uses this run's DB", bool(m) and m.group(2) == info["db"], m.group(2) if m else "no ready line"))
    try:
        code, state = get(info["port"], "/api/state")
        checks.append(("/api/state", code == 200, f"placement={'set' if state['placement'] else 'none'} known={state['known']} queue={state['queue']}"))
    except OSError as e:
        checks.append(("/api/state", False, str(e)))
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    checks.append(("build matches launch", head == info["git"], f"launched {info['git']} now {head}"))
    for name, ok, detail in checks:
        print(f"{'OK  ' if ok else 'FAIL'} {name}: {detail}")
    sys.exit(0 if all(ok for _, ok, _ in checks) else 1)


def db_counts(db):
    con = sqlite3.connect(db)
    out = {"events": dict(con.execute("SELECT activity, COUNT(*) FROM events WHERE item != 'block_end' GROUP BY activity").fetchall()),
           "cards": con.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
           "known": con.execute("SELECT COUNT(*) FROM known").fetchone()[0]}
    row = con.execute("SELECT value_json FROM profile WHERE key='placement'").fetchone()
    out["placement"] = json.loads(row[0]) if row else None
    return out


def drive(run, feature):
    ev, info = run_dir(run)
    sys.path.insert(0, str(ROOT))
    import app.e2e as e2e  # reuse the journeys; redirect their screenshots and URL to this run
    from playwright.sync_api import sync_playwright
    shots = ev / feature; shots.mkdir(exist_ok=True)
    e2e.SHOTS = shots
    e2e.URL = f"http://localhost:{info['port']}/?timescale={e2e.TIMESCALE}"
    before = db_counts(info["db"])
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True, args=[
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(viewport={"width": 1100, "height": 900}, permissions=["microphone"])
        ctx.add_init_script(e2e.TRACK_STREAMS)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        try:
            if feature == "placement":
                if before["placement"]:
                    sys.exit("placement already done in this run; launch a fresh run")
                e2e.placement(page)
            elif feature == "session":
                if not before["placement"]:
                    sys.exit("session needs a placement first: drive RUN placement")
                page.goto(e2e.URL + "#/home")
                e2e.session(page)
            elif feature == "stats":
                page.goto(e2e.URL + "#/stats")
                page.wait_for_load_state("networkidle")
                e2e.shot(page, "stats", full=True)
            else:
                sys.exit("feature must be placement, session or stats")
        except Exception as e:
            e2e.shot(page, "failure")
            errors.append(f"{type(e).__name__}: {e}")
        b.close()
    after = db_counts(info["db"])
    proof = {"feature": feature, "run": run, "url": e2e.URL, "errors": errors, "before": before, "after": after,
             "screenshots": sorted(x.name for x in shots.glob("*.png"))}
    (ev / f"{feature}.json").write_text(json.dumps(proof, indent=2, ensure_ascii=False))
    print(json.dumps({k: proof[k] for k in ("feature", "errors", "screenshots")}, ensure_ascii=False, indent=1))
    print("events added:", {k: after["events"].get(k, 0) - before["events"].get(k, 0) for k in after["events"]})
    print(f"proof: {ev / (feature + '.json')}")
    sys.exit(1 if errors else 0)


def cleanup(run):
    ev, info = run_dir(run)
    try:
        cmd = subprocess.run(["ps", "-o", "command=", "-p", str(info["pid"])], capture_output=True, text=True).stdout
        if "app.server" in cmd and str(info["port"]) in cmd:
            os.killpg(info["pid"], signal.SIGTERM)
            print(f"stopped pid {info['pid']}")
        else:
            print(f"pid {info['pid']} is not this run's server; not killing")
    except ProcessLookupError:
        pass
    scratch = Path(info["scratch"])
    if scratch.exists():
        shutil.copy2(scratch / "study.db", ev / "study.db") if (scratch / "study.db").exists() else None
        if (scratch / "recordings").exists():
            shutil.copytree(scratch / "recordings", ev / "recordings", dirs_exist_ok=True)
        shutil.rmtree(scratch)
        print(f"removed scratch {scratch}; DB and recordings kept in {ev}")
    print(f"evidence kept: {ev}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["launch"]:
        launch()
    elif len(a) == 2 and a[0] in ("doctor", "cleanup"):
        {"doctor": doctor, "cleanup": cleanup}[a[0]](a[1])
    elif len(a) == 3 and a[0] == "drive":
        drive(a[1], a[2])
    else:
        sys.exit(__doc__)
