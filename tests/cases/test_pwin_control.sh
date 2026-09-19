#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

test_pwin_supported_choice_sets() {
    local PWIN_LOCK_BANDS_KPATH
    PWIN_LOCK_BANDS_KPATH=0

    rtask='energy'
    qe_pwin_set_choices
    assert_eq '0 1 3 8 10 11 12 14' "${pwin_choice[*]}" 'energy choices changed' || return 1

    PWIN_LOCK_BANDS_KPATH=0
    rtask='nscf'
    qe_pwin_set_choices
    assert_eq '0 1 3 8 9 10 11 12 14' "${pwin_choice[*]}" 'nscf choices changed' || return 1

    PWIN_LOCK_BANDS_KPATH=0
    rtask='bands'
    qe_pwin_set_choices
    assert_eq '0 1 3 9 10 11 12 13 14' "${pwin_choice[*]}" 'unlocked bands choices changed' || return 1

    PWIN_LOCK_BANDS_KPATH=1
    rtask='bands'
    qe_pwin_set_choices
    assert_eq '0 1 3 9 10 11 12 14' "${pwin_choice[*]}" 'locked bands choices changed' || return 1

    PWIN_LOCK_BANDS_KPATH=0
    rtask='structural optimization(relax)'
    qe_pwin_set_choices
    assert_eq '0 1 3 8 10 11 12 14' "${pwin_choice[*]}" 'relax choices changed' || return 1

    PWIN_LOCK_BANDS_KPATH=0
    rtask='cell optimization(vc-relax)'
    qe_pwin_set_choices
    assert_eq '0 1 3 8 10 11 12 14' "${pwin_choice[*]}" 'vc-relax choices changed' || return 1

    PWIN_LOCK_BANDS_KPATH=0
    rtask='energy+force+stress'
    qe_pwin_set_choices
    assert_eq '0 1 3 8 10 11 12 14' "${pwin_choice[*]}" 'energy+force+stress choices changed' || return 1

    PWIN_LOCK_BANDS_KPATH=0
    rtask='cell optimization for 2D materials'
    qe_pwin_set_choices
    assert_eq '0 1 3 8 10 11 12 14' "${pwin_choice[*]}" '2D vc-relax choices changed' || return 1

    unset PWIN_LOCK_BANDS_KPATH
}

test_pwin_case_loop_has_no_unreachable_labels() {
    local dead_labels awk_status
    dead_labels="$(awk '
        /^[[:space:]]*while \[\[ "\$pwin_arg" != "14" \]\]; do$/ {inside=1; next}
        inside {
            if ($0 ~ /^[[:space:]]*case[[:space:]].*[[:space:]]in[[:space:]]*$/) {
                case_depth++
                found_case=1
                next
            }
            if ($0 ~ /^[[:space:]]*esac;?[[:space:]]*$/) {
                case_depth--
                if (case_depth == 0) exit
                next
            }
            if (case_depth == 1 && $0 ~ /^[[:space:]]*"?[24567]"?[[:space:]]*\)[[:space:]]*$/) print
        }
        END {if (!found_case) exit 2}
    ' < <(declare -f pwin))"
    awk_status=$?
    assert_eq 0 "$awk_status" 'could not locate pwin case loop' || return 1
    [ -z "$dead_labels" ] || { fail 'unreachable pwin case label remains'; return 1; }
}

write_pwin_mock_qe_tmp() {
    local output="$1"
    printf '%s\n' \
        '&SYSTEM' \
        ' nat 1' \
        ' ntyp 1' \
        '/' \
        'CELL_PARAMETERS angstrom' \
        ' 1.0 0.0 0.0' \
        ' 0.0 1.0 0.0' \
        ' 0.0 0.0 1.0' \
        'ATOMIC_POSITIONS angstrom' \
        ' Si 0.0 0.0 0.0' >"$output"
}

run_stubbed_pwin_return() {
    local sandbox="$1" return_to_exec="$2" status_file="$3" return_file="$4" menu_marker="$5"
    (
        cd "$sandbox" || exit 1
        fname1="$sandbox/structure.cif"
        prefix="$sandbox/sample"
        PRESET_RTASK=''
        NONINTERACTIVE_PWIN=''
        RETURN_TO_EXEC_CALC="$return_to_exec"
        QE_RETURN_TO_MAIN=0
        PWIN_LOCK_BANDS_KPATH=0
        PWIN_DEFAULT_KMESH_SCALE=''
        PWIN_DEFAULT_BANDS_NBND=''
        mock_qe_tmp="$sandbox/mock_QE.tmp"

        qe_pwin_menu() { :; }
        require_multiwfn() { return 0; }
        Multiwfn() { cp -- "$mock_qe_tmp" "${prefix}_QE.tmp"; }
        main_menu() { printf '%s\n' called >"$menu_marker"; }
        rmainfunc() { printf '%s\n' called >>"$menu_marker"; }

        pwin <<'INPUT'
1
14
INPUT
        local status=$?
        printf '%s\n' "$status" >"$status_file"
        printf '%s\n' "${QE_RETURN_TO_MAIN:-unset}" >"$return_file"
    )
}

prepare_stubbed_pwin_sandbox() {
    local sandbox="$1"
    printf 'data_test\n' >"$sandbox/structure.cif"
    write_pwin_mock_qe_tmp "$sandbox/mock_QE.tmp"
    printf 'keep this sibling\n' >"$sandbox/sample_QE.tmp.sibling"
}

assert_pwin_return_cleanup() {
    local sandbox="$1" expected_status="$2" status_file="$3" return_file="$4" menu_marker="$5"
    assert_eq "$expected_status" "$(cat "$status_file")" 'pwin option 14 status changed' || return 1
    assert_eq '1' "$(cat "$return_file")" 'pwin option 14 did not request the main menu' || return 1
    [ ! -e "$sandbox/sample_QE.tmp" ] || { fail 'pwin option 14 leaked its structure temp'; return 1; }
    assert_eq 'keep this sibling' "$(cat "$sandbox/sample_QE.tmp.sibling")" 'pwin cleanup touched a sibling sentinel' || return 1
    [ ! -e "$menu_marker" ] || { fail 'pwin option 14 called the main menu directly'; return 1; }
}

test_pwin_interactive_return_requests_main_menu() {
    local sandbox status_file return_file menu_marker
    sandbox="$(new_sandbox)" || return 1
    status_file="$sandbox/status"
    return_file="$sandbox/return"
    menu_marker="$sandbox/main-menu-called"
    prepare_stubbed_pwin_sandbox "$sandbox"
    run_stubbed_pwin_return "$sandbox" 0 "$status_file" "$return_file" "$menu_marker" || return 1
    assert_pwin_return_cleanup "$sandbox" 0 "$status_file" "$return_file" "$menu_marker"
}

test_pwin_exec_return_skips_main_menu() {
    local sandbox status_file return_file menu_marker
    sandbox="$(new_sandbox)" || return 1
    status_file="$sandbox/status"
    return_file="$sandbox/return"
    menu_marker="$sandbox/main-menu-called"
    prepare_stubbed_pwin_sandbox "$sandbox"
    run_stubbed_pwin_return "$sandbox" 1 "$status_file" "$return_file" "$menu_marker" || return 1
    assert_eq '1' "$(cat "$status_file")" 'pwin execution return did not fail' || return 1
    assert_eq '0' "$(cat "$return_file")" 'pwin execution return requested the main menu' || return 1
    [ ! -e "$sandbox/sample_QE.tmp" ] || { fail 'pwin execution return leaked its structure temp'; return 1; }
    assert_eq 'keep this sibling' "$(cat "$sandbox/sample_QE.tmp.sibling")" 'pwin execution cleanup touched a sibling sentinel' || return 1
    [ ! -e "$menu_marker" ] || { fail 'pwin execution return called the main menu directly'; return 1; }
}

run_test 'supported pwin choice sets stay exact' test_pwin_supported_choice_sets
run_test 'unreachable pwin case labels are absent' test_pwin_case_loop_has_no_unreachable_labels
run_test 'interactive pwin return requests the main menu' test_pwin_interactive_return_requests_main_menu
run_test 'execution pwin return skips the main menu' test_pwin_exec_return_skips_main_menu
finish_tests
