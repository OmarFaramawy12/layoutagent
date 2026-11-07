// The command-line program:
//   layoutagent <layout.json> [--min-width W] [--min-spacing S] [--overlap LAYER_A LAYER_B]...
//   layoutagent <layout.json> --window LAYER X1 Y1 X2 Y2
//   layoutagent <layout.json> --shape ID
//
// The first form prints the violations as JSON on stdout. The second prints the IDs of the
// shapes on LAYER that intersect the window, as {"shape_ids": [...]}. The third prints the
// layer and the corners of the shape with that ID, as {"shape": {...}}. The window and shape
// queries cannot be combined with each other or with the checks.
// Errors go to stderr as "error: ...".
// Exit codes: 0 = the checks ran (with or without violations), 1 = runtime error
// (bad file, unknown layer name), 2 = usage error (bad command line).

#include <charconv>      // std::from_chars
#include <cstddef>       // std::size_t
#include <cstdint>
#include <exception>
#include <iostream>
#include <optional>
#include <ostream>
#include <stdexcept>
#include <string>
#include <system_error>  // std::errc
#include <utility>       // std::pair
#include <vector>

#include "checks.hpp"
#include "io_json.hpp"
#include "layout.hpp"
#include "violation.hpp"

using layoutagent::check_overlap;
using layoutagent::check_spacing_grid;
using layoutagent::check_width;
using layoutagent::Layout;
using layoutagent::load_layout;
using layoutagent::shape_ids_to_json;
using layoutagent::shape_to_json;
using layoutagent::Violation;
using layoutagent::violations_to_json;
using layoutagent::window_query;

namespace {

const char* const kUsage =
    "usage: layoutagent <layout.json> ([--min-width W] [--min-spacing S] "
    "[--overlap LAYER_A LAYER_B]... | --window LAYER X1 Y1 X2 Y2 | --shape ID)";

// The arguments of --window.
struct Window {
    std::string layer;
    std::int64_t x1 = 0;
    std::int64_t y1 = 0;
    std::int64_t x2 = 0;
    std::int64_t y2 = 0;
};

// What the command line asked for.
struct Options {
    std::string layout_path;
    std::optional<std::int64_t> min_width;    // empty = do not run this check
    std::optional<std::int64_t> min_spacing;  // empty = do not run this check
    std::vector<std::pair<std::string, std::string>> overlaps;
    std::optional<Window> window;             // empty = no window query
    std::optional<std::int64_t> shape;        // empty = no shape query (the shape ID)
};

// Returns the argument after args[i] and moves i forward by one, so the loop in
// parse_arguments does not look at the value again. "i" is a non-const reference
// (std::size_t&): changing it here changes the caller's variable.
const std::string& take_value(const std::vector<std::string>& args, std::size_t& i,
                              const std::string& option) {
    if (i + 1 >= args.size()) {
        throw std::invalid_argument(option + " needs a value");
    }
    ++i;
    return args[i];
}

// Converts the WHOLE text to an integer ("12x" and "1.5" are errors, unlike std::stoll
// which would quietly stop at the first bad character).
std::int64_t parse_int(const std::string& text, const std::string& option) {
    std::int64_t value = 0;
    const char* first = text.data();
    const char* last = text.data() + text.size();
    const std::from_chars_result result = std::from_chars(first, last, value);
    if (result.ec != std::errc() || result.ptr != last) {
        throw std::invalid_argument(option + " needs an integer, got '" + text + "'");
    }
    return value;
}

// Throws if an option that may be given only once has already been given.
void check_not_repeated(bool already_given, const std::string& option) {
    if (already_given) {
        throw std::invalid_argument(option + " given more than once");
    }
}

// Reads the five values after --window (a layer name and four integers) and moves i to the
// last of them. "option" is the text "--window", used in the error messages.
Window parse_window(const std::vector<std::string>& args, std::size_t& i,
                    const std::string& option) {
    Window window;
    window.layer = take_value(args, i, option);
    window.x1 = parse_int(take_value(args, i, option), option);
    window.y1 = parse_int(take_value(args, i, option), option);
    window.x2 = parse_int(take_value(args, i, option), option);
    window.y2 = parse_int(take_value(args, i, option), option);
    return window;
}

// Checks the options as a whole once all of them are read: there must be a layout file, and
// exactly one kind of request: the checks (any of them together), a window query or a shape
// query.
void check_combination(const Options& options, bool have_path) {
    if (!have_path) {
        throw std::invalid_argument("missing layout file");
    }
    const bool has_check =
        options.min_width || options.min_spacing || !options.overlaps.empty();
    const int kinds_of_request = (has_check ? 1 : 0) + (options.window ? 1 : 0) +
                                 (options.shape ? 1 : 0);
    if (kinds_of_request > 1) {
        throw std::invalid_argument(
            "--window and --shape cannot be combined with each other or with --min-width, "
            "--min-spacing or --overlap");
    }
    if (kinds_of_request == 0) {
        throw std::invalid_argument(
            "nothing to check: give --min-width, --min-spacing, --overlap, --window or --shape");
    }
}

// Every problem with the command line is reported by throwing std::invalid_argument.
Options parse_arguments(const std::vector<std::string>& args) {
    Options options;
    bool have_path = false;

    for (std::size_t i = 0; i < args.size(); ++i) {
        const std::string& arg = args[i];
        if (arg == "--min-width") {
            check_not_repeated(options.min_width.has_value(), arg);
            options.min_width = parse_int(take_value(args, i, arg), arg);
        } else if (arg == "--min-spacing") {
            check_not_repeated(options.min_spacing.has_value(), arg);
            options.min_spacing = parse_int(take_value(args, i, arg), arg);
        } else if (arg == "--overlap") {
            const std::string& layer_a = take_value(args, i, arg);
            const std::string& layer_b = take_value(args, i, arg);
            options.overlaps.push_back({layer_a, layer_b});  // push_back makes its own copies
        } else if (arg == "--window") {
            check_not_repeated(options.window.has_value(), arg);
            options.window = parse_window(args, i, arg);
        } else if (arg == "--shape") {
            check_not_repeated(options.shape.has_value(), arg);
            options.shape = parse_int(take_value(args, i, arg), arg);
        } else if (arg.rfind("--", 0) == 0) {  // starts with "--"
            throw std::invalid_argument("unknown option " + arg);
        } else {
            if (have_path) {
                throw std::invalid_argument("only one layout file is allowed");
            }
            options.layout_path = arg;
            have_path = true;
        }
    }

    check_combination(options, have_path);
    return options;
}

void append(std::vector<Violation>& all, const std::vector<Violation>& more) {
    all.insert(all.end(), more.begin(), more.end());
}

// Runs the program and returns the exit code. Everything is written to the streams that are
// passed in (std::cout and std::cerr in main).
int run(const std::vector<std::string>& args, std::ostream& out, std::ostream& err) {
    try {
        const Options options = parse_arguments(args);
        const Layout layout = load_layout(options.layout_path);

        if (options.window) {
            const Window& window = *options.window;
            const std::vector<int> shape_ids = window_query(
                layout, layout.layer_id(window.layer), window.x1, window.y1, window.x2, window.y2);
            out << shape_ids_to_json(shape_ids) << '\n';
            return 0;
        }
        if (options.shape) {
            out << shape_to_json(layout, layout.find_rect(*options.shape)) << '\n';
            return 0;
        }

        std::vector<Violation> violations;
        if (options.min_width) {
            for (int id = 0; id < layout.layer_count(); ++id) {
                append(violations, check_width(layout, id, *options.min_width));
            }
        }
        if (options.min_spacing) {
            for (int id = 0; id < layout.layer_count(); ++id) {
                append(violations, check_spacing_grid(layout, id, *options.min_spacing));
            }
        }
        for (const auto& pair : options.overlaps) {
            append(violations, check_overlap(layout, layout.layer_id(pair.first),
                                             layout.layer_id(pair.second)));
        }

        // Printed only when everything succeeded, so a failed run never leaves
        // half an answer on stdout.
        out << violations_to_json(layout, violations) << '\n';
        return 0;
    } catch (const std::invalid_argument& error) {
        // A bad command line, or a rule value / layer pair the checks refused.
        // (load_layout reports bad files as std::runtime_error, so they do not end up here.)
        err << "error: " << error.what() << '\n' << kUsage << '\n';
        return 2;
    } catch (const std::exception& error) {
        err << "error: " << error.what() << '\n';
        return 1;
    }
}

}  // namespace

int main(int argc, char** argv) {
    std::vector<std::string> args;
    for (int i = 1; i < argc; ++i) {  // argv[0] is the program name
        args.push_back(argv[i]);
    }
    return run(args, std::cout, std::cerr);
}
