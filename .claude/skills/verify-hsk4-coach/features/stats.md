# Stats and weekly report

The learner checks progress: minutes per block per day, reviews, recall calibration against FSRS predictions, listening understood rate, shadow match trend, reading speed, and words known against the 1,950-word target by 2027-06-01. The same numbers are available as Markdown from `tools/weekly.py`.

## Sub-features

- `stats-page` `#/stats` renders all sections, empty states included.
- `stats-pace` words known vs target, with the pace needed per day.
- `stats-momentum` streak, freezes and the share of days the minimum was met (7 and 28 days); see [momentum](./momentum.md).
- `stats-weekly` `tools/weekly.py --db <path> [--days N]` prints the report.

## How to get to it (user POV)

- `Stats` in the nav (`#/stats`).
- Terminal: `.venv/bin/python tools/weekly.py`.

## Driving it with verify.py

Preconditions:

- Any run; meaningful numbers need `placement` and `session` first.

- **Page.** `V drive <RUN> stats` saves `stats/stats.png` (full page).
- **CLI.** While the run is live: `.venv/bin/python tools/weekly.py --db "$(python3 -c "import json;print(json.load(open('verify-runs/<RUN>/run.json'))['db'])")"`. After cleanup use `--db verify-runs/<RUN>/study.db`. Exit code 0 and a table row for today.
- **Proof.** Today's minutes and review counts in the page match the CLI and `session.json` `after.events`.

## Gotchas

- Calibration excludes same-day learning steps, so a single-day run shows 0 Review-state reviews. That is correct, not empty data.
- `block_end` marker events are excluded from counts; a reader of the raw `events` table must filter `item='block_end'` too.
