# LayoutAgent

[![CI](https://github.com/OmarFaramawy12/layoutagent/actions/workflows/ci.yml/badge.svg)](https://github.com/OmarFaramawy12/layoutagent/actions/workflows/ci.yml)

A small design-rule checker (DRC) for IC layouts, with a natural-language front end.

- A **C++20 engine** stores axis-aligned rectangles on layers and finds rule violations
  (minimum width, minimum spacing, cross-layer overlap, window query) using exact integer
  geometry.
- A **Python layer** lets an LLM call the engine through tool calling. The LLM only picks which
  check to run and explains the result. **All geometry happens in C++**, so the numbers in an
  answer come from the engine and not from the model.

```
 "Which shapes are narrower than 50 nm?"
            |
            v
   python -m agent  ──►  LLM (any OpenAI-compatible API)
            |                 |
            |   tool call:    |  check_min_width {"min_width": 50}
            |  ◄──────────────┘
            v
   layoutagent (C++ CLI)  ──►  violations as JSON
            |
            v
   the LLM reads the JSON and explains it in plain language
```

## Quick start

Needs CMake 3.20+, Ninja, a C++20 compiler (developed with GCC 13 on WSL Ubuntu) and Python 3
(standard library only, no pip packages). CMake downloads GoogleTest on the first configure.

```
cmake -S . -B build -G Ninja
ninja -C build
ctest --test-dir build --output-on-failure
```

Try the engine on a generated layout:

```
python3 tools/gen_layout.py --seed 5 --count 200 --out /tmp/demo
build/layoutagent /tmp/demo.json --min-width 50 --min-spacing 40 --overlap metal1 via1
```

## The command-line program

```
layoutagent <layout.json> ([--min-width W] [--min-spacing S] [--overlap LAYER_A LAYER_B]... |
                           --window LAYER X1 Y1 X2 Y2)
```

The checks can be combined. `--window` is a separate query and cannot be combined with them.
For a tiny layout `{"layers": {"metal1": [[0, 0, 100, 30], [120, 0, 220, 100]], "via1": [[10, 10, 60, 60]]}}`
the command `--min-width 50 --min-spacing 40 --overlap metal1 via1` prints, on stdout:

```json
{"violations": [
  {"type": "min_width",   "layer_a": "metal1", "layer_b": "metal1", "first_shape_id": 0,
   "second_shape_id": null, "measured": 30,   "required": 50},
  {"type": "min_spacing", "layer_a": "metal1", "layer_b": "metal1", "first_shape_id": 0,
   "second_shape_id": 1,    "measured": 400,  "required": 1600},
  {"type": "overlap",     "layer_a": "metal1", "layer_b": "via1",   "first_shape_id": 0,
   "second_shape_id": 2,    "measured": 1000, "required": 0}
]}
```

(The real output is pretty-printed; it is shortened here.) What `measured` and `required` mean
depends on the type:

| type | measured | required |
|---|---|---|
| `min_width` | the shape's smaller side, in nm | the rule W |
| `min_spacing` | the **squared** distance, in nm² | S² |
| `overlap` | the overlap **area**, in nm² | 0 |

`--window` prints `{"shape_ids": [...]}`: the shapes on that layer that share area with the window.

Streams and exit codes: results go to **stdout**, errors to **stderr** as `error: ...`.
`0` means the checks ran (with or without violations), `1` a runtime error (bad file, unknown
layer), `2` a usage error (bad command line).

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

## Geometry and rules

Everything is exact integer arithmetic; there is no floating point and no `sqrt`.

- Coordinates are signed `std::int64_t` in database units (1 unit = 1 nm), y grows upward.
  Every coordinate satisfies `|value| <= 1,000,000,000`, enforced in the `Rect` constructor, so
  `dx*dx + dy*dy` cannot overflow `int64_t`. Rule values must be in `(0, 2,000,000,000]` so
  `S*S` fits too.
- A `Rect` is valid only if `x1 < x2` and `y1 < y2`; zero-width shapes are rejected.
- The gap of two intervals is `max(a1, b1) - min(a2, b2)`: negative means overlap, zero means
  touching, positive is the empty space between them.
- **Spacing:** the distance between two rectangles is Euclidean, with `dx = max(0, gap_x)` and
  `dy = max(0, gap_y)`. Two shapes on the same layer violate the rule if and only if
  `dx² + dy² < S²`. A distance exactly equal to S is allowed. Touching or overlapping shapes
  have distance 0, so they are violations.
- **Width:** a shape violates the rule if `min(width, height) < W`; a side exactly equal to W is
  allowed.
- **Overlap:** two shapes on different layers overlap only if they share positive area
  (`gap_x < 0` and `gap_y < 0`); touching along an edge or at a corner does not count.
- Width and spacing only compare shapes on the **same layer**.

## Spatial grid for the spacing check

The naive spacing check compares every pair of shapes: O(n²). `check_spacing_grid` puts the
shapes in a grid of square cells and only compares shapes in neighbouring cells. A pair closer
than S must have a gap below S on both axes, so each shape's search box (the shape grown by S on
every side) always touches the cells of every shape that could violate the rule.

The grid returns **exactly the same violations in exactly the same order** as the naive check,
which is kept as the reference. `tests/test_spacing_grid.cpp` compares the two field by field
on hand-made edge cases (touching shapes, a distance exactly equal to S, negative coordinates,
coordinates at the ±1e9 limits, one giant shape among small ones) and on 30 random layouts.
The CLI uses the grid.

Benchmark (`app/benchmark.cpp`, Release build, best of 3 runs, about one shape per
1000 x 1000 nm at every size so only the algorithm changes the timing):

| shapes | violations | naive ms | grid ms | speedup |
|---:|---:|---:|---:|---:|
| 1,000 | 21 | 1.03 | 0.70 | 1.5x |
| 2,000 | 30 | 4.15 | 1.43 | 2.9x |
| 5,000 | 90 | 23.86 | 3.93 | 6.1x |
| 10,000 | 161 | 95.80 | 9.39 | 10.2x |
| 20,000 | 349 | 383.72 | 19.45 | 19.7x |
| 40,000 | 705 | 1552.78 | 46.89 | 33.1x |

Each doubling of the size makes the naive check about 4x slower and the grid about 2x slower.
To reproduce (never benchmark a Debug build; the program warns if it is one):

```
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release
ninja -C build-release benchmark && ./build-release/benchmark
```

## Natural-language front end

`python -m agent` lets you ask questions about a layout in plain language. The model never sees
coordinates and never does arithmetic: it chooses one of four tools, `agent/tools.py` runs the
C++ program, and the model explains the JSON it gets back.

| tool | runs |
|---|---|
| `check_min_width` | `--min-width W` |
| `check_min_spacing` | `--min-spacing S` |
| `check_overlap` | `--overlap LAYER_A LAYER_B` |
| `window_query` | `--window LAYER X1 Y1 X2 Y2` |

Setup: any chat API that follows the OpenAI "chat completions" format works (NVIDIA NIM, Groq,
OpenRouter, ...). Put three variables in a file named `.env` (it is in `.gitignore`; never commit
a key) and load it with `source .env`:

```
export LLM_BASE_URL=https://integrate.api.nvidia.com/v1
export LLM_MODEL=<a model that supports tool calling>
export LLM_API_KEY=<your key>
```

```
$ python -m agent /tmp/demo.json "Which shapes are narrower than 50 nm?" --show-calls
tool call: check_min_width {"min_width": 50}
The following shape IDs are narrower than the 50 nm minimum width:
- metal1: 19, 39, 46, 57, 106
- via1: 111, 121, 141, 161, 181, 199, 205
- metal2: 217, 239, 245, 264, 265, 285
```

Design choices that keep the model honest and the program safe:

- The C++ program is started with an argument list, never through a shell, with a timeout.
  Layer names are checked against the layout and numbers are validated before the program runs.
- A tool mistake by the model (a wrong argument, an unknown layer) is returned to it as an
  `Error: ...` message so it can fix the call and retry. Host problems (the program is missing)
  stop the run instead.
- Long results are capped (50 violations, 200 shape IDs), but `total_count` is always the real
  count, and the system prompt tells the model to report `total_count`.
- The system prompt states the units (nm) and that spacing values are squared. The loop stops
  after 8 steps so a model that keeps calling tools cannot run forever. Temperature is 0.
- If a question lacks a number (such as "check the minimum width"), the model is told to ask
  instead of inventing one.
- The loop only needs an object with `chat(messages, tools)`, so the tests use a scripted fake
  model and a small local fake HTTP server; no network or API key is needed to run them.

### Evaluation

`python -m eval.run_eval` runs 9 questions from `eval/cases.json` against the real model on a
fixed generated layout and prints a table (`--only ID ...` runs a subset). Scoring is
deterministic, with no second LLM as a judge:

- **tool check:** did the model call the expected tool with the expected arguments, and did that
  call succeed? (The two layers of an overlap check may come in either order.)
- **answer check:** does the answer state the correct count, or list every shape ID the engine
  returned? The correct values come from running the C++ engine, not from the model.
- A case passes if the run finished and both checks pass. A "which shapes ...?" question is
  naturally answered with a list, which is why listing the IDs is accepted.

The cases cover width, spacing, overlap (including reversed layer names and an overlap with no
violations), a window query, and a question with a missing number where the correct behaviour
is to ask. Tests check that no expected count or ID equals a number that appears in its own
question, because the scoring would otherwise match it by accident.

Result with `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` on NVIDIA NIM: the model chose the
right tool with the right arguments in all 9 cases, about 4,000 tokens per case. The first full
run showed 2 answer failures; both were a flaw in my scoring (it demanded the count from
"which shapes" answers, while the model had listed exactly the right IDs), not a mistake of the
model. After fixing the scoring, all 9 cases pass. The scoring weakness that remains is
documented in `eval/scoring.py`: numbers are looked up anywhere in the text.

## How it is tested

- **GoogleTest** unit tests for every C++ piece: `Rect`, geometry helpers, `Layout`, each check,
  the JSON loader and writer, and the grid.
- **Generator with planted violations:** `tools/gen_layout.py` builds seeded random layouts on a
  grid of slots, one pattern per slot, so the violations are known **by construction** and the
  generator contains no geometry checker of its own. Decoys sit exactly on the rule limits and
  must not be reported. It writes the layout and an expected-answer file.
- **End-to-end test** (`tests/test_cli_e2e.py`): runs the real CLI on generated layouts across
  many seeds and compares its output with the expected answers as sorted lists, so duplicate
  reports are caught.
- **Naive-vs-grid equivalence tests** (see above).
- **Python unit tests** (`unittest`) for the generator, the tool layer, the LLM client (against
  a local fake server, including retries and errors), the agent loop and the evaluation scoring.
- **Sanitizers:** AddressSanitizer and UndefinedBehaviorSanitizer, which matters because the
  geometry depends on `int64_t` arithmetic never overflowing. The whole suite, including the
  Python tests that run the CLI, passes under them:

  ```
  cmake -S . -B build-asan -G Ninja -DCMAKE_BUILD_TYPE=Debug -DLAYOUTAGENT_SANITIZE=ON
  ninja -C build-asan && ctest --test-dir build-asan --output-on-failure
  ```

- **clang-tidy:** `ninja -C build tidy` checks `src/` and `app/` with the rules in `.clang-tidy`
  (bug-finding and performance checks plus a few that guard the conventions above); any finding
  is an error.
- **CI** (`.github/workflows/ci.yml`, GitHub Actions on Ubuntu 24.04): every push to `main` and
  every pull request runs the full suite in a Debug and a Release build, again under the
  sanitizers, and clang-tidy (version 15, pinned). The Python tests need no network or API key.

## Limitations

- Only axis-aligned rectangles. No polygons, no rotation, no hierarchy.
- A layout file with the same layer name twice is not rejected: the JSON library silently keeps
  one of them. Detecting it would need a streaming parser.
- The grid's cell size is the larger of S and the largest shape side, so a single huge shape
  makes the cells huge and the check slow (still correct). Layouts with bounded shape sizes,
  like the generated ones, do not have this problem.
- The agent answers one question at a time with no memory between questions, and its tools
  return shape IDs, not coordinates.
- The evaluation uses a single generated layout and 9 cases with one model; it shows that the
  loop works, not how well any model does in general.
- Built and tested on Linux (WSL Ubuntu) with GCC. GitHub Actions runs the Debug and Release
  tests, the sanitizer build and clang-tidy on Ubuntu; Windows has not been tried.

## Project layout

```
src/        the engine: rect.hpp, geometry.hpp, violation.hpp, layout, checks, io_json
app/        main.cpp (the layoutagent CLI) and benchmark.cpp
agent/      tools.py (the four tools), llm.py (API client), agent.py (the loop), __main__.py
eval/       cases.json, scoring.py, run_eval.py
tests/      GoogleTest tests (*.cpp) and Python tests (test_*.py)
tools/      gen_layout.py (layout generator with planted violations)
third_party/nlohmann/json.hpp
```

`src/` is built as a library that the CLI, the benchmark and the tests all link against.
