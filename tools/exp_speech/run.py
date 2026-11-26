"""Entry point: rebuild clips, run Chrome STT and pitch analysis, write data/exp_speech.md.

	tools/exp_speech/.venv/bin/python tools/exp_speech/run.py            # everything (cached steps are skipped)
	tools/exp_speech/.venv/bin/python tools/exp_speech/run.py --no-stt   # pitch only, reuse cached STT
"""
from __future__ import annotations

import asyncio
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import stimuli
import stt
import tonecheck as tc

HERE = Path(__file__).resolve().parent
TABLES = HERE.parent.parent / "data" / "exp_speech_tables.md"
DIGITS = dict(zip("0123456789", "零一二三四五六七八九"))
REF_OF = {"Tingting": "Eddy"}  # reference speaker a 'learner' voice shadows; every other voice shadows Tingting


def norm(text: str) -> str:
	return "".join(DIGITS.get(c, c) for c in text if "一" <= c <= "鿿" or c.isdigit())


def toned(chars: str) -> list[str]:
	return stimuli.pinyin_of(chars) if chars else []


def edit_distance(a: str, b: str) -> int:
	d = list(range(len(b) + 1))
	for i, ca in enumerate(a, 1):
		prev, d[0] = d[0], i
		for j, cb in enumerate(b, 1):
			prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (ca != cb))
	return d[-1]


def stt_result(sttres: dict, clip: dict, tag: str = "run1") -> dict | None:
	"""The cached transcript for this clip, if it was made from the current wav file by the current method."""
	r = sttres.get(f"{tag}|{clip['id']}")
	return r if stt.fresh(r, HERE / clip["wav"]) else None


def repeat_subset(man: dict) -> list[dict]:
	"""200 clips transcribed a second time, to measure run-to-run agreement of the recognizer."""
	exp = {i["id"]: i["exp"] for i in man["items"]}
	clips = sorted((c for c in man["clips"] if c.get("wav") and exp[c["item"]] != "H"), key=lambda c: stt.hashlib.sha1(c["id"].encode()).hexdigest())
	return clips[:200]


def pct(n: int, d: int) -> str:
	return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


# ---------- pitch ----------

def pitch_segments(man: dict) -> dict:
	"""clip_id -> {"voice": [Segment...], "self": [Segment...]} with the voice-level and the clip-only register."""
	cache_path = HERE / "cache" / "pitch.json"
	cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
	items = {i["id"]: i for i in man["items"]}
	bases = {v: tc.Baseline(**b) for v, b in man["baselines"].items()}
	bases |= {f"speaker:{k}": tc.Baseline(**b) for k, b in man.get("speaker_baselines", {}).items()}
	out = {}
	for c in man["clips"]:
		if not c.get("wav"):
			continue
		w = HERE / c["wav"]
		who = f"speaker:{c['speaker']}" if c.get("speaker") else c["voice"]
		key = f"{c['id']}|{stt.sha1(w)}|{json.dumps(vars(bases[who]) if who in bases else None)}"
		if key not in cache:
			n = len(items[c["item"]]["expected"])
			segs_self, _ = tc.analyze(w, n)
			segs_voice = tc.analyze(w, n, bases[who])[0] if who in bases else segs_self
			cache[key] = {"voice": [vars(s) for s in segs_voice], "self": [vars(s) for s in segs_self]}
		out[c["id"]] = {k: [tc.Segment(**s) for s in v] for k, v in cache[key].items()}
	cache_path.write_text(json.dumps(cache))
	return out


def syllables(item: dict) -> list[tc.Syllable]:
	n = len(item["expected"])
	return [tc.Syllable(p, frozenset(t), i == n - 1) for i, (p, t) in enumerate(zip(item["pinyin"].split(), item["expected"]))]


# ---------- E1 ----------

def e1_rows(man: dict, segs: dict, sttres: dict) -> list[dict]:
	"""One row per E1 clip (ctrl or wrong) with each method's raw evidence."""
	items = {i["id"]: i for i in man["items"]}
	rows = []
	for c in man["clips"]:
		it = items[c["item"]]
		if it["exp"] != "E1" or c["variant"] not in ("ctrl", "wrong") or not c.get("wav"):
			continue
		syls = syllables(it)
		j = c.get("target")
		r = stt_result(sttres, c)
		top = norm(r["alts"][0][0]) if r and r["alts"] else ""
		exp_py, got_py = toned(it["chars"]), toned(top)
		wrong_py = None
		if j is not None:
			wrong_py = list(exp_py)
			wrong_py[j] = exp_py[j][:-1] + str(c["to"])
		ref_voice = REF_OF.get(c["voice"], "Tingting")
		ref = segs.get(f"{ref_voice}|raw|{it['id']}", {}).get("voice")
		rows.append({
			"clip": c["id"], "item": it["id"], "kind": it["kind"], "voice": c["voice"], "variant": c["variant"],
			"target": j, "from": c.get("from"), "to": c.get("to"), "valid": c.get("valid", True), "gap": it.get("gap"),
			"stt_done": r is not None, "stt_top": top, "stt_error": r and r["error"], "stt_match": got_py == exp_py,
			"stt_heard_wrong": wrong_py is not None and got_py == wrong_py,
			"stt_alts": [norm(a[0]) for a in (r or {}).get("alts", [])],
			"syls": syls, "segs": segs[c["id"]]["voice"], "segs_self": segs[c["id"]]["self"], "ref": ref,
		})
	return rows


def ref_distances(row: dict, loo_offset: bool) -> list[float | None]:
	"""Per-syllable RMS (Chao units) between the attempt's contour and the reference clip's.
	loo_offset: first remove the mean attempt-minus-reference level of the other syllables."""
	ref = row["ref"] or [tc.Segment(0, 0, None)] * len(row["syls"])
	pairs = [(np.asarray(a.contour), np.asarray(b.contour)) if s.tones and a.contour and b.contour else None
		for s, a, b in zip(row["syls"], row["segs"], ref)]
	out = []
	for i, p in enumerate(pairs):
		if p is None:
			out.append(None)
			continue
		others = [np.mean(q[0] - q[1]) for k, q in enumerate(pairs) if q is not None and k != i]
		off = float(np.mean(others)) if loo_offset and others else 0.0
		out.append(float(np.sqrt(np.mean((p[0] - p[1] - off) ** 2))))
	return out


def flags(row: dict, method: str, thr: float) -> list[bool | None]:
	if method in ("reference", "reference-offset"):
		return [None if d is None else bool(d > thr) for d in ref_distances(row, method == "reference-offset")]
	segs = row["segs_self"] if method == "template-self" else row["segs"]
	return [None if x.ok is None else not x.ok for x in tc.judge(row["syls"], segs, margin=thr)]


def score(rows: list[dict], method: str, thr: float) -> dict:
	"""Detection: the manipulated syllable is flagged. False alarm: any syllable of a control clip is flagged."""
	det = [r for r in rows if r["variant"] == "wrong" and r["valid"]]
	ctl = [r for r in rows if r["variant"] == "ctrl"]
	hit = sum(1 for r in det if flags(r, method, thr)[r["target"]] is True)
	fa = sum(1 for r in ctl if any(f is True for f in flags(r, method, thr)))
	syl_fa = sum(sum(1 for f in flags(r, method, thr) if f is True) for r in ctl)
	syl_n = sum(sum(1 for f in flags(r, method, thr) if f is not None) for r in ctl)
	return {"hit": hit, "n_wrong": len(det), "fa": fa, "n_ctrl": len(ctl), "syl_fa": syl_fa, "syl_n": syl_n}


def tune(rows: list[dict], method: str, grid: list[float], max_fa: float = 0.10) -> float:
	"""Lowest threshold whose item-level false-alarm rate on these rows is at most max_fa (most sensitive such)."""
	ok = [t for t in grid if (s := score(rows, method, t))["fa"] <= max_fa * s["n_ctrl"]]
	return min(ok) if ok else max(grid)


def split(rows: list[dict], man: dict) -> tuple[list, list]:
	"""Dev = even-indexed items within each kind, test = odd. Thresholds are picked on dev only."""
	order = defaultdict(list)
	for i in man["items"]:
		if i["exp"] == "E1":
			order[i["kind"]].append(i["id"])
	dev_items = {x for ids in order.values() for k, x in enumerate(ids) if k % 2 == 0}
	return [r for r in rows if r["item"] in dev_items], [r for r in rows if r["item"] not in dev_items]


# ---------- E2 ----------

def e2_rows(man: dict, segs: dict, sttres: dict) -> list[dict]:
	items = {i["id"]: i for i in man["items"]}
	rows = []
	for c in man["clips"]:
		it = items[c["item"]]
		if it["exp"] != "E2" or not c.get("wav"):
			continue
		r = stt_result(sttres, c)
		top = norm(r["alts"][0][0]) if r and r["alts"] else ""
		syls = syllables(it)
		v = tc.judge(syls, segs[c["id"]]["self"])
		rows.append({"clip": c["id"], "item": it["id"], "voice": c["voice"], "chars": it["chars"], "top": top, "stt_done": r is not None,
			"err": edit_distance(top, it["chars"]), "syl_err": edit_distance(toned(top), toned(it["chars"])),
			"n": len(it["chars"]), "verdicts": v, "segs": segs[c["id"]]["self"]})
	return rows


# ---------- report ----------

def table(header: list[str], rows: list[list]) -> str:
	return "\n".join([" | ".join(header), " | ".join("---" for _ in header)] + [" | ".join(map(str, r)) for r in rows])


def report(man: dict, segs: dict, sttres: dict) -> str:
	voices = man["voices"]
	items = {i["id"]: i for i in man["items"]}
	rows = e1_rows(man, segs, sttres)
	dev, test = split(rows, man)
	out = []

	# manipulation check
	wrong = [c for c in man["clips"] if c["variant"] == "wrong"]
	mrows = []
	for v in voices + ["all"]:
		cs = [c for c in wrong if v in ("all", c["voice"])]
		val = [c for c in cs if c.get("valid")]
		d = [c["rms_to_donor"] for c in cs if c.get("rms_to_donor") is not None]
		o = [c["rms_to_orig"] for c in cs if c.get("rms_to_orig") is not None]
		oth = [c["rms_others_vs_ctrl"] for c in cs if c.get("rms_others_vs_ctrl") is not None]
		mrows.append([v, pct(len(val), len(cs)), f"{st.median(d):.2f}" if d else "-", f"{st.median(o):.2f}" if o else "-",
			f"{np.percentile(oth, 90):.2f}" if oth else "-"])
	out.append(("manip", table(["voice", "valid variants", "median RMS to donor contour", "median RMS to original contour",
		"p90 RMS change on other syllables"], mrows)))

	# how alike the voices are: median contour distance between two voices' renders of the same E1 syllables
	vrows = []
	for a_i, a in enumerate(voices):
		for b in voices[a_i + 1:]:
			ds = []
			for it in (i for i in man["items"] if i["exp"] == "E1"):
				for x, y in zip(segs[f"{a}|raw|{it['id']}"]["voice"], segs[f"{b}|raw|{it['id']}"]["voice"]):
					if x.contour and y.contour:
						ds.append(float(np.sqrt(np.mean((np.asarray(x.contour) - np.asarray(y.contour)) ** 2))))
			vrows.append([a, b, len(ds), f"{st.median(ds):.2f}"])
	out.append(("voices", table(["voice", "voice", "syllables", "median contour distance (Chao units)"], vrows)))

	# STT sanity on unmodified renders and on identity resynthesis
	srows = []
	for v in voices:
		for kind in ("word", "sentence"):
			raw = [c for c in man["clips"] if c["voice"] == v and c["variant"] == "raw" and items[c["item"]]["exp"] == "E1" and items[c["item"]]["kind"] == kind]
			raw = [c for c in raw if stt_result(sttres, c)]
			ok_raw = sum(1 for c in raw if toned(norm((stt_result(sttres, c)["alts"] or [[""]])[0][0])) == toned(items[c["item"]]["chars"]))
			ctl = [r for r in rows if r["voice"] == v and r["variant"] == "ctrl" and r["kind"] == kind and r["stt_done"]]
			srows.append([v, kind, pct(ok_raw, len(raw)), pct(sum(r["stt_match"] for r in ctl), len(ctl))])
	rep = [c for c in repeat_subset(man) if stt_result(sttres, c) and stt_result(sttres, c, "run2")]
	same = sum(1 for c in rep if toned(norm((stt_result(sttres, c)["alts"] or [[""]])[0][0])) ==
		toned(norm((stt_result(sttres, c, "run2")["alts"] or [[""]])[0][0])))
	confs = Counter(round(r["alts"][0][1], 4) for k, r in sttres.items() if k.startswith("run1|") and r.get("alts") and r.get("method") == stt.METHOD)
	top_conf, top_n = confs.most_common(1)[0] if confs else (None, 0)
	group = lambda v: v if v in ("Tingting", "native") else "Eloquence voices"
	by_group = [[f"same toned transcript on a second pass, {g}",
		pct(sum(1 for c in rep if group(c["voice"]) == g and toned(norm((stt_result(sttres, c)["alts"] or [[""]])[0][0])) ==
			toned(norm((stt_result(sttres, c, "run2")["alts"] or [[""]])[0][0]))), sum(1 for c in rep if group(c["voice"]) == g))]
		for g in ("Tingting", "Eloquence voices", "native")]
	out.append(("stt_repeat", table(["check", "result"], [
		["same toned transcript on a second pass", pct(same, len(rep))], *by_group,
		["most common top-result confidence", f"{top_conf} on {pct(top_n, sum(confs.values()))} of transcripts"]])))
	out.append(("stt_sanity", table(["voice", "kind", "raw render transcribed as target", "PSOLA control transcribed as target"], srows)))

	# operating points from dev
	grid_t = [round(x, 2) for x in np.arange(0, 2.01, 0.05)]
	grid_r = [round(x, 2) for x in np.arange(0.2, 3.01, 0.05)]
	thr = {}
	for kind in ("word", "sentence"):
		dk = [r for r in dev if r["kind"] == kind]
		thr[("template", kind)] = tune(dk, "template", grid_t)
		thr[("template-self", kind)] = tune(dk, "template-self", grid_t)
		thr[("reference", kind)] = tune(dk, "reference", grid_r)
		thr[("reference-offset", kind)] = tune(dk, "reference-offset", grid_r)

	def method_rows(sub: list[dict]) -> list[list]:
		res = []
		for kind in ("word", "sentence"):
			for v in voices + ["all"]:
				rs = [r for r in sub if r["kind"] == kind and v in ("all", r["voice"])]
				det = [r for r in rs if r["variant"] == "wrong" and r["valid"] and r["stt_done"]]
				ctl = [r for r in rs if r["variant"] == "ctrl" and r["stt_done"]]
				ctl_ok = {(r["voice"], r["item"]) for r in ctl if r["stt_match"]}
				paired = [r for r in det if (r["voice"], r["item"]) in ctl_ok]
				line = [kind, v, pct(sum(not r["stt_match"] for r in det), len(det)), pct(sum(not r["stt_match"] for r in paired), len(paired)),
					pct(sum(r["stt_heard_wrong"] for r in det), len(det)), pct(sum(not r["stt_match"] for r in ctl), len(ctl))]
				for m in ("template", "reference-offset"):
					s = score(rs, m, thr[(m, kind)])
					line += [pct(s["hit"], s["n_wrong"]), pct(s["fa"], s["n_ctrl"])]
				res.append(line)
		return res

	hdr = ["kind", "voice", "STT: wrong item mis-transcribed", "STT: same, where its control was right", "STT: transcript has the wrong tone", "STT: control mis-transcribed",
		"pitch template: target flagged", "pitch template: control flagged", "pitch vs reference clip: target flagged", "pitch vs reference clip: control flagged"]
	out.append(("e1_test", table(hdr, method_rows(test))))
	out.append(("e1_all", table(hdr, method_rows(rows))))
	out.append(("thresholds", table(["method", "kind", "threshold picked on dev (FA <= 10%)"],
		[[m, k, t] for (m, k), t in sorted(thr.items())])))

	# syllable-level false alarms and the clip-only register ablation, test split
	arows = []
	for kind in ("word", "sentence"):
		tk = [r for r in test if r["kind"] == kind]
		for m in ("template", "template-self", "reference", "reference-offset"):
			s = score(tk, m, thr[(m, kind)])
			arows.append([kind, m, pct(s["hit"], s["n_wrong"]), pct(s["fa"], s["n_ctrl"]), pct(s["syl_fa"], s["syl_n"])])
	out.append(("ablation", table(["kind", "method", "target flagged", "control clip flagged", "control syllables flagged"], arows)))

	# sweep on all rows, words, for the threshold tradeoff
	sw = []
	for m, grid in (("template", [0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5]), ("reference-offset", [0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5])):
		for t in grid:
			cells = [m, t]
			for kind in ("word", "sentence"):
				s = score([r for r in rows if r["kind"] == kind], m, t)
				cells += [pct(s["hit"], s["n_wrong"]), pct(s["fa"], s["n_ctrl"])]
			sw.append(cells)
	out.append(("sweep", table(["method", "threshold", "words: target flagged", "words: control flagged", "sentences: target flagged",
		"sentences: control flagged"], sw)))

	# detection by confusion pair and by voicing gap, all rows, template + STT
	prow = []
	det_all = [r for r in rows if r["variant"] == "wrong" and r["valid"]]
	for pair in sorted({(r["from"], r["to"]) for r in det_all}):
		rs = [r for r in det_all if (r["from"], r["to"]) == pair]
		th = sum(1 for r in rs if flags(r, "template", thr[("template", r["kind"])])[r["target"]] is True)
		rf = sum(1 for r in rs if flags(r, "reference-offset", thr[("reference-offset", r["kind"])])[r["target"]] is True)
		ctl_ok = {(r["voice"], r["item"]) for r in rows if r["variant"] == "ctrl" and r["stt_done"] and r["stt_match"]}
		sd = [r for r in rs if r["stt_done"] and (r["voice"], r["item"]) in ctl_ok]
		prow.append([f"T{pair[0]} said as T{pair[1]}", len(rs), pct(sum(not r["stt_match"] for r in sd), len(sd)), pct(th, len(rs)), pct(rf, len(rs))])
	out.append(("pairs", table(["error", "clips", "STT mis-transcribed (control was right)", "pitch template flagged", "pitch vs reference flagged"], prow)))

	grow = []
	for g in (True, False):
		rs = [r for r in rows if r["kind"] == "word" and r["gap"] == g]
		for m in ("template", "reference-offset"):
			s = score(rs, m, thr[(m, "word")])
			grow.append(["voiceless initial on syllable 2" if g else "voiced or zero initial on syllable 2", m, pct(s["hit"], s["n_wrong"]), pct(s["fa"], s["n_ctrl"])])
	out.append(("gap", table(["word type", "method", "target flagged", "control flagged"], grow)))

	# E2
	e2 = e2_rows(man, segs, sttres)
	erows = []
	srcs = ["native"] + voices
	for s in srcs:
		rs = [r for r in e2 if r["voice"] == s]
		if not rs:
			continue
		done = [r for r in rs if r["stt_done"]]
		chars = max(1, sum(r["n"] for r in done))
		exact = sum(1 for r in done if r["syl_err"] == 0)
		checked = [v for r in rs for v in r["verdicts"] if v.ok is not None]
		agree = sum(1 for v in checked if v.heard in v.expected)
		m_s = thr[("template", "sentence")]
		agree_m = sum(1 for r in rs for v in tc.judge(syllables(items[r["item"]]), r["segs"], m_s) if v.ok)
		erows.append([s, len(rs), f"{100 * sum(r['err'] for r in done) / chars:.1f}%", f"{100 * sum(r['syl_err'] for r in done) / chars:.1f}%",
			pct(exact, len(done)), pct(agree, len(checked)), pct(agree_m, len(checked))])
	out.append(("e2", table(["source", "sentences", "STT character error rate", "STT toned-syllable error rate", "STT transcript matches every toned syllable",
		"syllables whose best template is the expected tone",
		f"syllables passing tonecheck (margin {thr[('template', 'sentence')]})"], erows)))

	# contour agreement with native, per voice
	crows = []
	nat = {r["item"]: r for r in e2 if r["voice"] == "native"}
	for v in voices:
		ds = []
		for r in e2:
			if r["voice"] != v or r["item"] not in nat:
				continue
			for a, b, s in zip(r["segs"], nat[r["item"]]["segs"], syllables(items[r["item"]])):
				if a.contour is not None and b.contour is not None and s.tones:
					ds.append(float(np.sqrt(np.mean((np.asarray(a.contour) - np.asarray(b.contour)) ** 2))))
		crows.append([v, len(ds), f"{st.median(ds):.2f}" if ds else "-", pct(sum(1 for d in ds if d <= 1.0), len(ds))])
	out.append(("e2_contour", table(["voice", "syllables compared", "median RMS to native contour (Chao units)", "within 1.0 of native"], crows)))

	# tonecheck on native speakers' correct speech: every flag is a false alarm
	hrows = []
	hclips = [c for c in man["clips"] if items[c["item"]]["exp"] == "H"]
	buckets = (("3-4 syllables", 3, 4), ("5-6 syllables", 5, 6), ("7+ syllables", 7, 99))
	for label, lo, hi in buckets:
		cs = [c for c in hclips if lo <= len(items[c["item"]]["expected"]) <= hi]
		for reg, key in (("speaker calibrated", "voice"), ("this clip only", "self")):
			for mname, margin in (("word margin", thr[("template", "word")]), ("sentence margin", thr[("template", "sentence")])):
				vs = [tc.judge(syllables(items[c["item"]]), segs[c["id"]][key], margin) for c in cs]
				checked = [x for v in vs for x in v if x.ok is not None]
				hrows.append([label, reg, f"{mname} {margin}", len(cs), pct(sum(1 for v in vs if any(x.ok is False for x in v)), len(cs)),
					pct(sum(1 for x in checked if x.ok is False), len(checked)), pct(sum(1 for x in checked if x.heard in x.expected), len(checked))])
	spk = Counter(c["speaker"] for c in hclips)
	out.append(("human", table(["utterance", "register", "threshold", "clips", "clips with any flag", "syllables flagged",
		"syllables whose best template is the expected tone"], hrows) + "\n\nSpeakers: " + ", ".join(f"{k} {n}" for k, n in spk.most_common())))

	return out, rows, e2, thr


def main():
	man = stimuli.build()
	items = {i["id"]: i for i in man["items"]}
	if "--no-stt" not in sys.argv:
		clips = [(c["id"], HERE / c["wav"]) for c in man["clips"] if c.get("wav") and items[c["item"]]["exp"] != "H"]
		asyncio.run(stt.transcribe(clips, "run1"))
		asyncio.run(stt.transcribe([(c["id"], HERE / c["wav"]) for c in repeat_subset(man)], "run2"))
	sttres = json.loads(stt.OUT.read_text()) if stt.OUT.exists() else {}
	segs = pitch_segments(man)
	sections, rows, e2, thr = report(man, segs, sttres)
	body = "\n\n".join(f"## {k}\n\n{v}" for k, v in sections)
	TABLES.write_text("# Speech experiment tables\n\nGenerated by `tools/exp_speech/run.py`. Do not edit by hand. "
		"The write-up is in `exp_speech.md`.\n\n" + body + "\n")
	print(TABLES.read_text())


if __name__ == "__main__":
	main()
