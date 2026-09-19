#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"

PROMOTED_HELPERS=(
    qe_pwin_select_task
    qe_pwin_advanced_menu
    qe_pwin_refresh_cutoff_values
    qe_pwin_cutoff_label
    qe_pwin_cutoff_menu
    qe_pwin_menu
    qe_pwin_set_choices
    qe_generate_pw_input_unsafe
    qe_generate_pw_input
    qe_md_menu
    qe_md_pseudo_dir
    qe_md_pseudo_file
    qe_generate_md_input_unsafe
    qe_generate_md_input
    qe_phonon_menu
    qe_phonon_adsorbed_frequency
    qe_phonon_adsorbed_thermo
    qe_phonon_gas_frequency
    qe_phonon_gas_thermo
    qe_phonon_nonpolar_frequency
    qe_phonon_ir
    qe_phonon_nonpolar_dispersion
    qe_phonon_nonpolar_raman
    qe_phonon_polar_frequency
    qe_phonon_polar_dispersion
    qe_phonon_polar_raman
    qe_bandin_menu
    qe_builtin_clean_pdos_next_steps
    qe_cluster_menu
    qe_element_mass_from_symbol
    qe_cluster_parse_cif_symbols
    qe_cluster_parse_multiwfn_symbols
    qe_cluster_generate_velocities
)

extract_lexical_functions() {
    qbox_lexical_functions
}

extract_loaded_functions() {
    qbox_loaded_functions
}

test_syntax_and_removed_patterns() {
    local source_file
    while IFS= read -r source_file; do
        bash -n "$source_file" || return 1
        if rg -n 'QEversion|fname1%%[.]\*|rm -f[[:space:]]+\$\{prefix\}_tmp\*' "$source_file"; then
            fail "removed legacy expression is present: $source_file"
            return 1
        fi
    done < <(qbox_shell_source_files)
}

test_function_registry_invariants() {
    local sandbox expected lexical loaded duplicates lexical_helpers loaded_helpers
    sandbox="$(new_sandbox)" || return 1
    expected="$sandbox/expected-promoted"
    lexical="$sandbox/lexical"
    loaded="$sandbox/loaded"
    lexical_helpers="$sandbox/lexical-promoted"
    loaded_helpers="$sandbox/loaded-promoted"

    printf '%s\n' "${PROMOTED_HELPERS[@]}" | sort >"$expected" || return 1
    assert_eq 33 "$(wc -l <"$expected")" 'promoted helper authority must contain exactly 33 names' || return 1

    extract_lexical_functions >"$lexical" || return 1
    duplicates="$(uniq -d "$lexical")"
    assert_eq '' "$duplicates" 'duplicate Bash function names exist in qbox' || return 1

    extract_loaded_functions >"$loaded" || return 1
    assert_file_equals "$lexical" "$loaded" 'lexical functions differ from clean-subshell loaded functions' || return 1

    grep -Fxf "$expected" "$lexical" >"$lexical_helpers" || return 1
    grep -Fxf "$expected" "$loaded" >"$loaded_helpers" || return 1
    assert_file_equals "$expected" "$lexical_helpers" 'the exact 33 promoted helpers are not present lexically' || return 1
    assert_file_equals "$expected" "$loaded_helpers" 'the exact 33 promoted helpers are not loaded after test-mode source'
}

test_dispatch_and_main_loop_have_one_authority() {
    source_qbox || return 1
    local calls='' loop_count=0 status
    main_menu() { calls+="menu "; }
    rmainfunc() {
        calls+="dispatch ";
        loop_count=$((loop_count + 1))
        if [ "$loop_count" -eq 1 ]; then QE_RETURN_TO_MAIN=1; else return 7; fi
    }
    qe_main_loop
    status=$?
    assert_eq 'menu dispatch menu dispatch ' "$calls" \
        'main loop must show one menu before each dispatch' || return 1
    assert_eq 7 "$status" 'main loop must propagate the final task status'
}

test_deferred_writer_guards_have_expected_structure() {
    source_qbox || return 1
    local source
    source="$(declare -f qe_write_pw_system)"
    assert_contains "$source" 'for ((i=1; i<="${#atmtype[@]}"; i++))' \
        'PW system magnetic scan is missing' || return 1
    assert_eq 1 "$(printf '%s\n' "$source" | rg -F -c '[[ "${magarr[$i]}" > "0" ]]')" \
        'PW system magnetic guard count is incorrect' || return 1
    assert_contains "$source" '[[ "${magarr[$i]}" > "0" ]]' \
        'PW system magnetic guard is missing' || return 1
    source="$(declare -f qe_write_pw_structure)"
    assert_contains "$source" 'for ((i=1; i<=$ntyp; i++))' \
        'PW structure species scan is missing' || return 1
    assert_eq 1 "$(printf '%s\n' "$source" | rg -F -c 'for ((j=1; j<=86; j++))')" \
        'PW structure element lookup loop count is incorrect' || return 1
    assert_contains "$source" 'for ((j=1; j<=86; j++))' \
        'PW structure element lookup guard is missing' || return 1
    assert_contains "$source" 'if [ "${atmtype[$i]}" == "${atm[$j]}" ]; then' \
        'PW structure symbol match is missing' || return 1
    assert_contains "$source" 'atmindex=$j' \
        'PW structure index assignment is missing' || return 1
    assert_contains "$source" 'atmmass[$atmindex]' \
        'PW structure mass lookup is missing' || return 1
    assert_contains "$source" 'pseudo_file_by_lib "$pseudolib" "$atmindex"' \
        'PW structure pseudopotential lookup is missing'
}

run_test 'syntax and removed legacy patterns' test_syntax_and_removed_patterns
run_test 'exact helper and function registry invariants' test_function_registry_invariants
run_test 'dispatcher and main loop have one authority' test_dispatch_and_main_loop_have_one_authority
run_test 'deferred writer guard structure' test_deferred_writer_guards_have_expected_structure
finish_tests
