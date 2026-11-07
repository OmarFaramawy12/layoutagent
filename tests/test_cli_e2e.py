"""End-to-end tests for the command-line program (app/main.cpp).

Run through ctest (which sets LAYOUTAGENT_CLI to the built program), or by hand with:

    LAYOUTAGENT_CLI=build/layoutagent python3 -m unittest discover -s tests -p "test_cli_e2e.py"

The main test generates layouts with tools/gen_layout.py, runs the real program on them, and
compares what it prints with the generator's expected answers (both sorted, so a violation
reported twice or missing makes the test fail).
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import gen_layout  # noqa: E402

CLI = os.environ.get("LAYOUTAGENT_CLI", os.path.join(ROOT, "build", "layoutagent"))


def setUpModule():
    if not os.path.isfile(CLI):
        raise RuntimeError(f"CLI not found at {CLI}. Build it first or set LAYOUTAGENT_CLI.")


def run_cli(*args):
    return subprocess.run([CLI, *args], capture_output=True, text=True)


def write_file(folder, name, text):
    path = os.path.join(folder, name)
    with open(path, "w") as f:
        f.write(text)
    return path


def generate_case(folder, seed, count):
    """Writes a generated layout and returns (layout path, expected-answer dict)."""
    prefix = os.path.join(folder, f"case_{seed}_{count}")
    with contextlib.redirect_stdout(io.StringIO()):
        gen_layout.main(["--seed", str(seed), "--count", str(count), "--out", prefix])
    with open(prefix + ".expected.json") as f:
        expected = json.load(f)
    return prefix + ".json", expected


def rule_arguments(rules):
    """Turns the "rules" part of an expected file into command-line flags."""
    args = ["--min-width", str(rules["min_width"]), "--min-spacing", str(rules["min_spacing"])]
    for layer_a, layer_b in rules["overlap_pairs"]:
        args += ["--overlap", layer_a, layer_b]
    return args


def sorted_violations(stdout):
    return sorted(json.loads(stdout)["violations"], key=gen_layout.violation_sort_key)


class AgainstGeneratorTest(unittest.TestCase):
    def test_matches_the_expected_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            for count in (60, 200):
                for seed in range(1, 21):
                    with self.subTest(seed=seed, count=count):
                        layout_path, expected = generate_case(folder, seed, count)
                        result = run_cli(layout_path, *rule_arguments(expected["rules"]))
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stderr, "")
                        self.assertEqual(sorted_violations(result.stdout),
                                         expected["violations"])

    def test_each_flag_runs_only_its_own_check(self):
        with tempfile.TemporaryDirectory() as folder:
            layout_path, expected = generate_case(folder, 5, 200)
            rules = expected["rules"]
            cases = [
                (["--min-width", str(rules["min_width"])], "min_width"),
                (["--min-spacing", str(rules["min_spacing"])], "min_spacing"),
                (["--overlap", "metal1", "via1"], "overlap"),
            ]
            for flags, kind in cases:
                with self.subTest(kind=kind):
                    result = run_cli(layout_path, *flags)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    want = [v for v in expected["violations"] if v["type"] == kind]
                    self.assertTrue(want, "the test layout has no violation of this kind")
                    self.assertEqual(sorted_violations(result.stdout), want)

    def test_flags_may_come_before_the_layout_path(self):
        with tempfile.TemporaryDirectory() as folder:
            layout_path, expected = generate_case(folder, 5, 60)
            result = run_cli(*rule_arguments(expected["rules"]), layout_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted_violations(result.stdout), expected["violations"])

    def test_output_is_json_followed_by_a_newline(self):
        with tempfile.TemporaryDirectory() as folder:
            layout_path, expected = generate_case(folder, 5, 60)
            result = run_cli(layout_path, *rule_arguments(expected["rules"]))
            self.assertTrue(result.stdout.endswith("\n"))
            self.assertEqual(list(json.loads(result.stdout)), ["violations"])


class HandWrittenLayoutTest(unittest.TestCase):
    def test_a_clean_layout_gives_an_empty_list(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_file(folder, "clean.json", '{"layers": {"metal1": [[0, 0, 100, 100]]}}')
            result = run_cli(path, "--min-width", "50", "--min-spacing", "10")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"violations": []})

    def test_overlap_pairs_are_reported_in_flag_order(self):
        layout = '{"layers": {"a": [[0, 0, 10, 10]], "b": [[5, 5, 15, 15]], "c": [[12, 12, 20, 20]]}}'
        with tempfile.TemporaryDirectory() as folder:
            path = write_file(folder, "three.json", layout)
            result = run_cli(path, "--overlap", "b", "c", "--overlap", "a", "b")
            self.assertEqual(result.returncode, 0, result.stderr)
            violations = json.loads(result.stdout)["violations"]
            # a is shape 0, b is shape 1, c is shape 2.
            self.assertEqual([(v["layer_a"], v["layer_b"], v["first_shape_id"],
                               v["second_shape_id"], v["measured"]) for v in violations],
                             [("b", "c", 1, 2, 9),     # shared area 3 x 3
                              ("a", "b", 0, 1, 25)])   # shared area 5 x 5


class WindowTest(unittest.TestCase):
    """--window LAYER X1 Y1 X2 Y2 prints the IDs of the shapes that intersect the window."""

    LAYOUT = ('{"layers": {"metal1": [[0, 0, 10, 10], [20, 0, 30, 10], [100, 100, 110, 110]],'
              ' "via1": [[5, 5, 8, 8]]}}')

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.path = write_file(cls.folder.name, "window.json", cls.LAYOUT)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def window(self, *args):
        result = run_cli(self.path, "--window", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def test_returns_the_ids_of_the_shapes_in_the_window(self):
        self.assertEqual(self.window("metal1", "5", "5", "25", "8"), {"shape_ids": [0, 1]})

    def test_ids_are_global_across_layers(self):
        self.assertEqual(self.window("via1", "0", "0", "100", "100"), {"shape_ids": [3]})

    def test_an_empty_window_gives_an_empty_list(self):
        self.assertEqual(self.window("metal1", "500", "500", "600", "600"), {"shape_ids": []})

    def test_touching_the_window_edge_is_not_inside(self):
        # shape 0 ends exactly at x = 10, where this window starts
        self.assertEqual(self.window("metal1", "10", "0", "20", "10"), {"shape_ids": []})

    def test_the_window_may_come_before_the_layout_path(self):
        result = run_cli("--window", "metal1", "5", "5", "25", "8", self.path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"shape_ids": [0, 1]})

    def test_output_ends_with_a_newline(self):
        result = run_cli(self.path, "--window", "metal1", "0", "0", "10", "10")
        self.assertTrue(result.stdout.endswith("\n"))


class WindowOnGeneratedLayoutTest(unittest.TestCase):
    def test_a_window_over_everything_returns_every_shape_of_the_layer(self):
        with tempfile.TemporaryDirectory() as folder:
            layout_path, _ = generate_case(folder, 3, 60)
            with open(layout_path) as f:
                layers = json.load(f)["layers"]

            first_id = 0  # shape IDs count layer by layer, in file order
            for name, rects in layers.items():
                with self.subTest(layer=name):
                    result = run_cli(layout_path, "--window", name,
                                     "-100000", "-100000", "100000", "100000")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout)["shape_ids"],
                                     list(range(first_id, first_id + len(rects))))
                first_id += len(rects)


class ErrorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.good = write_file(cls.folder.name, "good.json",
                              '{"layers": {"metal1": [[0, 0, 100, 100]], "via1": [[10, 10, 40, 40]]}}')
        cls.broken = write_file(cls.folder.name, "broken.json", "{not json")
        cls.bad_rect = write_file(cls.folder.name, "bad_rect.json",
                                  '{"layers": {"metal1": [[5, 0, 5, 10]]}}')

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def assert_fails(self, args, code, *texts):
        result = run_cli(*args)
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertEqual(result.stdout, "", "nothing may be printed to stdout on failure")
        self.assertTrue(result.stderr.startswith("error:"), result.stderr)
        for text in texts:
            self.assertIn(text, result.stderr)

    # ---- usage errors: exit code 2, and the usage line is shown ----

    def test_no_arguments(self):
        self.assert_fails([], 2, "layout", "usage:")

    def test_no_check_given(self):
        self.assert_fails([self.good], 2, "nothing to check", "usage:")

    def test_unknown_option(self):
        self.assert_fails([self.good, "--bogus"], 2, "--bogus", "usage:")

    def test_option_without_a_value(self):
        self.assert_fails([self.good, "--min-width"], 2, "--min-width", "usage:")
        self.assert_fails([self.good, "--overlap", "metal1"], 2, "--overlap", "usage:")

    def test_value_must_be_a_whole_integer(self):
        self.assert_fails([self.good, "--min-width", "abc"], 2, "abc", "usage:")
        self.assert_fails([self.good, "--min-width", "12x"], 2, "12x", "usage:")
        self.assert_fails([self.good, "--min-spacing", "1.5"], 2, "1.5", "usage:")

    def test_rule_value_out_of_range(self):
        self.assert_fails([self.good, "--min-width", "0"], 2, "Width rule", "usage:")
        self.assert_fails([self.good, "--min-width", "-5"], 2, "Width rule", "usage:")
        self.assert_fails([self.good, "--min-spacing", "2000000001"], 2, "Spacing rule", "usage:")

    def test_overlap_needs_two_different_layers(self):
        self.assert_fails([self.good, "--overlap", "metal1", "metal1"], 2, "two different", "usage:")

    def test_more_than_one_layout_file(self):
        self.assert_fails([self.good, self.good, "--min-width", "50"], 2, "one layout", "usage:")

    def test_same_option_twice(self):
        self.assert_fails([self.good, "--min-width", "50", "--min-width", "60"], 2,
                          "--min-width", "usage:")

    def test_min_spacing_twice(self):
        self.assert_fails([self.good, "--min-spacing", "40", "--min-spacing", "50"], 2,
                          "--min-spacing", "usage:")

    def test_window_cannot_be_combined_with_any_check(self):
        window = ["--window", "metal1", "0", "0", "10", "10"]
        for check in (["--min-spacing", "40"], ["--overlap", "metal1", "via1"]):
            self.assert_fails([self.good, *window, *check], 2, "combined", "usage:")
            self.assert_fails([self.good, *check, *window], 2, "combined", "usage:")  # either order

    def test_window_needs_five_values(self):
        self.assert_fails([self.good, "--window", "metal1", "0", "0"], 2, "--window", "usage:")

    def test_window_values_must_be_integers(self):
        self.assert_fails([self.good, "--window", "metal1", "0", "0", "abc", "10"], 2, "abc", "usage:")

    def test_window_cannot_be_combined_with_checks(self):
        self.assert_fails([self.good, "--window", "metal1", "0", "0", "10", "10",
                           "--min-width", "50"], 2, "--window", "combined", "usage:")

    def test_window_given_twice(self):
        self.assert_fails([self.good, "--window", "metal1", "0", "0", "10", "10",
                           "--window", "via1", "0", "0", "10", "10"], 2, "--window", "usage:")

    def test_window_must_have_a_positive_size(self):
        self.assert_fails([self.good, "--window", "metal1", "10", "0", "0", "10"], 2,
                          "Invalid window", "usage:")
        self.assert_fails([self.good, "--window", "metal1", "5", "0", "5", "10"], 2,
                          "Invalid window", "usage:")

    def test_window_coordinates_out_of_range(self):
        self.assert_fails([self.good, "--window", "metal1", "0", "0", "2000000000", "10"], 2,
                          "Invalid window", "usage:")

    # ---- runtime errors: exit code 1 ----

    def test_window_on_an_unknown_layer(self):
        self.assert_fails([self.good, "--window", "ghost", "0", "0", "10", "10"], 1, "ghost")


    def test_missing_file(self):
        self.assert_fails(["no_such_file.json", "--min-width", "50"], 1, "no_such_file.json")

    def test_invalid_json(self):
        self.assert_fails([self.broken, "--min-width", "50"], 1, "Invalid JSON")

    def test_invalid_rect_names_the_layer(self):
        self.assert_fails([self.bad_rect, "--min-width", "50"], 1, "metal1", "rect 0")

    def test_unknown_layer_name(self):
        self.assert_fails([self.good, "--overlap", "metal1", "nope"], 1, "nope")


if __name__ == "__main__":
    unittest.main()
