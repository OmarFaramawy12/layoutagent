"""Tests for agent/tools.py (the tools the LLM can call). No network and no API key needed.

Most tests use a tiny fake "layoutagent" program, so failures (bad output, timeouts, exit
codes) can be tested exactly. RealProgramTest runs the real built program on generated
layouts. Run through ctest, or by hand with:

    LAYOUTAGENT_CLI=build/layoutagent python3 -m unittest discover -s tests -p "test_agent_tools.py"
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from agent import tools  # noqa: E402
import gen_layout  # noqa: E402

CLI = os.environ.get("LAYOUTAGENT_CLI", os.path.join(ROOT, "build", "layoutagent"))

LAYOUT_TEXT = '{"layers": {"metal1": [[0, 0, 100, 100]], "via1": [[10, 10, 40, 40]], "metal2": []}}'
LAYER_NAMES = ["metal1", "via1", "metal2"]  # file order, deliberately not alphabetical

# The fake program: waits, records its arguments, prints canned output, exits with a canned code.
FAKE_PROGRAM = """
import json, sys, time
time.sleep({sleep})
with open({record!r}, "w") as f:
    json.dump(sys.argv[1:], f)
sys.stdout.write({stdout!r})
sys.stderr.write({stderr!r})
sys.exit({code})
"""


def violation(shape_id, layer="metal1", kind="min_width"):
    return {"type": kind, "layer_a": layer, "layer_b": layer, "first_shape_id": shape_id,
            "second_shape_id": None, "measured": 10, "required": 50}


class FakeProgramTestCase(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.folder = self._folder.name
        self.layout_path = os.path.join(self.folder, "layout.json")
        with open(self.layout_path, "w") as f:
            f.write(LAYOUT_TEXT)
        self.record_path = os.path.join(self.folder, "arguments.json")

    def make_tools(self, violations=(), stderr="", code=0, sleep=0, timeout=10, stdout=None):
        """DrcTools that runs a fake program printing the given violations."""
        if stdout is None:
            stdout = json.dumps({"violations": list(violations)})
        script_path = os.path.join(self.folder, "fake_layoutagent.py")
        with open(script_path, "w") as f:
            f.write(FAKE_PROGRAM.format(sleep=sleep, record=self.record_path, stdout=stdout,
                                        stderr=stderr, code=code))
        return tools.DrcTools(self.layout_path, program=[sys.executable, script_path],
                              timeout_seconds=timeout)

    def program_arguments(self):
        with open(self.record_path) as f:
            return json.load(f)

    def program_was_run(self):
        return os.path.exists(self.record_path)


class DefinitionsTest(FakeProgramTestCase):
    def test_the_tools_with_descriptions_and_schemas(self):
        definitions = self.make_tools().definitions()
        self.assertEqual([d["name"] for d in definitions],
                         ["check_min_width", "check_min_spacing", "check_overlap", "window_query",
                          "get_shape"])
        for definition in definitions:
            self.assertTrue(definition["description"].strip())
            schema = definition["input_schema"]
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
            self.assertTrue(set(schema["required"]) <= set(schema["properties"]))

    def test_layer_choices_come_from_the_layout_file(self):
        by_name = {d["name"]: d["input_schema"]["properties"]
                   for d in self.make_tools().definitions()}
        self.assertEqual(by_name["check_min_width"]["layer"]["enum"], LAYER_NAMES)
        self.assertEqual(by_name["check_min_spacing"]["layer"]["enum"], LAYER_NAMES)
        self.assertEqual(by_name["check_overlap"]["layer_a"]["enum"], LAYER_NAMES)
        self.assertEqual(by_name["check_overlap"]["layer_b"]["enum"], LAYER_NAMES)
        self.assertEqual(by_name["window_query"]["layer"]["enum"], LAYER_NAMES)

    def test_rule_values_are_required_integers(self):
        by_name = {d["name"]: d["input_schema"] for d in self.make_tools().definitions()}
        self.assertEqual(by_name["check_min_width"]["required"], ["min_width"])
        self.assertEqual(by_name["check_min_width"]["properties"]["min_width"]["type"], "integer")
        self.assertEqual(by_name["check_min_spacing"]["required"], ["min_spacing"])
        self.assertEqual(by_name["check_overlap"]["required"], ["layer_a", "layer_b"])

    def test_window_tool_needs_a_layer_and_four_integers(self):
        schema = {d["name"]: d["input_schema"] for d in self.make_tools().definitions()}["window_query"]
        self.assertEqual(schema["required"], ["layer", "x1", "y1", "x2", "y2"])
        for key in ("x1", "y1", "x2", "y2"):
            self.assertEqual(schema["properties"][key]["type"], "integer")

    def test_get_shape_needs_one_integer_id(self):
        schema = {d["name"]: d["input_schema"] for d in self.make_tools().definitions()}["get_shape"]
        self.assertEqual(schema["required"], ["shape_id"])
        self.assertEqual(schema["properties"]["shape_id"]["type"], "integer")

    def test_definitions_can_be_sent_as_json(self):
        json.dumps(self.make_tools().definitions())  # must not raise


class RunToolsTest(FakeProgramTestCase):
    def test_min_width_passes_the_right_arguments(self):
        result = self.make_tools([violation(3)]).run("check_min_width", {"min_width": 50})
        self.assertFalse(result.is_error)
        self.assertEqual(self.program_arguments(), [self.layout_path, "--min-width", "50"])

    def test_min_spacing_passes_the_right_arguments(self):
        self.make_tools().run("check_min_spacing", {"min_spacing": 40})
        self.assertEqual(self.program_arguments(), [self.layout_path, "--min-spacing", "40"])

    def test_overlap_passes_the_right_arguments(self):
        self.make_tools().run("check_overlap", {"layer_a": "metal1", "layer_b": "via1"})
        self.assertEqual(self.program_arguments(),
                         [self.layout_path, "--overlap", "metal1", "via1"])

    def test_the_answer_lists_the_violations_and_their_count(self):
        result = self.make_tools([violation(3), violation(5)]).run("check_min_width",
                                                                   {"min_width": 50})
        answer = json.loads(result.content)
        self.assertEqual(answer["total_count"], 2)
        self.assertEqual(answer["returned_count"], 2)
        self.assertFalse(answer["truncated"])
        self.assertEqual(answer["violations"], [violation(3), violation(5)])

    def test_no_violations(self):
        answer = json.loads(self.make_tools([]).run("check_min_width", {"min_width": 50}).content)
        self.assertEqual(answer["total_count"], 0)
        self.assertEqual(answer["violations"], [])

    def test_long_answers_are_cut_but_the_total_is_kept(self):
        violations = [violation(i) for i in range(60)]
        result = self.make_tools(violations).run("check_min_width", {"min_width": 50})
        answer = json.loads(result.content)
        self.assertEqual(answer["total_count"], 60)
        self.assertEqual(answer["returned_count"], tools.MAX_VIOLATIONS_RETURNED)
        self.assertTrue(answer["truncated"])
        self.assertEqual(answer["violations"], violations[:tools.MAX_VIOLATIONS_RETURNED])

    def test_layer_filter_keeps_only_that_layer_and_counts_only_those(self):
        violations = [violation(0, "metal1"), violation(1, "metal2"), violation(2, "metal1")]
        result = self.make_tools(violations).run("check_min_width",
                                                 {"min_width": 50, "layer": "metal1"})
        answer = json.loads(result.content)
        self.assertEqual(answer["total_count"], 2)
        self.assertEqual([v["first_shape_id"] for v in answer["violations"]], [0, 2])

    def test_a_null_layer_means_no_filter(self):
        violations = [violation(0, "metal1"), violation(1, "metal2")]
        result = self.make_tools(violations).run("check_min_spacing",
                                                 {"min_spacing": 40, "layer": None})
        self.assertEqual(json.loads(result.content)["total_count"], 2)


class WindowToolTest(FakeProgramTestCase):
    def arguments(self, **changes):
        arguments = {"layer": "metal1", "x1": 0, "y1": 0, "x2": 100, "y2": 100}
        arguments.update(changes)
        return arguments

    def make_window_tools(self, shape_ids, **kwargs):
        return self.make_tools(stdout=json.dumps({"shape_ids": list(shape_ids)}), **kwargs)

    def test_passes_the_right_arguments(self):
        result = self.make_window_tools([1]).run("window_query", self.arguments(x1=-5, y2=70))
        self.assertFalse(result.is_error)
        self.assertEqual(self.program_arguments(),
                         [self.layout_path, "--window", "metal1", "-5", "0", "100", "70"])

    def test_the_answer_lists_the_shape_ids_and_their_count(self):
        result = self.make_window_tools([4, 9, 2]).run("window_query", self.arguments())
        self.assertEqual(json.loads(result.content),
                         {"total_count": 3, "returned_count": 3, "truncated": False,
                          "shape_ids": [4, 9, 2]})

    def test_an_empty_window(self):
        answer = json.loads(self.make_window_tools([]).run("window_query", self.arguments()).content)
        self.assertEqual(answer["total_count"], 0)
        self.assertEqual(answer["shape_ids"], [])

    def test_long_lists_are_cut_but_the_total_is_kept(self):
        ids = list(range(250))
        answer = json.loads(self.make_window_tools(ids).run("window_query", self.arguments()).content)
        self.assertEqual(answer["total_count"], 250)
        self.assertEqual(answer["returned_count"], tools.MAX_SHAPE_IDS_RETURNED)
        self.assertTrue(answer["truncated"])
        self.assertEqual(answer["shape_ids"], ids[:tools.MAX_SHAPE_IDS_RETURNED])

    def test_bad_arguments_never_reach_the_program(self):
        bad_calls = [
            {"layer": "metal1", "x1": 0, "y1": 0, "x2": 100},               # y2 missing
            self.arguments(x2="100"),                                       # not an integer
            self.arguments(y1=1.5),
            self.arguments(layer="metal9"),                                 # unknown layer
            {"x1": 0, "y1": 0, "x2": 100, "y2": 100},                       # layer missing
            dict(self.arguments(), z=1),                                    # extra argument
        ]
        for arguments in bad_calls:
            with self.subTest(arguments=arguments):
                result = self.make_window_tools([1]).run("window_query", arguments)
                self.assertTrue(result.is_error, result.content)
                self.assertFalse(self.program_was_run())

    def test_an_engine_error_returns_only_the_error_line(self):
        stderr = "error: Invalid window: need x1 < x2 and y1 < y2, got x1=10\nusage: layoutagent ...\n"
        result = self.make_tools(stderr=stderr, code=2).run("window_query", self.arguments(x1=10, x2=0))
        self.assertTrue(result.is_error)
        self.assertEqual(result.content, "error: Invalid window: need x1 < x2 and y1 < y2, got x1=10")


class GetShapeToolTest(FakeProgramTestCase):
    SHAPE = {"id": 7, "layer": "via1", "x1": -10, "y1": 0, "x2": 40, "y2": 25}

    def make_shape_tools(self, shape=None, **kwargs):
        return self.make_tools(stdout=json.dumps({"shape": shape or self.SHAPE}), **kwargs)

    def test_passes_the_id_to_the_program(self):
        result = self.make_shape_tools().run("get_shape", {"shape_id": 7})
        self.assertFalse(result.is_error)
        self.assertEqual(self.program_arguments(), [self.layout_path, "--shape", "7"])

    def test_the_answer_is_the_shape(self):
        result = self.make_shape_tools().run("get_shape", {"shape_id": 7})
        self.assertEqual(json.loads(result.content), self.SHAPE)

    def test_bad_arguments_never_reach_the_program(self):
        for arguments in ({}, {"shape_id": "7"}, {"shape_id": 1.5}, {"shape_id": None},
                          {"shape_id": True}, {"shape_id": 7, "layer": "metal1"}):
            with self.subTest(arguments=arguments):
                result = self.make_shape_tools().run("get_shape", arguments)
                self.assertTrue(result.is_error, result.content)
                self.assertFalse(self.program_was_run())

    def test_an_unknown_id_returns_only_the_error_line(self):
        stderr = "error: Unknown shape id: 999\n"
        result = self.make_tools(stderr=stderr, code=1).run("get_shape", {"shape_id": 999})
        self.assertTrue(result.is_error)
        self.assertEqual(result.content, "error: Unknown shape id: 999")


class BadArgumentsTest(FakeProgramTestCase):
    """Mistakes by the LLM: reported back as errors, and the program is never run."""

    def assert_error(self, name, arguments, *texts):
        result = self.make_tools().run(name, arguments)
        self.assertTrue(result.is_error, result.content)
        self.assertFalse(self.program_was_run(), "the program must not run for bad arguments")
        for text in texts:
            self.assertIn(text, result.content)

    def test_unknown_tool(self):
        self.assert_error("check_everything", {}, "check_everything", "check_min_width")

    def test_missing_argument(self):
        self.assert_error("check_min_width", {}, "min_width")

    def test_unexpected_argument(self):
        self.assert_error("check_min_width", {"min_width": 50, "colour": "red"}, "colour")

    def test_arguments_must_be_an_object(self):
        self.assert_error("check_min_width", [50], "arguments")

    def test_rule_value_must_be_an_integer(self):
        for bad in ("50", 5.5, True, None, [50]):
            with self.subTest(value=bad):
                self.assert_error("check_min_width", {"min_width": bad}, "min_width", "integer")

    def test_unknown_layer(self):
        self.assert_error("check_min_width", {"min_width": 50, "layer": "metal9"},
                          "metal9", "metal1", "via1", "metal2")
        self.assert_error("check_overlap", {"layer_a": "metal1", "layer_b": "nope"}, "nope")

    def test_layer_must_be_a_string(self):
        self.assert_error("check_min_spacing", {"min_spacing": 40, "layer": 1}, "layer")


class EngineFailureTest(FakeProgramTestCase):
    def test_a_usage_error_returns_only_the_error_line(self):
        stderr = "error: Width rule must be in (0, 2000000000], got 0\nusage: layoutagent <layout.json> ...\n"
        result = self.make_tools(stderr=stderr, code=2).run("check_min_width", {"min_width": 0})
        self.assertTrue(result.is_error)
        self.assertEqual(result.content, "error: Width rule must be in (0, 2000000000], got 0")

    def test_a_runtime_error_returns_the_message(self):
        result = self.make_tools(stderr="error: Unknown layer name: x\n", code=1).run(
            "check_overlap", {"layer_a": "metal1", "layer_b": "via1"})
        self.assertTrue(result.is_error)
        self.assertIn("Unknown layer name", result.content)

    def test_a_failure_without_a_message_still_says_something(self):
        result = self.make_tools(code=3).run("check_min_width", {"min_width": 50})
        self.assertTrue(result.is_error)
        self.assertIn("3", result.content)

    def test_a_slow_program_is_stopped(self):
        result = self.make_tools(sleep=5, timeout=0.5).run("check_min_width", {"min_width": 50})
        self.assertTrue(result.is_error)
        self.assertIn("longer than", result.content)

    def test_output_that_is_not_json_is_a_host_problem_not_a_tool_error(self):
        tools_ = self.make_tools(stdout="this is not json")
        with self.assertRaises(RuntimeError):
            tools_.run("check_min_width", {"min_width": 50})


class ConstructionTest(FakeProgramTestCase):
    def test_missing_layout_file(self):
        with self.assertRaises(FileNotFoundError):
            tools.DrcTools(os.path.join(self.folder, "nope.json"), program=["unused"])

    def test_layout_without_layers(self):
        for text in ('{"shapes": []}', '{"layers": {}}', "[]"):
            with self.subTest(text=text):
                with open(self.layout_path, "w") as f:
                    f.write(text)
                with self.assertRaises(ValueError):
                    tools.DrcTools(self.layout_path, program=["unused"])

    def test_duplicate_layer_name(self):
        # Python's json module keeps the last of two equal keys without a word; the C++ loader
        # rejects such a file, so the tool layer must not accept it either.
        with open(self.layout_path, "w") as f:
            f.write('{"layers": {"metal1": [[0, 0, 10, 10]], "metal1": [[20, 0, 30, 10]]}}')
        with self.assertRaisesRegex(ValueError, "Duplicate key 'metal1'"):
            tools.DrcTools(self.layout_path, program=["unused"])

    def test_the_same_key_in_different_objects_is_fine(self):
        with open(self.layout_path, "w") as f:
            f.write('{"layers": {"metal1": []}, "meta": {"metal1": 1}}')
        self.assertEqual(tools.DrcTools(self.layout_path, program=["unused"]).layer_names, ["metal1"])

    def test_layout_that_is_not_json(self):
        with open(self.layout_path, "w") as f:
            f.write("{not json")
        with self.assertRaises(ValueError):
            tools.DrcTools(self.layout_path, program=["unused"])

    def make_program(self, *parts):
        """Creates an empty file build/<parts> under the temporary folder; returns its path."""
        path = os.path.join(self.folder, "build", *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w"):
            pass
        return path

    def default_path(self):
        with mock.patch.dict(os.environ, clear=True):  # no LAYOUTAGENT_CLI
            return tools.default_program_path(self.folder)

    def test_default_path_finds_the_linux_program(self):
        path = self.make_program("layoutagent")
        self.assertEqual(self.default_path(), path)

    def test_default_path_finds_the_windows_program(self):
        path = self.make_program("layoutagent.exe")
        self.assertEqual(self.default_path(), path)

    def test_default_path_finds_a_visual_studio_build(self):
        # The Visual Studio generator puts the program in build/<configuration>/.
        path = self.make_program("Release", "layoutagent.exe")
        self.assertEqual(self.default_path(), path)

    def test_default_path_takes_the_newest_build(self):
        old = self.make_program("Debug", "layoutagent.exe")
        new = self.make_program("Release", "layoutagent.exe")
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (2_000_000, 2_000_000))
        self.assertEqual(self.default_path(), new)

    def test_default_path_without_a_build_names_the_plain_path(self):
        # Nothing exists: the path is still given, so the error message says where it looked.
        self.assertEqual(self.default_path(), os.path.join(self.folder, "build", "layoutagent"))

    def test_the_environment_variable_wins(self):
        self.make_program("layoutagent")
        with mock.patch.dict(os.environ, {"LAYOUTAGENT_CLI": "/somewhere/else"}):
            self.assertEqual(tools.default_program_path(self.folder), "/somewhere/else")

    def test_default_program_must_exist(self):
        with mock.patch.dict(os.environ, {"LAYOUTAGENT_CLI": os.path.join(self.folder, "missing")}):
            with self.assertRaises(FileNotFoundError):
                tools.DrcTools(self.layout_path)


@unittest.skipUnless(os.path.isfile(CLI), "the layoutagent program is not built")
class RealProgramTest(unittest.TestCase):
    """The tools against the real C++ program and the generator's expected answers."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        prefix = os.path.join(cls.folder.name, "case")
        with contextlib.redirect_stdout(io.StringIO()):
            gen_layout.main(["--seed", "5", "--count", "200", "--out", prefix])
        with open(prefix + ".expected.json") as f:
            cls.expected = json.load(f)["violations"]
        with open(prefix + ".json") as f:
            cls.layers = json.load(f)["layers"]
        cls.tools = tools.DrcTools(prefix + ".json", program=[CLI])

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def expected_count(self, kind, layer=None):
        return len([v for v in self.expected
                    if v["type"] == kind and (layer is None or v["layer_a"] == layer)])

    def check_counts(self, result, expected_total):
        self.assertFalse(result.is_error, result.content)
        answer = json.loads(result.content)
        self.assertEqual(answer["total_count"], expected_total)
        self.assertEqual(answer["returned_count"],
                         min(expected_total, tools.MAX_VIOLATIONS_RETURNED))
        self.assertEqual(answer["truncated"], expected_total > tools.MAX_VIOLATIONS_RETURNED)
        return answer

    def test_min_width_matches_the_expected_answers(self):
        answer = self.check_counts(self.tools.run("check_min_width", {"min_width": 50}),
                                   self.expected_count("min_width"))
        self.assertTrue(all(v["type"] == "min_width" for v in answer["violations"]))

    def test_min_spacing_with_a_layer_filter(self):
        answer = self.check_counts(
            self.tools.run("check_min_spacing", {"min_spacing": 40, "layer": "metal1"}),
            self.expected_count("min_spacing", "metal1"))
        self.assertTrue(all(v["layer_a"] == "metal1" for v in answer["violations"]))

    def test_overlap_matches_the_expected_answers(self):
        self.check_counts(
            self.tools.run("check_overlap", {"layer_a": "metal1", "layer_b": "via1"}),
            self.expected_count("overlap"))

    def test_get_shape_matches_the_layout_file(self):
        # The ID rule from the README: IDs count 0, 1, 2, ... layer by layer, in file order.
        shapes = [(layer, rect) for layer, rects in self.layers.items() for rect in rects]
        for shape_id in (0, 1, len(shapes) // 2, len(shapes) - 1):
            with self.subTest(shape_id=shape_id):
                layer, rect = shapes[shape_id]
                result = self.tools.run("get_shape", {"shape_id": shape_id})
                self.assertFalse(result.is_error, result.content)
                self.assertEqual(json.loads(result.content), {
                    "id": shape_id, "layer": layer,
                    "x1": rect[0], "y1": rect[1], "x2": rect[2], "y2": rect[3]})

    def test_get_shape_with_an_unknown_id_is_an_error_for_the_llm(self):
        result = self.tools.run("get_shape", {"shape_id": 10 ** 6})
        self.assertTrue(result.is_error)
        self.assertIn("Unknown shape id", result.content)
        self.assertNotIn("usage", result.content)

    def test_an_engine_error_reaches_the_llm_without_the_usage_text(self):
        result = self.tools.run("check_min_width", {"min_width": 0})
        self.assertTrue(result.is_error)
        self.assertIn("Width rule", result.content)
        self.assertNotIn("usage", result.content)

    def test_a_window_over_everything_returns_every_shape_of_the_layer(self):
        everything = {"x1": -100000, "y1": -100000, "x2": 100000, "y2": 100000}
        result = self.tools.run("window_query", dict(everything, layer="via1"))
        self.assertFalse(result.is_error, result.content)
        answer = json.loads(result.content)
        count = len(self.layers["via1"])
        first_id = len(self.layers["metal1"])  # via1 comes after metal1 in the file
        self.assertEqual(answer["total_count"], count)
        self.assertEqual(answer["shape_ids"], list(range(first_id, first_id + count)))

    def test_an_invalid_window_reaches_the_llm_as_a_clear_error(self):
        result = self.tools.run("window_query",
                                {"layer": "metal1", "x1": 10, "y1": 0, "x2": 0, "y2": 10})
        self.assertTrue(result.is_error)
        self.assertIn("Invalid window", result.content)
        self.assertNotIn("usage", result.content)


if __name__ == "__main__":
    unittest.main()
