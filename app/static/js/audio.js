// Native Tatoeba audio through /audio/<id>, else browser TTS rotating over the installed Mandarin voices.

let current = null;
let utterance = null;
let turn = 0;
const failedNative = new Set();

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

export function nextVoice() {
  const vs = mandarinVoices();
  return vs.length ? vs[turn++ % vs.length] : null;
}

export function stopAudio() {
  if (current) {
    current.onended = current.onerror = null;
    current.pause();
    current.removeAttribute('src');
    current.load();
    current = null;
  }
  if ('speechSynthesis' in window) speechSynthesis.cancel();
}

export function speak(text, { rate = 0.9, pitch = 1, voice = nextVoice() } = {}) {
  return new Promise(resolve => {
    stopAudio();
    if (!('speechSynthesis' in window)) return resolve({ via: 'none', voice: null, status: 'unsupported' });
    const u = new SpeechSynthesisUtterance(text);
    utterance = u;
    u.lang = 'zh-CN';
    u.rate = rate;
    u.pitch = pitch;
    if (voice) u.voice = voice;
    let timer;
    const done = status => { clearTimeout(timer); resolve({ via: 'tts', voice: voice ? voice.name : null, status }); };
    u.onend = () => done('end');
    u.onerror = e => done(`error:${e.error}`);
    timer = setTimeout(() => done('timeout'), 2000 + text.length * 500 / rate);
    speechSynthesis.speak(u);
  });
}

export function playNative(id, rate = 1) {
  return new Promise((resolve, reject) => {
    stopAudio();
    const a = new Audio(`/audio/${id}`);
    current = a;
    a.playbackRate = rate;
    const fail = () => {
      clearTimeout(timer);
      if (current !== a) return;
      stopAudio();
      reject(new Error('native audio unavailable'));
    };
    const timer = setTimeout(fail, 5000);
    a.onplaying = () => clearTimeout(timer);
    a.onended = () => resolve({ via: 'native', voice: `tatoeba:${id}` });
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
  return speak(s.zh, { rate: slow ? 0.6 : 0.9, voice: voice || nextVoice() });
}
