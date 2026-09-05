#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

assert_no_postprocess_staging() {
    local sandbox="$1"
    if find "$sandbox" -maxdepth 1 -name '.qbox-*' -print -quit | grep -q .; then
        fail 'qbox staging directory leaked'
        return 1
    fi
}

test_relax_context_is_explicit() {
    local sandbox context expected
    sandbox="$(new_sandbox)" || return 1
    context="$sandbox/context.txt"
    qbox_parse_relax_output "$TESTS_DIR/fixtures/postprocess/relax.out" "$context" || return 1
    [ -s "$context" ] || fail 'relax parser did not write a context file'
    expected=$'source_kind\trelax_output\nibrav\t0\nnormal_exit\tYES\nnat\t3\ncell_unit\tangstrom\natom_unit\tangstrom\ncell_row\t1\t10.000000000\t0.000000000\t0.000000000\ncell_row\t2\t0.000000000\t10.000000000\t0.000000000\ncell_row\t3\t0.000000000\t0.000000000\t10.000000000\natom\t1\tO\t5.000000000\t5.000000000\t5.000000000\natom\t2\tH\t5.570000000\t5.000000000\t5.000000000\natom\t3\tH\t4.810000000\t5.540000000\t5.000000000'
    assert_eq "$expected" "$(cat "$context")" 'relax context schema or values changed' || return 1
    assert_no_postprocess_staging "$sandbox"
}

test_relax_parser_uses_last_complete_block() {
    local sandbox output context contents
    sandbox="$(new_sandbox)" || return 1
    output="$sandbox/relax.out"
    context="$sandbox/context.txt"
    printf '%s\n' \
        'Program PWSCF' \
        'bravais-lattice index = 0' \
        'number of atoms/cell = 2' \
        'CELL_PARAMETERS (angstrom)' \
        '10 0 0' '0 10 0' '0 0 10' \
        'ATOMIC_POSITIONS (angstrom)' \
        'H 1 1 1' 'H 2 2 2' \
        'CELL_PARAMETERS (angstrom)' \
        '11 0 0' '0 11 0' '0 0 11' \
        'ATOMIC_POSITIONS (angstrom)' \
        'O 3 3 3' 'H 4 4 4' \
        'ATOMIC_POSITIONS (angstrom)' \
        'C 9 9 9' \
        'JOB DONE.' >"$output"

    qbox_parse_relax_output "$output" "$context" || return 1
    contents="$(cat "$context")"
    assert_contains "$contents" $'normal_exit\tYES' 'malformed trailing block hid normal termination' || return 1
    assert_contains "$contents" $'atom\t1\tO\t3\t3\t3' 'parser did not retain the last complete atom block' || return 1
    assert_not_contains "$contents" $'atom\t1\tC\t9\t9\t9' 'parser accepted an incomplete trailing atom block'
}

test_relax_parser_rejects_unsupported_atom_unit_without_clobbering() {
    local sandbox output context status
    sandbox="$(new_sandbox)" || return 1
    output="$sandbox/invalid-unit.out"
    context="$sandbox/context.txt"
    printf 'existing context\n' >"$context"
    cp -- "$context" "$sandbox/expected-context.txt"
    printf '%s\n' \
        'bravais-lattice index = 0' \
        'number of atoms/cell = 1' \
        'CELL_PARAMETERS (angstrom)' \
        '1 0 0' '0 1 0' '0 0 1' \
        'ATOMIC_POSITIONS (alat)' \
        'H 0 0 0' \
        'JOB DONE.' >"$output"

    qbox_parse_relax_output "$output" "$context"
    status=$?
    [ "$status" -ne 0 ] || { fail 'relax parser accepted unsupported coordinate units'; return 1; }
    assert_file_equals "$sandbox/expected-context.txt" "$context" \
        'unsupported relax coordinate unit clobbered existing context' || return 1
    assert_no_postprocess_staging "$sandbox"
}

test_relax_parser_rejects_invalid_geometry_without_clobbering() {
    local sandbox output context expected status
    sandbox="$(new_sandbox)" || return 1
    output="$sandbox/invalid.out"
    context="$sandbox/context.txt"
    printf 'existing context\n' >"$context"
    cp -- "$context" "$sandbox/expected-context.txt"
    printf '%s\n' \
        'bravais-lattice index = 1' \
        'number of atoms/cell = 1' \
        'CELL_PARAMETERS (angstrom)' \
        '1 0 0' '0 1 0' '0 0 1' \
        'ATOMIC_POSITIONS (angstrom)' \
        'H 0 0 0' >"$output"

    qbox_parse_relax_output "$output" "$context"
    status=$?
    [ "$status" -ne 0 ] || { fail 'nonzero ibrav was accepted'; return 1; }
    assert_file_equals "$sandbox/expected-context.txt" "$context" 'failed parser clobbered existing context' || return 1
    assert_no_postprocess_staging "$sandbox"
}

test_pw_input_context_is_explicit_and_validated() {
    local sandbox context invalid status contents
    sandbox="$(new_sandbox)" || return 1
    context="$sandbox/context.txt"
    invalid="$sandbox/invalid.in"
    qbox_parse_pw_input "$TESTS_DIR/fixtures/expected/pw/water.relax.in" "$context" || return 1
    contents="$(cat "$context")"
    assert_contains "$contents" $'source_kind\tpw_input' 'PW parser wrote the wrong source kind' || return 1
    assert_contains "$contents" $'normal_exit\tNO' 'PW parser wrote an invalid normal-exit value' || return 1
    assert_contains "$contents" $'atom_unit\tangstrom' 'PW parser did not record the coordinate unit' || return 1
    assert_contains "$contents" $'atom\t3\tH\t4.810000000\t5.540000000\t5.000000000' 'PW parser lost atom rows' || return 1

    sed 's/ATOMIC_POSITIONS angstrom/ATOMIC_POSITIONS alat/' \
        "$TESTS_DIR/fixtures/expected/pw/water.relax.in" >"$invalid"
    qbox_parse_pw_input "$invalid" "$sandbox/invalid-context.txt"
    status=$?
    [ "$status" -ne 0 ] || fail 'PW parser accepted unsupported coordinate units'
}

test_gjf_writer_has_public_metadata() {
    local sandbox context gjf
    sandbox="$(new_sandbox)" || return 1
    context="$sandbox/context.txt"
    gjf="$sandbox/water.gjf"
    qbox_parse_relax_output "$TESTS_DIR/fixtures/postprocess/relax.out" "$context" || return 1
    qbox_write_gjf "$context" "$gjf" || return 1
    assert_contains "$(cat "$gjf")" 'Generated by qbox' 'GJF metadata is not branded qbox'
}

test_gjf_writer_rolls_back_invalid_context() {
    local sandbox context gjf status
    sandbox="$(new_sandbox)" || return 1
    context="$sandbox/context.txt"
    gjf="$sandbox/water.gjf"
    printf '%s\n' $'nat\t2' $'cell_row\t1\t1\t0\t0' $'atom\t1\tH\t0\t0\t0' >"$context"
    printf 'existing gjf\n' >"$gjf"
    cp -- "$gjf" "$sandbox/expected.gjf"

    qbox_write_gjf "$context" "$gjf"
    status=$?
    [ "$status" -ne 0 ] || { fail 'GJF writer accepted an incomplete context'; return 1; }
    assert_file_equals "$sandbox/expected.gjf" "$gjf" 'failed GJF render clobbered existing output' || return 1
    assert_no_postprocess_staging "$sandbox"
}

test_md_writer_uses_only_explicit_paths() {
    local sandbox md_output xyz_output contents
    sandbox="$(new_sandbox)" || return 1
    md_output="$sandbox/requested.md.out"
    xyz_output="$sandbox/requested.xyz"
    printf '%s\n' \
        'number of atoms/cell = 2' \
        'Entering Dynamics: iteration = 7' \
        'time = 0.250 ps' \
        'ATOMIC_POSITIONS (crystal)' \
        'H 0.1 0.2 0.3' \
        'O 0.4 0.5 0.6' >"$md_output"
    printf 'unrelated\n' >"$sandbox/unrelated.md.out"
    fname1="$sandbox/unrelated.md.out"
    prefix="$sandbox/unrelated-prefix"

    qbox_convert_md_to_xyz "$md_output" "$xyz_output" || return 1
    contents="$(cat "$xyz_output")"
    assert_contains "$contents" 'Step 0, QE iteration = 7, time = 0.250 ps, ATOMIC_POSITIONS unit = crystal' \
        'MD frame metadata changed' || return 1
    assert_contains "$contents" 'H        0.10000000       0.20000000       0.30000000' \
        'MD coordinates were not written from the requested file' || return 1
    [ ! -e "$sandbox/unrelated-prefix.xyz" ] || fail 'MD writer derived output from a global prefix'
}

test_md_cif_bridge_does_not_emit_task_context() {
    local source_text bridge_body
    source_text="$(cat "$PROJECT_ROOT/qbox")"
    assert_contains "$source_text" 'function qbox_write_md_gjf' 'MD CIF bridge does not use a direct GJF writer' || return 1
    assert_not_contains "$source_text" 'function qbox_write_md_context' 'MD CIF bridge still exposes a context writer' || return 1
    assert_not_contains "$source_text" 'source_kind\\tmd_output' 'MD CIF bridge emits a noncanonical Task 4 context' || return 1
    bridge_body="$(sed -n '/^function qbox_write_md_gjf /,/^function md2cif_extract_target /p' <<<"$source_text")"
    assert_contains "$bridge_body" 'Generated by qbox' 'direct MD GJF writer lost public metadata' || return 1
    assert_not_contains "$bridge_body" 'source_kind' 'direct MD GJF writer emits context records'
}

test_postprocess_stage_registration_uses_caller_scope() {
    local sandbox output stage registered path
    sandbox="$(new_sandbox)" || return 1
    output="$sandbox/water.gjf"
    stage=''
    QE_CLEANUP_PATHS=()

    qbox_postprocess_stage_dir "$output" registration stage || return 1
    [ -n "$stage" ] || { fail 'stage helper did not set the caller-owned variable'; return 1; }
    registered=0
    for path in "${QE_CLEANUP_PATHS[@]}"; do
        if [ "$path" = "$stage" ]; then
            registered=1
            break
        fi
    done
    [ "$registered" -eq 1 ] || { fail 'stage registration was lost in command substitution'; return 1; }
    qbox_postprocess_remove_stage "$stage" || return 1
    assert_no_postprocess_staging "$sandbox"
}

test_gjf_to_cif_validates_and_installs_staged_output() {
    local sandbox gjf cif expected link mode status menu_path
    sandbox="$(new_sandbox)" || return 1
    gjf="$sandbox/water.gjf"
    cif="$sandbox/water.cif"
    link="$sandbox/water-link.cif"
    printf 'gjf input\n' >"$gjf"
    printf 'existing cif\n' >"$cif"
    cp -- "$cif" "$sandbox/expected.cif"

    require_multiwfn() { return 0; }
    qbox_multiwfn() {
        read -r _
        read -r _
        read -r _
        read -r menu_path
        if [ "$mode" = symlink ]; then
            ln -s -- "$cif" "$menu_path"
        else
            printf 'data_water\n' >"$menu_path"
        fi
    }

    mode=regular
    qbox_convert_gjf_to_cif "$gjf" "$cif" || return 1
    assert_contains "$(cat "$cif")" 'data_water' 'CIF converter did not install staged output' || return 1
    assert_no_postprocess_staging "$sandbox" || return 1

    cp -- "$sandbox/expected.cif" "$cif"
    mode=symlink
    qbox_convert_gjf_to_cif "$gjf" "$cif"
    status=$?
    [ "$status" -ne 0 ] || { fail 'CIF converter accepted a symlink staged output'; return 1; }
    assert_file_equals "$sandbox/expected.cif" "$cif" 'invalid staged CIF clobbered the target' || return 1
    assert_no_postprocess_staging "$sandbox" || return 1

    ln -s -- "$cif" "$link"
    mode=regular
    qbox_convert_gjf_to_cif "$gjf" "$link"
    status=$?
    [ "$status" -ne 0 ] || fail 'CIF converter accepted a symlink output target'
}

test_nscf_builder_reconstructs_explicit_output() {
    local sandbox relax_input relax_output nscf contents
    sandbox="$(new_sandbox)" || return 1
    relax_input="$sandbox/water.relax.in"
    relax_output="$sandbox/water.relax.out"
    nscf="$sandbox/custom-output.in"
    cp -- "$TESTS_DIR/fixtures/expected/pw/water.relax.in" "$relax_input"
    printf '%s\n' \
        'Program PWSCF' \
        'bravais-lattice index = 0' \
        'number of atoms/cell = 3' \
        'number of electrons = 10.00' \
        'CELL_PARAMETERS (angstrom)' \
        '11 0 0' '0 12 0' '0 0 13' \
        'ATOMIC_POSITIONS (angstrom)' \
        'O 1 2 3' 'H 4 5 6' 'H 7 8 9' \
        'End final coordinates' \
        'JOB DONE.' >"$relax_output"

    qbox_build_nscf_input "$relax_input" "$relax_output" "$nscf" || return 1
    contents="$(cat "$nscf")"
    assert_contains "$contents" "calculation     = 'nscf'" 'NSCF calculation mode was not set' || return 1
    assert_not_contains "$contents" 'nstep' 'NSCF output retained nstep' || return 1
    assert_contains "$contents" '11.000000000' 'NSCF output did not use the final cell' || return 1
    assert_contains "$contents" 'O      1.000000000    2.000000000    3.000000000' 'NSCF output did not use final coordinates' || return 1
    assert_contains "$contents" 'nbnd            = 13' 'NSCF nbnd recommendation changed' || return 1
    assert_no_postprocess_staging "$sandbox"
}

test_nscf_builder_rewrites_atom_unit_from_relax_output() {
    local sandbox relax_input relax_output nscf contents
    sandbox="$(new_sandbox)" || return 1
    relax_input="$sandbox/water.relax.in"
    relax_output="$sandbox/water.relax.out"
    nscf="$sandbox/custom-output.in"
    cp -- "$TESTS_DIR/fixtures/expected/pw/water.relax.in" "$relax_input"
    printf '%s\n' \
        'Program PWSCF' \
        'bravais-lattice index = 0' \
        'number of atoms/cell = 3' \
        'number of electrons = 10.00' \
        'CELL_PARAMETERS (angstrom)' \
        '11 0 0' '0 12 0' '0 0 13' \
        'ATOMIC_POSITIONS (crystal)' \
        'O 0.1 0.2 0.3' 'H 0.4 0.5 0.6' 'H 0.7 0.8 0.9' \
        'End final coordinates' \
        'JOB DONE.' >"$relax_output"

    qbox_build_nscf_input "$relax_input" "$relax_output" "$nscf" || return 1
    contents="$(cat "$nscf")"
    assert_contains "$contents" $' ATOMIC_POSITIONS crystal\n' \
        'NSCF output did not adopt the relax coordinate unit' || return 1
    assert_not_contains "$contents" $' ATOMIC_POSITIONS angstrom\n' \
        'NSCF output retained the input coordinate unit' || return 1
    assert_contains "$contents" 'O      0.100000000    0.200000000    0.300000000' \
        'NSCF output changed relax coordinate values while changing unit' || return 1
    assert_no_postprocess_staging "$sandbox"
}

test_nscf_builder_rejects_unsupported_relax_atom_unit_without_clobbering() {
    local sandbox relax_output nscf status
    sandbox="$(new_sandbox)" || return 1
    relax_output="$sandbox/water.relax.out"
    nscf="$sandbox/existing-output.in"
    printf 'existing output\n' >"$nscf"
    cp -- "$nscf" "$sandbox/expected-output.in"
    printf '%s\n' \
        'Program PWSCF' \
        'bravais-lattice index = 0' \
        'number of atoms/cell = 3' \
        'CELL_PARAMETERS (angstrom)' \
        '11 0 0' '0 12 0' '0 0 13' \
        'ATOMIC_POSITIONS (alat)' \
        'O 1 2 3' 'H 4 5 6' 'H 7 8 9' \
        'JOB DONE.' >"$relax_output"

    qbox_build_nscf_input "$TESTS_DIR/fixtures/expected/pw/water.relax.in" \
        "$relax_output" "$nscf"
    status=$?
    [ "$status" -ne 0 ] || { fail 'NSCF builder accepted unsupported relax coordinate units'; return 1; }
    assert_file_equals "$sandbox/expected-output.in" "$nscf" \
        'unsupported relax coordinate unit clobbered NSCF output' || return 1
    assert_no_postprocess_staging "$sandbox"
}

test_nscf_builder_rejects_unsafe_target_and_rolls_back_failure() {
    local sandbox target link status
    sandbox="$(new_sandbox)" || return 1
    target="$sandbox/existing.in"
    link="$sandbox/link.in"
    printf 'existing output\n' >"$target"
    cp -- "$target" "$sandbox/expected.in"

    qbox_build_nscf_input "$TESTS_DIR/fixtures/expected/pw/water.relax.in" \
        "$sandbox/missing.out" "$target"
    status=$?
    [ "$status" -ne 0 ] || { fail 'missing relax output was accepted'; return 1; }
    assert_file_equals "$sandbox/expected.in" "$target" 'failed NSCF build clobbered output' || return 1

    ln -s -- "$target" "$link"
    qbox_build_nscf_input "$TESTS_DIR/fixtures/expected/pw/water.relax.in" \
        "$TESTS_DIR/fixtures/postprocess/relax.out" "$link"
    status=$?
    [ "$status" -ne 0 ] || fail 'NSCF builder accepted a symlink target'
}

test_constraint_writer_isolated() {
    local sandbox input output contents
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/water.in"
    output="$sandbox/water-fixed.in"
    cp "$TESTS_DIR/fixtures/expected/pw/water.scf.in" "$input"
    qbox_apply_constraints "$input" '1,2' '0 0 0' "$output" || return 1
    [ -s "$output" ] || fail 'constraint writer did not produce output'
    contents="$(cat "$output")"
    assert_contains "$contents" 'O      5.000000000    5.000000000    5.000000000    0 0 0' 'first atom flags were not written' || return 1
    assert_contains "$contents" 'H      5.570000000    5.000000000    5.000000000    0 0 0' 'second atom flags were not written' || return 1
    assert_contains "$contents" 'H      4.810000000    5.540000000    5.000000000' 'unselected atom changed' || return 1
    assert_file_equals "$TESTS_DIR/fixtures/expected/pw/water.scf.in" "$input" 'constraint writer modified its input file' || return 1
    assert_no_postprocess_staging "$sandbox"
}

test_constraint_writer_rejects_bad_ranges_without_clobbering() {
    local sandbox input output spec status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/water.in"
    output="$sandbox/water-fixed.in"
    cp -- "$TESTS_DIR/fixtures/expected/pw/water.scf.in" "$input"
    printf 'existing output\n' >"$output"
    cp -- "$output" "$sandbox/expected.in"

    for spec in '3-1' 'one' '1,,2' '4'; do
        qbox_apply_constraints "$input" "$spec" '0 0 0' "$output"
        status=$?
        [ "$status" -ne 0 ] || { fail "invalid atom specification was accepted: $spec"; return 1; }
        assert_file_equals "$sandbox/expected.in" "$output" "invalid atom specification clobbered output: $spec" || return 1
    done
    qbox_apply_constraints "$input" '1,2' '0 2 0' "$output"
    status=$?
    [ "$status" -ne 0 ] || fail 'invalid if_pos was accepted'
}

test_dispatch_and_definitions_use_qbox_interfaces() {
    local source_text handler
    source_text="$(cat "$PROJECT_ROOT/qbox")"
    assert_eq 'qbox_md_to_xyz_menu' "$(qe_action_handler 26)" 'action 26 still targets the legacy MD handler' || return 1
    assert_eq 'qbox_nscf_menu' "$(qe_action_handler 27)" 'action 27 still targets the legacy NSCF handler' || return 1
    assert_eq 'qbox_constraints_menu' "$(qe_action_handler 30)" 'action 30 does not target the qbox constraints menu' || return 1
    for handler in qbox_md_to_xyz_menu qbox_nscf_menu qbox_constraints_menu; do
        [ "$(type -t "$handler")" = function ] || {
            fail "dispatcher target is not a defined qbox menu: $handler"
            return 1
        }
    done
    assert_contains "$source_text" 'qbox_postprocess_cif' 'CIF menu does not use the qbox CIF core' || return 1
    assert_contains "$source_text" 'qbox_postprocess_xyz' 'MD menu does not use the qbox XYZ core' || return 1
    assert_contains "$source_text" 'qbox_postprocess_nscf' 'NSCF menu does not use the qbox NSCF core' || return 1
    assert_contains "$source_text" 'qbox_postprocess_constraints' 'constraint menu does not use the qbox constraints core' || return 1
    if grep -Eq '^function (relaxcheck|infcheck|relax2cif|relax2nscf|fixatm|mdout2xyz)[[:space:]]*\(\)' <<<"$source_text"; then
        fail 'legacy post-processing function definition remains public'
        return 1
    fi
    if grep -Eq '(^|[^[:alnum:]_])(relaxcheck|write_qe_structure_gjf_tmp|relax2cif|relax2nscf|fixatm|mdout2xyz)([^[:alnum:]_]|$)' <<<"$source_text"; then
        fail 'legacy post-processing target remains in qbox source'
        return 1
    fi
}

run_test 'relax parser writes an explicit context' test_relax_context_is_explicit
run_test 'relax parser keeps the last complete block' test_relax_parser_uses_last_complete_block
run_test 'relax parser rejects unsupported coordinate units atomically' test_relax_parser_rejects_unsupported_atom_unit_without_clobbering
run_test 'relax parser rejects invalid geometry atomically' test_relax_parser_rejects_invalid_geometry_without_clobbering
run_test 'PW parser writes and validates explicit context' test_pw_input_context_is_explicit_and_validated
run_test 'GJF writer uses qbox metadata only' test_gjf_writer_has_public_metadata
run_test 'GJF writer rolls back invalid context' test_gjf_writer_rolls_back_invalid_context
run_test 'MD writer uses only explicit paths' test_md_writer_uses_only_explicit_paths
run_test 'MD CIF bridge does not emit a Task 4 context' test_md_cif_bridge_does_not_emit_task_context
run_test 'post-process staging registration stays in caller scope' test_postprocess_stage_registration_uses_caller_scope
run_test 'GJF to CIF conversion validates staged output atomically' test_gjf_to_cif_validates_and_installs_staged_output
run_test 'NSCF builder reconstructs explicit final geometry' test_nscf_builder_reconstructs_explicit_output
run_test 'NSCF builder rewrites coordinate units from relax output' test_nscf_builder_rewrites_atom_unit_from_relax_output
run_test 'NSCF builder rejects unsupported relax units atomically' test_nscf_builder_rejects_unsupported_relax_atom_unit_without_clobbering
run_test 'NSCF builder rejects unsafe output and rolls back' test_nscf_builder_rejects_unsafe_target_and_rolls_back_failure
run_test 'constraint writer uses isolated output' test_constraint_writer_isolated
run_test 'constraint writer rejects invalid ranges atomically' test_constraint_writer_rejects_bad_ranges_without_clobbering
run_test 'dispatcher and definitions use qbox interfaces' test_dispatch_and_definitions_use_qbox_interfaces
finish_tests
