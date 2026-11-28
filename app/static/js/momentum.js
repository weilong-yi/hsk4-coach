// Momentum views shared by Home, the session-complete screen and Stats: today's rings, the streak and freezes,
// the four-week calendar strip, the if-then plan, and what a session moved forward. Data comes from app/momentum.py.
import { post } from './api.js';
import { h, pct } from './ui.js';

const NS = 'http://www.w3.org/2000/svg';
const svg = (tag, attrs = {}, ...kids) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  el.append(...kids);
  return el;
};

const COLOR = { cards: 'var(--s1)', listen: 'var(--s2)', speak: 'var(--s3)' };  // the Stats page's block colours
const NOUN = { cards: ['card', 'cards'], listen: ['listening answer', 'listening answers'], speak: ['recording', 'recordings'] };
const STATUS = { met: 'Met', frozen: 'Frozen: a freeze kept the streak', missed: 'Missed', pending: 'Today', future: 'Coming up', none: 'Before you started' };
const plural = (n, [one, many]) => `${n} ${n === 1 ? one : many}`;

// One ring per activity: the arc fills toward the day's target. The tick sits at the minimum fraction (half), so
// a ring whose arc reaches its tick meets today's minimum.
export function ringsView(rings) {
  const R = 26, W = 8, CELL = 112, CY = 38;
  const root = svg('svg', { class: 'rings', viewBox: `0 0 ${CELL * rings.length} 100`, role: 'img',
    'aria-label': `Today: ${rings.map(r => `${r.label} ${r.count} of ${r.target}`).join(', ')}` });
  rings.forEach((r, i) => {
    const cx = CELL * (i + 0.5), C = 2 * Math.PI * R;
    const a = 2 * Math.PI * r.minimum_fill - Math.PI / 2;
    const at = rr => [cx + rr * Math.cos(a), CY + rr * Math.sin(a)];
    const [x1, y1] = at(R + W / 2 + 2), [x2, y2] = at(R + W / 2 + 7);
    root.append(svg('g', { class: 'ring' },
      svg('title', {}, `${r.label}: ${r.count} of ${r.target} today; ${r.minimum} meet the minimum`),
      svg('circle', { class: 'track', cx, cy: CY, r: R, stroke: COLOR[r.id], 'stroke-width': W }),
      r.count ? svg('circle', { class: 'arc', cx, cy: CY, r: R, stroke: COLOR[r.id], 'stroke-width': W,
        'stroke-dasharray': `${C * r.fill} ${C}`, transform: `rotate(-90 ${cx} ${CY})` }) : '',
      svg('line', { class: 'tick', x1, y1, x2, y2 }),
      svg('text', { class: 'ring-label', x: cx, y: CY + R + W / 2 + 22 },
        svg('tspan', {}, `${r.label} `), svg('tspan', { class: 'count' }, `${r.count}/${r.target}`))));
  });
  return root;
}

export function freezeText(m) {
  const held = m.freezes ? `${plural(m.freezes, ['freeze', 'freezes'])} saved` : 'No freezes saved yet';
  if (m.next_freeze_in == null) return `${held}, the most you can hold`;
  return `${held} · ${m.freezes ? 'next' : 'first'} one after ${plural(m.next_freeze_in, ['more day', 'more days'])} in a row`;
}

export const streakText = m => (m.streak ? `${m.streak}-day streak` : 'No streak yet');

export function minimumText(today) {
  if (today.met) return "Today's minimum is met.";
  const { ring, more, started } = today.next;
  return `${started ? `${more} more ${more === 1 ? NOUN[ring][0] : NOUN[ring][1]}` : plural(more, NOUN[ring])} would count today.`;
}

// Rings beside the streak, freezes and the minimum. `gained` marks a session that just met today's minimum.
export function todayView(m, { gained = false } = {}) {
  return h('div', { class: 'momentum' },
    ringsView(m.today.rings),
    h('div', { class: 'momentum-text' },
      h('div', { class: 'streak-n' }, streakText(m), gained ? h('span', { class: 'gain' }, '+1 today') : null),
      h('p', { class: 'muted freezes', title: 'A freeze covers one missed day, so the streak carries on.' }, freezeText(m)),
      h('p', { class: 'minimum' }, minimumText(m.today))));
}

const isoDate = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const parse = iso => new Date(`${iso}T12:00:00`);
const shift = (iso, n) => { const d = parse(iso); return isoDate(new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)); };
const label = iso => parse(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });

// Up to four Monday-to-Sunday weeks ending with this one, starting with the week of the first study day.
// `days` is the last 28 study days, today last.
export function calendarStrip(days) {
  const today = days[days.length - 1].date;
  const ahead = 6 - ((parse(today).getDay() + 6) % 7);
  const cells = [...days.slice(ahead), ...Array.from({ length: ahead }, (_, i) => ({ date: shift(today, i + 1), status: 'future' }))];
  const weeks = [0, 7, 14, 21].filter(k => k === 21 || cells.slice(k, k + 7).some(c => c.status !== 'none'));
  const cell = c => h('span', { class: `day ${c.status}${c.date === today ? ' today' : ''}`, role: 'listitem',
    title: `${label(c.date)}: ${STATUS[c.status]}`, 'aria-label': `${label(c.date)}: ${STATUS[c.status]}` });
  return h('div', { class: 'calendar' },
    h('div', { class: 'weeks', role: 'list', 'aria-label': 'Study days by week' }, weeks.map(k => h('div', { class: 'week' },
      h('div', { class: 'days' }, cells.slice(k, k + 7).map(cell)),
      h('div', { class: 'week-label' }, label(cells[k].date))))),
    h('div', { class: 'cal-legend' }, ['met', 'frozen', 'missed', 'pending', 'future'].map(s =>
      h('span', {}, h('span', { class: `day ${s}${s === 'pending' ? ' today' : ''}` }), s === 'frozen' ? 'Frozen' : STATUS[s]))));
}

const sentence = cue => cue.replace(/[.!,;:\s]+$/, '').replace(/^[A-Z](?=[a-z])/, ch => ch.toLowerCase());
export const ifThen = plan => `If it's ${plan.time} ${sentence(plan.cue)}, I study.`;

// The if-then plan: shown as one sentence once set, edited in place as the same sentence with two fields.
export function planView(m) {
  const box = h('div', { class: 'plan' });
  let reminderOn = m.reminder;
  const show = (plan, note) => box.replaceChildren(...[
    h('div', { class: 'plan-line' }, h('span', { class: 'plan-label' }, 'Plan'), h('span', { class: 'if-then' }, ifThen(plan)),
      h('button', { class: 'link', onclick: () => edit(plan, true) }, 'Edit')),
    reminderOn && h('p', { class: 'muted' }, `A reminder shows at ${plan.time} on this Mac if today's minimum isn't met.`),
    note].filter(Boolean));
  const edit = (plan, focus) => {
    const time = h('input', { type: 'time', name: 'time', required: true, value: plan ? plan.time : '19:30', 'aria-label': 'Time' });
    const cue = h('input', { type: 'text', name: 'cue', required: true, maxlength: 80, value: plan ? plan.cue : '',
      placeholder: 'after dinner at my desk', 'aria-label': 'Where or after what' });
    const save = async e => {
      e.preventDefault();
      const r = await post('/api/plan', { cue: cue.value, time: time.value });
      reminderOn = !!(r.reminder && r.reminder.path);
      show(r.plan, r.reminder && r.reminder.error && h('p', { class: 'warn' }, `Plan saved, but the reminder could not be set: ${r.reminder.error}`));
    };
    box.replaceChildren(h('form', { class: 'plan-form', onsubmit: save },
      h('span', { class: 'plan-label' }, 'Plan'),
      h('span', {}, "If it's"), time, cue, h('span', {}, ', I study.'),
      h('button', { type: 'submit', class: 'small' }, 'Save plan'),
      plan ? h('button', { type: 'button', class: 'link', onclick: () => show(plan) }, 'Cancel')
        : h('p', { class: 'muted' }, 'Tie study to a time and a place you already pass every day.')));
    if (focus) cue.focus();
  };
  if (m.plan) show(m.plan);
  else edit(null, false);
  return box;
}

const chips = words => h('span', { class: 'chips' }, words.slice(0, 16).map(w =>
  h('a', { class: 'chip', href: `#/graph/${encodeURIComponent(w)}`, title: 'Open in the graph' }, w)),
  words.length > 16 ? h('span', { class: 'muted' }, `+${words.length - 16} more`) : null);

function listeningText({ this_week: a, last_week: b }) {
  const part = (w, name) => (w.n ? `${name} ${pct(w.rate)} of ${plural(w.n, ['sentence', 'sentences'])}` : `${name} none`);
  if (!a.n && !b.n) return 'No listening in the last two weeks.';
  return `${part(a, 'Last 7 days')}; ${part(b, 'the 7 days before')}.`;
}

// What a session moved forward, from app/momentum.py feedback(): graduations, new words, recall, listening trend.
export function progressView(fb) {
  const item = (name, ...body) => h('div', { class: 'progress-item' }, h('b', {}, name), h('div', {}, ...body));
  return h('div', { class: 'progress-list' },
    item('Moved forward', fb.moved.length ? [`${plural(fb.moved.length, ['word', 'words'])} now in review `, chips(fb.moved)]
      : 'No words reached review this time.'),
    item('New words', fb.introduced.length ? [`${plural(fb.introduced.length, ['word', 'words'])} started `, chips(fb.introduced)] : 'None this time.'),
    fb.reviews.n ? item('Recall', `You remembered ${fb.reviews.recalled} of ${fb.reviews.n} reviews (${pct(fb.reviews.recalled / fb.reviews.n)}).`) : null,
    item('Listening understood', listeningText(fb.listening)));
}
