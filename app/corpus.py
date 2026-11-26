import json, re
from dataclasses import dataclass, field
from pathlib import Path

from pypinyin import Style, pinyin

ROOT = Path(__file__).resolve().parent.parent
HAN = re.compile(r"[一-鿿]")
DIGITS = str.maketrans("0123456789０１２３４５６７８９", "零一二三四五六七八九零一二三四五六七八九")


def han(text):
    return "".join(HAN.findall(text.translate(DIGITS)))


NOT_A_MEANING = re.compile(r"variant of|surname|bound form|used in ", re.I)


def segments(en):
    return [s.strip() for s in en.split(";") if s.strip() and not NOT_A_MEANING.search(s)] or [en.strip()]


def short_gloss(en, limit=48):
    out = ""
    for seg in segments(en):
        if out and len(out) + len(seg) + 2 > limit:
            break
        out = f"{out}; {seg}" if out else seg
    return out


@dataclass
class Corpus:
    words: dict
    sents: list
    gloss: dict
    pseudo: list
    by_id: dict = field(init=False)
    by_word: dict = field(init=False)
    by_level: dict = field(init=False)

    def __post_init__(self):
        self.by_id = {s["id"]: s for s in self.sents}
        self.by_word, self.by_level = {}, {}
        for s in self.sents:
            self.by_level.setdefault(s["lvl"], []).append(s)
            for t in set(s["tok"]):
                if t in self.words:
                    self.by_word.setdefault(t, []).append(s)

    def lookup(self, word):
        if word in self.words:
            w = self.words[word]
            return {"w": word, "num": w["num"], "en": w["en"], "lvl": w["lvl"]}
        g = self.gloss.get(word)
        return {"w": word, "num": g["num"] if g else "", "en": g["en"] if g else "", "lvl": None}

    def meaning_options(self, word, rng):
        target = self.words[word]
        taken = {s.lower() for s in segments(target["en"])}
        pool = [w for w in self.words.values() if w["lvl"] == target["lvl"] and w["w"] != word]
        rng.shuffle(pool)
        options = [short_gloss(target["en"])]
        for w in pool:
            segs = {s.lower() for s in segments(w["en"])}
            if not segs & taken and short_gloss(w["en"]) not in options:
                options.append(short_gloss(w["en"]))
                taken |= segs
            if len(options) == 4:
                break
        rng.shuffle(options)
        return options, options.index(short_gloss(target["en"]))

    def translation_options(self, sent, rng, avoid=()):
        n = len(han(sent["zh"]))
        pool = [s for s in self.by_level.get(sent["lvl"], [])
                if s["id"] != sent["id"] and s["id"] not in avoid and abs(len(han(s["zh"])) - n) <= 4]
        rng.shuffle(pool)
        options = [sent["en"]]
        for s in pool:
            if s["en"].lower() not in {o.lower() for o in options}:
                options.append(s["en"])
            if len(options) == 4:
                break
        rng.shuffle(options)
        return options, options.index(sent["en"])

    def example(self, word, known):
        def cost(s):
            unknown = sum(t not in known and t != word for t in s["tok"])
            return (unknown, s["audio"] is None, abs(len(han(s["zh"])) - 10))
        pool = self.by_word.get(word, [])
        return min(pool, key=cost) if pool else None

    def bundle(self, known, rng, share=0.97, max_sents=None, max_chars=None, focus=None, exclude=()):
        """Greedy bundle at >= `share` known tokens: take a one-unknown-HSK-word sentence whenever the running
        share allows, otherwise a fully known one. `focus` weights words to prefer (today's new and young cards)."""
        focus = focus or {}
        full, one = [], []
        for s in self.sents:
            if s["id"] in exclude:
                continue
            unknown = [t for t in s["tok"] if t not in known]
            if not unknown:
                full.append(s)
            elif len(unknown) == 1 and unknown[0] in self.words:
                one.append(s)
        score = {s["id"]: sum(focus.get(t, 0) for t in set(s["tok"])) + 0.5 * (s["audio"] is not None) + 0.4 * rng.random()
                 for s in full + one}
        full.sort(key=lambda s: -score[s["id"]])
        one.sort(key=lambda s: -score[s["id"]])
        out, tok, unk, chars = [], 0, 0, 0
        while (max_sents is None or len(out) < max_sents) and (max_chars is None or chars < max_chars):
            if one and (tok + len(one[0]["tok"]) - unk - 1) / (tok + len(one[0]["tok"])) >= share:
                s, unk = one.pop(0), unk + 1
            elif full:
                s = full.pop(0)
            else:
                break
            out.append(s)
            tok, chars = tok + len(s["tok"]), chars + len(han(s["zh"]))
        return out


def common_reading(word):
    return " ".join(x[0] for x in pinyin(word, style=Style.TONE3, neutral_tone_with_five=True)).replace("v", "u:")


def repair_forms(words, raw_path):
    """data/words.json keeps each entry's first reading, which is often a surname, variant, or rare reading
    (百 "surname Bai", 都 "Du1", 吗 "ma2", 要 "yao1"). Among the lowercase readings that carry a real meaning,
    take the one pypinyin considers most common, else the first; keep the others as `alt`."""
    if not raw_path.exists():
        return 0
    fixed = 0
    for e in json.load(open(raw_path)):
        w = words.get(e["simplified"])
        if w is None:
            continue
        forms = {}
        for f in e["forms"]:
            t, meanings = f["transcriptions"], [m for m in f["meanings"] if not NOT_A_MEANING.search(m)]
            if meanings and t["numeric"][:1].islower():
                forms.setdefault(t["numeric"], (t["pinyin"], meanings))
        if not forms:
            continue
        num = common_reading(w["w"]) if common_reading(w["w"]) in forms else next(iter(forms))
        py, meanings = forms.pop(num)
        fixed += num != w["num"] or "; ".join(meanings[:3]) != w["en"]
        w.update(num=num, py=py, en="; ".join(meanings[:3]), alt=[{"num": n, "en": "; ".join(m[:2])} for n, (_, m) in forms.items()])
    return fixed


def load(root=ROOT):
    data = root / "data"
    words = {w["w"]: w for w in json.load(open(data / "words.json"))}
    repair_forms(words, data / "raw" / "hsk_complete.json")
    return Corpus(words=words, sents=json.load(open(data / "sentences.json")),
                  gloss=json.load(open(data / "gloss.json")),
                  pseudo=json.load(open(root / "app" / "pseudo_words.json")))
