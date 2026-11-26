import { get } from './api.js';
import { tile } from './placement.js';
import { h, pct } from './ui.js';

const NS = 'http://www.w3.org/2000/svg';
const W = 640, H = 180, M = { l: 40, r: 12, t: 12, b: 24 };
const BLOCKS = [{ key: 'cards', label: 'Cards', color: 'var(--s1)' }, { key: 'listen', label: 'Listen & read', color: 'var(--s2)' }, { key: 'speak', label: 'Speak', color: 'var(--s3)' }];
const WINDOW_DAYS = 28;

const s = (tag, attrs = {}, ...kids) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  el.append(...kids);
  return el;
};

// Four clean gridline steps: the top is 4x a 1/2/2.5/5 step.
function niceMax(v) {
  const raw = Math.max(v, 0.001) / 4, p = 10 ** Math.floor(Math.log10(raw)), f = raw / p;
  return 4 * (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}

const tip = h('div', { class: 'viz-tip', hidden: true });
function hover(el, lines) {
  el.addEventListener('pointermove', e => {
    tip.replaceChildren(...lines.map(([strong, rest]) => h('div', {}, h('b', {}, strong), rest ? ` ${rest}` : '')));
    tip.style.left = `${Math.min(window.innerWidth - 220, e.clientX + 14)}px`;
    tip.style.top = `${e.clientY + 14}px`;
    tip.hidden = false;
  });
  el.addEventListener('pointerleave', () => { tip.hidden = true; });
}

function frame(yMax, fmt, labels) {
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'viz', role: 'img' });
  const ih = H - M.t - M.b;
  for (let i = 0; i <= 4; i++) {
    const y = M.t + ih - (ih * i) / 4;
    svg.append(s('line', { x1: M.l, x2: W - M.r, y1: y, y2: y, class: i ? 'grid' : 'axis' }),
      s('text', { x: M.l - 6, y: y + 4, 'text-anchor': 'end', class: 'tick' }, fmt((yMax * i) / 4)));
  }
  const band = (W - M.l - M.r) / labels.length;
  const every = Math.ceil(labels.length / 10);
  labels.forEach((l, i) => {
    if (i % every === 0 || i === labels.length - 1) svg.append(s('text', { x: M.l + band * (i + 0.5), y: H - 6, 'text-anchor': 'middle', class: 'tick' }, l));
  });
  return { svg, band, y: v => M.t + ih - (ih * v) / yMax, x: i => M.l + band * (i + 0.5) };
}

const roundTop = (x, y, w, hgt, r) => (hgt <= r ? `M${x},${y + hgt}V${y}H${x + w}V${y + hgt}Z`
  : `M${x},${y + hgt}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hgt}Z`);

function columns(days, series, fmt) {
  const totals = days.map(d => series.reduce((a, se) => a + (d.values[se.key] || 0), 0));
  const yMax = niceMax(Math.max(...totals, 0.001));
  const f = frame(yMax, fmt, days.map(d => d.label));
  const bw = Math.min(24, f.band * 0.6);
  days.forEach((d, i) => {
    let acc = 0;
    const present = series.filter(se => d.values[se.key] > 0);
    present.forEach((se, k) => {
      const bottom = f.y(acc) - (k ? 2 : 0);
      acc += d.values[se.key];
      const top = f.y(acc), hgt = Math.max(0, bottom - top), x = f.x(i) - bw / 2;
      f.svg.append(k === present.length - 1 ? s('path', { d: roundTop(x, top, bw, hgt, 4), fill: se.color })
        : s('rect', { x, y: top, width: bw, height: hgt, fill: se.color }));
    });
    const hit = s('rect', { x: f.x(i) - f.band / 2, y: M.t, width: f.band, height: H - M.t - M.b, fill: 'transparent' });
    hover(hit, [[d.label, ''], ...series.map(se => [fmt(d.values[se.key] || 0), se.label])]);
    f.svg.append(hit);
  });
  return f.svg;
}

function line(points, fmt, yMax) {
  yMax = yMax || niceMax(Math.max(...points.map(p => p.y || 0), 0.001));
  const f = frame(yMax, fmt, points.map(p => p.label));
  let d = '';
  points.forEach((p, i) => {
    if (p.y == null) return;
    const prev = points[i - 1];
    d += `${prev && prev.y != null ? 'L' : 'M'}${f.x(i)},${f.y(p.y)}`;
  });
  f.svg.append(s('path', { d, class: 'line' }));
  points.forEach((p, i) => {
    if (p.y == null) return;
    f.svg.append(s('circle', { cx: f.x(i), cy: f.y(p.y), r: 4, class: 'dot' }));
    const hit = s('circle', { cx: f.x(i), cy: f.y(p.y), r: 12, fill: 'transparent' });
    hover(hit, [[fmt(p.y), p.label], ...(p.extra || []).map(e => [e, ''])]);
    f.svg.append(hit);
  });
  return f.svg;
}

function figure(title, subtitle, chart, table, legend) {
  return h('figure', { class: 'viz-root' },
    h('figcaption', {}, h('b', {}, title), subtitle ? h('span', {}, subtitle) : null),
    legend ? h('div', { class: 'legend' }, legend.map(l => h('span', {}, h('i', { style: `background:${l.color}` }), l.label))) : null,
    chart,
    h('details', {}, h('summary', {}, 'Table'), table));
}

const table = (head, rows) => h('table', {}, h('thead', {}, h('tr', {}, head.map(x => h('th', {}, x)))),
  h('tbody', {}, rows.map(r => h('tr', {}, r.map(x => h('td', {}, x == null ? '–' : x))))));

function lastDays(n) {
  const out = [];
  const now = new Date();
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`);
  }
  return out;
}

export async function statsScreen(root) {
  const st = await get('/api/stats');
  const byDate = Object.fromEntries(st.per_day.map(d => [d.date, d]));
  const days = lastDays(WINDOW_DAYS).map(date => ({ date, label: `${Number(date.slice(5, 7))}/${Number(date.slice(8))}`, d: byDate[date] }));
  const w = st.words;
  const minutes = days.map(x => ({ label: x.label, values: x.d ? x.d.minutes : {} }));
  const active = st.per_day.slice(-WINDOW_DAYS);

  root.replaceChildren(h('section', { class: 'panel stats' },
    h('h1', {}, 'Progress'),
    h('div', { class: 'tiles' },
      tile('Words started', `${w.started} / ${w.target}`, `${w.known_placement} from placement, ${w.learning + w.mature} as cards`),
      tile('Solid', w.solid, `known at placement or mature (stability ≥ 21 days)`),
      tile('Pace needed', `${w.needed_per_day} / day`, `${w.days_left} days to ${w.target_date}`),
      tile('Recent pace', `${w.recent_per_day} / day`, w.projected_date ? `on track for ${w.projected_date}` : 'no new cards in 14 days')),
    h('div', { class: 'meter wide' }, h('div', { style: `width:${(100 * w.started) / w.target}%` }), h('div', { class: 'solid', style: `width:${(100 * w.solid) / w.target}%` })),

    figure('Minutes per block', `last ${WINDOW_DAYS} days, on each block's timer from start to end`,
      columns(minutes, BLOCKS, v => (v < 10 ? v.toFixed(1).replace(/\.0$/, '') : Math.round(v))),
      table(['Date', ...BLOCKS.map(b => b.label)], active.map(d => [d.date, ...BLOCKS.map(b => d.minutes[b.key])])), BLOCKS),

    figure('Cards reviewed', `per day, last ${WINDOW_DAYS} days`,
      columns(days.map(x => ({ label: x.label, values: { cards: x.d ? x.d.cards : 0 } })), [{ key: 'cards', label: 'reviews', color: 'var(--s1)' }], v => Math.round(v)),
      table(['Date', 'Reviews', 'New'], active.map(d => [d.date, d.cards, d.new_cards]))),

    h('figure', { class: 'viz-root' },
      h('figcaption', {}, h('b', {}, 'Calibration: recall vs FSRS prediction'),
        h('span', {}, `${st.calibration_reviews} reviews of cards in the Review state, binned by FSRS-predicted recall at review time. ${st.learning_step_reviews} same-day learning-step reviews are left out: FSRS counts whole days, so it predicts 100% for them.`)),
      table(['Predicted retrievability', 'Reviews', 'Mean predicted', 'Actually recalled'],
        st.calibration.map(b => [b.bin, b.n, pct(b.predicted), pct(b.recalled)]))),

    figure('Listening understood', 'share of sentences marked understood before seeing the text',
      line(days.map(x => ({ label: x.label, y: x.d ? x.d.understood_rate : null, extra: x.d ? [`${x.d.listened} sentences`] : [] })), v => pct(v), 1),
      table(['Date', 'Sentences', 'Understood', 'Lookups'], active.map(d => [d.date, d.listened, pct(d.understood_rate), d.lookups]))),

    figure('Shadowing match', 'characters of the target sentence found in the speech-recognition transcript',
      line(days.map(x => ({ label: x.label, y: x.d ? x.d.shadow_score : null, extra: x.d ? [`${x.d.shadow_scored} of ${x.d.shadow_attempts} attempts scored`] : [] })), v => pct(v), 1),
      table(['Date', 'Attempts', 'Scored', 'Mean match'], active.map(d => [d.date, d.shadow_attempts, d.shadow_scored, pct(d.shadow_score)]))),

    figure('Reading speed', 'timed reads from placement and reading checks, characters per minute',
      st.reading.length > 1 ? line(st.reading.map(r => ({ label: r.date.slice(5), y: r.cpm, extra: [`comprehension ${pct(r.accuracy)}`] })), v => Math.round(v)) : h('p', { class: 'muted' }, st.reading.length ? `One timed read so far: ${st.reading[0].cpm} cpm. Use Reading check on Home to add more.` : 'No timed reads yet.'),
      table(['Date', 'Chars/min', 'Characters', 'Comprehension'], st.reading.map(r => [r.date, r.cpm, r.chars, pct(r.accuracy)]))),
    tip));
}
