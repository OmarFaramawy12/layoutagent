"""Tests for agent/agent.py (the conversation loop) and agent/__main__.py (the terminal front
end). A scripted fake LLM plays the part of the language model, so no network or API key is
needed. The tests marked "real program" also need the built layoutagent program."""

import contextlib
import copy
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
from agent import agent as agent_module  # noqa: E402
from agent import __main__ as agent_main  # noqa: E402
from agent.tools import DrcTools, ToolResult  # noqa: E402
import gen_layout  # noqa: E402

CLI = os.environ.get("LAYOUTAGENT_CLI", os.path.join(ROOT, "build", "layoutagent"))


class StubTools:
    """Stands in for DrcTools: records the calls and returns canned results."""

    layer_names = ["metal1", "via1"]

    def __init__(self, results=()):
        self.results = list(results)
        self.calls = []

    def definitions(self):
        return [{"name": "check_min_width", "description": "d",
                 "input_schema": {"type": "object", "properties": {}, "required": []}}]

    def run(self, name, arguments):
        self.calls.append((name, arguments))
        return self.results.pop(0) if self.results else ToolResult('{"total_count":0}', False)


class FakeLLM:
    """Plays a script of assistant replies and records every request it receives."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def chat(self, messages, tools):
        self.requests.append({"messages": copy.deepcopy(messages), "tools": tools})
        if not self.replies:
            raise AssertionError("the fake LLM was asked more often than the script allows")
        return self.replies.pop(0)


def text(content):
    return {"role": "assistant", "content": content}


def calls(*specs):
    """An assistant reply that asks for tool calls: specs are (id, tool name, arguments)."""
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": name, "arguments": arguments if isinstance(arguments, str)
                      else json.dumps(arguments)}}
        for call_id, name, arguments in specs]}


class SystemPromptTest(unittest.TestCase):
    def test_names_the_layers_and_the_rules_of_the_game(self):
        prompt = agent_module.build_system_prompt(["metal1", "via1"])
        for expected in ("metal1", "via1", "total_count", "SQUARED", "nanometres", "ask",
                         "get_shape"):
            self.assertIn(expected, prompt)


class AgentLoopTest(unittest.TestCase):
    def test_answers_directly_when_no_tool_is_needed(self):
        llm, tools = FakeLLM(text("hello")), StubTools()
        result = agent_module.Agent(llm, tools).ask("hi")

        self.assertEqual(result.answer, "hello")
        self.assertEqual(result.tool_calls, [])
        self.assertEqual(result.steps, 1)
        self.assertTrue(result.finished)

        request = llm.requests[0]
        self.assertEqual([m["role"] for m in request["messages"]], ["system", "user"])
        self.assertEqual(request["messages"][1]["content"], "hi")
        self.assertEqual(request["tools"][0]["type"], "function")
        self.assertEqual(request["tools"][0]["function"]["name"], "check_min_width")

    def test_runs_a_tool_and_sends_its_result_back(self):
        llm = FakeLLM(calls(("call_1", "check_min_width", {"min_width": 50})), text("3 shapes"))
        tools = StubTools([ToolResult('{"total_count":3}', False)])
        result = agent_module.Agent(llm, tools).ask("how many narrow shapes?")

        self.assertEqual(tools.calls, [("check_min_width", {"min_width": 50})])
        second = llm.requests[1]["messages"]
        self.assertEqual([m["role"] for m in second], ["system", "user", "assistant", "tool"])
        self.assertEqual(second[2]["tool_calls"][0]["id"], "call_1")
        self.assertEqual(second[3], {"role": "tool", "tool_call_id": "call_1",
                                     "content": '{"total_count":3}'})
        self.assertEqual(result.tool_calls,
                         [agent_module.ToolCall("check_min_width", {"min_width": 50}, False)])
        self.assertEqual(result.answer, "3 shapes")
        self.assertEqual(result.steps, 2)

    def test_several_tool_calls_in_one_reply_are_all_answered_in_order(self):
        llm = FakeLLM(calls(("a", "check_min_width", {"min_width": 50}),
                            ("b", "check_min_width", {"min_width": 60})), text("done"))
        tools = StubTools()
        agent_module.Agent(llm, tools).ask("two checks")

        self.assertEqual([c[1]["min_width"] for c in tools.calls], [50, 60])
        second = llm.requests[1]["messages"]
        self.assertEqual([m["role"] for m in second][-2:], ["tool", "tool"])
        self.assertEqual([m["tool_call_id"] for m in second[-2:]], ["a", "b"])

    def test_a_tool_error_is_sent_back_marked_as_an_error_so_the_llm_can_retry(self):
        llm = FakeLLM(calls(("c1", "check_min_width", {"min_width": "50"})),
                      calls(("c2", "check_min_width", {"min_width": 50})), text("fixed"))
        tools = StubTools([ToolResult("min_width must be an integer, got '50'", True),
                           ToolResult('{"total_count":1}', False)])
        result = agent_module.Agent(llm, tools).ask("check width 50")

        error_message = llm.requests[1]["messages"][-1]
        self.assertEqual(error_message["content"], "Error: min_width must be an integer, got '50'")
        self.assertEqual([c.is_error for c in result.tool_calls], [True, False])
        self.assertEqual(result.answer, "fixed")

    def test_arguments_that_are_not_valid_json_are_reported_and_not_run(self):
        llm = FakeLLM(calls(("c1", "check_min_width", "{not json")), text("sorry"))
        tools = StubTools()
        result = agent_module.Agent(llm, tools).ask("question")

        self.assertEqual(tools.calls, [])
        content = llm.requests[1]["messages"][-1]["content"]
        self.assertTrue(content.startswith("Error:"), content)
        self.assertIn("JSON", content)
        self.assertEqual(result.tool_calls, [agent_module.ToolCall("check_min_width", {}, True)])

    def test_empty_arguments_mean_no_arguments(self):
        tools = StubTools()
        agent_module.Agent(FakeLLM(calls(("c1", "check_min_width", "")), text("ok")), tools).ask("q")
        self.assertEqual(tools.calls, [("check_min_width", {})])

    def test_arguments_that_arrive_already_parsed_are_accepted(self):
        reply = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "check_min_width", "arguments": {"min_width": 50}}}]}
        tools = StubTools()
        agent_module.Agent(FakeLLM(reply, text("ok")), tools).ask("q")
        self.assertEqual(tools.calls, [("check_min_width", {"min_width": 50})])

    def test_stops_after_max_steps_if_the_llm_never_finishes(self):
        script = [calls(("c%d" % i, "check_min_width", {"min_width": 50})) for i in range(3)]
        llm, tools = FakeLLM(*script), StubTools()
        result = agent_module.Agent(llm, tools, max_steps=3).ask("loop forever")

        self.assertFalse(result.finished)
        self.assertEqual(result.answer, "")
        self.assertEqual(result.steps, 3)
        self.assertEqual(len(llm.requests), 3)  # no fourth request
        self.assertEqual(len(tools.calls), 3)

    def test_a_reply_without_text_gives_an_empty_answer(self):
        result = agent_module.Agent(FakeLLM({"role": "assistant", "content": None}), StubTools()).ask("q")
        self.assertEqual(result.answer, "")
        self.assertTrue(result.finished)

    def test_only_the_standard_fields_of_a_reply_are_sent_back(self):
        reply = dict(calls(("c1", "check_min_width", {"min_width": 50})),
                     reasoning_content="private thoughts", refusal=None)
        llm = FakeLLM(reply, text("ok"))
        agent_module.Agent(llm, StubTools()).ask("q")

        resent = llm.requests[1]["messages"][2]
        self.assertEqual(set(resent), {"role", "content", "tool_calls"})
        self.assertEqual(resent["content"], "")  # None is sent as an empty string

    def test_every_question_starts_a_new_conversation(self):
        llm = FakeLLM(text("one"), text("two"))
        agent = agent_module.Agent(llm, StubTools())
        agent.ask("first")
        agent.ask("second")
        self.assertEqual([m["content"] for m in llm.requests[1]["messages"][1:]], ["second"])


def make_layout(folder, seed=5, count=200):
    prefix = os.path.join(folder, "case")
    with contextlib.redirect_stdout(io.StringIO()):
        gen_layout.main(["--seed", str(seed), "--count", str(count), "--out", prefix])
    with open(prefix + ".expected.json") as f:
        return prefix + ".json", json.load(f)["violations"]


@unittest.skipUnless(os.path.isfile(CLI), "the layoutagent program is not built")
class RealProgramTest(unittest.TestCase):
    """The loop with the real tools and the real C++ program (only the LLM is fake)."""

    def test_a_tool_call_runs_the_real_check(self):
        with tempfile.TemporaryDirectory() as folder:
            layout_path, expected = make_layout(folder)
            tools = DrcTools(layout_path, program=[CLI])
            llm = FakeLLM(calls(("c1", "check_min_width", {"min_width": 50})), text("done"))
            agent_module.Agent(llm, tools).ask("which shapes are too narrow?")

            tool_message = llm.requests[1]["messages"][-1]
            self.assertEqual(tool_message["tool_call_id"], "c1")
            self.assertEqual(json.loads(tool_message["content"])["total_count"],
                             len([v for v in expected if v["type"] == "min_width"]))


@unittest.skipUnless(os.path.isfile(CLI), "the layoutagent program is not built")
class MainTest(unittest.TestCase):
    """python -m agent LAYOUT QUESTION"""

    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.layout_path, _ = make_layout(self._folder.name, count=30)
        environment = mock.patch.dict(os.environ, {"LAYOUTAGENT_CLI": CLI})
        environment.start()
        self.addCleanup(environment.stop)

    def run_main(self, argv, llm=None):
        out, err = io.StringIO(), io.StringIO()
        code = agent_main.main(argv, llm=llm, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_prints_the_answer(self):
        code, out, err = self.run_main([self.layout_path, "hello?"], FakeLLM(text("all fine")))
        self.assertEqual((code, out, err), (0, "all fine\n", ""))

    def test_show_calls_lists_the_tool_calls_on_stderr(self):
        llm = FakeLLM(calls(("c1", "check_min_width", {"min_width": 50})), text("ok"))
        code, out, err = self.run_main([self.layout_path, "q", "--show-calls"], llm)
        self.assertEqual(code, 0)
        self.assertEqual(out, "ok\n")
        self.assertIn("check_min_width", err)
        self.assertIn('"min_width": 50', err)

    def test_missing_llm_settings_are_reported(self):
        with mock.patch.dict(os.environ, {"LAYOUTAGENT_CLI": CLI}, clear=True):
            code, out, err = self.run_main([self.layout_path, "q"])
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error:"), err)
        self.assertIn("LLM_API_KEY", err)

    def test_missing_layout_file(self):
        code, out, err = self.run_main(["no_such_layout.json", "q"], FakeLLM())
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("error:"), err)

    def test_an_llm_that_never_finishes_is_an_error(self):
        script = [calls(("c%d" % i, "check_min_width", {"min_width": 50})) for i in range(8)]
        code, out, err = self.run_main([self.layout_path, "q"], FakeLLM(*script))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("did not finish", err)


if __name__ == "__main__":
    unittest.main()
