// Tests for check_spacing_grid. The naive check_spacing is the reference: the grid version
// must return exactly the same violations, in the same order.

#include <gtest/gtest.h>

#include <cstdint>
#include <random>
#include <stdexcept>
#include <vector>

#include "checks.hpp"
#include "layout.hpp"
#include "rect.hpp"
#include "violation.hpp"

using layoutagent::check_spacing;
using layoutagent::check_spacing_grid;
using layoutagent::kMaxAbsCoord;
using layoutagent::Layout;
using layoutagent::Violation;

namespace {

// Fails the test if the grid result differs from the naive result in any field or in order.
// Returns the number of violations so a test can also check it is not trivially zero.
std::size_t expect_same_as_naive(const Layout& layout, int layer_id, std::int64_t min_spacing) {
    const std::vector<Violation> naive = check_spacing(layout, layer_id, min_spacing);
    const std::vector<Violation> grid = check_spacing_grid(layout, layer_id, min_spacing);

    EXPECT_EQ(grid.size(), naive.size());
    for (std::size_t i = 0; i < naive.size() && i < grid.size(); ++i) {
        EXPECT_EQ(grid[i].type, naive[i].type) << "violation " << i;
        EXPECT_EQ(grid[i].layer_a, naive[i].layer_a) << "violation " << i;
        EXPECT_EQ(grid[i].layer_b, naive[i].layer_b) << "violation " << i;
        EXPECT_EQ(grid[i].first_shape_id, naive[i].first_shape_id) << "violation " << i;
        EXPECT_EQ(grid[i].second_shape_id, naive[i].second_shape_id) << "violation " << i;
        EXPECT_EQ(grid[i].measured, naive[i].measured) << "violation " << i;
        EXPECT_EQ(grid[i].required, naive[i].required) << "violation " << i;
    }
    return naive.size();
}

// `count` random rects with lower-left corners in [low, high]^2 and sides in [1, max_side].
Layout random_layout(unsigned seed, int count, std::int64_t low, std::int64_t high,
                     std::int64_t max_side) {
    std::mt19937 random(seed);  // the same seed always gives the same layout
    std::uniform_int_distribution<std::int64_t> position(low, high);
    std::uniform_int_distribution<std::int64_t> side(1, max_side);

    Layout layout;
    const int m1 = layout.add_layer("metal1");
    for (int i = 0; i < count; ++i) {
        const std::int64_t x = position(random);
        const std::int64_t y = position(random);
        layout.add_rect(m1, x, y, x + side(random), y + side(random));
    }
    return layout;
}

}  // namespace

TEST(CheckSpacingGrid, EmptyLayerHasNoViolations) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_TRUE(check_spacing_grid(layout, m1, 10).empty());
}

TEST(CheckSpacingGrid, OneShapeHasNoViolations) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    EXPECT_TRUE(check_spacing_grid(layout, m1, 10).empty());
}

TEST(CheckSpacingGrid, FindsAClosePairAndReportsTheSquaredDistance) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m1, 15, 0, 25, 10);  // gap 5

    const auto result = check_spacing_grid(layout, m1, 10);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].first_shape_id, 0);
    EXPECT_EQ(result[0].second_shape_id, 1);
    EXPECT_EQ(result[0].measured, 25);
    EXPECT_EQ(result[0].required, 100);
}

TEST(CheckSpacingGrid, ADistanceExactlyEqualToTheRuleIsAllowed) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m1, 20, 0, 30, 10);  // gap exactly 10
    EXPECT_EQ(expect_same_as_naive(layout, m1, 10), 0u);
    EXPECT_EQ(expect_same_as_naive(layout, m1, 11), 1u);
}

TEST(CheckSpacingGrid, TouchingAndOverlappingShapesAreViolations) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m1, 10, 0, 20, 10);   // touches the first along an edge
    layout.add_rect(m1, 5, 5, 15, 15);    // overlaps both
    layout.add_rect(m1, 30, 30, 40, 40);  // touches nothing and is far away
    EXPECT_EQ(expect_same_as_naive(layout, m1, 10), 3u);
}

TEST(CheckSpacingGrid, DiagonalDistanceIsEuclidean) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m1, 17, 17, 27, 27);  // dx = dy = 7: 49 + 49 = 98 < 100
    layout.add_rect(m1, 100, 0, 110, 10);
    layout.add_rect(m1, 118, 18, 128, 28);  // dx = dy = 8: 64 + 64 = 128 >= 100
    EXPECT_EQ(expect_same_as_naive(layout, m1, 10), 1u);
}

TEST(CheckSpacingGrid, ShapesOnOtherLayersAreIgnored) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int m2 = layout.add_layer("metal2");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m2, 11, 0, 21, 10);  // very close, but on another layer
    EXPECT_TRUE(check_spacing_grid(layout, m1, 10).empty());
    EXPECT_TRUE(check_spacing_grid(layout, m2, 10).empty());
}

// The grid divides coordinates by the cell size, and C++ "/" rounds toward zero (-5 / 10 is 0).
// These pairs sit on both sides of the axes and entirely in negative coordinates, where that
// rounding is easy to get wrong.
TEST(CheckSpacingGrid, PairsAroundTheOriginAndInNegativeCoordinates) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, -12, -5, -2, 5);   // left of the y axis
    layout.add_rect(m1, 3, -5, 13, 5);     // right of it: gap 5
    layout.add_rect(m1, -5, -30, 5, -20);  // below the x axis
    layout.add_rect(m1, -5, 22, 5, 32);    // above it, far from the others
    layout.add_rect(m1, -105, -105, -95, -95);
    layout.add_rect(m1, -92, -105, -82, -95);  // gap 3, entirely negative
    EXPECT_EQ(expect_same_as_naive(layout, m1, 10), 2u);
}

TEST(CheckSpacingGrid, IdenticalShapesAreEachOthersViolations) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    for (int i = 0; i < 20; ++i) {
        layout.add_rect(m1, 0, 0, 10, 10);
    }
    EXPECT_EQ(expect_same_as_naive(layout, m1, 10), 190u);  // 20 * 19 / 2 pairs
}

TEST(CheckSpacingGrid, AGiantShapeAmongSmallOnesIsStillCorrect) {
    Layout layout = random_layout(7, 100, 0, 1000, 20);
    const int m1 = 0;
    layout.add_rect(m1, -kMaxAbsCoord, -kMaxAbsCoord, kMaxAbsCoord, kMaxAbsCoord);
    // The giant shape overlaps all 100 small ones; some small ones are also close to each other.
    EXPECT_GE(expect_same_as_naive(layout, m1, 10), 100u);
}

TEST(CheckSpacingGrid, CoordinatesAtTheLimitsDoNotOverflow) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, kMaxAbsCoord - 10, kMaxAbsCoord - 10, kMaxAbsCoord, kMaxAbsCoord);
    layout.add_rect(m1, kMaxAbsCoord - 30, kMaxAbsCoord - 10, kMaxAbsCoord - 20, kMaxAbsCoord);
    layout.add_rect(m1, -kMaxAbsCoord, -kMaxAbsCoord, -kMaxAbsCoord + 10, -kMaxAbsCoord + 10);
    layout.add_rect(m1, -kMaxAbsCoord + 15, -kMaxAbsCoord, -kMaxAbsCoord + 25, -kMaxAbsCoord + 10);

    EXPECT_EQ(expect_same_as_naive(layout, m1, 10), 1u);  // only the pair with gap 5
    EXPECT_EQ(expect_same_as_naive(layout, m1, 11), 2u);  // the gap-10 pair is now too close
    expect_same_as_naive(layout, m1, 2 * kMaxAbsCoord);   // the largest allowed rule value
}

TEST(CheckSpacingGrid, ShapesFarApartInAHugeSparseLayout) {
    Layout layout = random_layout(3, 200, -kMaxAbsCoord, kMaxAbsCoord - 100, 100);
    expect_same_as_naive(layout, 0, 50);
}

// Many random layouts, dense enough that most have violations. Both rule values are used so
// the cell size is chosen by the rule (small S) and by the largest shape (large shapes).
TEST(CheckSpacingGrid, RandomDenseLayoutsMatchNaive) {
    std::size_t total_violations = 0;
    for (unsigned seed = 1; seed <= 20; ++seed) {
        const Layout layout = random_layout(seed, 300, -500, 500, 60);
        for (const std::int64_t rule : {1, 10, 37, 200}) {
            total_violations += expect_same_as_naive(layout, 0, rule);
        }
    }
    EXPECT_GT(total_violations, 1000u);  // the comparison is not trivially "both empty"
}

TEST(CheckSpacingGrid, RandomSparseLayoutsMatchNaive) {
    for (unsigned seed = 1; seed <= 10; ++seed) {
        const Layout layout = random_layout(seed, 300, -100000, 100000, 60);
        for (const std::int64_t rule : {10, 500}) {
            expect_same_as_naive(layout, 0, rule);
        }
    }
}

TEST(CheckSpacingGrid, RuleValueMustBeInRange) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    EXPECT_THROW(check_spacing_grid(layout, m1, 0), std::invalid_argument);
    EXPECT_THROW(check_spacing_grid(layout, m1, -5), std::invalid_argument);
    EXPECT_THROW(check_spacing_grid(layout, m1, 2 * kMaxAbsCoord + 1), std::invalid_argument);
    EXPECT_NO_THROW(check_spacing_grid(layout, m1, 2 * kMaxAbsCoord));
}

TEST(CheckSpacingGrid, UnknownLayerThrows) {
    Layout layout;
    layout.add_layer("metal1");
    EXPECT_THROW(check_spacing_grid(layout, 3, 10), std::out_of_range);
}
