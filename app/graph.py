"""The HSK character graph, shared by the in-app Graph page and the Obsidian export.

Nodes are Chinese spellings: words (HSK 1-4), characters (in those words), and components shared by at least
two characters (from Make Me a Hanzi). Typed edges:
  contains  word -> character
  part      character -> component, with role "sound", "meaning" or "part"
"""
import json, re
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path

from pypinyin import Style, lazy_pinyin

ROOT = Path(__file__).resolve().parent.parent
MMAH = ROOT / "data" / "raw" / "makemeahanzi_dictionary.txt"
IDC = re.compile(r"[⿰-⿿？]")
TONE_MARKS = {"a": "āáǎà", "e": "ēéěè", "i": "īíǐì", "o": "ōóǒò", "u": "ūúǔù", "ü": "ǖǘǚǜ"}


def toned(num):
    """'xue2 sheng5' -> 'xuésheng'."""
    out = []
    for syl in num.replace("u:", "ü").replace("v", "ü").split():
        m = re.fullmatch(r"([a-zü]+)([1-5])", syl.lower())
        if not m or m.group(2) == "5":
            out.append(syl.rstrip("5").lower())
            continue
        s, t = m.group(1), int(m.group(2)) - 1
        v = "a" if "a" in s else "e" if "e" in s else "o" if "ou" in s else next((c for c in reversed(s) if c in TONE_MARKS), None)
        out.append(s.replace(v, TONE_MARKS[v][t], 1) if v else s)
    return "".join(out)


@lru_cache(maxsize=1)
def load_mmah():
    """Make Me a Hanzi by character; empty if the file was not downloaded (the graph then has no components)."""
    if not MMAH.exists():
        return {}
    return {d["character"]: d for d in map(json.loads, MMAH.read_text(encoding="utf-8").splitlines())}


def relations(words, mmah):
    chars = sorted({ch for w in words for ch in w})
    comp_of, sound_of, meaning_of, uses = {}, {}, {}, defaultdict(set)
    for ch in chars:
        d = mmah.get(ch, {})
        comp_of[ch] = sorted(set(IDC.sub("", d.get("decomposition", ""))) - {ch})
        ety = d.get("etymology", {})
        sound_of[ch], meaning_of[ch] = ety.get("phonetic"), ety.get("semantic")
        for x in comp_of[ch]:
            uses[x].add(ch)
    shared = {x for x, s in uses.items() if len(s) >= 2}
    in_words = defaultdict(list)
    for w in sorted(words, key=lambda w: (words[w]["lvl"], words[w]["rank"])):
        if len(w) > 1:
            for ch in dict.fromkeys(w):
                in_words[ch].append(w)
    family = defaultdict(list)
    for ch in chars:
        if sound_of[ch]:
            family[sound_of[ch]].append(ch)
    return {"chars": chars, "comp_of": comp_of, "sound_of": sound_of, "meaning_of": meaning_of, "uses": uses,
            "shared": shared, "noted": set(words) | set(chars) | shared, "in_words": in_words, "family": family}


class Graph:
    """Adjacency over the relations, plus node details. Built once per server; card states are passed per call."""

    def __init__(self, words, mmah):
        self.words, self.mmah = words, mmah
        self.r = r = relations(words, mmah)
        self.adj = defaultdict(dict)  # node -> {neighbour: (type, role)}
        for w in words:
            if len(w) > 1:
                for ch in dict.fromkeys(w):
                    self._edge(w, ch, "contains", None)
        for ch, comps in r["comp_of"].items():
            for x in comps:
                if x in r["noted"]:
                    role = "sound" if x == r["sound_of"][ch] else "meaning" if x == r["meaning_of"][ch] else "part"
                    self._edge(ch, x, "part", role)
        self.toneless = defaultdict(list)
        for w in words:
            self.toneless["".join(lazy_pinyin(w, style=Style.NORMAL))].append(w)

    def _edge(self, a, b, kind, role):
        self.adj[a][b] = (kind, role)
        self.adj[b][a] = (kind, role)

    def kind(self, n):
        return "word" if n in self.words else "character" if n in self.r["comp_of"] else "component"

    def node(self, n, states):
        w, d = self.words.get(n), self.mmah.get(n, {})
        out = {"id": n, "kind": self.kind(n), "is_char": n in self.r["comp_of"],
               "pinyin": toned(w["num"]) if w else ", ".join(d.get("pinyin", [])),
               "meaning": w["en"] if w else d.get("definition", ""), "hsk": w["lvl"] if w else None}
        if w:
            out["state"] = states.get(n, {}).get("state", "new")
        return out

    def local(self, center, states, depth=1, cap=60):
        """Nodes within `depth` steps of center (BFS), the most frequent words kept when over `cap`."""
        if center not in self.r["noted"]:
            raise ValueError(f"{center!r} is not in the HSK 1-4 graph")
        dist, q = {center: 0}, deque([center])
        while q:
            n = q.popleft()
            if dist[n] >= depth:
                continue
            for m in self.adj[n]:
                if m not in dist:
                    dist[m] = dist[n] + 1
                    q.append(m)
        rank = lambda n: (dist[n], self.words[n]["rank"] if n in self.words else 50000, n)
        keep = sorted(dist, key=rank)[:cap]
        kept = set(keep)
        edges = [{"s": a, "t": b, "type": self.adj[a][b][0], "role": self.adj[a][b][1]}
                 for a in keep for b in self.adj[a] if b in kept and a < b]
        nodes = [{**self.node(n, states), "dist": dist[n]} for n in keep]
        return {"center": center, "depth": depth, "nodes": nodes, "edges": edges, "hidden": len(dist) - len(keep),
                "neighbours": self.neighbours(center, states)}

    def neighbours(self, n, states):
        """The center's typed links as lists: the page's table view."""
        r = self.r
        groups = {
            "Characters": [ch for ch in dict.fromkeys(n)] if n in self.words and len(n) > 1 else [],
            "Sound part": [r["sound_of"][n]] if r["sound_of"].get(n) else [],
            "Meaning part": [r["meaning_of"][n]] if r["meaning_of"].get(n) else [],
            "Components": [x for x in r["comp_of"].get(n, []) if x not in (r["sound_of"].get(n), r["meaning_of"].get(n))],
            "Same sound part": [x for x in r["family"].get(r["sound_of"].get(n), []) if x != n],
            "In words": r["in_words"].get(n, []),
            "Component of": sorted(r["uses"].get(n, [])) if n in r["shared"] else [],
        }
        return [{"label": k, "items": [self.node(x, states) for x in v if x in r["noted"]]} for k, v in groups.items() if v]

    def search(self, q, limit=12):
        q = q.strip()
        if not q:
            return []
        if re.search(r"[⺀-鿿]", q):
            hits = [n for n in self.r["noted"] if n == q] + sorted(
                (n for n in self.words if q in n and n != q), key=lambda w: (len(w), self.words[w]["rank"]))
        else:
            key = re.sub(r"[^a-z]", "", q.lower())
            # exact syllables first (qing -> 请 情 清 ...), then longer words starting with them (情况)
            hits = sorted(((k != key, self.words[w]["rank"], w) for k, ws in self.toneless.items() if k.startswith(key) for w in ws))
            hits = [w for _, _, w in hits]
        return hits[:limit]
