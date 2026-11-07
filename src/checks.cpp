#include "checks.hpp"

#include <algorithm>  // std::min, std::max, std::sort, std::unique
#include <cstddef>    // std::size_t
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>    // std::pair

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

// A grid cell (column, row).
using Cell = std::pair<std::int64_t, std::int64_t>;

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

std::vector<Violation> check_spacing_grid(const Layout& layout, int layer_id,
                                          std::int64_t min_spacing) {
    check_rule_value(min_spacing, "Spacing rule");

    const std::vector<Rect>& rects = layout.rects(layer_id);
    const std::int64_t required = min_spacing * min_spacing;

    // Cell size: at least the rule value, and at least the largest side of any shape, so a
    // shape covers at most 2 x 2 cells (memory stays small). A layer with one huge shape gets
    // huge cells: slower, but still correct.
    std::int64_t cell_size = min_spacing;
    for (const Rect& rect : rects) {
        cell_size = std::max(cell_size, std::max(rect.width(), rect.height()));
    }

    // Cell of a coordinate = coordinate / cell_size. C++ integer division rounds toward ZERO,
    // so -5 / 10 is 0, like +5 / 10: cell 0 is simply twice as wide as the others. That is fine:
    // a bigger coordinate never gets a smaller cell number, so two shapes that overlap in
    // space always get overlapping ranges of cells, which is all the search below needs.

    // The grid: for every cell, the indexes (into `rects`) of the shapes that touch it.
    // std::map with a pair as key needs no hash function (pairs compare with <).
    std::map<Cell, std::vector<std::size_t>> grid;
    for (std::size_t i = 0; i < rects.size(); ++i) {
        const Rect& rect = rects[i];
        for (std::int64_t column = rect.x1() / cell_size;
             column <= rect.x2() / cell_size; ++column) {
            for (std::int64_t row = rect.y1() / cell_size;
                 row <= rect.y2() / cell_size; ++row) {
                grid[{column, row}].push_back(i);
            }
        }
    }

    // For every shape i: collect the shapes j > i that share a cell with i's search box
    // (i grown by min_spacing on every side), then run the exact test on those only.
    // A pair closer than min_spacing has gaps below min_spacing on both axes, so j always
    // touches the search box and the two share a cell: the grid never misses a violation.
    std::vector<Violation> result;
    std::vector<std::size_t> candidates;  // reused for every i, so it is allocated rarely
    for (std::size_t i = 0; i < rects.size(); ++i) {
        const Rect& a = rects[i];
        candidates.clear();
        for (std::int64_t column = (a.x1() - min_spacing) / cell_size;
             column <= (a.x2() + min_spacing) / cell_size; ++column) {
            for (std::int64_t row = (a.y1() - min_spacing) / cell_size;
                 row <= (a.y2() + min_spacing) / cell_size; ++row) {
                const auto cell = grid.find({column, row});
                if (cell == grid.end()) {
                    continue;  // nothing in this cell
                }
                for (const std::size_t j : cell->second) {
                    if (j > i) {
                        candidates.push_back(j);
                    }
                }
            }
        }
        // A shape in several cells is found several times; sorting and removing the repeats
        // also puts the candidates in the order the naive check visits them (j ascending).
        std::sort(candidates.begin(), candidates.end());
        candidates.erase(std::unique(candidates.begin(), candidates.end()), candidates.end());

        for (const std::size_t j : candidates) {
            const std::int64_t distance_sq = squared_distance(a, rects[j]);
            if (distance_sq < required) {
                result.push_back({.type = ViolationType::MinSpacing,
                                  .layer_a = layer_id,
                                  .layer_b = layer_id,
                                  .first_shape_id = a.shape_id(),
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
