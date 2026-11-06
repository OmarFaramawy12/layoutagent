#include "checks.hpp"

#include <algorithm>  // std::min
#include <cstddef>    // std::size_t
#include <optional>
#include <stdexcept>
#include <string>

#include "geometry.hpp"
#include "rect.hpp"

namespace layoutagent {

namespace {

// Rule values (W, S) must be in (0, 2 * kMaxAbsCoord]. 2 * kMaxAbsCoord is the largest
// possible rect size or gap, and its square (4e18) still fits in int64_t.
// This function is only visible inside this .cpp file (anonymous namespace).
void check_rule_value(std::int64_t value, const std::string& rule_name) {
    if (value <= 0 || value > 2 * kMaxAbsCoord) {
        throw std::invalid_argument(rule_name + " must be in (0, " +
                                    std::to_string(2 * kMaxAbsCoord) +
                                    "], got " + std::to_string(value));
    }
}

// True if the two rects share positive area (a negative gap on both axes).
// Touching along an edge or at a corner is not an overlap.
bool overlaps(const Rect& a, const Rect& b) {
    return gap_x(a, b) < 0 && gap_y(a, b) < 0;
}

// Checks a window with the Rect rules (x1 < x2, y1 < y2, coordinates within +/- kMaxAbsCoord)
// by building a Rect: its constructor does the validation. The layer and shape IDs mean
// nothing for a window, so they are -1. The error message talks about the window, because
// the Rect message would mention a "shape -1".
Rect make_window(std::int64_t x1, std::int64_t y1, std::int64_t x2, std::int64_t y2) {
    try {
        return Rect(x1, y1, x2, y2, -1, -1);
    } catch (const std::invalid_argument&) {
        throw std::invalid_argument(
            "Invalid window: need x1 < x2 and y1 < y2, with all values within +/-" +
            std::to_string(kMaxAbsCoord) + ", got x1=" + std::to_string(x1) +
            " y1=" + std::to_string(y1) + " x2=" + std::to_string(x2) +
            " y2=" + std::to_string(y2));
    }
}

}  // namespace

std::vector<Violation> check_width(const Layout& layout, int layer_id,
                                   std::int64_t min_width) {
    check_rule_value(min_width, "Width rule");

    std::vector<Violation> result;
    for (const Rect& rect : layout.rects(layer_id)) {
        const std::int64_t narrowest_side = std::min(rect.width(), rect.height());
        if (narrowest_side < min_width) {
            result.push_back({.type = ViolationType::MinWidth,
                              .layer_a = layer_id,
                              .layer_b = layer_id,
                              .first_shape_id = rect.shape_id(),
                              .second_shape_id = std::nullopt,
                              .measured = narrowest_side,
                              .required = min_width});
        }
    }
    return result;
}

std::vector<Violation> check_spacing(const Layout& layout, int layer_id,
                                     std::int64_t min_spacing) {
    check_rule_value(min_spacing, "Spacing rule");

    const std::vector<Rect>& rects = layout.rects(layer_id);
    const std::int64_t required = min_spacing * min_spacing;

    std::vector<Violation> result;
    for (std::size_t i = 0; i < rects.size(); ++i) {
        for (std::size_t j = i + 1; j < rects.size(); ++j) {
            const std::int64_t distance_sq = squared_distance(rects[i], rects[j]);
            if (distance_sq < required) {
                result.push_back({.type = ViolationType::MinSpacing,
                                  .layer_a = layer_id,
                                  .layer_b = layer_id,
                                  .first_shape_id = rects[i].shape_id(),
                                  .second_shape_id = rects[j].shape_id(),
                                  .measured = distance_sq,
                                  .required = required});
            }
        }
    }
    return result;
}

std::vector<Violation> check_overlap(const Layout& layout, int layer_a, int layer_b) {
    if (layer_a == layer_b) {
        throw std::invalid_argument(
            "check_overlap needs two different layers, got layer " +
            std::to_string(layer_a) + " twice");
    }

    const std::vector<Rect>& rects_a = layout.rects(layer_a);
    const std::vector<Rect>& rects_b = layout.rects(layer_b);

    std::vector<Violation> result;
    for (const Rect& a : rects_a) {
        for (const Rect& b : rects_b) {
            if (overlaps(a, b)) {
                // Both gaps are negative here, and minus a gap is the size of the shared
                // part along that axis. So the product of the two gaps is the area.
                const std::int64_t overlap_area = gap_x(a, b) * gap_y(a, b);
                result.push_back({.type = ViolationType::Overlap,
                                  .layer_a = layer_a,
                                  .layer_b = layer_b,
                                  .first_shape_id = a.shape_id(),
                                  .second_shape_id = b.shape_id(),
                                  .measured = overlap_area,
                                  .required = 0});
            }
        }
    }
    return result;
}

std::vector<int> window_query(const Layout& layout, int layer_id, std::int64_t x1,
                              std::int64_t y1, std::int64_t x2, std::int64_t y2) {
    const Rect window = make_window(x1, y1, x2, y2);

    std::vector<int> ids;
    for (const Rect& rect : layout.rects(layer_id)) {
        if (overlaps(rect, window)) {
            ids.push_back(rect.shape_id());
        }
    }
    return ids;
}

}  // namespace layoutagent
