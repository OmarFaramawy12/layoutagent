"""The conversation loop: the LLM picks checks, DrcTools runs them in C++, the LLM explains.

The loop only needs an object with chat(messages, tools) -> assistant message, so tests can
use a scripted fake instead of a real language model."""

import json
from dataclasses import dataclass, field

from agent.llm import tool_schemas

MAX_STEPS = 8


def build_system_prompt(layer_names):
    return (
        "You are an assistant for an IC layout design-rule checker. The layout has these "
        "layers: " + ", ".join(layer_names) + ".\n"
        "All geometry is done by the tools, never by you: do not compute distances, widths "
        "or overlaps yourself, and do not guess results. Call a tool, then explain what it "
        "returned.\n"
        "Units: all coordinates and rule values are in nanometres (nm). The y axis grows "
        "upward.\n"
        "Reading results: 'total_count' is the real number of violations or shapes; the list "
        "may be shorter ('truncated': true), so report total_count, not the list length. "
        "For spacing violations, 'measured' and 'required' are SQUARED distances (nm squared); "
        "take the square root to talk about nm. For overlap violations, 'measured' is the "
        "overlap area in nm squared. For width violations, 'measured' and 'required' are in "
        "nm.\n"
        "Violations and window queries give shape IDs, not positions: if you need a shape's "
        "layer or coordinates, call get_shape with its ID instead of guessing.\n"
        "If the question lacks a number you need (such as a minimum width), ask the user "
        "instead of inventing one. If a tool returns an error, fix the call and try again."
    )


@dataclass
class ToolCall:
    name: str
    arguments: dict
    is_error: bool


@dataclass
class AgentResult:
    answer: str
    tool_calls: list = field(default_factory=list)
    steps: int = 0
    finished: bool = False  # False = the LLM was still calling tools after max_steps


def parse_arguments(raw):
    """Returns (arguments dict, error text or None). The API sends the arguments as a JSON
    string, but some providers send an already parsed object."""
    if isinstance(raw, dict):
        return raw, None
    if raw is None or raw == "":
        return {}, None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}, "the arguments are not valid JSON"
    if not isinstance(parsed, dict):
        return {}, "the arguments must be a JSON object"
    return parsed, None


class Agent:
    def __init__(self, llm, tools, max_steps=MAX_STEPS):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps

    def ask(self, question):
        """Answers one question. Every question starts a fresh conversation."""
        messages = [{"role": "system", "content": build_system_prompt(self.tools.layer_names)},
                    {"role": "user", "content": question}]
        schemas = tool_schemas(self.tools.definitions())
        result = AgentResult(answer="")

        for _ in range(self.max_steps):
            reply = self.llm.chat(messages, schemas)
            result.steps += 1
            requested = reply.get("tool_calls") or []
            if not requested:
                result.answer = reply.get("content") or ""
                result.finished = True
                return result

            # Resend only the standard fields: strict providers reject extra ones.
            messages.append({"role": "assistant", "content": reply.get("content") or "",
                             "tool_calls": [self._standard_call(c) for c in requested]})
            for call in requested:
                messages.append(self._run_call(call, result))
        return result

    @staticmethod
    def _standard_call(call):
        arguments = call["function"].get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {})
        return {"id": call["id"], "type": "function",
                "function": {"name": call["function"]["name"], "arguments": arguments}}

    def _run_call(self, call, result):
        name = call["function"]["name"]
        arguments, problem = parse_arguments(call["function"].get("arguments"))
        if problem:
            content, is_error = problem, True
        else:
            tool_result = self.tools.run(name, arguments)
            content, is_error = tool_result.content, tool_result.is_error
        result.tool_calls.append(ToolCall(name, arguments, is_error))
        if is_error:
            content = "Error: " + content  # this message format has no separate error flag
        return {"role": "tool", "tool_call_id": call["id"], "content": content}
