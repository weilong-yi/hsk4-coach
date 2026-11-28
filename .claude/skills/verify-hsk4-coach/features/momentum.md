# Momentum: the minimum, rings, streak, plan and review cap

The learner sees today's three rings, a streak with freezes and a four-week calendar on Home, can do a 5-minute session that counts as a study day, sets an if-then plan with a daily macOS reminder, gets feedback from real progress after each session, and has reviews capped at 60 a day so a comeback session stays normal-sized. All of it is derived from the `events` table by `app/momentum.py`; nothing derived is stored.

## Sub-features

- `mom-rings` Home shows an SVG with three ring labels `Cards n/20`, `Listen n/15`, `Speak n/5` (`.rings .ring-label`), the streak (`N-day streak` or `No streak yet`, `.streak-n`), freezes (`.freezes`) and the minimum line (`10 cards would count today.` or `Today's minimum is met.`, `.minimum`).
- `mom-calendar` up to four Monday-to-Sunday weeks of `.calendar .weeks .day` cells classed `met`, `frozen`, `missed`, `pending`, `future` or `none` (before the first study day), starting with the week of the first study day; today also has `.today`. A text legend sits under it.
- `mom-quick` the `5-minute session` link opens `#/session?quick=1`: heading `Cards · 5 minutes`, a session id starting with `Q`, never offered for resume.
- `mom-feedback` `Session complete` (both session types) shows the rings, the streak with `+1 today` when that session met the minimum, `Moved forward`, `New words`, `Recall` and `Listening understood`. Quick sessions show only the Cards tile.
- `mom-plan` the Plan form (time, cue, `Save plan`) renders `If it's 19:30 after dinner at my desk, I study.`; `Edit` reopens it and `Cancel` closes it unchanged. Saving writes `com.hsk4coach.reminder.plist` with that hour and minute.
- `mom-reminder` `python -m app.reminder --notify --print --db <db>` prints `notify: <cue>: time for Chinese (http://localhost:8766)` when today's minimum is unmet, otherwise `no reminder: …`.
- `mom-cap` after `momentum.max_reviews_per_day` card reviews in a study day the cards block shows `Today's reviews are done; N more are spread over the next days.` (just `Today's reviews are done.` with no backlog), and Home's `Reviews due` tile shows only what fits under the cap, with `N more spread over the next days`.
- `mom-stats` `#/stats` tiles `Streak`, `Minimum met, last 7 days`, `Minimum met, last 28 days`; `tools/weekly.py` prints a `**Momentum**` line.

## How to get to it (user POV)

- `#/home` after a placement; `5-minute session` beside `Start 30-minute session`.
- `#/stats`, and `.venv/bin/python tools/weekly.py` in a terminal.

## Driving it

Preconditions:

- A placement in the run. Never start a server without `--launch-agents <temp dir>` if it could point at `data/study.db`: only the real DB installs a LaunchAgent into `~/Library/LaunchAgents` and calls `launchctl`.

- **Unit tests.** `.venv/bin/python -m app.test_momentum`: 4 a.m. boundary, minimum via each ring, freezes earned at 7 and capped at 2, a freeze used on a miss, reset without a freeze, pending today, shares that leave out days before the first study day, session feedback.
- **Run it.** `.venv/bin/python app/e2e.py` runs `quick_session` right after the placement (fresh DB: 3 cards Easy, 9 Again, then Skip block) and `history_journey` at the end: a second server over a copy of the DB with seeded listening history, every introduced card made two days overdue (a comeback backlog), a config whose cap is today's reviews + 3, and `--launch-agents <tmp>/history/LaunchAgents`.
- **Screenshots.** `32-quick-session-complete`, `33-plan-form`, `34-home-momentum-light`, `35-home-momentum-dark`, `36-cards-review-cap`; `24-stats` shows the stats tiles.
- **Proof.** The e2e JSON: `quick.session_id` starts with `Q`, `quick.complete.rings[0]` is `Cards 12/20` and `moved` lists the three Easy words; `history.calendar` is 19 met, 1 frozen, 1 missed; `history.plist` has `{Hour: 19, Minute: 30}`; `history.rated_before_cap` is 3, `history.reviews_today` equals `history.cap`, and `history.cap_message` names `backlog - 3` more.

## Gotchas

- Multi-day behaviour cannot be driven in one run, so `history_journey` inserts past `listen` rows (8 per day, one day at 01:30 the next morning to cross the 4 a.m. boundary) and moves card due dates back. That is the one sanctioned exception to "do not insert DB rows", and only into the copy.
- Expected walk of the seed: 3 met, a miss with no freeze (reset), 7 met (a freeze), a miss (frozen), 8 met (another freeze), today met: `16-day streak`, `1 freeze saved · next one after 5 more days in a row`.
- Moved forward counts cards that reached the Review state in the session. A new card rated Good stays in learning, but a second Good on it later in the same session graduates it, so rating everything Good makes the count depend on FSRS learning steps. The journey uses Easy and Again to keep it exact.
- launchctl and the real notification are not exercised: the e2e reads the plist, lints it with `plutil`, and runs the check script with `--print`. A real reminder needs the real DB and a human at the Mac.
- A run between midnight and 4 a.m. counts for the previous study day; the e2e computes "today" with the same rule.
