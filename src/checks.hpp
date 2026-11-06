#pragma once

#include <cstdint>
#include <vector>

#include "layout.hpp"
#include "violation.hpp"

namespace layoutagent {

// Minimum width check on one layer: a shape violates the rule if
// min(width(), height()) < min_width. A side exactly equal to min_width is allowed.
// Violations come back in the order the shapes were added to the layer.
// Throws std::invalid_argument if min_width is not in (0, 2 * kMaxAbsCoord],
// and std::out_of_range if the layer ID is unknown.
std::vector<Violation> check_width(const Layout& layout, int layer_id,
                                   std::int64_t min_width);

// Minimum spacing check on one layer (naive O(n^2) over pairs i < j).
// A pair violates the rule if squared_distance(a, b) < min_spacing^2: a distance
// exactly equal to min_spacing is allowed, touching or overlapping shapes (distance 0)
// are violations. Only shapes on the same layer are compared.
// measured = squared distance, required = min_spacing^2. Violations come back ordered
// by the first shape, then the second, in the order the shapes were added.
// Throws std::invalid_argument if min_spacing is not in (0, 2 * kMaxAbsCoord],
// and std::out_of_range if the layer ID is unknown.
std::vector<Violation> check_spacing(const Layout& layout, int layer_id,
                                     std::int64_t min_spacing);

// Cross-layer overlap check (naive O(n*m)): reports every pair (a on layer_a, b on layer_b)
// that shares positive area, i.e. gap_x < 0 and gap_y < 0. Touching along an edge or at
// a corner is not an overlap. Overlaps inside one layer are not reported.
// first_shape_id is the shape on layer_a, second_shape_id the shape on layer_b.
// measured is the overlap area (at most (2 * kMaxAbsCoord)^2 = 4e18, which fits in
// int64_t); required is 0.
// Violations come back ordered by the layer_a shape, then the layer_b shape.
// Throws std::invalid_argument if layer_a == layer_b,
// and std::out_of_range if a layer ID is unknown.
std::vector<Violation> check_overlap(const Layout& layout, int layer_a, int layer_b);

// Window query: returns the shape IDs of the shapes on one layer that share positive area
// with the window (x1, y1) - (x2, y2). Touching the window along an edge or at a corner
// is not inside. The IDs are the global shape IDs, in the order the shapes were added.
// The window follows the Rect rules (x1 < x2, y1 < y2, coordinates within +/- kMaxAbsCoord).
// Throws std::invalid_argument ("Invalid window: ...") if the window is invalid,
// and std::out_of_range if the layer ID is unknown.
std::vector<int> window_query(const Layout& layout, int layer_id, std::int64_t x1,
                              std::int64_t y1, std::int64_t x2, std::int64_t y2);

}  // namespace layoutagent
