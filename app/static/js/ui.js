export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  }
  return el;
}

// A Scope owns listeners, timers, and teardown (mic, audio). Closing a scope closes its children,
// so leaving a screen or step releases everything it started.
export class Scope {
  constructor(parent) {
    this.fns = [];
    this.closed = false;
    if (parent) parent.defer(() => this.close());
  }
  defer(fn) {
    if (this.closed) fn();
    else this.fns.push(fn);
  }
  child() { return new Scope(this); }
  close() {
    if (this.closed) return;
    this.closed = true;
    while (this.fns.length) {
      try { this.fns.pop()(); } catch (e) { console.error(e); }
    }
  }
  on(target, type, fn) {
    target.addEventListener(type, fn);
    this.defer(() => target.removeEventListener(type, fn));
  }
  keys(map) {
    this.on(window, 'keydown', e => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
      const fn = map[e.key] || map[e.code];
      if (fn) { e.preventDefault(); fn(e); }
    });
  }
  interval(fn, ms) {
    const id = setInterval(fn, ms);
    this.defer(() => clearInterval(id));
  }
  timeout(fn, ms) {
    const id = setTimeout(fn, ms);
    this.defer(() => clearTimeout(id));
  }
}

// Run one UI step in a child scope; resolves with the value passed to done().
export function step(scope, build) {
  return new Promise(resolve => {
    if (scope.closed) return;
    const s = scope.child();
    build(s, value => { s.close(); resolve(value); });
  });
}

// ?timescale=N runs block timers N times faster (used by app/e2e.py).
export const TIMESCALE = Number(new URLSearchParams(location.search).get('timescale')) || 1;
export const clock = () => performance.now() * TIMESCALE;
export const elapsed = t0 => Math.round(performance.now() - t0);

export class BlockTimer {
  constructor(minutes, el, scope, usedMs = 0) {
    this.total = minutes * 60000;
    this.t0 = clock() - usedMs;  // a resumed block continues from the time it had used
    this.el = el;
    scope.interval(() => this.render(), 250);
    this.render();
  }
  get ms() { return Math.round(clock() - this.t0); }
  get expired() { return this.ms >= this.total; }
  render() {
    const left = Math.max(0, this.total - this.ms) / 1000;
    this.el.textContent = this.expired ? "Time's up · finish this item"
      : `${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, '0')}`;
    this.el.classList.toggle('expired', this.expired);
    this.el.style.setProperty('--progress', Math.min(1, this.ms / this.total));
  }
}

export function toast(msg, kind = 'error') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `show ${kind}`;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { el.className = ''; }, 5000);
}

export const kbd = k => h('kbd', {}, k);

// Multiple-choice question: keys 1-4 pick; marks right/wrong and calls onPick(index, correct).
export function choices(scope, options, answer, onPick) {
  let picked = false;
  const buttons = options.map((o, i) => h('button', { class: 'choice', onclick: () => pick(i) }, kbd(i + 1), h('span', {}, o)));
  function pick(i) {
    if (picked || i >= options.length) return;
    picked = true;
    buttons.forEach((b, j) => {
      b.disabled = true;
      b.classList.toggle('right', j === answer);
      b.classList.toggle('wrong', j === i && i !== answer);
    });
    onPick(i, i === answer);
  }
  scope.keys({ 1: () => pick(0), 2: () => pick(1), 3: () => pick(2), 4: () => pick(3) });
  return h('div', { class: 'choices' }, buttons);
}

export function nextButton(scope, label, onNext) {
  const b = h('button', { class: 'primary', onclick: onNext }, label, ' ', kbd('Enter'));
  scope.keys({ Enter: onNext });
  return b;
}

export const pct = x => (x == null ? '–' : `${Math.round(x * 100)}%`);
