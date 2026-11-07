#pragma once

#include <string>
#include <vector>

#include "layout.hpp"
#include "violation.hpp"

namespace layoutagent {

// Builds a Layout from JSON text of the form
//   {"layers": {"metal1": [[x1, y1, x2, y2], ...], "via1": [...]}}
// Layer IDs follow the order of the layers in the text (not alphabetical order), and
// shape IDs count 0, 1, 2, ... across the whole text, layer by layer, in list order.
// Coordinates must be JSON integers (1.5 and 10.0 are rejected).
// Throws std::runtime_error, with a message saying what is wrong and where, on bad input:
// invalid JSON, a key repeated inside one JSON object (for example a layer name that appears
// twice), a missing or wrongly shaped part, or an invalid rect.
Layout parse_layout(const std::string& json_text);

// Reads a file and calls parse_layout on its content.
// Throws std::runtime_error if the file cannot be opened.
Layout load_layout(const std::string& path);

// Turns violations into JSON text (pretty-printed, 2 spaces):
//   {"violations": [{"type": "min_spacing", "layer_a": "metal1", "layer_b": "metal1",
//                    "first_shape_id": 2, "second_shape_id": 7,
//                    "measured": 81, "required": 1600}, ...]}
// The keys are the field names of Violation. "type" is "min_width", "min_spacing" or
// "overlap"; the layers are given by name (looked up in the layout); "second_shape_id" is
// null when there is no second shape. The order of the violations is kept.
// Throws std::out_of_range if a violation has a layer ID the layout does not know.
std::string violations_to_json(const Layout& layout, const std::vector<Violation>& violations);

// Turns the result of a window query into JSON text: {"shape_ids": [7, 2, 9]}.
// The order of the IDs is kept; no shapes gives an empty array.
std::string shape_ids_to_json(const std::vector<int>& shape_ids);

}  // namespace layoutagent
