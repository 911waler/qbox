#!/usr/bin/env bash
set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$TESTS_DIR/.." && pwd)"
TEST_FAILURES=0

cleanup_test_root() {
    local root="${TEST_TMP_ROOT:-}"
    case "${root##*/}" in
        .qbox-tests.*)
            if [ -e "$root" ]; then
                rm -rf -- "$root"
            fi
            ;;
    esac
}

TEST_TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/.qbox-tests.XXXXXX")" || exit 1
trap cleanup_test_root EXIT

qbox_test_python_supports_required_modules() {
    timeout 5s "$1" -c 'import seekpath' >/dev/null 2>&1
}

qbox_test_configure_python() {
    local path_entry candidate candidate_path path_list
    local -a path_entries
    local probe_count=0
    local max_probe_count=2
    if [ -n "${QBOX_PYTHON:-}" ]; then
        qbox_test_python_supports_required_modules "$QBOX_PYTHON" || {
            printf 'FAIL: QBOX_PYTHON cannot import required module: seekpath\n' >&2
            return 1
        }
        export QBOX_PYTHON
        return 0
    fi

    path_list="${PATH:-}"
    local IFS=:
    read -r -a path_entries <<< "$path_list"

    for candidate in python3 python; do
        [ "$probe_count" -lt "$max_probe_count" ] || break
        candidate_path=''
        for path_entry in "${path_entries[@]}"; do
            case "$path_entry" in
                /*) ;;
                *) continue ;;
            esac
            candidate_path="$path_entry/$candidate"
            [ -f "$candidate_path" ] && [ -x "$candidate_path" ] || {
                candidate_path=''
                continue
            }
            break
        done
        [ -n "$candidate_path" ] || continue
        probe_count=$((probe_count + 1))
        if qbox_test_python_supports_required_modules "$candidate_path"; then
            QBOX_PYTHON="$candidate_path"
            export QBOX_PYTHON
            return 0
        fi
    done

    printf 'FAIL: no Python interpreter on PATH can import required module: seekpath; set QBOX_PYTHON\n' >&2
    return 1
}

qbox_test_configure_python || exit 1

fail() { printf 'FAIL: %s\n' "$*" >&2; return 1; }
assert_eq() { [ "$1" = "$2" ] || fail "${3:-expected <$1>, got <$2>}"; }
assert_contains() { case "$1" in *"$2"*) return 0;; *) fail "${3:-missing <$2>}";; esac; }
assert_not_contains() { case "$1" in *"$2"*) fail "${3:-unexpected <$2>}";; *) return 0;; esac; }
assert_file_equals() { cmp -s -- "$1" "$2" || { diff -u -- "$1" "$2" >&2 || true; fail "${3:-files differ}"; }; }
assert_or_update_golden() {
    local expected="$1" actual="$2"
    if [ "${QBOX_UPDATE_GOLDEN:-0}" = 1 ]; then
        mkdir -p "$(dirname "$expected")"
        cp -- "$actual" "$expected"
    else
        assert_file_equals "$expected" "$actual" "${3:-golden output changed}"
    fi
}
new_sandbox() { mktemp -d "$TEST_TMP_ROOT/case.XXXXXX"; }
source_qbox() { QBOX_TEST_MODE=1 source "$PROJECT_ROOT/qbox"; }
run_test() {
    local name="$1"; shift
    if ( "$@" ); then printf 'PASS: %s\n' "$name"; else TEST_FAILURES=$((TEST_FAILURES + 1)); fi
}
finish_tests() { [ "$TEST_FAILURES" -eq 0 ]; }
