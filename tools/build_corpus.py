"""Build data/words.json and data/sentences.json from the raw downloads in data/raw.

Word:     {w, py, en, lvl (1-4 or 0 if not in HSK 1-4), rank (wordfreq rank, lower = more common)}
Sentence: {id, zh, en, tok [words], lvl (max HSK level of its words, 9 = has a non-HSK-1-4 word), audio bool}
"""
import bz2, csv, gzip, io, json, re, sys, tarfile
from pathlib import Path

import jieba
from wordfreq import top_n_list

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT = RAW.parent
csv.field_size_limit(sys.maxsize)

# ---- HSK 3.0 (2025 revision, "newest-*") levels 1-4 ----
hsk = json.load(open(RAW / "hsk_complete.json"))
words = {}
for e in hsk:
    lv = [int(l.split("-")[1]) for l in e.get("level", []) if l.startswith("newest-")]
    if not lv or min(lv) > 4:
        continue
    f = e["forms"][0]
    words[e["simplified"]] = {"w": e["simplified"], "py": f["transcriptions"]["pinyin"],
                              "num": f["transcriptions"]["numeric"], "en": "; ".join(f["meanings"][:3]), "lvl": min(lv)}

rank = {w: i for i, w in enumerate(top_n_list("zh", 60000))}
for w in words.values():
    w["rank"] = rank.get(w["w"], 99999)

# ---- CC-CEDICT, for glossing non-HSK words ----
cedict, trad_chars, simp_chars = {}, set(), set()
for line in gzip.open(RAW / "cedict.txt.gz", "rt", encoding="utf-8"):
    if line.startswith("#"):
        continue
    m = re.match(r"(\S+) (\S+) \[(.+?)\] /(.+)/", line)
    if not m:
        continue
    tr, m = m.group(1), re.match(r"\S+ (\S+) \[(.+?)\] /(.+)/", line)
    simp_chars.update(m.group(1))
    trad_chars.update(a for a, b in zip(tr, m.group(1)) if a != b)
    if m.group(1) not in cedict:
        cedict[m.group(1)] = {"num": m.group(2), "en": "; ".join(m.group(3).split("/")[:2])}

for w in words:
    jieba.add_word(w, freq=200000)

# ---- Tatoeba: Mandarin sentences, English translations, audio ----
def tsv(fileobj):
    return csv.reader(io.TextIOWrapper(fileobj, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)

cmn = {int(r[0]): r[2] for r in tsv(bz2.open(RAW / "cmn_sentences.tsv.bz2"))}
eng = {int(r[0]): r[2] for r in tsv(bz2.open(RAW / "eng_sentences.tsv.bz2"))}

en_of = {}
with tarfile.open(RAW / "links.tar.bz2") as t:
    for r in tsv(t.extractfile(t.getmember("links.csv"))):
        a, b = int(r[0]), int(r[1])
        if a in cmn and b in eng and a not in en_of:
            en_of[a] = eng[b]

audio = {}
with tarfile.open(RAW / "sentences_with_audio.tar.bz2") as t:
    m = next(x for x in t.getmembers() if x.name.endswith(".csv"))
    for r in tsv(t.extractfile(m)):
        sid = int(r[0])
        if sid in cmn and sid not in audio:
            audio[sid] = int(r[1])  # audio id, served at https://tatoeba.org/audio/download/<id>

HAN = re.compile(r"[一-鿿]")
trad_only = trad_chars - simp_chars
sents = []
for sid, zh in cmn.items():
    if sid not in en_of or any(c in trad_only for c in zh) or not (4 <= len(zh) <= 30):
        continue
    tok = [t for t in jieba.lcut(zh) if HAN.search(t)]
    if not tok:
        continue
    lv = max((words[t]["lvl"] if t in words else 9) for t in tok)
    sents.append({"id": sid, "zh": zh, "en": en_of[sid], "tok": tok, "lvl": lv, "audio": audio.get(sid)})

gloss = {}
for s in sents:
    for t in s["tok"]:
        if t not in words and t not in gloss and t in cedict:
            gloss[t] = cedict[t]

json.dump(list(words.values()), open(OUT / "words.json", "w"), ensure_ascii=False)
json.dump(sents, open(OUT / "sentences.json", "w"), ensure_ascii=False)
json.dump(gloss, open(OUT / "gloss.json", "w"), ensure_ascii=False)

by = lambda k: {i: sum(1 for w in words.values() if w["lvl"] == i) for i in range(1, 5)}
print("HSK words by level:", by(0), "total", len(words))
print("sentences with English:", len(sents), " with native audio:", sum(1 for s in sents if s["audio"]))
print("sentences fully inside HSK 1-4:", sum(1 for s in sents if s["lvl"] <= 4),
      " of those with audio:", sum(1 for s in sents if s["lvl"] <= 4 and s["audio"]))
