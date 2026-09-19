#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"

source_qbox

test_uppercase_nbnd_and_nat() (
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    cd "$sandbox" || return 1

    cat > cell.scf.in <<'EOF'
! NBND = 99,
! NAT = 99,

&SYSTEM
  NBnD = 12,
  nbnd = 18,
  NAT = 3,
  nat = 7,
/
EOF

    assert_eq 12 "$(qe_unfold_read_nbnd cell.scf.in)" || return 1
    assert_eq 3 "$(qe_estimate_atom_count cell)"
)

test_nbnd_miss_and_nat_structure_fallback() (
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    cd "$sandbox" || return 1

    printf '&SYSTEM\n  ntyp = 2,\n/\n' > molecule.scf.in
    printf '4\nstructure fallback\nH 0 0 0\nH 0 0 1\nO 0 0 2\nO 0 0 3\n' > molecule.xyz

    assert_eq '' "$(qe_unfold_read_nbnd molecule.scf.in)" || return 1
    assert_eq 4 "$(qe_estimate_atom_count molecule)"
)

test_uppercase_upf_cutoffs_and_numeric_conversion() (
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    cd "$sandbox" || return 1

    cat > sample.upf <<'EOF'
<UPF version="2.0.1">
  <PP_HEADER WFC_CUTOFF="40.0D+0" RHO_CUTOFF="3.2E2"/>
</UPF>
EOF

    assert_eq '40 320' "$(read_upf_cutoffs sample.upf)"
)

test_decimal_frequency_contract() (
    local status
    qe_frequency_is_positive 0.125 || return 1
    qe_frequency_is_positive .5 || return 1
    qe_frequency_is_positive 0.0000000000000000000000000000001 || return 1

    if qe_frequency_is_positive -0.25; then status=0; else status=$?; fi
    assert_eq 1 "$status" || return 1
    if qe_frequency_is_positive 0.0; then status=0; else status=$?; fi
    assert_eq 1 "$status" || return 1
    if qe_frequency_is_positive 1e-20; then status=0; else status=$?; fi
    assert_eq 2 "$status" || return 1
    if qe_frequency_is_positive 1D-20; then status=0; else status=$?; fi
    assert_eq 2 "$status" || return 1
    if qe_frequency_is_positive +.5; then status=0; else status=$?; fi
    assert_eq 2 "$status" || return 1
    if qe_frequency_is_positive ''; then status=0; else status=$?; fi
    assert_eq 2 "$status"
)

prepare_gas_thermo_fixture() {
    local sandbox="$1"
    cat > "$sandbox/dynmat.mold" <<'EOF'
dynmat header
frequency header
0.125
.5
-0.25
0.0
0.0000000000000000000000000000001
FR-COORD
EOF
    cat > "$sandbox/molecule.xyz" <<'EOF'
H 0 0 0
O 1.25 -2.5 3
EOF
}

prepare_bc_failure_path() {
    local controlled_bin="$1" tool
    mkdir -p "$controlled_bin" || return 1
    for tool in awk grep ls sed; do
        ln -s "$(command -v "$tool")" "$controlled_bin/$tool" || return 1
    done
    cat > "$controlled_bin/bc" <<'EOF'
#!/usr/bin/env bash
printf 'bc was invoked\n' >> "$BC_SENTINEL_LOG"
exit 97
EOF
    chmod +x "$controlled_bin/bc"
}

test_gas_thermo_keeps_decimal_bytes_without_bc() (
    local sandbox controlled_bin
    sandbox="$(new_sandbox)" || return 1
    controlled_bin="$sandbox/bin"
    prepare_gas_thermo_fixture "$sandbox" || return 1
    prepare_bc_failure_path "$controlled_bin" || return 1

    cat > "$sandbox/expected.shm" <<'EOF'
*E
  Input electronic energy in Hartree unit rather than Ry unit.
*wavenum
0.125
.5
0.0000000000000000000000000000001
*atoms
H 	1.008 	 0.000000000    0.000000000    0.000000000
O 	15.999 	 1.250000000    -2.500000000    3.000000000
*elevel
0.00    1
EOF

    (
        set -e
        cd "$sandbox"
        prefix=water
        fname1=molecule.xyz
        natm=2
        begatmpos=1
        export BC_SENTINEL_LOG="$sandbox/bc-called.log"
        PATH="$controlled_bin"
        qe_phonon_gas_thermo >stdout.txt 2>&1
        printf 'completed\n' > completed.txt
    ) || return 1

    assert_eq "$(base64 "$sandbox/expected.shm")" "$(base64 "$sandbox/water.shm")" \
        'gas thermochemistry output changed for ordinary decimals' || return 1
    assert_eq completed "$(cat "$sandbox/completed.txt")" || return 1
    [ ! -e "$sandbox/bc-called.log" ] || fail 'gas thermochemistry invoked bc'
)

test_invalid_frequency_preserves_existing_output() (
    local sandbox value status output
    for value in 1e-20 invalid; do
        sandbox="$(new_sandbox)" || return 1
        prepare_gas_thermo_fixture "$sandbox" || return 1
        printf 'dynmat header\nfrequency header\n%s\nFR-COORD\n' "$value" \
            > "$sandbox/dynmat.mold"
        printf 'existing output\n' > "$sandbox/water.shm"

        if output="$({
            set -e
            cd "$sandbox"
            prefix=water
            fname1=molecule.xyz
            natm=2
            begatmpos=1
            qe_phonon_gas_thermo
        } 2>&1)"; then
            status=0
        else
            status=$?
        fi

        assert_eq 2 "$status" "invalid frequency '$value' returned the wrong status" || return 1
        assert_eq 'existing output' "$(cat "$sandbox/water.shm")" \
            "invalid frequency '$value' truncated an existing output" || return 1
        assert_contains "$output" "$value" "diagnostic omitted invalid frequency '$value'" || return 1
        case "$value" in
            1e-20) assert_contains "$output" '不支持指数记数法' \
                'exponent diagnostic did not state the unsupported form' || return 1 ;;
            *) assert_contains "$output" '普通十进制' \
                'invalid-decimal diagnostic did not state the supported form' || return 1 ;;
        esac
    done
)

run_test 'uppercase nbnd and nat use first uncommented match' test_uppercase_nbnd_and_nat
run_test 'nbnd miss and nat structure fallback remain stable' test_nbnd_miss_and_nat_structure_fallback
run_test 'uppercase UPF cutoffs retain numeric conversion' test_uppercase_upf_cutoffs_and_numeric_conversion
run_test 'ordinary decimal frequency contract' test_decimal_frequency_contract
run_test 'gas thermochemistry preserves decimal bytes without bc' test_gas_thermo_keeps_decimal_bytes_without_bc
run_test 'invalid frequencies preserve existing output' test_invalid_frequency_preserves_existing_output
finish_tests
