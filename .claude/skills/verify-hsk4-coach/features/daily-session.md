# Daily session: cards and listen & read

The learner runs one timed 30-minute session. The first two blocks are FSRS flashcards (audio first, then hanzi, pinyin, meaning, example) and listen & read (sentences at ≥97% known words, audio first, then text with tap-to-look-up).

## Sub-features

- `sess-start` session opens with the block strip and the first block heading.
- `cards-review` front plays audio, Space flips, `1-4` grades Again/Hard/Good/Easy with FSRS intervals shown.
- `cards-new` new cards (default 8/day) after due reviews.
- `listen-audio` sentence plays first; `y`/`n` marks understood.
- `listen-lookup` clicking a word opens a popover with pinyin and meaning; HSK words are added to cards.
- `block-timer` a per-block countdown; on expiry the block ends after the current item.

## How to get to it (user POV)

- `Start 30-minute session` on `#/home`, or `Start today's session` on the placement results. Both are the primary link to `#/session`.
- `#/session` from the nav.

## Driving it with verify.py

Preconditions:

- Placement done in this run (`V drive <RUN> placement`).

- **Start.** Choose the primary `#/session` link; heading `Cards · 8 minutes`; Enter.
- **Cards.** While `.card.front` shows press Space; on `.card.back` press `1` or `3`. Repeats until heading `Listen & read · 12 minutes`.
- **Listen & read.** On `.listen.audio` press `y`/`n`; on `.listen.text` click a `.tok.new` (or `.tok.tap`) word, expect `.popover`, then Enter.
- **Run it.** `V drive <RUN> session` (runs the speak block too). Screenshots `10-session-start` … `16-listen-lookup`.
- **Proof.** `session.json` `after.events` gains `card` and `listen` events and at least one `read_lookup`; `after.cards` grows by the lookups.

## Gotchas

- With timescale 30, the cards block can run out of due cards before its timer, so `13-cards-time-up` may not appear. That is expected.
- Audio goes through the server's `/tts` (neural voice, cached in `data/tts_cache/`, needs network on first synthesis). Card events log `voice: server-tts`; an instant scripted answer logs null.
- A looked-up word that was marked known moves from known to cards on purpose.
- The home button's minute count and the block titles follow `app/config.json`; update the headings above if the split changes.
