"""Transcribe clips with Chrome's webkitSpeechRecognition (zh-CN, Google's cloud recognizer).

Chrome 158 ignores --use-file-for-fake-audio-capture for a plain recognition.start(): it hears silence and
returns no-speech. It does accept start(track) with a MediaStreamTrack, so each clip is decoded in the page and
played into a MediaStreamAudioDestinationNode track. `python stt.py --probe <wav>` shows the routes.

The track also carries faint white noise (about -50 dBFS), as a real microphone does. On digital silence the
recognizer drops the last syllable (我不老 -> 我不); with the noise it ends the utterance by itself.

Results cache: cache/stt.json, {"<tag>|<clip_id>": {"sha1", "method", "alts": [[text, conf], ...], "error"}}.
Reruns skip clips whose cached entry has the same wav sha1 and METHOD.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "cache" / "stt.json"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PAGES = 3
METHOD = "webaudio-track+noise0.003+natural-end"

PAGE = """<!doctype html><meta charset=utf-8><script>
const R = window.SpeechRecognition || window.webkitSpeechRecognition;
function listen(start, stopAfterMs) {
	return new Promise(res => {
		const out = {alts: [], error: null, local: null};
		const r = new R(); r.lang = 'zh-CN'; r.maxAlternatives = 5; r.interimResults = false; r.continuous = false;
		out.local = 'processLocally' in r ? r.processLocally : null;
		r.onresult = e => { for (const x of e.results) if (x.isFinal) out.alts.push(...Array.from(x).map(a => [a.transcript, a.confidence])); };
		r.onerror = e => { out.error = e.error; };
		r.onend = () => res(out);
		start(r);
		if (stopAfterMs) setTimeout(() => r.stop(), stopAfterMs);
		setTimeout(() => { out.error = out.error || 'timeout'; try { r.abort(); } catch (e) {} res(out); }, 25000);
	});
}
async function fromBuffer(b64, noise = 0.003) {
	const ac = new AudioContext();
	const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
	const buf = await ac.decodeAudioData(bytes.buffer);
	const dst = ac.createMediaStreamDestination();
	const src = ac.createBufferSource(); src.buffer = buf; src.connect(dst);
	const nb = ac.createBuffer(1, ac.sampleRate * 20, ac.sampleRate), nd = nb.getChannelData(0);
	for (let i = 0; i < nd.length; i++) nd[i] = (Math.random() * 2 - 1) * noise;
	const ns = ac.createBufferSource(); ns.buffer = nb; ns.connect(dst); ns.start();
	const track = dst.stream.getAudioTracks()[0];
	setTimeout(() => src.start(), 300);
	const out = await listen(r => r.start(track), 300 + buf.duration * 1000 + 5000);  // stop only if it never ends itself
	track.stop(); await ac.close();
	return out;
}
async function fromFakeMic() {  // the --use-file-for-fake-audio-capture file, via getUserMedia
	const s = await navigator.mediaDevices.getUserMedia({audio: true});
	const out = await listen(r => r.start(s.getAudioTracks()[0]), 0);
	s.getTracks().forEach(t => t.stop());
	return out;
}
function plainStart() { return listen(r => r.start(), 0); }
</script>"""


async def _browser(p, fake_wav: str | None = None):
	args = ["--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"]
	if fake_wav:
		args += ["--use-fake-device-for-media-stream", f"--use-file-for-fake-audio-capture={fake_wav}"]
	b = await p.chromium.launch(executable_path=CHROME, headless=True, args=args)
	ctx = await b.new_context(permissions=["microphone"])
	await ctx.route("https://stt.test/", lambda r: r.fulfill(body=PAGE, content_type="text/html"))
	return b, ctx


async def _page(ctx):
	pg = await ctx.new_page()
	await pg.goto("https://stt.test/")
	return pg


async def probe(wav: str) -> dict:
	"""Same file through the three input routes."""
	async with async_playwright() as p:
		b, ctx = await _browser(p, wav)
		pg = await _page(ctx)
		res = {
			"plain start() with fake-capture file": await pg.evaluate("plainStart()"),
			"start(getUserMedia track) from fake-capture file": await pg.evaluate("fromFakeMic()"),
			"start(WebAudio track) from decoded file, no noise": await pg.evaluate("b => fromBuffer(b, 0)", base64.b64encode(Path(wav).read_bytes()).decode()),
			"start(WebAudio track) from decoded file, with noise": await pg.evaluate("b => fromBuffer(b)", base64.b64encode(Path(wav).read_bytes()).decode()),
		}
		await b.close()
	return res


def sha1(path: Path) -> str:
	return hashlib.sha1(path.read_bytes()).hexdigest()


def fresh(entry: dict | None, wav: Path) -> bool:
	return bool(entry) and entry.get("method") == METHOD and entry.get("sha1") == sha1(wav) \
		and entry.get("error") not in ("network", "timeout", "aborted", "audio-capture")


async def transcribe(clips: list[tuple[str, Path]], tag: str = "run1", pages: int = PAGES) -> dict:
	"""clips: [(clip_id, wav_path)]; results land under "<tag>|<clip_id>". Returns the whole cache."""
	cache = json.loads(OUT.read_text()) if OUT.exists() else {}
	todo = [(f"{tag}|{cid}", w) for cid, w in clips if not fresh(cache.get(f"{tag}|{cid}"), w)]
	print(f"stt: {len(clips) - len(todo)} cached, {len(todo)} to run", flush=True)
	if not todo:
		return cache
	queue: asyncio.Queue = asyncio.Queue()
	for x in todo:
		queue.put_nowait(x)
	done = 0

	async with async_playwright() as p:
		b, ctx = await _browser(p)

		async def worker():
			nonlocal done
			pg = await _page(ctx)
			while not queue.empty():
				cid, w = queue.get_nowait()
				for attempt in range(3):
					r = await pg.evaluate("b => fromBuffer(b)", base64.b64encode(w.read_bytes()).decode())
					if r["error"] not in ("network", "timeout", "aborted"):
						break
					await asyncio.sleep(2 + 4 * attempt)
				cache[cid] = {"sha1": sha1(w), "method": METHOD, **r}
				done += 1
				if done % 25 == 0:
					OUT.write_text(json.dumps(cache, ensure_ascii=False))
					print(f"stt: {done}/{len(todo)}", flush=True)

		await asyncio.gather(*(worker() for _ in range(pages)))
		await b.close()
	OUT.write_text(json.dumps(cache, ensure_ascii=False))
	return cache


if __name__ == "__main__":
	if sys.argv[1:2] == ["--probe"]:
		print(json.dumps(asyncio.run(probe(sys.argv[2])), ensure_ascii=False, indent=1))
