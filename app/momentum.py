"""Momentum: study days, the three daily rings, the daily minimum, the streak with freezes, and session feedback.

Everything is derived from the event log; only load() at the bottom reads the database. `cfg` is the
"momentum" block of app/config.json. A study day starts at cfg["day_starts_hour"] (4 a.m.), so an event
at 01:30 on the 28th belongs to the 27th.
"""
import json, math
from collections import Counter
from datetime import datetime, timedelta

RINGS = {"cards": "card", "listen": "listen", "speak": "shadow"}  # ring -> the activity that fills it, in display order
RING_OF = {activity: ring for ring, activity in RINGS.items()}
LABELS = {"cards": "Cards", "listen": "Listen", "speak": "Speak"}
FREEZE_EVERY, MAX_FREEZES = 7, 2
CALENDAR_DAYS = 28
ACTIVITIES = (*RINGS.values(), "read_lookup")  # what load() reads; lookups only feed session feedback


def study_day(moment, start_hour):
    """The study day a local time belongs to: its date once moved back by start_hour hours."""
    return (moment - timedelta(hours=start_hour)).date()


def ring_of(ev):
    """The ring an event fills, or None. Real work only: card reviews, listening answers, shadow attempts with a WAV."""
    ring = RING_OF.get(ev["activity"])
    if ev["item"] == "block_end" or ring == "speak" and not ev["result"].get("wav"):
        return None
    return ring


def day_counts(events, start_hour):
    """{study day: Counter(ring -> real-work count)}."""
    out = {}
    for ev in events:
        ring = ring_of(ev)
        if ring:
            out.setdefault(study_day(datetime.fromisoformat(ev["ts"]), start_hour), Counter())[ring] += 1
    return out


def minimums(cfg):
    """Count per ring that meets the day's minimum: minimum_fraction of its target (10 cards, 8 answers, 3 recordings)."""
    return {r: math.ceil(round(cfg["minimum_fraction"] * cfg["rings"][r], 9)) for r in RINGS}


def is_met(counts, cfg):
    need = minimums(cfg)
    return any(counts.get(r, 0) >= need[r] for r in RINGS)


def rings(counts, cfg):
    need = minimums(cfg)
    return [{"id": r, "label": LABELS[r], "count": counts.get(r, 0), "target": cfg["rings"][r], "minimum": need[r],
             "fill": min(1, counts.get(r, 0) / cfg["rings"][r])} for r in RINGS]


def next_step(counts, cfg):
    """The ring closest to the minimum and how many more it needs, or None once the minimum is met.
    A tie goes to the first ring, so a fresh day suggests cards (what the 5-minute session does)."""
    if is_met(counts, cfg):
        return None
    need = minimums(cfg)
    ring = min(RINGS, key=lambda r: (need[r] - counts.get(r, 0)) / need[r])
    return {"ring": ring, "more": need[ring] - counts.get(ring, 0), "started": counts.get(ring, 0) > 0}


def streak(days):
    """Walk (date, met) pairs, one per study day in order, from the first real-work day through today.

    A met day adds 1. Every FREEZE_EVERY met days in a row earn a freeze, at most MAX_FREEZES held. A missed
    past day uses a freeze if one is held (the day shows as frozen and the streak goes on), else the streak
    resets to 0. Today is "pending" until met: it counts once met and never breaks the streak before that.
    """
    count = freezes = run = 0
    out = []
    for i, (day, met) in enumerate(days):
        if met:
            count, run, status = count + 1, run + 1, "met"
            if run % FREEZE_EVERY == 0:
                freezes = min(MAX_FREEZES, freezes + 1)
        elif i == len(days) - 1:
            status = "pending"
        elif freezes:
            freezes, run, status = freezes - 1, 0, "frozen"
        else:
            count, run, status = 0, 0, "missed"
        out.append({"date": day.isoformat(), "status": status})
    return {"streak": count, "freezes": freezes,
            "next_freeze_in": FREEZE_EVERY - run % FREEZE_EVERY if freezes < MAX_FREEZES else None, "days": out}


def share(statuses, n):
    """Met days among the last n study days. `statuses` starts at the first study day, so days before it are
    never in the denominator; a pending today is left out too, since it is not over."""
    window = [s for s in statuses[-n:] if s != "pending"]
    met = sum(s == "met" for s in window)
    return {"met": met, "days": len(window), "rate": round(met / len(window), 3) if window else None}


def summary(events, cfg, now):
    """Today's rings and minimum, the streak and freezes, the last 28 study days, and the share of days met.
    Calendar days before the first study day have status "none"."""
    counts = day_counts(events, cfg["day_starts_hour"])
    today = study_day(now, cfg["day_starts_hour"])
    first = min([*counts, today])
    span = [first + timedelta(days=i) for i in range((today - first).days + 1)]
    walk = streak([(d, is_met(counts.get(d, {}), cfg)) for d in span])
    status = {d["date"]: d["status"] for d in walk["days"]}
    dates = [(today - timedelta(days=i)).isoformat() for i in range(CALENDAR_DAYS - 1, -1, -1)]
    statuses = [d["status"] for d in walk["days"]]
    now_counts = counts.get(today, {})
    return {"today": {"date": today.isoformat(), "rings": rings(now_counts, cfg), "met": is_met(now_counts, cfg),
                      "next": next_step(now_counts, cfg)},
            "streak": walk["streak"], "freezes": walk["freezes"], "next_freeze_in": walk["next_freeze_in"],
            "days": [{"date": d, "status": status.get(d, "none")} for d in dates],
            "share": {"last7": share(statuses, 7), "last28": share(statuses, CALENDAR_DAYS)}}


def listening(events, start_hour, today):
    """Listening answers marked understood in the last 7 study days and in the 7 before."""
    weeks = [[0, 0], [0, 0]]
    for ev in events:
        if ring_of(ev) == "listen":
            age = (today - study_day(datetime.fromisoformat(ev["ts"]), start_hour)).days
            if 0 <= age < 14:
                weeks[age // 7][0] += 1
                weeks[age // 7][1] += bool(ev["result"].get("understood"))
    return [{"n": n, "understood": u, "rate": round(u / n, 3) if n else None} for n, u in weeks]


def feedback(events, session_id, cfg, now):
    """What one session changed, from its own events: today's rings and streak (and whether this session met today's
    minimum), words that moved forward (rated Good or Easy into the Review state), new words, recall on reviews,
    and listening understood this week against last week."""
    today = summary(events, cfg, now)
    others = day_counts((e for e in events if e["session_id"] != session_id), cfg["day_starts_hour"])
    mine = [e for e in events if e["session_id"] == session_id and e["item"] != "block_end"]
    cards = [e for e in mine if e["activity"] == "card"]
    reviews = [e["result"] for e in cards if e["result"]["before"]["state"] == "Review"]
    this_week, last_week = listening(events, cfg["day_starts_hour"], study_day(now, cfg["day_starts_hour"]))
    return {"today": today["today"], "streak": today["streak"], "freezes": today["freezes"],
            "next_freeze_in": today["next_freeze_in"],
            "met_now": today["today"]["met"] and not is_met(others.get(study_day(now, cfg["day_starts_hour"]), {}), cfg),
            "moved": unique(e["item"] for e in cards if e["result"]["rating"] >= 3
                            and e["result"]["before"]["state"] != "Review" and e["result"]["after"]["state"] == "Review"),
            "introduced": unique([e["item"] for e in cards if e["result"].get("new")]
                                 + [e["item"] for e in mine if e["activity"] == "read_lookup" and e["result"].get("added")]),
            "reviews": {"n": len(reviews), "recalled": sum(r["rating"] > 1 for r in reviews)},
            "listening": {"this_week": this_week, "last_week": last_week}}


def unique(xs):
    return list(dict.fromkeys(xs))


def load(con):
    """The events momentum reads, from an open study.db connection, oldest first."""
    rows = con.execute(f"SELECT ts, session_id, activity, item, result_json FROM events WHERE activity IN "
                       f"({','.join('?' * len(ACTIVITIES))}) ORDER BY id", ACTIVITIES)
    return [{"ts": r[0], "session_id": r[1], "activity": r[2], "item": r[3], "result": json.loads(r[4])} for r in rows]
