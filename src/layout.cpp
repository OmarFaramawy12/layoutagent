#include "layout.hpp"

#include <stdexcept>

namespace layoutagent {

int Layout::add_layer(const std::string& name) {
    if (name_to_id_.contains(name)) {
        throw std::invalid_argument("Duplicate layer name: " + name);
    }
    const int id = static_cast<int>(id_to_name_.size());
    name_to_id_[name] = id;
    id_to_name_.push_back(name);
    layer_rects_.emplace_back();  // an empty vector<Rect> for the new layer
    return id;
}

int Layout::layer_id(const std::string& name) const {
    const auto it = name_to_id_.find(name);
    if (it == name_to_id_.end()) {
        throw std::out_of_range("Unknown layer name: " + name);
    }
    return it->second;
}

const std::string& Layout::layer_name(int id) const {
    check_layer_id(id);
    return id_to_name_[id];
}

int Layout::add_rect(int layer_id, std::int64_t x1, std::int64_t y1,
                     std::int64_t x2, std::int64_t y2) {
    check_layer_id(layer_id);
    // The Rect constructor validates the coordinates and throws if they are bad.
    // Only after it succeeds do we store the rect and use up the shape ID.
    const Rect rect(x1, y1, x2, y2, layer_id, next_shape_id_);
    layer_rects_[layer_id].push_back(rect);
    return next_shape_id_++;
}

const std::vector<Rect>& Layout::rects(int layer_id) const {
    check_layer_id(layer_id);
    return layer_rects_[layer_id];
}

void Layout::check_layer_id(int id) const {
    if (id < 0 || id >= static_cast<int>(id_to_name_.size())) {
        throw std::out_of_range("Unknown layer id: " + std::to_string(id));
    }
}

}  // namespace layoutagent
