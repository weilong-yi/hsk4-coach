"""Fetch the erhua test words from a running app's /tts (exactly what the learner hears) into wavs, for f3.py.

    .venv/bin/python tools/exp_erhua/served.py http://localhost:<port> <out_dir>
    .venv/bin/python tools/exp_erhua/f3.py file:<out_dir>
"""
import subprocess, sys, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure import WORDS

base, out = sys.argv[1].rstrip("/"), Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
texts = set(WORDS) | {w.replace("儿", "") for w in WORDS} | {"儿", "子"}
for t in sorted(texts):
    mp3 = out / f"{t}.mp3"
    mp3.write_bytes(urllib.request.urlopen(f"{base}/tts?text={urllib.parse.quote(t)}&rate=-15", timeout=30).read())
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@22050", "-c", "1", str(mp3), str(out / f"{t}.wav")], check=True)
print(f"{len(texts)} clips from {base}/tts in {out}")
