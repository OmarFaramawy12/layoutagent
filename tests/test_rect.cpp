#include <gtest/gtest.h>

#include <stdexcept>
#include <vector>

#include "rect.hpp"

using layoutagent::KMaxAbsCoordinate;
using layoutagent::Rect;

TEST(Rect, StoresValues) {
    Rect r(1, 2, 11, 7, 3, 42);
    EXPECT_EQ(r.x1(), 1);
    EXPECT_EQ(r.y1(), 2);
    EXPECT_EQ(r.x2(), 11);
    EXPECT_EQ(r.y2(), 7);
    EXPECT_EQ(r.layer_id(), 3);
    EXPECT_EQ(r.shape_id(), 42);
}

TEST(Rect, WidthAndHeight) {
    Rect r(1, 2, 11, 7, 0, 0);
    EXPECT_EQ(r.width(), 10);
    EXPECT_EQ(r.height(), 5);
}

TEST(Rect, ZeroWidthThrows) {
    EXPECT_THROW(Rect(5, 0, 5, 10, 0, 0), std::invalid_argument);
}

TEST(Rect, ZeroHeightThrows) {
    EXPECT_THROW(Rect(0, 5, 10, 5, 0, 0), std::invalid_argument);
}

TEST(Rect, ReversedXThrows) {
    EXPECT_THROW(Rect(10, 0, 5, 10, 0, 0), std::invalid_argument);
}

TEST(Rect, ReversedYThrows) {
    EXPECT_THROW(Rect(0, 10, 10, 5, 0, 0), std::invalid_argument);
}

TEST(Rect, NegativeCoordinatesAreValid) {
    EXPECT_NO_THROW(Rect(-50, -30, -10, -5, 0, 0));
}

TEST(Rect, CoordinatesAtTheLimitAreValid) {
    EXPECT_NO_THROW(Rect(-kMaxAbsCoord, -kMaxAbsCoord,
                         kMaxAbsCoord, kMaxAbsCoord, 0, 0));
}

TEST(Rect, CoordinatesBeyondTheLimitThrow) {
    EXPECT_THROW(Rect(0, 0, kMaxAbsCoord + 1, 10, 0, 0), std::invalid_argument);
    EXPECT_THROW(Rect(-kMaxAbsCoord - 1, 0, 10, 10, 0, 0), std::invalid_argument);
}

TEST(Rect, CanBeCopiedAssignedAndStoredInVector) {
    Rect a(0, 0, 10, 10, 1, 1);
    Rect b(20, 20, 30, 30, 2, 2);
    a = b;  // fails to compile if the data members are const
    EXPECT_EQ(a.x1(), 20);

    std::vector<Rect> v;
    v.push_back(a);
    v.push_back(b);
    EXPECT_EQ(v.size(), 2u);
}