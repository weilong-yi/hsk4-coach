# Speak block (shadowing)

The learner hears a sentence from today's bundle, records themself saying it, and sees a live transcript and how much of the sentence speech recognition understood. Each attempt saves a 16 kHz mono WAV.

## Sub-features

- `speak-record` `r` starts and stops recording; the screen shows `Recording… speak now`.
- `speak-transcript` cloud recognizer transcript (Chrome sends audio to Google), merged across Chrome- and Safari-style results.
- `speak-score` share of the target understood, aligned on toned pinyin (homophones like 她/他 count), labelled `understood by speech recognition (not a tone check)`.
- `speak-wav` WAV posted to `/api/shadow`, saved under the run's `recordings/`.
- `speak-release` mic tracks end after an attempt and on Next during recording; the cut-short attempt is still logged.

## How to get to it (user POV)

- Third block of the daily session, heading `Speak · 10 minutes`.

## Driving it with verify.py

Preconditions:

- Placement done; reached through `V drive <RUN> session`.

- **Record.** Press `r`, wait, press `r`. Expect `.result .warn` (headless recognizer gives no transcript) and a `/api/shadow` response.
- **Abandon.** Press `r`, then Enter mid-recording. The next sentence shows and all mic tracks are ended (`window.__streams`).
- **Scored view.** The journey injects a scripted recognizer (`FAKE_RECOGNITION` in `app/e2e.py`), records, and expects `.scored` with the `understood` label.
- **Proof.** `session.json` `after.events.shadow` ≥ 3; after cleanup `verify-runs/<RUN>/recordings/` holds 16 kHz mono 16-bit WAVs with non-zero RMS (fake mic tone).

## Gotchas

- All TTS uses the Tingting voice (`mandarinVoice()` in `app/static/js/audio.js`). `events.result_json` `$.voice` should read `Tingting` for card and placement_tone events.
- Real transcription is unverified in headless Chrome. Screenshot `21-speak-scored-scripted-recognizer` proves the scoring UI, not the recognizer.
- The app must be on `http://localhost`; a `file://` page gets no mic.
- Pitch-based tone feedback is not in the app yet (see `data/exp_speech.md`); do not look for it.
