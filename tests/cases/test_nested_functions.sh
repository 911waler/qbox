#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

new_helper_names=(
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
    qbox_md_to_xyz_menu
    qbox_nscf_menu
    qbox_constraints_menu
)

legacy_helper_names=(
    pwin_select_task
    pwin_advanced_menu
    pwin_refresh_cutoff_values
    pwin_cutoff_label
    pwin_cutoff_menu
    pwin_menu
    pwin_set_choices
    genpwinfile_unsafe
    genpwinfile
    md_menu
    md_pseudo_dir
    md_pseudo_file
    genmdinfile_unsafe
    genmdinfile
    phin_menu
    adsmolfreq
    adsmolthermo
    gasmolfreq
    gasmolthermo
    nonpolarfreq
    irfreq
    nonpolardisp
    nonpolarraman
    polarfreq
    polardisp
    polarraman
    bandin_menu
    qe_builtin_clean_pdos_next_steps
    cluster_velocities_menu
    element_mass_from_symbol
    parse_cif_symbols
    parse_multiwfn_symbols
    gen_cluster_velocities_file
    relaxcheck
    infcheck
    relax2cif
    relax2nscf
    fixatm
    mdout2xyz
)

test_new_helpers_are_top_level() {
    local function_name
    for function_name in "${new_helper_names[@]}"; do
        declare -F "$function_name" >/dev/null || fail "missing top-level helper: $function_name"
    done
}

test_legacy_function_declarations_are_removed() {
    local function_name source_file
    for function_name in "${legacy_helper_names[@]}"; do
        local declaration_pattern
        if [ "$function_name" = "qe_builtin_clean_pdos_next_steps" ]; then
            declaration_pattern="^[[:space:]]+(function[[:space:]]+)?${function_name}[[:space:]]*\\(\\)[[:space:]]*\\{"
        else
            declaration_pattern="^[[:space:]]*(function[[:space:]]+)?${function_name}[[:space:]]*\\(\\)[[:space:]]*\\{"
        fi
        while IFS= read -r source_file; do
            if grep -Eq "$declaration_pattern" "$source_file"; then
                fail "legacy function declaration remains in $source_file: $function_name"
                return 1
            fi
        done < <(qbox_shell_source_files)
    done
}

run_pw_selector_with_local_task() {
    local rtask='unset'
    qe_pwin_select_task <<< '1' || return 1
    printf 'rtask=%s\n' "$rtask"
}

test_pw_helper_uses_caller_scope() {
    local output
    output="$(run_pw_selector_with_local_task)" || return 1
    assert_contains "$output" 'rtask=energy' 'PW task selector did not update caller scope'
}

run_md_menu_with_local_settings() {
    local kpmesh='custom-kmesh'
    local pseudolib='custom-lib'
    local md_time_ps='9'
    local md_timestep_fs='0.5'
    local md_fix_bottom='NO'
    local md_use_atomic_velocities='NO'
    qe_md_menu || return 1
}

test_md_helper_reads_caller_scope() {
    local output
    output="$(run_md_menu_with_local_settings)" || return 1
    assert_contains "$output" '当前：custom-kmesh' 'MD menu did not read caller k-mesh'
    assert_contains "$output" '当前：custom-lib' 'MD menu did not read caller pseudopotential library'
    assert_contains "$output" '当前：9 ps' 'MD menu did not read caller total time'
    assert_contains "$output" '当前：0.5 fs' 'MD menu did not read caller timestep'
    assert_contains "$output" '当前：NO' 'MD menu did not read caller settings'
}

run_phonon_builder_in_sandbox() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        prefix='phonon-smoke'
        ntyp=1
        atmtype[1]='Si'
        qe_phonon_nonpolar_frequency
        assert_contains "$(cat phonon-smoke.ph.in)" "prefix='phonon-smoke'" || exit 1
        assert_contains "$(cat phonon-smoke.dynmat.in)" "asr='simple'" || exit 1
    )
}

test_phonon_builder_preserves_input_contract() {
    run_phonon_builder_in_sandbox
}

test_phonon_menu_preserves_output() {
    local output
    output="$(qe_phonon_menu)" || return 1
    assert_contains "$output" '1) 表面/吸附模型' 'phonon menu output changed'
}

test_bandin_menu_preserves_output() {
    local bands_lsym='false' output
    output="$(qe_bandin_menu)" || return 1
    assert_contains "$output" '0) 立即生成 bands.x 输入文件' 'bands menu output changed'
    assert_contains "$output" '当前：.false.' 'bands menu did not read caller scope'
}

test_clean_pdos_next_steps_preserves_output() {
    local output
    output="$(qe_builtin_clean_pdos_next_steps 'ATOM_PDOS')" || return 1
    assert_contains "$output" '后续建议：' 'cleanPDOS next-step heading changed'
    assert_contains "$output" '进入 ATOM_PDOS 后确认 sumpdos.x 已在 PATH 中。' 'cleanPDOS destination changed'
}

test_cluster_menu_and_mass_helper_preserve_contract() {
    local cv_energy='200' cv_direction='0 0 -1' menu_output mass
    menu_output="$(qe_cluster_menu)" || return 1
    assert_contains "$menu_output" '团簇/分子 ATOMIC_VELOCITIES 生成' 'cluster menu output changed'
    mass="$(qe_element_mass_from_symbol C)" || return 1
    assert_eq "$mass" '12.011' 'carbon mass helper output changed'
}

test_all_lexical_functions_load_after_source() {
    local sandbox lexical loaded
    sandbox="$(new_sandbox)" || return 1
    lexical="$sandbox/lexical"
    loaded="$sandbox/loaded"
    qbox_lexical_functions >"$lexical" || return 1
    qbox_loaded_functions >"$loaded" || return 1
    if [ -n "$(uniq -d "$lexical")" ]; then
        fail 'lexical function extraction contains duplicate names'
        return 1
    fi
    assert_file_equals "$lexical" "$loaded" 'lexical functions differ from functions loaded after source'
}

run_test 'new helper names are top-level' test_new_helpers_are_top_level
run_test 'legacy function declarations are absent from source' test_legacy_function_declarations_are_removed
run_test 'PW helper uses caller scope' test_pw_helper_uses_caller_scope
run_test 'MD helper reads caller scope' test_md_helper_reads_caller_scope
run_test 'phonon builder preserves input contract' test_phonon_builder_preserves_input_contract
run_test 'phonon menu preserves output' test_phonon_menu_preserves_output
run_test 'bands menu preserves output' test_bandin_menu_preserves_output
run_test 'cleanPDOS next steps preserve output' test_clean_pdos_next_steps_preserves_output
run_test 'cluster menu and mass helper preserve contract' test_cluster_menu_and_mass_helper_preserve_contract
run_test 'all lexical functions load after source' test_all_lexical_functions_load_after_source
finish_tests
