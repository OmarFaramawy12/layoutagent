# LayoutAgent

A small design-rule checker (DRC) for IC layouts, with a natural-language front end.
(This README is a stub; the full README is planned for the end of the roadmap.)

## Layout file format

```json
{"layers": {"metal1": [[0, 0, 100, 60], [200, 0, 300, 60]], "via1": [[10, 10, 40, 40]]}}
```

Each rect is `[x1, y1, x2, y2]`: lower-left and upper-right corner, as JSON integers in
nanometres, with `x1 < x2`, `y1 < y2` and every value within +/- 1,000,000,000.

### The file-order assumption

Layer IDs and shape IDs are **not stored in the file**. The loader assigns them from the
order of the file:

- Layers get IDs 0, 1, 2, ... in the order they appear in the file (not alphabetical order).
- Shape IDs count 0, 1, 2, ... across the whole file, layer by layer, in list order.

In the example above, `metal1` is layer 0, `via1` is layer 1, the two metal1 rects are
shapes 0 and 1, and the via is shape 2.

Anything that produces or reads shape IDs relies on this: the generator's expected answers
(`tools/gen_layout.py`) and the violations printed by the CLI. If a tool rewrites the file
and reorders the layers, the IDs change. In C++ the loader uses `nlohmann::ordered_json`
to keep file order; the default `nlohmann::json` would sort keys alphabetically. A test
(`ParseLayout.LayerIdsFollowFileOrderNotAlphabeticalOrder`) fails if that ever changes.

JSON itself says the order of keys in an object has no meaning, so this is a convention of
this project and not something the JSON format guarantees. Python's `json` module keeps
file order for dicts, so `tools/gen_layout.py` can rely on it.
