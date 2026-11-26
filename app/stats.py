"""Progress stats computed from the event log and card states. Shared by /api/stats and tools/weekly.py."""
from collections import defaultdict
from datetime import date, timedelta

from . import db, study

BLOCK_OF = {"card": "cards", "listen": "listen", "read_lookup": "listen", "shadow": "speak"}
BINS = [0.0, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0001]


def mean(xs):
    xs = list(xs)
    return round(sum(xs) / len(xs), 3) if xs else None


def compute(con, c, cfg, since=None):
    evs = [e for e in db.events(con) if since is None or e["ts"][:10] >= since]
    day = lambda e: e["ts"][:10]

    block_ms = defaultdict(int)
    for e in evs:
        if e["activity"] in BLOCK_OF and e["result"].get("block_ms") is not None:
            key = (e["session_id"], BLOCK_OF[e["activity"]])
            block_ms[key] = max(block_ms[key], e["result"]["block_ms"])
    session_day = {e["session_id"]: day(e) for e in evs}
    days = defaultdict(lambda: {"minutes": defaultdict(float), "cards": 0, "new_cards": 0, "listened": 0,
                                "understood": [], "lookups": 0, "shadow_scores": [], "shadow_attempts": 0})
    for (sid, block), ms in block_ms.items():
        days[session_day[sid]]["minutes"][block] += ms / 60000
    for e in evs:
        d, r = days[day(e)], e["result"]
        if e["activity"] == "card":
            d["cards"] += 1
            d["new_cards"] += bool(r.get("new"))
        elif e["activity"] == "listen":
            d["listened"] += 1
            d["understood"].append(bool(r.get("understood")))
        elif e["activity"] == "read_lookup":
            d["lookups"] += 1
        elif e["activity"] == "shadow":
            d["shadow_attempts"] += 1
            if r.get("score") is not None:
                d["shadow_scores"].append(r["score"])
    per_day = [{"date": k, "minutes": {b: round(v["minutes"].get(b, 0), 1) for b in ("cards", "listen", "speak")},
                "cards": v["cards"], "new_cards": v["new_cards"], "listened": v["listened"],
                "understood_rate": mean(v["understood"]), "lookups": v["lookups"],
                "shadow_attempts": v["shadow_attempts"], "shadow_scored": len(v["shadow_scores"]),
                "shadow_score": mean(v["shadow_scores"])}
               for k, v in sorted(days.items()) if any([v["cards"], v["listened"], v["shadow_attempts"], v["lookups"]])]

    reviews = [e["result"] for e in evs if e["activity"] == "card" and e["result"]["before"]["last_review"]]
    calibration = []
    for lo, hi in zip(BINS, BINS[1:]):
        rs = [r for r in reviews if lo <= r["retrievability"] < hi]
        calibration.append({"bin": f"{lo:.2f}-{min(hi, 1):.2f}", "n": len(rs),
                            "predicted": mean(r["retrievability"] for r in rs),
                            "recalled": mean(r["rating"] > 1 for r in rs)})

    reading = []
    for e in evs:
        if e["activity"] == "placement_read" and e["result"].get("phase") == "timed":
            qs = [q["result"]["correct"] for q in evs if q["session_id"] == e["session_id"]
                  and q["activity"] == "placement_read" and q["result"].get("phase") == "question"]
            reading.append({"date": day(e), "session_id": e["session_id"], "cpm": e["result"]["cpm"],
                            "chars": e["result"]["chars"], "accuracy": mean(qs)})

    intro = study.introduced(con)
    mature = sum((card.stability or 0) >= study.YOUNG_DAYS for _, card, _ in intro)
    known = con.execute("SELECT COUNT(*) FROM known").fetchone()[0]
    queued = con.execute("SELECT COUNT(*) FROM cards WHERE introduced_at IS NULL").fetchone()[0]
    today = date.fromisoformat(study.today())
    target_date = date.fromisoformat(cfg["target_date"])
    days_left = max(1, (target_date - today).days)
    started = known + len(intro)
    recent = sum(i[:10] >= (today - timedelta(days=13)).isoformat() for _, _, i in intro) / 14
    remaining = max(0, cfg["target_words"] - started)
    words = {"target": cfg["target_words"], "target_date": cfg["target_date"], "days_left": days_left,
             "known_placement": known, "mature": mature, "learning": len(intro) - mature, "queued": queued,
             "started": started, "solid": known + mature,
             "needed_per_day": round(remaining / days_left, 2), "recent_per_day": round(recent, 2),
             "projected_date": (today + timedelta(days=round(remaining / recent))).isoformat() if recent and remaining else None}

    return {"since": since, "per_day": per_day, "calibration": calibration,
            "reviews_with_history": len(reviews), "reading": reading, "words": words,
            "totals": {"cards": sum(d["cards"] for d in per_day), "listened": sum(d["listened"] for d in per_day),
                       "shadow_attempts": sum(d["shadow_attempts"] for d in per_day),
                       "minutes": round(sum(sum(d["minutes"].values()) for d in per_day), 1)}}
