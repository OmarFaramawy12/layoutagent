# LayoutAgent architecture

How the code base fits together, and why each major design choice was made. For usage, the
command line and the benchmark, see the [README](README.md).

---

## 1. What the system is

A small design-rule checker (DRC) for IC layouts with a natural-language front end.

- **Engine (C++20):** stores axis-aligned rectangles on named layers and finds violations of
  four kinds of question: minimum width, minimum spacing, cross-layer overlap, and "which
  shapes touch this window". A fifth query returns one shape by ID. All arithmetic is exact
  64-bit integer arithmetic.
- **Front end (Python):** an LLM chooses which check to run through tool calling, and explains
  the JSON the engine returns. The LLM never sees raw geometry and never computes anything.

### Component map

```
                      +------------------+
 question  ---------> |  python -m agent |  (agent/__main__.py)
                      +--------+---------+
                               |
                      +--------v---------+        HTTPS, OpenAI chat-completions format
                      |   Agent loop     | <----------------------------------------> LLM
                      |  (agent/agent.py)|        (agent/llm.py, stdlib urllib)
                      +--------+---------+
                               | tool call, e.g. check_min_spacing {"min_spacing": 60}
                      +--------v---------+
                      |   DrcTools       |  validates arguments, builds an argument LIST
                      |  (agent/tools.py)|  (no shell), caps long results
                      +--------+---------+
                               | subprocess: layoutagent layout.json --min-spacing 60
                      +--------v---------+
                      | layoutagent CLI  |  app/main.cpp  (parse args, run, print JSON)
                      +--------+---------+
                               |
        +----------------------v-----------------------------------------+
        |  C++ engine library (src/)                                     |
        |  rect.hpp  geometry.hpp  violation.hpp  layout.*  checks.*     |
        |  io_json.*   (JSON in, JSON out; the ONLY place that makes text)|
        +----------------------------------------------------------------+

 Separate tools:   tools/gen_layout.py   seeded random layouts with PLANTED violations
                   eval/                 runs questions against a real LLM, deterministic scoring
                   app/benchmark.cpp     naive vs grid timing (Release only)
```

### Layers of responsibility

| Layer | Owns | Must NOT |
|---|---|---|
| `src/` engine | geometry, rules, IDs, JSON text at the I/O boundary | print, know about the LLM |
| `app/main.cpp` | command line, exit codes, stdout/stderr | contain geometry |
| `agent/tools.py` | argument validation, process launch, result caps | do geometry |
| `agent/agent.py` | the conversation loop, step limit | know which tools exist (gets them from `DrcTools`) |
| `agent/llm.py` | HTTP, retries, API format | know about DRC |
| `eval/` | questions, scoring | trust the model for ground truth |

The single most important rule across all layers: **numbers in an answer come from the C++
engine, never from the model.**

### One request, step by step

1. The user asks: "Which shapes are narrower than 50 nm?"
2. `Agent.ask` sends the system prompt (layer names, units, how to read results), the question
   and the tool schemas to the LLM.
3. The LLM replies with a tool call: `check_min_width {"min_width": 50}`.
4. `DrcTools` validates it (an integer, in range), runs
   `layoutagent layout.json --min-width 50` as a subprocess with a timeout.
5. The CLI loads the layout, runs `check_width` on every layer, prints JSON on stdout.
6. `DrcTools` parses the JSON, caps the list (50 violations), keeps the true `total_count`,
   and returns it. A failure is returned as `Error: ...` text instead.
7. The agent sends the result back to the LLM as a tool message; the LLM writes the answer.
8. The loop stops when the model answers without a tool call, or after 8 steps.

---

## 2. The engine in detail

### Data model

- `Rect`: lower-left `(x1, y1)`, upper-right `(x2, y2)`, a layer ID, a **global** shape ID.
  Invariant `x1 < x2` and `y1 < y2`, every coordinate within +/- 1,000,000,000. The
  constructor throws `std::invalid_argument` (with the shape ID and the bad values) so an
  invalid `Rect` cannot exist.
- `Layout`: layer names to integer IDs (and back), and **one `std::vector<Rect>` per layer**.
  Shape IDs are assigned 0, 1, 2, ... in the order shapes are added.
- `Violation`: one struct for all check types: type (`enum class`), layer IDs, first shape ID,
  optional second shape ID, `measured`, `required`.
- Checks: **free functions** returning `std::vector<Violation>`.

### The rules, exactly

- Gap of two intervals: `gap = max(a1, b1) - min(a2, b2)`. Negative = overlap, zero =
  touching, positive = empty space.
- Rect distance is Euclidean: `dx = max(0, gap_x)`, `dy = max(0, gap_y)`.
- Spacing violation iff `dx*dx + dy*dy < S*S` (squared integers, no `sqrt`). Exactly S is
  allowed. Touching or overlapping shapes (distance 0) are violations.
- Width violation iff `min(width, height) < W`.
- Overlap (different layers) iff `gap_x < 0 && gap_y < 0` (positive shared area; touching an
  edge or corner is not an overlap).
- Width and spacing only compare shapes on the same layer.

---

## 3. Design decisions: options considered and why one was chosen

Each entry: the decision, the realistic alternatives, the choice, and the reason. "Cost"
states honestly what the choice gives up.

### 3.1 Numbers and geometry

**Coordinate type**

| Option | Verdict |
|---|---|
| `double` | Rejected. Equality tests ("distance exactly S is allowed", "touching") become unreliable. A DRC tool lives on exact boundaries. |
| `unsigned` integers | Rejected. A gap is negative when shapes overlap; unsigned wrap-around turns that into a huge positive number. |
| **signed `int64_t` in nm** | Chosen. Exact, and the standard approach in layout tools (integer database units). |

Cost: overflow has to be prevented by design. That is why every coordinate is bounded by
`kMaxAbsCoord = 1e9`: the largest `dx` is 2e9, so `dx*dx + dy*dy <= 8e18 < 9.22e18`
(`int64_t` max). Rule values are bounded to `(0, 2e9]` so `S*S` fits too. The sanitizer build
(UBSan) exists partly to confirm no overflow ever happens.

**Spacing comparison**

| Option | Verdict |
|---|---|
| `sqrt(dx²+dy²) < S` | Rejected: floating point, and a needless `sqrt`. |
| Manhattan or per-axis distance | Rejected: not the rule being modelled; Euclidean is what the convention says. |
| **compare `dx²+dy²` with `S²`** | Chosen. Exact, fast, monotone (squaring preserves order for non-negative numbers). |

This is why the violation's `measured` for spacing is the *squared* distance and the system
prompt tells the LLM to take a square root before talking about nm.

**Invariant in the constructor, fields private**

Alternatives: public fields with a validating factory function, or a plain struct validated by
callers. Chosen: private fields, `const` getters, throwing constructor. Reason: the invariant
(`x1 < x2`) cannot be broken after construction, so every check can rely on it without
re-checking. Fields are non-const (not `const int64_t x1_`) so `std::vector<Rect>` still works
(const members would delete assignment).

### 3.2 Engine structure

**One `Violation` struct vs one struct (or class hierarchy) per check**

Chosen: one struct with an `enum class` type and an optional second shape. Reason: the JSON
writer, the tests and the Python layer all handle one shape of data. Inheritance and templates
were avoided on purpose (readable, explainable, small). Cost: `measured` means different
things per type (nm, nm², area); the README table and the system prompt document it.

**Checks as free functions returning vectors, the engine never prints**

Alternative: a `Checker` class with state, or checks that print. Chosen: stateless functions
`(const Layout&, rule values) -> std::vector<Violation>`. Reason: trivially testable (compare
the returned vector), no hidden state, and **text is only produced at the I/O boundary**
(`violations_to_json` in `src/io_json.cpp`). Cost: a few helper functions are passed
parameters instead of reading members.

**Layers as integer IDs, one vector per layer**

Alternatives: store a layer name string in every `Rect`; one big vector of all rects with a
layer field. Chosen: names converted to IDs at load, one vector per layer. Reason: width and
spacing only look at one layer, so per-layer vectors make "all shapes on this layer" free and
cross-layer comparison explicit. Cost: shape IDs are *global* (not per layer), so
`find_rect(id)` has to scan all layers. That is acceptable for a one-shot lookup; an index
(`vector` by ID) would be the fix if it were ever hot.

**Naive O(n²) first, grid later, naive kept as reference**

Chosen order: correct and simple first, then the grid with an equivalence test against the
naive version. The idea: for a shape `a`, a violating partner must be closer than S on both
axes, so only shapes inside `a` grown by S need the exact test. The grid is only a filter; the
rule test is unchanged, so the equivalence test (field by field, in order, on boundary cases
and random layouts) proves it. See the README for the benchmark.

### 3.3 Input and output formats

**Layout file: JSON with layers as an object of rect arrays**

Alternatives: GDSII/OASIS (real industry formats, but a binary parser is a project of its
own), CSV (no layer structure), Python pickle (not portable, unsafe). Chosen: JSON, because it
is easy to generate, diff and read, and a well-known library parses it.

**IDs come from file order, not from the file**

The file stores no IDs. Layer IDs follow the order of layers in the file; shape IDs count
across the file layer by layer. Alternative: store IDs explicitly in the file. Chosen:
implicit, because it keeps the file small and makes IDs impossible to duplicate. Cost: JSON
says key order has no meaning, so this is a project convention, not a guarantee. That is why:
(a) the C++ loader uses `nlohmann::ordered_json` (the default `json` sorts keys
alphabetically and would silently change IDs), (b) a test fails if that ever changes, (c) the
README documents the assumption.

**Duplicate keys are rejected**

JSON parsers usually keep the last of two equal keys without a word. For a layer name that
would silently drop a whole list of rects. The C++ loader uses a parse callback to detect
repeats; the Python tool layer uses `object_pairs_hook` for the same rule. Both implement the
same rule so the Python side and the engine can never disagree about which layers exist.

**CLI prints JSON to stdout, errors to stderr, exit codes 0/1/2**

0 = checks ran (with or without violations), 1 = runtime error (bad file, unknown layer),
2 = usage error. "Violations found" is deliberately exit code 0: finding violations is the
tool working, not failing. Output is printed only after everything succeeded, so a failed run
never leaves half an answer on stdout.

**Python talks to C++ through a subprocess, not a binding**

| Option | Cost |
|---|---|
| pybind11 / C extension | Adds a dependency and a build system for Python; a crash in C++ takes down the Python process; harder to run the sanitizers. |
| ctypes over a C ABI | Needs a hand-written C interface and manual memory rules. |
| **subprocess running the CLI** | Chosen. Process isolation, a timeout, the exact same interface a human uses, no new dependency, and the CLI is tested end to end by the same code path the agent uses. |

Cost: process start-up per call and JSON parsing. For tool calls driven by a human question
that is irrelevant. The process is started with an argument **list** (never a shell), so a
layer name like `metal1; rm -rf /` is just text.

### 3.4 The agent layer

**Raw HTTP client vs an SDK**

Chosen: ~one small module using the standard library (`urllib`) against the OpenAI-compatible
chat-completions format, configured by `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` (from a
git-ignored `.env`). Reason: no dependency, and the format works with NVIDIA NIM, Groq,
OpenRouter and others, so the project is not tied to one vendor. Cost: retries and error
handling are written by hand (and are tested against a local fake HTTP server).

**Tool set: five narrow tools vs one generic tool**

Alternative: a single `run_drc(args)` tool taking free text. Rejected: the model could invent
flags and the validation burden moves to a text parser. Chosen: five tools with JSON-schema
arguments (`additionalProperties: false`), each mapping to exactly one CLI mode. The model
picks a tool and fills typed numbers; `DrcTools` validates again (including: an integer, not a
boolean, and layer names that really exist in the layout).

**Errors go back to the model; host problems stop the run**

A *model* mistake (wrong argument, unknown layer) is returned as `Error: ...` so the model can
correct the call and retry. A *host* problem (the program is missing) raises and stops the
run, because the model cannot fix it. This split is what keeps retries useful.

**Long results are capped, `total_count` is not**

A layout can have thousands of violations; sending all of them wastes tokens. The tool layer
returns at most 50 violations / 200 shape IDs and always the real `total_count` plus a
`truncated` flag. The system prompt tells the model to report `total_count`.

**Loop limits and determinism**

Maximum 8 steps (a model that keeps calling tools cannot run forever) and temperature 0
(repeatable behaviour, comparable evaluation runs). If a number is missing (e.g. "check the
minimum width"), the prompt tells the model to ask rather than invent one; there is an
evaluation case for exactly that.

**`get_shape` exists because IDs are not positions**

Violations and window queries return shape IDs only. Without `get_shape` a model asked "where
is shape 19?" would have to guess. The ID-to-position lookup lives in C++ (`Layout::find_rect`)
because the loader assigns IDs: a Python lookup would re-implement the ID rule and could drift
from it.

### 3.5 Testing

**Planted violations instead of a second checker**

`tools/gen_layout.py` builds seeded random layouts on a grid of slots, one pattern per slot,
so the correct violations are known *by construction* (and decoys sitting exactly on the rule
limits must NOT be reported). Alternative: write a reference checker in Python and compare.
Rejected as the primary oracle: it would repeat the same geometry logic, and a shared
misunderstanding of the rule would pass both. Planted violations are independent of any
implementation. (For the grid the oracle *is* the naive C++ check, because
there the question is "same answer as the simple version", not "right according to the rules".)

**Tests first.** Behaviour tests were written and seen failing before each change.

**Gates:** warnings on (`-Wall -Wextra`, `/W4`), AddressSanitizer + UBSan build, clang-tidy 15
(with a cognitive-complexity limit of 25 that is enforced), and GitHub Actions on Ubuntu (Debug
and Release, sanitizers, clang-tidy) and Windows MSVC (Debug and Release).
