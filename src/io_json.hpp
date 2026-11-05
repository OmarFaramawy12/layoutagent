#pragma once

#include <string>

#include "layout.hpp"

namespace layoutagent {

// Builds a Layout from JSON text of the form
//   {"layers": {"metal1": [[x1, y1, x2, y2], ...], "via1": [...]}}
// Layer IDs follow the order of the layers in the text (not alphabetical order), and
// shape IDs count 0, 1, 2, ... across the whole text, layer by layer, in list order.
// Coordinates must be JSON integers (1.5 and 10.0 are rejected).
// Throws std::runtime_error, with a message saying what is wrong and where, on bad input:
// invalid JSON, a missing or wrongly shaped part, or an invalid rect.
Layout parse_layout(const std::string& json_text);

// Reads a file and calls parse_layout on its content.
// Throws std::runtime_error if the file cannot be opened.
Layout load_layout(const std::string& path);

}  // namespace layoutagent
