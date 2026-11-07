"""Terminal front end:  python -m agent LAYOUT.json "your question" [--show-calls]

Needs LLM_BASE_URL, LLM_MODEL and LLM_API_KEY (see agent/llm.py). The answer goes to stdout,
errors and the optional tool-call list go to stderr. Exit code 0 = answered, 1 = failure."""

import argparse
import json
import sys

from agent.agent import Agent
from agent.llm import LLMError, client_from_environment
from agent.tools import DrcTools


def main(argv=None, llm=None, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="python -m agent")
    parser.add_argument("layout", help="layout JSON file")
    parser.add_argument("question", help="what to ask, in plain language")
    parser.add_argument("--show-calls", action="store_true",
                        help="list the tool calls on stderr")
    args = parser.parse_args(argv)

    try:
        tools = DrcTools(args.layout)
        result = Agent(llm or client_from_environment(), tools).ask(args.question)
    except (LLMError, OSError, ValueError, RuntimeError) as error:
        print("error: " + str(error), file=err)
        return 1

    if args.show_calls:
        for call in result.tool_calls:
            status = " (error)" if call.is_error else ""
            print("tool call: %s %s%s" % (call.name, json.dumps(call.arguments), status), file=err)
    if not result.finished:
        print("error: the LLM did not finish within %d steps" % result.steps, file=err)
        return 1
    print(result.answer, file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
