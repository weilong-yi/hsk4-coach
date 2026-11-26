# HSK 4 Coach

A local study app for passing the new-format HSK 4 (HSK 3.0, 2025 syllabus, 1,950 words), built around 30 minutes a day. It has a placement test, then a daily session of FSRS flashcards, listening and reading at 97% known words, and shadowing with speech recognition. Every study action is logged so the session can be tuned from real data.

## Run it

Needs macOS or Linux, Python 3.12, [uv](https://github.com/astral-sh/uv), and Google Chrome for the speech features.

```sh
uv venv -p 3.12 .venv
uv pip install --python .venv/bin/python -r app/requirements.txt praat-parselmouth
```

Download the raw data into `data/raw/`, then build the corpus (about 25 s):

```sh
mkdir -p data/raw && cd data/raw
curl -LO https://raw.githubusercontent.com/drkameleon/complete-hsk-vocabulary/main/complete.json && mv complete.json hsk_complete.json
for f in per_language/cmn/cmn_sentences.tsv.bz2 per_language/eng/eng_sentences.tsv.bz2 sentences_with_audio.tar.bz2 links.tar.bz2; do
  curl -LO "https://downloads.tatoeba.org/exports/$f"; done
curl -L -o cedict.txt.gz https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz
cd ../.. && .venv/bin/python tools/build_corpus.py
```

Start the app and open http://localhost:8766:

```sh
.venv/bin/python -m app.server
```

Your study history lives in `data/study.db` and `data/recordings/`. Both stay on your machine and are not tracked by git, so back them up yourself.

## Check it

- `.venv/bin/python app/e2e.py` drives placement, a full session, session resume and stats in headless Chrome against a throwaway database.
- `.claude/skills/verify-hsk4-coach/` launches isolated instances and keeps evidence (see its `SKILL.md`).
- `tools/weekly.py` prints a progress report from the study database.

## Experiments behind the design

- `tools/exp_coverage.py`: reading bundles at 97% known words, and how many new words can be taught in context.
- `tools/exp_speech/`, results in `data/exp_speech.md`: speech-to-text does not catch tone errors, so shadowing is scored as "understood", not as a tone check.
- `tools/exp_erhua/`: which voice pronounces erhua. The app uses a neural voice that r-colours all 12 test words.

## Data and services

- HSK word list: [drkameleon/complete-hsk-vocabulary](https://github.com/drkameleon/complete-hsk-vocabulary), MIT licence, see `data/LICENSE-complete-hsk-vocabulary`. `data/words.json` is derived from it.
- Example sentences and native audio: [Tatoeba](https://tatoeba.org), CC BY 2.0 FR; audio licences vary per recording. Downloaded locally, not redistributed here.
- Dictionary glosses: [CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict), CC BY-SA 4.0. Downloaded locally, not redistributed here.
- Word frequency: [wordfreq](https://github.com/rspeer/wordfreq).
- Speech: synthesis through Microsoft's online neural voices via [edge-tts](https://github.com/rany2/edge-tts); recognition through the browser's Web Speech API (Chrome sends audio to Google).
