# HSK 4 Coach verification map

The maintained source for verifying what a learner can do in HSK 4 Coach. Read this index, then use the matching feature file as the recipe.

## Baseline preconditions

- A run launched with `V launch` and passing `V doctor <RUN>` (see `../SKILL.md` for `V`).
- A fresh run has no placement, no cards and no known words. `placement` must run before `session`.
- Never drive port 8766 or `data/study.db`; those are the learner's real instance and history.

## Driving conventions

- Prefer headings, button text, routes (`#/home`, `#/session`, `#/stats`) and the documented keyboard shortcuts over CSS position.
- Block names and lengths come from `app/config.json`. Read it before asserting a heading like `Cards · 8 minutes`.
- Use `?timescale=30` for timed blocks. Never edit the config to shorten blocks for a test.

## Proof and skip reporting

- Pair each screenshot with the DB delta in `verify-runs/<RUN>/<feature>.json` (`before` vs `after`).
- Name the entry point used. A feature verified via `V drive` is verified through its keyboard path only.
- Report anything driven with a scripted stand-in (the speech recognizer) as such, never as verified real behavior.
- An unmet precondition is a reported failure with its reason, not a skip.

## Features

- [Placement test](./placement.md): vocabulary yes/no with made-up words, spot check, listening, tones, timed reading, profile.
- [Daily session: cards and listen & read](./daily-session.md): FSRS cards, audio-first sentences, word lookup.
- [Speak block (shadowing)](./speaking.md): record, recognizer transcript, WAV upload, mic release.
- [Resume a session](./resume.md): leave by nav, reload or closed tab; same session, block, timer and tally on return.
- [Stats and weekly report](./stats.md): `#/stats` page and `tools/weekly.py`.
