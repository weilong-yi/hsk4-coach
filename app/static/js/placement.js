import { post, logEvent } from './api.js';
import { playSentence, speak, mandarinVoice, voicesReady } from './audio.js';
import { pinyin } from './pinyin.js';
import { h, step, choices, nextButton, kbd, elapsed, pct } from './ui.js';

const PARTS = ['Vocabulary', 'Listening', 'Tones', 'Reading'];
const TONE_MARKS = ['ā', 'á', 'ǎ', 'à'];

function frame(root, part, i, n, ...body) {
  root.replaceChildren(h('section', { class: 'panel' },
    h('div', { class: 'part' },
      h('span', {}, `Placement · ${PARTS.indexOf(part) + 1}/4 · ${part}`),
      n ? h('span', { class: 'muted' }, `${i + 1} / ${n}`) : null),
    h('div', { class: 'bar' }, h('div', { style: `width:${n ? (100 * i) / n : 0}%` })),
    ...body));
}

function intro(scope, root, title, lines, label = 'Start') {
  return step(scope, (s, done) => {
    root.replaceChildren(h('section', { class: 'panel intro' }, h('h1', {}, title),
      ...lines.map(l => h('p', {}, l)), nextButton(s, label, () => done())));
  });
}

async function vocab(scope, root, sid, items) {
  for (const [i, it] of items.entries()) {
    await step(scope, (s, done) => {
      const t0 = performance.now();
      const answer = claimed => {
        logEvent(sid, 'placement_vocab', it.w, { phase: 'yesno', claimed, lvl: it.lvl, pseudo: it.pseudo }, elapsed(t0));
        it.claimed = claimed;
        done();
      };
      s.keys({ y: () => answer(true), ArrowRight: () => answer(true), n: () => answer(false), ArrowLeft: () => answer(false) });
      frame(root, 'Vocabulary', i, items.length,
        h('p', { class: 'prompt' }, 'Do you know this word? Some items are made-up words, so say yes only if you know its meaning.'),
        h('div', { class: 'hanzi xl' }, it.w),
        h('div', { class: 'row center' },
          h('button', { class: 'big no', onclick: () => answer(false) }, 'No ', kbd('N')),
          h('button', { class: 'big yes', onclick: () => answer(true) }, 'Yes ', kbd('Y'))));
    });
  }
}

// Spot-check five claimed words, highest levels first, round-robin across levels.
function spotPicks(items) {
  const byLevel = [4, 3, 2, 1].map(l => items.filter(it => !it.pseudo && it.claimed && it.lvl === l));
  const out = [];
  while (out.length < 5 && byLevel.some(b => b.length)) for (const b of byLevel) if (b.length && out.length < 5) out.push(b.shift());
  return out;
}

async function spot(scope, root, sid, picks) {
  for (const [i, it] of picks.entries()) {
    await step(scope, (s, done) => {
      const t0 = performance.now();
      const next = nextButton(s, 'Next', () => done());
      next.hidden = true;
      frame(root, 'Vocabulary', i, picks.length,
        h('p', { class: 'prompt' }, 'Quick check: what does this word mean?'),
        h('div', { class: 'hanzi xl' }, it.w),
        choices(s, it.options, it.answer, (choice, correct) => {
          logEvent(sid, 'placement_vocab', it.w, { phase: 'spot', choice, correct, lvl: it.lvl }, elapsed(t0));
          next.hidden = false;
        }),
        h('div', { class: 'row end' }, next));
    });
  }
}

async function listen(scope, root, sid, items) {
  for (const [i, it] of items.entries()) {
    await step(scope, (s, done) => {
      const t0 = performance.now();
      let plays = 0, via = null;
      const play = () => { plays++; playSentence(it).then(r => { via = r; }); };
      const next = nextButton(s, 'Next', () => done());
      next.hidden = true;
      const reveal = h('div', { class: 'reveal', hidden: true }, h('div', { class: 'hanzi md' }, it.zh));
      s.keys({ ' ': play });
      frame(root, 'Listening', i, items.length,
        h('p', { class: 'prompt' }, 'Listen (no text) and pick the meaning.'),
        h('div', { class: 'row center' }, h('button', { class: 'play', onclick: play }, '▶ Play again ', kbd('Space'))),
        choices(s, it.options, it.answer, (choice, correct) => {
          logEvent(sid, 'placement_listen', it.id, { lvl: it.lvl, choice, correct, plays, audio: via && via.via, voice: via && via.voice, native_available: !!it.audio }, elapsed(t0));
          reveal.hidden = false;
          next.hidden = false;
        }),
        reveal, h('div', { class: 'row end' }, next));
      play();
    });
  }
}

async function tones(scope, root, sid, items) {
  for (const [i, it] of items.entries()) {
    await step(scope, (s, done) => {
      const t0 = performance.now();
      const voice = mandarinVoice();
      const rate = 0.75 + Math.random() * 0.2;
      let plays = 0;
      const play = () => { plays++; speak(it.w, { voice, rate }); };
      const picked = [];
      const rows = [0, 1].map(k => h('div', { class: 'tone-row' }, h('span', { class: 'muted' }, `Syllable ${k + 1}`),
        TONE_MARKS.map((m, t) => h('button', { class: 'tone', 'data-tone': t + 1, onclick: () => pick(k, t + 1) }, h('b', {}, t + 1), ` ${m}`))));
      const feedback = h('div', { class: 'reveal', hidden: true });
      const next = nextButton(s, 'Next', () => done());
      next.hidden = true;
      function pick(k, tone) {
        if (picked.length === 2 || k !== picked.length) return;
        picked.push(tone);
        rows[k].querySelectorAll('button').forEach(b => b.classList.toggle('sel', Number(b.dataset.tone) === tone));
        if (picked.length < 2) return;
        const correct = picked.map((t, j) => t === it.tones[j]);
        logEvent(sid, 'placement_tone', it.w, { answer: picked, expected: it.tones, correct, plays, voice: voice && voice.name, rate: Number(rate.toFixed(2)) }, elapsed(t0));
        rows.forEach((r, j) => r.classList.add(correct[j] ? 'right' : 'wrong'));
        feedback.replaceChildren(h('div', { class: 'hanzi md' }, it.w), pinyin(it.num, 'py lg'),
          h('p', {}, correct.every(Boolean) ? 'Both right.' : `You heard ${picked.join('-')}; it is ${it.tones.join('-')}.`));
        feedback.hidden = false;
        next.hidden = false;
      }
      s.keys({ ' ': play, 1: () => pick(picked.length, 1), 2: () => pick(picked.length, 2), 3: () => pick(picked.length, 3), 4: () => pick(picked.length, 4) });
      frame(root, 'Tones', i, items.length,
        h('p', { class: 'prompt' }, 'Pick the tone of each syllable. Keys 1-4 fill syllable 1, then syllable 2.'),
        h('div', { class: 'row center' }, h('button', { class: 'play', onclick: play }, '▶ Play again ', kbd('Space'))),
        rows, feedback, h('div', { class: 'row end' }, next));
      play();
    });
  }
}

// Timed read, then three "which of these did the text say?" questions. Shared with the standalone reading check.
export async function readingTest(scope, root, sid, bundle) {
  await intro(scope, root, 'Timed reading',
    [`Read ${bundle.chars} characters at your normal pace, for meaning. Press Done when you finish.`,
      'Then answer three questions without the text.'], 'Show the text');
  const ms = await step(scope, (s, done) => {
    const t0 = performance.now();
    frame(root, 'Reading', 0, 0,
      h('div', { class: 'reading' }, bundle.sentences.map(x => x.zh).join('')),
      h('div', { class: 'row end' }, nextButton(s, 'Done', () => done(elapsed(t0)))));
  });
  const cpm = Math.round(bundle.chars / (ms / 60000));
  logEvent(sid, 'placement_read', 'timed', { phase: 'timed', chars: bundle.chars, ms, cpm, sentence_ids: bundle.sentences.map(x => x.id) }, ms);
  let right = 0;
  for (const [i, q] of bundle.questions.entries()) {
    await step(scope, (s, done) => {
      const t0 = performance.now();
      const next = nextButton(s, 'Next', () => done());
      next.hidden = true;
      frame(root, 'Reading', i, bundle.questions.length,
        h('p', { class: 'prompt' }, 'Which of these did the text say?'),
        choices(s, q.options, q.answer, (choice, correct) => {
          right += correct;
          logEvent(sid, 'placement_read', q.id, { phase: 'question', choice, correct }, elapsed(t0));
          next.hidden = false;
        }),
        h('div', { class: 'row end' }, next));
    });
  }
  return { cpm, right, n: bundle.questions.length };
}

function results(root, p) {
  const lv = p.levels;
  root.replaceChildren(h('section', { class: 'panel' },
    h('h1', {}, 'Your starting profile'),
    h('div', { class: 'levels' }, [1, 2, 3, 4].map(l => h('div', { class: 'level' },
      h('span', {}, `HSK ${l}`),
      h('div', { class: 'meter' }, h('div', { style: `width:${lv[l].corrected * 100}%` })),
      h('span', {}, `${pct(lv[l].corrected)} ${lv[l].corrected >= 0.9 ? '· known' : lv[l].corrected > 0 ? '· partial' : ''}`)))),
    h('p', { class: 'muted' }, `Yes to ${p.false_alarm.claimed} of ${p.false_alarm.n} made-up words (false-alarm rate ${pct(p.false_alarm.rate)}), subtracted from each level's hit rate. `,
      `Spot check: ${p.spot.correct}/${p.spot.n} meanings right${p.spot.missed.length ? `; ${p.spot.missed.join('、')} went to your cards` : ''}.`),
    h('div', { class: 'tiles' },
      tile('Words known', p.known_count, `${p.queued_count} queued as new cards`),
      tile('Listening', `${p.listen.correct}/${p.listen.n}`, 'sentence meanings'),
      tile('Tones', `${p.tone.correct}/${p.tone.n}`, [1, 2, 3, 4].map(t => `T${t} ${p.tone.by_tone[t][0]}/${p.tone.by_tone[t][1]}`).join(' · ')),
      tile('Reading', p.read.cpm ? `${p.read.cpm} cpm` : '–', `${p.read.correct}/${p.read.n_questions} questions`)),
    h('div', { class: 'row end' }, h('a', { class: 'button primary', href: '#/session' }, "Start today's session"))));
}

export const tile = (label, value, sub) => h('div', { class: 'tile' }, h('div', { class: 'label' }, label), h('div', { class: 'value' }, value), h('div', { class: 'sub' }, sub));

export async function placementScreen(root, scope) {
  await voicesReady;
  await intro(scope, root, 'Placement test (about 10 minutes)', [
    'Four parts: a yes/no vocabulary check across HSK 1-4, listening for meaning, telling tones apart, and a short timed read.',
    'Answer honestly and quickly. The result sets which words start as known and which queue as new cards.',
    'Turn your sound on. Keyboard shortcuts are shown on every button.']);
  const p = await post('/api/placement/start');
  const sid = p.session_id;
  await vocab(scope, root, sid, p.vocab);
  await spot(scope, root, sid, spotPicks(p.vocab));
  await intro(scope, root, 'Listening', ['Ten sentences, audio only. Pick the English meaning. Replay as often as you like.']);
  await listen(scope, root, sid, p.listen);
  await intro(scope, root, 'Tones', ['Twelve two-syllable words in different voices. Pick the tone of each syllable.']);
  await tones(scope, root, sid, p.tone);
  await readingTest(scope, root, sid, await post('/api/placement/reading', { session_id: sid }));
  root.replaceChildren(h('section', { class: 'panel' }, h('p', {}, 'Scoring…')));
  results(root, await post('/api/placement/finish', { session_id: sid }));
}

export async function readingScreen(root, scope) {
  const b = await post('/api/reading/start');
  const r = await readingTest(scope, root, b.session_id, b);
  root.replaceChildren(h('section', { class: 'panel' }, h('h1', {}, 'Reading check saved'),
    h('div', { class: 'tiles' }, tile('Speed', `${r.cpm} cpm`, `${b.chars} characters`), tile('Comprehension', `${r.right}/${r.n}`, 'questions')),
    h('div', { class: 'row end' }, h('a', { class: 'button', href: '#/stats' }, 'See stats'), h('a', { class: 'button primary', href: '#/home' }, 'Home'))));
}

