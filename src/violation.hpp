#pragma once

#include <cstdint>
#include <optional>

namespace layoutagent {

enum class ViolationType {
    MinWidth,
    MinSpacing,
    Overlap,
};

// One rule violation found by a check. The same struct is used for every check.
// - Width and spacing are same-layer checks, so layer_a == layer_b.
// - second_shape_id is empty when only one shape is involved (width).
// - Spacing: measured is the squared distance, required is S*S.
struct Violation {
    ViolationType type;
    int layer_a;
    int layer_b;
    int first_shape_id;
    std::optional<int> second_shape_id;
    std::int64_t measured;
    std::int64_t required;
};

}  // namespace layoutagent
