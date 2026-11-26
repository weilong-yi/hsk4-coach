# Resume a session

Leaving a daily session part-way (clicking Home or Stats, reloading, or closing the tab) keeps its progress. Coming back continues the same session: same block, the block timer where it stopped, and the running tally in the final summary.

## Sub-features

- `resume-offer` home shows `Resume session · <block title>` instead of `Start N-minute session`.
- `resume-note` the block intro says `Resuming where you left off: m:ss left in this block.` and the button reads `Resume <block>`.
- `resume-timer` the timer continues from the time used; `block_ms` in events never resets within a session.
- `resume-tally` the `Session complete` tiles count work from before the leave.
- `resume-expiry` a session older than 12 hours, or with every block finished (time, done or skip), is not resumed.

## How to get to it (user POV)

- Start a session, then leave by the nav, a reload, or closing the tab; return via `#/home` or `#/session`.

## Driving it with verify.py

Preconditions:

- Placement done. Use `?timescale=1` so the block cannot expire during the journey.

- **Run it.** `.venv/bin/python app/e2e.py` runs `resume_journey` after the main session (screenshots `26-home-resume-offered`, `27-resume-note`, `28-resumed-session-complete`).
- **Proof.** The e2e JSON `resume` shows one session id, 4 listen answers with non-decreasing `listen_block_ms` where the first answer after the leave includes the 1.5 s idle, and a Listening tile of 4.

## Gotchas

- The server rebuilds resume state from the event log (`resume_state` in `app/study.py`); there is no separate session table to inspect.
- A reload does not post a `leave` block-end, so time between the last answer and the reload is not counted. Navigating away inside the app does count it.
- Leaving after the block timer expired counts that block as used up; the session resumes at the next block.
