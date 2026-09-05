#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"

test_source_mode_is_quiet() {
    local output status
    output="$(env -i PATH="$PATH" HOME="${HOME:-/tmp}" TMPDIR="${TMPDIR:-/tmp}" QBOX_TEST_MODE=1 bash --noprofile --norc -c 'source "$1"' _ "$PROJECT_ROOT/qbox" 2>&1)"
    status=$?
    assert_eq 0 "$status" 'test-mode source must succeed'
    assert_eq '' "$output" 'test-mode source must not enter the menu'
}

test_main_menu_snapshot() {
    local sandbox actual
    sandbox="$(new_sandbox)" || return 1
    actual="$sandbox/menu.txt"
    env -i PATH="$PATH" HOME="${HOME:-/tmp}" TMPDIR="${TMPDIR:-/tmp}" QBOX_TEST_MODE=1 bash --noprofile --norc -c 'source "$1"; main_menu' _ "$PROJECT_ROOT/qbox" >"$actual"
    assert_file_equals "$TESTS_DIR/fixtures/expected/main_menu.txt" "$actual" 'main menu changed'
}

run_test 'source mode is quiet' test_source_mode_is_quiet
run_test 'main menu matches compatibility snapshot' test_main_menu_snapshot
finish_tests
