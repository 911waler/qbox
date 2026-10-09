#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

DISPATCH_TABLE='0 pwin
1 nebin
2 phin
3 hpin
4 dosin
5 projwfcin
6 ppin
7 bandin
8 mdin
9 epsilonin
10 qe_generate_unfold_inputs
11 qbox_wannier_menu
12 run_qe_scf_calculation
13 run_qe_band_calculation
14 qe_action_pdos
15 run_qe_ldos_calculation
16 run_qe_polar_calculation
17 run_qe_epsilon_calculation
18 run_qe_effective_mass_calculation
19 run_qe_unfold_calculation
20 plot_qe_band
21 redraw_qe_pdos_plot
22 redraw_qe_ldos_plot
23 plot_qe_epsilon
24 extract_qe_band_edges
25 calc_qe_effective_mass
26 relax2cif_menu
27 qbox_md_to_xyz_menu
28 qbox_nscf_menu
29 analyze_qe_dopant_pdos
30 scf2nscf
31 qbox_constraints_menu
32 conver
33 qe_action_ecut_scan
34 qe_action_kpoint_scan
35 cluster_velocities
36 merge_md_outputs
37 qe_action_cif_to_vasp
38 qe_action_vasp_to_cif
39 plot_qe_phonon
40 run_qe_phonon_calculation'

DIRECT_ACTION_IDS='0 1 7 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40'

table_handler_for_id() {
    awk -v wanted="$1" '$1 == wanted {print $2; exit}' <<<"$DISPATCH_TABLE"
}

invocation_snapshot() {
    printf '%s|%s|%s|%s|%s|%s|%s\n' \
        "${fname1-}" "${fname2-}" "${fname3-}" "${prefix-}" \
        "${NONINTERACTIVE_PWIN-}" "${PRESET_RTASK-}" "${DIRECT_BANDIN-}"
}

test_action_table_matches_authoritative_registry() {
    local actual='' id expected got
    while read -r id expected; do
        [ -n "$id" ] || continue
        got="$(qe_action_handler "$id")" || {
            fail "action table rejected supported ID $id"
            return 1
        }
        actual+="$id $got"$'\n'
    done <<<"$DISPATCH_TABLE"
    actual="${actual%$'\n'}"
    assert_eq "$DISPATCH_TABLE" "$actual" 'action ID table changed or is incomplete'
}

test_dispatch_invokes_static_handler_without_eval() {
    local body
    body="$(declare -f qe_dispatch_action)"
    assert_not_contains "$body" 'eval' 'dispatcher executes a handler through eval' || return 1
    assert_contains "$body" '"$handler"' 'dispatcher does not invoke the resolved handler directly'
}

install_dispatch_stubs() {
    local id handler
    while read -r id handler; do
        [ -n "$id" ] || continue
        # The fixture is a trusted list of shell identifiers; this only creates
        # test doubles and never participates in production dispatch.
        eval "$handler() { printf '%s\\n' '$handler' >> \"\${DISPATCH_LOG}\"; }"
    done <<<"$DISPATCH_TABLE"
}

direct_prepare_for_id() {
    local id="$1" input="$2" sandbox="$3"
    case "$id" in
        0)
            qe_prepare_invocation "$input" 00
            ;;
        1)
            : >"$sandbox/first"
            : >"$sandbox/second"
            : >"$sandbox/third"
            qe_prepare_invocation "$sandbox/first" "$sandbox/second" "$sandbox/third"
            ;;
        7)
            qe_prepare_invocation "$input" 7
            ;;
        *)
            qe_prepare_invocation "$input" "$id"
            ;;
    esac
}

test_interactive_and_direct_dispatch_reach_same_handler() {
    local sandbox input id expected interactive_log direct_log
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.cif"
    printf 'data_sample\n' >"$input"
    install_dispatch_stubs

    for id in $DIRECT_ACTION_IDS; do
        expected="$(table_handler_for_id "$id")"
        interactive_log="$sandbox/interactive.$id"
        direct_log="$sandbox/direct.$id"

        : >"$interactive_log"
        DISPATCH_LOG="$interactive_log"
        rmainfunc <<<"$id" >/dev/null || {
            fail "interactive dispatch failed for action $id"
            return 1
        }
        assert_eq "$expected" "$(cat "$interactive_log")" \
            "interactive action $id reached the wrong handler" || return 1

        : >"$direct_log"
        DISPATCH_LOG="$direct_log"
        direct_prepare_for_id "$id" "$input" "$sandbox" || {
            fail "invocation preparation failed for action $id"
            return 1
        }
        qe_detect_direct_action || {
            fail "direct action $id was not detected"
            return 1
        }
        assert_eq "$id" "${QE_DIRECT_ACTION-}" "direct action precedence changed for $id" || return 1
        qe_dispatch_action "$QE_DIRECT_ACTION" || {
            fail "direct dispatch failed for action $id"
            return 1
        }
        assert_eq "$expected" "$(cat "$direct_log")" \
            "direct action $id reached the wrong handler" || return 1
    done
}

test_action_14_uses_one_mode_adapter_for_both_entry_points() {
    local sandbox input mode expected interactive_log direct_log
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.cif"
    printf 'data_sample\n' >"$input"

    run_qe_pdos_batch_stage() { printf '%s\n' run_qe_pdos_batch_stage >>"$DISPATCH_LOG"; }
    run_qe_pdos_calculation() { printf '%s\n' run_qe_pdos_calculation >>"$DISPATCH_LOG"; }

    for mode in 1 0; do
        if [ "$mode" = 1 ]; then
            expected=run_qe_pdos_batch_stage
        else
            expected=run_qe_pdos_calculation
        fi

        interactive_log="$sandbox/pdos-interactive.$mode"
        direct_log="$sandbox/pdos-direct.$mode"
        : >"$interactive_log"
        QE_PDOS_BATCH_MODE="$mode" DISPATCH_LOG="$interactive_log" \
            rmainfunc <<<14 >/dev/null || return 1
        assert_eq "$expected" "$(cat "$interactive_log")" \
            "interactive PDOS mode $mode changed" || return 1

        : >"$direct_log"
        QE_PDOS_BATCH_MODE="$mode" DISPATCH_LOG="$direct_log" \
            qe_prepare_invocation "$input" 14 || return 1
        qe_detect_direct_action || return 1
        QE_PDOS_BATCH_MODE="$mode" DISPATCH_LOG="$direct_log" \
            qe_dispatch_action "$QE_DIRECT_ACTION" || return 1
        assert_eq "$expected" "$(cat "$direct_log")" \
            "direct PDOS mode $mode changed" || return 1
    done
}

test_direct_precedence_and_legacy_argument_normalization() {
    local sandbox input input2 expected snapshot preset
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.cif"
    input2="$sandbox/other.cif"
    printf 'data_sample\n' >"$input"
    printf 'data_other\n' >"$input2"

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation "$input" 00; invocation_snapshot)"
    expected="$input|00||sample|1|energy|"
    assert_eq "$expected" "$snapshot" '00 preset invocation changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation "$input" 0250; invocation_snapshot)"
    expected="$input|0250||sample|1|nscf|"
    assert_eq "$expected" "$snapshot" '0250 preset invocation changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation "$input" 0260; invocation_snapshot)"
    expected="$input|0260||sample|1|bands|"
    assert_eq "$expected" "$snapshot" '0260 preset invocation changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation "$input" 0230; invocation_snapshot)"
    expected="$input|0230||sample|1|structural optimization(relax)|"
    assert_eq "$expected" "$snapshot" '0230 preset invocation changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation "$input" 0240; invocation_snapshot)"
    expected="$input|0240||sample|1|cell optimization(vc-relax)|"
    assert_eq "$expected" "$snapshot" '0240 preset invocation changed' || return 1

    for preset in 00 0250 0260 0230 0240; do
        unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN
        qe_prepare_invocation "$input" "$preset" || return 1
        qe_detect_direct_action || return 1
        assert_eq 0 "${QE_DIRECT_ACTION-}" "preset $preset did not select action 0" || return 1
    done

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation "$input" 7; invocation_snapshot)"
    expected="$input|7||sample|||1"
    assert_eq "$expected" "$snapshot" '7 direct band invocation changed' || return 1
    qe_prepare_invocation "$input" 7 || return 1
    qe_detect_direct_action || return 1
    assert_eq 7 "${QE_DIRECT_ACTION-}" '7 direct band action was not detected' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation 9 "$input"; invocation_snapshot)"
    expected="$input|$input||sample|||"
    assert_eq "$expected" "$snapshot" 'argument-1 action 9 reshuffle changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation "$input" 9; invocation_snapshot)"
    expected="$input|9||sample|||"
    assert_eq "$expected" "$snapshot" 'argument-2 action 9 normalization changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation 10 "$input"; invocation_snapshot)"
    expected="10|$input||10|||"
    assert_eq "$expected" "$snapshot" 'action 10 argument-1 normalization changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation 19 "$input"; invocation_snapshot)"
    expected="19|$input||19|||"
    assert_eq "$expected" "$snapshot" 'action 19 argument-1 normalization changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation 21 "$input"; invocation_snapshot)"
    expected="|$input||21|||"
    assert_eq "$expected" "$snapshot" 'action 21 argument-1 normalization changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation 29 "$input"; invocation_snapshot)"
    expected="$input|$input||29|||"
    assert_eq "$expected" "$snapshot" 'action 29 argument-1 normalization changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation 28 "$input" "$input2"; invocation_snapshot)"
    expected="$input|$input2|$input2|sample|||"
    assert_eq "$expected" "$snapshot" 'action 28 argument-1 reshuffle changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation "$input" 28 "$input2"; invocation_snapshot)"
    expected="$input|$input2|$input2|sample|||"
    assert_eq "$expected" "$snapshot" 'action 28 argument-2 reshuffle changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation 36 "$input" "$input2"; invocation_snapshot)"
    expected="|$input|$input2|36|||"
    assert_eq "$expected" "$snapshot" 'action 36 argument-1 reshuffle changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation "$input" 36 "$input2"; invocation_snapshot)"
    expected="$input||$input2|sample|||"
    assert_eq "$expected" "$snapshot" 'action 36 argument-2 reshuffle changed' || return 1

    snapshot="$(unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN; qe_prepare_invocation "$input" "$input2" 36; invocation_snapshot)"
    expected="$input|$input2|36|sample|||"
    assert_eq "$expected" "$snapshot" 'action 36 argument-3 normalization changed' || return 1

    unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN
    qe_prepare_invocation 21 9 || return 1
    snapshot="$(invocation_snapshot)"
    expected="21|9||21|||"
    assert_eq "$expected" "$snapshot" 'ascending precedence normalization changed for 21/9' || return 1
    qe_detect_direct_action || return 1
    assert_eq 9 "${QE_DIRECT_ACTION-}" 'ascending recognized-ID precedence changed for 21/9' || return 1

    unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN
    qe_prepare_invocation 9 21 || return 1
    snapshot="$(invocation_snapshot)"
    expected="21|21||21|||"
    assert_eq "$expected" "$snapshot" 'ascending precedence normalization changed for 9/21' || return 1
    qe_detect_direct_action || return 1
    assert_eq 9 "${QE_DIRECT_ACTION-}" 'ascending recognized-ID precedence changed for 9/21' || return 1

    unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN
    qe_prepare_invocation 9 00 || return 1
    snapshot="$(invocation_snapshot)"
    expected="00|00||00|1|energy|"
    assert_eq "$expected" "$snapshot" 'numeric action must precede the 00 preset' || return 1
    qe_detect_direct_action || return 1
    assert_eq 9 "${QE_DIRECT_ACTION-}" 'numeric action lost precedence over the 00 preset' || return 1

    unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN
    qe_prepare_invocation 9 7 || return 1
    snapshot="$(invocation_snapshot)"
    expected="7|7||7|||1"
    assert_eq "$expected" "$snapshot" 'numeric action must precede the action-7 shortcut' || return 1
    qe_detect_direct_action || return 1
    assert_eq 9 "${QE_DIRECT_ACTION-}" 'numeric action lost precedence over the action-7 shortcut' || return 1

    : >"$sandbox/first"
    : >"$sandbox/9"
    : >"$sandbox/third"
    (
        cd "$sandbox" || exit 1
        unset NONINTERACTIVE_PWIN PRESET_RTASK DIRECT_BANDIN
        qe_prepare_invocation first 9 third || exit 1
        qe_detect_direct_action || exit 1
        assert_eq 1 "${QE_DIRECT_ACTION-}" 'three-file NEB shortcut lost precedence' || exit 1
    ) || return 1
}

test_direct_detection_covers_ids_in_both_supported_positions() {
    local sandbox input id
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.cif"
    for id in $(seq 9 40); do
        qe_prepare_invocation "$id" "$input" "$sandbox/extra" || return 1
        qe_detect_direct_action || return 1
        assert_eq "$id" "${QE_DIRECT_ACTION-}" "argument-1 action $id was not detected" || return 1

        qe_prepare_invocation "$input" "$id" "$sandbox/extra" || return 1
        qe_detect_direct_action || return 1
        assert_eq "$id" "${QE_DIRECT_ACTION-}" "argument-2 action $id was not detected" || return 1
    done

    qe_prepare_invocation "$input" "$sandbox/extra" 36 || return 1
    qe_detect_direct_action || return 1
    assert_eq 36 "${QE_DIRECT_ACTION-}" 'argument-3 action 36 was not detected' || return 1

    qe_prepare_invocation "$input" 8 || return 1
    if qe_detect_direct_action; then
        fail 'non-direct invocation entered direct mode'
        return 1
    fi
    assert_eq '' "${QE_DIRECT_ACTION-}" 'non-direct invocation left a stale action'
}

test_no_direct_action_enters_the_interactive_main_loop() {
    local sandbox input loop_marker status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.cif"
    printf 'data_sample\n' >"$input"
    loop_marker="$sandbox/interactive-loop"
    qe_install_cleanup_traps() { :; }
    qe_main_loop() { printf '%s\n' entered >"$loop_marker"; return 17; }
    qe_main "$input" 8
    status=$?
    assert_eq 17 "$status" 'non-direct invocation did not enter interactive mode' || return 1
    assert_eq entered "$(cat "$loop_marker")" 'interactive main loop was skipped'
}

test_main_loop_survives_500_returns() {
    local count=0 min_depth=999999 max_depth=0 status depth
    main_menu() { :; }
    rmainfunc() {
        depth="${#FUNCNAME[@]}"
        [ "$depth" -lt "$min_depth" ] && min_depth="$depth"
        [ "$depth" -gt "$max_depth" ] && max_depth="$depth"
        count=$((count + 1))
        if [ "$count" -le 500 ]; then QE_RETURN_TO_MAIN=1; return 0; fi
        return 23
    }
    qe_main_loop
    status=$?
    assert_eq 23 "$status" 'terminal action status changed' || return 1
    assert_eq 501 "$count" 'main loop return count changed' || return 1
    assert_eq "$min_depth" "$max_depth" 'main-menu stack depth grew'
}

test_submenus_request_the_loop_instead_of_calling_it_recursively() {
    local function_name body
    for function_name in pwin mdin phin hpin dosin qe_generate_pdos_input projwfcin ppin; do
        body="$(declare -f "$function_name")" || return 1
        if printf '%s\n' "$body" | grep -Eq '(^|[^[:alnum:]_])(main_menu|rmainfunc)([[:space:]]|$)'; then
            fail "submenu $function_name still calls main_menu/rmainfunc directly"
            return 1
        fi
    done
}

test_wannier_completion_exits_and_explicit_return_reopens_main() {
    local outcome count status
    local -a python_args
    local fname1='structure with spaces.cif'
    unset QE_DIRECT_ACTION
    main_menu() { count=$((count + 1)); }
    rmainfunc() {
        [ "$count" = 1 ] || return 23
        qbox_wannier_menu
    }
    qbox_python() { python_args=("$@"); return "$outcome"; }
    for outcome in 0 10 1; do
        count=0
        qe_main_loop
        status=$?
        assert_eq 4 "${#python_args[@]}" 'Wannier bridge split the source path' || return 1
        assert_eq --from-main-menu "${python_args[2]}" 'Wannier bridge omitted navigation protocol' || return 1
        assert_eq "$fname1" "${python_args[3]}" 'Wannier bridge changed the source path' || return 1
        if [ "$outcome" = 10 ]; then
            assert_eq 2 "$count" 'explicit return did not reopen main menu' || return 1
            assert_eq 23 "$status" 'main loop did not dispatch the next choice' || return 1
        else
            assert_eq 1 "$count" 'generation or failure reopened main menu' || return 1
            assert_eq "$outcome" "$status" 'Wannier terminal status changed' || return 1
        fi
    done
    QE_DIRECT_ACTION=11
    QE_RETURN_TO_MAIN=0
    outcome=10
    qbox_wannier_menu
    status=$?
    assert_eq 0 "$status" 'direct cancellation leaked internal navigation status' || return 1
    assert_eq 0 "$QE_RETURN_TO_MAIN" 'direct cancellation requested the main menu'
}

run_test 'Wannier generation exits and explicit return reopens main' test_wannier_completion_exits_and_explicit_return_reopens_main
run_test 'action handler table matches the authoritative registry' test_action_table_matches_authoritative_registry
run_test 'dispatcher invokes a static handler without eval' test_dispatch_invokes_static_handler_without_eval
run_test 'interactive and direct dispatch reach the same handler' test_interactive_and_direct_dispatch_reach_same_handler
run_test 'PDOS action mode is shared by both entry points' test_action_14_uses_one_mode_adapter_for_both_entry_points
run_test 'direct precedence and argument normalization remain compatible' test_direct_precedence_and_legacy_argument_normalization
run_test 'direct IDs are detected in both supported positions' test_direct_detection_covers_ids_in_both_supported_positions
run_test 'non-direct invocations enter the interactive main loop' test_no_direct_action_enters_the_interactive_main_loop
run_test 'main loop survives 500 submenu returns' test_main_loop_survives_500_returns
run_test 'submenus request the loop without recursive calls' test_submenus_request_the_loop_instead_of_calling_it_recursively
finish_tests
