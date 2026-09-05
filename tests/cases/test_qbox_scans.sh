#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"

source_qbox

test_ecut_generator() {
    local sandbox input scan_dir
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/input.in"
    scan_dir="$sandbox/scan_ecut"
    cp "$TESTS_DIR/fixtures/expected/pw/water.scf.in" "$input"
    qbox_prepare_ecut_scan "$input" "$scan_dir" 30 10 50 '4 8' || return 1
    [ "$(find "$scan_dir" -maxdepth 1 -type f -name '*.scf.in' | wc -l)" -eq 6 ] || fail 'unexpected ecut scan count'
    rg -l 'ecutwfc[[:space:]]*=[[:space:]]*30' "$scan_dir" >/dev/null || fail 'ecutwfc=30 missing'
    rg -l 'ecutrho[[:space:]]*=[[:space:]]*240' "$scan_dir" >/dev/null || fail 'dual=8 output missing'
}

test_kpoint_generator() {
    local sandbox input scan_dir
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/input.in"
    scan_dir="$sandbox/scan_kp"
    cp "$TESTS_DIR/fixtures/expected/pw/water.scf.in" "$input"
    qbox_prepare_kpoint_scan "$input" "$scan_dir" '1 1 1,2 3 4' || return 1
    [ "$(find "$scan_dir" -maxdepth 1 -type f -name '*.scf.in' | wc -l)" -eq 2 ] || fail 'unexpected k-point scan count'
    rg -l '2 3 4 0 0 0' "$scan_dir" >/dev/null || fail 'k-point mesh was not written'
}

test_scan_action_wrappers_delegate_after_input_validation() {
    local sandbox input output
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/input.in"
    cp "$TESTS_DIR/fixtures/expected/pw/water.scf.in" "$input"

    output="$(
        cd "$sandbox" || exit 1
        fname1="$input"
        qbox_ecut_scan_menu() { printf 'ecut|%s|%s\n' "$1" "$2"; }
        qbox_kpoint_scan_menu() { printf 'kpoint|%s|%s\n' "$1" "$2"; }
        qe_action_ecut_scan || exit 1
        qe_action_kpoint_scan || exit 1
    )" || return 1
    assert_contains "$output" "ecut|$input|$sandbox/scan_ecut" \
        'ecut action did not delegate to its scan menu' || return 1
    assert_contains "$output" "kpoint|$input|$sandbox/scan_kp" \
        'k-point action did not delegate to its scan menu' || return 1
}

test_scan_action_wrappers_prompt_for_missing_input() {
    local sandbox input output
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/input.in"
    cp "$TESTS_DIR/fixtures/expected/pw/water.scf.in" "$input"

    output="$(
        cd "$sandbox" || exit 1
        fname1=''
        qbox_ecut_scan_menu() { printf 'ecut|%s|%s\n' "$1" "$2"; }
        qe_action_ecut_scan <<<"$input"
    )" || return 1
    assert_contains "$output" "ecut|$input|$sandbox/scan_ecut" \
        'scan action did not prompt for a missing input path'
}

test_convergence_extractor() {
    local sandbox output data last
    sandbox="$(new_sandbox)" || return 1
    output="$sandbox/scf.out"
    data="$sandbox/all.dat"
    last="$sandbox/last.dat"
    cat >"$output" <<'EOF_QE_OUT'
!    total energy              =   -10.0000 Ry
!    total energy              =    -9.9000 Ry
!    total energy              =    -9.8000d+00 rY
EOF_QE_OUT
    qbox_extract_convergence_data "$output" "$data" "$last" || return 1
    [ -s "$data" ] && [ -s "$last" ] || fail 'convergence data was not written'
    assert_eq 3 "$(wc -l <"$data")" 'convergence data did not contain exactly three records' || return 1
    awk '
        NR == 1 && $0 == "1\t0" { next }
        NR == 2 && $0 == "2\t1.36057" { next }
        NR == 3 && $0 == "3\t2.72114" { next }
        { invalid=1 }
        END { exit !(NR == 3 && !invalid) }
    ' "$data" >/dev/null || {
        fail 'convergence data rows did not match expected indices and values'
        return 1
    }
    rg -F -x -- $'3\t2.72114' "$last" >/dev/null || {
        fail 'last convergence data missed the final record and value'
        return 1
    }
    assert_not_contains "$(cat "$data")" 'qbox' 'data file contains branding'
}

test_convergence_extractor_rejects_invalid_records_atomically() {
    local sandbox output data last invalid_record
    local -a invalid_records=(
        '!    k-point                  1    2    3'
        '!    total energy              -9.8000 Ry'
        '!    total energy              =    not-a-number Ry'
        '!    total energy              =    -9.8000 eV'
        '!    total energy              =    -9.8000'
    )
    sandbox="$(new_sandbox)" || return 1
    output="$sandbox/scf.out"
    data="$sandbox/all.dat"
    last="$sandbox/last.dat"
    for invalid_record in "${invalid_records[@]}"; do
        printf '%s\n' \
            '!    total energy              =   -10.0000 Ry' \
            '!    total energy              =    -9.9000 Ry' \
            "$invalid_record" >"$output"
        printf 'data-sentinel\n' >"$data"
        printf 'last-sentinel\n' >"$last"
        if qbox_extract_convergence_data "$output" "$data" "$last"; then
            fail "invalid convergence record was accepted: $invalid_record"
            return 1
        fi
        assert_eq data-sentinel "$(cat "$data")" 'invalid convergence data replaced the data sentinel' || return 1
        assert_eq last-sentinel "$(cat "$last")" 'invalid convergence data replaced the last sentinel' || return 1
        [ -z "$(find "$sandbox" -maxdepth 1 -name '.qbox-*' -print -quit)" ] || {
            fail 'invalid convergence data left staging files'
            return 1
        }
    done
}

test_scan_generators_validate_before_creating_directories() {
    local sandbox input missing_cutoff ecut_dir kp_dir
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/input.in"
    missing_cutoff="$sandbox/missing-cutoff.in"
    ecut_dir="$sandbox/scan_ecut"
    kp_dir="$sandbox/scan_kp"
    cp "$TESTS_DIR/fixtures/expected/pw/water.scf.in" "$input"
    awk '!/ecutrho/' "$input" >"$missing_cutoff"

    if qbox_prepare_ecut_scan "$input" "$ecut_dir" nope 10 50 '4'; then
        fail 'invalid ecut values were accepted'
        return 1
    fi
    [ ! -e "$ecut_dir" ] || fail 'invalid ecut values created a scan directory'

    if qbox_prepare_ecut_scan "$missing_cutoff" "$ecut_dir" 30 10 50 '4'; then
        fail 'template without ecutrho was accepted'
        return 1
    fi
    [ ! -e "$ecut_dir" ] || fail 'invalid ecut template created a scan directory'

    if qbox_prepare_kpoint_scan "$input" "$kp_dir" '1 1 0'; then
        fail 'invalid K-point mesh was accepted'
        return 1
    fi
    [ ! -e "$kp_dir" ] || fail 'invalid K-point mesh created a scan directory'

    if qbox_prepare_ecut_scan "$input" "$ecut_dir" 30 10 50 ''; then
        fail 'empty dual list was accepted'
        return 1
    fi
    [ ! -e "$ecut_dir" ] || fail 'empty dual list created a scan directory'

    if qbox_prepare_kpoint_scan "$input" "$kp_dir" ''; then
        fail 'empty K-point list was accepted'
        return 1
    fi
    [ ! -e "$kp_dir" ] || fail 'empty K-point list created a scan directory'
}

test_ecut_generator_preserves_template_mode() {
    local sandbox input scan_dir mode output
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/input.in"
    scan_dir="$sandbox/scan_ecut"
    cp "$TESTS_DIR/fixtures/expected/pw/water.scf.in" "$input"
    chmod 640 "$input"
    mode="$(stat -c '%a' "$input")"
    qbox_prepare_ecut_scan "$input" "$scan_dir" 30 10 30 '4' || return 1
    output="$scan_dir/scan_30_120.scf.in"
    assert_eq "$mode" "$(stat -c '%a' "$output")" 'scan input mode changed'
    qbox_write_ecut_batch_script "$scan_dir" || return 1
    assert_not_contains "$(cat "$scan_dir/sub_qe.sh")" 'qbox' 'batch script contains branding'
}

test_explicit_interfaces_reject_missing_arguments() {
    local status function_name
    for function_name in \
        qbox_extract_convergence_data \
        qbox_plot_convergence_data \
        qbox_prepare_ecut_scan \
        qbox_prepare_kpoint_scan \
        qbox_write_ecut_batch_script \
        qbox_write_kpoint_batch_script; do
        ("$function_name") >/dev/null 2>&1
        status=$?
        assert_eq 2 "$status" "$function_name did not reject missing arguments" || return 1
    done
}

test_scan_generators_reject_duplicates_without_publishing_a_directory() {
    local sandbox input ecut_dir kp_dir
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/input.in"
    ecut_dir="$sandbox/scan_ecut"
    kp_dir="$sandbox/scan_kp"
    cp "$TESTS_DIR/fixtures/expected/pw/water.scf.in" "$input"

    if qbox_prepare_ecut_scan "$input" "$ecut_dir" 30 10 40 '4 4'; then
        fail 'duplicate dual values were accepted'
        return 1
    fi
    [ ! -e "$ecut_dir" ] || fail 'duplicate dual values published a partial scan directory'

    if qbox_prepare_kpoint_scan "$input" "$kp_dir" '2 2 2,2 2 2'; then
        fail 'duplicate K-point meshes were accepted'
        return 1
    fi
    [ ! -e "$kp_dir" ] || fail 'duplicate K-point meshes published a partial scan directory'
}

test_ecut_generator_removes_staging_when_rendering_fails() {
    local sandbox input scan_dir status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/input.in"
    scan_dir="$sandbox/scan_ecut"
    cp "$TESTS_DIR/fixtures/expected/pw/water.scf.in" "$input"
    (
        mktemp() {
            case "$*" in
                *.qbox-scan-input.*) return 1 ;;
                *) command mktemp "$@" ;;
            esac
        }
        qbox_prepare_ecut_scan "$input" "$scan_dir" 30 10 30 '4'
    )
    status=$?
    [ "$status" -ne 0 ] || fail 'scan renderer failure was accepted'
    [ ! -e "$scan_dir" ] || fail 'scan renderer failure published a directory'
    [ -z "$(find "$sandbox" -maxdepth 1 -name '.qbox-scan-ecut.*' -print -quit)" ] || fail 'scan renderer failure left staging data'
}

test_convergence_extractor_rejects_equivalent_output_paths() {
    local sandbox output data
    sandbox="$(new_sandbox)" || return 1
    output="$sandbox/scf.out"
    data="$sandbox/all.dat"
    printf '%s\n' \
        '!    total energy              =   -10.0000 Ry' \
        '!    total energy              =    -9.9000 Ry' >"$output"
    printf 'sentinel\n' >"$data"
    if qbox_extract_convergence_data "$output" "$data" "$sandbox/./all.dat"; then
        fail 'equivalent convergence output paths were accepted'
        return 1
    fi
    assert_eq sentinel "$(cat "$data")" 'equivalent paths changed the existing data file'
}

run_test 'ecut scan generator has explicit inputs' test_ecut_generator
run_test 'k-point scan generator has explicit inputs' test_kpoint_generator
run_test 'scan action wrappers validate and delegate' test_scan_action_wrappers_delegate_after_input_validation
run_test 'scan action wrappers prompt for missing input' test_scan_action_wrappers_prompt_for_missing_input
run_test 'convergence extractor writes neutral data' test_convergence_extractor
run_test 'convergence extractor rejects invalid records atomically' test_convergence_extractor_rejects_invalid_records_atomically
run_test 'scan generators validate before creating directories' test_scan_generators_validate_before_creating_directories
run_test 'ecut generator preserves input mode and writes neutral batch script' test_ecut_generator_preserves_template_mode
run_test 'explicit scan interfaces reject missing arguments' test_explicit_interfaces_reject_missing_arguments
run_test 'scan generators reject duplicates without publishing a directory' test_scan_generators_reject_duplicates_without_publishing_a_directory
run_test 'ecut generator removes staging when rendering fails' test_ecut_generator_removes_staging_when_rendering_fails
run_test 'convergence extractor rejects equivalent output paths' test_convergence_extractor_rejects_equivalent_output_paths
finish_tests
