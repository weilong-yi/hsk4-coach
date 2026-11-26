"""Behavior checks for tonecheck. Run: tools/exp_speech/.venv/bin/python tools/exp_speech/test_tonecheck.py"""
import itertools
import tempfile
import wave
from pathlib import Path

import numpy as np

import tonecheck as tc

SR = 16000
# Semitones re 200 Hz at the start, middle and end of a syllable.
SHAPES = {1: (5, 5, 5), 2: (0, 1, 5), 3: (-2, -6, -5), 4: (5, 1, -5)}


def syllable(tone: int, dur: float = 0.25) -> np.ndarray:
	t = np.linspace(0, 1, int(SR * dur))
	st = np.interp(t, [0, 0.5, 1], SHAPES[tone])
	phase = 2 * np.pi * np.cumsum(200 * 2 ** (st / 12)) / SR
	buzz = sum(np.sin(k * phase) / k for k in range(1, 12))
	return buzz * np.hanning(len(t)) ** 0.3


def write(path: Path, tones: tuple) -> None:
	gap = np.zeros(int(SR * 0.08))
	x = np.concatenate([gap] + [np.concatenate([syllable(t), gap]) for t in tones])
	with wave.open(str(path), "wb") as w:
		w.setnchannels(1)
		w.setsampwidth(2)
		w.setframerate(SR)
		w.writeframes((x / np.abs(x).max() * 0.5 * 32767).astype(np.int16).tobytes())


def test_two_syllable_tones() -> None:
	combos = [c for c in itertools.product((1, 2, 3, 4), repeat=2) if c != (3, 3)]
	with tempfile.TemporaryDirectory() as d:
		paths = {}
		for c in combos:
			paths[c] = Path(d) / f"{c[0]}{c[1]}.wav"
			write(paths[c], c)
		speaker = tc.baseline([tc.analyze(p, 2)[1] for p in paths.values()])
		wrong = []
		for c, p in paths.items():
			v = tc.check(str(p), f"ma{c[0]} ma{c[1]}", speaker=speaker)
			if [x.heard for x in v] != list(c) or not all(x.ok for x in v):
				wrong.append((c, [x.heard for x in v]))
			said_as = (c[0] % 4) + 1  # the same audio checked against another first tone must be flagged
			if said_as != 3 or c[1] != 3:
				v2 = tc.check(str(p), f"ma{said_as} ma{c[1]}", speaker=speaker)
				assert v2[0].ok is False, (c, said_as, v2[0])
		assert not wrong, wrong


def test_expected_tones() -> None:
	acc = lambda num, chars=None: [sorted(s.tones) for s in tc.expected_tones(num, chars)]
	assert acc("ni3 hao3") == [[2], [3]]  # word-internal 3-3 sandhi
	assert acc("wo3 hen3 hao3") == [[2, 3], [2, 3], [3]]  # across words, either is accepted
	assert acc("bu4 shi4", "不是") == [[2], [4]]
	assert acc("yi1 ge4", "一个") == [[2], [4]]
	assert acc("yi1 tian1", "一天") == [[4], [1]]
	assert acc("xue2 sheng5") == [[2], []]  # neutral tone is not checked
	assert acc("yi1 sheng1", "医生") == [[1], [1]]


if __name__ == "__main__":
	test_expected_tones()
	test_two_syllable_tones()
	print("ok")
