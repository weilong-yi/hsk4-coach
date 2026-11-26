import { h } from './ui.js';

const MARKS = { a: 'āáǎà', e: 'ēéěè', i: 'īíǐì', o: 'ōóǒò', u: 'ūúǔù', ü: 'ǖǘǚǜ' };

// "hao3" -> {text: "hǎo", tone: 3}; numeric CC-CEDICT syllables, with u: for ü.
export function syllable(s) {
  const m = s.match(/^([A-Za-zü:]+?)([1-5])?$/);
  if (!m) return { text: s, tone: 0 };
  const base = m[1].replace(/u:|v/g, 'ü').replace(/U:|V/g, 'Ü');
  const tone = Number(m[2] || 5);
  if (tone === 5) return { text: base, tone };
  const low = base.toLowerCase();
  let i = low.indexOf('a');
  if (i < 0) i = low.indexOf('e');
  if (i < 0) i = low.indexOf('ou');
  if (i < 0) for (let j = low.length - 1; j >= 0; j--) if ('aeiouü'.includes(low[j])) { i = j; break; }
  if (i < 0) return { text: base, tone };
  const mark = MARKS[low[i]][tone - 1];
  return { text: base.slice(0, i) + (base[i] === low[i] ? mark : mark.toUpperCase()) + base.slice(i + 1), tone };
}

export function pinyin(num, cls = 'py') {
  return h('span', { class: cls }, (num || '').split(/\s+/).filter(Boolean).flatMap((s, i) => {
    const { text, tone } = syllable(s);
    return [i ? ' ' : '', h('span', { class: `t${tone}` }, text)];
  }));
}
