#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

STRUCTURE_FIXTURE="$PROJECT_ROOT/tests/fixtures/structures/water.cif"
QE_TMP_FIXTURE="$PROJECT_ROOT/tests/fixtures/qe-inputs/water_QE.tmp"
MOCK_MULTIWFN_DIR="$PROJECT_ROOT/tests/mocks"

prepare_structure_sandbox() {
    local sandbox="$1"
    cp -- "$STRUCTURE_FIXTURE" "$sandbox/water.cif" || return 1
    export QBOX_MOCK_QE_TMP="$QE_TMP_FIXTURE"
    Multiwfnpath="$MOCK_MULTIWFN_DIR"
    PATH="$MOCK_MULTIWFN_DIR:$PATH"
    fname1="$sandbox/water.cif"
    qe_set_input_path "$fname1"
}

install_existing_structure_context() {
    local sandbox="$1" context_dir
    context_dir="$sandbox/.qbox-structure-existing"
    mkdir -p "$context_dir" || return 1
    cp -- "$QE_TMP_FIXTURE" "$context_dir/water_QE.tmp" || return 1
    qe_cleanup_register "$context_dir" || return 1
    QE_STRUCT_INPUT="$sandbox/water.cif"
    QE_STRUCT_SOURCE="$sandbox/water.cif"
    QE_STRUCT_DIR="$context_dir"
    QE_STRUCT_TMP="$context_dir/water_QE.tmp"
    QE_STRUCT_NAT=3
    QE_STRUCT_NTYP=2
    QE_STRUCT_TYPE_1=H
    QE_STRUCT_COUNT_1=2
    QE_STRUCT_TYPE_2=O
    QE_STRUCT_COUNT_2=1
    natm=3
    ntyp=2
    begcellpos=7
    endcellpos=9
    begatmpos=11
    endatmpos=13
    atmtype[1]=H
    Natmtype[1]=2
    atmtype[2]=O
    Natmtype[2]=1
    a_1=10.000000000
    a_2=10.000000000
    a_3=10.000000000
    k_1=3
    k_2=3
    k_3=3
}

assert_context_released() {
    local name path
    assert_unset QE_STRUCT_DIR || return 1
    assert_unset QE_STRUCT_TMP || return 1
    assert_unset QE_STRUCT_INPUT || return 1
    assert_unset natm || return 1
    assert_unset ntyp || return 1
    [ "${#QE_CLEANUP_PATHS[@]}" -eq 0 ] || {
        fail 'structure context cleanup registry is not empty'
        return 1
    }
    for name in QE_STRUCT_SOURCE QE_STRUCT_NAT QE_STRUCT_NTYP QE_STRUCT_TYPE_1 QE_STRUCT_COUNT_1 QE_STRUCT_TYPE_2 QE_STRUCT_COUNT_2; do
        assert_unset "$name" || return 1
    done
    for path in "$@"; do
        [ ! -e "$path" ] || {
            fail "unexpected leaked context path: $path"
            return 1
        }
    done
}

assert_nonzero() {
    [ "$1" -ne 0 ] || fail "${2:-expected nonzero status}"
}

init_pwin_test_state() {
    PRESET_RTASK=''
    NONINTERACTIVE_PWIN=''
    RETURN_TO_EXEC_CALC=0
    PWIN_LOCK_BANDS_KPATH=0
    PWIN_DEFAULT_KMESH_SCALE=''
    PWIN_DEFAULT_BANDS_NBND=''
}

assert_unset() {
    local name="$1"
    [ -z "${!name+x}" ] || fail "$name remained set"
}

# This is intentionally the first test: capture the pre-task MD output before
# structure preparation or staging changes are made.
test_md_baseline_output_is_stable() {
    local sandbox expected status
    sandbox="$(new_sandbox)" || return 1
    expected="$PROJECT_ROOT/tests/fixtures/expected/md/water.md.in"
    cp -- "$QE_TMP_FIXTURE" "$sandbox/water_QE.tmp" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        # The legacy generator probes the full periodic-table range and was
        # written before the test harness enabled nounset; capture its output
        # under the production shell semantics.
        set +u
        prefix='water'
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
        kpmesh='gamma'
        pseudolib='SSSP'
        md_time_ps='5'
        md_timestep_fs='0.25'
        md_fix_bottom='YES'
        md_use_atomic_velocities='YES'
        qe_md_pseudo_dir() { printf '%s\n' '/mock/SSSP'; }
        qe_md_pseudo_file() { printf '%s.UPF\n' "${atm[$1]}"; }
        default_cutoffs_from_pseudos() { printf '%s\n' '45 400'; }
        qe_estimate_nelec_from_current_pwin_context() { printf '%s\n' '10'; }
        qe_generate_md_input
    )
    status=$?
    assert_eq 0 "$status" 'baseline MD generation failed' || return 1
    [ -s "$sandbox/water.md.in" ] || { fail 'baseline MD output was not generated'; return 1; }
    assert_or_update_golden "$expected" "$sandbox/water.md.in" 'baseline MD output changed' || return 1
}

test_structure_context_populates_namespaced_and_legacy_globals() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        qe_prepare_structure_context "$fname1" || exit 1

        assert_eq 3 "$QE_STRUCT_NAT" 'namespaced atom count changed' || exit 1
        assert_eq 2 "$QE_STRUCT_NTYP" 'namespaced type count changed' || exit 1
        assert_eq H "$QE_STRUCT_TYPE_1" 'first namespaced element changed' || exit 1
        assert_eq 2 "$QE_STRUCT_COUNT_1" 'first namespaced element count changed' || exit 1
        assert_eq O "$QE_STRUCT_TYPE_2" 'second namespaced element changed' || exit 1
        assert_eq 1 "$QE_STRUCT_COUNT_2" 'second namespaced element count changed' || exit 1
        assert_eq 3 "$QE_STRUCT_K1" 'first namespaced K value changed' || exit 1
        assert_eq 3 "$QE_STRUCT_K2" 'second namespaced K value changed' || exit 1
        assert_eq 3 "$QE_STRUCT_K3" 'third namespaced K value changed' || exit 1
        case "$QE_STRUCT_DIR" in
            "$PWD"/.qbox-structure.*) ;;
            *) fail "structure directory escaped caller cwd: $QE_STRUCT_DIR"; exit 1 ;;
        esac
        case "$QE_STRUCT_TMP" in
            "$QE_STRUCT_DIR/water_QE.tmp") ;;
            *) fail "structure tmp is not inside context directory: $QE_STRUCT_TMP"; exit 1 ;;
        esac
        local registered=0 path
        for path in "${QE_CLEANUP_PATHS[@]}"; do
            [ "$path" = "$QE_STRUCT_DIR" ] && registered=1
        done
        assert_eq 1 "$registered" 'structure directory was not registered' || exit 1

        assert_eq 3 "$natm" 'legacy natm changed' || exit 1
        assert_eq 2 "$ntyp" 'legacy ntyp changed' || exit 1
        assert_eq 7 "$begcellpos" 'legacy cell start changed' || exit 1
        assert_eq 9 "$endcellpos" 'legacy cell end changed' || exit 1
        assert_eq 11 "$begatmpos" 'legacy atom start changed' || exit 1
        assert_eq 13 "$endatmpos" 'legacy atom end changed' || exit 1
        assert_eq H "${atmtype[1]}" 'legacy first element changed' || exit 1
        assert_eq 2 "${Natmtype[1]}" 'legacy first element count changed' || exit 1
        assert_eq O "${atmtype[2]}" 'legacy second element changed' || exit 1
        assert_eq 1 "${Natmtype[2]}" 'legacy second element count changed' || exit 1
        assert_eq 10.000000000 "$a_1" 'legacy first cell length changed' || exit 1
        assert_eq 10.000000000 "$a_2" 'legacy second cell length changed' || exit 1
        assert_eq 10.000000000 "$a_3" 'legacy third cell length changed' || exit 1
        assert_eq 3 "$k_1" 'legacy first K value changed' || exit 1
        assert_eq 3 "$k_2" 'legacy second K value changed' || exit 1
        assert_eq 3 "$k_3" 'legacy third K value changed' || exit 1
        qe_release_structure_context || exit 1
    )
}

test_structure_context_reset_preserves_unrelated_state() {
    local sentinel
    sentinel="$(new_sandbox)" || return 1
    (
        source_qbox
        QE_STRUCT_TEST_SENTINEL='context'
        natm=7
        ntyp=8
        begcellpos=9
        endcellpos=10
        begatmpos=11
        endatmpos=12
        atmtype[1]='legacy'
        Natmtype[1]=99
        a_1='legacy-a'
        a_2='legacy-b'
        a_3='legacy-c'
        k_1='legacy-k1'
        k_2='legacy-k2'
        k_3='legacy-k3'
        lsda='magnetic-state'
        magarr[1]='magnetic-array'
        atm[1]='H'
        atmmass[1]='1.008'
        SSSPlib[1]='H.UPF'
        qe_structure_context_reset
        assert_unset QE_STRUCT_TEST_SENTINEL || exit 1
        assert_unset natm || exit 1
        assert_unset ntyp || exit 1
        assert_unset begcellpos || exit 1
        assert_unset endcellpos || exit 1
        assert_unset begatmpos || exit 1
        assert_unset endatmpos || exit 1
        assert_unset atmtype || exit 1
        assert_unset Natmtype || exit 1
        assert_unset a_1 || exit 1
        assert_unset a_2 || exit 1
        assert_unset a_3 || exit 1
        assert_unset k_1 || exit 1
        assert_unset k_2 || exit 1
        assert_unset k_3 || exit 1
        assert_eq magnetic-state "$lsda" 'reset changed lsda' || exit 1
        assert_eq magnetic-array "${magarr[1]}" 'reset changed magarr' || exit 1
        assert_eq H "${atm[1]}" 'reset changed atm lookup' || exit 1
        assert_eq 1.008 "${atmmass[1]}" 'reset changed atmmass lookup' || exit 1
        assert_eq H.UPF "${SSSPlib[1]}" 'reset changed pseudopotential lookup' || exit 1
    )
}

test_structure_context_uses_short_local_names_under_deep_paths() {
    local sandbox deep component long_prefix input context_dir old_cwd log
    sandbox="$(new_sandbox)" || return 1
    printf -v component '%080d' 0
    printf -v long_prefix 'molecule_%0150d' 0
    deep="$sandbox/$component/$component/$component"
    mkdir -p "$deep" || return 1
    input="$deep/$long_prefix.CIF"
    cp -- "$STRUCTURE_FIXTURE" "$input" || return 1
    printf '%s\n' 'user-owned output' >"$deep/${long_prefix}_QE.tmp"
    (
        cd "$deep" || exit 1
        source_qbox
        export QBOX_MOCK_QE_TMP="$QE_TMP_FIXTURE"
        export QBOX_MOCK_MULTIWFN_PATH_LIMIT=200
        export QBOX_MOCK_MULTIWFN_CALL="$sandbox/multiwfn-call"
        PATH="$MOCK_MULTIWFN_DIR:$PATH"
        unset QBOX_MULTIWFN_HOME
        old_cwd="$PWD"
        qe_prepare_structure_context "$input" || exit 1
        context_dir="$QE_STRUCT_DIR"
        assert_eq "$old_cwd" "$PWD" 'structure preparation changed caller cwd' || exit 1
        assert_eq "$input" "$QE_STRUCT_INPUT" 'source path contract changed' || exit 1
        assert_eq "$context_dir/${long_prefix}_QE.tmp" "$QE_STRUCT_TMP" 'public scratch filename changed' || exit 1
        assert_eq 3 "$QE_STRUCT_NAT" 'deep-path atom count changed' || exit 1
        assert_file_equals "$STRUCTURE_FIXTURE" "$input" 'original CIF was modified' || exit 1
        assert_eq 'user-owned output' "$(cat "$deep/${long_prefix}_QE.tmp")" 'caller output was modified' || exit 1
        mapfile -t call <"$QBOX_MOCK_MULTIWFN_CALL"
        [[ "${call[0]}" != */* && "${call[0]}" == *.CIF && ${#call[0]} -lt 200 ]] || { fail 'Multiwfn input did not use a short relative name with preserved extension'; exit 1; }
        [[ "${call[1]}" != */* && ${#call[1]} -lt 200 ]] || { fail 'Multiwfn output did not use a short relative name'; exit 1; }
        assert_eq "$context_dir" "${call[2]}" 'Multiwfn ran outside the private context' || exit 1
        qe_release_structure_context || exit 1
        assert_context_released "$context_dir" || exit 1
        assert_eq 2 "$(find "$deep" -mindepth 1 -maxdepth 1 | wc -l)" 'structure scratch leaked into caller directory' || exit 1
    )
}

test_structure_context_missing_output_reports_multiwfn_diagnostic() {
    local sandbox status log
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        unset QBOX_MULTIWFN_HOME
        Multiwfn() { cat >/dev/null; echo 'Multiwfn diagnostic: export unavailable'; return 0; }
        qe_prepare_structure_context "$fname1" >"$sandbox/prepare.log" 2>&1
        status=$?
        log="$(cat "$sandbox/prepare.log")"
        assert_nonzero "$status" 'zero exit without output incorrectly succeeded' || exit 1
        assert_contains "$log" 'Multiwfn 未生成有效的 QE 结构文件' 'missing output has no clear error' || exit 1
        assert_contains "$log" 'export unavailable' 'Multiwfn diagnostic was swallowed' || exit 1
        assert_not_contains "$log" 'awk:' 'missing output leaked a raw awk error' || exit 1
        assert_context_released "$sandbox/water_QE.tmp" || exit 1
        assert_eq 0 "$(find "$sandbox" -maxdepth 1 -name '.qbox-structure.*' | wc -l)" 'missing output leaked a private context' || exit 1
    )
}

test_structure_context_survives_output_only_path_truncation() {
    local sandbox input long_prefix pad_length
    sandbox="$(new_sandbox)" || return 1
    # The source fits Multiwfn's buffer, while the old absolute output path
    # grows past it once the private context directory is inserted.
    pad_length=$((188 - ${#sandbox} - 5 - 9))
    printf -v long_prefix 'molecule_%0*d' "$pad_length" 0
    input="$sandbox/$long_prefix.cif"
    [ "${#input}" -eq 188 ] || return 1
    cp -- "$STRUCTURE_FIXTURE" "$input" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        export QBOX_MOCK_QE_TMP="$QE_TMP_FIXTURE"
        export QBOX_MOCK_MULTIWFN_PATH_LIMIT=200
        PATH="$MOCK_MULTIWFN_DIR:$PATH"
        unset QBOX_MULTIWFN_HOME
        qe_prepare_structure_context "$input" || exit 1
        [ "${#QE_STRUCT_TMP}" -gt 200 ] || { fail 'output-only truncation fixture is too short'; exit 1; }
        assert_eq 3 "$QE_STRUCT_NAT" 'output-path truncation prevented parsing' || exit 1
        qe_release_structure_context || exit 1
    )
}

test_structure_context_retains_nonzero_multiwfn_diagnostic() {
    local sandbox status log
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        unset QBOX_MULTIWFN_HOME
        Multiwfn() { cat >/dev/null; echo 'Multiwfn diagnostic: bad structure' >&2; return 29; }
        qe_prepare_structure_context "$fname1" >"$sandbox/prepare.log" 2>&1
        status=$?
        log="$(cat "$sandbox/prepare.log")"
        assert_eq 29 "$status" 'Multiwfn failure status was masked' || exit 1
        assert_contains "$log" 'bad structure' 'nonzero Multiwfn diagnostic was swallowed' || exit 1
        assert_context_released "$sandbox/water_QE.tmp" || exit 1
    )
}

test_structure_context_resolves_relative_multiwfn_location_before_chdir() {
    local sandbox mode
    sandbox="$(new_sandbox)" || return 1
    for mode in home path; do
        (
            cd "$sandbox" || exit 1
            source_qbox
            prepare_structure_sandbox "$sandbox" || exit 1
            mkdir -p 'relative tools'
            cp -- "$MOCK_MULTIWFN_DIR/Multiwfn" 'relative tools/Multiwfn' || exit 1
            export QBOX_MOCK_MULTIWFN_CALL="$sandbox/multiwfn-call"
            if [ "$mode" = home ]; then
                QBOX_MULTIWFN_HOME='relative tools'
            else
                unset QBOX_MULTIWFN_HOME
                PATH="relative tools:$PATH"
            fi
            qe_prepare_structure_context "$fname1" || exit 1
            mapfile -t call <"$QBOX_MOCK_MULTIWFN_CALL"
            assert_eq "$QE_STRUCT_DIR" "${call[2]}" "$mode tool did not run in context" || exit 1
            assert_eq 3 "$QE_STRUCT_NAT" "$mode relative Multiwfn was not resolved" || exit 1
            qe_release_structure_context || exit 1
        ) || return 1
    done
}

test_structure_context_accepts_legacy_shim_inside_private_directory() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        unset QBOX_MULTIWFN_HOME
        Multiwfn() { cat >/dev/null; cp -- "$QE_TMP_FIXTURE" "${prefix}_QE.tmp"; }
        qe_prepare_structure_context "$fname1" || exit 1
        [ ! -e "$sandbox/water_QE.tmp" ] || { fail 'legacy shim wrote into caller cwd'; exit 1; }
        assert_eq 3 "$QE_STRUCT_NAT" 'legacy shim result was not parsed' || exit 1
        qe_release_structure_context || exit 1
    )
}

test_structure_context_release_removes_only_registered_context() {
    local sandbox sibling
    sandbox="$(new_sandbox)" || return 1
    sibling="$sandbox/.qbox-structure-user"
    mkdir -p "$sibling"
    printf '%s\n' 'keep me' >"$sibling/sentinel"
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        qe_prepare_structure_context "$fname1" || exit 1
        local context_dir="$QE_STRUCT_DIR"
        qe_release_structure_context || exit 1
        [ ! -e "$context_dir" ] || { fail 'released context directory remains'; exit 1; }
        [ -f "$sibling/sentinel" ] || { fail 'release removed sibling sentinel'; exit 1; }
        assert_eq 'keep me' "$(cat "$sibling/sentinel")" 'release changed sibling sentinel' || exit 1
        assert_unset QE_STRUCT_DIR || exit 1
        assert_unset QE_STRUCT_TMP || exit 1
        [ "${#QE_CLEANUP_PATHS[@]}" -eq 0 ] || { fail 'release left context registered'; exit 1; }
    )
}

test_prepare_empty_input_releases_existing_context_first() {
    local sandbox context_dir status
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        install_existing_structure_context "$sandbox" || exit 1
        context_dir="$QE_STRUCT_DIR"
        qe_prepare_structure_context ''
        status=$?
        assert_nonzero "$status" 'empty structure input unexpectedly succeeded' || exit 1
        [ ! -e "$context_dir" ] || { fail 'old context survived empty-input release'; exit 1; }
        assert_context_released || exit 1
    )
}

test_prepare_failure_paths_leave_no_context_or_legacy_tmp() {
    local sandbox status legacy_tmp malformed_tmp
    sandbox="$(new_sandbox)" || return 1

    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        legacy_tmp="$sandbox/water_QE.tmp"
        rm -f -- "$legacy_tmp"
        Multiwfn() { return 29; }
        qe_prepare_structure_context "$fname1"
        status=$?
        assert_nonzero "$status" 'nonzero Multiwfn unexpectedly succeeded' || exit 1
        assert_context_released "$legacy_tmp" || exit 1
    ) || return 1

    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        malformed_tmp="$sandbox/malformed.tmp"
        printf '%s\n' ' &SYSTEM' '   nat= 3,' '   ntyp= 2,' ' /' >"$malformed_tmp"
        export QBOX_MOCK_QE_TMP="$malformed_tmp"
        legacy_tmp="$sandbox/water_QE.tmp"
        rm -f -- "$legacy_tmp"
        qe_prepare_structure_context "$fname1"
        status=$?
        assert_nonzero "$status" 'malformed QE output unexpectedly succeeded' || exit 1
        assert_context_released "$legacy_tmp" || exit 1
    ) || return 1

    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        fname1="$sandbox/water.vasp"
        printf '%s\n' 'POSCAR' >"$fname1"
        qe_auto_convert_vasp_to_cif() { return 31; }
        qe_prepare_structure_context "$fname1"
        status=$?
        assert_nonzero "$status" 'VASP conversion failure unexpectedly succeeded' || exit 1
        assert_context_released "$sandbox/water_QE.tmp" || exit 1
    )
}

test_context_release_failure_preserves_handle_for_retry() {
    local sandbox context_dir status
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        qe_prepare_structure_context "$fname1" || exit 1
        context_dir="$QE_STRUCT_DIR"
        rm() {
            if [ "$1" = '-rf' ] && [ "$3" = "$context_dir" ]; then
                return 41
            fi
            command rm "$@"
        }
        qe_release_structure_context
        status=$?
        assert_eq 41 "$status" 'context rm failure status changed' || exit 1
        [ -d "$context_dir" ] || { fail 'context rm failure removed directory'; exit 1; }
        [ "$QE_STRUCT_DIR" = "$context_dir" ] || { fail 'context handle was lost after rm failure'; exit 1; }
        [ "$QE_STRUCT_TMP" = "$context_dir/water_QE.tmp" ] || { fail 'context tmp handle was lost after rm failure'; exit 1; }
        assert_eq 3 "$QE_STRUCT_NAT" 'context atom count was lost after rm failure' || exit 1
        assert_eq 3 "$natm" 'legacy atom count was lost after rm failure' || exit 1
        assert_eq 10.000000000 "$a_1" 'legacy cell length was lost after rm failure' || exit 1
        local registered=0 path
        assert_eq 1 "${#QE_CLEANUP_PATHS[@]}" 'context registry gained unexpected entries' || exit 1
        for path in "${QE_CLEANUP_PATHS[@]}"; do
            [ "$path" = "$context_dir" ] && registered=1
        done
        assert_eq 1 "$registered" 'context registration was lost after rm failure' || exit 1
        unset -f rm
        qe_release_structure_context || exit 1
        [ ! -e "$context_dir" ] || { fail 'context retry did not remove directory'; exit 1; }
        assert_context_released || exit 1
    )
}

test_staging_cleanup_failure_preserves_registered_stage() {
    local sandbox status stage_path registered path
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        qe_prepare_structure_context "$fname1" || exit 1
        stage_success_generator() { printf '%s\n' 'staged output' >water.md.in; }
        rm() {
            case "$3" in
                "$PWD"/.qbox-md.*) return 43 ;;
            esac
            command rm "$@"
        }
        qe_generate_in_staging md water.md.in stage_success_generator
        status=$?
        assert_eq 43 "$status" 'staging rm failure status changed' || exit 1
        [ -s water.md.in ] || { fail 'staging output was lost before cleanup failure'; exit 1; }
        assert_eq 2 "${#QE_CLEANUP_PATHS[@]}" 'staging failure changed unrelated registrations' || exit 1
        registered=0
        for path in "${QE_CLEANUP_PATHS[@]}"; do
            case "$path" in
                "$PWD"/.qbox-md.*)
                    registered=1
                    stage_path="$path"
                    ;;
            esac
        done
        assert_eq 1 "$registered" 'staging handle was lost after rm failure' || exit 1
        [ -d "$stage_path" ] || { fail 'staging directory vanished despite rm failure'; exit 1; }
        unset -f rm
        qe_cleanup_all || exit 1
        [ ! -e "$stage_path" ] || { fail 'cleanup_all did not remove failed stage'; exit 1; }
        qe_release_structure_context || exit 1
    )
}

test_context_parser_preserves_nontrivial_lengths_and_k_rounding() {
    local sandbox custom_tmp status
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        custom_tmp="$sandbox/nontrivial_QE.tmp"
        printf '%s\n' \
            ' &SYSTEM' \
            '   ibrav= 0,' \
            '   nat= 3,' \
            '   ntyp= 2,' \
            ' /' \
            ' CELL_PARAMETERS angstrom' \
            '   7.200000000 9.600000000 0.000000000' \
            '   9.000000000 0.000000000 12.000000000' \
            '   20.000000000 0.000000000 21.000000000' \
            ' ATOMIC_POSITIONS angstrom' \
            '   O 5.000000000 5.000000000 5.000000000' \
            '   H 5.570000000 5.000000000 5.000000000' \
            '   H 4.810000000 5.540000000 5.000000000' >"$custom_tmp"
        export QBOX_MOCK_QE_TMP="$custom_tmp"
        qe_prepare_structure_context "$fname1" || exit 1
        assert_eq 12.000000000 "$QE_STRUCT_A_1" 'first nontrivial vector length changed' || exit 1
        assert_eq 15.000000000 "$QE_STRUCT_A_2" 'second nontrivial vector length changed' || exit 1
        assert_eq 29.000000000 "$QE_STRUCT_A_3" 'third nontrivial vector length changed' || exit 1
        assert_eq 3 "$QE_STRUCT_K1" 'half-boundary K rounding changed' || exit 1
        assert_eq 2 "$QE_STRUCT_K2" 'second K rounding changed' || exit 1
        assert_eq 1 "$QE_STRUCT_K3" 'third K rounding changed' || exit 1
        assert_eq "$QE_STRUCT_A_1" "$a_1" 'first namespaced/legacy length diverged' || exit 1
        assert_eq "$QE_STRUCT_A_2" "$a_2" 'second namespaced/legacy length diverged' || exit 1
        assert_eq "$QE_STRUCT_A_3" "$a_3" 'third namespaced/legacy length diverged' || exit 1
        assert_eq "$QE_STRUCT_K1" "$k_1" 'first namespaced/legacy K diverged' || exit 1
        assert_eq "$QE_STRUCT_K2" "$k_2" 'second namespaced/legacy K diverged' || exit 1
        assert_eq "$QE_STRUCT_K3" "$k_3" 'third namespaced/legacy K diverged' || exit 1
        qe_release_structure_context || exit 1
    )
}

test_pwin_uses_shared_structure_preparation() {
    local sandbox marker
    sandbox="$(new_sandbox)" || return 1
    marker="$sandbox/pwin-context-called"
    printf '%s\n' 'data_water' >"$sandbox/water.cif"
    (
        cd "$sandbox" || exit 1
        source_qbox
        fname1="$sandbox/water.cif"
        prefix='water'
        qe_prepare_structure_context() { : >"$marker"; return 37; }
        pwin >/dev/null 2>&1
    )
    [ -e "$marker" ] || { fail 'pwin bypassed shared structure preparation'; return 1; }
}

test_mdin_uses_shared_structure_preparation() {
    local sandbox marker
    sandbox="$(new_sandbox)" || return 1
    marker="$sandbox/mdin-context-called"
    printf '%s\n' 'data_water' >"$sandbox/water.cif"
    (
        cd "$sandbox" || exit 1
        source_qbox
        fname1="$sandbox/water.cif"
        prefix='water'
        qe_prepare_structure_context() { : >"$marker"; return 37; }
        mdin >/dev/null 2>&1
    )
    [ -e "$marker" ] || { fail 'mdin bypassed shared structure preparation'; return 1; }
}

test_staging_failure_rolls_back_target_and_cleans_stage() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        qe_prepare_structure_context "$fname1" || exit 1
        printf '%s\n' 'original target' >water.md.in
        mkdir .qbox-sibling
        printf '%s\n' 'keep sibling' >.qbox-sibling/sentinel
        failing_generator() { printf '%s\n' 'partial output' >water.md.in; return 23; }
        qe_generate_in_staging md water.md.in failing_generator
        local status=$?
        assert_eq 23 "$status" 'staging failure status changed' || exit 1
        assert_eq 'original target' "$(cat water.md.in)" 'failed staging replaced target' || exit 1
        assert_eq 'keep sibling' "$(cat .qbox-sibling/sentinel)" 'failed staging changed sibling' || exit 1
        [ -z "$(find . -maxdepth 1 -type d -name '.qbox-md.*' -print -quit)" ] || {
            fail 'failed staging leaked its directory'
            exit 1
        }
        qe_release_structure_context || exit 1
    )
}

test_staging_success_preserves_mode_and_links_context() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        qe_prepare_structure_context "$fname1" || exit 1
        printf '%s\n' 'original target' >water.md.in
        chmod 640 water.md.in
        stage_probe_generator() {
            [ -L water_QE.tmp ] || return 11
            [ -L water.cif ] || return 12
            printf '%s\n' 'replacement target' >water.md.in
        }
        qe_generate_in_staging md water.md.in stage_probe_generator || exit 1
        assert_eq 'replacement target' "$(cat water.md.in)" 'successful staging did not replace target' || exit 1
        assert_eq 640 "$(stat -c '%a' water.md.in)" 'successful staging changed target mode' || exit 1
        [ -z "$(find . -maxdepth 1 -type d -name '.qbox-md.*' -print -quit)" ] || {
            fail 'successful staging leaked its directory'
            exit 1
        }
        qe_release_structure_context || exit 1
    )
}

test_pwin_releases_context_on_post_prepare_eof() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        install_existing_structure_context "$sandbox" || exit 1
        qe_prepare_structure_context() { :; }
        init_pwin_test_state
        pwin >/dev/null 2>&1 <<< '1'
        local status=$?
        assert_nonzero "$status" 'pwin EOF unexpectedly succeeded' || exit 1
        assert_context_released "$sandbox/.qbox-structure-existing" || exit 1
    )
}

test_pwin_releases_existing_context_on_initial_input_eof() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        install_existing_structure_context "$sandbox" || exit 1
        fname1=''
        init_pwin_test_state
        pwin >/dev/null 2>&1 </dev/null
        local status=$?
        assert_nonzero "$status" 'pwin initial EOF unexpectedly succeeded' || exit 1
        assert_context_released "$sandbox/.qbox-structure-existing" || exit 1
    )
}

test_pwin_releases_context_when_task_selection_errors() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        install_existing_structure_context "$sandbox" || exit 1
        qe_prepare_structure_context() { :; }
        qe_pwin_select_task() { return 53; }
        init_pwin_test_state
        pwin >/dev/null 2>&1
        local status=$?
        assert_eq 1 "$status" 'pwin task-selection error status changed' || exit 1
        assert_context_released "$sandbox/.qbox-structure-existing" || exit 1
    )
}

test_pwin_releases_context_on_generation_error() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        install_existing_structure_context "$sandbox" || exit 1
        qe_prepare_structure_context() { :; }
        qe_generate_pw_input() { return 59; }
        PRESET_RTASK='energy'
        NONINTERACTIVE_PWIN=1
        RETURN_TO_EXEC_CALC=0
        PWIN_LOCK_BANDS_KPATH=0
        PWIN_DEFAULT_KMESH_SCALE=''
        PWIN_DEFAULT_BANDS_NBND=''
        pwin >/dev/null 2>&1
        local status=$?
        assert_eq 59 "$status" 'pwin generation error status changed' || exit 1
        assert_context_released "$sandbox/.qbox-structure-existing" || exit 1
    )
}

test_pwin_propagates_release_failure_after_success() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        install_existing_structure_context "$sandbox" || exit 1
        qe_prepare_structure_context() { :; }
        qe_generate_pw_input() { return 0; }
        context_dir="$QE_STRUCT_DIR"
        rm() {
            if [ "$1" = '-rf' ] && [ "$3" = "$context_dir" ]; then
                return 61
            fi
            command rm "$@"
        }
        PRESET_RTASK='energy'
        NONINTERACTIVE_PWIN=1
        RETURN_TO_EXEC_CALC=0
        PWIN_LOCK_BANDS_KPATH=0
        PWIN_DEFAULT_KMESH_SCALE=''
        PWIN_DEFAULT_BANDS_NBND=''
        pwin >/dev/null 2>&1
        local status=$?
        assert_eq 61 "$status" 'pwin release failure was masked' || exit 1
        [ "$QE_STRUCT_DIR" = "$context_dir" ] || { fail 'pwin lost context after release failure'; exit 1; }
        unset -f rm
        qe_release_structure_context || exit 1
    )
}

run_pwin_submenu_eof_probe() {
    local sandbox="$1" option="$2" state_file="$3" menu_marker="$4"
    timeout 2 bash -c '
        root=$1
        sandbox=$2
        option=$3
        state_file=$4
        menu_marker=$5
        context_dir="$sandbox/.qbox-structure-existing"
        QBOX_TEST_MODE=1 source "$root/qbox"
        printf "%s\n" "data_water" >"$sandbox/water.cif"
        mkdir -p "$context_dir" || exit 1
        cp -- "$root/tests/fixtures/qe-inputs/water_QE.tmp" "$context_dir/water_QE.tmp" || exit 1
        qe_cleanup_register "$context_dir" || exit 1
        fname1="$sandbox/water.cif"
        prefix=water
        QE_STRUCT_INPUT="$sandbox/water.cif"
        QE_STRUCT_SOURCE="$sandbox/water.cif"
        QE_STRUCT_DIR="$context_dir"
        QE_STRUCT_TMP="$context_dir/water_QE.tmp"
        QE_STRUCT_NAT=3
        QE_STRUCT_NTYP=2
        k_1=3
        k_2=3
        k_3=3
        PRESET_RTASK=""
        NONINTERACTIVE_PWIN=""
        RETURN_TO_EXEC_CALC=0
        PWIN_LOCK_BANDS_KPATH=0
        PWIN_DEFAULT_KMESH_SCALE=""
        PWIN_DEFAULT_BANDS_NBND=""
        QE_RETURN_TO_MAIN=0
        qe_prepare_structure_context() { :; }
        qe_pwin_menu() { :; }
        qe_request_main_menu() { : >"$menu_marker"; }
        pwin >/dev/null 2>&1
        status=$?
        {
            printf "status=%s\n" "$status"
            if [ -n "${QE_STRUCT_DIR+x}" ]; then
                printf "dir=%s\n" "$QE_STRUCT_DIR"
            else
                printf "dir=unset\n"
            fi
            if [ -n "${QE_STRUCT_TMP+x}" ]; then
                printf "tmp=%s\n" "$QE_STRUCT_TMP"
            else
                printf "tmp=unset\n"
            fi
            printf "registry=%s\n" "${#QE_CLEANUP_PATHS[@]}"
        } >"$state_file"
        exit "$status"
    ' _ "$PROJECT_ROOT" "$sandbox" "$option" "$state_file" "$menu_marker" <<EOF
1
$option
EOF
}

assert_pwin_submenu_eof_cleanup() {
    local sandbox="$1" option="$2" state_file="$3" menu_marker="$4"
    local status state
    run_pwin_submenu_eof_probe "$sandbox" "$option" "$state_file" "$menu_marker"
    status=$?
    assert_nonzero "$status" "pwin option $option EOF unexpectedly succeeded" || return 1
    [ "$status" -ne 124 ] || {
        fail "pwin option $option helper still loops on EOF (status 124)"
        return 1
    }
    [ -f "$state_file" ] || {
        fail "pwin option $option did not return state after EOF"
        return 1
    }
    state="$(cat "$state_file")"
    assert_contains "$state" 'status=1' "pwin option $option did not return helper failure" || return 1
    assert_contains "$state" 'dir=unset' "pwin option $option retained QE_STRUCT_DIR" || return 1
    assert_contains "$state" 'tmp=unset' "pwin option $option retained QE_STRUCT_TMP" || return 1
    assert_contains "$state" 'registry=0' "pwin option $option retained cleanup registration" || return 1
    [ ! -e "$sandbox/.qbox-structure-existing" ] || {
        fail "pwin option $option leaked context directory"
        return 1
    }
    [ ! -e "$menu_marker" ] || {
        fail "pwin option $option requested the main menu after EOF"
        return 1
    }
}

test_pwin_cutoff_menu_eof_releases_context() {
    local sandbox state_file menu_marker
    sandbox="$(new_sandbox)" || return 1
    state_file="$sandbox/cutoff-state"
    menu_marker="$sandbox/cutoff-main-menu"
    assert_pwin_submenu_eof_cleanup "$sandbox" 11 "$state_file" "$menu_marker"
}

test_pwin_advanced_menu_eof_releases_context() {
    local sandbox state_file menu_marker
    sandbox="$(new_sandbox)" || return 1
    state_file="$sandbox/advanced-state"
    menu_marker="$sandbox/advanced-main-menu"
    assert_pwin_submenu_eof_cleanup "$sandbox" 12 "$state_file" "$menu_marker"
}

test_mdin_releases_context_on_eof_and_return() {
    local sandbox status
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        install_existing_structure_context "$sandbox" || exit 1
        qe_prepare_structure_context() { :; }
        mdin >/dev/null 2>&1 </dev/null
        status=$?
        assert_nonzero "$status" 'mdin EOF unexpectedly succeeded' || exit 1
        assert_context_released "$sandbox/.qbox-structure-existing" || exit 1
    ) || return 1

    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        install_existing_structure_context "$sandbox" || exit 1
        qe_prepare_structure_context() { :; }
        mdin >/dev/null 2>&1 <<< '7'
        status=$?
        assert_eq 0 "$status" 'mdin return option status changed' || exit 1
        assert_context_released "$sandbox/.qbox-structure-existing" || exit 1
    )
}

test_mdin_releases_existing_context_on_initial_input_eof() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        install_existing_structure_context "$sandbox" || exit 1
        fname1=''
        mdin >/dev/null 2>&1 </dev/null
        local status=$?
        assert_nonzero "$status" 'mdin initial EOF unexpectedly succeeded' || exit 1
        assert_context_released "$sandbox/.qbox-structure-existing" || exit 1
    )
}

test_mdin_releases_context_on_generation_error() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        install_existing_structure_context "$sandbox" || exit 1
        qe_prepare_structure_context() { :; }
        qe_generate_md_input() { return 67; }
        mdin >/dev/null 2>&1 <<< '0'
        local status=$?
        assert_eq 67 "$status" 'mdin generation error status changed' || exit 1
        assert_context_released "$sandbox/.qbox-structure-existing" || exit 1
    )
}

test_mdin_propagates_release_failure_after_success() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        source_qbox
        prepare_structure_sandbox "$sandbox" || exit 1
        install_existing_structure_context "$sandbox" || exit 1
        qe_prepare_structure_context() { :; }
        qe_generate_md_input() { return 0; }
        context_dir="$QE_STRUCT_DIR"
        rm() {
            if [ "$1" = '-rf' ] && [ "$3" = "$context_dir" ]; then
                return 71
            fi
            command rm "$@"
        }
        mdin >/dev/null 2>&1 <<< '0'
        local status=$?
        assert_eq 71 "$status" 'mdin release failure was masked' || exit 1
        [ "$QE_STRUCT_DIR" = "$context_dir" ] || { fail 'mdin lost context after release failure'; exit 1; }
        unset -f rm
        qe_release_structure_context || exit 1
    )
}

test_postprocess_pw_context_is_file_scoped() {
    local sandbox context
    sandbox="$(new_sandbox)" || return 1
    context="$sandbox/pw-context.txt"
    QE_STRUCT_DIR='active-structure-context'
    QE_STRUCT_TMP='active-structure-file'
    natm='existing-atom-count'
    begatmpos='existing-position-line'

    qbox_parse_pw_input "$TESTS_DIR/fixtures/expected/pw/water.relax.in" "$context" || return 1
    [ -s "$context" ] || { fail 'explicit PW context was not written'; return 1; }
    assert_eq 'active-structure-context' "$QE_STRUCT_DIR" 'PW parser replaced the active structure context' || return 1
    assert_eq 'active-structure-file' "$QE_STRUCT_TMP" 'PW parser replaced the active structure file' || return 1
    assert_eq 'existing-atom-count' "$natm" 'PW parser leaked atom count into menu globals' || return 1
    assert_eq 'existing-position-line' "$begatmpos" 'PW parser leaked line offsets into menu globals'
}

run_test 'baseline MD output remains exact' test_md_baseline_output_is_stable
run_test 'structure context populates namespaced and legacy globals' test_structure_context_populates_namespaced_and_legacy_globals
run_test 'structure context survives Multiwfn path limit in deep directories' test_structure_context_uses_short_local_names_under_deep_paths
run_test 'structure context survives output-only Multiwfn path truncation' test_structure_context_survives_output_only_path_truncation
run_test 'structure context reports missing Multiwfn output clearly' test_structure_context_missing_output_reports_multiwfn_diagnostic
run_test 'structure context retains Multiwfn failure diagnostics' test_structure_context_retains_nonzero_multiwfn_diagnostic
run_test 'structure context resolves relative Multiwfn locations' test_structure_context_resolves_relative_multiwfn_location_before_chdir
run_test 'structure context keeps legacy shims inside its private directory' test_structure_context_accepts_legacy_shim_inside_private_directory
run_test 'structure reset preserves unrelated state' test_structure_context_reset_preserves_unrelated_state
run_test 'structure release removes only registered context' test_structure_context_release_removes_only_registered_context
run_test 'pwin uses shared structure preparation' test_pwin_uses_shared_structure_preparation
run_test 'mdin uses shared structure preparation' test_mdin_uses_shared_structure_preparation
run_test 'staging failure rolls back target and cleans stage' test_staging_failure_rolls_back_target_and_cleans_stage
run_test 'staging success preserves mode and links context' test_staging_success_preserves_mode_and_links_context
run_test 'empty input releases existing context first' test_prepare_empty_input_releases_existing_context_first
run_test 'preparation failures leave no context or legacy tmp' test_prepare_failure_paths_leave_no_context_or_legacy_tmp
run_test 'context release failure preserves handle for retry' test_context_release_failure_preserves_handle_for_retry
run_test 'staging cleanup failure preserves registered stage' test_staging_cleanup_failure_preserves_registered_stage
run_test 'context parser preserves nontrivial K rounding' test_context_parser_preserves_nontrivial_lengths_and_k_rounding
run_test 'pwin releases context on post-prepare EOF' test_pwin_releases_context_on_post_prepare_eof
run_test 'pwin releases existing context on initial input EOF' test_pwin_releases_existing_context_on_initial_input_eof
run_test 'pwin releases context on task-selection error' test_pwin_releases_context_when_task_selection_errors
run_test 'pwin releases context on generation error' test_pwin_releases_context_on_generation_error
run_test 'pwin propagates release failure after success' test_pwin_propagates_release_failure_after_success
run_test 'pwin cutoff menu EOF releases context' test_pwin_cutoff_menu_eof_releases_context
run_test 'pwin advanced menu EOF releases context' test_pwin_advanced_menu_eof_releases_context
run_test 'mdin releases context on EOF and return' test_mdin_releases_context_on_eof_and_return
run_test 'mdin releases existing context on initial input EOF' test_mdin_releases_existing_context_on_initial_input_eof
run_test 'mdin releases context on generation error' test_mdin_releases_context_on_generation_error
run_test 'mdin propagates release failure after success' test_mdin_propagates_release_failure_after_success
run_test 'post-processing PW context remains file scoped' test_postprocess_pw_context_is_file_scoped
finish_tests
