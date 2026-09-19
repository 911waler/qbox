#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"

source_qbox

STRUCTURE_FIXTURE="$PROJECT_ROOT/tests/fixtures/structures/water.cif"
QE_TMP_FIXTURE="$PROJECT_ROOT/tests/fixtures/qe-inputs/water_QE.tmp"

prepare_pw_generation_state() {
    local sandbox="$1"
    cp -- "$STRUCTURE_FIXTURE" "$sandbox/water.cif" || return 1
    cp -- "$QE_TMP_FIXTURE" "$sandbox/water_QE.tmp" || return 1

    prefix='water'
    QE_STRUCT_INPUT="$sandbox/water.cif"
    QE_STRUCT_SOURCE="$sandbox/water.cif"
    QE_STRUCT_TMP="$sandbox/water_QE.tmp"
    natm=3
    ntyp=2
    begcellpos=7
    endcellpos=9
    begatmpos=11
    endatmpos=13
    atmtype[1]='H'
    Natmtype[1]=2
    atmtype[2]='O'
    Natmtype[2]=1
    a_1=10.000000000
    a_2=10.000000000
    a_3=10.000000000
    k_1=3
    k_2=3
    k_3=3
    magarr[1]=0
    magarr[2]=0
    lsda=''

    systype='Semi-conductor'
    func='PBE'
    dispcorr='None'
    dipcorr='None'
    dftu='No'
    pwin_nosym='No'
    kpmesh='3*3*3'
    nscf_kpmesh='6*6*6'
    nbnd='Default'
    PWIN_DEFAULT_BANDS_NBND_FACTOR=''
    PWIN_DEFAULT_BANDS_NBND_MIN=''
    pwin_ecutwfc_override=''
    pwin_ecutrho_override=''
    pwin_scf_conv_thr='1.D-6'
    pwin_diagonalization='david'
    pwin_diago_david_ndim=2
    pwin_diago_cg_maxiter=20
    pwin_diago_full_acc='true'
    pwin_diago_thr_init='1.D-8'
    pseudolib='SSSP'
    band_kpath_mode='fixed'
    band_kpath_points=20
    band_kpath_spacing='0.02'

    # Keep the characterization independent of installed pseudo files while
    # preserving the normal H/O, nonmagnetic defaults.
    pseudo_dir_by_lib() { printf '%s\n' '/mock/SSSP'; }
    default_cutoffs_from_pseudos() { printf '%s\n' '35 400'; }
    qe_estimate_nelec_from_current_pwin_context() { printf '%s\n' '10'; }
}

generate_pw_case() {
    local sandbox="$1" task="$2"
    (
        cd "$sandbox" || exit 1
        prepare_pw_generation_state "$sandbox" || exit 1
        rtask="$task"
        qe_generate_pw_input >generator.log 2>&1
    )
}

profile_snapshot() {
    printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
        "${QE_TASK_OUTPUT-}" \
        "${QE_TASK_CALCULATION-}" \
        "${QE_TASK_VERBOSITY-}" \
        "${QE_TASK_PRINT_FORCE_STRESS-}" \
        "${QE_TASK_ETOT_CONV_THR-}" \
        "${QE_TASK_FORC_CONV_THR-}" \
        "${QE_TASK_NSTEP-}" \
        "${QE_TASK_SYSTEM_KIND-}" \
        "${QE_TASK_ELECTRONS_KIND-}" \
        "${QE_TASK_KPOINTS_KIND-}" \
        "${QE_TASK_WRITE_IONS-}" \
        "${QE_TASK_WRITE_CELL-}" \
        "${QE_TASK_CELL_DOFREE-}"
}

test_task_profile_sets_every_field() {
    local task expected actual
    prefix='water'
    while IFS='|' read -r task expected; do
        [ -n "$task" ] || continue
        qe_task_profile "$task" || {
            fail "task profile rejected supported task: $task"
            return 1
        }
        actual="$(profile_snapshot)"
        assert_eq "$expected" "$actual" "task profile changed for $task" || return 1
    done <<'PROFILES'
energy|water.scf.in|scf|low|0||||scf|scf|automatic|0|0|
energy+force+stress|water.scf.in|scf|low|1||||scf|scf|automatic|0|0|
structural optimization(relax)|water.relax.in|relax|high|0|1.D-6|1.D-4|300|relax|relax|automatic|1|0|
cell optimization(vc-relax)|water.vcrelax.in|vc-relax|low|0|1.D-5|1.D-3|300|vc-relax|vc-relax|automatic|1|1|
cell optimization for 2D materials|water.vcrelax.in|vc-relax|low|0|1.D-5|1.D-3|300|vc-relax|vc-relax|automatic|1|1|2Dxy
bands|water.bands.in|bands|high|0||||bands|bands|bands|0|0|
nscf|water.nscf.in|nscf|high|0||||nscf|nscf|automatic|0|0|
PROFILES
}

test_task_profile_clears_stale_fields_and_rejects_unknown() {
    local field
    prefix='water'
    for field in \
        QE_TASK_OUTPUT QE_TASK_CALCULATION QE_TASK_VERBOSITY \
        QE_TASK_PRINT_FORCE_STRESS QE_TASK_ETOT_CONV_THR \
        QE_TASK_FORC_CONV_THR QE_TASK_NSTEP QE_TASK_SYSTEM_KIND \
        QE_TASK_ELECTRONS_KIND QE_TASK_KPOINTS_KIND QE_TASK_WRITE_IONS \
        QE_TASK_WRITE_CELL QE_TASK_CELL_DOFREE; do
        printf -v "$field" '%s' stale
    done
    if qe_task_profile unknown >/dev/null 2>&1; then
        fail 'unknown task was accepted'
        return 1
    fi
    for field in \
        QE_TASK_OUTPUT QE_TASK_CALCULATION QE_TASK_VERBOSITY \
        QE_TASK_PRINT_FORCE_STRESS QE_TASK_ETOT_CONV_THR \
        QE_TASK_FORC_CONV_THR QE_TASK_NSTEP QE_TASK_SYSTEM_KIND \
        QE_TASK_ELECTRONS_KIND QE_TASK_KPOINTS_KIND QE_TASK_WRITE_IONS \
        QE_TASK_WRITE_CELL QE_TASK_CELL_DOFREE; do
        assert_eq '' "${!field-}" "unknown task left stale $field" || return 1
    done
}

test_pw_writer_interfaces_are_top_level() {
    local writer
    for writer in \
        qe_write_pw_control qe_write_pw_system qe_write_pw_electrons \
        qe_write_pw_ions_cell qe_write_pw_structure qe_write_pw_kpoints \
        qe_write_pw_hubbard; do
        declare -F "$writer" >/dev/null || {
            fail "missing PW writer: $writer"
            return 1
        }
    done
}

test_magnetic_comparison_and_lsda_behavior_are_source_locked() {
    local body
    body="$(declare -f qe_write_pw_system)"
    assert_contains "$body" '[[ "${magarr[$i]}" > "0" ]]' \
        'PW system writer changed its magnetic comparison' || return 1
    assert_not_contains "$body" 'local lsda' \
        'PW system writer introduced a local lsda declaration' || return 1
    assert_not_contains "$body" 'lsda=""' \
        'PW system writer initializes lsda with an empty value' || return 1
    assert_not_contains "$body" "lsda=''" \
        'PW system writer initializes lsda with an empty value' || return 1
    assert_contains "$body" 'lsda=on' \
        'PW system writer no longer enables spin polarization' || return 1
    assert_contains "$body" 'if [ "$lsda" == "on" ]; then' \
        'PW system writer no longer checks lsda state' || return 1
    assert_contains "$body" 'starting_magnetization(%s)' \
        'PW system writer no longer emits per-type magnetization'
}

test_element_range_and_ambient_atmindex_are_source_locked() {
    local body source
    body="$(declare -f qe_write_pw_structure)"
    source="$(declare -f qe_write_pw_structure)"
    assert_contains "$source" 'for ((j=1; j<=86; j++))' \
        'PW element lookup range changed' || return 1
    assert_contains "$source" 'if [ "${atmtype[$i]}" == "${atm[$j]}" ]; then' \
        'PW element lookup no longer matches symbols' || return 1
    assert_contains "$source" 'atmindex=$j' \
        'PW element lookup no longer records the matched index' || return 1
    assert_contains "$source" 'atmmass[$atmindex]' \
        'PW structure writer no longer uses the matched atomic mass' || return 1
    assert_contains "$source" 'pseudo_file_by_lib "$pseudolib" "$atmindex"' \
        'PW structure writer no longer uses the matched pseudopotential' || return 1
    assert_not_contains "$source" 'atmindex='"''" \
        'PW structure writer resets ambient atmindex' || return 1
    assert_not_contains "$body" 'atmindex=""' \
        'PW structure writer clears ambient atmindex' || return 1
    assert_not_contains "$body" "atmindex=''" \
        'PW structure writer clears ambient atmindex' || return 1
    assert_not_contains "$body" 'atmindex=0' \
        'PW structure writer resets ambient atmindex'
}

test_writer_bodies_do_not_reinterpret_rtask() {
    local writer body
    for writer in \
        qe_write_pw_control qe_write_pw_system qe_write_pw_electrons \
        qe_write_pw_ions_cell qe_write_pw_structure qe_write_pw_kpoints \
        qe_write_pw_hubbard; do
        body="$(declare -f "$writer")"
        assert_not_contains "$body" '"$rtask"' \
            "$writer still interprets rtask"
    done
}

test_pw_generation_goldens() {
    local sandbox task expected output
    while IFS='|' read -r task output expected; do
        [ -n "$task" ] || continue
        sandbox="$(new_sandbox)" || return 1
        generate_pw_case "$sandbox" "$task" || {
            fail "PW generation failed for $task"
            return 1
        }
        expected="$TESTS_DIR/fixtures/expected/pw/$expected"
        assert_or_update_golden "$expected" "$sandbox/$output" \
            "PW output changed for $task" || return 1
    done <<'CASES'
energy|water.scf.in|water.scf.in
nscf|water.nscf.in|water.nscf.in
bands|water.bands.in|water.bands.in
structural optimization(relax)|water.relax.in|water.relax.in
cell optimization(vc-relax)|water.vcrelax.in|water.vcrelax.in
cell optimization for 2D materials|water.vcrelax.in|water.vcrelax-2d.in
CASES
}

run_test 'task profile sets every field' test_task_profile_sets_every_field
run_test 'task profile clears stale fields and rejects unknown' test_task_profile_clears_stale_fields_and_rejects_unknown
run_test 'PW writer interfaces are top-level' test_pw_writer_interfaces_are_top_level
run_test 'magnetic comparison and lsda behavior stay source-locked' test_magnetic_comparison_and_lsda_behavior_are_source_locked
run_test 'element range and ambient atmindex stay source-locked' test_element_range_and_ambient_atmindex_are_source_locked
run_test 'PW writers do not reinterpret rtask' test_writer_bodies_do_not_reinterpret_rtask
run_test 'PW generation matches expected goldens' test_pw_generation_goldens
finish_tests
