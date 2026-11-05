#include <gtest/gtest.h>

#include <stdexcept>

#include "checks.hpp"
#include "layout.hpp"
#include "rect.hpp"
#include "violation.hpp"

using layoutagent::check_overlap;
using layoutagent::check_spacing;
using layoutagent::check_width;
using layoutagent::kMaxAbsCoord;
using layoutagent::Layout;
using layoutagent::window_query;
using layoutagent::ViolationType;

// ---- check_width ----

TEST(CheckWidth, NoViolationWhenAllShapesAreWideEnough) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 100, 100);
    layout.add_rect(m1, 200, 0, 300, 60);

    EXPECT_TRUE(check_width(layout, m1, 50).empty());
}

TEST(CheckWidth, EmptyLayerHasNoViolations) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_TRUE(check_width(layout, m1, 50).empty());
}

TEST(CheckWidth, NarrowInXIsFlagged) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 30, 100);  // width 30, height 100

    const auto result = check_width(layout, m1, 50);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].measured, 30);
}

TEST(CheckWidth, NarrowInYIsFlagged) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 100, 20);  // width 100, height 20

    const auto result = check_width(layout, m1, 50);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].measured, 20);
}

TEST(CheckWidth, ExactlyTheMinimumIsAllowed) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 50, 100);  // min side is exactly W
    EXPECT_TRUE(check_width(layout, m1, 50).empty());
}

TEST(CheckWidth, OneBelowTheMinimumIsFlagged) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 49, 100);
    EXPECT_EQ(check_width(layout, m1, 50).size(), 1u);
}

TEST(CheckWidth, ViolationFieldsAreFilledIn) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 100, 100);         // shape 0, fine
    const int bad = layout.add_rect(m1, 0, 200, 30, 300);  // shape 1, too narrow

    const auto result = check_width(layout, m1, 50);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].type, ViolationType::MinWidth);
    EXPECT_EQ(result[0].layer_a, m1);
    EXPECT_EQ(result[0].layer_b, m1);
    EXPECT_EQ(result[0].first_shape_id, bad);
    EXPECT_FALSE(result[0].second_shape_id.has_value());
    EXPECT_EQ(result[0].measured, 30);
    EXPECT_EQ(result[0].required, 50);
}

TEST(CheckWidth, ReportsEveryViolatingShapeInInsertionOrder) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 100);     // shape 0, bad
    layout.add_rect(m1, 50, 0, 150, 100);   // shape 1, fine
    layout.add_rect(m1, 200, 0, 300, 20);   // shape 2, bad

    const auto result = check_width(layout, m1, 50);
    ASSERT_EQ(result.size(), 2u);
    EXPECT_EQ(result[0].first_shape_id, 0);
    EXPECT_EQ(result[1].first_shape_id, 2);
}

TEST(CheckWidth, OnlyLooksAtTheRequestedLayer) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int m2 = layout.add_layer("metal2");
    layout.add_rect(m1, 0, 0, 100, 100);  // fine
    layout.add_rect(m2, 0, 0, 10, 100);   // too narrow, but on another layer

    EXPECT_TRUE(check_width(layout, m1, 50).empty());
    EXPECT_EQ(check_width(layout, m2, 50).size(), 1u);
}

TEST(CheckWidth, UnknownLayerThrows) {
    Layout layout;
    layout.add_layer("metal1");
    EXPECT_THROW(check_width(layout, 3, 50), std::out_of_range);
}

TEST(CheckWidth, RuleValueMustBePositiveAndBounded) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_THROW(check_width(layout, m1, 0), std::invalid_argument);
    EXPECT_THROW(check_width(layout, m1, -5), std::invalid_argument);
    EXPECT_THROW(check_width(layout, m1, 2 * kMaxAbsCoord + 1), std::invalid_argument);
    EXPECT_NO_THROW(check_width(layout, m1, 2 * kMaxAbsCoord));
}

// ---- check_spacing ----

TEST(CheckSpacing, FarApartShapesAreFine) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m1, 100, 0, 110, 10);
    EXPECT_TRUE(check_spacing(layout, m1, 10).empty());
}

TEST(CheckSpacing, EmptyLayerAndSingleShapeHaveNoViolations) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_TRUE(check_spacing(layout, m1, 10).empty());
    layout.add_rect(m1, 0, 0, 10, 10);
    EXPECT_TRUE(check_spacing(layout, m1, 10).empty());
}

TEST(CheckSpacing, DistanceExactlyEqualToSIsAllowed) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m1, 20, 0, 30, 10);  // gap of exactly 10
    EXPECT_TRUE(check_spacing(layout, m1, 10).empty());
}

TEST(CheckSpacing, OneBelowSIsFlagged) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m1, 19, 0, 29, 10);  // gap of 9

    const auto result = check_spacing(layout, m1, 10);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].measured, 81);  // 9 squared
}

TEST(CheckSpacing, TouchingShapesAreFlagged) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m1, 10, 0, 20, 10);  // shares an edge

    const auto result = check_spacing(layout, m1, 10);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].measured, 0);
}

TEST(CheckSpacing, OverlappingShapesAreFlagged) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m1, 5, 5, 15, 15);

    const auto result = check_spacing(layout, m1, 10);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].measured, 0);
}

TEST(CheckSpacing, DiagonalDistanceIsEuclidean) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m1, 13, 14, 20, 20);  // dx = 3, dy = 4, distance 5

    // Euclidean distance is exactly 5, so S = 5 is allowed. A "largest of
    // dx, dy" rule would measure 4 and wrongly flag it.
    EXPECT_TRUE(check_spacing(layout, m1, 5).empty());

    const auto result = check_spacing(layout, m1, 6);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].measured, 25);
    EXPECT_EQ(result[0].required, 36);
}

TEST(CheckSpacing, ViolationFieldsAreFilledIn) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);      // shape 0
    layout.add_rect(m1, 200, 0, 210, 10);   // shape 1, far from everything
    layout.add_rect(m1, 13, 14, 20, 20);    // shape 2, too close to shape 0

    const auto result = check_spacing(layout, m1, 10);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].type, ViolationType::MinSpacing);
    EXPECT_EQ(result[0].layer_a, m1);
    EXPECT_EQ(result[0].layer_b, m1);
    EXPECT_EQ(result[0].first_shape_id, 0);
    ASSERT_TRUE(result[0].second_shape_id.has_value());
    EXPECT_EQ(*result[0].second_shape_id, 2);
    EXPECT_EQ(result[0].measured, 25);    // squared distance
    EXPECT_EQ(result[0].required, 100);   // S*S
}

TEST(CheckSpacing, EachPairIsReportedOnceInOrder) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);    // shape 0
    layout.add_rect(m1, 12, 0, 22, 10);   // shape 1, gap 2 to shape 0
    layout.add_rect(m1, 24, 0, 34, 10);   // shape 2, gap 2 to shape 1, gap 14 to shape 0

    const auto result = check_spacing(layout, m1, 20);  // all three pairs are closer than 20
    ASSERT_EQ(result.size(), 3u);
    EXPECT_EQ(result[0].first_shape_id, 0);
    EXPECT_EQ(*result[0].second_shape_id, 1);
    EXPECT_EQ(result[1].first_shape_id, 0);
    EXPECT_EQ(*result[1].second_shape_id, 2);
    EXPECT_EQ(result[2].first_shape_id, 1);
    EXPECT_EQ(*result[2].second_shape_id, 2);
}

TEST(CheckSpacing, OnlyComparesShapesOnTheSameLayer) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int m2 = layout.add_layer("metal2");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m2, 5, 5, 15, 15);   // overlaps the metal1 shape, but another layer
    layout.add_rect(m2, 100, 0, 110, 10);

    EXPECT_TRUE(check_spacing(layout, m1, 10).empty());
    EXPECT_TRUE(check_spacing(layout, m2, 10).empty());
}

TEST(CheckSpacing, UnknownLayerThrows) {
    Layout layout;
    layout.add_layer("metal1");
    EXPECT_THROW(check_spacing(layout, 3, 10), std::out_of_range);
}

TEST(CheckSpacing, RuleValueMustBePositiveAndBounded) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_THROW(check_spacing(layout, m1, 0), std::invalid_argument);
    EXPECT_THROW(check_spacing(layout, m1, -5), std::invalid_argument);
    EXPECT_THROW(check_spacing(layout, m1, 2 * kMaxAbsCoord + 1), std::invalid_argument);
    EXPECT_NO_THROW(check_spacing(layout, m1, 2 * kMaxAbsCoord));
}

TEST(CheckSpacing, LargestRuleAndFarthestShapesDoNotOverflow) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, -kMaxAbsCoord, -kMaxAbsCoord, -kMaxAbsCoord + 1, -kMaxAbsCoord + 1);
    layout.add_rect(m1, kMaxAbsCoord - 1, kMaxAbsCoord - 1, kMaxAbsCoord, kMaxAbsCoord);

    // S*S = 4e18 and the squared distance is about 8e18: both fit in int64_t.
    // The distance (~2.83e9) is larger than S (2e9), so there is no violation.
    EXPECT_TRUE(check_spacing(layout, m1, 2 * kMaxAbsCoord).empty());
}

// ---- check_overlap ----

TEST(CheckOverlap, PartialOverlapAcrossLayersIsFlagged) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 100, 100);
    layout.add_rect(v1, 90, 90, 110, 110);  // overlaps the corner by 10 x 10

    EXPECT_EQ(check_overlap(layout, m1, v1).size(), 1u);
}

TEST(CheckOverlap, ContainmentIsFlagged) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 100, 100);
    layout.add_rect(v1, 40, 40, 60, 60);

    EXPECT_EQ(check_overlap(layout, m1, v1).size(), 1u);
}

TEST(CheckOverlap, DisjointShapesAreFine) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 100, 100);
    layout.add_rect(v1, 200, 200, 220, 220);
    layout.add_rect(v1, 50, 150, 60, 160);  // overlaps in x only, not in y

    EXPECT_TRUE(check_overlap(layout, m1, v1).empty());
}

TEST(CheckOverlap, SharingOnlyAnEdgeOrCornerIsNotOverlap) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 100, 100);
    layout.add_rect(v1, 100, 0, 120, 50);     // touches along an edge
    layout.add_rect(v1, 100, 100, 120, 120);  // touches at a corner only

    EXPECT_TRUE(check_overlap(layout, m1, v1).empty());
}

TEST(CheckOverlap, ViolationFieldsAreFilledIn) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 100, 100);   // shape 0
    layout.add_rect(v1, 40, 40, 60, 60);   // shape 1

    const auto result = check_overlap(layout, m1, v1);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].type, ViolationType::Overlap);
    EXPECT_EQ(result[0].layer_a, m1);
    EXPECT_EQ(result[0].layer_b, v1);
    EXPECT_EQ(result[0].first_shape_id, 0);
    ASSERT_TRUE(result[0].second_shape_id.has_value());
    EXPECT_EQ(*result[0].second_shape_id, 1);
    EXPECT_EQ(result[0].measured, 400);  // the via is 20 x 20 and fully inside
    EXPECT_EQ(result[0].required, 0);
}

TEST(CheckOverlap, MeasuredValueIsTheOverlapArea) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 100, 100);
    layout.add_rect(v1, 90, 80, 130, 150);  // overlap is x 90..100 (10) by y 80..100 (20)

    const auto result = check_overlap(layout, m1, v1);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].measured, 200);
}

TEST(CheckOverlap, AreaIsTheSameWhicheverLayerComesFirst) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 100, 100);
    layout.add_rect(v1, 90, 80, 130, 150);

    EXPECT_EQ(check_overlap(layout, m1, v1)[0].measured, 200);
    EXPECT_EQ(check_overlap(layout, v1, m1)[0].measured, 200);
}

TEST(CheckOverlap, LargestPossibleAreaDoesNotOverflow) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int m2 = layout.add_layer("metal2");
    layout.add_rect(m1, -kMaxAbsCoord, -kMaxAbsCoord, kMaxAbsCoord, kMaxAbsCoord);
    layout.add_rect(m2, -kMaxAbsCoord, -kMaxAbsCoord, kMaxAbsCoord, kMaxAbsCoord);

    const auto result = check_overlap(layout, m1, m2);
    ASSERT_EQ(result.size(), 1u);
    // (2e9) * (2e9) = 4e18, which still fits in int64_t (max about 9.22e18)
    EXPECT_EQ(result[0].measured, 4'000'000'000'000'000'000);
}

TEST(CheckOverlap, ArgumentOrderDecidesWhichShapeIsFirst) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 100, 100);   // shape 0
    layout.add_rect(v1, 40, 40, 60, 60);   // shape 1

    const auto result = check_overlap(layout, v1, m1);
    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].layer_a, v1);
    EXPECT_EQ(result[0].layer_b, m1);
    EXPECT_EQ(result[0].first_shape_id, 1);
    EXPECT_EQ(*result[0].second_shape_id, 0);
}

TEST(CheckOverlap, ReportsEveryPairInOrder) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 10, 10);      // shape 0
    layout.add_rect(m1, 100, 0, 110, 10);   // shape 1
    layout.add_rect(v1, 5, 5, 8, 8);        // shape 2, overlaps shape 0
    layout.add_rect(v1, 105, 5, 108, 8);    // shape 3, overlaps shape 1
    layout.add_rect(v1, 6, 6, 9, 9);        // shape 4, overlaps shape 0

    const auto result = check_overlap(layout, m1, v1);
    ASSERT_EQ(result.size(), 3u);
    EXPECT_EQ(result[0].first_shape_id, 0);
    EXPECT_EQ(*result[0].second_shape_id, 2);
    EXPECT_EQ(result[1].first_shape_id, 0);
    EXPECT_EQ(*result[1].second_shape_id, 4);
    EXPECT_EQ(result[2].first_shape_id, 1);
    EXPECT_EQ(*result[2].second_shape_id, 3);
}

TEST(CheckOverlap, IgnoresOverlapsInsideOneLayerAndOtherLayers) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    const int m2 = layout.add_layer("metal2");
    layout.add_rect(m1, 0, 0, 100, 100);
    layout.add_rect(m1, 50, 50, 150, 150);   // overlaps the other metal1 shape
    layout.add_rect(v1, 300, 300, 320, 320);  // far away
    layout.add_rect(m2, 0, 0, 100, 100);     // overlaps metal1, but we only compare m1 and v1

    EXPECT_TRUE(check_overlap(layout, m1, v1).empty());
}

TEST(CheckOverlap, EmptyLayerGivesNoViolations) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 100, 100);
    EXPECT_TRUE(check_overlap(layout, m1, v1).empty());
}

TEST(CheckOverlap, SameLayerTwiceThrows) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_THROW(check_overlap(layout, m1, m1), std::invalid_argument);
}

TEST(CheckOverlap, UnknownLayerThrows) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_THROW(check_overlap(layout, m1, 7), std::out_of_range);
    EXPECT_THROW(check_overlap(layout, 7, m1), std::out_of_range);
}

// ---- window_query ----

TEST(WindowQuery, ReturnsShapesThatIntersectTheWindow) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);        // shape 0, partly inside the window
    layout.add_rect(m1, 20, 0, 30, 10);       // shape 1, partly inside the window
    layout.add_rect(m1, 100, 100, 110, 110);  // shape 2, far away

    const std::vector<int> ids = window_query(layout, m1, 5, 5, 25, 8);
    ASSERT_EQ(ids.size(), 2u);
    EXPECT_EQ(ids[0], 0);
    EXPECT_EQ(ids[1], 1);
}

TEST(WindowQuery, WindowInsideAShapeStillFindsIt) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 100, 100);

    const std::vector<int> ids = window_query(layout, m1, 40, 40, 60, 60);
    ASSERT_EQ(ids.size(), 1u);
    EXPECT_EQ(ids[0], 0);
}

TEST(WindowQuery, WindowEqualToAShapeFindsIt) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    EXPECT_EQ(window_query(layout, m1, 0, 0, 10, 10).size(), 1u);
}

TEST(WindowQuery, TouchingTheWindowEdgeOrCornerIsNotInside) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);

    EXPECT_TRUE(window_query(layout, m1, 10, 0, 20, 10).empty());   // shares an edge
    EXPECT_TRUE(window_query(layout, m1, 10, 10, 20, 20).empty());  // shares a corner
}

TEST(WindowQuery, ShapesOutsideTheWindowAreNotReturned) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(m1, 0, 50, 10, 60);  // overlaps the window in x only

    EXPECT_TRUE(window_query(layout, m1, 0, 20, 10, 30).empty());
}

TEST(WindowQuery, OnlySearchesTheRequestedLayerAndReturnsGlobalShapeIds) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int m2 = layout.add_layer("metal2");
    layout.add_rect(m1, 0, 0, 10, 10);  // shape 0
    layout.add_rect(m2, 0, 0, 10, 10);  // shape 1

    const std::vector<int> on_m1 = window_query(layout, m1, 0, 0, 10, 10);
    const std::vector<int> on_m2 = window_query(layout, m2, 0, 0, 10, 10);
    ASSERT_EQ(on_m1.size(), 1u);
    ASSERT_EQ(on_m2.size(), 1u);
    EXPECT_EQ(on_m1[0], 0);
    EXPECT_EQ(on_m2[0], 1);
}

TEST(WindowQuery, EmptyLayerReturnsNothing) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_TRUE(window_query(layout, m1, 0, 0, 10, 10).empty());
}

TEST(WindowQuery, InvalidWindowThrows) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_THROW(window_query(layout, m1, 5, 0, 5, 10), std::invalid_argument);  // zero width
    EXPECT_THROW(window_query(layout, m1, 10, 0, 0, 10), std::invalid_argument);  // x1 > x2
    EXPECT_THROW(window_query(layout, m1, 0, 0, kMaxAbsCoord + 1, 10),
                 std::invalid_argument);  // out of range
}

TEST(WindowQuery, UnknownLayerThrows) {
    Layout layout;
    layout.add_layer("metal1");
    EXPECT_THROW(window_query(layout, 4, 0, 0, 10, 10), std::out_of_range);
}
