#include <gtest/gtest.h>
#include <nlohmann/json.hpp>

TEST(Hello, Math) {
    EXPECT_EQ(1 + 1, 2);
}

TEST(Hello, JsonParses) {
    auto j = nlohmann::json::parse(R"({"w": 10})");
    EXPECT_EQ(j["w"], 10);
}
