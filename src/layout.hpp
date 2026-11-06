#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "rect.hpp"

namespace layoutagent {

// Holds the layers of a layout and the rectangles on each layer.
// Layer names are converted to integer IDs; both directions are kept:
// name -> ID and ID -> name.
class Layout {
public:
    // Adds a layer and returns its ID. IDs start at 0 and go up by one.
    // Throws std::invalid_argument if the name already exists.
    int add_layer(const std::string& name);

    // Throws std::out_of_range if the name / ID is unknown.
    int layer_id(const std::string& name) const;
    const std::string& layer_name(int id) const;

    // Number of layers. Valid layer IDs are 0 .. layer_count() - 1.
    int layer_count() const;

    // Adds a rectangle to a layer and returns its shape ID. Shape IDs are
    // unique across all layers: 0, 1, 2, ... in the order rects are added.
    // Throws std::out_of_range if the layer ID is unknown, and
    // std::invalid_argument if the rect is invalid (no shape ID is used up).
    int add_rect(int layer_id, std::int64_t x1, std::int64_t y1,
                 std::int64_t x2, std::int64_t y2);

    // All rects on one layer, in the order they were added.
    // Throws std::out_of_range if the layer ID is unknown.
    const std::vector<Rect>& rects(int layer_id) const;

private:
    void check_layer_id(int id) const;

    std::unordered_map<std::string, int> name_to_id_;
    std::vector<std::string> id_to_name_;       // index in this vector is the layer ID
    std::vector<std::vector<Rect>> layer_rects_;  // one vector of Rect per layer ID
    int next_shape_id_ = 0;
};

}  // namespace layoutagent
