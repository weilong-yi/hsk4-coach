# Placement test

A first-time learner takes a ten-minute placement test and gets a starting profile: an estimate per HSK level, words known, listening, tone and reading scores. It decides which words are marked known and which are queued as cards.

## Sub-features

- `place-vocab` yes/no on ~80 real words (20 per level 1-4) and ~15 made-up words.
- `place-spot` 4-option meaning check on 5 claimed words; a miss sends that word to cards.
- `place-listen` 10 audio-only sentences, 4-option English meaning.
- `place-tone` 12 two-syllable words, pick each syllable's tone.
- `place-read` timed read of a ~150-character text and 3 questions.
- `place-profile` results screen; known words and queued cards written to the DB.

## How to get to it (user POV)

- `#/home` on a fresh DB shows `Start placement`.
- After a placement, `Retake placement` on `#/home` (link to `#/placement`) runs it again.

## Driving it with verify.py

Preconditions:

- Fresh run (`V doctor` shows `placement=none`).

- **Start.** Choose `Start placement`, then Enter on `Placement test (about 10 minutes)`. `POST /api/placement/start` returns the item lists.
- **Vocab and spot check.** Press `y`/`n` per word (the counter reads `i / N`), then `1-4` and Enter for each `Quick check: what does this word mean?`.
- **Listening, tones, reading.** Enter past each section heading (`Listening`, `Tones`, `Timed reading`), answer with `1-4` (tones: one digit per syllable), Enter to advance.
- **Profile.** Heading `Your starting profile` with per-level bars and four score tiles.
- **Run it.** `V drive <RUN> placement`. Screenshots `01-home-first-run` … `09-placement-results`.
- **Proof.** In `verify-runs/<RUN>/placement.json`, `after.events` gains `placement_vocab` (~100), `placement_listen` (10), `placement_tone` (12), `placement_read` (~4); `after.placement.levels` is set; `after.known` and `after.cards` are non-zero. Measured on 2026-11-25: 673 known, 1,277 cards.

## Gotchas

- The scripted answers in `app/e2e.py` claim levels 1-2, half of level 3, and one made-up word, so the profile always lands near "HSK 1-2 known, 3 partial". That is the script, not a scoring bug.
- Reading speed is ~6,000 chars/min under the script because it advances after 1.5 s. Do not report it as a plausible human number.
- Listening audio may be TTS if Tatoeba is slow; the question still works.
