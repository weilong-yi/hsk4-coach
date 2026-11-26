import { get, post, logEvent } from './api.js';
import { playSentence, speak, nextVoice, stopAudio, voicesReady } from './audio.js';
import { pinyin } from './pinyin.js';
import { Attempt, errorMessage, blobToBase64 } from './speech.js';
import { h, step, BlockTimer, kbd, nextButton, elapsed, pct, toast } from './ui.js';
import { tile } from './placement.js';

const ABOUT = {
  cards: 'Listen to each word first and recall its meaning, then reveal and rate yourself. Due reviews come first, then new words.',
  listen: 'Hear each sentence before you see it. Mark whether you understood, then read it. Click any word for pinyin and meaning; HSK words you look up become cards.',
  speak: 'Shadow sentences from today. Hear it, record yourself saying it, and compare. Recordings are saved for later tone analysis.',
};

// Sentence as token blocks (hanzi over pinyin), punctuation kept between tokens.
export function sentenceView(s, { onTap, highlight, marks = {} } = {}) {
  const out = [];
  let i = 0;
  s.tok.forEach((t, k) => {
    const j = s.zh.indexOf(t, i);
    if (j < 0) return;
    if (j > i) out.push(h('span', { class: 'punct' }, s.zh.slice(i, j)));
    const cls = ['tok', marks[t], t === highlight ? 'target' : '', onTap ? 'tap' : ''].filter(Boolean).join(' ');
    out.push(h('span', { class: cls, onclick: onTap ? e => onTap(t, e.currentTarget) : null },
      h('span', { class: 'zh' }, t), pinyin(s.nums[k], 'rt')));
    i = j + t.length;
  });
  if (i < s.zh.length) out.push(h('span', { class: 'punct' }, s.zh.slice(i)));
  return h('div', { class: 'sentence' }, out);
}

async function cardsBlock(ctx) {
  let last = null;
  while (!ctx.timer.expired) {
    const { card } = await post('/api/cards/next', { session_id: ctx.sid, exclude: last });
    if (!card) return finished(ctx, 'No more cards due today. New words are capped at the daily limit.');
    await reviewCard(ctx, card);
    last = card.w;
    ctx.tally.cards++;
  }
}

function reviewCard(ctx, card) {
  return step(ctx.scope, (s, done) => {
    const t0 = performance.now();
    const voice = nextVoice();
    let plays = 0, revealMs = null, busy = false;
    const play = () => { plays++; speak(card.w, { voice, rate: 0.85 }); };
    const playExample = () => card.example && playSentence(card.example);
    const rate = async r => {
      if (revealMs == null || busy) return;
      busy = true;
      await post('/api/cards/review', {
        session_id: ctx.sid, word: card.w, rating: r, ms: elapsed(t0),
        extra: { ...ctx.extra(), reveal_ms: revealMs, plays, voice: voice && voice.name, example_id: card.example && card.example.id },
      });
      done();
    };
    const reveal = () => {
      if (revealMs != null) return;
      revealMs = elapsed(t0);
      ctx.body.replaceChildren(h('div', { class: 'card back' },
        badge(card),
        h('div', { class: 'hanzi xl' }, card.w),
        pinyin(card.num, 'py lg'),
        h('p', { class: 'meaning' }, card.en),
        card.alt.length ? h('p', { class: 'muted alt' }, 'Also read ', card.alt.map((a, i) => [i ? ' · ' : '', pinyin(a.num), ` ${a.en}`])) : null,
        card.example ? h('div', { class: 'example' },
          sentenceView(card.example, { highlight: card.w }),
          h('p', { class: 'muted' }, card.example.en),
          h('button', { class: 'small', onclick: playExample }, '▶ Example ', kbd('E'))) : null,
        h('div', { class: 'ratings' }, ['Again', 'Hard', 'Good', 'Easy'].map((label, i) =>
          h('button', { class: `rate r${i + 1}`, onclick: () => rate(i + 1) },
            h('b', {}, label), h('span', {}, card.intervals[i + 1]), kbd(i + 1))))));
    };
    s.keys({ ' ': () => (revealMs == null ? reveal() : play()), r: play, e: playExample,
      1: () => rate(1), 2: () => rate(2), 3: () => rate(3), 4: () => rate(4) });
    ctx.body.replaceChildren(h('div', { class: 'card front' },
      badge(card),
      h('button', { class: 'play huge', onclick: play, 'aria-label': 'Play word' }, '▶'),
      h('p', { class: 'muted' }, card.new ? 'New word. Listen, guess if you can, then reveal to learn it.' : 'Listen and recall the meaning.'),
      h('div', { class: 'row center' },
        h('button', { class: 'small', onclick: play }, 'Replay ', kbd('R')),
        h('button', { class: 'primary', onclick: reveal }, 'Show answer ', kbd('Space')))));
    play();
  });
}

const badge = card => h('div', { class: 'badges' },
  card.new ? h('span', { class: 'badge new' }, 'New') : h('span', { class: 'badge' }, card.state === 'Review' ? 'Review' : 'Learning'),
  h('span', { class: 'badge' }, `HSK ${card.lvl}`));

async function listenBlock(ctx) {
  while (!ctx.timer.expired) {
    const { sentences } = await post('/api/bundle');
    if (!sentences.length) return finished(ctx, 'No more sentences at your level right now.');
    for (const s of sentences) {
      if (ctx.timer.expired) return;
      await listenItem(ctx, s);
      ctx.tally.listened++;
    }
  }
}

function listenItem(ctx, s) {
  return step(ctx.scope, (st, done) => {
    const t0 = performance.now();
    let plays = 0, slowPlays = 0, via = null, marked = false, shownAt = null;
    const play = (slow = false) => {
      plays++;
      if (slow) slowPlays++;
      playSentence(s, { slow }).then(r => { via = r; });
    };
    const pop = h('div', { class: 'popover', hidden: true });
    st.on(window, 'scroll', () => { pop.hidden = true; });
    st.on(document, 'pointerdown', e => { if (!pop.contains(e.target) && !e.target.closest('.tok')) pop.hidden = true; });
    st.keys({ Escape: () => { pop.hidden = true; } });
    const tap = async (word, el) => {
      const info = await post('/api/lookup', {
        session_id: ctx.sid, word, ms: elapsed(shownAt),
        extra: { ...ctx.extra(), sentence_id: s.id, mark: s.marks[word] || null },
      });
      ctx.tally.lookups++;
      const r = el.getBoundingClientRect();
      pop.replaceChildren(
        h('div', { class: 'row' }, h('span', { class: 'hanzi md' }, word), pinyin(info.num, 'py lg'),
          h('button', { class: 'small', onclick: () => speak(word) }, '▶')),
        h('p', {}, info.en || 'No dictionary gloss.'),
        h('p', { class: 'muted' }, info.lvl ? `HSK ${info.lvl}` : 'Not in HSK 1-4', info.added ? ' · added to your cards' : ''));
      pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 340, r.left))}px`;
      pop.style.top = `${r.bottom + 8}px`;
      pop.hidden = false;
    };
    const mark = understood => {
      if (marked) return;
      marked = true;
      ctx.tally.understood += understood;
      logEvent(ctx.sid, 'listen', s.id, {
        ...ctx.extra(), understood, plays, slow_plays: slowPlays, audio: via && via.via, voice: via && via.voice,
        native_available: !!s.audio, lvl: s.lvl, unknown: Object.keys(s.marks).filter(t => s.marks[t] === 'new'),
      }, elapsed(t0));
      shownAt = performance.now();
      const en = h('p', { class: 'translation', hidden: true }, s.en);
      const showEn = () => { en.hidden = !en.hidden; };
      st.keys({ t: showEn });
      ctx.body.replaceChildren(h('div', { class: 'listen text' },
        h('p', { class: 'muted' }, understood ? 'You understood it. Check the text.' : 'Read along. Click words you are unsure of.'),
        sentenceView(s, { onTap: tap, marks: s.marks }),
        h('div', { class: 'row' },
          h('button', { class: 'small', onclick: () => play() }, '▶ Again ', kbd('Space')),
          h('button', { class: 'small', onclick: showEn }, 'Translation ', kbd('T'))),
        en,
        h('div', { class: 'row end' }, nextButton(st, 'Next', () => done()))), pop);
    };
    st.keys({ ' ': () => play(), s: () => play(true), y: () => mark(true), n: () => mark(false) });
    ctx.body.replaceChildren(h('div', { class: 'listen audio' },
      h('button', { class: 'play huge', onclick: () => play(), 'aria-label': 'Play sentence' }, '▶'),
      h('div', { class: 'row center' },
        h('button', { class: 'small', onclick: () => play() }, 'Replay ', kbd('Space')),
        h('button', { class: 'small', onclick: () => play(true) }, 'Slower ', kbd('S'))),
      h('p', { class: 'prompt' }, 'Did you understand it?'),
      h('div', { class: 'row center' },
        h('button', { class: 'big no', onclick: () => mark(false) }, 'Not really ', kbd('N')),
        h('button', { class: 'big yes', onclick: () => mark(true) }, 'Yes ', kbd('Y')))));
    play();
  });
}

async function speakBlock(ctx) {
  const { sentences } = await post('/api/shadow/items', { session_id: ctx.sid });
  for (const s of sentences) {
    if (ctx.timer.expired) return;
    await shadowItem(ctx, s);
  }
  if (!ctx.timer.expired) return finished(ctx, "You shadowed all of today's sentences.");
}

// Per-sentence state: idle -> starting -> recording -> saving -> result -> (starting again | next).
// Leaving mid-attempt (Next, Skip, navigation) releases the mic at once and still logs what was captured.
function shadowItem(ctx, s) {
  return step(ctx.scope, (st, done) => {
    let state = 'idle', attempt = null, n = 0, modelPlays = 0, via = null;
    st.defer(() => {
      if (state === 'starting' || state === 'recording') save(attempt, attempt.take('abandoned'));
    });
    const live = h('div', { class: 'live' });
    const result = h('div', { class: 'result' });
    const recBtn = h('button', { class: 'record', onclick: () => toggle() });
    const status = h('p', { class: 'muted status' });
    const hear = (slow = false) => {
      if (state === 'starting' || state === 'recording') return;
      modelPlays++;
      playSentence(s, { slow }).then(r => { via = r; });
    };
    const render = () => {
      recBtn.replaceChildren(state === 'recording' ? '■ Stop ' : n ? '● Try again ' : '● Record ', kbd('R'));
      recBtn.disabled = state === 'saving' || state === 'starting';
      recBtn.classList.toggle('on', state === 'recording');
      status.textContent = { idle: 'Hear it, then record yourself saying it.', starting: 'Starting the microphone…', recording: 'Recording… speak now. Press R to stop.', saving: 'Saving…', result: '' }[state];
    };
    const showLive = a => {
      live.replaceChildren(h('span', { class: 'muted' }, 'Heard: '), a.transcript || '…');
      if (a.error && a.error !== 'empty') live.append(h('p', { class: 'warn' }, errorMessage(a.error)));
    };

    async function start() {
      stopAudio();
      const a = new Attempt(x => { if (x === attempt) showLive(x); });
      attempt = a;
      n++;
      a.tStart = performance.now();
      state = 'starting';
      render();
      result.replaceChildren();
      live.replaceChildren(h('span', { class: 'muted' }, 'Heard: …'));
      try {
        await a.start();
      } catch (e) {
        if (a !== attempt) return;
        a.abort();
        state = 'result';
        render();
        const code = e.name === 'NotAllowedError' ? 'not-allowed' : e.name === 'NotFoundError' ? 'audio-capture' : e.message;
        result.replaceChildren(h('p', { class: 'warn' }, errorMessage(code)));
        await post('/api/shadow', { session_id: ctx.sid, sentence_id: s.id, attempt: n, transcript: '', error: code, ms: elapsed(a.tStart), extra: { ...ctx.extra(), model_plays: modelPlays } });
        ctx.tally.attempts++;
        return;
      }
      if (a !== attempt || st.closed) return;
      state = 'recording';
      render();
      st.timeout(() => { if (attempt === a && state === 'recording') finish(); }, Math.min(20000, 4000 + s.zh.length * 700));
    }

    async function save(a, r) {
      const saved = await post('/api/shadow', {
        session_id: ctx.sid, sentence_id: s.id, attempt: n, transcript: r.transcript, error: r.error, ms: elapsed(a.tStart),
        wav_b64: await blobToBase64(r.blob),
        extra: { ...ctx.extra(), rec_ms: r.recMs, model_plays: modelPlays, model_audio: via && via.via, model_voice: via && via.voice },
      });
      ctx.tally.attempts++;
      if (saved.score != null) ctx.tally.scores.push(saved.score);
      return saved;
    }

    async function finish() {
      const a = attempt;
      state = 'saving';
      render();
      const r = await a.stop();
      const saved = await save(a, r);
      if (a !== attempt || st.closed) return;
      state = 'result';
      render();
      const url = URL.createObjectURL(r.blob);
      st.defer(() => URL.revokeObjectURL(url));
      result.replaceChildren(
        saved.marks
          ? h('div', { class: 'scored' }, h('div', { class: 'chars' }, [...saved.chars].map((ch, i) => h('span', { class: saved.marks[i] ? 'hit' : 'miss' }, ch))),
            h('div', { class: 'score' }, pct(saved.score), h('span', { class: 'muted' }, ' characters matched')))
          : h('p', { class: 'warn' }, errorMessage(r.error)),
        h('div', { class: 'row' }, h('span', { class: 'muted' }, `Your recording (${saved.duration_s.toFixed(1)} s):`), h('audio', { controls: true, src: url })));
    }

    const toggle = () => {
      if (state === 'recording') finish();
      else if (state !== 'saving') start().catch(e => toast(e.message));
    };
    st.keys({ ' ': () => hear(), s: () => hear(true), r: toggle });
    ctx.body.replaceChildren(h('div', { class: 'speak' },
      sentenceView(s),
      h('p', { class: 'muted' }, s.en),
      h('div', { class: 'row center' },
        h('button', { class: 'play', onclick: () => hear() }, '▶ Hear it ', kbd('Space')),
        h('button', { class: 'small', onclick: () => hear(true) }, 'Slower ', kbd('S')),
        recBtn),
      status, live, result,
      h('div', { class: 'row end' }, nextButton(st, 'Next sentence', () => done()))));
    render();
    hear();
  });
}

function finished(ctx, message) {
  return step(ctx.scope, (s, done) => {
    ctx.body.replaceChildren(h('div', { class: 'card' }, h('p', {}, message), nextButton(s, 'Continue', () => done())));
  });
}

const BLOCKS = { cards: cardsBlock, listen: listenBlock, speak: speakBlock };

export async function sessionScreen(root, scope) {
  await voicesReady;
  const state = await get('/api/state');
  if (!state.placement) {
    root.replaceChildren(h('section', { class: 'panel intro' }, h('h1', {}, 'Take the placement first'),
      h('p', {}, 'The session is built from your profile.'), h('a', { class: 'button primary', href: '#/placement' }, 'Start placement')));
    return;
  }
  const s = await post('/api/session/start');
  const tally = { cards: 0, listened: 0, understood: 0, lookups: 0, attempts: 0, scores: [] };
  const t0 = performance.now();
  for (const [i, block] of s.blocks.entries()) {
    await step(scope, (st, done) => {
      root.replaceChildren(h('section', { class: 'panel intro' },
        steps(s.blocks, i),
        h('h1', {}, `${block.title} · ${block.minutes} minutes`),
        h('p', {}, ABOUT[block.id]),
        i === 0 ? h('p', { class: 'muted' }, `${s.queue.due} reviews due, ${s.queue.new} new words today.`) : null,
        nextButton(st, `Start ${block.title.toLowerCase()}`, () => done())));
    });
    const bs = scope.child();
    const timerEl = h('div', { class: 'timer' });
    const body = h('div', { class: 'block-body' });
    let skip;
    const skipped = new Promise(r => { skip = r; });
    root.replaceChildren(h('section', { class: 'panel session' },
      h('div', { class: 'session-head' }, steps(s.blocks, i), timerEl,
        h('button', { class: 'link', onclick: () => skip() }, 'Skip block →')),
      body));
    const timer = new BlockTimer(block.minutes, timerEl, bs);
    const ctx = { sid: s.session_id, timer, body, scope: bs, tally, extra: () => ({ block: block.id, block_ms: timer.ms }) };
    let reason = 'leave';
    bs.defer(() => post('/api/block_end', { session_id: s.session_id, block: block.id, block_ms: timer.ms, reason }));
    reason = await Promise.race([BLOCKS[block.id](ctx).then(() => (timer.expired ? 'time' : 'done')), skipped.then(() => 'skip')]);
    bs.close();
    stopAudio();
  }
  const scores = tally.scores;
  root.replaceChildren(h('section', { class: 'panel' },
    h('h1', {}, 'Session complete'),
    h('p', { class: 'muted' }, `${Math.round(elapsed(t0) / 60000)} minutes of real time.`),
    h('div', { class: 'tiles' },
      tile('Cards', tally.cards, 'reviewed'),
      tile('Listening', tally.listened, `${pct(tally.listened ? tally.understood / tally.listened : null)} understood`),
      tile('Lookups', tally.lookups, 'words checked'),
      tile('Shadowing', tally.attempts, scores.length ? `avg match ${pct(scores.reduce((a, b) => a + b, 0) / scores.length)}` : 'no transcripts scored')),
    h('div', { class: 'row end' }, h('a', { class: 'button', href: '#/stats' }, 'Stats'), h('a', { class: 'button primary', href: '#/home' }, 'Home'))));
}

const steps = (blocks, current) => h('ol', { class: 'steps' }, blocks.map((b, i) =>
  h('li', { class: i < current ? 'done' : i === current ? 'now' : '' }, `${b.title} ${b.minutes}m`)));
