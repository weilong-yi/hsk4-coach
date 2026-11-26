"""Weekly progress report from data/study.db, printed as Markdown. Same numbers as the app's Stats page.

    .venv/bin/python tools/weekly.py                 # last 7 days
    .venv/bin/python tools/weekly.py --days 28 --db /path/study.db
"""
import argparse, json, sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, stats  # noqa: E402


def pct(x):
    return "–" if x is None else f"{round(100 * x)}%"


def report(s, days):
    w, out = s["words"], []
    out.append(f"# HSK 4 coach: last {days} days (since {s['since']})\n")
    out.append(f"**Words started** {w['started']} / {w['target']} ({w['known_placement']} known at placement, "
               f"{w['learning']} learning, {w['mature']} mature). **Solid** {w['solid']}.")
    out.append(f"**Pace** needed {w['needed_per_day']}/day for {w['days_left']} days to {w['target_date']}; "
               f"recent {w['recent_per_day']}/day" + (f", on track for {w['projected_date']}." if w["projected_date"] else "."))
    out.append("\n## Per day\n")
    out.append("| Date | Cards min | Listen min | Speak min | Reviews | New | Sentences | Understood | Lookups | Shadow attempts | Shadow match |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for d in s["per_day"]:
        m = d["minutes"]
        out.append(f"| {d['date']} | {m['cards']} | {m['listen']} | {m['speak']} | {d['cards']} | {d['new_cards']} | "
                   f"{d['listened']} | {pct(d['understood_rate'])} | {d['lookups']} | {d['shadow_attempts']} | {pct(d['shadow_score'])} |")
    t = s["totals"]
    out.append(f"\nTotal {t['minutes']} min, {t['cards']} reviews, {t['listened']} sentences, {t['shadow_attempts']} shadow attempts.")
    out.append(f"\n## Calibration ({s['calibration_reviews']} Review-state reviews; {s['learning_step_reviews']} learning-step reviews excluded)\n")
    out.append("| Predicted R | Reviews | Mean predicted | Recalled |")
    out.append("|---|---|---|---|")
    for b in s["calibration"]:
        out.append(f"| {b['bin']} | {b['n']} | {pct(b['predicted'])} | {pct(b['recalled'])} |")
    out.append("\n## Reading speed\n")
    out.append("| Date | Chars/min | Characters | Comprehension |")
    out.append("|---|---|---|---|")
    for r in s["reading"]:
        out.append(f"| {r['date']} | {r['cpm']} | {r['chars']} | {pct(r['accuracy'])} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "study.db"))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true", help="print the raw stats instead of Markdown")
    args = ap.parse_args()
    since = (date.today() - timedelta(days=args.days - 1)).isoformat()
    con = db.connect(args.db)
    cfg = json.loads((ROOT / "app" / "config.json").read_text())
    s = stats.compute(con, cfg, since=since)
    print(json.dumps(s, ensure_ascii=False, indent=1) if args.json else report(s, args.days))


if __name__ == "__main__":
    main()
