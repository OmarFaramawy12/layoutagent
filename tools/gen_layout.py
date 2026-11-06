"""Generates a seeded random layout with planted rule violations, plus the expected answers.

    python3 tools/gen_layout.py --seed 42 --count 60 --out build/data/case42

writes  build/data/case42.json           the layout file read by the C++ loader
and     build/data/case42.expected.json  the violations the C++ engine must report

How the expected answers are guaranteed
---------------------------------------
The plane is a grid of square slots. Each slot gets exactly one "pattern" (a rect, a pair of
rects, ...) placed inside the slot's interior, at least MIN_SPACING away from the slot edge.
So shapes in different slots are always far apart, and the only violations in a layout are
the ones a pattern plants on purpose. Each pattern knows its own numbers by construction
(for example a planted gap of 9 means a squared distance of 81), so this script contains no
geometry checker. The C++ engine does all the checking, and the end-to-end test compares it
with these answers.

Some patterns are "decoys" that sit exactly on a rule limit and must NOT be reported.

IDs follow the rule in the README: layers get IDs in the order of LAYERS (which is also the
order in the layout file), and shape IDs count 0, 1, 2, ... across the file, layer by layer.
"""

import argparse
import json
import os
import random

# ---- the rules the layouts are built for (the same values go in the expected file) ----

MIN_WIDTH = 50
MIN_SPACING = 40

# Layer order is the order in the file, so it is also the layer ID order. It is deliberately
# NOT alphabetical, so the end-to-end test also checks that the loader keeps file order.
LAYERS = ["metal1", "via1", "metal2"]
OVERLAP_PAIRS = [("metal1", "via1")]  # (layer_a, layer_b) pairs checked for overlap

# ---- slot grid ----

SLOT_PITCH = 1000            # slot size in nm
SLOT_MARGIN = MIN_SPACING    # empty border inside each slot: neighbours end up >= 2 * margin apart
SLOTS_PER_ROW = 10
MAX_SIDE = 200               # largest rect side the patterns use

# A pair of diagonal gaps whose squared lengths add up to exactly MIN_SPACING squared.
EXACT_DIAGONAL = (24, 32)
assert EXACT_DIAGONAL[0] ** 2 + EXACT_DIAGONAL[1] ** 2 == MIN_SPACING ** 2


class Builder:
    """Collects the rects and the planted violations while the patterns are placed."""

    def __init__(self):
        self.rects = {layer: [] for layer in LAYERS}
        self.planted = []  # (type, ref_a, ref_b or None, measured, required)

    def add_rect(self, layer, x1, y1, x2, y2):
        """Adds a rect and returns its reference (layer, index in that layer's list)."""
        self.rects[layer].append([x1, y1, x2, y2])
        return (layer, len(self.rects[layer]) - 1)

    def plant(self, kind, ref_a, ref_b, measured, required):
        self.planted.append((kind, ref_a, ref_b, measured, required))

    def layout_dict(self):
        return {"layers": {layer: self.rects[layer] for layer in LAYERS}}

    def expected_dict(self, seed):
        # Shape IDs: layer by layer in LAYERS order, in list order inside each layer.
        shape_id = {}
        for layer in LAYERS:
            for index in range(len(self.rects[layer])):
                shape_id[(layer, index)] = len(shape_id)

        violations = []
        for kind, ref_a, ref_b, measured, required in self.planted:
            violations.append({
                "type": kind,
                "layer_a": ref_a[0],
                "layer_b": ref_a[0] if ref_b is None else ref_b[0],
                "first_shape_id": shape_id[ref_a],
                "second_shape_id": None if ref_b is None else shape_id[ref_b],
                "measured": measured,
                "required": required,
            })
        violations.sort(key=violation_sort_key)

        return {
            "seed": seed,
            "rules": {
                "min_width": MIN_WIDTH,
                "min_spacing": MIN_SPACING,
                "overlap_pairs": [list(pair) for pair in OVERLAP_PAIRS],
            },
            "violations": violations,
        }


def violation_sort_key(violation):
    """The order violation lists are compared in (also used by the end-to-end test)."""
    second = violation["second_shape_id"]
    return (violation["type"], violation["layer_a"], violation["layer_b"],
            violation["first_shape_id"], -1 if second is None else second,
            violation["measured"], violation["required"])


# ---- small helpers used by the patterns ----

def random_side(rng):
    """A side length that is wide enough to satisfy the width rule."""
    return rng.randint(MIN_WIDTH, MAX_SIDE)


def place(builder, layer, x, y, rel, transpose):
    """Adds a rect given relative to the slot origin (x, y) as (u1, v1, u2, v2).
    With transpose=True the u and v axes are swapped, which turns horizontal patterns
    into vertical ones."""
    u1, v1, u2, v2 = rel
    if transpose:
        return builder.add_rect(layer, x + v1, y + u1, x + v2, y + u2)
    return builder.add_rect(layer, x + u1, y + v1, x + u2, y + v2)


def side_by_side_pair(builder, rng, x, y, gap):
    """Two wide-enough rects on one layer, `gap` apart along one axis and overlapping along
    the other, so the distance between them is exactly `gap`. Returns (ref_a, ref_b)."""
    layer = rng.choice(LAYERS)
    transpose = rng.random() < 0.5
    w1, h1, w2, h2 = (random_side(rng) for _ in range(4))
    offset = rng.randint(0, h1 - 1)  # the second rect starts inside the first one's v range
    a = place(builder, layer, x, y, (0, 0, w1, h1), transpose)
    b = place(builder, layer, x, y, (w1 + gap, offset, w1 + gap + w2, offset + h2), transpose)
    return a, b


def diagonal_pair(builder, rng, x, y, dx, dy):
    """Two wide-enough rects on one layer, corner to corner, `dx` apart in x and `dy` in y,
    so the squared distance is dx*dx + dy*dy. Returns (ref_a, ref_b)."""
    layer = rng.choice(LAYERS)
    w1, h1, w2, h2 = (random_side(rng) for _ in range(4))
    a = builder.add_rect(layer, x, y, x + w1, y + h1)
    b = builder.add_rect(layer, x + w1 + dx, y + h1 + dy, x + w1 + dx + w2, y + h1 + dy + h2)
    return a, b


# ---- patterns: each one fills one slot. Signature: (builder, rng, x, y) ----

def clean_rect(builder, rng, x, y):
    """No violation."""
    builder.add_rect(rng.choice(LAYERS), x, y, x + random_side(rng), y + random_side(rng))


def exact_width_rect(builder, rng, x, y):
    """Decoy: a side of exactly MIN_WIDTH is allowed."""
    w, h = MIN_WIDTH, random_side(rng)
    if rng.random() < 0.5:
        w, h = h, w
    builder.add_rect(rng.choice(LAYERS), x, y, x + w, y + h)


def narrow_rect(builder, rng, x, y):
    """Planted min_width violation: the narrow side is below MIN_WIDTH."""
    narrow = rng.randint(1, MIN_WIDTH - 1)
    long_side = random_side(rng)
    w, h = (narrow, long_side) if rng.random() < 0.5 else (long_side, narrow)
    ref = builder.add_rect(rng.choice(LAYERS), x, y, x + w, y + h)
    builder.plant("min_width", ref, None, narrow, MIN_WIDTH)


def close_pair(builder, rng, x, y):
    """Planted min_spacing violation: a gap from 0 (touching) to MIN_SPACING - 1."""
    gap = rng.randint(0, MIN_SPACING - 1)
    a, b = side_by_side_pair(builder, rng, x, y, gap)
    builder.plant("min_spacing", a, b, gap * gap, MIN_SPACING ** 2)


def close_diagonal_pair(builder, rng, x, y):
    """Planted min_spacing violation: corner to corner, Euclidean distance below MIN_SPACING."""
    while True:  # rejection sampling; dx = dy = 1 always works, so this ends
        dx = rng.randint(1, MIN_SPACING - 1)
        dy = rng.randint(1, MIN_SPACING - 1)
        if dx * dx + dy * dy < MIN_SPACING ** 2:
            break
    a, b = diagonal_pair(builder, rng, x, y, dx, dy)
    builder.plant("min_spacing", a, b, dx * dx + dy * dy, MIN_SPACING ** 2)


def overlapping_pair(builder, rng, x, y):
    """Planted min_spacing violation: two rects on the SAME layer overlap (distance 0)."""
    layer = rng.choice(LAYERS)
    w1, h1, w2, h2 = (random_side(rng) for _ in range(4))
    a = builder.add_rect(layer, x, y, x + w1, y + h1)
    left, bottom = x + rng.randint(0, w1 - 1), y + rng.randint(0, h1 - 1)
    b = builder.add_rect(layer, left, bottom, left + w2, bottom + h2)
    builder.plant("min_spacing", a, b, 0, MIN_SPACING ** 2)


def exact_spacing_pair(builder, rng, x, y):
    """Decoy: a gap of exactly MIN_SPACING is allowed."""
    side_by_side_pair(builder, rng, x, y, MIN_SPACING)


def exact_diagonal_pair(builder, rng, x, y):
    """Decoy: a diagonal distance of exactly MIN_SPACING (24-32-40) is allowed."""
    diagonal_pair(builder, rng, x, y, *EXACT_DIAGONAL)


def cross_layer_overlap(builder, rng, x, y):
    """Planted overlap violation: a rect on layer_a and one on layer_b share an area."""
    layer_a, layer_b = rng.choice(OVERLAP_PAIRS)
    w, h, vw, vh = (random_side(rng) for _ in range(4))
    overlap_w = rng.randint(1, min(w, vw))  # how far the second rect reaches into the first
    overlap_h = rng.randint(1, min(h, vh))
    a = builder.add_rect(layer_a, x, y, x + w, y + h)
    left, bottom = x + w - overlap_w, y + h - overlap_h
    b = builder.add_rect(layer_b, left, bottom, left + vw, bottom + vh)
    # The second rect reaches past the first one's top and right edge (vw >= overlap_w and
    # vh >= overlap_h), so the shared area is exactly overlap_w * overlap_h.
    builder.plant("overlap", a, b, overlap_w * overlap_h, 0)


def cross_layer_touching(builder, rng, x, y):
    """Decoy: shapes on two layers that only share an edge or a corner are not an overlap."""
    layer_a, layer_b = rng.choice(OVERLAP_PAIRS)
    w, h, vw, vh = (random_side(rng) for _ in range(4))
    builder.add_rect(layer_a, x, y, x + w, y + h)
    bottom = y + rng.randint(0, h - 1) if rng.random() < 0.5 else y + h  # edge or corner
    builder.add_rect(layer_b, x + w, bottom, x + w + vw, bottom + vh)


# (pattern, weight): how often each pattern is picked
PATTERNS = [
    (clean_rect, 6),
    (exact_width_rect, 1),
    (narrow_rect, 2),
    (close_pair, 2),
    (close_diagonal_pair, 1),
    (overlapping_pair, 1),
    (exact_spacing_pair, 1),
    (exact_diagonal_pair, 1),
    (cross_layer_overlap, 2),
    (cross_layer_touching, 1),
]


def generate(seed, count):
    """Returns (layout, expected) as plain dicts. The same seed and count always give the
    same result (for the same Python version). `count` is the number of slots."""
    rng = random.Random(seed)
    builder = Builder()
    functions = [function for function, _ in PATTERNS]
    weights = [weight for _, weight in PATTERNS]

    for slot in range(count):
        row, column = divmod(slot, SLOTS_PER_ROW)
        x = column * SLOT_PITCH + SLOT_MARGIN
        y = row * SLOT_PITCH + SLOT_MARGIN
        pattern = rng.choices(functions, weights)[0]
        pattern(builder, rng, x, y)

    return builder.layout_dict(), builder.expected_dict(seed)


def format_layout(layout):
    """JSON text with one line per layer, which is readable and still compact."""
    lines = [f"  {json.dumps(name)}: {json.dumps(rects)}"
             for name, rects in layout["layers"].items()]
    return '{"layers": {\n' + ",\n".join(lines) + "\n}}\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a random layout with planted violations and its expected answers.")
    parser.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    parser.add_argument("--count", type=int, default=60,
                        help="number of slots, one pattern each (default 60)")
    parser.add_argument("--out", required=True,
                        help="output prefix: writes PREFIX.json and PREFIX.expected.json")
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be at least 1")

    layout, expected = generate(args.seed, args.count)

    folder = os.path.dirname(args.out)
    if folder:
        os.makedirs(folder, exist_ok=True)
    layout_path = args.out + ".json"
    expected_path = args.out + ".expected.json"
    with open(layout_path, "w") as f:
        f.write(format_layout(layout))
    with open(expected_path, "w") as f:
        json.dump(expected, f, indent=2)
        f.write("\n")

    shape_count = sum(len(rects) for rects in layout["layers"].values())
    print(f"wrote {layout_path} ({shape_count} shapes)")
    print(f"wrote {expected_path} ({len(expected['violations'])} violations)")


if __name__ == "__main__":
    main()
