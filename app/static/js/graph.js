// Graph page: the local HSK character graph around one word, character or component.
// Words are coloured by card state (3 validated slots: new s1, in progress s2, known s3); characters and
// components are told apart by shape, so colour never carries identity alone. Every node is labelled.
import { post } from './api.js';
import { speak } from './audio.js';
import { h } from './ui.js';

const SVG = 'http://www.w3.org/2000/svg';
const s = (tag, attrs = {}, ...kids) => {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  el.append(...kids);
  return el;
};
const SLOT = { new: 's1', learning: 's2', review: 's2', relearning: 's2', known: 's3' };
const STATE = { new: 'New', learning: 'Learning', review: 'In review', relearning: 'Relearning', known: 'Known' };
const W = 560, H = 520;  // close to the drawn size, so labels render near their CSS size

function parseHash() {
  const [path, query = ''] = location.hash.replace(/^#\/?graph\/?/, '').split('?');
  return { center: decodeURIComponent(path) || '学', depth: new URLSearchParams(query).get('d') === '2' ? 2 : 1 };
}
const go = (node, depth) => { location.hash = `#/graph/${encodeURIComponent(node)}?d=${depth}`; };

// Deterministic force layout: same graph, same picture. Center pinned; repulsion, springs, light gravity.
function layout(nodes, edges) {
  const idx = new Map(nodes.map((n, i) => [n.id, i]));
  const P = nodes.map((n, i) => {
    if (n.dist === 0) return { x: 0, y: 0 };
    const r = 100 * n.dist, a = i * 2.399963;
    return { x: r * Math.cos(a), y: r * Math.sin(a) };
  });
  const E = edges.map(e => [idx.get(e.s), idx.get(e.t)]);
  const N = nodes.length, steps = 400;
  for (let it = 0; it < steps; it++) {
    const F = P.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      const dx = P[i].x - P[j].x, dy = P[i].y - P[j].y, d2 = Math.max(dx * dx + dy * dy, 25), d = Math.sqrt(d2);
      const f = 6000 / d2;
      F[i].x += f * dx / d; F[i].y += f * dy / d; F[j].x -= f * dx / d; F[j].y -= f * dy / d;
    }
    for (const [a, b] of E) {
      const dx = P[b].x - P[a].x, dy = P[b].y - P[a].y, d = Math.max(Math.hypot(dx, dy), 1), f = (d - 110) * 0.04;
      F[a].x += f * dx / d; F[a].y += f * dy / d; F[b].x -= f * dx / d; F[b].y -= f * dy / d;
    }
    const t = 12 * (1 - it / steps) + 0.5;
    for (let i = 0; i < N; i++) {
      if (nodes[i].dist === 0) continue;
      F[i].x -= P[i].x * 0.01; F[i].y -= P[i].y * 0.01;
      const m = Math.hypot(F[i].x, F[i].y);
      if (m > 0) { P[i].x += F[i].x / m * Math.min(m, t); P[i].y += F[i].y / m * Math.min(m, t); }
    }
  }
  // Fit into the viewBox with room for labels.
  const xs = P.map(p => p.x), ys = P.map(p => p.y), pad = 40;
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const k = Math.min((W - 2 * pad) / Math.max(x1 - x0, 1), (H - 2 * pad - 20) / Math.max(y1 - y0, 1), 1.6);
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  return P.map(p => ({ x: W / 2 + (p.x - cx) * k, y: H / 2 - 10 + (p.y - cy) * k }));
}

function nodeMark(n) {
  const big = n.dist === 0, r = big ? 14 : 9;
  if (n.kind === 'word') return s('circle', { r, class: `gn word ${SLOT[n.state] || 's1'}${big ? ' center' : ''}` });
  if (n.kind === 'character') return s('circle', { r: r - 1, class: `gn char${big ? ' center' : ''}` });
  return s('rect', { x: -r + 1, y: -r + 1, width: 2 * r - 2, height: 2 * r - 2, rx: 2, class: `gn comp${big ? ' center' : ''}` });
}

const kindLabel = n => n.kind === 'word' ? `${STATE[n.state] || 'New'} · HSK ${n.hsk}` : n.kind === 'character' ? 'Character (not an HSK word on its own)' : 'Component';
const dot = n => n.kind === 'word' ? h('span', { class: `gdot ${SLOT[n.state] || 's1'}` }) : h('span', { class: `gdot ${n.kind}` });

function legend() {
  const item = (mark, label) => h('span', { class: 'legend-item' }, mark, label);
  return h('div', { class: 'graph-legend' },
    item(h('span', { class: 'gdot s3' }), 'Known'),
    item(h('span', { class: 'gdot s2' }), 'Learning / review'),
    item(h('span', { class: 'gdot s1' }), 'New'),
    item(h('span', { class: 'gdot character' }), 'Character'),
    item(h('span', { class: 'gdot component' }), 'Component'),
    item(h('span', { class: 'gline contains' }), 'contains'),
    item(h('span', { class: 'gline sound' }), 'sound part'),
    item(h('span', { class: 'gline meaning' }), 'meaning part'));
}

function searchBox(scope, depth) {
  const results = h('div', { class: 'graph-results', hidden: true });
  const input = h('input', { type: 'search', placeholder: 'Find a word: 学, xuesheng…', 'aria-label': 'Find a word', autocomplete: 'off' });
  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const { results: rs } = await post('/api/graph/search', { q: input.value });
      results.replaceChildren(...rs.map(n => h('button', { class: 'graph-result', onclick: () => go(n.id, depth) },
        dot(n), h('span', { class: 'hanzi' }, n.id), h('span', { class: 'muted' }, ` ${n.pinyin} · ${n.meaning}`))));
      results.hidden = !rs.length;
    }, 150);
  });
  input.addEventListener('keydown', e => {
    const first = results.querySelector('button');
    if (e.key === 'Enter' && first) first.click();
  });
  scope.on(document, 'pointerdown', e => { if (!results.contains(e.target) && e.target !== input) results.hidden = true; });
  return h('div', { class: 'graph-search' }, input, results);
}

function panel(data) {
  const c = data.nodes.find(n => n.dist === 0);
  const o = data.obsidian;
  return h('aside', { class: 'graph-panel' },
    h('div', { class: 'row' }, h('span', { class: 'hanzi xl' }, c.id),
      c.kind === 'word' ? h('button', { class: 'small', onclick: () => speak(c.id), 'aria-label': 'Play' }, '▶') : null),
    h('p', { class: 'py lg' }, c.pinyin),
    h('p', {}, c.meaning || '—'),
    h('p', { class: 'muted' }, dot(c), ' ', kindLabel(c)),
    o && c ? h('a', { class: 'obsidian-link', href: `obsidian://open?vault=${encodeURIComponent(o.vault)}&file=${encodeURIComponent(`${o.folder}/${c.id}`)}` }, 'Open in Obsidian →') : null,
    ...data.neighbours.map(g => h('div', { class: 'graph-group' },
      h('h3', {}, g.label, h('span', { class: 'muted' }, ` ${g.items.length}`)),
      h('div', { class: 'chips' }, ...g.items.map(n => h('a', { class: 'chip', href: `#/graph/${encodeURIComponent(n.id)}?d=${data.depth}`, title: `${n.pinyin} · ${n.meaning}` }, dot(n), n.id))))),
    data.hidden ? h('p', { class: 'muted' }, `${data.hidden} less common nodes not drawn at 2 steps.`) : null);
}

function drawGraph(data, tip) {
  const pos = layout(data.nodes, data.edges);
  const at = new Map(data.nodes.map((n, i) => [n.id, pos[i]]));
  const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'viz graph-viz', role: 'img', 'aria-label': `Graph of ${data.center}` });
  const lines = s('g', { class: 'gedges' });
  for (const e of data.edges) {
    const a = at.get(e.s), b = at.get(e.t);
    lines.append(s('line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: `gedge ${e.type === 'contains' ? 'contains' : e.role}` }));
  }
  svg.append(lines);
  for (const [i, n] of data.nodes.entries()) {
    const p = pos[i];
    const g = s('g', { class: 'gnode', transform: `translate(${p.x.toFixed(1)},${p.y.toFixed(1)})`, tabindex: 0, role: 'link',
      'aria-label': `${n.id} ${n.pinyin} ${n.meaning}` });
    g.append(nodeMark(n), s('text', { y: n.dist === 0 ? 36 : 27, class: `glabel${n.dist === 0 ? ' center' : ''}` }, n.id),
      s('circle', { r: 20, class: 'ghit' }));
    g.addEventListener('pointermove', e => {
      tip.replaceChildren(h('div', {}, h('b', {}, n.id), ` ${n.pinyin}`), h('div', {}, n.meaning), h('div', { class: 'muted' }, kindLabel(n)));
      tip.style.left = `${Math.min(window.innerWidth - 240, e.clientX + 14)}px`;
      tip.style.top = `${e.clientY + 14}px`;
      tip.hidden = false;
    });
    g.addEventListener('pointerleave', () => { tip.hidden = true; });
    const open = () => { tip.hidden = true; go(n.id, data.depth); };
    g.addEventListener('click', open);
    g.addEventListener('keydown', e => { if (e.key === 'Enter') open(); });
    svg.append(g);
  }
  return svg;
}

export async function graphScreen(root, scope) {
  const { center, depth } = parseHash();
  const tip = h('div', { class: 'viz-tip', hidden: true });
  scope.defer(() => tip.remove());
  const depthButton = d => h('button', { class: `seg${d === depth ? ' on' : ''}`, onclick: () => go(center, d) }, d === 1 ? '1 step' : '2 steps');
  const head = h('div', { class: 'graph-head' }, h('h1', {}, 'Graph'), searchBox(scope, depth),
    h('div', { class: 'segmented', role: 'group', 'aria-label': 'Depth' }, depthButton(1), depthButton(2)));
  let data;
  try {
    data = await post('/api/graph', { node: center, depth });
  } catch (e) {
    root.replaceChildren(h('section', { class: 'panel' }, head, h('p', {}, `${center} is not in the HSK 1-4 graph. Search for another word.`)));
    return;
  }
  root.replaceChildren(h('section', { class: 'panel graph-page viz-root' }, head, legend(),
    h('div', { class: 'graph-layout' }, h('figure', { class: 'graph-figure' }, drawGraph(data, tip)), panel(data))), tip);
}
