#include <gtest/gtest.h>

#include <stdexcept>
#include <string>

#include "layout.hpp"

using layoutagent::Layout;

TEST(Layout, LayerIdsAreAssignedInOrderStartingAtZero) {
    Layout layout;
    EXPECT_EQ(layout.add_layer("metal1"), 0);
    EXPECT_EQ(layout.add_layer("via1"), 1);
    EXPECT_EQ(layout.add_layer("metal2"), 2);
}

TEST(Layout, LayerCountGrowsWithEachLayer) {
    Layout layout;
    EXPECT_EQ(layout.layer_count(), 0);
    layout.add_layer("metal1");
    EXPECT_EQ(layout.layer_count(), 1);
    layout.add_layer("via1");
    EXPECT_EQ(layout.layer_count(), 2);
}

TEST(Layout, NameToIdAndIdToNameRoundTrip) {
    Layout layout;
    layout.add_layer("metal1");
    layout.add_layer("via1");

    EXPECT_EQ(layout.layer_id("metal1"), 0);
    EXPECT_EQ(layout.layer_id("via1"), 1);
    EXPECT_EQ(layout.layer_name(0), "metal1");
    EXPECT_EQ(layout.layer_name(1), "via1");
}

TEST(Layout, DuplicateLayerNameThrows) {
    Layout layout;
    layout.add_layer("metal1");
    EXPECT_THROW(layout.add_layer("metal1"), std::invalid_argument);
}

TEST(Layout, UnknownLayerNameThrows) {
    Layout layout;
    layout.add_layer("metal1");
    EXPECT_THROW(layout.layer_id("metal9"), std::out_of_range);
}

TEST(Layout, UnknownLayerIdThrows) {
    Layout layout;
    layout.add_layer("metal1");
    EXPECT_THROW(layout.layer_name(1), std::out_of_range);   // one past the end
    EXPECT_THROW(layout.layer_name(-1), std::out_of_range);  // negative
}

TEST(Layout, ErrorMessageNamesTheBadLayer) {
    Layout layout;
    try {
        layout.layer_id("metal9");
        FAIL() << "expected std::out_of_range";
    } catch (const std::out_of_range& e) {
        EXPECT_NE(std::string(e.what()).find("metal9"), std::string::npos);
    }
}

// ---- rects and shape IDs ----

TEST(Layout, NewLayerHasNoRects) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_TRUE(layout.rects(m1).empty());
}

TEST(Layout, AddRectReturnsShapeIdsStartingAtZero) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_EQ(layout.add_rect(m1, 0, 0, 10, 10), 0);
    EXPECT_EQ(layout.add_rect(m1, 20, 0, 30, 10), 1);
}

TEST(Layout, ShapeIdsAreUniqueAcrossLayers) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    EXPECT_EQ(layout.add_rect(m1, 0, 0, 10, 10), 0);
    EXPECT_EQ(layout.add_rect(v1, 0, 0, 5, 5), 1);
    EXPECT_EQ(layout.add_rect(m1, 20, 0, 30, 10), 2);
}

TEST(Layout, RectsAreStoredPerLayerWithTheirIds) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int v1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 10, 10);   // shape 0
    layout.add_rect(v1, 1, 2, 3, 4);     // shape 1
    layout.add_rect(m1, 20, 0, 30, 10);  // shape 2

    ASSERT_EQ(layout.rects(m1).size(), 2u);
    ASSERT_EQ(layout.rects(v1).size(), 1u);

    const auto& via = layout.rects(v1)[0];
    EXPECT_EQ(via.x1(), 1);
    EXPECT_EQ(via.y1(), 2);
    EXPECT_EQ(via.x2(), 3);
    EXPECT_EQ(via.y2(), 4);
    EXPECT_EQ(via.layer_id(), v1);
    EXPECT_EQ(via.shape_id(), 1);

    EXPECT_EQ(layout.rects(m1)[1].shape_id(), 2);
    EXPECT_EQ(layout.rects(m1)[1].layer_id(), m1);
}

TEST(Layout, AddRectToUnknownLayerThrows) {
    Layout layout;
    layout.add_layer("metal1");
    EXPECT_THROW(layout.add_rect(5, 0, 0, 10, 10), std::out_of_range);
    EXPECT_THROW(layout.add_rect(-1, 0, 0, 10, 10), std::out_of_range);
}

TEST(Layout, RectsOfUnknownLayerThrows) {
    Layout layout;
    layout.add_layer("metal1");
    EXPECT_THROW(layout.rects(1), std::out_of_range);
    EXPECT_THROW(layout.rects(-1), std::out_of_range);
}

TEST(Layout, InvalidRectThrowsAndDoesNotUseUpAShapeId) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    EXPECT_THROW(layout.add_rect(m1, 5, 0, 5, 10), std::invalid_argument);  // zero width
    EXPECT_TRUE(layout.rects(m1).empty());
    EXPECT_EQ(layout.add_rect(m1, 0, 0, 10, 10), 0);  // still the first ID
}

// ---- find_rect (look up a shape by its global shape ID) ----

TEST(Layout, FindRectReturnsTheShapeWithThatId) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int via1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 10, 10);       // shape 0
    layout.add_rect(via1, 5, 6, 7, 9);       // shape 1
    layout.add_rect(m1, -20, -30, 40, 50);   // shape 2

    const auto& rect = layout.find_rect(1);
    EXPECT_EQ(rect.shape_id(), 1);
    EXPECT_EQ(rect.layer_id(), via1);
    EXPECT_EQ(rect.x1(), 5);
    EXPECT_EQ(rect.y1(), 6);
    EXPECT_EQ(rect.x2(), 7);
    EXPECT_EQ(rect.y2(), 9);

    EXPECT_EQ(layout.find_rect(2).x1(), -20);
}

// Rects may be added to the layers in any order, so the shapes of one layer do not have
// consecutive IDs (metal1 holds shapes 0 and 2 here). The lookup must not assume they do.
TEST(Layout, FindRectWorksWhenIdsAreNotGroupedByLayer) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    const int via1 = layout.add_layer("via1");
    layout.add_rect(m1, 0, 0, 10, 10);
    layout.add_rect(via1, 100, 100, 110, 110);
    layout.add_rect(m1, 200, 200, 210, 210);

    EXPECT_EQ(layout.find_rect(0).layer_id(), m1);
    EXPECT_EQ(layout.find_rect(1).layer_id(), via1);
    EXPECT_EQ(layout.find_rect(2).layer_id(), m1);
}

TEST(Layout, FindRectOfAnUnknownIdThrows) {
    Layout layout;
    const int m1 = layout.add_layer("metal1");
    layout.add_rect(m1, 0, 0, 10, 10);

    EXPECT_NO_THROW(layout.find_rect(0));
    EXPECT_THROW(layout.find_rect(1), std::out_of_range);
    EXPECT_THROW(layout.find_rect(-1), std::out_of_range);
    EXPECT_THROW(layout.find_rect(1000000000000), std::out_of_range);  // does not fit in an int
}

TEST(Layout, FindRectOnAnEmptyLayoutThrows) {
    Layout layout;
    EXPECT_THROW(layout.find_rect(0), std::out_of_range);
}
