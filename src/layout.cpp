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
    if (id < 0 || id >= static_cast<int>(id_to_name_.size())) {
        throw std::out_of_range("Unknown layer id: " + std::to_string(id));
    }
    return id_to_name_[id];
}

}  // namespace layoutagent
