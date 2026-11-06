"""Tests for tools/gen_layout.py. Run with:

    python3 -m unittest discover -s tests -p "test_gen_layout.py"

These tests check that the generator is deterministic, writes valid files, and that every
violation it *claims* matches the rects it points to (this catches shape-ID mix-ups).
They do not prove that no other violations exist: that is checked by the C++ engine in the
end-to-end test (roadmap step 7).
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import gen_layout  # noqa: E402

MAX_ABS_COORD = 1_000_000_000


# ---- small helpers (a spot-check of the generator's numbers, not a DRC engine) ----

def shapes_in_id_order(layout):
    """[(layer_name, rect), ...] so that the list index is the shape ID (file-order rule)."""
    shapes = []
    for layer, rects in layout["layers"].items():
        for rect in rects:
            shapes.append((layer, rect))
    return shapes


def gaps(a, b):
    gap_x = max(a[0], b[0]) - min(a[2], b[2])
    gap_y = max(a[1], b[1]) - min(a[3], b[3])
    return gap_x, gap_y


def squared_distance(a, b):
    gap_x, gap_y = gaps(a, b)
    return max(0, gap_x) ** 2 + max(0, gap_y) ** 2


def overlap_area(a, b):
    gap_x, gap_y = gaps(a, b)
    return gap_x * gap_y if gap_x < 0 and gap_y < 0 else 0


def sort_key(violation):
    second = violation["second_shape_id"]
    return (violation["type"], violation["layer_a"], violation["layer_b"],
            violation["first_shape_id"], -1 if second is None else second,
            violation["measured"], violation["required"])


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.layout, self.expected = gen_layout.generate(seed=3, count=200)
        self.shapes = shapes_in_id_order(self.layout)

    # ---- determinism and format ----

    def test_same_seed_gives_the_same_output(self):
        again = gen_layout.generate(seed=3, count=200)
        self.assertEqual(again, (self.layout, self.expected))

    def test_different_seed_gives_different_output(self):
        other_layout, _ = gen_layout.generate(seed=4, count=200)
        self.assertNotEqual(other_layout, self.layout)

    def test_layers_are_in_the_documented_order(self):
        self.assertEqual(list(self.layout["layers"]), gen_layout.LAYERS)
        # The order is deliberately not alphabetical, so the end-to-end test also proves
        # that the C++ loader keeps file order.
        self.assertNotEqual(gen_layout.LAYERS, sorted(gen_layout.LAYERS))

    def test_every_rect_is_valid(self):
        for layer, rect in self.shapes:
            self.assertEqual(len(rect), 4, rect)
            for value in rect:
                self.assertIsInstance(value, int)
                self.assertLessEqual(abs(value), MAX_ABS_COORD)
            self.assertLess(rect[0], rect[2], rect)
            self.assertLess(rect[1], rect[3], rect)

    def test_rects_stay_inside_their_slots(self):
        # Shapes in different slots can only be far apart if each one stays inside its
        # slot's interior, so no unplanned violation can appear between slots.
        pitch, margin = gen_layout.SLOT_PITCH, gen_layout.SLOT_MARGIN
        for layer, (x1, y1, x2, y2) in self.shapes:
            column, row = x1 // pitch, y1 // pitch
            self.assertGreaterEqual(x1, column * pitch + margin)
            self.assertLessEqual(x2, (column + 1) * pitch - margin)
            self.assertGreaterEqual(y1, row * pitch + margin)
            self.assertLessEqual(y2, (row + 1) * pitch - margin)

    def test_expected_file_lists_seed_and_rules(self):
        self.assertEqual(self.expected["seed"], 3)
        self.assertEqual(self.expected["rules"],
                         {"min_width": 50, "min_spacing": 40,
                          "overlap_pairs": [["metal1", "via1"]]})

    # ---- the violations ----

    def test_every_violation_type_appears(self):
        types = {v["type"] for v in self.expected["violations"]}
        self.assertEqual(types, {"min_width", "min_spacing", "overlap"})

    def test_violations_are_sorted(self):
        violations = self.expected["violations"]
        self.assertEqual(violations, sorted(violations, key=sort_key))

    def test_violation_values_follow_the_rules(self):
        for v in self.expected["violations"]:
            if v["type"] == "min_width":
                self.assertLess(v["measured"], 50)
                self.assertEqual(v["required"], 50)
            elif v["type"] == "min_spacing":
                self.assertLess(v["measured"], 40 * 40)
                self.assertEqual(v["required"], 40 * 40)
            else:
                self.assertGreater(v["measured"], 0)  # the overlap area
                self.assertEqual(v["required"], 0)

    def test_violations_match_the_shapes_they_point_to(self):
        for v in self.expected["violations"]:
            first_layer, first = self.shapes[v["first_shape_id"]]
            self.assertEqual(v["layer_a"], first_layer)

            if v["type"] == "min_width":
                self.assertIsNone(v["second_shape_id"])
                self.assertEqual(v["layer_b"], first_layer)
                self.assertEqual(v["measured"],
                                 min(first[2] - first[0], first[3] - first[1]))
                continue

            second_layer, second = self.shapes[v["second_shape_id"]]
            self.assertEqual(v["layer_b"], second_layer)
            if v["type"] == "min_spacing":
                self.assertEqual(first_layer, second_layer)
                self.assertLess(v["first_shape_id"], v["second_shape_id"])
                self.assertEqual(v["measured"], squared_distance(first, second))
            else:
                self.assertNotEqual(first_layer, second_layer)
                self.assertEqual(v["measured"], overlap_area(first, second))

    def test_boundary_decoys_are_present(self):
        # Shapes that sit exactly on a rule limit must NOT be flagged. The generator has to
        # create some, otherwise the strict "<" comparisons would never be tested.
        reported = {(v["first_shape_id"], v["second_shape_id"]) for v in self.expected["violations"]}

        exact_width = [i for i, (_, r) in enumerate(self.shapes)
                       if min(r[2] - r[0], r[3] - r[1]) == 50]
        self.assertTrue(exact_width, "no rect with width exactly 50")

        exact_spacing = [(i, j)
                         for i, (layer_i, a) in enumerate(self.shapes)
                         for j, (layer_j, b) in enumerate(self.shapes)
                         if i < j and layer_i == layer_j and squared_distance(a, b) == 40 * 40]
        self.assertTrue(exact_spacing, "no pair at distance exactly 40")
        for pair in exact_spacing:
            self.assertNotIn(pair, reported)

        touching = [(i, j)
                    for i, (layer_i, a) in enumerate(self.shapes)
                    for j, (layer_j, b) in enumerate(self.shapes)
                    if layer_i == "metal1" and layer_j == "via1"
                    and max(gaps(a, b)) == 0 and min(gaps(a, b)) <= 0]
        self.assertTrue(touching, "no metal1/via1 pair that only touches")
        for pair in touching:
            self.assertNotIn(pair, reported)


class CommandLineTest(unittest.TestCase):
    def test_writes_the_layout_and_expected_files(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = os.path.join(folder, "sub", "case7")
            with contextlib.redirect_stdout(io.StringIO()):
                gen_layout.main(["--seed", "7", "--count", "30", "--out", prefix])

            with open(prefix + ".json") as f:
                layout = json.load(f)
            with open(prefix + ".expected.json") as f:
                expected = json.load(f)

        self.assertEqual((layout, expected), gen_layout.generate(seed=7, count=30))
        self.assertEqual(list(layout["layers"]), gen_layout.LAYERS)  # file order survives

    def test_count_must_be_positive(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                gen_layout.main(["--count", "0", "--out", "unused"])


if __name__ == "__main__":
    unittest.main()
