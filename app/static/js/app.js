import { get } from './api.js';
import { stopAudio } from './audio.js';
import { placementScreen, readingScreen, tile } from './placement.js';
import { sessionScreen } from './session.js';
import { statsScreen } from './stats.js';
import { h, Scope, toast, pct } from './ui.js';

async function homeScreen(root) {
  const st = await get('/api/state');
  const p = st.placement;
  if (!p) {
    root.replaceChildren(h('section', { class: 'panel intro' },
      h('h1', {}, 'HSK 4 by June 2027'),
      h('p', {}, 'Thirty minutes a day: cards, listening and reading, then speaking. First, a 10-minute placement finds what you already know.'),
      h('a', { class: 'button primary', href: '#/placement' }, 'Start placement')));
    return;
  }
  const w = await get('/api/stats').then(s => s.words);
  root.replaceChildren(h('section', { class: 'panel' },
    h('h1', {}, 'Today'),
    h('div', { class: 'tiles' },
      tile('Reviews due', st.queue.due, 'cards'),
      tile('New words', st.queue.new, `of ${st.config.new_cards_per_day} per day`),
      tile('Words started', `${w.started} / ${w.target}`, `${w.solid} solid (known or mature)`),
      tile('Pace needed', `${w.needed_per_day}/day`, `to reach ${w.target} by ${w.target_date}`)),
    h('div', { class: 'meter wide' }, h('div', { style: `width:${(100 * w.started) / w.target}%` }), h('div', { class: 'solid', style: `width:${(100 * w.solid) / w.target}%` })),
    h('div', { class: 'row end' },
      h('a', { class: 'button', href: '#/reading' }, 'Reading check'),
      h('a', { class: 'button', href: '#/placement' }, 'Retake placement'),
      h('a', { class: 'button primary', href: '#/session' }, `Start ${st.config.blocks.reduce((a, b) => a + b.minutes, 0)}-minute session`)),
    h('p', { class: 'muted' }, `Placement ${p.date.slice(0, 10)}: listening ${p.listen.correct}/${p.listen.n}, tones ${pct(p.tone.correct / p.tone.n)}, reading ${p.read.cpm || '–'} characters/min.`)));
}

const ROUTES = { home: homeScreen, placement: placementScreen, session: sessionScreen, stats: statsScreen, reading: readingScreen };
let scope = null;

async function route() {
  if (scope) scope.close();
  stopAudio();
  scope = new Scope();
  const name = location.hash.replace(/^#\/?/, '').split('/')[0] || 'home';
  document.querySelectorAll('nav a').forEach(a => a.classList.toggle('active', a.dataset.route === name));
  const main = document.getElementById('main');
  main.replaceChildren();
  window.scrollTo(0, 0);
  try {
    await (ROUTES[name] || homeScreen)(main, scope);
  } catch (e) {
    console.error(e);
    toast(e.message);
  }
}

window.addEventListener('hashchange', route);
window.addEventListener('pagehide', () => scope && scope.close());
window.addEventListener('unhandledrejection', e => toast(e.reason && e.reason.message ? e.reason.message : String(e.reason)));
route();
