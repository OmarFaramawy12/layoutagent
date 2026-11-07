"""Tests for eval/run_eval.py and eval/cases.json. A scripted fake LLM plays the model, so no
network or API key is needed. The tests need the built layoutagent program (the ground truth
comes from the real C++ engine)."""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from agent.tools import ToolResult  # noqa: E402
from eval import run_eval, scoring  # noqa: E402

CLI = os.environ.get("LAYOUTAGENT_CLI", os.path.join(ROOT, "build", "layoutagent"))
CASES_PATH = os.path.join(ROOT, "eval", "cases.json")


def write_cases(folder, document):
    path = os.path.join(folder, "cases.json")
    with open(path, "w") as f:
        json.dump(document, f)
    return path


def good_document(**changes):
    document = {"layout": {"seed": 5, "count": 40},
                "cases": [{"id": "w", "question": "Which shapes are narrower than 50 nm?",
                           "expect": {"tool": "check_min_width", "arguments": {"min_width": 50}}}]}
    document.update(changes)
    return document


class LoadCasesTest(unittest.TestCase):
    def load(self, document):
        with tempfile.TemporaryDirectory() as folder:
            return run_eval.load_cases(write_cases(folder, document))

    def test_loads_the_layout_settings_and_cases(self):
        layout, cases = self.load(good_document())
        self.assertEqual(layout, {"seed": 5, "count": 40})
        self.assertEqual([c["id"] for c in cases], ["w"])

    def test_a_missing_file(self):
        with self.assertRaises(ValueError):
            run_eval.load_cases("no_such_cases.json")

    def test_rejects_duplicate_ids(self):
        case = good_document()["cases"][0]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.load(good_document(cases=[case, case]))

    def test_rejects_a_case_without_a_question(self):
        case = dict(good_document()["cases"][0], question="")
        with self.assertRaisesRegex(ValueError, "question"):
            self.load(good_document(cases=[case]))

    def test_rejects_an_unknown_tool(self):
        case = dict(good_document()["cases"][0], expect={"tool": "check_everything", "arguments": {}})
        with self.assertRaisesRegex(ValueError, "check_everything"):
            self.load(good_document(cases=[case]))

    def test_a_tool_case_needs_arguments(self):
        case = dict(good_document()["cases"][0], expect={"tool": "check_min_width"})
        with self.assertRaisesRegex(ValueError, "arguments"):
            self.load(good_document(cases=[case]))

    def test_no_cases(self):
        with self.assertRaisesRegex(ValueError, "no cases"):
            self.load(good_document(cases=[]))

    def test_the_layout_settings_are_needed(self):
        with self.assertRaisesRegex(ValueError, "layout"):
            self.load({"cases": good_document()["cases"]})


class StubTools:
    """Returns one canned tool answer."""

    def __init__(self, content, is_error=False):
        self.result = ToolResult(json.dumps(content), is_error)

    def run(self, name, arguments):
        return self.result


class ExpectedAnswerTest(unittest.TestCase):
    EXPECT = {"tool": "check_min_width", "arguments": {"min_width": 50}}

    def test_violations_give_the_count_and_all_shape_ids(self):
        tools = StubTools({"total_count": 2, "returned_count": 2, "truncated": False, "violations": [
            {"first_shape_id": 5, "second_shape_id": None},
            {"first_shape_id": 7, "second_shape_id": 9}]})
        self.assertEqual(run_eval.expected_answer(tools, self.EXPECT), (2, {5, 7, 9}))

    def test_a_window_query_gives_its_shape_ids(self):
        tools = StubTools({"total_count": 2, "returned_count": 2, "truncated": False,
                           "shape_ids": [3, 4]})
        self.assertEqual(run_eval.expected_answer(tools, self.EXPECT), (2, {3, 4}))

    def test_a_truncated_answer_has_no_complete_id_list(self):
        tools = StubTools({"total_count": 300, "returned_count": 50, "truncated": True,
                           "shape_ids": [3, 4]})
        self.assertEqual(run_eval.expected_answer(tools, self.EXPECT), (300, None))

    def test_no_violations_gives_no_ids(self):
        tools = StubTools({"total_count": 0, "returned_count": 0, "truncated": False,
                           "violations": []})
        self.assertEqual(run_eval.expected_answer(tools, self.EXPECT), (0, None))

    def test_a_case_that_expects_no_tool(self):
        self.assertEqual(run_eval.expected_answer(StubTools({}), {"tool": None}), (None, None))

    def test_a_failing_expected_call_is_reported(self):
        with self.assertRaisesRegex(ValueError, "failed"):
            run_eval.expected_answer(StubTools({}, is_error=True), self.EXPECT)


class OracleLLM:
    """Always behaves perfectly: calls the expected tool, then reports the engine's count."""

    def __init__(self, cases):
        self.by_question = {c["question"]: c["expect"] for c in cases}
        self.total_tokens = 123

    def chat(self, messages, tools):
        expect = self.by_question[messages[1]["content"]]
        if messages[-1]["role"] == "tool":
            count = json.loads(messages[-1]["content"])["total_count"]
            return {"role": "assistant", "content": "Found %d." % count}
        if expect["tool"] is None:
            return {"role": "assistant", "content": "Which value should I use?"}
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": expect["tool"], "arguments": json.dumps(expect["arguments"])}}]}


class LazyLLM:
    """Never calls a tool."""

    def chat(self, messages, tools):
        return {"role": "assistant", "content": "I do not know."}


class ListingLLM(OracleLLM):
    """Answers a "which" question the natural way: lists the IDs and never says the count."""

    def chat(self, messages, tools):
        if messages[-1]["role"] != "tool":
            return super().chat(messages, tools)
        answer = json.loads(messages[-1]["content"])
        ids = set(answer.get("shape_ids", []))
        for violation in answer.get("violations", []):
            ids |= {violation["first_shape_id"], violation["second_shape_id"]} - {None}
        return {"role": "assistant", "content": "IDs: " + ", ".join(map(str, sorted(ids)))}


class BrokenLLM:
    def chat(self, messages, tools):
        raise run_eval.LLMError("the LLM returned HTTP 401: invalid key")


@unittest.skipUnless(os.path.isfile(CLI), "the layoutagent program is not built")
class RealCasesFileTest(unittest.TestCase):
    """eval/cases.json itself, checked against the real engine."""

    def test_the_file_is_valid(self):
        layout, cases = run_eval.load_cases(CASES_PATH)
        self.assertGreaterEqual(len(cases), 8)
        self.assertIn(None, [c["expect"]["tool"] for c in cases])  # at least one "ask" case
        self.assertIn(0, self.counts(layout, cases))               # at least one "none found" case

    def test_no_count_or_id_equals_a_number_in_its_question(self):
        # The scoring looks for the count (or the IDs) anywhere in the answer, so a count or
        # ID that is also in the question (for example "50 nm" and 50 violations) could be
        # matched by accident, for instance by an answer that just repeats the question.
        layout, cases = run_eval.load_cases(CASES_PATH)
        for case, (count, ids) in zip(cases, self.answers(layout, cases)):
            in_question = scoring.numbers_in(case["question"])
            if count not in (None, 0):
                self.assertNotIn(count, in_question, case["id"])
            self.assertFalse((ids or set()) & in_question, case["id"])

    def counts(self, layout, cases):
        return [count for count, _ in self.answers(layout, cases)]

    def answers(self, layout, cases):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.dict(os.environ, {"LAYOUTAGENT_CLI": CLI}):
                tools = run_eval.make_tools(layout, folder)
                return [run_eval.expected_answer(tools, c["expect"]) for c in cases]


@unittest.skipUnless(os.path.isfile(CLI), "the layoutagent program is not built")
class MainTest(unittest.TestCase):
    def setUp(self):
        environment = mock.patch.dict(os.environ, {"LAYOUTAGENT_CLI": CLI})
        environment.start()
        self.addCleanup(environment.stop)
        _, self.cases = run_eval.load_cases(CASES_PATH)

    def run_main(self, argv, llm):
        out, err = io.StringIO(), io.StringIO()
        code = run_eval.main(argv, llm=llm, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_a_perfect_model_passes_every_case(self):
        code, out, err = self.run_main([], OracleLLM(self.cases))
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Passed %d of %d cases" % (len(self.cases), len(self.cases)), out)
        self.assertIn("Tokens used: 123", out)
        for case in self.cases:
            self.assertIn(case["id"], out)

    def test_listing_the_ids_without_the_count_passes(self):
        code, out, _ = self.run_main(["--only", "width_basic", "window_basic"],
                                     ListingLLM(self.cases))
        self.assertEqual(code, 0)
        self.assertIn("Passed 2 of 2 cases", out)

    def test_a_model_that_never_calls_tools_fails_the_tool_cases(self):
        code, out, err = self.run_main([], LazyLLM())
        ask_cases = len([c for c in self.cases if c["expect"]["tool"] is None])
        self.assertEqual(code, 0)  # the evaluation ran; the failures are in the report
        self.assertIn("Passed %d of %d cases" % (ask_cases, len(self.cases)), out)
        self.assertIn("FAIL", out)

    def test_a_failed_case_shows_the_calls_that_were_made(self):
        _, out, _ = self.run_main(["--only", self.cases[0]["id"]], LazyLLM())
        self.assertIn("calls: (none)", out)

    def test_only_runs_the_named_cases(self):
        wanted = [self.cases[0]["id"], self.cases[1]["id"]]
        code, out, _ = self.run_main(["--only"] + wanted, OracleLLM(self.cases))
        self.assertEqual(code, 0)
        self.assertIn("Passed 2 of 2 cases", out)

    def test_only_with_an_unknown_id(self):
        code, out, err = self.run_main(["--only", "nope"], OracleLLM(self.cases))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("nope", err)

    def test_an_llm_error_stops_the_run(self):
        code, out, err = self.run_main([], BrokenLLM())
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("error:"), err)
        self.assertIn("401", err)

    def test_missing_llm_settings_are_reported(self):
        with mock.patch.dict(os.environ, {"LAYOUTAGENT_CLI": CLI}, clear=True):
            code, out, err = self.run_main([], None)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("LLM_API_KEY", err)

    def test_a_bad_cases_file(self):
        code, out, err = self.run_main(["--cases", "no_such_cases.json"], LazyLLM())
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error:"), err)


if __name__ == "__main__":
    unittest.main()
