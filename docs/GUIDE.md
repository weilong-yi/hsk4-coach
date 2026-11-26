# Using HSK 4 Coach

This guide is for the learner. It covers starting the app, the placement test, the daily 30-minute session, speaking practice, progress, the Obsidian graph, and what to do when something goes wrong. For installation, see the [README](../README.md).

## Start the app

From the project folder:

```sh
.venv/bin/python -m app.server
```

Then open **http://localhost:8766** in Chrome or Safari. Keep the terminal open while you study; closing it stops the app. Your progress is saved as you go, so you can stop at any time.

Use `localhost`, not a file path. The microphone only works on a `localhost` address.

## 1. Take the placement test (once, about 10 minutes)

The first time you open the app, Home shows **Start placement**. The test decides which words you already know and which become flashcards.

| Part | What you do | Keys |
|---|---|---|
| Vocabulary | Say whether you know each word. About 15 of them are made up, to catch guessing. | **Y** yes, **N** no (or → and ←) |
| Quick check | Pick the meaning of 5 words you said you knew. | **1**–**4**, then **Enter** |
| Listening | Hear 10 sentences and pick what each one means. | **Space** replay, **1**–**4**, **Enter** |
| Tones | Hear 12 two-syllable words and pick each syllable's tone. | **Space** replay, **1**–**4** per syllable, **Enter** |
| Timed reading | Read a short text, then answer 3 questions about it. | **Enter** when finished reading |

Answer honestly. Saying yes to a word you only half know marks it as known and you will never review it. If you are unsure, say no; the app will teach it.

At the end, **Your starting profile** shows your estimate for each HSK level, words known, and your listening, tone and reading scores. You can take it again later with **Retake placement** on Home.

## 2. Do the daily session (30 minutes)

Click **Start 30-minute session** on Home. The session has three timed blocks. Each block has its own timer at the top right; when it reaches zero, finish the current item and the next block starts. **Skip block →** moves on early.

### Cards (8 minutes)

Flashcards scheduled by FSRS, a spaced-repetition method: words come back just before you would forget them. Reviews come first, then up to 8 new words a day.

1. Listen to the word and try to recall its meaning before looking.
2. Press **Space** to reveal the characters, pinyin, meaning and an example sentence.
3. Rate how well you remembered it:

| Key | Rating | Use it when |
|---|---|---|
| **1** | Again | You did not remember it |
| **2** | Hard | You remembered it with effort |
| **3** | Good | You remembered it normally |
| **4** | Easy | It was instant |

Each button shows when the card will come back. **R** replays the word, **E** plays the example sentence.

### Listen & read (12 minutes)

Sentences chosen so that about 97% of their words are ones you know, with a few new ones mixed in.

1. Listen first, without the text. Press **Space** to replay or **S** to hear it slower.
2. Press **Y** if you understood it, **N** if not. Be honest: this is your listening score.
3. The text appears. Click any word you are unsure of to see its pinyin and meaning. HSK words you look up become flashcards. **Esc** closes the popup.
4. **T** shows the English translation. **Enter** goes to the next sentence.

The word popup also has **Graph →** (see section 4) and **Open in Obsidian →**, which opens that word's note in your vault (see section 6).

### Speak (10 minutes)

Shadowing: you repeat sentences from today's listening out loud.

1. Press **Space** to hear the sentence (**S** for slower).
2. Press **R**, say the sentence, then press **R** again to stop.
3. The app shows what speech recognition heard, colours each character green (understood) or red (missed), and gives a percentage.
4. **R** to try again, **Enter** for the next sentence.

What the score means:

- It measures whether you were **understood**, not whether your tones were perfect. Speech recognition guesses the most likely words, so it forgives small tone mistakes. Use the model audio for tones.
- Homophones count: if you say 她 and it hears 他, both are *tā*, so it counts.
- Beijing speech counts. 这儿 for 这里 (and 那儿, 哪儿) is accepted, adding 儿 costs nothing, and an erhua 儿 is never marked missed, because recognisers often drop it.

The first time, the browser asks for microphone access; allow it. In Chrome, your voice is sent to Google to be transcribed. Every attempt is also saved on your computer in `data/recordings/`.

### Leaving in the middle

You can click Home or Stats, reload, or close the tab. Your session is kept. Home will show **Resume session · *block name***, and the block continues with its remaining time and your earlier answers. A session older than 12 hours starts fresh.

## 3. Check your progress

- **Home** shows reviews due, new words today, words started out of 1,950, and the pace you need per day to reach 1,950 by 1 June 2027.
- **Stats** shows minutes per block per day, how often you recalled cards compared with what the scheduler predicted, your listening "understood" rate, your speaking trend, and your reading speed.
- **Reading check** on Home runs another timed read, to track reading speed over time.
- For a text report of the last week: `.venv/bin/python tools/weekly.py` (add `--days 30` for a month).

## 4. Explore the graph

**Graph** in the top bar shows how a word connects to others: its characters, the words that share them, each character's components, and characters with the same sound part.

- **Find a word** by typing characters (学) or toneless pinyin (xuesheng, qing). Exact syllables come first.
- **Colours show your progress**: aqua known, orange learning or in review, blue new. Hollow rings are characters that are not HSK words on their own; grey squares are components.
- **Lines show the link**: solid "contains", dashed "sound part", dotted "meaning part".
- **1 step / 2 steps** sets how far out to look. Two steps shows up to 60 nodes, keeping the most common words.
- **Click any node or chip** to move to it. Hover a node for its pinyin and meaning.
- The side panel lists every neighbour by type, plays the word (▶), and opens its note in Obsidian.

During a session, the word popup in Listen & read has **Graph →**, which opens the graph in a new tab so your session keeps going.

## 5. Audio

Sentences with a native recording play that recording. Everything else is read by a neural voice (Yunxi) that pronounces erhua the Beijing way. The voice needs an internet connection the first time each sentence is played; after that it is saved and plays instantly. If the voice service is unreachable, the app falls back to your Mac's Tingting voice.

## 6. Use the Obsidian graph

The app mirrors HSK 1–4 into your Obsidian vault (the vault named in `app/config.json`, folder `HSK`). It updates automatically at the end of every block. To update by hand:

```sh
.venv/bin/python -m app.obsidian
```

What you get:

- **One note per word, character and component.** 学 is both a word and a character, so it has one note.
- **Links.** Each note's properties link to its characters, components, meaning part, sound part, words containing it, and characters that share its sound part. For example 请 links to 讠 (meaning), 青 (sound) and 情 晴 清 猜 睛 精 (same sound part). The backlinks panel shows everything that points to a note.
- **Your progress.** Word notes carry `state/known`, `state/learning`, `state/review`, `state/relearning` or `state/new` as tags, plus `due` and `known_neighbors`.
- **Graph colours.** The same colours as the app's Graph page: aqua known, orange learning or review, blue new, dark grey components. Characters that are not words keep Obsidian's default grey (Obsidian cannot use shapes, and more colours would be hard to tell apart). Open a word, press **Cmd+P**, type "open local graph" to see its neighbourhood.
- **HSK words.base.** Two tables: *Next words through characters I know* (unlearned words grouped by how many known words share a character, highest first, which makes them the easiest to learn next) and *Learning now*.
- **Your own notes.** Write anything under **## My notes** at the bottom of a note. The export never touches that section. Everything above it is rewritten from the app, so edit only below it.

A new local graph pane starts without colours. Copy the groups from the main graph's **Groups** panel: `tag:#state/known` (#00a888), `tag:#state/learning OR tag:#state/review OR tag:#state/relearning` (#e76624), `tag:#state/new` (#338ced), `tag:#hsk/component` (#5c5c5c).

## 7. Back up your progress

Everything you have done is in `data/study.db`, and your recordings are in `data/recordings/`. Neither is in git, so neither is on GitHub. Copy both somewhere safe, for example iCloud Drive, now and then. If you lose `study.db`, you lose your flashcard history.

## 8. When something goes wrong

| Problem | What to do |
|---|---|
| "Mic error: not-allowed" | Allow the microphone in the address bar, and in System Settings → Privacy & Security → Microphone for your browser. |
| "Mic error: service-not-allowed" (Safari) | Turn on Dictation in System Settings → Keyboard. |
| "Mic error: no-speech" | Check the input device in System Settings → Sound → Input. |
| "Recognition returned no transcript" | Speak a little louder and closer, then try again. The recording is still saved. |
| No sound | Check the volume, then the internet connection (the neural voice needs it the first time). |
| Page does not load | Make sure the terminal running the app is still open, and that you are on `http://localhost:8766`. |
| "Address already in use" when starting | The app is already running in another terminal. Use that one, or close it first. |
| Obsidian notes not updating | Run `.venv/bin/python -m app.obsidian` and read its output. It only syncs your real `data/study.db`. |
