"""Local HSK 4 coach: stdlib HTTP server for app/static/ plus a JSON API over data/study.db.

    .venv/bin/python -m app.server            # http://localhost:8766
    .venv/bin/python -m app.server --db /tmp/x.db --port 8767
"""
import argparse, json, mimetypes, random, re, secrets, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import corpus, db, placement, stats, study

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
AUDIO_CACHE = ROOT / "data" / "audio_native"
CLIENT_ACTIVITIES = {"placement_vocab", "placement_listen", "placement_tone", "placement_read", "listen"}


class App:
    def __init__(self, db_path, config_path):
        self.db_path = Path(db_path)
        self.rec_dir = self.db_path.parent / "recordings"
        self.cfg = json.loads(Path(config_path).read_text())
        self.c = corpus.load()
        self.rng = random.Random()
        db.connect(self.db_path).close()

    def con(self):
        return db.connect(self.db_path)

    def new_session(self, prefix):
        return f"{prefix}{db.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"

    # ---- API handlers: (app, body) -> JSON ----

    def state(self, con, _):
        return {"placement": db.get_profile(con, "placement"), "config": self.cfg,
                "queue": study.queue_counts(con, self.cfg), "known": len(study.known_set(con))}

    def placement_start(self, con, _):
        return {"session_id": self.new_session("P"), **placement.build(self.c, self.rng)}

    def placement_reading(self, con, body):
        est = placement.vocab_estimate(self.c, db.events(con, body["session_id"]))
        return placement.reading(self.c, placement.known_words(self.c, est), self.rng)

    def placement_finish(self, con, body):
        return placement.finish(con, self.c, body["session_id"])

    def reading_start(self, con, _):
        return {"session_id": self.new_session("R"), **placement.reading(self.c, study.known_set(con), self.rng)}

    def session_start(self, con, _):
        return {"session_id": self.new_session("S"), "blocks": self.cfg["blocks"], "queue": study.queue_counts(con, self.cfg)}

    def event(self, con, body):
        if body["activity"] not in CLIENT_ACTIVITIES:
            raise ValueError(f"activity {body['activity']!r} is not client-logged")
        with con:
            db.log_event(con, body["session_id"], body["activity"], body.get("item"), body.get("result", {}), body.get("ms"))
        return {"ok": True}

    def cards_next(self, con, body):
        return {"card": study.next_card(con, self.c, self.cfg, body.get("exclude"))}

    def cards_review(self, con, body):
        if body["rating"] not in study.RATINGS:
            raise ValueError("rating must be 1-4")
        return study.review(con, body["session_id"], body["word"], body["rating"], body.get("ms"), body.get("extra", {}))

    def bundle(self, con, _):
        return {"sentences": study.listen_bundle(con, self.c, self.cfg, self.rng)}

    def lookup(self, con, body):
        return study.lookup(con, self.c, body["session_id"], body["word"], body.get("ms"), body.get("extra", {}))

    def shadow_items(self, con, body):
        return {"sentences": study.shadow_items(con, self.c, self.cfg, body["session_id"], self.rng)}

    def shadow(self, con, body):
        return study.save_shadow(con, self.c, self.rec_dir, body)

    def stats(self, con, _):
        return stats.compute(con, self.c, self.cfg)


ROUTES = {
    ("GET", "/api/state"): App.state,
    ("POST", "/api/placement/start"): App.placement_start,
    ("POST", "/api/placement/reading"): App.placement_reading,
    ("POST", "/api/placement/finish"): App.placement_finish,
    ("POST", "/api/reading/start"): App.reading_start,
    ("POST", "/api/session/start"): App.session_start,
    ("POST", "/api/event"): App.event,
    ("POST", "/api/cards/next"): App.cards_next,
    ("POST", "/api/cards/review"): App.cards_review,
    ("POST", "/api/bundle"): App.bundle,
    ("POST", "/api/lookup"): App.lookup,
    ("POST", "/api/shadow/items"): App.shadow_items,
    ("POST", "/api/shadow"): App.shadow,
    ("GET", "/api/stats"): App.stats,
}


def fetch_audio(audio_id):
    path = AUDIO_CACHE / f"{audio_id}.mp3"
    if not path.exists():
        req = urllib.request.Request(f"https://tatoeba.org/audio/download/{audio_id}", headers={"User-Agent": "hsk4-coach/0.1"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return path.read_bytes()


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if "/api/" in self.path and not self.path.startswith("/api/state"):
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
    args = ap.parse_args()
    app = App(args.db, args.config)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app))
    print(f"HSK 4 coach on http://localhost:{args.port}  (db {app.db_path})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
