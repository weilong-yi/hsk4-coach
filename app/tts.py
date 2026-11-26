"""Server-side Mandarin TTS with a neural voice, cached as mp3.

The default voice is zh-CN-YunxiNeural: in tools/exp_erhua it was the only source that r-coloured erhua on -n finals
(玩儿, 一点儿, 好玩儿, 聊天儿; F3 drop 700-1,190 Hz vs 68-212 Hz for macOS Tingting). Synthesising on the server means
the audio the learner hears is the audio that was measured.
"""
import asyncio, hashlib, re, threading
from pathlib import Path

import edge_tts

CACHE = Path(__file__).resolve().parent.parent / "data" / "tts_cache"
HAN = re.compile(r"[一-鿿]")
_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()


def parse(text, rate):
    """Boundary check for /tts: Chinese text up to 200 characters, rate a percent change in [-50, 50]."""
    text = (text or "").strip()
    if not HAN.search(text) or len(text) > 200:
        raise ValueError("text must contain Chinese and be at most 200 characters")
    rate = int(rate or 0)
    if not -50 <= rate <= 50:
        raise ValueError("rate must be between -50 and 50")
    return text, rate


def cached_path(text, voice, rate):
    return CACHE / f"{hashlib.sha1(f'{voice}|{rate}|{text}'.encode()).hexdigest()}.mp3"


def synth(text, voice, rate=0):
    path = cached_path(text, voice, rate)
    if path.exists():
        return path
    with _locks_guard:
        lock = _locks.setdefault(path, threading.Lock())
    with lock:
        if not path.exists():
            CACHE.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            asyncio.run(edge_tts.Communicate(text, voice, rate=f"{rate:+d}%").save(str(tmp)))
            if tmp.stat().st_size == 0:
                tmp.unlink()
                raise OSError("TTS returned no audio")
            tmp.replace(path)
    return path


def prefetch(texts, voice, rate=0):
    todo = [t for t in dict.fromkeys(texts) if t and not cached_path(t, voice, rate).exists()]

    def run():
        for t in todo:
            try:
                synth(t, voice, rate)
            except Exception:
                pass

    if todo:
        threading.Thread(target=run, daemon=True).start()
