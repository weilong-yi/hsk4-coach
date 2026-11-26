// Native Tatoeba audio through /audio/<id>; else neural TTS from the server (/tts, zh-CN-YunxiNeural, which
// pronounces erhua, tools/exp_erhua); else browser TTS in Tingting if the server cannot synthesise.
// data/exp_speech.md E2.1: Tingting's STT error matched native audio (1.4% vs 3.2%); the other macOS voices were 12.8-42%.

let current = null;
let utterance = null;
const failedNative = new Set();
let source = null;  // what actually started playing last: 'server-tts', 'tatoeba:<id>' or 'browser:<voice>'
export const playingSource = () => source;

export const voicesReady = new Promise(resolve => {
  if (!('speechSynthesis' in window)) return resolve();
  if (speechSynthesis.getVoices().length) return resolve();
  speechSynthesis.addEventListener('voiceschanged', resolve, { once: true });
  setTimeout(resolve, 1500);
});

export function mandarinVoices() {
  if (!('speechSynthesis' in window)) return [];
  const all = speechSynthesis.getVoices();
  const mainland = all.filter(v => /^(zh[-_](CN|Hans)|cmn)/i.test(v.lang));
  return mainland.length ? mainland : all.filter(v => /^zh/i.test(v.lang) && !/HK|yue/i.test(v.lang));
}

const ELOQUENCE = /^(Eddy|Flo|Grandma|Grandpa|Reed|Rocko|Sandy|Shelley)\b/;

export function mandarinVoice() {
  const vs = mandarinVoices();
  return vs.find(v => /Tingting|婷婷/.test(v.name)) || vs.find(v => !ELOQUENCE.test(v.name)) || vs[0] || null;
}

export function stopAudio() {
  source = null;
  if (current) {
    current.onended = current.onerror = null;
    current.pause();
    current.removeAttribute('src');
    current.load();
    current = null;
  }
  if ('speechSynthesis' in window) speechSynthesis.cancel();
}

// Browser rate (1 = normal) as the server's percent change; matches TTS_RATE in app/study.py for prefetching.
const ratePct = rate => Math.max(-50, Math.min(50, Math.round((rate - 1) * 100)));

export async function speak(text, opts = {}) {
  try {
    return await playUrl(`/tts?text=${encodeURIComponent(text)}&rate=${ratePct(opts.rate ?? 0.9)}`, 1, 'server-tts', 8000);
  } catch {
    return speakBrowser(text, opts);
  }
}

function speakBrowser(text, { rate = 0.9, pitch = 1, voice = mandarinVoice() } = {}) {
  return new Promise(resolve => {
    stopAudio();
    if (!('speechSynthesis' in window)) return resolve({ via: 'none', voice: null, status: 'unsupported' });
    voice = voice || mandarinVoice();
    const u = new SpeechSynthesisUtterance(text);
    utterance = u;
    u.lang = 'zh-CN';
    u.rate = rate;
    u.pitch = pitch;
    if (voice) u.voice = voice;
    source = `browser:${voice ? voice.name : 'default'}`;
    let timer;
    const done = status => { clearTimeout(timer); resolve({ via: 'tts', voice: voice ? voice.name : null, status }); };
    u.onend = () => done('end');
    u.onerror = e => done(`error:${e.error}`);
    timer = setTimeout(() => done('timeout'), 2000 + text.length * 500 / rate);
    speechSynthesis.speak(u);
  });
}

export function playNative(id, rate = 1) {
  return playUrl(`/audio/${id}`, rate, `tatoeba:${id}`, 5000).then(r => ({ via: 'native', voice: r.voice }));
}

function playUrl(url, rate, label, waitMs) {
  return new Promise((resolve, reject) => {
    stopAudio();
    const a = new Audio(url);
    current = a;
    a.playbackRate = rate;
    const fail = () => {
      clearTimeout(timer);
      if (current !== a) return;
      stopAudio();
      reject(new Error(`audio unavailable: ${url}`));
    };
    const timer = setTimeout(fail, waitMs);
    a.onplaying = () => { clearTimeout(timer); source = label; };
    a.onended = () => resolve({ via: label === 'server-tts' ? 'tts' : 'native', voice: label });
    a.onerror = fail;
    a.play().catch(fail);
  });
}

// A sentence {zh, audio}: native recording when it has one and it loads, else TTS.
export async function playSentence(s, { slow = false, voice } = {}) {
  if (s.audio && !failedNative.has(s.audio)) {
    try {
      return await playNative(s.audio, slow ? 0.75 : 1);
    } catch {
      failedNative.add(s.audio);
    }
  }
  return speak(s.zh, { rate: slow ? 0.6 : 0.9, voice });
}
