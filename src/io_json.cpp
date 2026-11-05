#include "io_json.hpp"

#include <cstddef>  // std::size_t
#include <cstdint>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>

#include <nlohmann/json.hpp>

namespace layoutagent {

namespace {

// ordered_json keeps object keys in the order they appear in the file. The default
// nlohmann::json would sort them alphabetically, which would change the layer IDs.
using Json = nlohmann::ordered_json;

// Reads one coordinate. "where" is text like "layer 'metal1', rect 3" used in error messages.
std::int64_t read_coordinate(const Json& value, const std::string& where) {
    // is_number_integer() is false for 1.5, 10.0, "10" and null.
    if (!value.is_number_integer()) {
        throw std::runtime_error(where + ": coordinate must be an integer, got " +
                                 value.dump());
    }
    // Non-negative integers are stored as unsigned 64-bit. One bigger than int64's maximum
    // would wrap around to a negative number in get<int64_t>(), so reject it first.
    if (value.is_number_unsigned() &&
        value.get<std::uint64_t>() >
            static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())) {
        throw std::runtime_error(where + ": coordinate does not fit in 64 bits: " +
                                 value.dump());
    }
    return value.get<std::int64_t>();
}

void add_rect_from_json(Layout& layout, int layer_id, const std::string& layer_name,
                        std::size_t index, const Json& rect_json) {
    const std::string where = "layer '" + layer_name + "', rect " + std::to_string(index);

    if (!rect_json.is_array() || rect_json.size() != 4) {
        throw std::runtime_error(where + ": expected [x1, y1, x2, y2]");
    }

    const std::int64_t x1 = read_coordinate(rect_json[0], where);
    const std::int64_t y1 = read_coordinate(rect_json[1], where);
    const std::int64_t x2 = read_coordinate(rect_json[2], where);
    const std::int64_t y2 = read_coordinate(rect_json[3], where);

    // Layout::add_rect throws std::invalid_argument for a bad rect (zero size, reversed
    // corners, out of range). Re-throw it as runtime_error with the layer and rect number
    // added, so every loader error has the same type and says where the problem is.
    try {
        layout.add_rect(layer_id, x1, y1, x2, y2);
    } catch (const std::invalid_argument& error) {
        throw std::runtime_error(where + ": " + error.what());
    }
}

}  // namespace

Layout parse_layout(const std::string& json_text) {
    Json document;
    try {
        document = Json::parse(json_text);
    } catch (const Json::parse_error& error) {
        throw std::runtime_error(std::string("Invalid JSON: ") + error.what());
    }

    if (!document.is_object() || !document.contains("layers")) {
        throw std::runtime_error("Layout file must be an object with a \"layers\" key");
    }
    const Json& layers = document.at("layers");
    if (!layers.is_object()) {
        throw std::runtime_error("\"layers\" must be an object of layer name -> list of rects");
    }

    Layout layout;
    // items() lets us loop over an object's (key, value) pairs, in file order.
    for (const auto& item : layers.items()) {
        const std::string& layer_name = item.key();
        const Json& rects = item.value();
        if (!rects.is_array()) {
            throw std::runtime_error("layer '" + layer_name + "': expected a list of rects");
        }

        const int layer_id = layout.add_layer(layer_name);
        for (std::size_t i = 0; i < rects.size(); ++i) {
            add_rect_from_json(layout, layer_id, layer_name, i, rects[i]);
        }
    }
    return layout;
}

Layout load_layout(const std::string& path) {
    std::ifstream file(path);
    if (!file) {
        throw std::runtime_error("Cannot open layout file: " + path);
    }
    std::ostringstream text;
    text << file.rdbuf();  // copies the whole file into the string stream
    return parse_layout(text.str());
}

}  // namespace layoutagent
