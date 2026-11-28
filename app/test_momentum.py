"""Unit tests for app/momentum.py. Plain asserts, no database.

    .venv/bin/python -m app.test_momentum
"""
from datetime import date, datetime, timedelta, timezone

from .momentum import feedback, streak, summary

# The values the spec fixes, so a config edit cannot quietly change what these tests mean.
CFG = {"day_starts_hour": 4, "rings": {"cards": 20, "listen": 15, "speak": 5}, "minimum_fraction": 0.5}
TZ = timezone(timedelta(hours=1))


def at(day, hh=12, mm=0):
    return datetime(2026, 11, day, hh, mm, tzinfo=TZ)


def events(when, activity, n, wav=True, item="1", sid="S1", **result):
    if activity == "shadow":
        result["wav"] = "/rec/1-1.wav" if wav else None
    return [{"ts": when.isoformat(timespec="milliseconds"), "session_id": sid, "activity": activity, "item": item,
             "result": dict(result)} for _ in range(n)]


def met_today(evs, now=at(27, 20)):
    return summary(evs, CFG, now)["today"]["met"]


def walk(pattern, start=date(2026, 11, 1)):
    """'M' met, '.' not met, one character per study day; the last one is today."""
    return streak([(start + timedelta(days=i), c == "M") for i, c in enumerate(pattern)])


def statuses(w):
    return "".join({"met": "M", "frozen": "F", "missed": "x", "pending": "p"}[d["status"]] for d in w["days"])


def test_day_starts_at_4am():
    late = events(at(28, 1, 30), "card", 10)  # 01:30 on the 28th belongs to the 27th
    s = summary(late, CFG, now=at(28, 3, 59))
    assert s["today"]["date"] == "2026-11-27" and s["today"]["met"]
    s = summary(late, CFG, now=at(28, 4, 0))
    assert s["today"]["date"] == "2026-11-28" and not s["today"]["met"]
    assert s["days"][-2] == {"date": "2026-11-27", "status": "met"} and s["streak"] == 1
    assert met_today(events(at(27, 4, 0), "card", 10)) and not met_today(events(at(27, 3, 59), "card", 10))


def test_minimum_via_each_ring():
    for activity, need in (("card", 10), ("listen", 8), ("shadow", 3)):
        assert not met_today(events(at(27), activity, need - 1)), activity
        assert met_today(events(at(27), activity, need)), activity
    assert not met_today(events(at(27), "card", 9) + events(at(27), "listen", 7) + events(at(27), "shadow", 2))


def test_only_real_work_counts():
    assert not met_today(events(at(27), "shadow", 5, wav=False))  # attempts without a saved recording
    assert not met_today(events(at(27), "card", 12, item="block_end"))
    assert not met_today(events(at(27), "placement_listen", 20) + events(at(27), "placement_vocab", 100))
    assert not met_today(events(at(27), "read_lookup", 20))


def test_rings_and_next_step():
    s = summary(events(at(27), "card", 12) + events(at(27), "shadow", 1) + events(at(27), "shadow", 4, wav=False), CFG, at(27, 20))
    assert [(r["label"], r["count"], r["target"]) for r in s["today"]["rings"]] == [("Cards", 12, 20), ("Listen", 0, 15), ("Speak", 1, 5)]
    assert [r["fill"] for r in s["today"]["rings"]] == [0.6, 0, 0.2]
    assert summary(events(at(27), "card", 30), CFG, at(27, 20))["today"]["rings"][0]["fill"] == 1
    assert summary([], CFG, at(27, 20))["today"]["next"] == {"ring": "cards", "more": 10, "started": False}
    assert summary(events(at(27), "card", 4), CFG, at(27, 20))["today"]["next"] == {"ring": "cards", "more": 6, "started": True}
    nearest = summary(events(at(27), "card", 4) + events(at(27), "listen", 6), CFG, at(27, 20))["today"]["next"]
    assert nearest == {"ring": "listen", "more": 2, "started": True}
    assert summary(events(at(27), "listen", 8), CFG, at(27, 20))["today"]["next"] is None


def test_freeze_earned_every_7_met_days_capped_at_2():
    assert walk("M" * 6)["freezes"] == 0
    assert walk("M" * 7)["freezes"] == 1
    assert walk("M" * 13)["freezes"] == 1
    assert walk("M" * 14)["freezes"] == 2
    w = walk("M" * 21)
    assert (w["streak"], w["freezes"], w["next_freeze_in"]) == (21, 2, None)
    assert walk("MMM.")["next_freeze_in"] == 4


def test_freeze_consumed_on_a_miss():
    w = walk("M" * 7 + "." + "M")
    assert statuses(w) == "MMMMMMMFM" and (w["streak"], w["freezes"]) == (8, 0)
    w = walk("M" * 14 + ".." + "M")
    assert statuses(w) == "M" * 14 + "FFM" and (w["streak"], w["freezes"]) == (15, 0)
    w = walk("M" * 7 + ".." + "M")  # one freeze covers one day; the second miss resets
    assert statuses(w) == "MMMMMMMFxM" and w["streak"] == 1
    # A frozen day ends the run of met days, so the next freeze needs 7 more in a row.
    assert walk("M" * 10 + "." + "M" * 4)["freezes"] == 0
    assert walk("M" * 10 + "." + "M" * 7)["freezes"] == 1


def test_reset_without_a_freeze():
    w = walk("MMM.M")
    assert statuses(w) == "MMMxM" and (w["streak"], w["freezes"]) == (1, 0)
    w = walk("MMM..")
    assert statuses(w) == "MMMxp" and w["streak"] == 0


def test_pending_today_does_not_break_the_streak():
    w = walk("MMM.")
    assert statuses(w) == "MMMp" and w["streak"] == 3
    assert walk("MMMM")["streak"] == 4
    s = summary(events(at(25), "card", 10) + events(at(26), "card", 10), CFG, now=at(27, 23))
    assert s["streak"] == 2 and s["days"][-1] == {"date": "2026-11-27", "status": "pending"}
    assert summary([], CFG, at(27))["streak"] == 0


def test_shares_exclude_days_before_the_first_study_day():
    evs = events(at(24), "card", 10) + events(at(26), "card", 10)  # met, missed, met, today pending
    s = summary(evs, CFG, now=at(27, 20))
    assert s["share"]["last7"] == {"met": 2, "days": 3, "rate": 0.667}
    assert s["share"]["last28"] == {"met": 2, "days": 3, "rate": 0.667}
    assert [d["status"] for d in s["days"][-5:]] == ["none", "met", "missed", "met", "pending"]
    assert len(s["days"]) == 28 and s["days"][-1]["date"] == "2026-11-27"
    s = summary(evs + events(at(27), "listen", 8), CFG, now=at(27, 20))
    assert s["share"]["last7"] == {"met": 3, "days": 4, "rate": 0.75}
    # Ten days of history: the 7-day window holds only the last 7, the 28-day window all 10.
    evs = [e for d in range(17, 27) for e in events(at(d), "card", 10 if d >= 21 else 0)] + events(at(17), "card", 10)
    s = summary(evs, CFG, now=at(27, 20))
    assert s["share"]["last7"] == {"met": 6, "days": 6, "rate": 1.0}
    assert s["share"]["last28"]["days"] == 10 and s["share"]["last28"]["met"] == 7
    assert summary([], CFG, at(27))["share"]["last7"] == {"met": 0, "days": 0, "rate": None}


def card(word, rating, before, after, new=False, sid="Q1", when=at(27, 18)):
    return events(when, "card", 1, item=word, sid=sid, rating=rating, new=new, before={"state": before}, after={"state": after})


def test_session_feedback():
    earlier = events(at(27, 9), "card", 6, sid="S0", rating=3, new=False, before={"state": "Review"}, after={"state": "Review"})
    session = (card("学", 4, "Learning", "Review", new=True) + card("好", 3, "Learning", "Learning", new=True)
               + card("水", 3, "Review", "Review") + card("火", 1, "Review", "Relearning")
               + card("好", 3, "Learning", "Review") + card("累", 2, "Learning", "Review") + events(at(27, 18), "read_lookup", 1, item="猫", sid="Q1", added=True)
               + events(at(27, 18), "card", 1, item="block_end", sid="Q1", block="cards", block_ms=300000))
    listens = (events(at(25), "listen", 3, understood=True) + events(at(25), "listen", 1, understood=False)
               + events(at(18), "listen", 1, understood=True) + events(at(18), "listen", 1, understood=False)
               + events(at(13), "listen", 5, understood=True))  # 14 days back: in neither week
    fb = feedback(earlier + session + listens, "Q1", CFG, now=at(27, 20))
    assert fb["moved"] == ["学", "好"]
    assert fb["introduced"] == ["学", "好", "猫"]
    assert fb["reviews"] == {"n": 2, "recalled": 1}
    assert fb["today"]["rings"][0]["count"] == 12 and fb["met_now"] and fb["streak"] == 1
    assert fb["listening"] == {"this_week": {"n": 4, "understood": 3, "rate": 0.75},
                               "last_week": {"n": 2, "understood": 1, "rate": 0.5}}
    already = feedback(earlier + events(at(27, 10), "card", 4, sid="S0", rating=3, before={"state": "Review"},
                                        after={"state": "Review"}) + session, "Q1", CFG, now=at(27, 20))
    assert already["today"]["met"] and not already["met_now"]


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"{len(tests)} tests passed")
