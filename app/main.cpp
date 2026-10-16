#include <iostream>
#include <nlohmann/json.hpp>

int main() {
    nlohmann::json j = {{"hello", "world"}};
    std::cout << j.dump() << "\n";
    return 0;
}
