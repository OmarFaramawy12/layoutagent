#pragma once

#include <algorithm>  // std::max, std::min
#include <cstdint>

#include "rect.hpp"

namespace layoutagent {

// Gap between interval [a1, a2] and interval [b1, b2].
// Negative = overlap, zero = touching, positive = empty space between them.
inline std::int64_t gap_1d(std::int64_t a1, std::int64_t a2,
                           std::int64_t b1, std::int64_t b2) {
    return std::max(a1, b1) - std::min(a2, b2);
}

inline std::int64_t gap_x(const Rect& a, const Rect& b) {
    return gap_1d(a.x1(), a.x2(), b.x1(), b.x2());
}

inline std::int64_t gap_y(const Rect& a, const Rect& b) {
    return gap_1d(a.y1(), a.y2(), b.y1(), b.y2());
}

// Gap clamped to zero: overlapping or touching means no distance along that axis.
inline std::int64_t dx(const Rect& a, const Rect& b) {
    return std::max<std::int64_t>(0, gap_x(a, b));
}

inline std::int64_t dy(const Rect& a, const Rect& b) {
    return std::max<std::int64_t>(0, gap_y(a, b));
}

// Squared Euclidean distance between two rectangles (no sqrt).
// Cannot overflow int64_t because every coordinate is bounded by kMaxAbsCoord.
inline std::int64_t squared_distance(const Rect& a, const Rect& b) {
    const std::int64_t x = dx(a, b);
    const std::int64_t y = dy(a, b);
    return x * x + y * y;
}

}  // namespace layoutagent
