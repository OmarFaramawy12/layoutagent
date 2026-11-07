#!/usr/bin/env bash
# A scripted demo for screen recording. It shows how the output changes when ONE input changes.
#
#   demo/run_demo.sh engine    the C++ program alone (no API key needed)
#   demo/run_demo.sh agent     the same questions through the LLM (needs `source .env` first)
#   demo/run_demo.sh           both
#
# DEMO_PAUSE=3 demo/run_demo.sh   changes the pause between steps (seconds, default 2).
# The layout is demo/demo_layout.json (hand-made, so the answers are easy to follow):
#   metal1: 6 shapes. Heights 20, 40, 60 (shapes 0, 1, 2), and three 100 x 100 shapes
#           (3, 4, 5) with gaps of 15 nm (3-4) and 35 nm (4-5).
#   via1:   2 shapes (6, 7), each sitting on a metal1 shape (0 and 3).
#   metal2: 1 shape (8), far from everything.

set -u
cd "$(dirname "$0")/.."
LAYOUT=demo/demo_layout.json
CLI="${LAYOUTAGENT_CLI:-build/layoutagent}"
PAUSE="${DEMO_PAUSE:-2}"

if [ -t 1 ]; then BOLD=$'\e[1m'; DIM=$'\e[2m'; RESET=$'\e[0m'; else BOLD=""; DIM=""; RESET=""; fi

title() { printf '\n%s== %s ==%s\n' "$BOLD" "$1" "$RESET"; sleep "$PAUSE"; }
note()  { printf '%s# %s%s\n' "$DIM" "$1" "$RESET"; }

# The CLI output is pretty-printed over many lines; --compact keeps one violation per run readable.
engine() {
    local args=("$@")
    printf '%s$ layoutagent demo_layout.json %s%s\n' "$BOLD" "${args[*]}" "$RESET"
    "$CLI" "$LAYOUT" "${args[@]}" | python3 -m json.tool --compact
    echo
    sleep "$PAUSE"
}

run_engine_demo() {
    if [ ! -x "$CLI" ]; then
        echo "layoutagent program not found at $CLI (build it first, or set LAYOUTAGENT_CLI)" >&2
        exit 1
    fi

    title "1. Minimum width: tighten the rule, get more violations"
    note "metal1 shapes 0, 1, 2 have smaller sides of 20, 40 and 60 nm (both vias are 60 nm, so they fail at 70)"
    engine --min-width 30
    engine --min-width 50
    engine --min-width 70

    title "2. Minimum spacing: the gaps are 15 nm (shapes 3-4) and 35 nm (shapes 4-5)"
    note "'measured' and 'required' are SQUARED distances: 15 -> 225, 20 -> 400"
    engine --min-spacing 10
    engine --min-spacing 20
    engine --min-spacing 40

    title "3. Overlap between layers"
    engine --overlap metal1 via1
    engine --overlap metal1 metal2

    title "4. Window query and shape lookup (IDs to positions)"
    engine --window metal1 0 0 350 120
    engine --window metal1 0 0 350 20
    engine --shape 4

    title "5. Bad input is an error, not a crash"
    note "exit code 2 = usage error, with the message on stderr"
    printf '%s$ layoutagent demo_layout.json --min-width abc%s\n' "$BOLD" "$RESET"
    "$CLI" "$LAYOUT" --min-width abc
    echo "exit code: $?"
    sleep "$PAUSE"
}

ask() {
    printf '\n%s? %s%s\n' "$BOLD" "$1" "$RESET"
    python3 -m agent "$LAYOUT" "$1" --show-calls
    sleep "$PAUSE"
}

run_agent_demo() {
    if [ -z "${LLM_API_KEY:-}" ]; then
        echo "LLM_API_KEY is not set: run 'source .env' first (see the README)." >&2
        exit 1
    fi
    title "Natural language: the model picks the check, the C++ engine does the geometry"
    ask "Which shapes are narrower than 30 nm?"
    ask "Which shapes are narrower than 70 nm?"
    ask "Are any two metal1 shapes closer than 20 nm to each other?"
    ask "Are any two metal1 shapes closer than 40 nm to each other?"
    ask "Do any via1 shapes sit on metal1 shapes? How big is the overlap?"
    ask "Where exactly is shape 4, and which layer is it on?"
    ask "Check the layout for minimum width violations."
}

case "${1:-all}" in
    engine) run_engine_demo ;;
    agent)  run_agent_demo ;;
    all)    run_engine_demo; run_agent_demo ;;
    *)      echo "usage: demo/run_demo.sh [engine|agent]" >&2; exit 2 ;;
esac
