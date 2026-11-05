#include <gtest/gtest.h>

#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>

#include "io_json.hpp"
#include "layout.hpp"

using layoutagent::Layout;
using layoutagent::load_layout;
using layoutagent::parse_layout;

// ---- good input ----

TEST(ParseLayout, ReadsLayersRectsAndShapeIds) {
    const Layout layout = parse_layout(R"({
        "layers": {
            "metal1": [[0, 0, 100, 60], [200, 0, 300, 60]],
            "via1": [[10, 10, 40, 40]]
        }
    })");

    EXPECT_EQ(layout.layer_id("metal1"), 0);
    EXPECT_EQ(layout.layer_id("via1"), 1);

    ASSERT_EQ(layout.rects(0).size(), 2u);
    ASSERT_EQ(layout.rects(1).size(), 1u);

    const auto& second = layout.rects(0)[1];
    EXPECT_EQ(second.x1(), 200);
    EXPECT_EQ(second.y1(), 0);
    EXPECT_EQ(second.x2(), 300);
    EXPECT_EQ(second.y2(), 60);
    EXPECT_EQ(second.layer_id(), 0);

    // Shape IDs count 0, 1, 2 across the whole file, layer by layer.
    EXPECT_EQ(layout.rects(0)[0].shape_id(), 0);
    EXPECT_EQ(layout.rects(0)[1].shape_id(), 1);
    EXPECT_EQ(layout.rects(1)[0].shape_id(), 2);
}

// If the loader used the default nlohmann::json (keys sorted alphabetically) instead of
// ordered_json, "metal1" would get ID 0 here and this test would fail. The generator's
// expected answers rely on layer IDs following the order of the file.
TEST(ParseLayout, LayerIdsFollowFileOrderNotAlphabeticalOrder) {
    const Layout layout = parse_layout(R"({
        "layers": {
            "via1": [[0, 0, 10, 10]],
            "metal2": [[0, 0, 20, 20]],
            "metal1": [[0, 0, 30, 30]]
        }
    })");

    EXPECT_EQ(layout.layer_id("via1"), 0);
    EXPECT_EQ(layout.layer_id("metal2"), 1);
    EXPECT_EQ(layout.layer_id("metal1"), 2);

    EXPECT_EQ(layout.rects(0)[0].shape_id(), 0);  // via1
    EXPECT_EQ(layout.rects(1)[0].shape_id(), 1);  // metal2
    EXPECT_EQ(layout.rects(2)[0].shape_id(), 2);  // metal1
}

TEST(ParseLayout, AnEmptyLayerIsAllowed) {
    const Layout layout = parse_layout(R"({"layers": {"metal1": []}})");
    EXPECT_EQ(layout.layer_id("metal1"), 0);
    EXPECT_TRUE(layout.rects(0).empty());
}

TEST(ParseLayout, NegativeCoordinatesAreAllowed) {
    const Layout layout = parse_layout(R"({"layers": {"metal1": [[-50, -40, -10, -5]]}})");
    EXPECT_EQ(layout.rects(0)[0].x1(), -50);
    EXPECT_EQ(layout.rects(0)[0].y2(), -5);
}

// ---- bad input: every case must throw std::runtime_error ----

TEST(ParseLayout, InvalidJsonThrows) {
    EXPECT_THROW(parse_layout("{not json"), std::runtime_error);
    EXPECT_THROW(parse_layout(""), std::runtime_error);
}

TEST(ParseLayout, TopLevelMustBeAnObjectWithLayers) {
    EXPECT_THROW(parse_layout("[]"), std::runtime_error);
    EXPECT_THROW(parse_layout("{}"), std::runtime_error);
    EXPECT_THROW(parse_layout(R"({"shapes": []})"), std::runtime_error);
}

TEST(ParseLayout, LayersMustBeAnObject) {
    EXPECT_THROW(parse_layout(R"({"layers": []})"), std::runtime_error);
}

TEST(ParseLayout, EachLayerMustBeAList) {
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": 5}})"), std::runtime_error);
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": {}}})"), std::runtime_error);
}

TEST(ParseLayout, EachRectMustBeAListOfFourNumbers) {
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": [5]}})"), std::runtime_error);
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": [[0, 0, 10]]}})"), std::runtime_error);
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": [[0, 0, 10, 10, 5]]}})"),
                 std::runtime_error);
}

TEST(ParseLayout, CoordinatesMustBeIntegers) {
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": [[0, 0, 1.5, 10]]}})"),
                 std::runtime_error);
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": [[0, 0, 10.0, 10]]}})"),
                 std::runtime_error);
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": [[0, 0, "10", 10]]}})"),
                 std::runtime_error);
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": [[0, 0, null, 10]]}})"),
                 std::runtime_error);
}

TEST(ParseLayout, InvalidRectsAreRejected) {
    // zero width, reversed corners, outside +/- 1e9
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": [[5, 0, 5, 10]]}})"),
                 std::runtime_error);
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": [[10, 0, 0, 10]]}})"),
                 std::runtime_error);
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": [[0, 0, 2000000000, 10]]}})"),
                 std::runtime_error);
}

// 18446744073709551615 is 2^64 - 1. Converted to int64 it would wrap around to -1 and look
// like a valid coordinate, so the loader must reject it before converting.
TEST(ParseLayout, IntegersTooBigForInt64AreRejected) {
    EXPECT_THROW(parse_layout(R"({"layers": {"metal1": [[0, 0, 18446744073709551615, 10]]}})"),
                 std::runtime_error);
}

TEST(ParseLayout, ErrorMessageSaysWhichLayerAndRect) {
    try {
        parse_layout(R"({"layers": {"metal1": [[0, 0, 10, 10], [5, 0, 5, 10]]}})");
        FAIL() << "expected std::runtime_error";
    } catch (const std::runtime_error& e) {
        const std::string message = e.what();
        EXPECT_NE(message.find("metal1"), std::string::npos) << message;
        EXPECT_NE(message.find("rect 1"), std::string::npos) << message;
    }
}

// ---- files ----

TEST(LoadLayout, ReadsAFile) {
    const auto path = std::filesystem::temp_directory_path() / "layoutagent_test_layout.json";
    {
        std::ofstream out(path);
        out << R"({"layers": {"metal1": [[0, 0, 100, 60]]}})";
    }

    const Layout layout = load_layout(path.string());
    std::filesystem::remove(path);  // clean up our own temporary file

    EXPECT_EQ(layout.layer_id("metal1"), 0);
    ASSERT_EQ(layout.rects(0).size(), 1u);
    EXPECT_EQ(layout.rects(0)[0].x2(), 100);
}

TEST(LoadLayout, MissingFileThrows) {
    EXPECT_THROW(load_layout("this_file_does_not_exist.json"), std::runtime_error);
}
