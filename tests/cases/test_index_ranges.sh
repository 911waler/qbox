#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

test_expand_index_spec_expands_ranges() {
    local actual expected
    expected='1
5
9
10
11
12
14
15'
    actual="$(qe_expand_index_spec '1,5,9-12,14-15')" || return 1
    assert_eq "$expected" "$actual" 'index range expansion changed'
}

test_expand_index_spec_rejects_invalid_specs() {
    local spec
    for spec in 0 5-3 1,,2 a 1-2-3; do
        if qe_expand_index_spec "$spec" >/dev/null 2>&1; then
            fail "invalid index specification accepted: $spec"
            return 1
        fi
    done
}

test_qbox_constraints_preserve_sentinel_and_flag_atoms() {
    local sandbox input output sentinel expected_sentinel status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.scf.in"
    output="$sandbox/sample-fixed.scf.in"
    sentinel="$sandbox/sample_tmp_user.dat"
    expected_sentinel="$sandbox/sentinel.expected"
    printf '%s\n' \
        '&CONTROL' \
        " calculation = 'scf'," \
        '/' \
        '&SYSTEM' \
        ' ibrav = 0, nat = 3, ntyp = 1,' \
        '/' \
        'ATOMIC_POSITIONS angstrom' \
        'C 0.0 0.0 0.0    1 1 1' \
        'C 1.0 0.0 0.0' \
        'C 2.0 0.0 0.0' \
        'K_POINTS gamma' >"$input"
    printf 'sentinel bytes must remain unchanged\n' >"$sentinel"
    cp -- "$sentinel" "$expected_sentinel"

    (
        cd "$sandbox" || exit 1
        QBOX_TEST_MODE=1 source "$PROJECT_ROOT/qbox"
        qbox_apply_constraints 'sample.scf.in' '1,3' '0 0 0' 'sample-fixed.scf.in'
    )
    status=$?
    assert_eq 0 "$status" 'qbox_apply_constraints failed for a valid atom selection' || return 1
    assert_eq 'C 0.0 0.0 0.0    0 0 0' "$(sed -n '8p' "$output")" 'first selected atom was not fixed' || return 1
    assert_eq 'C 1.0 0.0 0.0' "$(sed -n '9p' "$output")" 'unselected atom changed' || return 1
    assert_eq 'C 2.0 0.0 0.0    0 0 0' "$(sed -n '10p' "$output")" 'last selected atom was not fixed' || return 1
    assert_eq 'C 0.0 0.0 0.0    1 1 1' "$(sed -n '8p' "$input")" 'explicit constraint writer modified its input' || return 1
    [ -f "$sentinel" ] || { fail 'sibling sentinel was removed'; return 1; }
    cmp -s -- "$sentinel" "$expected_sentinel" || { fail 'sibling sentinel changed'; return 1; }
}

test_phin_adsmolfreq_rejects_invalid_spec() {
    local sandbox input ph_input expected_ph_input output status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.scf.in"
    ph_input="$sandbox/sample.ph.in"
    expected_ph_input="$sandbox/sample.ph.in.expected"
    output="$sandbox/phin.out"
    printf '%s\n' \
        'nat = 3' \
        'ntyp = 1' \
        'ATOMIC_POSITIONS angstrom' \
        'C 0.0 0.0 0.0' \
        'C 1.0 0.0 0.0' \
        'C 2.0 0.0 0.0' >"$input"
    printf 'existing ph input must remain unchanged\n' >"$ph_input"
    cp -- "$ph_input" "$expected_ph_input"

    (
        cd "$sandbox" || exit 1
        QBOX_TEST_MODE=1 source "$PROJECT_ROOT/qbox"
        fname1='sample.scf.in'
        prefix='sample'
        printf '1\n1\n1,,2\n' | phin
    ) >"$output" 2>&1
    status=$?
    [ "$status" -ne 0 ] || { fail 'invalid adsmolfreq input was reported as successful'; return 1; }
    assert_not_contains "$(cat "$output")" ' 输入文件已在当前文件夹生成。' 'invalid adsmolfreq input printed success' || return 1
    [ -f "$ph_input" ] || { fail 'invalid adsmolfreq input removed its existing output'; return 1; }
    cmp -s -- "$ph_input" "$expected_ph_input" || { fail 'invalid adsmolfreq input truncated its existing output'; return 1; }
}

run_test 'index ranges expand exactly' test_expand_index_spec_expands_ranges
run_test 'invalid index ranges are rejected' test_expand_index_spec_rejects_invalid_specs
run_test 'qbox constraints preserve sentinel and fix selected atoms' test_qbox_constraints_preserve_sentinel_and_flag_atoms
run_test 'phin rejects invalid adsmolfreq ranges' test_phin_adsmolfreq_rejects_invalid_spec
finish_tests
