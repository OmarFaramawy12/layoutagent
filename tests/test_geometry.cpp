#include <gtest/gtest.h>

#include <cstdint>

#include "geometry.hpp"
#include "rect.hpp"

using layoutagent::dx;
using layoutagent::dy;
using layoutagent::gap_1d;
using layoutagent::gap_x;
using layoutagent::gap_y;
using layoutagent::kMaxAbsCoord;
using layoutagent::Rect;
using layoutagent::squared_distance;

// ---- gap_1d(a1, a2, b1, b2): interval [a1,a2] versus interval [b1,b2] ----

TEST(Gap1D, SeparatedIsPositive) {
    EXPECT_EQ(gap_1d(0, 10, 15, 25), 5);
}

TEST(Gap1D, TouchingIsZero) {
    EXPECT_EQ(gap_1d(0, 10, 10, 20), 0);
}

TEST(Gap1D, PartialOverlapIsNegative) {
    EXPECT_EQ(gap_1d(0, 10, 5, 15), -5);
}

TEST(Gap1D, ContainmentIsNegative) {
    // [40,60] sits inside [0,100]: gap = max(0,40) - min(100,60) = 40 - 60
    EXPECT_EQ(gap_1d(0, 100, 40, 60), -20);
}

TEST(Gap1D, IsSymmetric) {
    EXPECT_EQ(gap_1d(0, 10, 15, 25), gap_1d(15, 25, 0, 10));
    EXPECT_EQ(gap_1d(0, 10, 5, 15), gap_1d(5, 15, 0, 10));
}

TEST(Gap1D, WorksWithNegativeCoordinates) {
    EXPECT_EQ(gap_1d(-20, -10, -5, 5), 5);
}

// ---- gap_x / gap_y on rectangles ----

TEST(RectGap, SeparatedInXOnly) {
    Rect a(0, 0, 10, 10, 0, 0);
    Rect b(15, 0, 25, 10, 0, 1);
    EXPECT_EQ(gap_x(a, b), 5);
    EXPECT_EQ(gap_y(a, b), -10);  // same y range, so full overlap in y
}

TEST(RectGap, SeparatedInYOnly) {
    Rect a(0, 0, 10, 10, 0, 0);
    Rect b(0, 14, 10, 20, 0, 1);
    EXPECT_EQ(gap_x(a, b), -10);
    EXPECT_EQ(gap_y(a, b), 4);
}

// ---- dx / dy: the gap clamped to zero ----

TEST(DxDy, SeparatedGivesTheGap) {
    Rect a(0, 0, 10, 10, 0, 0);
    Rect b(13, 14, 20, 20, 0, 1);
    EXPECT_EQ(dx(a, b), 3);
    EXPECT_EQ(dy(a, b), 4);
}

TEST(DxDy, OverlapClampsToZero) {
    Rect a(0, 0, 10, 10, 0, 0);
    Rect b(5, 5, 15, 15, 0, 1);
    EXPECT_EQ(dx(a, b), 0);
    EXPECT_EQ(dy(a, b), 0);
}

TEST(DxDy, TouchingIsZero) {
    Rect a(0, 0, 10, 10, 0, 0);
    Rect b(10, 0, 20, 10, 0, 1);
    EXPECT_EQ(dx(a, b), 0);
    EXPECT_EQ(dy(a, b), 0);
}

// ---- squared_distance ----

TEST(SquaredDistance, DiagonalIsThreeFourFive) {
    Rect a(0, 0, 10, 10, 0, 0);
    Rect b(13, 14, 20, 20, 0, 1);
    EXPECT_EQ(squared_distance(a, b), 25);  // 3*3 + 4*4
}

TEST(SquaredDistance, SeparatedInOneAxisOnly) {
    Rect a(0, 0, 10, 10, 0, 0);
    Rect b(15, 0, 25, 10, 0, 1);
    EXPECT_EQ(squared_distance(a, b), 25);  // 5*5 + 0
}

TEST(SquaredDistance, TouchingIsZero) {
    Rect a(0, 0, 10, 10, 0, 0);
    Rect b(10, 0, 20, 10, 0, 1);
    EXPECT_EQ(squared_distance(a, b), 0);
}

TEST(SquaredDistance, OverlapIsZero) {
    Rect a(0, 0, 10, 10, 0, 0);
    Rect b(5, 5, 15, 15, 0, 1);
    EXPECT_EQ(squared_distance(a, b), 0);
}

TEST(SquaredDistance, ContainmentIsZero) {
    Rect a(0, 0, 100, 100, 0, 0);
    Rect b(40, 40, 60, 60, 0, 1);
    EXPECT_EQ(squared_distance(a, b), 0);
}

TEST(SquaredDistance, IsSymmetric) {
    Rect a(0, 0, 10, 10, 0, 0);
    Rect b(13, 14, 20, 20, 0, 1);
    EXPECT_EQ(squared_distance(a, b), squared_distance(b, a));
}

TEST(SquaredDistance, ExtremeCoordinatesDoNotOverflow) {
    // Opposite corners of the allowed coordinate range.
    Rect a(-kMaxAbsCoord, -kMaxAbsCoord, -kMaxAbsCoord + 1, -kMaxAbsCoord + 1, 0, 0);
    Rect b(kMaxAbsCoord - 1, kMaxAbsCoord - 1, kMaxAbsCoord, kMaxAbsCoord, 0, 1);
    const std::int64_t d = 2 * kMaxAbsCoord - 2;  // gap in both x and y
    EXPECT_EQ(dx(a, b), d);
    EXPECT_EQ(dy(a, b), d);
    EXPECT_EQ(squared_distance(a, b), d * d + d * d);  // about 8e18, still < 9.22e18
}
