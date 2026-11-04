# LayoutAgent

A small design-rule checker (DRC) for IC layouts, with a natural-language front end.

- A **C++20 engine** stores axis-aligned rectangles on layers and finds rule violations (minimum width, minimum spacing, cross-layer overlap, window query) using exact integer geometry.
- A **Python layer** lets an LLM call the engine through tool calling. The LLM only picks which check to run and explains the result. **All geometry happens in C++.**

Portfolio project for a Siemens EDA Software Development Engineer application. The owner is an experienced Python developer who is learning C++ while building this.

## How to work with me

- Make **small, focused changes**. Do not refactor, rename, or add features I did not ask for.
- Before or after each change, briefly explain **what** you did and **why**, especially anything C++-specific (ownership, `const`, references vs copies, headers and linking). Assume I know Python well and C++ not yet.
- I must be able to explain, debug, and modify every line. Prefer plain, readable code over clever code. Avoid templates, inheritance, and other advanced features unless the task needs them.
- Write or update **tests first** when adding behavior (GoogleTest, in `tests/`).
- In reviews, point out the problem, explain why it is a problem, and show the fix directly.
- Ask at most one or two questions, and only when you cannot reasonably decide yourself.
- **Do not commit or push.** Leave changes uncommitted so I can review them with `git diff`.
- Do not delete files and do not add dependencies without asking.
- If something here conflicts with the existing code, **stop and tell me**. Do not silently pick one.

## Conventions (decisions already made; do not change without asking)

**Coordinates and units**
- Coordinates are **signed `std::int64_t`**, in database units (1 unit = 1 nm). Never `unsigned`: gaps are negative when shapes overlap.
- The y axis grows **upward**.
- Every coordinate must satisfy `|value| <= kMaxAbsCoord` (1,000,000,000), enforced in the `Rect` constructor. This guarantees `dx*dx + dy*dy` cannot overflow `int64_t`. Rule values (S, W) must be bounded so `S*S` also fits.

**Rect**
- Defined by lower-left `(x1, y1)` and upper-right `(x2, y2)`.
- Invariant: `x1 < x2` and `y1 < y2` (strict, so zero-width and zero-height shapes are rejected). The constructor throws `std::invalid_argument` with a message that includes the shape ID and the bad values.
- Fields are **private and non-const**, with `const` getters, so the invariant cannot be broken after construction and `std::vector<Rect>` still works.
- Getters: `x1() y1() x2() y2() width() height() layer_id() shape_id()`. `width()` is the x extent and `height()` is the y extent. No area or perimeter functions until a check needs them.

**Geometry rules**
- 1D gap of two intervals: `gap = max(a1, b1) - min(a2, b2)`. Negative means overlap, zero means touching, positive is the empty space between them.
- Rectangle distance: `dx = max(0, gap_x)`, `dy = max(0, gap_y)`. Distance is **Euclidean**.
- Spacing violation if and only if `dx*dx + dy*dy < S*S` (compared as squared integers, no `sqrt`). A distance exactly equal to S is allowed.
- Touching or overlapping shapes on the same layer have distance 0, so they are spacing violations.
- Spacing and width only look at shapes on the **same layer**. Cross-layer comparison is the job of `check_overlap(layerA, layerB)`.
- Minimum width violation: `min(width(), height()) < W`.

**Layout and layers**
- Layer names are converted to integer IDs at load time. `Layout` keeps both directions: name to ID (`unordered_map<string,int>`) and ID to name (`vector<string>`).
- `Layout` stores **one vector of `Rect` per layer**. Every `Rect` gets a **globally unique shape ID** assigned at load time.

**Violations and checks**
- One `Violation` struct (not one per check type) with: type (enum class), layer ID(s), first shape ID, optional second shape ID (`std::optional`), measured value, required value. For spacing, the measured value is the **squared** distance.
- Checks are **free functions returning `std::vector<Violation>`**. The engine never prints. Turning violations into JSON or text is done only at the CLI boundary.

**Input and output**
- Layout file is JSON: `{"layers": {"metal1": [[x1, y1, x2, y2], ...], ...}}`. It is produced by `tools/gen_layout.py` (seeded random layouts with planted violations plus an expected-answer file). The C++ loader reads it and fails loudly on bad input.
- CLI prints violation JSON to **stdout** and errors to **stderr**, with a non-zero exit code on failure.

## Code style

- Language standard C++20. Warnings on: `-Wall -Wextra`.
- Everything in `namespace layoutagent`. Use `#pragma once` in headers.
- No raw `new`/`delete` and no raw owning pointers. Use value types and standard containers.
- Do not add unused code (no speculative helpers).
- Small header-only types are fine (`Rect`, `Violation`). Larger logic gets a `.hpp` + `.cpp` pair.

## Project layout

```
src/     engine: rect.hpp, geometry, violation.hpp, layout, checks, io_json
app/     main.cpp (the CLI)            (planned)
tests/   GoogleTest tests
tools/   gen_layout.py (layout generator)
third_party/nlohmann/json.hpp
```

`src/` is built as a library that both the CLI and the tests link against.

## Build and test (WSL Ubuntu, CMake + Ninja)

```
cd build && cmake .. && ninja && ctest --output-on-failure
```

Or from the project root: `ctest --test-dir build --output-on-failure`. Never benchmark a debug build.

## Roadmap (2 weeks, about 2 hours per day)

1. `Rect` and tests
2. Geometry helpers (gap, dx, dy, squared distance)
3. `Violation`, layers, `Layout`
4. Width and spacing checks (naive O(n²), pairs with `j > i`)
5. Overlap check and window query
6. JSON loader and the Python generator
7. CLI and an end-to-end check against the generator's expected answers
8. Python LLM tool-calling layer and a small evaluation set
9. Spatial grid for spacing, with a test that it matches the naive result, plus a benchmark
10. Sanitizers (ASan/UBSan), clang-tidy, CI on Ubuntu and Windows, README

If time runs short, cut in this order: stretch goals, CI, the evaluation set, clang-tidy. Never cut the tests or the naive-vs-grid equivalence test.

**Current stage:** Violation, layers, and Layout (roadmap step 3). Steps 1-2 (Rect, geometry helpers) are done (update this line as the project moves).
