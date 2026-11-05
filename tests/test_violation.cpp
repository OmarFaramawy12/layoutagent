#include <gtest/gtest.h>

#include <vector>

#include "violation.hpp"

using layoutagent::Violation;
using layoutagent::ViolationType;

TEST(Violation, WidthViolationHasNoSecondShape) {
    Violation v{.type = ViolationType::MinWidth,
                .layer_a = 1,
                .layer_b = 1,
                .first_shape_id = 7,
                .second_shape_id = std::nullopt,
                .measured = 30,
                .required = 50};

    EXPECT_EQ(v.type, ViolationType::MinWidth);
    EXPECT_EQ(v.layer_a, 1);
    EXPECT_EQ(v.layer_b, 1);
    EXPECT_EQ(v.first_shape_id, 7);
    EXPECT_FALSE(v.second_shape_id.has_value());
    EXPECT_EQ(v.measured, 30);
    EXPECT_EQ(v.required, 50);
}

TEST(Violation, SpacingViolationStoresBothShapesAndSquaredValues) {
    // Distance 3-4-5 = 25 squared, rule S = 10 so required is S*S = 100.
    Violation v{.type = ViolationType::MinSpacing,
                .layer_a = 2,
                .layer_b = 2,
                .first_shape_id = 3,
                .second_shape_id = 9,
                .measured = 25,
                .required = 100};

    EXPECT_EQ(v.type, ViolationType::MinSpacing);
    ASSERT_TRUE(v.second_shape_id.has_value());
    EXPECT_EQ(*v.second_shape_id, 9);
    EXPECT_EQ(v.measured, 25);
    EXPECT_EQ(v.required, 100);
}

TEST(Violation, OverlapViolationCanSpanTwoLayers) {
    Violation v{.type = ViolationType::Overlap,
                .layer_a = 0,
                .layer_b = 1,
                .first_shape_id = 4,
                .second_shape_id = 12,
                .measured = 0,
                .required = 0};

    EXPECT_EQ(v.type, ViolationType::Overlap);
    EXPECT_EQ(v.layer_a, 0);
    EXPECT_EQ(v.layer_b, 1);
}

TEST(Violation, CanBeStoredInVector) {
    std::vector<Violation> result;
    result.push_back({.type = ViolationType::MinWidth,
                      .layer_a = 0,
                      .layer_b = 0,
                      .first_shape_id = 1,
                      .second_shape_id = std::nullopt,
                      .measured = 5,
                      .required = 10});

    ASSERT_EQ(result.size(), 1u);
    EXPECT_EQ(result[0].first_shape_id, 1);
}
