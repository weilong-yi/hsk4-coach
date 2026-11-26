"""Experiment E3: can the corpus feed reading bundles at 95-98% known words, and introduce every new word in context?

For simulated learner profiles, count
  known sentences  (every word known)
  new-word sentences (exactly one unknown word, and it is an HSK 1-4 word: the teachable case)
  word reach       (share of the profile's unknown HSK 1-4 words that appear as the single unknown in >=1 sentence)
and build a 200-token bundle (known sentences + new-word sentences) to report its actual known-token share.
"""
import json, random
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "data"
W = {w["w"]: w for w in json.load(open(D / "words.json"))}
S = json.load(open(D / "sentences.json"))
random.seed(0)

def profile(levels_known, frac_next=0.0):
    known = {w for w, x in W.items() if x["lvl"] in levels_known}
    nxt = sorted((w for w, x in W.items() if x["lvl"] == max(levels_known) + 1), key=lambda w: W[w]["rank"])
    known |= set(nxt[: int(len(nxt) * frac_next)])  # learners pick up the most frequent words first
    return known

def bundle(known, target_tokens=200, known_share=0.97):
    """Greedy: take a new-word sentence whenever the bundle stays at or above known_share, else a known one."""
    full = [s for s in S if all(t in known for t in s["tok"])]
    one = [s for s in S if sum(t not in known for t in s["tok"]) == 1 and all(t in known or t in W for t in s["tok"])]
    random.shuffle(full); random.shuffle(one)
    out, tok, unk = [], 0, 0
    while tok < target_tokens and (full or one):
        if one and (tok + len(one[-1]["tok"]) - unk - 1) / (tok + len(one[-1]["tok"])) >= known_share:
            s = one.pop(); unk += 1
        elif full:
            s = full.pop()
        else:
            break
        out.append(s); tok += len(s["tok"])
    return full, one, out, tok, unk

rows = []
for name, lv, frac in [("HSK1 done", {1}, 0), ("HSK1-2 done", {1, 2}, 0), ("HSK1-2 + half of 3", {1, 2}, .5),
                       ("HSK1-3 done", {1, 2, 3}, 0), ("HSK1-3 + half of 4", {1, 2, 3}, .5)]:
    known = profile(lv, frac)
    full = [s for s in S if all(t in known for t in s["tok"])]
    one = [s for s in S if sum(t not in known for t in s["tok"]) == 1 and all(t in known or t in W for t in s["tok"])]
    targets = {w for w in W if w not in known}
    reached = {next(t for t in s["tok"] if t not in known) for s in one}
    _, _, b, tok, unk = bundle(known)
    rows.append((name, len(known), len(full), sum(1 for s in full if s["audio"]), len(one),
                 f"{len(reached & targets)}/{len(targets)} ({100*len(reached & targets)/max(1,len(targets)):.0f}%)",
                 f"{len(b)} sents, {tok} tok, {100*(tok-unk)/max(1,tok):.1f}% known, {unk} new"))

hdr = ("profile", "known words", "known sents", "…with audio", "new-word sents", "unknown HSK words reachable", "200-token bundle")
print(" | ".join(hdr)); print(" | ".join("---" for _ in hdr))
for r in rows: print(" | ".join(map(str, r)))
