# Graph page

The Graph page draws the local HSK character graph around a word, character or component: words coloured by card state, characters as rings, components as squares, typed edges, and a side panel listing every neighbour by link type.

## Sub-features

- `graph-open` `#/graph/<hanzi>?d=1|2` draws `Graph of <hanzi>` (an SVG with role img).
- `graph-search` the `Find a word` searchbox matches hanzi or toneless pinyin, exact syllables first.
- `graph-depth` `1 step` / `2 steps` buttons; 2 steps is capped at 60 nodes, most frequent kept.
- `graph-recenter` clicking a node or a side-panel chip recenters on it.
- `graph-popover` the Listen & read word popup links `Graph →` in a new tab.

## How to get to it (user POV)

- `Graph` in the top nav (`#/graph`, defaults to 学).
- `Graph →` in the Listen & read word popup.

## Driving it with verify.py

Preconditions:

- Any run; card colours need a placement.

- **Run it.** `.venv/bin/python app/e2e.py` runs `graph_journey` (screenshots `29-graph-xue`, `30-graph-qing-2-steps`, `31-graph-dark`).
- **Proof.** The e2e JSON `graph` shows `xue_nodes` (28 on the HSK 3.0 list) and `qing_2step_nodes` between 10 and 60; every `.gnode` has a `.glabel`.

## Gotchas

- Components come from `data/raw/makemeahanzi_dictionary.txt`. Without it the graph has words and characters only.
- The layout is deterministic: the same node and depth always draw the same picture, so screenshots are comparable.
- Light-mode orange and aqua are below 3:1 contrast on white; labels and the side panel carry state in text, which the palette rules require.
