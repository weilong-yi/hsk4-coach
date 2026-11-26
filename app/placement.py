"""Placement: build the test items, then turn the logged answers into a profile and the starting known/cards sets.

Everything after `build` is a function of the session's events, so a profile can be recomputed from the log.
"""
from collections import Counter

from . import db
from .corpus import han
from .study import new_card

VOCAB_PER_LEVEL, PSEUDO_N = 20, 15
LISTEN_PER_LEVEL = {1: 2, 2: 3, 3: 3, 4: 2}
TONE_N = 12
FULL_LEVEL = 0.9
READ_CHARS = 150


def tones(num):
    return [int(s[-1]) if s[-1].isdigit() else 5 for s in num.split()]


def build(c, rng):
    vocab = []
    for lvl in (1, 2, 3, 4):
        ws = sorted((w for w in c.words.values() if w["lvl"] == lvl), key=lambda w: w["rank"])
        for i in range(VOCAB_PER_LEVEL):
            w = rng.choice(ws[i * len(ws) // VOCAB_PER_LEVEL:(i + 1) * len(ws) // VOCAB_PER_LEVEL])
            options, answer = c.meaning_options(w["w"], rng)
            vocab.append({"w": w["w"], "lvl": lvl, "pseudo": False, "options": options, "answer": answer})
    vocab += [{"w": p, "lvl": 0, "pseudo": True} for p in rng.sample(c.pseudo, PSEUDO_N)]
    rng.shuffle(vocab)

    listen = []
    for lvl, n in LISTEN_PER_LEVEL.items():
        pool = [s for s in c.by_level[lvl] if 5 <= len(han(s["zh"])) <= 16]
        native = [s for s in pool if s["audio"]]
        for s in rng.sample(native if len(native) >= n else pool, n):
            options, answer = c.translation_options(s, rng)
            listen.append({"id": s["id"], "zh": s["zh"], "lvl": lvl, "audio": s["audio"], "options": options, "answer": answer})

    combos = [(a, b) for a in (1, 2, 3, 4) for b in (1, 2, 3, 4) if (a, b) != (3, 3)]
    rng.shuffle(combos)
    tone = []
    for combo in combos[:TONE_N]:
        pool = [w for w in c.words.values() if len(w["w"]) == 2 and tuple(tones(w["num"])) == combo
                and not set(w["w"]) & set("一不") and w["rank"] < 10000]
        if pool:
            w = rng.choice(pool)
            tone.append({"w": w["w"], "num": w["num"], "tones": list(combo)})
    return {"vocab": vocab, "listen": listen, "tone": tone}


def vocab_estimate(c, evs):
    answers = [e for e in evs if e["activity"] == "placement_vocab" and e["result"].get("phase") == "yesno"]
    pseudo = [e for e in answers if e["item"] not in c.words]
    fa = sum(e["result"]["claimed"] for e in pseudo) / len(pseudo) if pseudo else 0.0
    levels = {}
    for lvl in (1, 2, 3, 4):
        es = [e for e in answers if e["item"] in c.words and c.words[e["item"]]["lvl"] == lvl]
        hit = sum(e["result"]["claimed"] for e in es) / len(es) if es else 0.0
        levels[lvl] = {"n": len(es), "hit": round(hit, 3), "corrected": round(max(0.0, hit - fa), 3)}
    spot = [e for e in evs if e["activity"] == "placement_vocab" and e["result"].get("phase") == "spot"]
    return {
        "levels": levels,
        "false_alarm": {"n": len(pseudo), "claimed": sum(e["result"]["claimed"] for e in pseudo), "rate": round(fa, 3)},
        "said_no": sorted(e["item"] for e in answers if e["item"] in c.words and not e["result"]["claimed"]),
        "spot": {"n": len(spot), "correct": sum(e["result"]["correct"] for e in spot),
                 "missed": sorted(e["item"] for e in spot if not e["result"]["correct"])},
    }


def known_words(c, est):
    """{word: source}. Levels at >= FULL_LEVEL are fully known; partial levels keep their most frequent share.
    Direct evidence wins: words answered "no" and missed spot checks stay unknown."""
    out = {}
    for lvl, score in est["levels"].items():
        ws = sorted((w["w"] for w in c.words.values() if w["lvl"] == lvl), key=lambda w: c.words[w]["rank"])
        full = score["corrected"] >= FULL_LEVEL
        for w in ws if full else ws[:round(score["corrected"] * len(ws))]:
            out[w] = f"placement:{'level' if full else 'freq'}{lvl}"
    for w in est["said_no"] + est["spot"]["missed"]:
        out.pop(w, None)
    return out


def reading(c, known, rng, avoid=()):
    sents = c.bundle(known, rng, max_chars=READ_CHARS, exclude=set(avoid))
    if not sents:
        sents, chars = [], 0
        for s in sorted(c.by_level[1], key=lambda s: sum(t not in known for t in s["tok"]) / len(s["tok"])):
            if chars >= READ_CHARS:
                break
            sents.append(s)
            chars += len(han(s["zh"]))
    ids = {s["id"] for s in sents}
    questions = []
    for s in rng.sample(sorted(sents, key=lambda s: -len(s["zh"]))[:6], min(3, len(sents))):
        options, answer = c.translation_options(s, rng, avoid=ids)
        questions.append({"id": s["id"], "options": options, "answer": answer})
    return {"sentences": [{"id": s["id"], "zh": s["zh"]} for s in sents],
            "chars": sum(len(han(s["zh"])) for s in sents), "questions": questions}


def summarize(c, evs):
    est = vocab_estimate(c, evs)
    listen = [e for e in evs if e["activity"] == "placement_listen"]
    by_lvl = {}
    for e in listen:
        b = by_lvl.setdefault(str(e["result"]["lvl"]), [0, 0])
        b[0] += e["result"]["correct"]
        b[1] += 1
    sylls = [(exp, ans) for e in evs if e["activity"] == "placement_tone"
             for exp, ans in zip(tones(c.words[e["item"]]["num"]), e["result"]["answer"])]
    confusion = Counter(f"{exp}>{ans}" for exp, ans in sylls)
    timed = [e for e in evs if e["activity"] == "placement_read" and e["result"].get("phase") == "timed"]
    qs = [e for e in evs if e["activity"] == "placement_read" and e["result"].get("phase") == "question"]
    return {
        **est,
        "listen": {"n": len(listen), "correct": sum(e["result"]["correct"] for e in listen), "by_level": by_lvl},
        "tone": {"n": len(sylls), "correct": sum(a == b for a, b in sylls),
                 "by_tone": {str(t): [sum(a == b for a, b in sylls if a == t), sum(a == t for a, _ in sylls)] for t in (1, 2, 3, 4)},
                 "confusion": dict(confusion)},
        "read": {"chars": timed[-1]["result"]["chars"] if timed else 0, "cpm": timed[-1]["result"]["cpm"] if timed else None,
                 "n_questions": len(qs), "correct": sum(e["result"]["correct"] for e in qs)},
    }


def finish(con, c, session_id):
    evs = db.events(con, session_id)
    profile = summarize(c, evs)
    known = known_words(c, profile)
    introduced = {r[0] for r in con.execute("SELECT word FROM cards WHERE introduced_at IS NOT NULL")}
    with con:
        con.execute("DELETE FROM known WHERE source LIKE 'placement%'")
        con.executemany("INSERT OR REPLACE INTO known(word, source) VALUES (?,?)",
                        [(w, src) for w, src in known.items() if w not in introduced])
        con.executemany("DELETE FROM cards WHERE word=? AND introduced_at IS NULL", [(w,) for w in known])
        have = {r[0] for r in con.execute("SELECT word FROM cards UNION SELECT word FROM known")}
        con.executemany("INSERT INTO cards(word, fsrs_json, introduced_at) VALUES (?,?,NULL)",
                        [(w, new_card(w).to_json()) for w in c.words if w not in have])
        profile.update(session_id=session_id, date=db.now().isoformat(timespec="seconds"),
                       known_count=con.execute("SELECT COUNT(*) FROM known").fetchone()[0],
                       queued_count=con.execute("SELECT COUNT(*) FROM cards WHERE introduced_at IS NULL").fetchone()[0])
        db.set_profile(con, "placement", profile)
    return profile
