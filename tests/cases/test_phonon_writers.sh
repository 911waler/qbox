#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"

source_qbox

prepare_phonon_state() {
    prefix='water'
    ntyp=2
    atmtype[1]='H'
    atmtype[2]='O'
}

run_phonon_mode() {
    local sandbox="$1" mode="$2"
    (
        cd "$sandbox" || exit 1
        prepare_phonon_state
        "$mode" >stdout.txt 2>&1
    )
}

test_phonon_outputs_match_expected_goldens() {
    local mode files suffix sandbox expected
    local nonpolar_sandbox='' polar_sandbox=''

    while IFS='|' read -r mode files; do
        [ -n "$mode" ] || continue
        sandbox="$(new_sandbox)" || return 1
        run_phonon_mode "$sandbox" "$mode" || {
            fail "phonon mode failed on H/O fixture: $mode"
            return 1
        }

        expected="$TESTS_DIR/fixtures/expected/phonon/$mode"
        assert_or_update_golden "$expected/stdout.txt" "$sandbox/stdout.txt" \
            "phonon stdout changed for $mode" || return 1
        for suffix in $files; do
            [ -f "$sandbox/water${suffix}" ] || {
                fail "phonon mode did not generate water${suffix}: $mode"
                return 1
            }
            assert_or_update_golden "$expected/water${suffix}" "$sandbox/water${suffix}" \
                "phonon output changed for $mode water${suffix}" || return 1
        done

        case "$mode" in
            qe_phonon_nonpolar_dispersion) nonpolar_sandbox="$sandbox" ;;
            qe_phonon_polar_dispersion) polar_sandbox="$sandbox" ;;
        esac
    done <<'CASES'
qe_phonon_gas_frequency|.ph.in .dynmat.in
qe_phonon_nonpolar_frequency|.ph.in .dynmat.in
qe_phonon_ir|.ph.in .dynmat.in
qe_phonon_nonpolar_dispersion|.ph.in .q2r.in .matdyn.in .plotband.in
qe_phonon_nonpolar_raman|.ph.in .dynmat.in
qe_phonon_polar_frequency|.ph.in .dynmat.in
qe_phonon_polar_dispersion|.ph.in .q2r.in .matdyn.in .plotband.in
qe_phonon_polar_raman|.ph.in .dynmat.in
CASES

    for suffix in .ph.in .q2r.in .matdyn.in .plotband.in; do
        assert_file_equals "$nonpolar_sandbox/water${suffix}" "$polar_sandbox/water${suffix}" \
            "polar/nonpolar dispersion differs for water${suffix}" || return 1
    done
}

test_phonon_writer_interfaces_are_top_level() {
    local writer
    for writer in \
        qe_write_ph_masses qe_write_ph_input qe_write_dynmat_input \
        qe_write_dispersion_post_inputs qe_generate_phonon_dispersion_inputs; do
        declare -F "$writer" >/dev/null || {
            fail "missing phonon writer: $writer"
            return 1
        }
    done
}

test_phonon_writers_have_explicit_contracts() {
    local body
    body="$(declare -f qe_write_ph_input)"
    assert_contains "$body" 'local outfile="$1"' || return 1
    assert_contains "$body" 'local fildyn="$2"' || return 1
    assert_contains "$body" 'local epsil="$3"' || return 1
    assert_contains "$body" 'local lraman="$4"' || return 1
    assert_contains "$body" 'local ldisp="$5"' || return 1
    assert_contains "$body" 'local qpoint="$6"' || return 1

    body="$(declare -f qe_write_dynmat_input)"
    assert_contains "$body" 'local outfile="$1"' || return 1
    assert_contains "$body" 'local fildyn="$2"' || return 1
    assert_contains "$body" 'local asr="$3"' || return 1

    body="$(declare -f qe_write_dispersion_post_inputs)"
    assert_contains "$body" 'local prefix="$1"' || return 1
}

test_ph_input_writer_formats_option_values() {
    local sandbox body
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        prepare_phonon_state
        qe_write_ph_input test.ph.in water.dynG '.true.' '' '' '0.0 0.0 0.0' || exit 1
    ) || return 1
    body="$(cat "$sandbox/test.ph.in")"
    assert_contains "$body" '   epsil=.true.,' \
        'ph input writer did not format epsil as a Fortran logical line'
}

test_phonon_mass_lookup_source_contract() {
    local source body
    source="$(declare -f qe_write_ph_masses)"
    body="$(declare -f qe_write_ph_masses)"
    assert_contains "$source" 'for ((j=1; j<=86; j++))' \
        'phonon mass lookup range changed from H-Rn coverage' || return 1
    assert_contains "$source" 'if [ "${atmtype[$i]}" == "${atm[$j]}" ]; then' \
        'phonon mass lookup no longer matches symbols' || return 1
    assert_contains "$source" 'atmindex=$j' \
        'phonon mass lookup no longer records the matched index' || return 1
    assert_contains "$source" 'atmmass[$atmindex]' \
        'phonon mass writer no longer uses the matched atomic mass' || return 1
    assert_not_contains "$body" 'atmindex=""' \
        'phonon mass writer cleared ambient atmindex' || return 1
    assert_not_contains "$body" "atmindex=''" \
        'phonon mass writer cleared ambient atmindex' || return 1
    assert_not_contains "$body" 'atmindex=0' \
        'phonon mass writer reset ambient atmindex' || return 1
}

test_phonon_mass_lookup_edges_and_ambient_state() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        cd "$sandbox" || exit 1
        ntyp=3
        atmtype[1]='H'
        atmtype[2]='Rn'
        atmtype[3]='Xx'
        atmindex=0
        : > masses.in || exit 1
        qe_write_ph_masses masses.in || exit 1
        printf '%s\n' "$atmindex" > ambient-atmindex.txt
    ) || return 1

    assert_eq '   amass(1)=1.008,' "$(sed -n '1p' "$sandbox/masses.in")" \
        'H mass lookup output is incorrect' || return 1
    assert_eq '   amass(2)=222,' "$(sed -n '2p' "$sandbox/masses.in")" \
        'Rn mass lookup output is incorrect' || return 1
    assert_eq '   amass(3)=222,' "$(sed -n '3p' "$sandbox/masses.in")" \
        'ambient mass lookup output is incorrect' || return 1
    assert_eq '86' "$(cat "$sandbox/ambient-atmindex.txt")" \
        'ambient atmindex value is incorrect'
}

test_phonon_dispersion_has_one_shared_body() {
    local calls=0
    qe_generate_phonon_dispersion_inputs() { calls=$((calls + 1)); }
    qe_phonon_nonpolar_dispersion || return 1
    assert_eq 1 "$calls" 'nonpolar dispersion must call the shared generator once' || return 1
    qe_phonon_polar_dispersion || return 1
    assert_eq 2 "$calls" 'polar dispersion must call the shared generator once'
}

test_phonon_builders_do_not_duplicate_common_writers() {
    local function_name body
    for function_name in \
        qe_phonon_gas_frequency qe_phonon_nonpolar_frequency qe_phonon_ir \
        qe_phonon_nonpolar_raman qe_phonon_polar_frequency qe_phonon_polar_raman; do
        body="$(declare -f "$function_name")"
        assert_not_contains "$body" 'for ((j=1;j<=86;j++))' \
            "$function_name still owns the common mass lookup" || return 1
        assert_not_contains "$body" "echo '&inputph'" \
            "$function_name still owns the common ph input header" || return 1
    done
}

run_test 'phonon outputs match expected goldens' test_phonon_outputs_match_expected_goldens
run_test 'phonon writer interfaces are top-level' test_phonon_writer_interfaces_are_top_level
run_test 'phonon writers expose explicit contracts' test_phonon_writers_have_explicit_contracts
run_test 'ph input writer formats option values' test_ph_input_writer_formats_option_values
run_test 'phonon mass lookup source contract' test_phonon_mass_lookup_source_contract
run_test 'phonon mass lookup edge behavior' test_phonon_mass_lookup_edges_and_ambient_state
run_test 'dispersion has one shared body' test_phonon_dispersion_has_one_shared_body
run_test 'phonon builders use common writers' test_phonon_builders_do_not_duplicate_common_writers
finish_tests
