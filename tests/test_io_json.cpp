#include <gtest/gtest.h>

#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>

#include <cstdint>
#include <optional>
#include <vector>

#include <nlohmann/json.hpp>

#include "io_json.hpp"
#include "layout.hpp"
#include "violation.hpp"

using layoutagent::Layout;
using layoutagent::load_layout;
using layoutagent::parse_layout;
using layoutagent::shape_ids_to_json;
using layoutagent::Violation;
using layoutagent::ViolationType;
using layoutagent::violations_to_json;

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

// The JSON library would silently keep only one of two equal keys, so the loader has to check
// for repeats while parsing. A repeated layer name would otherwise lose a whole list of rects.
TEST(ParseLayout, ADuplicateLayerNameIsRejected) {
    try {
        parse_layout(R"({"layers": {"metal1": [[0, 0, 10, 10]], "via1": [], "metal1": [[20, 0, 30, 10]]}})");
        FAIL() << "expected std::runtime_error";
    } catch (const std::runtime_error& e) {
        const std::string message = e.what();
        EXPECT_NE(message.find("Duplicate key 'metal1'"), std::string::npos) << message;
    }
}

TEST(ParseLayout, ADuplicateKeyInAnyObjectIsRejected) {
    EXPECT_THROW(parse_layout(R"({"layers": {}, "layers": {"metal1": []}})"), std::runtime_error);
    EXPECT_THROW(parse_layout(R"({"layers": {}, "meta": {"a": 1, "a": 2}})"), std::runtime_error);
}

// Only keys of the SAME object count. Equal keys in different objects are fine, and layer
// names are case sensitive.
TEST(ParseLayout, TheSameKeyInDifferentObjectsIsFine) {
    const Layout layout = parse_layout(
        R"({"layers": {"metal1": [], "Metal1": []}, "meta": {"metal1": 1}, "other": {"metal1": 2}})");
    EXPECT_EQ(layout.layer_count(), 2);
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

// ---- violations_to_json ----

namespace {

// Parses the text from violations_to_json and returns its "violations" array.
nlohmann::json parse_violations(const std::string& text) {
    const nlohmann::json document = nlohmann::json::parse(text);
    return document.at("violations");
}

Layout two_layer_layout() {
    Layout layout;
    layout.add_layer("metal1");  // layer 0
    layout.add_layer("via1");    // layer 1
    return layout;
}

}  // namespace

TEST(ViolationsToJson, NoViolationsGivesAnEmptyArray) {
    const nlohmann::json list = parse_violations(violations_to_json(two_layer_layout(), {}));
    EXPECT_TRUE(list.is_array());
    EXPECT_TRUE(list.empty());
}

TEST(ViolationsToJson, WidthViolationHasANullSecondShape) {
    const std::vector<Violation> violations = {{.type = ViolationType::MinWidth,
                                                .layer_a = 0,
                                                .layer_b = 0,
                                                .first_shape_id = 7,
                                                .second_shape_id = std::nullopt,
                                                .measured = 30,
                                                .required = 50}};

    const nlohmann::json list = parse_violations(violations_to_json(two_layer_layout(), violations));
    ASSERT_EQ(list.size(), 1u);
    const nlohmann::json& item = list[0];
    EXPECT_EQ(item.size(), 7u);  // exactly these seven keys
    EXPECT_EQ(item.at("type").get<std::string>(), "min_width");
    EXPECT_EQ(item.at("layer_a").get<std::string>(), "metal1");
    EXPECT_EQ(item.at("layer_b").get<std::string>(), "metal1");
    EXPECT_EQ(item.at("first_shape_id").get<int>(), 7);
    EXPECT_TRUE(item.at("second_shape_id").is_null());
    EXPECT_EQ(item.at("measured").get<std::int64_t>(), 30);
    EXPECT_EQ(item.at("required").get<std::int64_t>(), 50);
}

TEST(ViolationsToJson, SpacingViolationHasBothShapes) {
    const std::vector<Violation> violations = {{.type = ViolationType::MinSpacing,
                                                .layer_a = 1,
                                                .layer_b = 1,
                                                .first_shape_id = 3,
                                                .second_shape_id = 9,
                                                .measured = 81,
                                                .required = 1600}};

    const nlohmann::json list = parse_violations(violations_to_json(two_layer_layout(), violations));
    ASSERT_EQ(list.size(), 1u);
    EXPECT_EQ(list[0].at("type").get<std::string>(), "min_spacing");
    EXPECT_EQ(list[0].at("first_shape_id").get<int>(), 3);
    EXPECT_EQ(list[0].at("second_shape_id").get<int>(), 9);
    EXPECT_EQ(list[0].at("measured").get<std::int64_t>(), 81);
    EXPECT_EQ(list[0].at("required").get<std::int64_t>(), 1600);
}

TEST(ViolationsToJson, OverlapUsesTwoLayerNamesNotIds) {
    const std::vector<Violation> violations = {{.type = ViolationType::Overlap,
                                                .layer_a = 0,
                                                .layer_b = 1,
                                                .first_shape_id = 4,
                                                .second_shape_id = 12,
                                                .measured = 400,
                                                .required = 0}};

    const nlohmann::json list = parse_violations(violations_to_json(two_layer_layout(), violations));
    ASSERT_EQ(list.size(), 1u);
    EXPECT_EQ(list[0].at("type").get<std::string>(), "overlap");
    EXPECT_EQ(list[0].at("layer_a").get<std::string>(), "metal1");
    EXPECT_EQ(list[0].at("layer_b").get<std::string>(), "via1");
}

TEST(ViolationsToJson, KeepsTheOrderOfTheViolations) {
    std::vector<Violation> violations;
    for (int id : {5, 2, 8}) {
        violations.push_back({.type = ViolationType::MinWidth,
                              .layer_a = 0,
                              .layer_b = 0,
                              .first_shape_id = id,
                              .second_shape_id = std::nullopt,
                              .measured = 1,
                              .required = 2});
    }

    const nlohmann::json list = parse_violations(violations_to_json(two_layer_layout(), violations));
    ASSERT_EQ(list.size(), 3u);
    EXPECT_EQ(list[0].at("first_shape_id").get<int>(), 5);
    EXPECT_EQ(list[1].at("first_shape_id").get<int>(), 2);
    EXPECT_EQ(list[2].at("first_shape_id").get<int>(), 8);
}

TEST(ViolationsToJson, LargeValuesStayExactIntegers) {
    const std::vector<Violation> violations = {{.type = ViolationType::Overlap,
                                                .layer_a = 0,
                                                .layer_b = 1,
                                                .first_shape_id = 0,
                                                .second_shape_id = 1,
                                                .measured = 4'000'000'000'000'000'000,
                                                .required = 0}};

    const nlohmann::json list = parse_violations(violations_to_json(two_layer_layout(), violations));
    ASSERT_EQ(list.size(), 1u);
    EXPECT_TRUE(list[0].at("measured").is_number_integer());  // not a rounded double
    EXPECT_EQ(list[0].at("measured").get<std::int64_t>(), 4'000'000'000'000'000'000);
}

// ---- shape_ids_to_json ----

TEST(ShapeIdsToJson, NoIdsGivesAnEmptyArray) {
    const nlohmann::json document = nlohmann::json::parse(shape_ids_to_json({}));
    EXPECT_EQ(document.size(), 1u);  // only the "shape_ids" key
    EXPECT_TRUE(document.at("shape_ids").is_array());
    EXPECT_TRUE(document.at("shape_ids").empty());
}

TEST(ShapeIdsToJson, KeepsTheIdsInOrder) {
    const nlohmann::json document = nlohmann::json::parse(shape_ids_to_json({7, 2, 9}));
    EXPECT_EQ(document.at("shape_ids").get<std::vector<int>>(), (std::vector<int>{7, 2, 9}));
}

TEST(ViolationsToJson, UnknownLayerIdThrows) {
    const std::vector<Violation> violations = {{.type = ViolationType::MinWidth,
                                                .layer_a = 5,
                                                .layer_b = 5,
                                                .first_shape_id = 0,
                                                .second_shape_id = std::nullopt,
                                                .measured = 1,
                                                .required = 2}};

    EXPECT_THROW(violations_to_json(two_layer_layout(), violations), std::out_of_range);
}
