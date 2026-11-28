"""Local HSK 4 coach: stdlib HTTP server for app/static/ plus a JSON API over data/study.db.

    .venv/bin/python -m app.server            # http://localhost:8766
    .venv/bin/python -m app.server --db /tmp/x.db --port 8767 --launch-agents /tmp/agents
"""
import argparse, json, mimetypes, urllib.parse, random, re, secrets, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import corpus, db, graph, momentum, obsidian, placement, reminder, stats, study, tts

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
AUDIO_CACHE = ROOT / "data" / "audio_native"
CLIENT_ACTIVITIES = {"placement_vocab", "placement_listen", "placement_tone", "placement_read", "listen"}
BLOCK_ACTIVITY = {"cards": "card", "listen": "listen", "speak": "shadow"}
PLAN_TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


class App:
    def __init__(self, db_path, config_path, launch_agents=None):
        self.db_path = Path(db_path)
        # Only the learner's real database syncs the Obsidian vault and installs the reminder; e2e and verify runs
        # use throwaway DBs. --launch-agents points the reminder at a test folder and never calls launchctl.
        self.real_db = self.db_path.resolve() == (ROOT / "data" / "study.db").resolve()
        self.launch_agents = Path(launch_agents) if launch_agents else None
        self.reminder_dir = self.launch_agents or (reminder.AGENTS if self.real_db else None)
        self.rec_dir = self.db_path.parent / "recordings"
        self.cfg = json.loads(Path(config_path).read_text())
        self.c = corpus.load()
        self.graph = graph.Graph(self.c.words, graph.load_mmah())
        self.rng = random.Random()
        db.connect(self.db_path).close()

    def con(self):
        return db.connect(self.db_path)

    def new_session(self, prefix):
        return f"{prefix}{db.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"

    # ---- API handlers: (app, body) -> JSON ----

    def state(self, con, _):
        return {"placement": db.get_profile(con, "placement"), "config": self.cfg,
                "queue": study.queue_counts(con, self.cfg), "known": len(study.known_set(con)),
                "resume": study.resume_state(con, self.cfg), "momentum": self.momentum_state(con, None)}

    def momentum_state(self, con, _):
        out = momentum.summary(momentum.load(con), self.cfg["momentum"], db.now())
        return {**out, "plan": db.get_profile(con, "plan"),
                "reminder": bool(self.reminder_dir and reminder.plist_path(self.reminder_dir).exists())}

    def plan(self, con, body):
        cue, at = str(body.get("cue", "")).strip(), str(body.get("time", ""))
        if not 0 < len(cue) <= 80 or not PLAN_TIME.fullmatch(at):
            raise ValueError("a plan needs a cue of 1-80 characters and a time as HH:MM")
        plan = {"cue": cue, "time": at}
        with con:
            db.set_profile(con, "plan", plan)
        if self.reminder_dir is None:
            return {"plan": plan, "reminder": None}
        try:
            path = reminder.install(at, self.db_path, self.reminder_dir, load=self.launch_agents is None)
        except OSError as e:
            return {"plan": plan, "reminder": {"error": str(e)}}
        return {"plan": plan, "reminder": {"path": str(path)}}

    def placement_start(self, con, _):
        items = placement.build(self.c, self.rng)
        prefetch(it["audio"] for it in items["listen"])
        for rate in (-20, -10, 0):  # TONE_RATES in app/static/js/placement.js
            tts.prefetch((it["w"] for it in items["tone"]), self.cfg["tts_voice"], rate)
        return {"session_id": self.new_session("P"), **items}

    def placement_reading(self, con, body):
        est = placement.vocab_estimate(self.c, db.events(con, body["session_id"]))
        return placement.reading(self.c, placement.known_words(self.c, est), self.rng)

    def placement_finish(self, con, body):
        return placement.finish(con, self.c, body["session_id"])

    def reading_start(self, con, _):
        return {"session_id": self.new_session("R"), **placement.reading(self.c, study.known_set(con), self.rng)}

    def session_start(self, con, body):
        """A quick session is a fresh 5-minute cards block (id prefix Q, never resumed). A daily session resumes
        today's unfinished one if there is one, else starts a new one."""
        if body.get("quick"):
            resume, sid = None, self.new_session("Q")
            blocks = [{"id": "cards", "title": "Cards", "minutes": self.cfg["momentum"]["quick_minutes"]}]
        else:
            resume = study.resume_state(con, self.cfg)
            sid, blocks = resume["session_id"] if resume else self.new_session("S"), self.cfg["blocks"]
        return {"session_id": sid, "blocks": blocks, "queue": study.queue_counts(con, self.cfg), "resume": resume,
                "obsidian": self.cfg.get("obsidian")}

    def session_summary(self, con, body):
        return momentum.feedback(momentum.load(con), body["session_id"], self.cfg["momentum"], db.now())

    def event(self, con, body):
        if body["activity"] not in CLIENT_ACTIVITIES:
            raise ValueError(f"activity {body['activity']!r} is not client-logged")
        with con:
            db.log_event(con, body["session_id"], body["activity"], body.get("item"), body.get("result", {}), body.get("ms"))
        return {"ok": True}

    def cards_next(self, con, body):
        card = study.next_card(con, self.c, self.cfg, body.get("exclude"))
        if card:
            tts.prefetch([card["w"]], self.cfg["tts_voice"], study.TTS_RATE["word"])
            if card.get("example") and not card["example"].get("audio"):
                tts.prefetch([card["example"]["zh"]], self.cfg["tts_voice"], study.TTS_RATE["sentence"])
            return {"card": card}
        q = study.queue_counts(con, self.cfg)
        return {"card": None, "capped": q["capped"], "later": q["later"]}

    def cards_review(self, con, body):
        if body["rating"] not in study.RATINGS:
            raise ValueError("rating must be 1-4")
        return study.review(con, body["session_id"], body["word"], body["rating"], body.get("ms"), body.get("extra", {}))

    def sync_vault(self):
        """Mirror study.db into the Obsidian vault in the background (about 0.2 s). Skipped if the vault is absent."""
        cfg = self.cfg.get("obsidian")
        if not cfg or not self.real_db:
            return

        def run():
            with VAULT_LOCK:
                try:
                    out = obsidian.export(self.db_path, obsidian.vault_path(cfg["vault"]), cfg["folder"], self.c)
                    print(f"obsidian: {out['changed']} of {out['notes']} notes updated", flush=True)
                except (SystemExit, OSError) as e:
                    print(f"obsidian: skipped ({e})", flush=True)

        threading.Thread(target=run, daemon=True).start()

    def block_end(self, con, body):
        self.sync_vault()
        with con:
            db.log_event(con, body["session_id"], BLOCK_ACTIVITY[body["block"]], stats.BLOCK_END,
                         {"block": body["block"], "block_ms": body["block_ms"], "reason": body["reason"]})
        return {"ok": True}

    def bundle(self, con, _):
        sents = study.listen_bundle(con, self.c, self.cfg, self.rng)
        prefetch(s["audio"] for s in sents)
        tts.prefetch((s["zh"] for s in sents if not s["audio"]), self.cfg["tts_voice"], study.TTS_RATE["sentence"])
        return {"sentences": sents}

    def lookup(self, con, body):
        return study.lookup(con, self.c, body["session_id"], body["word"], body.get("ms"), body.get("extra", {}))

    def shadow_items(self, con, body):
        sents = study.shadow_items(con, self.c, self.cfg, body["session_id"], self.rng)
        tts.prefetch((s["zh"] for s in sents if not s["audio"]), self.cfg["tts_voice"], study.TTS_RATE["sentence"])
        return {"sentences": sents}

    def shadow(self, con, body):
        return study.save_shadow(con, self.c, self.rec_dir, body)

    def graph_local(self, con, body):
        depth = int(body.get("depth", 1))
        if depth not in (1, 2):
            raise ValueError("depth must be 1 or 2")
        out = self.graph.local(body["node"], obsidian.card_states(self.db_path), depth)
        return {**out, "obsidian": self.cfg.get("obsidian")}

    def graph_search(self, con, body):
        states = obsidian.card_states(self.db_path)
        return {"results": [self.graph.node(n, states) for n in self.graph.search(str(body.get("q", "")))]}

    def stats(self, con, _):
        return stats.compute(con, self.cfg)


ROUTES = {
    ("GET", "/api/state"): App.state,
    ("POST", "/api/placement/start"): App.placement_start,
    ("POST", "/api/placement/reading"): App.placement_reading,
    ("POST", "/api/placement/finish"): App.placement_finish,
    ("POST", "/api/reading/start"): App.reading_start,
    ("POST", "/api/session/start"): App.session_start,
    ("POST", "/api/session/summary"): App.session_summary,
    ("GET", "/api/momentum"): App.momentum_state,
    ("POST", "/api/plan"): App.plan,
    ("POST", "/api/event"): App.event,
    ("POST", "/api/cards/next"): App.cards_next,
    ("POST", "/api/cards/review"): App.cards_review,
    ("POST", "/api/block_end"): App.block_end,
    ("POST", "/api/bundle"): App.bundle,
    ("POST", "/api/lookup"): App.lookup,
    ("POST", "/api/shadow/items"): App.shadow_items,
    ("POST", "/api/shadow"): App.shadow,
    ("GET", "/api/stats"): App.stats,
    ("POST", "/api/graph"): App.graph_local,
    ("POST", "/api/graph/search"): App.graph_search,
}


FETCH_LOCK = threading.Lock()
VAULT_LOCK = threading.Lock()
cooldown_until = 0.0


def fetch_audio(audio_id, wait=3):
    """Cached Tatoeba mp3. Tatoeba answers concurrent downloads with 429s and stalls, so fetch one at a time,
    give up after `wait` seconds in line, and back off for 30 s after a 429. The client falls back to TTS."""
    global cooldown_until
    path = AUDIO_CACHE / f"{audio_id}.mp3"
    if path.exists():
        return path.read_bytes()
    if not FETCH_LOCK.acquire(timeout=wait):
        raise OSError("another audio download is in progress")
    try:
        if not path.exists():
            if time.time() < cooldown_until:
                raise OSError("Tatoeba rate limit cooldown")
            req = urllib.request.Request(f"https://tatoeba.org/audio/download/{audio_id}", headers={"User-Agent": "hsk4-coach/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = r.read()
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    cooldown_until = time.time() + 30
                raise
            AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(path)
    finally:
        FETCH_LOCK.release()
    return path.read_bytes()


def prefetch(audio_ids):
    ids = [i for i in audio_ids if i and not (AUDIO_CACHE / f"{i}.mp3").exists()]

    def run():
        for i in ids:
            try:
                fetch_audio(i, wait=60)
            except OSError:
                pass
            time.sleep(1)

    if ids:
        threading.Thread(target=run, daemon=True).start()


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if args[1:2] != ("200",) or "/api/" in self.path and not self.path.startswith("/api/state"):
                super().log_message(fmt, *args)

        def send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, code, obj):
            self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def api(self, method):
            path = self.path.split("?")[0]
            fn = ROUTES.get((method, path))
            if fn is None:
                return self.send_json(404, {"error": f"no route {method} {path}"})
            try:
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}") if size else {}
                con = app.con()
                try:
                    out = fn(app, con, body)
                finally:
                    con.close()
            except (KeyError, ValueError, TypeError) as e:
                return self.send_json(400, {"error": f"{type(e).__name__}: {e}"})
            self.send_json(200, out)

        def do_POST(self):
            self.api("POST")

        def do_GET(self):
            path = self.path.split("?")[0]
            if path.startswith("/api/"):
                return self.api("GET")
            if path == "/tts":
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                try:
                    text, rate = tts.parse(q.get("text", [""])[0], q.get("rate", ["0"])[0])
                    return self.send(200, tts.synth(text, app.cfg["tts_voice"], rate).read_bytes(), "audio/mpeg")
                except ValueError as e:
                    return self.send_json(400, {"error": str(e)})
                except Exception as e:
                    return self.send_json(502, {"error": f"tts unavailable: {type(e).__name__}: {e}"})
            m = re.fullmatch(r"/audio/(\d+)", path)
            if m:
                try:
                    return self.send(200, fetch_audio(int(m.group(1))), "audio/mpeg")
                except OSError as e:
                    return self.send_json(502, {"error": f"native audio unavailable: {e}"})
            file = (STATIC / (path.lstrip("/") or "index.html")).resolve()
            if not file.is_relative_to(STATIC) or not file.is_file():
                return self.send_json(404, {"error": "not found"})
            ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            self.send(200, file.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/javascript")) else ""))

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "study.db"))
    ap.add_argument("--config", default=str(ROOT / "app" / "config.json"))
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--launch-agents", help="write the reminder LaunchAgent here without loading it (tests)")
    args = ap.parse_args()
    app = App(args.db, args.config, args.launch_agents)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app))
    print(f"HSK 4 coach on http://localhost:{args.port}  (db {app.db_path})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
