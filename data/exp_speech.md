# Speech experiments: tone feedback and audio sources

These experiments decide two things for the app. E1 asks what feedback after a shadowing attempt catches a wrong tone. E2 asks which audio the app should play. Every number below is measured on this Mac (macOS 26.6, Google Chrome 158) on 2026-11-25. Counts come from [exp_speech_tables.md](exp_speech_tables.md), which `tools/exp_speech/run.py` regenerates.

## Verdicts

Question | Verdict | Evidence
--- | --- | ---
E1a. Chrome cloud speech-to-text (STT) catches a wrong tone | NOT VERIFIED | On the one voice STT reads reliably (Tingting), 1 of 20 wrong-tone test words changed the transcript. Across all voices, 1 of 100 test transcripts contained the wrong-tone syllable.
E1b. Pitch tracking catches a wrong tone in a two-syllable word | VERIFIED on synthetic voices, INCONCLUSIVE for a human learner | Test split: 52 of 100 wrong syllables flagged, 7 of 100 correct words flagged. On native speakers' correct 3-4 syllable phrases, the same setting flags 22% to 43% of clips.
E1b. Pitch tracking catches a wrong tone in a sentence | NOT VERIFIED | Test split: 8 of 38 wrong syllables flagged. At the same margin, 11% to 30% of native speakers' correct sentences are flagged.
E2.1. Tingting is as intelligible as native audio | VERIFIED | STT toned-syllable error rate 1.4% for Tingting and 3.2% for native, 40 sentences each. The other macOS voices score 12.8% to 42.0%.
E2.2. macOS voices match the expected tones as well as native audio | INCONCLUSIVE | The per-syllable check agrees with only 54% of native syllables, so it cannot rank sources.

## Recommendation for the app

After a shadowing attempt on a sentence, show these things:

1. Show which characters the recognizer understood, as `app/study.py` `match()` does now. Compare toned pinyin instead of characters. Native clips lost 6.4% of characters but only 3.2% of toned syllables. The gap is homophones: 她来了 comes back as 他来了, and character matching marks a correct attempt wrong.
2. Label that result "understood", not "tones correct". It does not react to tone errors (E1a).
3. Draw the learner's pitch contour over the model clip's contour, with no right or wrong verdict. This is an inference, not a measured result. It is the only pitch display left, because per-syllable verdicts on sentences failed.
4. Do not show per-syllable tone verdicts on sentences.

For tone verdicts, add a separate two-syllable word drill that uses `tonecheck.check()` with the learner's register from `tonecheck.baseline()`. Turn it on only after the learner's [self-check](#self-check-on-your-own-voice) passes. Synthetic voices are the only evidence that it works.

For audio, play these sources:

1. Play the native Tatoeba clip when the sentence has one. That covers 345 of the 6,336 sentences that are fully inside HSK 1-4 (5.4%). The clips come from three speakers.
2. Otherwise play Tingting through `speechSynthesis`, and only Tingting. `app/static/js/audio.js` now rotates over all nine zh-CN voices, so eight of every nine plays use an Eloquence voice (Eddy, Flo, Grandma, Grandpa, Reed, Rocko, Sandy, Shelley). The four Eloquence voices tested had 9 to 30 times Tingting's STT error rate.

Browser `speechSynthesis` on this Mac is good enough for intelligibility when it uses Tingting. In Chrome, `speechSynthesis.getVoices()` listed exactly the nine local macOS zh-CN voices and no network voices. Two things are not verified. First, that `speechSynthesis` output is acoustically the same as `say` output, given that the app also sets the rate to 0.9 and 0.6. Second, whether a downloadable higher-quality Mandarin voice beats Tingting. The installed Tingting is the "super-compact" build. To test a new voice, add its name to `VOICES` in `tools/exp_speech/stimuli.py` and rerun.

## E1: what catches a wrong tone

### Test set

- **Words.** 40 two-syllable HSK 1-3 words, 2 or 3 per tone pair, chosen by frequency. The set has no neutral tones and no 3-3 pairs. It has no 一 or 不, and only words where `data/words.json` and pypinyin agree on the pinyin.
- **Sentences.** 20 HSK 1-3 sentences of 4 to 8 syllables, with no 一 or 不.
- **Voices.** Each item is rendered by Tingting, Eddy, Flo, Grandpa and Sandy. Those are five registers, from a median of 83 Hz (Grandpa) to 238 Hz (Sandy).
- **Independent speakers.** The five voices are only two independent speakers. Eddy, Flo, Grandpa and Sandy share one Eloquence prosody model. Their normalized contours differ from each other by 0.19 to 0.32 Chao units (median), against 0.87 to 0.92 from Tingting.

Each item exists as a control and as a wrong-tone variant in every voice. The control is the render resynthesized with its own pitch. Both variants go through the same PSOLA step, so resynthesis artifacts affect both sides. Each wrong-tone variant replaces one syllable's pitch with the same voice's real contour for another tone, taken from a different item in the same position. The (from, to) tone pairs are balanced at 4 to 6 items each, which gives 300 controls and 290 wrong-tone clips. Ten clips were skipped for lack of a donor syllable.

Pitch values are on the Chao scale, where 1 to 5 spans the speaker's 5th to 95th percentile of F0. One Chao unit is about 3 semitones for these voices.

### Checking the manipulation

I could not listen to the clips, so I measured each one. In each manipulated clip I measured the F0 contour of the target syllable. The median distance to the donor contour is 0.07 Chao units RMS, and the median distance to the original contour is 1.51. A variant counts as valid when it sits closer to the donor than to the original, and 282 of 290 do. The other 8 are excluded from detection counts. On the untouched syllables, 90% of clips change by at most 0.69 Chao units.

### Results on the test split

The thresholds were picked on the dev half of the items. Dev is the even-indexed items, and the threshold is the most sensitive one that flags at most 10% of dev controls. The table counts the odd-indexed items.

Method | Words: wrong syllable caught | Words: correct word flagged | Sentences: wrong syllable caught | Sentences: correct sentence flagged
--- | --- | --- | --- | ---
STT, all voices (transcript differs from target) | 58/100 | 32/100 | 26/38 | 22/50
STT, Tingting only | 1/20 | 0/20 | 1/7 | 1/10
Pitch against tone templates (`tonecheck`) | 52/100 | 7/100 | 8/38 | 2/50
Pitch against the reference clip | 30/100 | 6/100 | 4/38 | 6/50

Per voice, on words, the pitch template method catches 15 of 20 for Tingting and flags 4 of 20 of her correct words. On the Eloquence voices it catches 8 to 10 of 20 and flags 0 to 3 of 20. The threshold sweep in the tables file shows the tradeoff on all 198 wrong and 200 correct words. At margin 0.5 it catches 79% and flags 16%. At margin 1.0 it catches 41% and flags 8%.

### What limits each number

**STT.** The recognizer returns the word its language model expects, and one wrong tone rarely moves it to another word. Tingting's word renders are transcribed correctly 39 of 40 times, and all 31 of her clips in the repeat sample came back identical on a second pass. On that clean audio, 3 of 38 wrong-tone words changed the transcript, across all splits. Only 5 of 198 word transcripts contained the wrong-tone syllable, so STT cannot say which tone was wrong.

The Eloquence voices look more sensitive. Where the control was transcribed right, 53% to 83% of their wrong-tone words changed the transcript. Their audio sits at the edge of what the recognizer can parse: 20% to 55% of their correct words already come back wrong, and 18% of their transcripts change between two identical runs. Any change tips them. That is a signal about audio quality, not about tone.

Chrome also reports the same confidence, 0.9097, on 84% of transcripts, so confidence cannot grade an attempt.

**Pitch templates.** Four things limit the template method:

- **Margin.** Holding false alarms near 10% needs a margin of 0.95 Chao units, which gives up the subtle errors.
- **Overlapping shapes.** The method catches T3 said as T1 in 18 of 19 cases. It catches T2 said as T3, the classic learner confusion, in only 3 of 30.
- **Speaker style.** Tingting's correct words get flagged 9 of 40 times. Her word-final syllables sit low in her range.
- **Connected speech.** In sentences, a tone's shape depends on its neighbors, and syllable boundaries inside a voiced stretch are guesses.

**Reference clip.** Two speakers' correct versions of the same syllable differ by 0.85 to 0.94 Chao units (median, E2). That is close to the 1.51 units that a whole tone change moves the contour. Comparing to the model clip therefore cannot separate errors from speaker differences. That holds with and without removing the level offset between the two clips.

### False alarms on real speakers

Synthetic controls cannot show how `tonecheck` treats a human. I ran it on 160 native Tatoeba clips of correct speech, from fucongcong (93), LeviHighway (52) and GlossaMatik (15). Every flag on these clips is a false alarm.

Utterance | Clips | Clips flagged at margin 0.95, speaker register | Clips flagged at margin 0.95, clip-only register | Syllables whose best template is the expected tone
--- | --- | --- | --- | ---
3-4 syllables | 58 | 25 (43%) | 13 (22%) | 48% to 56%
5-6 syllables | 82 | 42 (51%) | 31 (38%) | 50% to 54%
7+ syllables | 20 | 14 (70%) | 13 (65%) | 53% to 56%

I traced individual clips to see why. In 她来了, lai2 starts with a fall carried over from the high T1, so it fits the T3 template. In 我同意, the T2 rise peaks inside the next syllable. In 天很冷, the segmenter puts the boundary between two voiced syllables in the wrong place. In 没关系, the speaker reduces the dictionary T4 toward a neutral tone. These are properties of connected speech, so the same failures will hit the learner's sentences. No native recordings of isolated two-syllable words were available. The false-alarm rate on those is unmeasured, and the self-check below measures it on the learner's own voice.

### Caveats

- The errors are synthetic. A learner's wrong tone also changes duration, loudness and voice quality, such as creak on T3. PSOLA changes only F0. STT may react more to real errors than it did here.
- The wrong-tone clips were cut at boundaries from the same segmenter that `tonecheck` uses. That favors pitch tracking, because real learner speech will not line up as neatly.
- The donor contours are the voices' own tones, not my templates. That keeps the pitch method from simply recognizing its own templates.
- The test split was printed once before the last template change. That change added unlowered final T1 and T2 shapes after a synthetic-signal test failed. Dev results were identical before and after it.
- Grandpa's voice halves its pitch in creak. Within a syllable, `tonecheck` repairs the jump. A whole syllable an octave low cannot be told apart from a deep T3, so it stays unrepaired.

## Self-check on your own voice

This takes 5 minutes and validates `tonecheck` and STT on your voice before the app trusts either one.

1. Open QuickTime Player and choose **File > New Audio Recording**.
2. Record one clip per line, in this order, into one folder. Name the files `01` to `10`.
   1. 中国 zhōngguó, said correctly.
   2. 中国 said as zhòngguó, with a falling first syllable (T4).
   3. 没有 méiyǒu, said correctly.
   4. 没有 said as měiyǒu, with a low first syllable (T3).
   5. 学习 xuéxí, said correctly.
   6. 学习 said as xuéxì, with a falling second syllable (T4).
   7. 开始 kāishǐ, said correctly.
   8. 开始 said as kāishí, with a rising second syllable (T2).
   9. 问题 wèntí, said correctly.
   10. 问题 said as wēntí, with a level first syllable (T1).
3. Run `tools/exp_speech/.venv/bin/python tools/exp_speech/selfcheck.py <folder> --stt`.

The script estimates your register from all ten clips. For each syllable it prints the best-matching tone and how much worse the expected tone fits. It then counts flags on the correct clips and catches on the wrong ones, at margins 0.5 and 0.95. Turn on the word drill at a margin where at most 1 of 5 correct clips is flagged and at least 3 of 5 wrong clips are caught.

Five clips per side is a coarse estimate. One false alarm in five is consistent with a true rate anywhere from about 1% to 72% (95% interval). Repeat the check on a second day before you trust a pass.

I ran the script on renders used as stand-ins for a learner. With Eddy as the learner it flags 0 of 5 correct clips and catches 4 of 5 at margin 0.5, and 1 of 5 at margin 0.95. With Tingting it catches 3 of 5 and 0 of 5. STT kept the target word in 4 of the 5 wrong clips for both voices.

## E2: macOS voices against native audio

The sample is 40 of the 345 native-audio HSK 1-4 sentences, picked at random with seed 0. Intelligibility is the STT error rate, counted on characters and on toned syllables, where a homophone is not an error. Tone fidelity is the share of syllables whose measured contour best matches the expected tone from the pinyin, with each clip's own register.

Source | STT character error | STT toned-syllable error | Sentences fully right | Syllables matching the expected tone | Median contour distance to native (Chao units)
--- | --- | --- | --- | --- | ---
Native | 6.4% | 3.2% | 35/40 | 128/235 (54%) | -
Tingting | 4.6% | 1.4% | 36/40 | 143/240 (60%) | 0.85
Eddy | 15.7% | 12.8% | 24/40 | 167/235 (71%) | 0.85
Grandpa | 22.4% | 19.2% | 16/40 | 172/237 (73%) | 0.92
Flo | 37.0% | 34.9% | 15/40 | 158/237 (67%) | 0.93
Sandy | 43.4% | 42.0% | 13/40 | 144/238 (61%) | 0.94

Tingting is as intelligible to the recognizer as the native clips. The Eloquence voices are not, and Sandy loses 42% of syllables. STT intelligibility stands in for a human listener and is not the same thing, but a gap this large is unlikely to be an artifact of the recognizer.

The tone-fidelity column does not rank the sources. The native speakers score lowest because connected speech departs from citation tones, and the per-syllable check penalizes that (see [False alarms on real speakers](#false-alarms-on-real-speakers)). Every voice sits 0.85 to 0.94 Chao units from the native contour, and the voices are no closer to native than to each other.

## Data problem found

`data/words.json` stores surname readings for some polyphones, for example 都 `Du1` and 还 `Huan2`. The experiment takes sentence pinyin from pypinyin in context and accepts either tone where the two sources disagree.

## Reproduce

```
cd tools/exp_speech && uv venv -p 3.12 && VIRTUAL_ENV=.venv uv pip install praat-parselmouth numpy playwright pypinyin
cd ../.. && tools/exp_speech/.venv/bin/python tools/exp_speech/run.py
tools/exp_speech/.venv/bin/python tools/exp_speech/test_tonecheck.py
```

`run.py` renders the clips, downloads native audio, runs STT twice and the pitch analysis, and rewrites `data/exp_speech_tables.md`. Each step skips work it has already cached in `tools/exp_speech/cache/`, so a rerun with a full cache takes about 15 seconds. A cold run takes several hours. Chrome recognizes about 10 clips a minute (1,330 recognitions), and Tatoeba serves about one clip a minute (200 clips).

The files are:

- `tools/exp_speech/stimuli.py` selects items and makes clips.
- `tools/exp_speech/stt.py` drives Chrome. Run `python stt.py --probe <wav>` to compare the input routes.
- `tools/exp_speech/tonecheck.py` is the importable tone check.
- `tools/exp_speech/selfcheck.py` runs the 10-clip check.

Chrome's plain `recognition.start()` ignores `--use-file-for-fake-audio-capture` and hears silence. The experiment instead passes a WebAudio track to `start(track)`, with faint noise like a real microphone. On a 0.8 s post-roll of digital silence the recognizer dropped the final syllable.
