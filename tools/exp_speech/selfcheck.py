"""Five-minute check of tonecheck on your own voice.

Record 10 clips (QuickTime Player > File > New Audio Recording, one word per clip) into one folder,
named 01 to 10 with any of .wav .m4a .aiff, in the order of PROMPTS. Then run

	tools/exp_speech/.venv/bin/python tools/exp_speech/selfcheck.py <folder> [--stt]

Odd clips are said correctly, even clips with one deliberate wrong tone. A useful checker flags none of the
odd clips and flags the named syllable in most of the even clips. Each syllable shows the tone whose
template fits best and, after "by", how much worse the expected tone fits (Chao units); tonecheck flags a
syllable when that exceeds its margin. The summary counts at two margins. --stt also sends the clips to
Chrome's speech recognition and shows whether each transcript matches the target's toned pinyin.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

from pypinyin import Style, lazy_pinyin

import stt
import tonecheck as tc

# (chars, pinyin you should say, syllable index you change or None, what to say instead)
PROMPTS = [
	("中国", "zhong1 guo2", None, "zhōngguó"),
	("中国", "zhong1 guo2", 0, "zhòngguó: first syllable falling (T4)"),
	("没有", "mei2 you3", None, "méiyǒu"),
	("没有", "mei2 you3", 0, "měiyǒu: first syllable low (T3)"),
	("学习", "xue2 xi2", None, "xuéxí"),
	("学习", "xue2 xi2", 1, "xuéxì: second syllable falling (T4)"),
	("开始", "kai1 shi3", None, "kāishǐ"),
	("开始", "kai1 shi3", 1, "kāishí: second syllable rising (T2)"),
	("问题", "wen4 ti2", None, "wèntí"),
	("问题", "wen4 ti2", 0, "wēntí: first syllable level (T1)"),
]


def to_wav(src: Path, tmp: Path) -> Path:
	if src.suffix.lower() == ".wav":
		return src
	out = tmp / (src.stem + ".wav")
	subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(src), str(out)], check=True)
	return out


def main(folder: str, with_stt: bool) -> None:
	files = {p.stem: p for p in Path(folder).iterdir() if p.suffix.lower() in (".wav", ".m4a", ".aiff", ".caf")}
	with tempfile.TemporaryDirectory() as t:
		wavs = [to_wav(files[f"{k + 1:02d}"], Path(t)) for k in range(len(PROMPTS))]
		heard = {}
		if with_stt:
			ids = [f"selfcheck:{Path(folder).resolve()}/{k + 1:02d}" for k in range(len(PROMPTS))]
			cache = asyncio.run(stt.transcribe(list(zip(ids, wavs)), tag="self"))
			heard = {k: ((cache[f"self|{i}"]["alts"] or [[""]])[0][0]) for k, i in enumerate(ids)}
		f0s = [tc.analyze(w, 2)[1] for w in wavs]
		speaker = tc.baseline(f0s)  # your register, from all ten clips
		print(f"your register: median {speaker.median_hz:.0f} Hz, range {speaker.hi_st - speaker.lo_st:.1f} semitones")
		margins = (0.5, tc.MARGIN)
		false_alarms, hits = dict.fromkeys(margins, 0), dict.fromkeys(margins, 0)
		for k, ((chars, py, wrong_at, say), w) in enumerate(zip(PROMPTS, wavs)):
			v = tc.check(str(w), py, chars, speaker=speaker)
			gaps = [min(x.distance[t] for t in x.expected) - x.distance[x.heard] if x.ok is not None else None for x in v]
			for m in margins:
				flagged = [i for i, g in enumerate(gaps) if g is not None and g > m]
				if wrong_at is None:
					false_alarms[m] += bool(flagged)
				else:
					hits[m] += wrong_at in flagged
			shown = "  ".join(f"{x.pinyin}: heard T{x.heard}" + (f" by {g:.2f}" if g else "") + ("" if x.ok else " (flagged)")
				for x, g in zip(v, gaps))
			if k in heard:
				same = lazy_pinyin(heard[k], style=Style.TONE3, neutral_tone_with_five=True) == py.split()
				shown += f"  | STT: {heard[k] or '(nothing)'}" + ("" if same else " (mismatch)")
			print(f"{k + 1:02d} {chars} said as {say:42s} {shown}")
	print()
	for m in margins:
		print(f"margin {m}: correct clips flagged {false_alarms[m]}/5, wrong clips caught at the right syllable {hits[m]}/5")


if __name__ == "__main__":
	main(sys.argv[1], "--stt" in sys.argv[2:])
