"""Tests for eval/scoring.py: the deterministic scoring of the agent's behaviour.
No network, no API key and no layoutagent program needed."""

import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from agent.agent import ToolCall  # noqa: E402
from eval import scoring  # noqa: E402

WIDTH_50 = ToolCall("check_min_width", {"min_width": 50}, False)


class NumbersInTest(unittest.TestCase):
    def test_finds_whole_numbers(self):
        self.assertEqual(scoring.numbers_in("There are 18 shapes and 3 layers."), {18, 3})

    def test_thousands_separators(self):
        self.assertEqual(scoring.numbers_in("1,234 violations"), {1234})

    def test_a_list_of_ids_is_not_read_as_thousands(self):
        self.assertEqual(scoring.numbers_in("IDs: 19, 39,46"), {19, 39, 46})

    def test_decimals_are_ignored(self):
        self.assertEqual(scoring.numbers_in("about 2.5 nm, count 7"), {7})

    def test_part_of_a_word_still_counts_as_a_number(self):
        self.assertEqual(scoring.numbers_in("metal1 has 4"), {1, 4})  # known weakness, see module

    def test_no_numbers(self):
        self.assertEqual(scoring.numbers_in("none at all"), set())


class SameArgumentsTest(unittest.TestCase):
    def test_equal_arguments(self):
        self.assertTrue(scoring.same_arguments("check_min_width", {"min_width": 50}, {"min_width": 50}))

    def test_different_value(self):
        self.assertFalse(scoring.same_arguments("check_min_width", {"min_width": 50}, {"min_width": 60}))

    def test_extra_argument_is_different(self):
        self.assertFalse(scoring.same_arguments("check_min_width", {"min_width": 50},
                                                {"min_width": 50, "layer": "metal1"}))

    def test_overlap_layers_can_come_in_either_order(self):
        self.assertTrue(scoring.same_arguments("check_overlap", {"layer_a": "metal1", "layer_b": "via1"},
                                               {"layer_a": "via1", "layer_b": "metal1"}))

    def test_other_tools_care_about_order(self):
        self.assertFalse(scoring.same_arguments("window_query", {"layer": "a", "x1": 0}, {"layer": "b", "x1": 0}))


class AnswerMentionsCountTest(unittest.TestCase):
    def test_count_present(self):
        self.assertTrue(scoring.answer_mentions_count("Found 18 narrow shapes.", 18))

    def test_count_absent(self):
        self.assertFalse(scoring.answer_mentions_count("Found 17 narrow shapes.", 18))

    def test_a_longer_number_is_not_a_match(self):
        self.assertFalse(scoring.answer_mentions_count("Found 180 narrow shapes.", 18))

    def test_zero_accepts_words(self):
        for text in ("There are no violations.", "None found.", "Zero shapes.", "Count: 0"):
            self.assertTrue(scoring.answer_mentions_count(text, 0), text)

    def test_zero_rejects_a_nonzero_answer(self):
        self.assertFalse(scoring.answer_mentions_count("Found 5 violations.", 0))


class AnswerListsIdsTest(unittest.TestCase):
    def test_all_ids_listed(self):
        self.assertTrue(scoring.answer_lists_ids("IDs: 19, 39 and 46.", {19, 39, 46}))

    def test_a_missing_id_fails(self):
        self.assertFalse(scoring.answer_lists_ids("IDs: 19 and 39.", {19, 39, 46}))

    def test_extra_numbers_are_fine(self):
        self.assertTrue(scoring.answer_lists_ids("19, 39 (2 shapes, 50 nm)", {19, 39}))

    def test_nothing_to_check_without_ids(self):
        self.assertFalse(scoring.answer_lists_ids("anything", None))
        self.assertFalse(scoring.answer_lists_ids("anything", set()))


class ScoreCaseTest(unittest.TestCase):
    CASE = {"id": "width", "expect": {"tool": "check_min_width", "arguments": {"min_width": 50}}}

    def score(self, calls, answer="Found 18 shapes.", finished=True, case=None, count=18,
              ids=None):
        return scoring.score_case(case or self.CASE, calls, answer, finished, count, ids)

    def test_listing_every_id_is_enough_without_the_count(self):
        score = self.score([WIDTH_50], answer="Shapes 19, 39 and 46.", ids={19, 39, 46})
        self.assertTrue(score.answer_ok)
        self.assertTrue(score.passed)

    def test_listing_only_some_ids_without_the_count_fails(self):
        self.assertFalse(self.score([WIDTH_50], answer="Shapes 19 and 39.", ids={19, 39, 46}).answer_ok)

    def test_the_right_count_is_enough_even_without_the_ids(self):
        self.assertTrue(self.score([WIDTH_50], answer="18 shapes.", ids={19, 39, 46}).answer_ok)

    def test_a_wrong_count_and_no_ids_fails(self):
        self.assertFalse(self.score([WIDTH_50], answer="17 shapes.", ids={19, 39, 46}).answer_ok)

    def test_everything_right_passes(self):
        score = self.score([WIDTH_50])
        self.assertEqual((score.case_id, score.tool_ok, score.answer_ok, score.finished, score.passed),
                         ("width", True, True, True, True))

    def test_wrong_arguments_fail_the_tool_check_only(self):
        score = self.score([ToolCall("check_min_width", {"min_width": 60}, False)])
        self.assertFalse(score.tool_ok)
        self.assertTrue(score.answer_ok)
        self.assertFalse(score.passed)

    def test_wrong_tool_fails(self):
        self.assertFalse(self.score([ToolCall("check_min_spacing", {"min_spacing": 50}, False)]).tool_ok)

    def test_no_tool_call_fails_when_one_is_expected(self):
        self.assertFalse(self.score([]).tool_ok)

    def test_a_failed_call_does_not_count(self):
        self.assertFalse(self.score([ToolCall("check_min_width", {"min_width": 50}, True)]).tool_ok)

    def test_a_retry_after_a_failed_call_counts(self):
        bad = ToolCall("check_min_width", {"min_width": "50"}, True)
        self.assertTrue(self.score([bad, WIDTH_50]).tool_ok)

    def test_extra_calls_are_allowed(self):
        other = ToolCall("check_min_spacing", {"min_spacing": 40}, False)
        self.assertTrue(self.score([other, WIDTH_50]).tool_ok)

    def test_wrong_count_in_the_answer_fails(self):
        score = self.score([WIDTH_50], answer="Found 17 shapes.")
        self.assertTrue(score.tool_ok)
        self.assertFalse(score.answer_ok)
        self.assertFalse(score.passed)

    def test_an_unfinished_run_fails_even_if_the_calls_were_right(self):
        score = self.score([WIDTH_50], finished=False)
        self.assertTrue(score.tool_ok)
        self.assertFalse(score.passed)

    def test_a_case_with_no_expected_count_skips_the_answer_check(self):
        score = self.score([WIDTH_50], answer="whatever", count=None)
        self.assertTrue(score.answer_ok)
        self.assertTrue(score.passed)

    def test_a_case_that_expects_no_tool_passes_without_calls(self):
        case = {"id": "ask", "expect": {"tool": None}}
        self.assertTrue(self.score([], answer="Which width?", case=case, count=None).passed)

    def test_a_case_that_expects_no_tool_fails_when_a_tool_is_called(self):
        case = {"id": "ask", "expect": {"tool": None}}
        score = self.score([WIDTH_50], answer="Which width?", case=case, count=None)
        self.assertFalse(score.tool_ok)
        self.assertFalse(score.passed)


class SummarizeTest(unittest.TestCase):
    def make(self, tool_ok, answer_ok, finished=True):
        return scoring.CaseScore("x", tool_ok, answer_ok, finished, tool_ok and answer_ok and finished)

    def test_counts_and_rates(self):
        summary = scoring.summarize([self.make(True, True), self.make(True, False),
                                     self.make(False, True), self.make(True, True)])
        self.assertEqual(summary, {"cases": 4, "passed": 2, "tool_ok": 3, "answer_ok": 3,
                                   "unfinished": 0, "pass_rate": 0.5})

    def test_unfinished_runs_are_counted(self):
        self.assertEqual(scoring.summarize([self.make(True, True, finished=False)])["unfinished"], 1)

    def test_no_cases(self):
        self.assertEqual(scoring.summarize([])["pass_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
