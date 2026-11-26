"""Write app/pseudo_words.json: two-character non-words built from productive HSK 1-3 morphemes.

A candidate is kept only if it is absent from CC-CEDICT (simplified and traditional headwords) and from
wordfreq's Chinese word list. Characters come from HSK 1-3 two-character words, appear in at least three
HSK words, and are not single-character words themselves, so each pseudo-word reads like a plausible compound.
"""
import gzip, json, random
from collections import Counter
from pathlib import Path

from wordfreq import top_n_list

ROOT = Path(__file__).resolve().parent.parent
POOL = 80


def cedict_headwords():
    heads = set()
    for line in gzip.open(ROOT / "data/raw/cedict.txt.gz", "rt", encoding="utf-8"):
        if not line.startswith("#"):
            heads.update(line.split(" ", 2)[:2])
    return heads


def build():
    words = json.load(open(ROOT / "data/words.json"))
    single = {w["w"] for w in words if len(w["w"]) == 1}
    uses = Counter(ch for w in words if len(w["w"]) > 1 for ch in w["w"])
    two = [w["w"] for w in words if len(w["w"]) == 2 and w["lvl"] <= 3]
    ok = lambda ch: ch not in single and uses[ch] >= 3
    first = sorted({x[0] for x in two if ok(x[0])})
    second = sorted({x[1] for x in two if ok(x[1])})
    heads, wf = cedict_headwords(), set(top_n_list("zh", 1_000_000))
    rng, out = random.Random(7), []
    while len(out) < POOL:
        x = rng.choice(first) + rng.choice(second)
        if x[0] != x[1] and x not in heads and x not in wf and x not in out and not any(x in w for w in single):
            out.append(x)
    assert not set(out) & heads
    return out


if __name__ == "__main__":
    pool = build()
    (ROOT / "app/pseudo_words.json").write_text(json.dumps(pool, ensure_ascii=False))
    print(len(pool), " ".join(pool))
