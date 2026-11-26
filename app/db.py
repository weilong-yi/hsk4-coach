import json, sqlite3
from datetime import datetime

ACTIVITIES = ("placement_vocab", "placement_listen", "placement_tone", "placement_read",
              "card", "listen", "read_lookup", "shadow")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS cards(word TEXT PRIMARY KEY, fsrs_json TEXT NOT NULL, introduced_at TEXT);
CREATE TABLE IF NOT EXISTS known(word TEXT PRIMARY KEY, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT NOT NULL,
  activity TEXT NOT NULL CHECK (activity IN ({",".join(repr(a) for a in ACTIVITIES)})),
  item TEXT, result_json TEXT NOT NULL, ms INTEGER);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS events_activity_ts ON events(activity, ts);
CREATE TABLE IF NOT EXISTS profile(key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
"""


def connect(path):
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def now():
    return datetime.now().astimezone()


def log_event(con, session_id, activity, item, result, ms=None):
    if activity not in ACTIVITIES:
        raise ValueError(f"unknown activity {activity!r}")
    con.execute("INSERT INTO events(ts, session_id, activity, item, result_json, ms) VALUES (?,?,?,?,?,?)",
                (now().isoformat(timespec="milliseconds"), session_id, activity,
                 None if item is None else str(item), json.dumps(result, ensure_ascii=False),
                 None if ms is None else int(ms)))


def events(con, session_id=None, activity=None):
    q, args = "SELECT * FROM events WHERE 1", []
    if session_id:
        q, args = q + " AND session_id=?", args + [session_id]
    if activity:
        q, args = q + " AND activity=?", args + [activity]
    return [dict(r, result=json.loads(r["result_json"])) for r in con.execute(q + " ORDER BY id", args)]


def get_profile(con, key):
    row = con.execute("SELECT value_json FROM profile WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def set_profile(con, key, value):
    con.execute("INSERT OR REPLACE INTO profile(key, value_json) VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))
