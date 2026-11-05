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
