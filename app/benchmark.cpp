// Benchmark: naive check_spacing against check_spacing_grid on random layouts of growing size.
//
//   cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release
//   ninja -C build-release benchmark && ./build-release/benchmark
//
// The density is the same for every size (about one shape per 1000 x 1000 nm), so the number
// of violations per shape stays about the same and only the algorithm changes the timing.
// Each timing is the best of a few runs. Never run this from a Debug build: the numbers
// would measure the missing optimizations, not the algorithms.

#include <algorithm>  // std::min
#include <chrono>
#include <cmath>      // std::sqrt
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <random>
#include <vector>

#include "checks.hpp"
#include "layout.hpp"
#include "violation.hpp"

using layoutagent::check_spacing;
using layoutagent::check_spacing_grid;
using layoutagent::Layout;
using layoutagent::Violation;

namespace {

constexpr std::int64_t kMinSpacing = 40;
constexpr std::int64_t kSmallestSide = 10;
constexpr std::int64_t kLargestSide = 100;
constexpr std::int64_t kAreaPerShape = 1000;  // each shape gets a 1000 x 1000 nm square on average
constexpr int kRepeats = 3;

Layout random_layout(int shape_count, unsigned seed) {
    // The area grows with the number of shapes, so the density stays constant.
    const auto extent =
        static_cast<std::int64_t>(std::sqrt(static_cast<double>(shape_count)) * kAreaPerShape);
    std::mt19937 random(seed);
    std::uniform_int_distribution<std::int64_t> position(0, extent);
    std::uniform_int_distribution<std::int64_t> side(kSmallestSide, kLargestSide);

    Layout layout;
    const int m1 = layout.add_layer("metal1");
    for (int i = 0; i < shape_count; ++i) {
        const std::int64_t x = position(random);
        const std::int64_t y = position(random);
        layout.add_rect(m1, x, y, x + side(random), y + side(random));
    }
    return layout;
}

// Runs `check` kRepeats times and returns the fastest time in milliseconds. The size of
// the last result is stored in `count`, which also makes sure the compiler cannot skip the call.
template <typename Check>
double best_milliseconds(Check check, std::size_t& count) {
    double best = 0.0;
    for (int run = 0; run < kRepeats; ++run) {
        const auto start = std::chrono::steady_clock::now();
        const std::vector<Violation> result = check();
        const auto stop = std::chrono::steady_clock::now();
        count = result.size();
        const double milliseconds =
            std::chrono::duration<double, std::milli>(stop - start).count();
        best = (run == 0) ? milliseconds : std::min(best, milliseconds);
    }
    return best;
}

}  // namespace

int main() {
#ifndef NDEBUG  // Release builds define NDEBUG; Debug builds do not
    std::cerr << "warning: this is not a Release build, so the timings mean nothing.\n"
                 "Build with -DCMAKE_BUILD_TYPE=Release (see the top of app/benchmark.cpp).\n";
#endif

    std::cout << "minimum spacing " << kMinSpacing << " nm, best of " << kRepeats << " runs\n\n"
              << std::setw(8) << "shapes" << std::setw(12) << "violations" << std::setw(12)
              << "naive ms" << std::setw(12) << "grid ms" << std::setw(10) << "speedup" << '\n';

    for (const int shape_count : {1000, 2000, 5000, 10000, 20000, 40000}) {
        const Layout layout = random_layout(shape_count, 1);

        std::size_t naive_count = 0;
        std::size_t grid_count = 0;
        const double naive_ms =
            best_milliseconds([&] { return check_spacing(layout, 0, kMinSpacing); }, naive_count);
        const double grid_ms = best_milliseconds(
            [&] { return check_spacing_grid(layout, 0, kMinSpacing); }, grid_count);

        if (naive_count != grid_count) {  // the equivalence test should make this impossible
            std::cerr << "error: naive found " << naive_count << " violations but the grid found "
                      << grid_count << " (" << shape_count << " shapes)\n";
            return 1;
        }
        std::cout << std::setw(8) << shape_count << std::setw(12) << naive_count << std::fixed
                  << std::setprecision(2) << std::setw(12) << naive_ms << std::setw(12) << grid_ms
                  << std::setw(9) << (naive_ms / grid_ms) << "x\n";
    }
    return 0;
}
