"""Deterministic scoring of one agent run. No second LLM judges anything.

A case says which tool the question needs ("expect": {"tool": ..., "arguments": {...}}, or
{"tool": null} when the agent should ask a question instead of calling a tool). The correct
count comes from running the real C++ engine, not from the model.

Known weakness: the answer check only looks for the count as a number anywhere in the text,
so a count that equals another number in the answer (for example the "50" of "50 nm") can be
matched by accident. Cases should be written so that the counts differ from the rule values.
"""

import re
from dataclasses import dataclass

NUMBER_PATTERN = re.compile(r"\d+\.\d+|\d{1,3}(?:,\d{3})+|\d+")  # decimal | 1,234 | plain
ZERO_WORDS = re.compile(r"\b(no|none|zero)\b", re.IGNORECASE)


@dataclass
class CaseScore:
    case_id: str
    tool_ok: bool
    answer_ok: bool
    finished: bool
    passed: bool


def numbers_in(text):
    """The whole numbers in the text. Decimals are skipped; "1,234" is 1234."""
    return {int(token.replace(",", "")) for token in NUMBER_PATTERN.findall(text)
            if "." not in token}


def same_arguments(tool, expected, actual):
    if tool == "check_overlap":  # overlap is symmetric, so the layer order does not matter
        return (frozenset([expected.get("layer_a"), expected.get("layer_b")]) ==
                frozenset([actual.get("layer_a"), actual.get("layer_b")]))
    return expected == actual


def answer_mentions_count(answer, count):
    if count == 0:
        return 0 in numbers_in(answer) or bool(ZERO_WORDS.search(answer))
    return count in numbers_in(answer)


def tool_was_called_correctly(expect, tool_calls):
    if expect["tool"] is None:
        return not tool_calls
    return any(call.name == expect["tool"] and not call.is_error
               and same_arguments(call.name, expect["arguments"], call.arguments)
               for call in tool_calls)


def score_case(case, tool_calls, answer, finished, expected_count):
    """tool_calls are the ToolCall records of the run; expected_count is None when the case
    has no count to check."""
    tool_ok = tool_was_called_correctly(case["expect"], tool_calls)
    answer_ok = expected_count is None or answer_mentions_count(answer, expected_count)
    return CaseScore(case["id"], tool_ok, answer_ok, finished, finished and tool_ok and answer_ok)


def summarize(scores):
    passed = sum(1 for s in scores if s.passed)
    return {"cases": len(scores), "passed": passed,
            "tool_ok": sum(1 for s in scores if s.tool_ok),
            "answer_ok": sum(1 for s in scores if s.answer_ok),
            "unfinished": sum(1 for s in scores if not s.finished),
            "pass_rate": passed / len(scores) if scores else 0.0}
