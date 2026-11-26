"""Does a TTS source pronounce erhua (哪儿 = one r-coloured syllable nǎr) or read 儿 as a separate syllable (nǎ ér)?

For each erhua word render three texts with the same source:
  base   the word without 儿            (哪)
  erhua  the word as written            (哪儿)
  split  儿 replaced by 而, always a full syllable ér  (哪而)
and measure syllable nuclei (intensity peaks in voiced speech) and voiced duration.
Verdict per word: erhua is MERGED when it has the base's nucleus count and its duration sits nearer base than split.

    .venv/bin/python tools/exp_erhua/measure.py [source ...]     sources: say:Tingting (default), edge:zh-CN-XiaoxiaoNeural, file:<dir>
"""
import json, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
import parselmouth

WORDS = ["哪儿", "这儿", "那儿", "一点儿", "玩儿", "一会儿", "好玩儿", "没事儿", "小孩儿", "一块儿", "有点儿", "聊天儿"]
CONTROLS = ["儿子", "女儿"]  # 儿 is a real syllable here: expect 2 nuclei
CACHE = Path(__file__).resolve().parent / "cache"


def render_say(voice, text, out):
    aiff = out.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@22050", "-c", "1", str(aiff), str(out)], check=True)
    aiff.unlink()


def render_edge(voice, text, out):
    mp3 = out.with_suffix(".mp3")
    subprocess.run([str(Path(__file__).resolve().parent / ".venv" / "bin" / "edge-tts"), "--voice", voice, "--text", text,
                    "--write-media", str(mp3)], check=True, capture_output=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@22050", "-c", "1", str(mp3), str(out)], check=True)
    mp3.unlink()


def clip(source, text):
    kind, arg = source.split(":", 1)
    d = CACHE / source.replace(":", "_"); d.mkdir(parents=True, exist_ok=True)
    out = d / f"{text}.wav"
    if kind == "file":
        out = Path(arg) / f"{text}.wav"
    elif not out.exists():
        (render_say if kind == "say" else render_edge)(arg, text, out)
    return out


def measure(path):
    snd = parselmouth.Sound(str(path))
    pitch = snd.to_pitch(time_step=0.01, pitch_floor=75, pitch_ceiling=500)
    inten = snd.to_intensity(minimum_pitch=100, time_step=0.01)
    ts = inten.xs()
    db = np.array([inten.get_value(t) or 0 for t in ts])
    voiced = np.array([(pitch.get_value_at_time(t) or 0) > 0 for t in ts])
    if not voiced.any():
        return {"nuclei": 0, "voiced_s": 0.0}
    # syllable nuclei: voiced intensity peaks above (max - 25 dB) separated by a dip of >= 2 dB
    floor = db[voiced].max() - 25
    peaks, last_peak, dip = [], None, None
    for i in range(1, len(db) - 1):
        if voiced[i] and db[i] > floor and db[i] >= db[i - 1] and db[i] >= db[i + 1]:
            if last_peak is None or (db[last_peak] - min(db[last_peak:i + 1]) >= 2 and db[i] - min(db[last_peak:i + 1]) >= 2):
                peaks.append(i); last_peak = i
            elif db[i] > db[last_peak]:
                peaks[-1] = i; last_peak = i
    v_idx = np.where(voiced)[0]
    return {"nuclei": len(peaks), "voiced_s": round((v_idx[-1] - v_idx[0] + 1) * 0.01, 3)}


def run(source):
    rows = []
    for w in WORDS:
        base, split = w.replace("儿", ""), w.replace("儿", "而")
        m = {k: measure(clip(source, t)) for k, t in (("base", base), ("erhua", w), ("split", split))}
        b, e, s = (m[k]["voiced_s"] for k in ("base", "erhua", "split"))
        nearer_base = abs(e - b) < abs(e - s)
        merged = m["erhua"]["nuclei"] == m["base"]["nuclei"] and nearer_base
        rows.append({"word": w, **{f"{k}_nuclei": m[k]["nuclei"] for k in m}, **{f"{k}_s": m[k]["voiced_s"] for k in m},
                     "verdict": "MERGED" if merged else "SPLIT"})
    ctrl = [{"word": w, "nuclei": measure(clip(source, w))["nuclei"]} for w in CONTROLS]
    return rows, ctrl


if __name__ == "__main__":
    for source in sys.argv[1:] or ["say:Tingting"]:
        rows, ctrl = run(source)
        print(f"\n## {source}: {sum(r['verdict'] == 'MERGED' for r in rows)}/{len(rows)} erhua words merged")
        print("| word | nuclei base/erhua/split | voiced s base/erhua/split | verdict |\n|---|---|---|---|")
        for r in rows:
            print(f"| {r['word']} | {r['base_nuclei']}/{r['erhua_nuclei']}/{r['split_nuclei']} | {r['base_s']}/{r['erhua_s']}/{r['split_s']} | {r['verdict']} |")
        print("controls (儿 as a full syllable, expect base nuclei + 1):", ", ".join(f"{c['word']} {c['nuclei']}" for c in ctrl))
