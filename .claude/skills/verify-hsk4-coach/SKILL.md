---
name: verify-hsk4-coach
description: Launch a disposable HSK 4 Coach instance (local web app at app/server.py), drive its placement test, daily session, speaking block and stats in headless Google Chrome, and keep screenshot, DB and recording evidence. Use whenever a change to app/ or data/ needs proof on the real browser surface, or when asked to verify, test, screenshot or demo HSK 4 Coach.
---

# Verify HSK 4 Coach

HSK 4 Coach is a local web app: a Python stdlib server (`app/server.py`) plus vanilla JS in `app/static/`, storing everything in one SQLite file. The user-facing surface is the browser at `http://localhost:<port>/`. Secondary surface: `tools/weekly.py`, a CLI report over the same DB. All commands below run from the repo root (the folder holding `app/` and `tools/`).

The helper `verify.py` in this folder wraps every step. Define this once per shell (zsh does not word-split a `$V` variable):

```sh
V(){ .venv/bin/python .claude/skills/verify-hsk4-coach/verify.py "$@"; }
```

## Launch

```sh
V launch            # prints RUN=<id> and "ready at http://localhost:<port>/"
```

- Starts `python -m app.server --db <scratch>/study.db --port <free port>` in its own process group, with an empty DB (the schema is created on first open). Ready means the log printed `HSK 4 coach on http://localhost:<port>  (db <path>)` and `GET /api/state` answered 200.
- If `data/sentences.json`, `data/gloss.json` or `data/words.json` is missing (a fresh clone: sentences and gloss are gitignored), launch runs `tools/build_corpus.py` first. That needs `data/raw/` (downloads listed in `tools/build_corpus.py`). Without it launch fails and says so.
- Each launch is isolated: its own port, DB and recordings dir. Several runs can coexist. Never drive the user's own instance on port 8766 or `data/study.db`; that is their real study history.
- Prerequisites: `.venv` with `app/requirements.txt` installed (includes playwright), and Google Chrome at `/Applications/Google Chrome.app` (driven via `channel="chrome"`, so no `playwright install` is needed).

## Doctor

```sh
V doctor <RUN>      # exit 0 = worth driving
```

Read-only. Checks: the recorded pid is alive; that pid (and only it) listens on the run's port; the server's ready line names this run's DB; `/api/state` returns 200 with placement/known/queue; git HEAD still equals the commit the run launched on. Run it first whenever anything looks off. A failing "build matches launch" means the code changed since launch: cleanup and relaunch.

## Drive

```sh
V drive <RUN> placement   # must come first on a fresh run
V drive <RUN> session     # needs a placement; runs all three blocks at timescale 30
V drive <RUN> stats       # full-page screenshot of #/stats
```

The driver reuses the journeys in `app/e2e.py` (`placement`, `session`, `shot`) with their screenshot dir and URL redirected to this run, so a journey fixed in e2e is fixed here too. Stable handles the journeys rely on:

- Routes: `#/home`, `#/session`, `#/stats` (nav links carry `data-route`).
- Headings: `Placement test (about 10 minutes)`, `Listening`, `Tones`, `Timed reading`, `Your starting profile`, `Cards · 8 minutes`, `Listen & read · 12 minutes`, `Speak · 10 minutes`, `Session complete`. Block headings follow `app/config.json` (`blocks[].title` and `minutes`); a config change renames them.
- Buttons/text: `Start placement`, the primary `#/session` link (labelled `Start today's session` on the placement results and `Start 30-minute session` on home, the minutes following the config), the `5-minute session` link (`#/session?quick=1`, heading `Cards · 5 minutes`), `Quick check: what does this word mean?`, `Which of these did the text say?`, `Recording… speak now`.
- Keyboard: every screen is keyboard-driven. `y`/`n` vocab, `1-4` options and card grades, `Space` flip, `Enter` continue/next, `r` start/stop recording.
- `?timescale=N` runs block timers N times faster. It only changes the timer, not what is logged.

For an ad-hoc check outside the mapped journeys, open `http://localhost:<port>/?timescale=30` with playwright (`channel="chrome"`, args `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream --autoplay-policy=no-user-gesture-required`, `permissions=["microphone"]`) and use the handles above.

## Evidence

Everything lands in `verify-runs/<RUN>/` (gitignored):

- `<feature>/*.png` screenshots of each step, `failure.png` if a journey threw.
- `<feature>.json`: page errors, screenshot list, and DB counts before and after (events per activity, cards, known, placement profile). The before/after diff is the side-effect proof. A screen alone is not proof.
- `server.log`, `run.json` (pid, port, DB path, commit).
- After cleanup: `study.db` and `recordings/*.wav` copied from scratch.

Proof standards:

- Drive the real user path through the browser. Do not call `/api/*` directly to set state, and do not insert DB rows.
- Report the action and the resulting state: name the screenshot of the action and the DB delta it caused.
- Speech recognition: headless Chrome's recognizer starts but returns no transcript. The real recognizer is proven only on its empty path ("Recognition returned no transcript… Your recording is still saved"). The scored view in `session` uses a scripted recognizer injected by `app/e2e.py`. Say so in any report. Real-mic transcription needs a human at a real browser.
- Native audio comes from Tatoeba through `/audio/<id>` and is cached in the shared `data/audio_native/`. A run touches the network unless the clips are cached; 429s are expected and the client falls back to TTS after 5 s.

## Cleanup

```sh
V cleanup <RUN>
```

Kills only the pid recorded in `run.json`, after confirming its command line is `app.server` on the run's port (never by process name). Copies the scratch DB and recordings into the evidence dir, then deletes the scratch dir. Evidence is never removed. Run cleanup after every failed attempt too, so ports and processes do not pile up. To prune old evidence, delete `verify-runs/<RUN>/` by hand.

## Feature map

`features/README.md` indexes the user-facing features and how to prove each. Read it before driving, and keep it current with `/pstack:maintain-verification-skill`.
