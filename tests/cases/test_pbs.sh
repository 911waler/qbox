#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"

source_qbox

generate_scan_kp_pbs() {
    local sandbox="$1"
    (
        cd "$sandbox" || exit 1
        mkdir scan_kp || exit 1
        qbox_write_kpoint_batch_script scan_kp || exit 1
        sed '/^#PBS -N /c\#PBS -N <JOB_NAME>' \
            scan_kp/sub_qe.sh >scan_kp.sub_qe.sh
    )
}

test_scan_kp_pbs_uses_matching_job_name() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    generate_scan_kp_pbs "$sandbox" || return 1

    assert_or_update_golden \
        "$TESTS_DIR/fixtures/expected/pbs/scan_kp.sub_qe.sh" \
        "$sandbox/scan_kp.sub_qe.sh" \
        'scan_kp PBS template changed outside the normalized job name' || return 1
    assert_or_update_golden \
        "$TESTS_DIR/fixtures/expected/pbs/scan_kp.gp" \
        "$sandbox/scan_kp/scan_kp.gp" \
        'scan_kp gnuplot template changed' || return 1

    grep -Fxq '#PBS -N scan_kp' "$sandbox/scan_kp/sub_qe.sh" || {
        fail 'scan_kp PBS script does not use the scan_kp job name'
        return 1
    }
    if grep -Fxq '#PBS -N scan_ecut' "$sandbox/scan_kp/sub_qe.sh"; then
        fail 'scan_kp PBS script still uses the scan_ecut job name'
        return 1
    fi
}

test_scan_kp_pbs_stops_when_calculation_fails() {
    local sandbox bin_dir status
    sandbox="$(new_sandbox)" || return 1
    bin_dir="$sandbox/bin"
    mkdir -p "$sandbox/scan_kp" "$bin_dir"
    : >"$sandbox/scan_kp/sample.scf.in"
    qbox_write_kpoint_batch_script "$sandbox/scan_kp" || return 1
    cat >"$bin_dir/mpirun" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
    chmod +x "$bin_dir/mpirun"
    (
        cd "$sandbox/scan_kp" || exit 1
        PATH="$bin_dir:$PATH" PBS_O_WORKDIR="$PWD" bash ./sub_qe.sh
    )
    status=$?
    [ "$status" -ne 0 ] || fail 'PBS script ignored a failed calculation'
}

test_scan_kp_pbs_stops_when_energy_is_missing() {
    local sandbox bin_dir status
    sandbox="$(new_sandbox)" || return 1
    bin_dir="$sandbox/bin"
    mkdir -p "$sandbox/scan_kp" "$bin_dir"
    : >"$sandbox/scan_kp/sample.scf.in"
    qbox_write_kpoint_batch_script "$sandbox/scan_kp" || return 1
    cat >"$bin_dir/mpirun" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' 'calculation finished without an energy row'
EOF
    chmod +x "$bin_dir/mpirun"
    (
        cd "$sandbox/scan_kp" || exit 1
        PATH="$bin_dir:$PATH" PBS_O_WORKDIR="$PWD" bash ./sub_qe.sh
    )
    status=$?
    [ "$status" -ne 0 ] || fail 'PBS script accepted output without a QE energy row'
}

test_scan_kp_pbs_rejects_nonenergy_markers() {
    local sandbox bin_dir status
    sandbox="$(new_sandbox)" || return 1
    bin_dir="$sandbox/bin"
    mkdir -p "$sandbox/scan_kp" "$bin_dir"
    : >"$sandbox/scan_kp/sample.scf.in"
    qbox_write_kpoint_batch_script "$sandbox/scan_kp" || return 1
    cat >"$bin_dir/mpirun" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' '! unrelated marker'
EOF
    chmod +x "$bin_dir/mpirun"
    (
        cd "$sandbox/scan_kp" || exit 1
        PATH="$bin_dir:$PATH" PBS_O_WORKDIR="$PWD" bash ./sub_qe.sh
    )
    status=$?
    [ "$status" -ne 0 ] || fail 'PBS script accepted a non-energy marker'
}

run_test 'scan_kp PBS uses matching job name' test_scan_kp_pbs_uses_matching_job_name
run_test 'scan_kp PBS stops when the calculation fails' test_scan_kp_pbs_stops_when_calculation_fails
run_test 'scan_kp PBS stops when the QE energy row is missing' test_scan_kp_pbs_stops_when_energy_is_missing
run_test 'scan_kp PBS rejects non-energy markers' test_scan_kp_pbs_rejects_nonenergy_markers
finish_tests
