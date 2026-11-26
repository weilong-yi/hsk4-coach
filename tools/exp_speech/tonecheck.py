"""Per-syllable Mandarin tone check from pitch.

check(wav_path, "xue2 sheng1") -> one Verdict per syllable.

Pipeline: F0 track (Praat, two-pass range) -> split the voiced stretch into N syllables
(N from the pinyin) at voicing gaps, then at intensity dips -> 5-point contour per syllable
on the Chao 1-5 scale of the speaker's own range -> nearest canonical tone template.
A syllable is flagged when its expected tone fits clearly worse than another tone (MARGIN).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import parselmouth

STEP = 0.01
POINTS = 5

# Chao-scale templates, 5 points across the voiced part of the syllable; a tone may have several shapes
# and matches its closest one. Final syllables may sit lower (final lowering, which not every speaker
# does), T2 may dip before it rises, and T3 may end without the rise.
TEMPLATES = {
	True: {  # utterance-final syllable
		1: [[4, 4, 4, 4, 4], [5, 5, 5, 5, 5]],
		2: [[2.5, 2.3, 2.7, 3.5, 4.3], [2.8, 2.2, 2.1, 2.8, 3.8], [3, 2.8, 3.2, 4, 5]],
		3: [[2.5, 1.5, 1, 1.5, 3], [2.3, 1.6, 1.1, 1, 1]],
		4: [[5, 4.5, 3.5, 2.3, 1]],
	},
	False: {  # non-final: half-third T3, shortened T4 fall
		1: [[5, 5, 5, 5, 5]],
		2: [[3, 2.8, 3.2, 4, 5], [3.2, 2.6, 2.6, 3.4, 4.4]],
		3: [[2.5, 1.8, 1.2, 1, 1]],
		4: [[5, 4.6, 4, 3.4, 2.8]],
	},
}
LEVEL_WEIGHT = 0.7  # how much an overall level offset counts against a template, relative to shape error
MARGIN = 0.25  # Chao units: flag only when the expected tone is this much worse than the best tone


@dataclass(frozen=True)
class Baseline:
	"""A speaker's pitch register: median F0 and the 5th/95th percentiles in semitones re that median."""
	median_hz: float
	lo_st: float
	hi_st: float


@dataclass(frozen=True)
class Syllable:
	pinyin: str
	tones: frozenset  # acceptable surface tones; empty means not checked (neutral tone)
	final: bool


@dataclass(frozen=True)
class Segment:
	start: float
	end: float
	contour: tuple | None  # POINTS values on the Chao 1-5 scale, None if too little voicing


@dataclass(frozen=True)
class Verdict:
	pinyin: str
	expected: tuple  # acceptable surface tones
	heard: int | None  # best-matching template tone
	ok: bool | None  # None: not checked (neutral tone, or no usable pitch)
	start: float
	end: float
	contour: tuple | None
	distance: dict  # tone -> template distance


# ---------- expected tones ----------

SYL = re.compile(r"^([a-zü:v]+?)([1-5])$", re.I)


def parse_pinyin(num: str) -> list[tuple[str, int]]:
	"""'xue2 sheng5' -> [('xue', 2), ('sheng', 5)]. Bare syllables count as neutral."""
	out = []
	for s in num.replace("'", " ").split():
		m = SYL.match(s)
		out.append((m.group(1).lower(), int(m.group(2))) if m else (s.lower(), 5))
	return out


def expected_tones(num: str, chars: str | None = None) -> list[Syllable]:
	"""Citation tones to acceptable surface tones (3-3 sandhi, and 不/一 sandhi when chars are given)."""
	syl = parse_pinyin(num)
	t = [x[1] for x in syl]
	n = len(t)
	ch = [c for c in (chars or "") if "一" <= c <= "鿿"]
	if len(ch) != n:
		ch = [None] * n
	acc = []
	for i, tone in enumerate(t):
		nxt = t[i + 1] if i + 1 < n else None
		if tone == 5:
			s = set()
		elif ch[i] == "不" and tone == 4:
			s = {2} if nxt == 4 else {4}
		elif ch[i] == "一" and tone == 1:
			s = {1} if nxt in (None, 5) else ({2} if nxt == 4 else {4})
		elif ch[i] is None and syl[i][0] == "bu" and tone == 4 and nxt == 4:
			s = {2, 4}
		elif ch[i] is None and syl[i][0] == "yi" and tone == 1 and nxt is not None:
			s = {1, 2, 4}
		elif tone == 3 and nxt == 3:
			s = {2} if n == 2 else {2, 3}  # word-internal 3-3 is certain; across words it depends on phrasing
		elif tone == 3 and nxt == 5:
			s = {2, 3}
		else:
			s = {tone}
		acc.append(Syllable(f"{syl[i][0]}{tone}", frozenset(s), i == n - 1))
	return acc


# ---------- acoustics ----------

def _pitch(snd: parselmouth.Sound, floor: float, ceiling: float) -> tuple[np.ndarray, np.ndarray]:
	p = snd.to_pitch_ac(time_step=STEP, pitch_floor=floor, pitch_ceiling=ceiling)
	return p.xs(), p.selected_array["frequency"]


def fix_octaves(f0: np.ndarray) -> np.ndarray:
	"""Undo halving and doubling. Inside a voiced run, a jump of more than 9 semitones in one frame is a
	tracking error (usually halving in creak), so pieces move by whole octaves to join the run's highest
	piece. A whole run more than 13 semitones below the upper quartile moves up an octave. A whole run
	closer than that stays: an octave below the rest is also where a low T3 after a high T1 can sit."""
	f = f0.copy()
	st = np.zeros_like(f)
	st[f > 0] = 12 * np.log2(f[f > 0] / 100)
	runs = _runs(f > 0)
	for a, b in runs:
		cuts = [a] + [i for i in range(a + 1, b) if abs(st[i] - st[i - 1]) > 9] + [b]
		pieces = list(zip(cuts[:-1], cuts[1:]))
		anchor = max(range(len(pieces)), key=lambda k: np.median(st[pieces[k][0]:pieces[k][1]]))
		for k in list(range(anchor - 1, -1, -1)) + list(range(anchor + 1, len(pieces))):
			p0, p1 = pieces[k]
			edge = st[pieces[k + 1][0]] if k < anchor else st[pieces[k - 1][1] - 1]
			near = st[p1 - 1] if k < anchor else st[p0]
			st[p0:p1] += 12 * round((edge - near) / 12)
	if runs:
		q3 = np.percentile(st[f > 0], 75)
		for a, b in runs:
			if np.median(st[a:b]) < q3 - 13:
				st[a:b] += 12
	f[f > 0] = 100 * 2 ** (st[f > 0] / 12)
	return f


def track(snd: parselmouth.Sound) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
	"""Frame times, F0 in Hz (0 = unvoiced), intensity in dB at the same times."""
	t, f0 = _pitch(snd, 50, 700)
	f0 = fix_octaves(f0)
	v = f0[f0 > 0]
	if len(v) >= 10:
		q1, q3 = np.percentile(v, [25, 75])
		t, f0 = _pitch(snd, max(40.0, 0.75 * q1), min(900.0, 1.75 * q3))
		f0 = fix_octaves(f0)
	it = snd.to_intensity(minimum_pitch=100, time_step=STEP)
	inten = np.interp(t, it.xs(), it.values[0])
	return t, f0, inten


def _runs(mask: np.ndarray) -> list[list[int]]:
	out, start = [], None
	for i, m in enumerate(mask):
		if m and start is None:
			start = i
		elif not m and start is not None:
			out.append([start, i])
			start = None
	if start is not None:
		out.append([start, len(mask)])
	return out


def segment(f0: np.ndarray, inten: np.ndarray, n: int) -> list[tuple[int, int]]:
	"""Split voiced frames into n syllable spans [i0, i1). Gaps first, then intensity dips."""
	loud = inten > inten.max() - 30
	voiced = (f0 > 0) & loud
	for i in range(1, len(voiced) - 2):  # close 1-2 frame dropouts
		if not voiced[i] and voiced[i - 1] and (voiced[i + 1] or voiced[i + 2]):
			voiced[i] = True
	runs = [r for r in _runs(voiced) if r[1] - r[0] >= 3]
	while len(runs) > n:
		k = int(np.argmin([runs[j + 1][0] - runs[j][1] for j in range(len(runs) - 1)]))
		runs[k:k + 2] = [[runs[k][0], runs[k + 1][1]]]
	sm = np.convolve(inten, np.ones(3) / 3, mode="same")
	min_len = 5
	while 0 < len(runs) < n:
		best = None
		for k, (a, b) in enumerate(runs):
			if b - a < 2 * min_len:
				continue
			for j in range(a + min_len, b - min_len + 1):
				if not (sm[j] <= sm[j - 1] and sm[j] <= sm[j + 1]):
					continue
				depth = min(sm[a:j].max(), sm[j:b].max()) - sm[j]
				score = depth + 0.02 * (b - a)
				if best is None or score > best[0]:
					best = (score, k, j)
		if best is None:  # no dip: halve the longest run
			k = int(np.argmax([b - a for a, b in runs]))
			a, b = runs[k]
			if b - a < 2 * min_len:
				break
			best = (0, k, (a + b) // 2)
		_, k, j = best
		a, b = runs[k]
		runs[k:k + 1] = [[a, j], [j, b]]
	return [tuple(r) for r in runs]


def baseline(f0s: list[np.ndarray]) -> Baseline:
	"""Register from one or more F0 tracks (Hz, 0 = unvoiced)."""
	v = np.concatenate([f[f > 0] for f in f0s])
	med = float(np.median(v))
	st = 12 * np.log2(v / med)
	lo, hi = np.percentile(st, [5, 95])
	if hi - lo < 4:  # a single short word can span almost nothing; assume a typical 8-semitone range
		lo, hi = -4.0, 4.0
	return Baseline(med, float(lo), float(hi))


def contour(f0: np.ndarray, span: tuple[int, int], base: Baseline) -> tuple | None:
	seg = f0[span[0]:span[1]]
	seg = seg[seg > 0]
	if len(seg) < POINTS:
		return None
	trim = max(1, int(round(len(seg) * 0.1)))
	seg = seg[trim:len(seg) - trim] if len(seg) - 2 * trim >= POINTS else seg
	st = 12 * np.log2(seg / base.median_hz)
	mid = np.median(st)
	st = np.where(st - mid > 7, st - 12, np.where(mid - st > 7, st + 12, st))  # fold octave jumps
	chao = 1 + 4 * (st - base.lo_st) / (base.hi_st - base.lo_st)
	bins = np.array_split(chao, POINTS)
	return tuple(round(float(b.mean()), 3) for b in bins)


def analyze(wav_path: str, n: int, base: Baseline | None = None) -> tuple[list[Segment], np.ndarray]:
	"""Segments for n syllables, plus the raw F0 track (for building a Baseline)."""
	snd = parselmouth.Sound(str(wav_path))
	if snd.n_channels > 1:
		snd = snd.convert_to_mono()
	t, f0, inten = track(snd)
	base = base or baseline([f0])
	spans = segment(f0, inten, n)
	segs = [Segment(float(t[a]), float(t[b - 1]), contour(f0, (a, b), base)) for a, b in spans]
	return segs + [Segment(0.0, 0.0, None)] * (n - len(segs)), f0


# ---------- decisions ----------

def template_distances(c, final: bool) -> dict:
	c = np.asarray(c)
	out = {}
	for tone, shapes in TEMPLATES[final].items():
		best = np.inf
		for tpl in shapes:
			diff = c - np.asarray(tpl)
			b = diff.mean()
			best = min(best, np.hypot(np.sqrt(np.mean((diff - b) ** 2)), LEVEL_WEIGHT * b))
		out[tone] = round(float(best), 3)
	return out


def judge(syls: list[Syllable], segs: list[Segment], margin: float = MARGIN) -> list[Verdict]:
	out = []
	for s, g in zip(syls, segs):
		if not s.tones or g.contour is None:
			out.append(Verdict(s.pinyin, tuple(sorted(s.tones)), None, None, g.start, g.end, g.contour, {}))
			continue
		d = template_distances(g.contour, s.final)
		heard = min(d, key=d.get)
		ok = min(d[t] for t in s.tones) - d[heard] <= margin
		out.append(Verdict(s.pinyin, tuple(sorted(s.tones)), heard, bool(ok), g.start, g.end, g.contour, d))
	return out


def check(wav_path: str, pinyin: str, chars: str | None = None, speaker: Baseline | None = None,
		margin: float = MARGIN) -> list[Verdict]:
	"""Per-syllable verdicts for a recording of `pinyin` (numeric, e.g. 'xue2 sheng1').

	chars: the characters, which enable 不/一 sandhi. speaker: the learner's register from earlier
	recordings (see `baseline`); without it the register comes from this clip alone, which is weak for
	one or two syllables.
	"""
	syls = expected_tones(pinyin, chars)
	segs, _ = analyze(wav_path, len(syls), speaker)
	return judge(syls, segs, margin)
