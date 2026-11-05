#pragma once

#include <string>
#include <unordered_map>
#include <vector>

namespace layoutagent {

// Holds the layers of a layout. Layer names are converted to integer IDs;
// both directions are kept: name -> ID and ID -> name.
class Layout {
public:
    // Adds a layer and returns its ID. IDs start at 0 and go up by one.
    // Throws std::invalid_argument if the name already exists.
    int add_layer(const std::string& name);

    // Throws std::out_of_range if the name / ID is unknown.
    int layer_id(const std::string& name) const;
    const std::string& layer_name(int id) const;

private:
    std::unordered_map<std::string, int> name_to_id_;
    std::vector<std::string> id_to_name_;  // index in this vector is the layer ID
};

}  // namespace layoutagent
