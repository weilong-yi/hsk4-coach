"""Export HSK 1-4 into an Obsidian vault as linked notes. study.db stays the source of truth; the vault mirrors it.

One note per Chinese spelling (a word, a character, or a shared component; 学 is both a word and a character).
Typed links live in properties (characters, components, meaning, sound, sound_family, in_words) and are repeated
as wikilinks in the body so backlinks and the graph see them either way. Everything under "## My notes" is the
learner's and is never overwritten. A file is rewritten only when its generated part changed.

    .venv/bin/python -m app.obsidian            # vault and folder from app/config.json "obsidian"
    .venv/bin/python -m app.obsidian --vault-path /path/to/vault --db data/study.db
"""
import argparse, json, re, sqlite3, unicodedata
from collections import defaultdict
from pathlib import Path

from .corpus import load

ROOT = Path(__file__).resolve().parent.parent
MMAH = ROOT / "data" / "raw" / "makemeahanzi_dictionary.txt"
MY_NOTES = "## My notes"
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


def link(x):
    return f"[[{x}]]"


def card_states(db_path):
    con = sqlite3.connect(db_path)
    known = {w for (w,) in con.execute("SELECT word FROM known")}
    out = {w: {"state": "known"} for w in known}
    for w, fj, intro in con.execute("SELECT word, fsrs_json, introduced_at FROM cards"):
        if intro is None:
            out[w] = {"state": "new"}
            continue
        f = json.loads(fj)
        out[w] = {"state": {1: "learning", 2: "review", 3: "relearning"}.get(f["state"], "learning"),
                  "due": (f.get("due") or "")[:10], "stability_days": None if f.get("stability") is None else round(f["stability"], 1)}
    return out


def build_notes(c, states, mmah):
    """name -> {"props": dict, "body": str}. Pure: same inputs give byte-identical notes."""
    words = c.words
    chars = sorted({ch for w in words for ch in w})
    comp_of, sound_of, meaning_of, uses = {}, {}, {}, defaultdict(set)
    for ch in chars:
        d = mmah.get(ch, {})
        comps = sorted(set(IDC.sub("", d.get("decomposition", ""))) - {ch})
        comp_of[ch] = comps
        ety = d.get("etymology", {})
        sound_of[ch], meaning_of[ch] = ety.get("phonetic"), ety.get("semantic")
        for x in comps:
            uses[x].add(ch)
    shared = {x for x, s in uses.items() if len(s) >= 2}  # components worth a note of their own
    noted = set(words) | set(chars) | shared
    in_words = defaultdict(list)
    for w in sorted(words, key=lambda w: (words[w]["lvl"], words[w]["rank"])):
        if len(w) > 1:
            for ch in dict.fromkeys(w):
                in_words[ch].append(w)
    family = defaultdict(list)
    for ch in chars:
        if sound_of[ch]:
            family[sound_of[ch]].append(ch)
    known = {w for w, s in states.items() if s["state"] == "known"}

    notes = {}
    for name in sorted(noted):
        w, is_char = words.get(name), name in comp_of
        roles = [r for r, ok in (("word", w), ("character", is_char), ("component", name in shared)) if ok]
        d = mmah.get(name, {})
        p = {"pinyin": toned(w["num"]) if w else ", ".join(d.get("pinyin", [])),
             "meaning": w["en"] if w else d.get("definition", ""), "hsk": w["lvl"] if w else None, "roles": roles}
        sections = []
        if w and len(name) > 1:
            p["characters"] = [link(ch) for ch in dict.fromkeys(name)]
            sections.append("Characters: " + " · ".join(p["characters"]))
        if is_char:
            p["components"] = [link(x) if x in noted else x for x in comp_of[name]]
            if meaning_of[name]:
                p["meaning_part"] = link(meaning_of[name]) if meaning_of[name] in noted else meaning_of[name]
            if sound_of[name]:
                p["sound_part"] = link(sound_of[name]) if sound_of[name] in noted else sound_of[name]
                p["sound_family"] = [link(x) for x in family[sound_of[name]] if x != name]
            if p["components"]:
                sections.append("Components: " + " · ".join(p["components"]))
            if p.get("sound_part"):
                sections.append(f"Sounds like {p['sound_part']} · meaning from {p.get('meaning_part', '?')}"
                                + (" · same sound part: " + " · ".join(p["sound_family"]) if p["sound_family"] else ""))
            if d.get("etymology", {}).get("hint"):
                sections.append(f"Hint: {d['etymology']['hint']}")
        if in_words.get(name):
            p["in_words"] = [link(x) for x in in_words[name]]
            sections.append("In words: " + " · ".join(p["in_words"]))
        if name in shared and not is_char:
            p["used_in"] = [link(x) for x in sorted(uses[name])]
            sections.append("Component of: " + " · ".join(p["used_in"]))
        if w:
            st = states.get(name, {"state": "unseen"})
            p.update(st)
            if st["state"] != "known":
                p["known_neighbors"] = len({k for ch in name for k in in_words.get(ch, []) + ([ch] if ch in words else [])} & known)
        kind_tag = f"hsk/{w['lvl']}" if w else "hsk/character" if is_char else "hsk/component"
        p["tags"] = [kind_tag] + ([f"state/{p['state']}"] if w else [])
        ex = sorted((s for s in c.by_word.get(name, []) if s["lvl"] <= 4),
                    key=lambda s: (s["audio"] is None, abs(len(s["zh"]) - 10), s["id"]))[:3] if w else []
        body = [f"# {name}", f"**{p['pinyin']}** {p['meaning']}" + (f" · HSK {w['lvl']}" if w else ""), ""]
        body += [f"- {s}" for s in sections]
        if ex:
            body += ["", "## Examples"] + [f"> {s['zh']}  \n> {s['en']}\n" for s in ex]
        notes[name] = {"props": {k: v for k, v in p.items() if v not in (None, [], "")}, "body": "\n".join(body).rstrip() + "\n"}
    return notes


def yaml_value(v):
    if isinstance(v, list):
        return "\n" + "".join(f"  - {yaml_value(x).strip()}\n" for x in v).rstrip("\n")
    if isinstance(v, (int, float)):
        return f" {v}"
    return " " + json.dumps(str(v), ensure_ascii=False)  # quoted: required for [[links]], safe for colons


def render(note, my_notes):
    fm = "\n".join(f"{k}:{yaml_value(v)}" for k, v in note["props"].items())
    return f"---\n{fm}\n---\n{note['body']}\n{MY_NOTES}\n{my_notes}"


def file_name(name):
    return unicodedata.normalize("NFC", name).replace("/", "／") + ".md"


def write_vault(notes, folder):
    folder.mkdir(parents=True, exist_ok=True)
    changed = 0
    for name, note in notes.items():
        path = folder / file_name(name)
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        mine = old.split(f"\n{MY_NOTES}\n", 1)[1] if f"\n{MY_NOTES}\n" in old else "\n"
        new = render(note, mine)
        if new != old:
            path.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def write_base(folder, base_name="HSK words.base"):
    """A Bases view of unknown words, grouped by how many known words share a character (most first)."""
    rel = folder.name
    text = f"""filters:
  and:
    - file.inFolder("{rel}")
views:
  - type: table
    name: "Next words through characters I know"
    filters:
      or:
        - file.hasTag("state/new")
        - file.hasTag("state/learning")
        - file.hasTag("state/review")
        - file.hasTag("state/relearning")
    groupBy:
      property: note.known_neighbors
      direction: DESC
    order:
      - file.name
      - pinyin
      - meaning
      - hsk
      - state
      - known_neighbors
  - type: table
    name: "Learning now"
    filters:
      or:
        - file.hasTag("state/learning")
        - file.hasTag("state/review")
        - file.hasTag("state/relearning")
    order:
      - file.name
      - pinyin
      - meaning
      - state
      - due
"""
    path = folder / base_name
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def vault_path(vault_name):
    reg = Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    for v in json.loads(reg.read_text())["vaults"].values():
        if Path(v["path"]).name == vault_name:
            return Path(v["path"])
    raise SystemExit(f"no Obsidian vault named {vault_name!r} in {reg}")


def export(db_path, vault, folder_name, c=None):
    mmah = {d["character"]: d for d in map(json.loads, MMAH.read_text(encoding="utf-8").splitlines())}
    notes = build_notes(c or load(), card_states(db_path), mmah)
    folder = vault / folder_name
    changed = write_vault(notes, folder)
    write_base(folder)
    return {"notes": len(notes), "changed": changed, "folder": str(folder)}


def main():
    cfg = json.loads((ROOT / "app" / "config.json").read_text())["obsidian"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "study.db"))
    ap.add_argument("--vault-path")
    a = ap.parse_args()
    print(json.dumps(export(a.db, Path(a.vault_path) if a.vault_path else vault_path(cfg["vault"]), cfg["folder"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
