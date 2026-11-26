// One shadowing attempt: 16 kHz mono WAV capture (AudioWorklet) plus Web Speech recognition, both bound
// to this attempt only. stop() resolves with the WAV and the merged transcript; abort() discards everything.

const RATE = 16000;

export const RECOGNITION_ERRORS = {
  'not-allowed': 'Microphone access was blocked. Allow the mic for localhost in Chrome site settings, then try again.',
  'service-not-allowed': 'This browser does not allow speech recognition here. Your recording is still saved.',
  'no-speech': 'No speech was detected. Check that the right mic is selected and speak a little louder.',
  network: 'Speech recognition needs the internet (Chrome sends audio to Google). Your recording is still saved.',
  'audio-capture': 'No microphone was found. Plug one in or pick one in system settings.',
  'language-not-supported': 'Chinese recognition is not available in this browser.',
  aborted: 'Recognition was stopped before it finished.',
  unsupported: 'This browser has no speech recognition, so there is no transcript. Your recording is still saved.',
  empty: 'Recognition returned no transcript for this attempt. Your recording is still saved.',
};

export const errorMessage = code => RECOGNITION_ERRORS[code] || `Speech recognition error: ${code}.`;

// Safari repeats the whole utterance in each final result; Chrome sends only the new part.
export const mergeFinal = (t, s) => (s.startsWith(t) ? s : t + s);

function resample(chunks, from) {
  const n = chunks.reduce((a, c) => a + c.length, 0);
  const input = new Float32Array(n);
  let o = 0;
  for (const c of chunks) { input.set(c, o); o += c.length; }
  if (from === RATE) return input;
  const ratio = from / RATE, out = new Float32Array(Math.floor(n / ratio));
  for (let i = 0; i < out.length; i++) {
    const a = Math.floor(i * ratio), b = Math.max(a + 1, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = a; j < b; j++) sum += input[j];
    out[i] = sum / (b - a);
  }
  return out;
}

function wav(samples) {
  const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
  const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE');
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, RATE, true); v.setUint32(28, RATE * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, 'data'); v.setUint32(40, samples.length * 2, true);
  samples.forEach((x, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, x)) * 0x7fff, true));
  return new Blob([buf], { type: 'audio/wav' });
}

export class Attempt {
  constructor(onUpdate) {
    this.onUpdate = onUpdate;
    this.final = '';
    this.interim = '';
    this.error = null;
    this.chunks = [];
    this.live = true;
  }

  get transcript() { return this.final + this.interim; }

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false } });
    if (!this.live) return this.release();
    this.ctx = new AudioContext({ sampleRate: RATE });
    await this.ctx.audioWorklet.addModule('/recorder-worklet.js');
    if (!this.live) return;
    const node = new AudioWorkletNode(this.ctx, 'pcm-recorder');
    node.port.onmessage = e => { if (this.live) this.chunks.push(e.data); };
    this.ctx.createMediaStreamSource(this.stream).connect(node);
    node.connect(this.ctx.destination);
    this.t0 = performance.now();
    this.startRecognition();
  }

  startRecognition() {
    const R = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!R) { this.error = 'unsupported'; this.ended = Promise.resolve(); return this.onUpdate(this); }
    const rec = new R();
    this.rec = rec;
    rec.lang = 'zh-CN';
    rec.interimResults = true;
    rec.continuous = true;
    this.ended = new Promise(resolve => { rec.onend = resolve; });
    rec.onresult = e => {
      if (rec !== this.rec) return;
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const s = e.results[i][0].transcript;
        if (e.results[i].isFinal) this.final = mergeFinal(this.final, s);
        else interim += s;
      }
      this.interim = interim;
      this.onUpdate(this);
    };
    rec.onerror = e => {
      if (rec !== this.rec || e.error === 'aborted') return;
      this.error = e.error;
      this.onUpdate(this);
    };
    rec.start();
  }

  release() {
    this.live = false;
    if (this.rec) { this.rec.onresult = this.rec.onerror = null; try { this.rec.abort(); } catch {} }
    if (this.stream) this.stream.getTracks().forEach(t => t.stop());
    if (this.ctx && this.ctx.state !== 'closed') this.ctx.close();
  }

  // Release the mic now and keep what was captured.
  take(error) {
    const recMs = this.t0 ? Math.round(performance.now() - this.t0) : 0;
    const rate = this.ctx ? this.ctx.sampleRate : RATE;
    this.release();
    if (this.interim) this.final = mergeFinal(this.final, this.interim);
    this.interim = '';
    this.error = error || this.error || (this.final ? null : 'empty');
    return { blob: wav(resample(this.chunks, rate)), transcript: this.final, error: this.error, recMs };
  }

  async stop() {
    if (this.rec) {
      this.rec.stop();
      await Promise.race([this.ended, new Promise(r => setTimeout(r, 1500))]);
    }
    return this.take();
  }
}

export async function blobToBase64(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
