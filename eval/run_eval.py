"""Runs the evaluation cases against a real LLM and prints a score table.

    python -m eval.run_eval [--cases eval/cases.json] [--only ID ...]

Needs LLM_BASE_URL, LLM_MODEL and LLM_API_KEY (see agent/llm.py) and the built layoutagent
program. Every case is one real LLM conversation, so a full run uses some of your API quota;
--only runs just the named cases. The layout is generated from a fixed seed, so results can be
compared from run to run. The correct counts come from running the C++ engine, not the model.
"""

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import gen_layout  # noqa: E402
from agent.agent import Agent  # noqa: E402
from agent.llm import LLMError, client_from_environment  # noqa: E402
from agent.tools import DrcTools  # noqa: E402
from eval import scoring  # noqa: E402

DEFAULT_CASES = os.path.join(ROOT, "eval", "cases.json")
TOOL_NAMES = {"check_min_width", "check_min_spacing", "check_overlap", "window_query"}


def load_cases(path):
    """Returns (layout settings, list of cases). Raises ValueError for a bad file."""
    try:
        with open(path) as f:
            document = json.load(f)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("cannot read cases file %s: %s" % (path, error))

    layout = document.get("layout")
    if not isinstance(layout, dict) or not {"seed", "count"} <= set(layout):
        raise ValueError('the cases file needs "layout": {"seed": ..., "count": ...}')
    cases = document.get("cases")
    if not cases:
        raise ValueError("the cases file has no cases")

    seen = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id:
            raise ValueError("every case needs an id")
        if case_id in seen:
            raise ValueError("duplicate case id: " + case_id)
        seen.add(case_id)
        if not case.get("question"):
            raise ValueError("case %s has no question" % case_id)
        tool = case.get("expect", {}).get("tool", "missing")
        if tool is not None and tool not in TOOL_NAMES:
            raise ValueError("case %s expects an unknown tool: %s" % (case_id, tool))
        if tool is not None and not isinstance(case["expect"].get("arguments"), dict):
            raise ValueError("case %s needs expect.arguments" % case_id)
    return layout, cases


def make_tools(layout, folder):
    """Generates the layout into folder and returns the DrcTools for it."""
    prefix = os.path.join(folder, "layout")
    with contextlib.redirect_stdout(io.StringIO()):  # gen_layout prints a summary line
        gen_layout.main(["--seed", str(layout["seed"]), "--count", str(layout["count"]),
                         "--out", prefix])
    return DrcTools(prefix + ".json")


def expected_count(tools, expect):
    """The right answer, from the C++ engine. None when the case has no count to check."""
    if expect["tool"] is None:
        return None
    result = tools.run(expect["tool"], expect["arguments"])
    if result.is_error:
        raise ValueError("the expected call %s failed: %s" % (expect["tool"], result.content))
    return json.loads(result.content)["total_count"]


def format_report(rows, summary, tokens):
    lines = ["%-26s %-5s %-7s %-6s %s" % ("case", "tool", "answer", "steps", "result")]
    for case, score, result in rows:
        lines.append("%-26s %-5s %-7s %-6d %s" % (
            case["id"], "ok" if score.tool_ok else "BAD", "ok" if score.answer_ok else "BAD",
            result.steps, "PASS" if score.passed else "FAIL"))
        if not score.passed:
            calls = ["%s %s%s" % (c.name, json.dumps(c.arguments), " (error)" if c.is_error else "")
                     for c in result.tool_calls]
            lines.append("    calls: " + ("; ".join(calls) if calls else "(none)"))
            lines.append("    answer: " + (result.answer.strip().replace("\n", " ")[:200] or "(empty)"))
    lines.append("")
    lines.append("Passed %d of %d cases (tool ok %d, answer ok %d, unfinished %d)" % (
        summary["passed"], summary["cases"], summary["tool_ok"], summary["answer_ok"],
        summary["unfinished"]))
    if tokens:
        lines.append("Tokens used: %d" % tokens)
    return "\n".join(lines)


def main(argv=None, llm=None, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="python -m eval.run_eval")
    parser.add_argument("--cases", default=DEFAULT_CASES, help="cases file (default eval/cases.json)")
    parser.add_argument("--only", nargs="+", metavar="ID", help="run only these case ids")
    args = parser.parse_args(argv)

    try:
        layout, cases = load_cases(args.cases)
        if args.only:
            unknown = set(args.only) - {c["id"] for c in cases}
            if unknown:
                raise ValueError("unknown case id(s): " + ", ".join(sorted(unknown)))
            cases = [c for c in cases if c["id"] in args.only]
        llm = llm or client_from_environment()

        rows = []
        with tempfile.TemporaryDirectory() as folder:
            tools = make_tools(layout, folder)
            agent = Agent(llm, tools)
            for case in cases:
                count = expected_count(tools, case["expect"])
                result = agent.ask(case["question"])
                score = scoring.score_case(case, result.tool_calls, result.answer,
                                           result.finished, count)
                rows.append((case, score, result))
    except (LLMError, OSError, ValueError, RuntimeError) as error:
        print("error: " + str(error), file=err)
        return 1

    summary = scoring.summarize([score for _, score, _ in rows])
    print(format_report(rows, summary, getattr(llm, "total_tokens", 0)), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
