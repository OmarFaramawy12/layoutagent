"""The tools the LLM can call (roadmap step 8).

The LLM only chooses WHICH check to run and with which numbers. Each tool runs the
`layoutagent` program on one layout file and gives its JSON answer back. All geometry
happens in C++: this file only checks the arguments, runs the program, and shapes the answer.

    tools = DrcTools("layout.json")
    tools.definitions()                                # describes the tools to the LLM
    tools.run("check_min_width", {"min_width": 50})    # runs one tool call -> ToolResult

Mistakes the LLM can fix (a bad argument, an unknown layer, an error from the program) come
back as a ToolResult with is_error=True. Problems only the programmer can fix (the program
is missing, or prints something that is not JSON) raise an exception instead.
"""

import json
import os
import subprocess
from dataclasses import dataclass

CLI_TIMEOUT_SECONDS = 30
MAX_VIOLATIONS_RETURNED = 50   # a layout can have thousands; the LLM sees the first ones
MAX_SHAPE_IDS_RETURNED = 200   # shape IDs are short, so more of them fit


@dataclass
class ToolResult:
    content: str    # the text that is sent back to the LLM
    is_error: bool  # True when the call failed and the LLM should adjust and try again


class BadArguments(ValueError):
    """The LLM called a tool with arguments that do not fit its description."""


def default_program_path(root=None):
    """The built layoutagent program: $LAYOUTAGENT_CLI, or the newest build found under
    build/ in the repo. Linux builds make build/layoutagent; Windows builds make
    layoutagent.exe, and the Visual Studio generator puts it in build/Debug or build/Release.
    If none exists, the plain build/layoutagent is returned, so the error says where we looked.
    "root" (the repo folder) is a parameter only so that tests can point it elsewhere."""
    if "LAYOUTAGENT_CLI" in os.environ:
        return os.environ["LAYOUTAGENT_CLI"]
    if root is None:
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    build = os.path.join(root, "build")
    candidates = [os.path.join(build, "layoutagent"),
                  os.path.join(build, "layoutagent.exe"),
                  os.path.join(build, "Release", "layoutagent.exe"),
                  os.path.join(build, "Debug", "layoutagent.exe")]
    found = [path for path in candidates if os.path.isfile(path)]
    return max(found, key=os.path.getmtime) if found else candidates[0]


def object_without_duplicate_keys(pairs):
    """json.load calls this for every JSON object, with its (key, value) pairs in file order.
    Python normally keeps the last of two equal keys without a word; the C++ loader rejects
    such files, so the tool layer does too."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key '" + key + "' in a JSON object")
        result[key] = value
    return result


def read_layer_names(layout_path):
    """The layer names of a layout file, in file order. (Reading names is not geometry.)"""
    with open(layout_path) as f:
        data = json.load(f, object_pairs_hook=object_without_duplicate_keys)
    layers = data.get("layers") if isinstance(data, dict) else None
    if not isinstance(layers, dict) or not layers:
        raise ValueError(layout_path + ': expected {"layers": {...}} with at least one layer')
    return list(layers)


def first_line(text):
    lines = text.strip().splitlines()
    return lines[0] if lines else ""


def check_arguments(arguments, required, optional=()):
    """Raises BadArguments unless `arguments` is an object with exactly the right keys."""
    if not isinstance(arguments, dict):
        raise BadArguments("the arguments must be a JSON object")
    for key in required:
        if key not in arguments:
            raise BadArguments("missing argument '" + key + "'")
    for key in arguments:
        if key not in required and key not in optional:
            raise BadArguments("unexpected argument '" + key + "'")


def require_int(arguments, key):
    value = arguments[key]
    # bool is a kind of int in Python, so True would slip through without the second test.
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadArguments(key + " must be an integer, got " + repr(value))
    return value


def limited_answer(items, limit, key):
    """The ToolResult for a list of items: the first `limit` of them under `key`, plus the
    total, which is counted here so the LLM never has to count."""
    shown = items[:limit]
    answer = {
        "total_count": len(items),
        "returned_count": len(shown),
        "truncated": len(shown) < len(items),
        key: shown,
    }
    return ToolResult(json.dumps(answer, separators=(",", ":")), False)


class DrcTools:
    def __init__(self, layout_path, program=None, timeout_seconds=CLI_TIMEOUT_SECONDS):
        """layout_path: the one layout file these tools work on (the LLM cannot pick another).
        program: the command that runs layoutagent, as a list; the default is the built program.
        """
        if program is None:
            path = default_program_path()
            if not os.path.isfile(path):
                raise FileNotFoundError("layoutagent program not found at " + path +
                                        " (build it, or set LAYOUTAGENT_CLI)")
            program = [path]
        self.layout_path = layout_path
        self.program = program
        self.timeout_seconds = timeout_seconds
        self.layer_names = read_layer_names(layout_path)

    # ---- what the LLM is told about the tools ----

    def definitions(self):
        """The tool descriptions in the format the Claude API expects."""
        filter_layer = {
            "type": "string",
            "enum": self.layer_names,
            "description": "Optional. Only report violations on this layer.",
        }
        return [
            {
                "name": "check_min_width",
                "description": (
                    "Finds shapes that are too narrow. A shape violates the rule when its "
                    "smaller side (its width or its height) is below min_width; a side exactly "
                    "equal to min_width is allowed. All lengths are in nanometres (nm). "
                    "In each violation, 'measured' is that smaller side and 'required' is "
                    "min_width. Checks every layer unless 'layer' is given."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "min_width": {"type": "integer", "minimum": 1,
                                      "description": "Minimum allowed width in nm."},
                        "layer": filter_layer,
                    },
                    "required": ["min_width"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "check_min_spacing",
                "description": (
                    "Finds pairs of shapes on the same layer that are closer than min_spacing "
                    "(the Euclidean distance between the two rectangles). Shapes that touch or "
                    "overlap on the same layer have distance 0, so they are violations too; a "
                    "distance exactly equal to min_spacing is allowed. Lengths are in nm. "
                    "In each violation, 'measured' is the SQUARED distance (nm squared) and "
                    "'required' is min_spacing squared. Checks every layer unless 'layer' "
                    "is given."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "min_spacing": {"type": "integer", "minimum": 1,
                                        "description": "Minimum allowed spacing in nm."},
                        "layer": filter_layer,
                    },
                    "required": ["min_spacing"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "check_overlap",
                "description": (
                    "Finds pairs of shapes on two different layers that share area (one shape "
                    "on layer_a, one on layer_b). Shapes that only touch along an edge or at a "
                    "corner do not overlap. In each violation, 'measured' is the overlap area "
                    "in nm squared and 'required' is 0. Overlaps between shapes of the same "
                    "layer are not reported; use check_min_spacing for those."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "layer_a": {"type": "string", "enum": self.layer_names},
                        "layer_b": {"type": "string", "enum": self.layer_names,
                                    "description": "Must be a different layer than layer_a."},
                    },
                    "required": ["layer_a", "layer_b"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "window_query",
                "description": (
                    "Lists the shapes on one layer that intersect a rectangular window. The "
                    "window is given by its lower-left corner (x1, y1) and its upper-right "
                    "corner (x2, y2) in nm, with x1 < x2 and y1 < y2; the y axis grows upward. "
                    "A shape counts as inside when it shares area with the window; shapes that "
                    "only touch the window's edge or corner are not included. Returns the "
                    "shape IDs (the same IDs that appear in violations), not coordinates."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "layer": {"type": "string", "enum": self.layer_names},
                        "x1": {"type": "integer", "description": "Left edge in nm."},
                        "y1": {"type": "integer", "description": "Bottom edge in nm."},
                        "x2": {"type": "integer", "description": "Right edge in nm."},
                        "y2": {"type": "integer", "description": "Top edge in nm."},
                    },
                    "required": ["layer", "x1", "y1", "x2", "y2"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_shape",
                "description": (
                    "Looks up one shape by its shape ID (the IDs that appear in violations and "
                    "in window query results) and returns its layer and its position: the "
                    "lower-left corner (x1, y1) and the upper-right corner (x2, y2) in nm, with "
                    "the y axis growing upward. Use it when you need to say where a shape is or "
                    "how big it is; the other tools give IDs only."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "shape_id": {"type": "integer",
                                     "description": "The shape ID, 0 or more."},
                    },
                    "required": ["shape_id"],
                    "additionalProperties": False,
                },
            },
        ]

    # ---- running a tool call ----

    def run(self, name, arguments):
        """Runs one tool call from the LLM and returns a ToolResult."""
        handlers = {
            "check_min_width": self._check_min_width,
            "check_min_spacing": self._check_min_spacing,
            "check_overlap": self._check_overlap,
            "window_query": self._window_query,
            "get_shape": self._get_shape,
        }
        if name not in handlers:
            return ToolResult("unknown tool '" + name + "'. Available tools: " +
                              ", ".join(handlers), True)
        try:
            return handlers[name](arguments)
        except BadArguments as error:
            return ToolResult(str(error), True)

    def _check_min_width(self, arguments):
        check_arguments(arguments, required=["min_width"], optional=["layer"])
        min_width = require_int(arguments, "min_width")
        layer = self._optional_layer(arguments)
        return self._run_check(["--min-width", str(min_width)], layer)

    def _check_min_spacing(self, arguments):
        check_arguments(arguments, required=["min_spacing"], optional=["layer"])
        min_spacing = require_int(arguments, "min_spacing")
        layer = self._optional_layer(arguments)
        return self._run_check(["--min-spacing", str(min_spacing)], layer)

    def _check_overlap(self, arguments):
        check_arguments(arguments, required=["layer_a", "layer_b"])
        layer_a = self._layer(arguments["layer_a"], "layer_a")
        layer_b = self._layer(arguments["layer_b"], "layer_b")
        return self._run_check(["--overlap", layer_a, layer_b], None)

    def _window_query(self, arguments):
        check_arguments(arguments, required=["layer", "x1", "y1", "x2", "y2"])
        layer = self._layer(arguments["layer"], "layer")
        corners = [str(require_int(arguments, key)) for key in ("x1", "y1", "x2", "y2")]
        shape_ids, error = self._call_program(["--window", layer] + corners, "shape_ids")
        if error:
            return error
        return limited_answer(shape_ids, MAX_SHAPE_IDS_RETURNED, "shape_ids")

    def _get_shape(self, arguments):
        check_arguments(arguments, required=["shape_id"])
        shape_id = require_int(arguments, "shape_id")
        shape, error = self._call_program(["--shape", str(shape_id)], "shape")
        if error:  # for example an unknown shape ID: the program says so
            return error
        return ToolResult(json.dumps(shape, separators=(",", ":")), False)

    def _layer(self, value, key):
        if not isinstance(value, str) or value not in self.layer_names:
            raise BadArguments(key + " must be one of the layers " + str(self.layer_names) +
                               ", got " + repr(value))
        return value

    def _optional_layer(self, arguments):
        if arguments.get("layer") is None:  # missing, or null: no filter
            return None
        return self._layer(arguments["layer"], "layer")

    def _run_check(self, flags, layer):
        """Runs one of the checks. `layer` filters the violations by layer name (None = all)."""
        violations, error = self._call_program(flags, "violations")
        if error:
            return error
        if layer is not None:
            violations = [v for v in violations if v["layer_a"] == layer]
        return limited_answer(violations, MAX_VIOLATIONS_RETURNED, "violations")

    def _call_program(self, flags, key):
        """Runs the program. Returns (items, None) with the list found under `key` in its JSON
        output, or (None, ToolResult) when it failed in a way the LLM can see and react to."""
        # The command is a list, so no shell is involved and nothing can be injected.
        command = self.program + [self.layout_path] + flags
        try:
            completed = subprocess.run(command, capture_output=True, text=True,
                                       timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            return None, ToolResult("the check took longer than " + str(self.timeout_seconds) +
                                    " seconds and was stopped", True)

        if completed.returncode != 0:
            # Only the "error: ..." line: the usage text after it is noise for the LLM.
            message = first_line(completed.stderr)
            return None, ToolResult(message or "layoutagent failed with exit code " +
                                    str(completed.returncode), True)

        try:
            return json.loads(completed.stdout)[key], None
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeError("layoutagent printed output that is not the expected JSON: " +
                               repr(completed.stdout[:200])) from error
