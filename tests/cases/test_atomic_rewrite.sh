#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

make_pw_rewriter_input() {
    local input="$1"
    printf '%s\n' \
        '&CONTROL' \
        " calculation = 'scf'," \
        '/' \
        '&SYSTEM' \
        ' ibrav = 0,' \
        ' nat = 1,' \
        ' ntyp = 1,' \
        ' nbnd = 4,' \
        " occupations = 'smearing'," \
        '/' \
        '&ELECTRONS' \
        ' conv_thr = 1.0D-8,' \
        ' electron_maxstep = 100,' \
        " mixing_mode = 'plain'," \
        ' mixing_beta = 0.7,' \
        ' mixing_ndim = 8,' \
        " diagonalization = 'david'," \
        ' diago_david_ndim = 4,' \
        ' diago_full_acc = .false.,' \
        ' diago_thr_init = 1.0D-2,' \
        '/' \
        'K_POINTS automatic' \
        ' 2 2 2 0 0 0' >"$input"
}

make_nscf_rewriter_input() {
    local input="$1"
    printf '%s\n' \
        '&CONTROL' \
        " calculation = 'scf'," \
        " restart_mode = 'from_scratch'," \
        '/' \
        '&SYSTEM' \
        ' ibrav = 0,' \
        ' nat = 1,' \
        ' ntyp = 1,' \
        ' nbnd = 4,' \
        " occupations = 'smearing'," \
        ' nosym = .false.,' \
        ' noinv = .false.,' \
        ' degauss = 0.01,' \
        " smearing = 'gauss'," \
        '/' \
        '&ELECTRONS' \
        ' conv_thr = 1.0D-8,' \
        ' electron_maxstep = 100,' \
        " diagonalization = 'david'," \
        '/' \
        'K_POINTS automatic' \
        ' 2 2 2 0 0 0' >"$input"
}

make_bandsx_rewriter_input() {
    local input="$1"
    printf '%s\n' \
        '&BANDS' \
        " prefix = 'sample'," \
        " filband = 'bands.dat'," \
        ' lsym = .true.,' \
        '/' >"$input"
}

make_pdos_rewriter_input() {
    local input="$1"
    printf '%s\n' \
        '&PROJWFC' \
        " prefix = 'sample'," \
        " filpdos = 'pdos.dat'," \
        ' DeltaE = 0.01,' \
        '/' >"$input"
}

make_pdos_batch_rewriter_input() {
    local input="$1"
    printf '%s\n' \
        '&CONTROL' \
        " calculation = 'scf'," \
        '/' \
        '&SYSTEM' \
        ' ibrav = 0,' \
        ' ecutwfc = 30,' \
        ' ecutrho = 300,' \
        ' nspin = 2,' \
        " occupations = 'fixed'," \
        " smearing = 'gauss'," \
        ' degauss = 0.02,' \
        ' starting_magnetization(1) = 0.5,' \
        ' tot_magnetization = 1,' \
        '/' \
        '&ELECTRONS' \
        ' conv_thr = 1.0D-5,' \
        ' mixing_beta = 0.7,' \
        '/' >"$input"
}

make_pd04_rewriter_input() {
    local input="$1"
    printf '%s\n' \
        '&CONTROL' \
        " pseudo_dir = '/old/pseudo'," \
        " prefix = 'sample'," \
        '/' \
        'ATOMIC_SPECIES' \
        ' H 1.008 H.old.UPF' \
        ' O 15.999 O.old.UPF' \
        ' Si 28.085 Si.old.UPF' \
        'ATOMIC_POSITIONS angstrom' \
        ' H 0.0 0.0 0.0' \
        ' O 0.0 0.0 1.0' \
        ' Si 1.0 1.0 1.0' \
        'K_POINTS gamma' >"$input"
}

prepare_atomic_target() {
    local sentinel="$1" tmp_path="$2"
    printf 'sentinel bytes must remain unchanged\n' >"$sentinel"
    ln -s "$(basename "$sentinel")" "$tmp_path"
}

run_concurrently() {
    local callback="$1" argument="$2" log_prefix="$3" pid1 pid2 status1 status2
    ( "$callback" "$argument" ) >"${log_prefix}.1" 2>&1 &
    pid1=$!
    ( "$callback" "$argument" ) >"${log_prefix}.2" 2>&1 &
    pid2=$!
    wait "$pid1"
    status1=$?
    wait "$pid2"
    status2=$?
    [ "$status1" -eq 0 ] && [ "$status2" -eq 0 ]
}

run_bandsx_rewrite() {
    qe_prepare_bandsx_input_for_band_dir "$1"
}

run_pdos_rewrite() {
    qe_prepare_pdos_input_for_pdos_dir "$1"
}

run_pdos_batch_rewrite() {
    QE_PDOS_ECUTWFC=55 \
    QE_PDOS_ECUTRHO=550 \
    QE_PDOS_CONV_THR=1.D-9 \
    QE_PDOS_DEGAUSS=0.015 \
    qe_prepare_pdos_batch_pw_input "$1"
}

run_pd04_rewrite() {
    PD04PBEpath='/fixture/pd04' qe_rewrite_pseudopotentials_to_pd04 "$1"
}

run_scf2nscf_rewrite() {
    fname1="$1"
    scf2nscf
}

run_nscf_rewrite() {
    local prefix="$1"
    qe_atomic_rewrite "${prefix}.nscf.in" qe_render_nscf_nbnd_update
}

prepare_rewriter_case() {
    local input="$1" sentinel="$2" tmp_path="$3"
    make_pw_rewriter_input "$input"
    printf 'sentinel bytes must remain unchanged\n' >"$sentinel"
    ln -s "$(basename "$sentinel")" "$tmp_path"
}

assert_rewriter_result() {
    local input="$1" expected="$2" sentinel="$3" tmp_path="$4" name="$5"
    assert_or_update_golden "$expected" "$input" "$name output changed" || return 1
    [ -L "$tmp_path" ] || { fail "$name replaced the predictable .tmp symlink"; return 1; }
    assert_eq "sentinel bytes must remain unchanged" "$(cat "$sentinel")" "$name changed the .tmp symlink target" || return 1
}

assert_workflow_result() {
    local input="$1" expected="$2" sentinel="$3" tmp_path="$4" name="$5"
    assert_or_update_golden "$expected" "$input" "$name output changed" || return 1
    [ -L "$tmp_path" ] || { fail "$name replaced the predictable temp symlink"; return 1; }
    assert_eq "sentinel bytes must remain unchanged" "$(cat "$sentinel")" "$name changed the predictable temp symlink target" || return 1
    [ -z "$(find "$(dirname "$input")" -maxdepth 1 -name '.*.qbox.*' -print -quit)" ] || {
        fail "$name leaked a managed temp file"
        return 1
    }
}

test_qe_set_pw_nbnd_atomic_rewrite() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pw-nbnd.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/pw-nbnd.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    prepare_rewriter_case "$input" "$sentinel" "$tmp_path"
    qe_set_pw_nbnd_in_file "$input" 8
    status=$?
    assert_eq 0 "$status" 'qe_set_pw_nbnd_in_file failed for valid input' || return 1
    assert_rewriter_result "$input" "$expected" "$sentinel" "$tmp_path" qe_set_pw_nbnd_in_file
}

test_pwin_replace_kpoints_atomic_rewrite() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pwin-kpoints.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/pwin-kpoints.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    prepare_rewriter_case "$input" "$sentinel" "$tmp_path"
    pwin_replace_kpoints_in_file "$input" '4*5*6'
    status=$?
    assert_eq 0 "$status" 'pwin_replace_kpoints_in_file failed for valid input' || return 1
    assert_rewriter_result "$input" "$expected" "$sentinel" "$tmp_path" pwin_replace_kpoints_in_file
}

test_pwin_set_diagonalization_accuracy_atomic_rewrite() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pwin-diagonalization-accuracy.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/pwin-diagonalization-accuracy.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    prepare_rewriter_case "$input" "$sentinel" "$tmp_path"
    pwin_diago_full_acc=true
    pwin_diago_thr_init='1.0D-10'
    pwin_set_diagonalization_accuracy_in_file "$input"
    status=$?
    assert_eq 0 "$status" 'pwin_set_diagonalization_accuracy_in_file failed for valid input' || return 1
    assert_rewriter_result "$input" "$expected" "$sentinel" "$tmp_path" pwin_set_diagonalization_accuracy_in_file
}

test_pwin_set_diagonalization_atomic_rewrite() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pwin-diagonalization.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/pwin-diagonalization.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    prepare_rewriter_case "$input" "$sentinel" "$tmp_path"
    pwin_diagonalization='cg'
    pwin_diago_david_ndim=12
    pwin_diago_cg_maxiter=25
    pwin_set_diagonalization_settings_in_file "$input"
    status=$?
    assert_eq 0 "$status" 'pwin_set_diagonalization_settings_in_file failed for valid input' || return 1
    assert_rewriter_result "$input" "$expected" "$sentinel" "$tmp_path" pwin_set_diagonalization_settings_in_file
}

test_pwin_remove_charge_mixing_atomic_rewrite() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pwin-without-charge-mixing.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/pwin-without-charge-mixing.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    prepare_rewriter_case "$input" "$sentinel" "$tmp_path"
    pwin_remove_charge_mixing_settings_from_file "$input"
    status=$?
    assert_eq 0 "$status" 'pwin_remove_charge_mixing_settings_from_file failed for valid input' || return 1
    assert_rewriter_result "$input" "$expected" "$sentinel" "$tmp_path" pwin_remove_charge_mixing_settings_from_file
}

test_renderer_failure_rolls_back_target() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pw-failure.in"
    expected="$sandbox/pw-failure.expected"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    prepare_rewriter_case "$input" "$sentinel" "$tmp_path"
    cp -- "$input" "$expected"
    qe_render_pw_nbnd() {
        printf 'partial replacement\n'
        return 17
    }
    qe_set_pw_nbnd_in_file "$input" 8
    status=$?
    assert_eq 17 "$status" 'renderer failure status was not propagated' || return 1
    assert_file_equals "$expected" "$input" 'renderer failure replaced the target' || return 1
    [ -L "$tmp_path" ] || { fail 'renderer failure replaced the predictable .tmp symlink'; return 1; }
    assert_eq "sentinel bytes must remain unchanged" "$(cat "$sentinel")" 'renderer failure changed the .tmp symlink target'
}

test_nscf_conversion_rewrite_is_atomic() {
    local sandbox prefix input expected sentinel tmp_path mode status
    sandbox="$(new_sandbox)" || return 1
    prefix="$sandbox/sample"
    input="${prefix}.nscf.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/nscf-nbnd-update.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    make_nscf_rewriter_input "$input"
    chmod 640 "$input"
    mode="$(stat -c '%a' "$input")"
    printf 'sentinel bytes must remain unchanged\n' >"$sentinel"
    ln -s "$(basename "$sentinel")" "$tmp_path"

    run_nscf_rewrite "$prefix"
    status=$?
    assert_eq 0 "$status" 'NSCF rewrite failed for valid input' || return 1
    assert_file_equals "$expected" "$input" 'NSCF rewrite output changed' || return 1
    assert_eq "$mode" "$(stat -c '%a' "$input")" 'NSCF rewrite changed target mode' || return 1
    [ -L "$tmp_path" ] || { fail 'NSCF rewrite replaced the predictable .tmp symlink'; return 1; }
    assert_eq "sentinel bytes must remain unchanged" "$(cat "$sentinel")" 'NSCF rewrite changed the .tmp symlink target' || return 1
    [ -z "$(find "$sandbox" -maxdepth 1 -name '.*.qbox.*' -print -quit)" ] || { fail 'NSCF rewrite leaked a managed temp file'; return 1; }
}

test_nscf_conversion_renderer_failure_rolls_back() {
    local sandbox prefix input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    prefix="$sandbox/failure"
    input="${prefix}.nscf.in"
    expected="$sandbox/failure.expected"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    make_nscf_rewriter_input "$input"
    cp -- "$input" "$expected"
    printf 'sentinel bytes must remain unchanged\n' >"$sentinel"
    ln -s "$(basename "$sentinel")" "$tmp_path"

    (
        qe_render_nscf_nbnd_update() {
            printf 'partial replacement\n'
            return 19
        }
        run_nscf_rewrite "$prefix"
    )
    status=$?
    assert_eq 19 "$status" 'NSCF renderer failure status was not propagated' || return 1
    assert_file_equals "$expected" "$input" 'NSCF renderer failure replaced the target' || return 1
    [ -L "$tmp_path" ] || { fail 'NSCF renderer failure replaced the predictable .tmp symlink'; return 1; }
    assert_eq "sentinel bytes must remain unchanged" "$(cat "$sentinel")" 'NSCF renderer failure changed the .tmp symlink target' || return 1
    [ -z "$(find "$sandbox" -maxdepth 1 -name '.*.qbox.*' -print -quit)" ] || { fail 'NSCF renderer failure leaked a managed temp file'; return 1; }
}

test_bandsx_workflow_rewrite_is_atomic() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/bands.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/bandsx-for-band-dir.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    make_bandsx_rewriter_input "$input"
    prepare_atomic_target "$sentinel" "$tmp_path"
    run_bandsx_rewrite "$input"
    status=$?
    assert_eq 0 "$status" 'qe_prepare_bandsx_input_for_band_dir failed for valid input' || return 1
    assert_workflow_result "$input" "$expected" "$sentinel" "$tmp_path" qe_prepare_bandsx_input_for_band_dir
}

test_bandsx_workflow_renderer_failure_rolls_back() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/bands.in"
    expected="$sandbox/bands.expected"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    make_bandsx_rewriter_input "$input"
    cp -- "$input" "$expected"
    prepare_atomic_target "$sentinel" "$tmp_path"
    (
        qe_render_bandsx_for_band_dir() {
            printf 'partial replacement\n'
            return 41
        }
        run_bandsx_rewrite "$input"
    )
    status=$?
    assert_eq 41 "$status" 'bands.x renderer failure status was not propagated' || return 1
    assert_file_equals "$expected" "$input" 'bands.x renderer failure replaced the target' || return 1
    [ -L "$tmp_path" ] || { fail 'bands.x renderer failure replaced the predictable temp symlink'; return 1; }
    assert_eq "sentinel bytes must remain unchanged" "$(cat "$sentinel")" 'bands.x renderer failure changed the temp symlink target' || return 1
    [ -z "$(find "$sandbox" -maxdepth 1 -name '.*.qbox.*' -print -quit)" ] || { fail 'bands.x renderer failure leaked a managed temp file'; return 1; }
}

test_bandsx_workflow_concurrent_rewrites_are_atomic() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/bands.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/bandsx-for-band-dir.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    make_bandsx_rewriter_input "$input"
    prepare_atomic_target "$sentinel" "$tmp_path"
    run_concurrently run_bandsx_rewrite "$input" "$sandbox/bands.concurrent"
    status=$?
    assert_eq 0 "$status" 'concurrent bands.x rewrites did not both succeed' || return 1
    assert_workflow_result "$input" "$expected" "$sentinel" "$tmp_path" 'concurrent bands.x rewrites'
}

test_pdos_workflow_rewrite_is_atomic() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pdos.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/pdos-for-pdos-dir.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    make_pdos_rewriter_input "$input"
    prepare_atomic_target "$sentinel" "$tmp_path"
    run_pdos_rewrite "$input"
    status=$?
    assert_eq 0 "$status" 'qe_prepare_pdos_input_for_pdos_dir failed for valid input' || return 1
    assert_workflow_result "$input" "$expected" "$sentinel" "$tmp_path" qe_prepare_pdos_input_for_pdos_dir
}

test_pdos_workflow_renderer_failure_rolls_back() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pdos.in"
    expected="$sandbox/pdos.expected"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    make_pdos_rewriter_input "$input"
    cp -- "$input" "$expected"
    prepare_atomic_target "$sentinel" "$tmp_path"
    (
        qe_render_pdos_for_pdos_dir() {
            printf 'partial replacement\n'
            return 43
        }
        run_pdos_rewrite "$input"
    )
    status=$?
    assert_eq 43 "$status" 'PDOS renderer failure status was not propagated' || return 1
    assert_file_equals "$expected" "$input" 'PDOS renderer failure replaced the target' || return 1
    [ -L "$tmp_path" ] || { fail 'PDOS renderer failure replaced the predictable temp symlink'; return 1; }
    assert_eq "sentinel bytes must remain unchanged" "$(cat "$sentinel")" 'PDOS renderer failure changed the temp symlink target' || return 1
    [ -z "$(find "$sandbox" -maxdepth 1 -name '.*.qbox.*' -print -quit)" ] || { fail 'PDOS renderer failure leaked a managed temp file'; return 1; }
}

test_pdos_workflow_concurrent_rewrites_are_atomic() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pdos.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/pdos-for-pdos-dir.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    make_pdos_rewriter_input "$input"
    prepare_atomic_target "$sentinel" "$tmp_path"
    run_concurrently run_pdos_rewrite "$input" "$sandbox/pdos.concurrent"
    status=$?
    assert_eq 0 "$status" 'concurrent PDOS rewrites did not both succeed' || return 1
    assert_workflow_result "$input" "$expected" "$sentinel" "$tmp_path" 'concurrent PDOS rewrites'
}

test_pdos_batch_workflow_rewrite_is_atomic() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.scf.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/pdos-batch-pw.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.pdos-batch.tmp"
    make_pdos_batch_rewriter_input "$input"
    prepare_atomic_target "$sentinel" "$tmp_path"
    run_pdos_batch_rewrite "$input"
    status=$?
    assert_eq 0 "$status" 'qe_prepare_pdos_batch_pw_input failed for valid input' || return 1
    assert_workflow_result "$input" "$expected" "$sentinel" "$tmp_path" qe_prepare_pdos_batch_pw_input
}

test_pdos_batch_workflow_renderer_failure_rolls_back() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.scf.in"
    expected="$sandbox/pdos-batch.expected"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.pdos-batch.tmp"
    make_pdos_batch_rewriter_input "$input"
    cp -- "$input" "$expected"
    prepare_atomic_target "$sentinel" "$tmp_path"
    (
        qe_render_pdos_batch_pw() {
            printf 'partial replacement\n'
            return 47
        }
        run_pdos_batch_rewrite "$input"
    )
    status=$?
    assert_eq 47 "$status" 'PDOS batch renderer failure status was not propagated' || return 1
    assert_file_equals "$expected" "$input" 'PDOS batch renderer failure replaced the target' || return 1
    [ -L "$tmp_path" ] || { fail 'PDOS batch renderer failure replaced the predictable temp symlink'; return 1; }
    assert_eq "sentinel bytes must remain unchanged" "$(cat "$sentinel")" 'PDOS batch renderer failure changed the temp symlink target' || return 1
    [ -z "$(find "$sandbox" -maxdepth 1 -name '.*.qbox.*' -print -quit)" ] || { fail 'PDOS batch renderer failure leaked a managed temp file'; return 1; }
}

test_pdos_batch_workflow_concurrent_rewrites_are_atomic() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.scf.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/pdos-batch-pw.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.pdos-batch.tmp"
    make_pdos_batch_rewriter_input "$input"
    prepare_atomic_target "$sentinel" "$tmp_path"
    run_concurrently run_pdos_batch_rewrite "$input" "$sandbox/pdos-batch.concurrent"
    status=$?
    assert_eq 0 "$status" 'concurrent PDOS batch rewrites did not both succeed' || return 1
    assert_workflow_result "$input" "$expected" "$sentinel" "$tmp_path" 'concurrent PDOS batch rewrites'
}

test_pd04_workflow_rewrite_is_atomic() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pd04.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/pd04-pseudos.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    make_pd04_rewriter_input "$input"
    prepare_atomic_target "$sentinel" "$tmp_path"
    run_pd04_rewrite "$input"
    status=$?
    assert_eq 0 "$status" 'qe_rewrite_pseudopotentials_to_pd04 failed for H/O/Si input' || return 1
    assert_workflow_result "$input" "$expected" "$sentinel" "$tmp_path" qe_rewrite_pseudopotentials_to_pd04
}

test_pd04_workflow_renderer_failure_rolls_back() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pd04.in"
    expected="$sandbox/pd04.expected"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    make_pd04_rewriter_input "$input"
    cp -- "$input" "$expected"
    prepare_atomic_target "$sentinel" "$tmp_path"
    (
        qe_render_pd04_pseudos() {
            printf 'partial replacement\n'
            return 53
        }
        run_pd04_rewrite "$input"
    )
    status=$?
    assert_eq 53 "$status" 'PD04 renderer failure status was not propagated' || return 1
    assert_file_equals "$expected" "$input" 'PD04 renderer failure replaced the target' || return 1
    [ -L "$tmp_path" ] || { fail 'PD04 renderer failure replaced the predictable temp symlink'; return 1; }
    assert_eq "sentinel bytes must remain unchanged" "$(cat "$sentinel")" 'PD04 renderer failure changed the temp symlink target' || return 1
    [ -z "$(find "$sandbox" -maxdepth 1 -name '.*.qbox.*' -print -quit)" ] || { fail 'PD04 renderer failure leaked a managed temp file'; return 1; }
}

test_pd04_workflow_concurrent_rewrites_are_atomic() {
    local sandbox input expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/pd04.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/pd04-pseudos.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${input}.tmp"
    make_pd04_rewriter_input "$input"
    prepare_atomic_target "$sentinel" "$tmp_path"
    run_concurrently run_pd04_rewrite "$input" "$sandbox/pd04.concurrent"
    status=$?
    assert_eq 0 "$status" 'concurrent PD04 rewrites did not both succeed' || return 1
    assert_workflow_result "$input" "$expected" "$sentinel" "$tmp_path" 'concurrent PD04 rewrites'
}

test_scf2nscf_workflow_rewrite_is_atomic() {
    local sandbox input output expected sentinel tmp_path source_mode status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.scf.in"
    output="$sandbox/sample.nscf.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/scf2nscf.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${output}.tmp"
    make_nscf_rewriter_input "$input"
    chmod 640 "$input"
    source_mode="$(stat -c '%a' "$input")"
    prepare_atomic_target "$sentinel" "$tmp_path"
    run_scf2nscf_rewrite "$input"
    status=$?
    assert_eq 0 "$status" 'scf2nscf failed for valid input' || return 1
    assert_workflow_result "$output" "$expected" "$sentinel" "$tmp_path" scf2nscf || return 1
    assert_eq "$source_mode" "$(stat -c '%a' "$output")" 'scf2nscf changed the copied target mode' || return 1
}

test_scf2nscf_workflow_renderer_failure_rolls_back() {
    local sandbox input output expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/failure.scf.in"
    output="$sandbox/failure.nscf.in"
    expected="$sandbox/failure.expected"
    sentinel="$sandbox/sentinel"
    tmp_path="${output}.tmp"
    make_nscf_rewriter_input "$input"
    printf 'pre-existing target must remain unchanged\n' >"$output"
    cp -- "$output" "$expected"
    prepare_atomic_target "$sentinel" "$tmp_path"
    (
        qe_render_scf_to_nscf() {
            printf 'partial replacement\n'
            return 59
        }
        fname1="$input"
        scf2nscf
    )
    status=$?
    assert_eq 59 "$status" 'scf2nscf renderer failure status was not propagated' || return 1
    assert_file_equals "$expected" "$output" 'scf2nscf renderer failure replaced the target' || return 1
    [ -L "$tmp_path" ] || { fail 'scf2nscf renderer failure replaced the predictable temp symlink'; return 1; }
    assert_eq "sentinel bytes must remain unchanged" "$(cat "$sentinel")" 'scf2nscf renderer failure changed the temp symlink target' || return 1
    [ -z "$(find "$sandbox" -maxdepth 1 -name '.*.qbox.*' -print -quit)" ] || { fail 'scf2nscf renderer failure leaked a managed temp file'; return 1; }
}

test_scf2nscf_workflow_concurrent_rewrites_are_atomic() {
    local sandbox input output expected sentinel tmp_path status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/sample.scf.in"
    output="$sandbox/sample.nscf.in"
    expected="$TESTS_DIR/fixtures/expected/rewriters/scf2nscf.in"
    sentinel="$sandbox/sentinel"
    tmp_path="${output}.tmp"
    make_nscf_rewriter_input "$input"
    prepare_atomic_target "$sentinel" "$tmp_path"
    run_concurrently run_scf2nscf_rewrite "$input" "$sandbox/scf2nscf.concurrent"
    status=$?
    assert_eq 0 "$status" 'concurrent scf2nscf rewrites did not both succeed' || return 1
    assert_workflow_result "$output" "$expected" "$sentinel" "$tmp_path" 'concurrent scf2nscf rewrites'
}

test_scf2nscf_accepts_decimal_electron_count() {
    local sandbox input output status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/decimal.scf.in"
    output="$sandbox/decimal.nscf.in"
    make_nscf_rewriter_input "$input"
    printf 'number of electrons = 10.5\n' >"$sandbox/decimal.out"

    run_scf2nscf_rewrite "$input" >"$sandbox/decimal.log" 2>&1
    status=$?
    assert_eq 0 "$status" 'scf2nscf rejected a valid decimal electron count' || return 1
    assert_contains "$(cat "$sandbox/decimal.log")" '根据电子数 10.5 为 NSCF 设置推荐 nbnd = 1' \
        'scf2nscf did not use the decimal electron count' || return 1
    grep -Eq "^[[:space:]]*nbnd[[:space:]]*= 1" "$output" || {
        fail 'scf2nscf did not update nbnd from the decimal electron count'
        return 1
    }
}

test_scf2nscf_renderer_removes_uppercase_smearing_settings() {
    local sandbox input output status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/uppercase.scf.in"
    output="$sandbox/uppercase.nscf.in"
    printf '%s\n' \
        '&CONTROL' \
        " calculation = 'scf'," \
        '/' \
        '&SYSTEM' \
        " OCCUPATIONS = 'smearing'," \
        " SMEARING = 'gauss'," \
        ' DEGAUSS = 0.03,' \
        '/' \
        'K_POINTS automatic' \
        ' 2 2 2 0 0 0' >"$input"

    qe_render_scf_to_nscf "$input" 1 >"$output"
    status=$?
    assert_eq 0 "$status" 'scf2nscf renderer failed on uppercase system settings' || return 1
    assert_not_contains "$(cat "$output")" 'SMEARING' 'uppercase smearing setting survived tetrahedra conversion' || return 1
    assert_not_contains "$(cat "$output")" 'DEGAUSS' 'uppercase degauss setting survived tetrahedra conversion' || return 1
    assert_contains "$(cat "$output")" "occupations     = 'tetrahedra'" \
        'tetrahedra occupation was not written for uppercase input' || return 1
}

test_scf2nscf_selects_tetrahedra_after_inline_comment_replacement() {
    local sandbox input output log status
    sandbox="$(new_sandbox)" || return 1
    input="$sandbox/commented.scf.in"
    output="$sandbox/commented.nscf.in"
    log="$sandbox/commented.log"
    printf '%s\n' \
        '&CONTROL' \
        " calculation = 'scf', ! methfessel-paxton" \
        " verbosity = 'low', ! methfessel-paxton" \
        '/' \
        '&SYSTEM' \
        " occupations = 'smearing'," \
        " smearing = 'gauss'," \
        ' degauss = 0.03,' \
        '/' \
        'K_POINTS automatic' \
        ' 2 2 2 0 0 0' >"$input"

    run_scf2nscf_rewrite "$input" >"$log" 2>&1
    status=$?
    assert_eq 0 "$status" 'scf2nscf failed on a valid inline-comment input' || return 1
    assert_contains "$(cat "$output")" "calculation     = 'nscf'" \
        'scf2nscf did not replace calculation after dropping its comment' || return 1
    assert_contains "$(cat "$output")" "verbosity       = 'high'" \
        'scf2nscf did not replace verbosity after dropping its comment' || return 1
    assert_not_contains "$(cat "$output")" 'methfessel-paxton' \
        'scf2nscf retained an inline methfessel-paxton comment' || return 1
    assert_contains "$(cat "$output")" "occupations     = 'tetrahedra'" \
        'scf2nscf did not select tetrahedra from post-replacement text' || return 1
    assert_not_contains "$(cat "$output")" 'smearing' \
        'scf2nscf retained smearing after selecting tetrahedra' || return 1
    assert_not_contains "$(cat "$output")" 'degauss' \
        'scf2nscf retained degauss after selecting tetrahedra' || return 1
    grep -Eq '^[[:space:]]*4 4 4 0 0 0$' "$output" || {
        fail 'scf2nscf did not double the automatic K mesh'
        return 1
    }
}

run_test 'qe_set_pw_nbnd_in_file rewrites atomically' test_qe_set_pw_nbnd_atomic_rewrite
run_test 'pwin_replace_kpoints_in_file rewrites atomically' test_pwin_replace_kpoints_atomic_rewrite
run_test 'pwin_set_diagonalization_accuracy_in_file rewrites atomically' test_pwin_set_diagonalization_accuracy_atomic_rewrite
run_test 'pwin_set_diagonalization_settings_in_file rewrites atomically' test_pwin_set_diagonalization_atomic_rewrite
run_test 'pwin_remove_charge_mixing_settings_from_file rewrites atomically' test_pwin_remove_charge_mixing_atomic_rewrite
run_test 'renderer failures roll back atomically' test_renderer_failure_rolls_back_target
run_test 'NSCF conversion rewrites atomically' test_nscf_conversion_rewrite_is_atomic
run_test 'NSCF renderer failures roll back atomically' test_nscf_conversion_renderer_failure_rolls_back
run_test 'bands.x workflow rewrites atomically' test_bandsx_workflow_rewrite_is_atomic
run_test 'bands.x workflow renderer failures roll back atomically' test_bandsx_workflow_renderer_failure_rolls_back
run_test 'bands.x workflow concurrent rewrites are atomic' test_bandsx_workflow_concurrent_rewrites_are_atomic
run_test 'PDOS workflow rewrites atomically' test_pdos_workflow_rewrite_is_atomic
run_test 'PDOS workflow renderer failures roll back atomically' test_pdos_workflow_renderer_failure_rolls_back
run_test 'PDOS workflow concurrent rewrites are atomic' test_pdos_workflow_concurrent_rewrites_are_atomic
run_test 'PDOS batch workflow rewrites atomically' test_pdos_batch_workflow_rewrite_is_atomic
run_test 'PDOS batch workflow renderer failures roll back atomically' test_pdos_batch_workflow_renderer_failure_rolls_back
run_test 'PDOS batch workflow concurrent rewrites are atomic' test_pdos_batch_workflow_concurrent_rewrites_are_atomic
run_test 'PD04 workflow rewrites atomically' test_pd04_workflow_rewrite_is_atomic
run_test 'PD04 workflow renderer failures roll back atomically' test_pd04_workflow_renderer_failure_rolls_back
run_test 'PD04 workflow concurrent rewrites are atomic' test_pd04_workflow_concurrent_rewrites_are_atomic
run_test 'scf2nscf workflow rewrites atomically' test_scf2nscf_workflow_rewrite_is_atomic
run_test 'scf2nscf workflow renderer failures roll back atomically' test_scf2nscf_workflow_renderer_failure_rolls_back
run_test 'scf2nscf workflow concurrent rewrites are atomic' test_scf2nscf_workflow_concurrent_rewrites_are_atomic
run_test 'scf2nscf accepts decimal electron counts' test_scf2nscf_accepts_decimal_electron_count
run_test 'scf2nscf renderer removes uppercase smearing settings' test_scf2nscf_renderer_removes_uppercase_smearing_settings
run_test 'scf2nscf chooses tetrahedra after comment replacement' test_scf2nscf_selects_tetrahedra_after_inline_comment_replacement
finish_tests
