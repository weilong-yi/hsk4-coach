"""Build the test clips: item selection, macOS voice renders, PSOLA wrong-tone variants, native downloads.

Writes cache/manifest.json: {"items": [...], "clips": [...], "baselines": {...}}. Every step skips work whose
output file already exists, so a rerun only fills gaps.
"""
from __future__ import annotations

import csv
import io
import json
import random
import subprocess
import tarfile
import time
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np
import parselmouth
from parselmouth.praat import call
from pypinyin import Style, lazy_pinyin

import tonecheck as tc

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "data"
CACHE = HERE / "cache"
VOICES = ["Tingting", "Eddy", "Flo", "Grandpa", "Sandy"]
N_WORDS, N_SENT_E1, N_SENT_E2 = 40, 20, 40
VOICELESS = ("b", "p", "d", "t", "g", "k", "j", "q", "x", "zh", "ch", "sh", "z", "c", "s", "f", "h")


def say_name(v: str) -> str:
	return v if v == "Tingting" else f"{v} (Chinese (China mainland))"  # bare names also match the zh_TW voice


def is_cjk(s: str) -> bool:
	return bool(s) and all("一" <= c <= "鿿" for c in s)


def strip_punct(s: str) -> str:
	return "".join(c for c in s if c not in "，。！？、；：,.!?;: “”\"'（）()《》…—")


def pinyin_of(chars: str) -> list[str]:
	return lazy_pinyin(chars, style=Style.TONE3, neutral_tone_with_five=True)


def sentence_tones(chars: str, toks: list[str], words: dict) -> tuple[str, list[frozenset]] | None:
	"""Numeric pinyin from pypinyin (context-aware), with each syllable's acceptable tones.

	Where words.json and pypinyin disagree on a tone, accept both; where either says neutral, do not check.
	"""
	p = pinyin_of(chars)
	w = " ".join(words[t]["num"] for t in toks if t in words).lower().split()
	if len(p) != len(chars) or len(w) != len(p):
		return None
	num = " ".join(p)
	base = tc.expected_tones(num, chars)
	acc = []
	for s, a, b in zip(base, p, w):
		ta, tb = int(a[-1]) if a[-1].isdigit() else 5, int(b[-1]) if b[-1].isdigit() else 5
		if 5 in (ta, tb):
			acc.append(frozenset())
		elif ta != tb:
			acc.append(frozenset(s.tones | {tb}))
		else:
			acc.append(s.tones)
	return num, acc


def select_items() -> list[dict]:
	words = {w["w"]: w for w in json.load(open(DATA / "words.json"))}
	sents = json.load(open(DATA / "sentences.json"))
	items = []

	# E1 words: two-syllable HSK 1-3, no neutral tone, no 3-3 sandhi, no 一/不, words.json agrees with pypinyin.
	by_combo: dict[tuple, list] = {}
	for w in sorted(words.values(), key=lambda x: x["rank"]):
		num = w["num"].lower().split()
		if w["lvl"] > 3 or len(w["w"]) != 2 or len(num) != 2 or not is_cjk(w["w"]) or set(w["w"]) & {"一", "不", "儿"}:
			continue
		tones = tuple(int(s[-1]) for s in num)
		if 5 in tones or tones == (3, 3) or pinyin_of(w["w"]) != num:
			continue
		by_combo.setdefault(tones, []).append(w)
	combos = sorted(by_combo)
	picked, depth = [], 0
	while len(picked) < N_WORDS:
		for c in combos:
			if depth < len(by_combo[c]) and len(picked) < N_WORDS:
				picked.append(by_combo[c][depth])
		depth += 1
	for w in picked:
		syl2 = w["num"].lower().split()[1]
		items.append({"id": f"w:{w['w']}", "kind": "word", "exp": "E1", "chars": w["w"], "pinyin": w["num"].lower(),
			"expected": [sorted(s.tones) for s in tc.expected_tones(w["num"].lower(), w["w"])],
			"gap": syl2.startswith(VOICELESS)})

	# Sentences: every character Chinese, every token an HSK word, pinyin resolvable.
	def clean(s, max_lvl):
		zh = strip_punct(s["zh"])
		if s["lvl"] > max_lvl or not is_cjk(zh) or zh != "".join(s["tok"]):
			return None
		r = sentence_tones(zh, s["tok"], words)
		return (zh, *r) if r else None

	rng = random.Random(0)
	e1 = [s for s in sents if s["lvl"] <= 3 and 4 <= len(strip_punct(s["zh"])) <= 8 and not set(s["zh"]) & {"一", "不", "儿"}]
	rng.shuffle(e1)
	for s in e1:
		r = clean(s, 3)
		if r and sum(1 for t in r[2] if len(t) == 1) >= 2:
			items.append({"id": f"s:{s['id']}", "kind": "sentence", "exp": "E1", "chars": r[0], "pinyin": r[1],
				"expected": [sorted(t) for t in r[2]], "en": s["en"]})
		if sum(1 for i in items if i["kind"] == "sentence") == N_SENT_E1:
			break

	native = [s for s in sents if s["lvl"] <= 4 and s["audio"]]
	rng.shuffle(native)
	speakers = audio_speakers()
	n = 0
	for s in native:
		r = clean(s, 4)
		if r and len(r[0]) >= 3:
			items.append({"id": f"n:{s['id']}", "kind": "sentence", "exp": "E2", "chars": r[0], "pinyin": r[1],
				"expected": [sorted(t) for t in r[2]], "en": s["en"], "audio": s["audio"]})
			n += 1
		if n == N_SENT_E2:
			break
	# Native clips as correct human speech for measuring false alarms (pitch only): every usable clip of
	# 3-6 syllables, plus the E2 clips for longer ones. Tatoeba serves about one clip a minute.
	e2_audio = {i["audio"] for i in items if i["exp"] == "E2"}
	for s in sorted(native, key=lambda s: s["id"]):
		r = clean(s, 4)
		if r and (3 <= len(r[0]) <= 6 or s["audio"] in e2_audio):
			items.append({"id": f"h:{s['id']}", "kind": "sentence", "exp": "H", "chars": r[0], "pinyin": r[1],
				"expected": [sorted(t) for t in r[2]], "audio": s["audio"], "speaker": speakers.get(s["audio"], "?")})
	return items


def audio_speakers() -> dict[int, str]:
	"""Tatoeba audio id -> contributor username, from the sentences_with_audio export."""
	with tarfile.open(DATA / "raw" / "sentences_with_audio.tar.bz2") as t:
		f = t.extractfile(t.getmember("sentences_with_audio.csv"))
		return {int(r[1]): r[2] for r in csv.reader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t") if len(r) > 2}


def render(voice: str, text: str, out: Path) -> None:
	if out.exists():
		return
	out.parent.mkdir(parents=True, exist_ok=True)
	subprocess.run(["say", "-v", say_name(voice), "-o", str(out), "--file-format=WAVE", "--data-format=LEI16@16000", text], check=True)


def fetch_native(audio_id: int, out: Path) -> None:
	"""Download one Tatoeba clip and convert it to 16 kHz mono WAV. Both files appear only when complete."""
	if out.exists():
		return
	out.parent.mkdir(parents=True, exist_ok=True)
	mp3 = out.with_suffix(".mp3")
	if not mp3.exists():
		req = urllib.request.Request(f"https://tatoeba.org/audio/download/{audio_id}", headers={"User-Agent": "exp-speech/0.1"})
		tmp = mp3.with_suffix(".part")
		tmp.write_bytes(urllib.request.urlopen(req, timeout=120).read())
		tmp.rename(mp3)
		time.sleep(0.5)
	tmp = out.with_suffix(".tmp.wav")
	subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(mp3), str(tmp)], check=True)
	tmp.rename(out)


def f0_frames(wav: Path, span: tuple[float, float]) -> np.ndarray:
	"""Voiced F0 values (Hz) inside a time span."""
	snd = parselmouth.Sound(str(wav))
	t, f0, _ = tc.track(snd)
	m = (t >= span[0]) & (t <= span[1]) & (f0 > 0)
	return f0[m]


def psola(src: Path, out: Path, base: tc.Baseline, span: tuple[float, float] | None = None, donor_hz: np.ndarray | None = None) -> None:
	"""Overlap-add resynthesis. With a span and donor F0 values, the span's pitch follows the donor contour.
	Skips the work when `out` was made from the same inputs (recorded in a .key file beside it)."""
	inputs = json.dumps([str(src), base.median_hz, span, None if donor_hz is None else np.round(donor_hz, 2).tolist()])
	key = out.with_suffix(".key")
	if out.exists() and key.exists() and key.read_text() == inputs:
		return
	out.parent.mkdir(parents=True, exist_ok=True)
	key.write_text(inputs)
	snd = parselmouth.Sound(str(src))
	manip = call(snd, "To Manipulation", 0.01, max(40.0, 0.5 * base.median_hz), min(900.0, 2.2 * base.median_hz))
	if span is not None:
		pt = call(manip, "Extract pitch tier")
		t0, t1 = span
		call(pt, "Remove points between", t0 - 0.005, t1 + 0.005)
		for u, hz in zip(np.linspace(0, 1, len(donor_hz)), donor_hz):
			call(pt, "Add point", t0 + u * (t1 - t0), float(hz))
		call([pt, manip], "Replace pitch tier")
	res = call(manip, "Get resynthesis (overlap-add)")
	res.save(str(out), "WAV")


def chao_rms(a, b) -> float | None:
	if a is None or b is None:
		return None
	return round(float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2))), 3)


def build() -> dict:
	CACHE.mkdir(exist_ok=True)
	items = select_items()
	clips = []
	for it in items:
		key = it["id"].replace(":", "_")
		if it["exp"] == "H":
			p = CACHE / "native" / f"{it['audio']}.wav"
			fetch_native(it["audio"], p)
			clips.append({"id": f"native|raw|{it['id']}", "item": it["id"], "voice": "native", "variant": "raw",
				"speaker": it["speaker"], "wav": str(p.relative_to(HERE))})
			continue
		for v in VOICES:
			p = CACHE / "raw" / v / f"{key}.wav"
			render(v, it["chars"], p)
			clips.append({"id": f"{v}|raw|{it['id']}", "item": it["id"], "voice": v, "variant": "raw", "wav": str(p.relative_to(HERE))})
		if it["exp"] == "E2":
			p = CACHE / "native" / f"{it['audio']}.wav"
			fetch_native(it["audio"], p)
			clips.append({"id": f"native|raw|{it['id']}", "item": it["id"], "voice": "native", "variant": "raw", "wav": str(p.relative_to(HERE))})

	# Per-voice register from all raw renders (an app gets this from the learner's past recordings).
	segs, f0s = {}, {}
	for c in clips:
		it = next(i for i in items if i["id"] == c["item"])
		_, f0 = tc.analyze(HERE / c["wav"], len(it["expected"]))
		f0s.setdefault(c["voice"], []).append(f0)
	bases = {v: tc.baseline(f) for v, f in f0s.items() if v != "native"}
	spk: dict[str, list] = {}
	for c in clips:
		if c.get("speaker"):
			it = next(i for i in items if i["id"] == c["item"])
			spk.setdefault(c["speaker"], []).append(tc.analyze(HERE / c["wav"], len(it["expected"]))[1])
	speaker_bases = {k: vars(tc.baseline(v)) for k, v in spk.items()}
	for c in clips:
		it = next(i for i in items if i["id"] == c["item"])
		b = bases.get(c["voice"]) or tc.baseline([tc.analyze(HERE / c["wav"], len(it["expected"]))[1]])
		segs[c["id"]] = tc.analyze(HERE / c["wav"], len(it["expected"]), b)[0]

	# Wrong-tone plan, identical across voices: target syllable and a new tone, balancing (from, to) pairs.
	pair_count: Counter = Counter()
	plan = {}
	for k, it in enumerate(i for i in items if i["exp"] == "E1"):
		cands = [j for j, t in enumerate(it["expected"]) if len(t) == 1]
		j = cands[k % len(cands)] if it["kind"] == "sentence" else k % 2
		frm = it["expected"][j][0]
		to = min((t for t in (1, 2, 3, 4) if t != frm), key=lambda t: (pair_count[(frm, t)], (t - frm) % 4))
		pair_count[(frm, to)] += 1
		plan[it["id"]] = (j, frm, to)

	def donor(voice, it, j, to):
		"""Same voice, same item kind and position class, syllable whose only acceptable tone is `to`."""
		n = len(it["expected"])
		tgt = segs[f"{voice}|raw|{it['id']}"][j]
		best = None
		for o in items:
			if o["exp"] != "E1" or o["kind"] != it["kind"] or o["id"] == it["id"]:
				continue
			for jj, t in enumerate(o["expected"]):
				same_pos = jj == j if it["kind"] == "word" else (jj == len(o["expected"]) - 1) == (j == n - 1)
				if t != [to] or not same_pos:
					continue
				g = segs[f"{voice}|raw|{o['id']}"][jj]
				if g.contour is None:
					continue
				score = abs((g.end - g.start) - (tgt.end - tgt.start))
				if best is None or score < best[0]:
					best = (score, o, jj, g)
		return best

	for it in [i for i in items if i["exp"] == "E1"]:
		key = it["id"].replace(":", "_")
		j, frm, to = plan[it["id"]]
		for v in VOICES:
			raw = CACHE / "raw" / v / f"{key}.wav"
			ctrl = CACHE / "ctrl" / v / f"{key}.wav"
			psola(raw, ctrl, bases[v])
			clips.append({"id": f"{v}|ctrl|{it['id']}", "item": it["id"], "voice": v, "variant": "ctrl", "wav": str(ctrl.relative_to(HERE))})
			tgt = segs[f"{v}|raw|{it['id']}"][j]
			d = donor(v, it, j, to)
			rec = {"id": f"{v}|wrong|{it['id']}", "item": it["id"], "voice": v, "variant": "wrong", "target": j, "from": frm, "to": to}
			if d is None or tgt.contour is None:
				clips.append({**rec, "wav": None, "skip": "no donor or unvoiced target"})
				continue
			_, o, jj, g = d
			donor_hz = f0_frames(CACHE / "raw" / v / f"{o['id'].replace(':', '_')}.wav", (g.start, g.end))
			out = CACHE / "wrong" / v / f"{key}.wav"
			psola(raw, out, bases[v], (tgt.start, tgt.end), donor_hz)
			clips.append({**rec, "wav": str(out.relative_to(HERE)), "donor": f"{o['id']}#{jj}", "donor_contour": g.contour,
				"orig_contour": tgt.contour})

	# Validate each manipulation by measuring the resynthesized contour.
	for c in clips:
		if c["variant"] != "wrong" or not c.get("wav"):
			continue
		it = next(i for i in items if i["id"] == c["item"])
		got = tc.analyze(HERE / c["wav"], len(it["expected"]), bases[c["voice"]])[0]
		ctrl = tc.analyze(HERE / f"cache/ctrl/{c['voice']}/{it['id'].replace(':', '_')}.wav", len(it["expected"]), bases[c["voice"]])[0]
		j = c["target"]
		c["measured_contour"] = got[j].contour
		c["rms_to_donor"] = chao_rms(got[j].contour, c["donor_contour"])
		c["rms_to_orig"] = chao_rms(got[j].contour, c["orig_contour"])
		others = [chao_rms(got[k].contour, ctrl[k].contour) for k in range(len(got)) if k != j]
		others = [x for x in others if x is not None]
		c["rms_others_vs_ctrl"] = round(max(others), 3) if others else None
		c["valid"] = bool(c["rms_to_donor"] is not None and c["rms_to_orig"] is not None and c["rms_to_donor"] < c["rms_to_orig"])

	man = {"voices": VOICES, "items": items, "clips": clips,
		"baselines": {v: vars(b) for v, b in bases.items()}, "speaker_baselines": speaker_bases, "plan_pairs": {f"{a}->{b}": n for (a, b), n in sorted(pair_count.items())}}
	(CACHE / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1))
	return man


if __name__ == "__main__":
	m = build()
	print(len(m["items"]), "items,", len(m["clips"]), "clips")
	print(Counter((c["variant"], c["voice"]) for c in m["clips"] if c.get("wav")))
