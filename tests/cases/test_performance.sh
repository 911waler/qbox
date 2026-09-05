#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"

# Capture canonical executables before a test prepends counting wrappers to
# PATH.  The wrappers must never resolve their own command name through PATH.
REAL_AWK="$(readlink -f -- "$(command -v awk)")"
REAL_SED="$(readlink -f -- "$(command -v sed)")"
REAL_SORT="$(readlink -f -- "$(command -v sort)")"
REAL_BC="$(command -v bc 2>/dev/null || true)"
[ -z "$REAL_BC" ] || REAL_BC="$(readlink -f -- "$REAL_BC")"

source_qbox

STRUCTURE_FIXTURE="$PROJECT_ROOT/tests/fixtures/structures/water.cif"
QE_TMP_FIXTURE="$PROJECT_ROOT/tests/fixtures/qe-inputs/water_QE.tmp"
MOCK_MULTIWFN_DIR="$PROJECT_ROOT/tests/mocks"

install_process_wrappers() {
    local wrapper_dir="$1" tool real
    mkdir -p "$wrapper_dir" || return 1
    for tool in awk sed sort bc; do
        case "$tool" in
            awk) real="$REAL_AWK" ;;
            sed) real="$REAL_SED" ;;
            sort) real="$REAL_SORT" ;;
            bc) real="$REAL_BC" ;;
        esac
        [ -n "$real" ] || continue
        {
            printf '%s\n' '#!/usr/bin/env bash'
            printf 'printf '\''%%s'\'' %q >> "$QBOX_PROCESS_LOG"\n' "$tool"
            printf 'printf '\'' <%%s>'\'' "$@" >> "$QBOX_PROCESS_LOG"\n'
            printf 'printf '\''\\n'\'' >> "$QBOX_PROCESS_LOG"\n'
            printf 'exec %q "$@"\n' "$real"
        } > "$wrapper_dir/$tool" || return 1
        chmod +x "$wrapper_dir/$tool" || return 1
    done
}

invocation_count() {
    local wanted="$1" line count=0
    [ -f "$QBOX_PROCESS_LOG" ] || { printf '0\n'; return; }
    while IFS= read -r line; do
        [ "${line%% *}" = "$wanted" ] && count=$((count + 1))
    done < "$QBOX_PROCESS_LOG"
    printf '%s\n' "$count"
}

count_lines_containing() {
    local wanted="$1" line count=0
    [ -f "$QBOX_PROCESS_LOG" ] || { printf '0\n'; return; }
    while IFS= read -r line; do
        case "$line" in *"$wanted"*) count=$((count + 1));; esac
    done < "$QBOX_PROCESS_LOG"
    printf '%s\n' "$count"
}

prepare_counted_context() {
    local sandbox="$1" wrappers="$2"
    cp -- "$STRUCTURE_FIXTURE" "$sandbox/water.cif" || return 1
    cp -- "$QE_TMP_FIXTURE" "$sandbox/water_QE.tmp" || return 1
    export QBOX_MOCK_QE_TMP="$QE_TMP_FIXTURE"
    export QBOX_PROCESS_LOG="$sandbox/process.log"
    : > "$QBOX_PROCESS_LOG"
    install_process_wrappers "$wrappers" || return 1
    Multiwfnpath="$MOCK_MULTIWFN_DIR"
    PATH="$wrappers:$MOCK_MULTIWFN_DIR:$PATH"
    fname1="$sandbox/water.cif"
    qe_prepare_structure_context "$fname1"
}

assert_no_invocations() {
    local tool
    for tool in "$@"; do
        assert_eq 0 "$(invocation_count "$tool")" \
            "$tool was started in a process-free structure path" || return 1
    done
}

test_prepare_and_pw_writer_avoid_repeated_parsers() {
    local sandbox wrappers output expected awk_count
    sandbox="$(new_sandbox)" || return 1
    wrappers="$sandbox/wrappers"
    (
        cd "$sandbox" || exit 1
        prepare_counted_context "$sandbox" "$wrappers" || exit 1

        awk_count="$(invocation_count awk)"
        [ "$awk_count" -le 2 ] || { fail "structure preparation started $awk_count awk processes"; exit 1; }
        assert_no_invocations sed sort bc || exit 1
        assert_eq '10.000000000 0.000000000 0.000000000' "${QE_STRUCT_CELL_LINES[1]-}" \
            'prepared context did not cache the first cell row' || exit 1
        assert_eq $'O\t5.000000000\t5.000000000\t5.000000000\t1' "${QE_STRUCT_ATOM_LINES[1]-}" \
            'prepared context did not cache the first atom row and bottom-layer flag' || exit 1

        : > "$QBOX_PROCESS_LOG"
        output="$sandbox/pw-structure.out"
        : > "$output"
        pseudolib=SSSP
        pseudo_file_by_lib() { printf '%s.UPF\n' "${atm[$2]}"; }
        qe_write_pw_structure "$output" || exit 1
        assert_no_invocations awk sed sort bc || exit 1

        expected="$sandbox/pw-structure.expected"
        printf '%s\n' \
            ' CELL_PARAMETERS angstrom' \
            '     10.000000000    0.000000000    0.000000000' \
            '     0.000000000    10.000000000    0.000000000' \
            '     0.000000000    0.000000000    10.000000000' \
            ' ' \
            ' ATOMIC_SPECIES' \
            $'   H \t1.008 \tH.UPF' \
            $'   O \t15.999 \tO.UPF' \
            ' ' \
            ' ATOMIC_POSITIONS angstrom' \
            '    O      5.000000000    5.000000000    5.000000000' \
            '    H      5.570000000    5.000000000    5.000000000' \
            '    H      4.810000000    5.540000000    5.000000000' > "$expected"
        assert_file_equals "$expected" "$output" 'PW structure output changed' || exit 1
        qe_release_structure_context || exit 1
    )
}

test_md_writer_uses_cached_rows_and_keeps_golden() {
    local sandbox wrappers awk_count
    sandbox="$(new_sandbox)" || return 1
    wrappers="$sandbox/wrappers"
    (
        cd "$sandbox" || exit 1
        prepare_counted_context "$sandbox" "$wrappers" || exit 1
        kpmesh=gamma
        pseudolib=SSSP
        md_time_ps=5
        md_timestep_fs=0.25
        md_fix_bottom=YES
        md_use_atomic_velocities=YES
        # Production does not enable nounset; preserve that shell mode while
        # exercising the historical sparse element arrays.
        set +u
        qe_md_pseudo_dir() { printf '%s\n' '/mock/SSSP'; }
        qe_md_pseudo_file() { printf '%s.UPF\n' "${atm[$1]}"; }
        default_cutoffs_from_pseudos() { printf '%s\n' '45 400'; }
        qe_estimate_nelec_from_current_pwin_context() { printf '%s\n' '10'; }

        : > "$QBOX_PROCESS_LOG"
        qe_generate_md_input >/dev/null || exit 1
        assert_eq 0 "$(invocation_count sed)" 'MD generation started sed for structure rows' || exit 1
        assert_eq 0 "$(invocation_count sort)" 'MD generation unexpectedly started sort' || exit 1
        assert_eq 0 "$(invocation_count bc)" 'MD generation unexpectedly started bc' || exit 1
        awk_count="$(invocation_count awk)"
        # Two scalar MD conversions plus the existing odd-electron predicate;
        # none scales with the number of cell or atom rows.
        [ "$awk_count" -le 3 ] || { fail "MD generation started $awk_count awk processes"; exit 1; }
        assert_file_equals "$PROJECT_ROOT/tests/fixtures/expected/md/water.md.in" \
            "$sandbox/water.md.in" 'MD output changed while removing row processes' || exit 1
        qe_release_structure_context || exit 1
    )
}

test_cluster_mass_is_aggregated_once_and_velocity_is_exact() {
    local sandbox wrappers expected
    sandbox="$(new_sandbox)" || return 1
    wrappers="$sandbox/wrappers"
    (
        cd "$sandbox" || exit 1
        export QBOX_PROCESS_LOG="$sandbox/process.log"
        : > "$QBOX_PROCESS_LOG"
        install_process_wrappers "$wrappers" || exit 1
        PATH="$wrappers:$PATH"
        qe_cluster_parse_cif_symbols() { printf '%s\n' H H O; }
        fname1=dummy.cif
        cv_energy=200
        cv_direction='0 0 -1'
        mkdir "$sandbox/work"
        qe_cluster_generate_velocities "$sandbox/work" >/dev/null || exit 1

        assert_eq 4 "$(invocation_count awk)" \
            'cluster velocity generation did not use one mass aggregation plus three fixed awk passes' || exit 1
        assert_eq 1 "$(count_lines_containing "$sandbox/work/masses")" \
            'cluster masses were not aggregated from the temp-dir masses file exactly once' || exit 1
        assert_no_invocations sed sort bc || exit 1
        expected="$sandbox/velocities.expected"
        printf '%s\n' \
            'ATOMIC_VELOCITIES a.u.' \
            'H        0.000000000     0.000000000    -0.021157165' \
            'H        0.000000000     0.000000000    -0.021157165' \
            'O        0.000000000     0.000000000    -0.021157165' > "$expected"
        assert_file_equals "$expected" "$sandbox/ATOMICs_VELOCITIES" \
            'cluster velocity output changed' || exit 1
    )
}

run_test 'structure preparation and PW writer avoid repeated parsers' test_prepare_and_pw_writer_avoid_repeated_parsers
run_test 'MD writer uses cached rows and keeps golden output' test_md_writer_uses_cached_rows_and_keeps_golden
run_test 'cluster mass aggregation is single-pass and velocity is exact' test_cluster_mass_is_aggregated_once_and_velocity_is_exact
finish_tests
