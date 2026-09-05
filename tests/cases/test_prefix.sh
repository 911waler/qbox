#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

test_prefix_cases() {
    local input expected actual
    while IFS='|' read -r input expected; do
        [ -n "$input" ] || continue
        actual="$(qe_calc_prefix_from_path "$input")" || return 1
        assert_eq "$expected" "$actual" "prefix for $input" || return 1
    done <<'CASES'
sample.cif|sample
sample.v2.cif|sample.v2
/work.v2/sample.cif|sample
name with spaces.scf.in|name with spaces
literal[*].bands.in|literal[*]
-leading.vasp|-leading
sample.vcrelax.in|sample
sample.nscf.in|sample
plain|plain
CASES
}

test_empty_prefix_fails() {
    if qe_calc_prefix_from_path '' >/dev/null 2>&1; then fail 'empty path must fail'; fi
}

run_test 'prefix table' test_prefix_cases
run_test 'empty path fails' test_empty_prefix_fails
finish_tests
