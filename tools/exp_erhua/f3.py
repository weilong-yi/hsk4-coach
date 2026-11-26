"""Rhotic check: erhua lowers F3 at the end of the rime. Report F3 (Hz) over the last 30% of voiced speech,
erhua word vs the same word without 儿. A real r-colouring drops F3 by several hundred Hz.

    .venv/bin/python tools/exp_erhua/f3.py [source ...]
"""
import sys
import numpy as np, parselmouth
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from measure import WORDS, clip

def f3_tail(path):
    snd = parselmouth.Sound(str(path))
    pitch = snd.to_pitch(time_step=0.01, pitch_floor=75, pitch_ceiling=500)
    fm = snd.to_formant_burg(time_step=0.01, max_number_of_formants=5, maximum_formant=5500)
    ts = [t for t in pitch.xs() if (pitch.get_value_at_time(t) or 0) > 0]
    if not ts: return None
    tail = [t for t in ts if t >= ts[0] + 0.7 * (ts[-1] - ts[0])]
    v = [fm.get_value_at_time(3, t) for t in tail]
    v = [x for x in v if x and not np.isnan(x)]
    return round(float(np.median(v))) if v else None

for source in sys.argv[1:] or ["say:Tingting"]:
    print(f"\n## {source}\n| word | F3 tail base | F3 tail erhua | drop Hz |\n|---|---|---|---|")
    drops = []
    for w in WORDS + ["儿子"]:
        b = f3_tail(clip(source, w.replace("儿", "") if w != "儿子" else "子"))
        e = f3_tail(clip(source, w if w != "儿子" else "儿"))
        d = (b - e) if b and e else None
        drops.append(d) if w != "儿子" and d is not None else None
        print(f"| {w if w!='儿子' else '儿 vs 子 (control)'} | {b} | {e} | {d} |")
    print(f"median drop over erhua words: {int(np.median(drops))} Hz; words with drop >= 300 Hz: {sum(x>=300 for x in drops)}/{len(drops)}")
