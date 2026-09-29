#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"

source_qbox

write_stage_command() {
    local target="$1"
    cat >"$target" <<'EOF_COMMAND'
#!/usr/bin/env bash
printf 'cwd=%s\n' "$PWD"
printf 'arg=<%s>\n' "$1"
exit "${QBOX_MOCK_EXIT:-0}"
EOF_COMMAND
    chmod +x "$target"
}

test_stage_runner_success_preserves_workdir_callback_and_argv() {
    local sandbox status_value='' callback_log
    sandbox="$(new_sandbox)" || return 1
    mkdir -p "$sandbox/work dir/bin"
    write_stage_command "$sandbox/work dir/bin/stage-command"
    callback_log="$sandbox/callback.log"
    stage_success() {
        printf '<%s>\n' "$@" >"$callback_log"
        grep -q '^arg=<argument with spaces>$' "$sandbox/work dir/stage.log"
    }

    qe_run_stage status_value "$sandbox/work dir" stage.log stage_success \
        'callback argument' second -- \
        "$sandbox/work dir/bin/stage-command" 'argument with spaces' >/dev/null || return 1

    assert_eq success "$status_value" 'successful stage did not set success status' || return 1
    assert_contains "$(cat "$sandbox/work dir/stage.log")" "cwd=$sandbox/work dir" || return 1
    assert_file_equals <(printf '<callback argument>\n<second>\n') "$callback_log" \
        'success callback arguments were not preserved'
}

test_stage_runner_predicate_failure_sets_failed() {
    local sandbox status_value='' rc
    sandbox="$(new_sandbox)" || return 1
    mkdir -p "$sandbox/bin"
    write_stage_command "$sandbox/bin/stage-command"
    stage_failure() { return 1; }

    qe_run_stage status_value "$sandbox" stage.log stage_failure -- \
        "$sandbox/bin/stage-command" ok >/dev/null
    rc=$?
    assert_eq 1 "$rc" 'predicate failure did not return one' || return 1
    assert_eq failed "$status_value" 'predicate failure did not set failed status'
}

test_stage_runner_sets_common_status_variable_name() {
    local sandbox status=''
    sandbox="$(new_sandbox)" || return 1
    mkdir -p "$sandbox/bin"
    write_stage_command "$sandbox/bin/stage-command"
    stage_success() { return 0; }

    qe_run_stage status "$sandbox" stage.log stage_success -- \
        "$sandbox/bin/stage-command" ok >/dev/null || return 1
    assert_eq success "$status" 'runner-local state shadowed the requested output variable'
}

test_stage_runner_rejects_every_reserved_internal_name() {
    local sandbox name value rc
    sandbox="$(new_sandbox)" || return 1
    stage_success() { return 0; }

    for name in \
        _qe_stage_result_name \
        _qe_stage_workdir \
        _qe_stage_log_file \
        _qe_stage_success_fn \
        _qe_stage_exit_status \
        _qe_stage_found_separator \
        _qe_stage_success_args \
        _qe_stage_command_args \
        _qe_stage_future_internal
    do
        printf -v "$name" '%s' caller-value
        qe_run_stage "$name" "$sandbox" stage.log stage_success -- touch "$sandbox/ran" >/dev/null 2>&1
        rc=$?
        printf -v value '%s' "${!name}"
        assert_eq 2 "$rc" "reserved output name '$name' did not return two" || return 1
        assert_eq caller-value "$value" "reserved output name '$name' changed caller state" || return 1
        [ ! -e "$sandbox/ran" ] || {
            fail "reserved output name '$name' executed the command"
            return 1
        }
    done
}

test_stage_runner_rejects_readonly_output_after_success() {
    local sandbox rc
    local -r readonly_success_status=unchanged
    sandbox="$(new_sandbox)" || return 1
    stage_success() { return 0; }

    qe_run_stage readonly_success_status "$sandbox" stage.log stage_success -- true >/dev/null 2>&1
    rc=$?
    assert_eq 2 "$rc" 'readonly output after successful stage did not return two' || return 1
    assert_eq unchanged "$readonly_success_status" 'readonly success output unexpectedly changed'
}

test_stage_runner_rejects_readonly_output_after_failure() {
    local sandbox rc
    local -r readonly_failed_status=unchanged
    sandbox="$(new_sandbox)" || return 1
    stage_success() { return 0; }

    qe_run_stage readonly_failed_status "$sandbox" stage.log stage_success -- false >/dev/null 2>&1
    rc=$?
    assert_eq 2 "$rc" 'readonly output after failed stage did not return two' || return 1
    assert_eq unchanged "$readonly_failed_status" 'readonly failure output unexpectedly changed'
}

test_stage_runner_preserves_command_failure_through_tee() {
    local sandbox status_value='' rc
    sandbox="$(new_sandbox)" || return 1
    mkdir -p "$sandbox/bin"
    write_stage_command "$sandbox/bin/stage-command"
    stage_success() { return 0; }

    QBOX_MOCK_EXIT=23 qe_run_stage status_value "$sandbox" stage.log stage_success -- \
        "$sandbox/bin/stage-command" ok >/dev/null
    rc=$?
    assert_eq 1 "$rc" 'failed command was hidden by tee' || return 1
    assert_eq failed "$status_value" 'failed command did not set failed status'
}

test_stage_runner_rejects_invalid_contract_without_execution() {
    local sandbox status_value='' rc
    sandbox="$(new_sandbox)" || return 1
    stage_success() { return 0; }

    qe_run_stage 'bad-name' "$sandbox" stage.log stage_success -- touch "$sandbox/ran"
    rc=$?
    assert_eq 2 "$rc" 'invalid output variable did not return two' || return 1
    [ ! -e "$sandbox/ran" ] || return 1

    qe_run_stage status_value "$sandbox" stage.log stage_success touch "$sandbox/ran"
    rc=$?
    assert_eq 2 "$rc" 'missing separator did not return two' || return 1
    [ ! -e "$sandbox/ran" ] || return 1

    qe_run_stage status_value "$sandbox" stage.log stage_success --
    rc=$?
    assert_eq 2 "$rc" 'missing command did not return two' || return 1
    [ ! -e "$sandbox/ran" ]
}

test_shared_recalculation_prompt_contract() {
    local sandbox output observed_file
    sandbox="$(new_sandbox)" || return 1
    observed_file="$sandbox/prompt"
    qe_prompt_yes_no() {
        local output_var="$1"
        printf '%s|%s|%s\n' "$2" "$3" "$4" >"$observed_file"
        printf -v "$output_var" '%s' yes
    }

    output="$(qe_prompt_recalculate_completed 0 'unused question')" || return 1
    assert_eq no "$output" 'incomplete stage should not ask to recalculate' || return 1
    output="$(qe_prompt_recalculate_completed 1 'exact question')" || return 1
    assert_eq yes "$output" 'completed stage did not return prompt answer' || return 1
    assert_eq 'exact question|否，跳过已经成功完成的步骤|是，全部重新计算' "$(cat "$observed_file")"
}

write_qe_command_mocks() {
    local bin="$1"
    mkdir -p "$bin"
    cat >"$bin/pw.x" <<'EOF_PW'
#!/usr/bin/env bash
input=''
while [ "$#" -gt 0 ]; do
    if [ "$1" = -in ]; then input="${2-}"; shift 2; else shift; fi
done
printf 'PW input <%s>\n' "$input"
if [ -n "${QBOX_MOCK_FAIL_INPUT:-}" ] && [ "${input##*/}" = "$QBOX_MOCK_FAIL_INPUT" ]; then exit 17; fi
printf 'JOB DONE.\n'
EOF_PW
    cat >"$bin/bands.x" <<'EOF_BANDS'
#!/usr/bin/env bash
printf 'BANDS input <%s>\n' "${2-}"
printf 'JOB DONE.\n'
touch bands.dat.gnu
EOF_BANDS
cat >"$bin/projwfc.x" <<'EOF_PROJWFC'
#!/usr/bin/env bash
printf 'PROJWFC input <%s>\n' "${2-}"
if [ "${QBOX_MOCK_FAIL_PROJWFC:-0}" = 1 ]; then exit 19; fi
if [ "${2##*/}" = ldos.in ]; then touch sample.pdos.ldos_boxes; fi
printf 'JOB DONE.\n'
EOF_PROJWFC
    chmod +x "$bin/pw.x" "$bin/bands.x" "$bin/projwfc.x"
}

write_optical_command_mocks() {
    local bin="$1"
    mkdir -p "$bin"
    cat >"$bin/pw.x" <<'EOF_OPTICAL_PW'
#!/usr/bin/env bash
input=''
while [ "$#" -gt 0 ]; do
    if [ "$1" = -in ]; then input="${2-}"; shift 2; else shift; fi
done
printf 'PW input <%s>\n' "$input"
if [ -n "${QBOX_MOCK_FAIL_INPUT:-}" ] && [ "${input##*/}" = "$QBOX_MOCK_FAIL_INPUT" ]; then exit 17; fi
case "$PWD/${input##*/}" in
    */Epsilon/*) mkdir -p tmp/sample.save ;;
    */Polar/*) printf 'POLARIZATION CALCULATION\n' ;;
esac
printf 'number of electrons = 8.00\n'
printf 'JOB DONE.\n'
EOF_OPTICAL_PW
    cat >"$bin/epsilon.x" <<'EOF_EPSILON'
#!/usr/bin/env bash
printf 'EPSILON input <%s>\n' "${2-}"
if [ "${QBOX_MOCK_FAIL_EPSILON:-0}" = 1 ]; then exit 21; fi
touch epsi_sample.dat epsr_sample.dat
printf 'JOB DONE.\n'
EOF_EPSILON
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/pw.x" "$bin/epsilon.x" "$bin/mpirun"
}

write_even_electron_ho_fixture() {
    local target="$1"
    cat >"$target" <<'EOF_HO'
&CONTROL
  calculation = 'scf'
  prefix = 'sample'
/
&SYSTEM
  ibrav = 0
  nat = 3
  ntyp = 2
/
ATOMIC_SPECIES
H 1.0 H.upf
O 16.0 O.upf
ATOMIC_POSITIONS angstrom
O 0.0 0.0 0.0
H 0.8 0.0 0.0
H -0.8 0.0 0.0
K_POINTS automatic
1 1 1 0 0 0
CELL_PARAMETERS angstrom
5.0 0.0 0.0
0.0 5.0 0.0
0.0 0.0 5.0
EOF_HO
}

configure_epsilon_workflow_doubles() {
    qe_prompt_calc_prefix() { printf '%s\n' sample; }
    qe_ask_recalculate_epsilon_completed() { printf '%s\n' "${QBOX_TEST_RECALC:-yes}"; }
    qe_estimate_nelec_from_pwin_file() { printf '%s\n' 8; }
    qe_epsilon_settings_menu() { return 0; }
    qe_recommend_pw_threads() { printf '%s\n' 2; }
    qe_estimate_atom_count() { printf '%s\n' 3; }
    qe_physical_cpu_cores() { printf '%s\n' 4; }
    qe_prompt_positive_int_default() { printf '%s\n' 2; }
    qe_prepare_epsilon_scf_input() { cp "$1" "$2"; }
    qe_prepare_epsilon_nscf_input() { cp "$1" "$2"; }
    qe_write_epsilon_input_file() { : >"$1"; }
    qe_ensure_runtime_for() { return 0; }
}

configure_polar_workflow_doubles() {
    qe_prompt_calc_prefix() { printf '%s\n' sample; }
    qe_estimate_nelec_from_pwin_file() { printf '%s\n' 8; }
    qe_ask_recalculate_polar_completed() { printf '%s\n' "${QBOX_TEST_RECALC:-yes}"; }
    qe_recommend_pw_threads() { printf '%s\n' 2; }
    qe_estimate_atom_count() { printf '%s\n' 3; }
    qe_physical_cpu_cores() { printf '%s\n' 4; }
    qe_prompt_positive_int_default() { printf '%s\n' 2; }
    qe_prepare_polar_input() { cp "$1" "$2"; }
    qe_ensure_runtime_for() { return 0; }
    qe_write_polarization_data() { return 0; }
}

configure_pdos_workflow_doubles() {
    qe_prompt_calc_prefix() { printf '%s\n' sample; }
    qe_ask_recalculate_completed() { printf '%s\n' "${QBOX_TEST_RECALC:-no}"; }
    qe_recommend_pw_threads() { printf '%s\n' 2; }
    qe_recommend_projwfc_threads() { printf '%s\n' 2; }
    qe_estimate_atom_count() { return 0; }
    qe_physical_cpu_cores() { printf '%s\n' 4; }
    qe_prompt_positive_int_default() { printf '%s\n' 2; }
    qe_prompt_energy_reference() { printf '%s\n' fermi; }
    qe_ensure_runtime_for() { return 0; }
    qe_pdos_input_matches_prefix() { return 0; }
    qe_output_success_for_prefix() { grep -q 'JOB DONE' "$1" 2>/dev/null; }
    qe_pdos_output_success() { grep -q 'JOB DONE' PDOS/pdos.out 2>/dev/null; }
    qe_pdos_clean_success() { [ -f PDOS/ATOM_PDOS/raw-pdos ]; }
    qe_pdos_sum_success() { [ -f PDOS/ATOM_PDOS/sample_tot.dat ]; }
    qe_pdos_plot_success() { [ -f "PDOS/ATOM_PDOS/${1}.png" ]; }
    qe_builtin_clean_pdos() { printf 'clean\n' >>../workflow-order.log; mkdir -p ATOM_PDOS; touch ATOM_PDOS/raw-pdos; }
    qe_builtin_sumdos() { printf 'sum\n' >>../../workflow-order.log; touch sample_tot.dat; }
    qe_builtin_plot_pdos() {
        local output_prefix=''
        printf 'plot\n' >>../../workflow-order.log
        while [ "$#" -gt 0 ]; do
            if [ "$1" = --output-prefix ]; then output_prefix="$2"; shift 2; else shift; fi
        done
        touch "${output_prefix}.png"
    }
}

configure_ldos_workflow_doubles() {
    qe_prompt_calc_prefix() { printf '%s\n' sample; }
    qe_ask_recalculate_ldos_completed() { printf '%s\n' "${QBOX_TEST_RECALC:-no}"; }
    qe_recommend_pw_threads() { printf '%s\n' 2; }
    qe_recommend_projwfc_threads() { printf '%s\n' 2; }
    qe_estimate_atom_count() { return 0; }
    qe_physical_cpu_cores() { printf '%s\n' 4; }
    qe_prompt_positive_int_default() { printf '%s\n' 2; }
    qe_prompt_energy_reference() { printf '%s\n' fermi; }
    qe_ensure_runtime_for() { return 0; }
    qe_pdos_input_matches_prefix() { return 0; }
    qe_output_success_for_prefix() { grep -q 'JOB DONE' "$1" 2>/dev/null; }
    qe_ldos_output_success() {
        grep -q 'JOB DONE' LDOS/ldos.out 2>/dev/null &&
            { [ -f LDOS/sample.pdos.ldos_boxes ] || [ -f LDOS/sample.pdos.ldos_boxes.dat ]; }
    }
    qe_ldos_plot_success() { [ -f "LDOS/${1}.pdos.ldos_boxes_${2}.png" ]; }
    qe_embedded_plot_ldos() {
        local output_prefix=''
        while [ "$#" -gt 0 ]; do
            if [ "$1" = --output-prefix ]; then output_prefix="$2"; shift 2; else shift; fi
        done
        touch "${output_prefix}.png"
    }
}

test_scf_workflow_preserves_command_and_summary() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_qe_command_mocks "$bin"
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/mpirun"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        qe_prompt_calc_prefix() { printf '%s\n' sample; }
        qe_ask_recalculate_scf_completed() { printf '%s\n' yes; }
        qe_recommend_pw_threads() { printf '%s\n' 4; }
        qe_estimate_atom_count() { printf '%s\n' 2; }
        qe_physical_cpu_cores() { printf '%s\n' 8; }
        qe_prompt_positive_int_default() { printf '%s\n' 4; }
        qe_ensure_runtime_for() { return 0; }
        qe_output_success_for_prefix() { qe_output_success "$1"; }
        run_qe_scf_calculation
    ) >"$sandbox/output" || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 开始 SCF 计算：mpirun -np 4 pw.x -in sample.scf.in 2>&1 | tee scf.out' || return 1
    assert_contains "$output" ' 1) mpirun -np 4 pw.x -in sample.scf.in 2>&1 | tee scf.out' || return 1
    assert_contains "$output" ' scf 是否计算成功：成功' || return 1
    assert_file_equals <(printf 'mpirun <-np> <4> <pw.x> <-in> <sample.scf.in>\n') "$sandbox/commands.log"
}

test_scf_workflow_preserves_preloaded_runtime_with_fallbacks_configured() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/preloaded/bin"
    write_qe_command_mocks "$bin"
    mv "$bin/pw.x" "$bin/pw-command"
    cat >"$bin/pw.x" <<'EOF_PRELOADED_PW'
#!/usr/bin/env bash
if [ "${1-}" = -version ]; then
    printf 'Program PWSCF v.7.5\n'
    exit 0
fi
printf '%s\n' "$0" >>"${QBOX_TEST_PW_EXECUTION_LOG:?}"
exec "${0%/*}/pw-command" "$@"
EOF_PRELOADED_PW
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/pw.x" "$bin/mpirun"
    mkdir -p "$sandbox/replacement/bin"
    cat >"$sandbox/replacement/bin/pw.x" <<'EOF_REPLACEMENT'
#!/usr/bin/env bash
exit 91
EOF_REPLACEMENT
    cp "$sandbox/replacement/bin/pw.x" "$sandbox/replacement/bin/mpirun"
    chmod +x "$sandbox/replacement/bin/pw.x" "$sandbox/replacement/bin/mpirun"
    cat >"$sandbox/qe-env.sh" <<'EOF_QE_ENV'
printf 'qe-env\n' >>"$QBOX_TEST_ENV_LOAD_LOG"
export PATH="$QBOX_TEST_REPLACEMENT_BIN:$PATH"
EOF_QE_ENV
    cat >"$sandbox/oneapi-env.sh" <<'EOF_ONEAPI_ENV'
printf 'oneapi-env\n' >>"$QBOX_TEST_ENV_LOAD_LOG"
export PATH="$QBOX_TEST_REPLACEMENT_BIN:$PATH"
EOF_ONEAPI_ENV
    write_even_electron_ho_fixture "$sandbox/sample.scf.in"
    : >"$sandbox/commands.log"
    : >"$sandbox/env-load.log"
    (
        cd "$sandbox" || exit 1
        local inherited_path="$bin:$PATH"
        export PATH="$inherited_path" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        export QBOX_TEST_PW_EXECUTION_LOG="$sandbox/pw-execution.log"
        export QBOX_TEST_ENV_LOAD_LOG="$sandbox/env-load.log"
        export QBOX_TEST_REPLACEMENT_BIN="$sandbox/replacement/bin"
        export QBOX_QE_ENV_SCRIPT="$sandbox/qe-env.sh"
        export QBOX_ONEAPI_ENV_SCRIPT="$sandbox/oneapi-env.sh"
        export QE_MODULE='qe/cpu/replacement'
        unset QBOX_MOCK_FAIL_INPUT QE_RUNTIME_VERSION
        module() {
            printf 'module <%s>\n' "$*" >>"$QBOX_TEST_ENV_LOAD_LOG"
            export PATH="$QBOX_TEST_REPLACEMENT_BIN:$PATH"
            return 1
        }
        qe_prompt_calc_prefix() { printf '%s\n' sample; }
        qe_ask_recalculate_scf_completed() { printf '%s\n' yes; }
        qe_recommend_pw_threads() { printf '%s\n' 4; }
        qe_estimate_atom_count() { printf '%s\n' 3; }
        qe_physical_cpu_cores() { printf '%s\n' 8; }
        qe_prompt_positive_int_default() { printf '%s\n' 4; }

        run_qe_scf_calculation || exit 1
        assert_eq "$inherited_path" "$PATH" 'SCF runtime setup changed the inherited PATH' || exit 1
        assert_eq "$bin/pw.x" "$(command -v pw.x)" 'SCF replaced the preloaded pw.x' || exit 1
        assert_eq "$bin/mpirun" "$(command -v mpirun)" 'SCF replaced the preloaded mpirun' || exit 1
        assert_eq 7.5 "${QE_RUNTIME_VERSION:-}" 'SCF did not validate the preloaded QE version'
    ) >"$sandbox/output" 2>&1 || {
        cat "$sandbox/output" >&2
        return 1
    }
    output="$(cat "$sandbox/output")"
    assert_file_equals /dev/null "$sandbox/env-load.log" \
        'SCF loaded a configured environment script or called module despite a ready runtime' || return 1
    assert_file_equals <(printf '%s\n' "$bin/pw.x") "$sandbox/pw-execution.log" \
        'SCF did not execute the preloaded pw.x exactly once' || return 1
    assert_file_equals <(printf 'mpirun <-np> <4> <pw.x> <-in> <sample.scf.in>\n') "$sandbox/commands.log" \
        'SCF did not use the preloaded mpirun for its calculation' || return 1
    assert_contains "$(cat "$sandbox/scf.out")" 'JOB DONE.' || return 1
    assert_contains "$output" ' scf 是否计算成功：成功'
}

test_scf_workflow_preserves_skip_message_and_command() {
    local sandbox output
    sandbox="$(new_sandbox)" || return 1
    : >"$sandbox/sample.scf.in"
    (
        cd "$sandbox" || exit 1
        qe_prompt_calc_prefix() { printf '%s\n' sample; }
        qe_ask_recalculate_scf_completed() { printf '%s\n' no; }
        qe_output_success_for_prefix() { return 0; }
        run_qe_scf_calculation
    ) >"$sandbox/output" || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 跳过 SCF 计算：已有成功的 scf.out。' || return 1
    assert_contains "$output" ' 1) 跳过：已有成功的 scf.out 和 tmp/sample.save' || return 1
    assert_contains "$output" ' scf 是否计算成功：跳过（已有成功结果）'
}

test_scf_workflow_propagates_stage_contract_error() {
    local sandbox rc
    sandbox="$(new_sandbox)" || return 1
    : >"$sandbox/sample.scf.in"
    (
        cd "$sandbox" || exit 1
        qe_prompt_calc_prefix() { printf '%s\n' sample; }
        qe_ask_recalculate_scf_completed() { printf '%s\n' yes; }
        qe_recommend_pw_threads() { printf '%s\n' 4; }
        qe_estimate_atom_count() { printf '%s\n' 2; }
        qe_physical_cpu_cores() { printf '%s\n' 8; }
        qe_prompt_positive_int_default() { printf '%s\n' 4; }
        qe_ensure_runtime_for() { return 0; }
        qe_run_stage() { printf 'stage\n' >>"$sandbox/stages"; return 2; }
        run_qe_scf_calculation
    ) >"$sandbox/output"
    rc=$?
    assert_eq 2 "$rc" 'standalone SCF swallowed stage contract error' || return 1
    assert_file_equals <(printf 'stage\n') "$sandbox/stages" \
        'standalone SCF did not stop at its contract error'
}

assert_band_stage_contract_error_propagates() {
    local fail_stage="$1" sandbox rc actual_count
    sandbox="$(new_sandbox)" || return 1
    mkdir -p "$sandbox/BAND"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/BAND/sample.bands.in"
    : >"$sandbox/BAND/bands.in"
    : >"$sandbox/BAND/bands.dat.gnu"
    (
        cd "$sandbox" || exit 1
        qe_prompt_calc_prefix() { printf '%s\n' sample; }
        qe_ensure_band_inputs() { return 0; }
        qe_ask_recalculate_band_completed() { printf '%s\n' yes; }
        qe_prompt_positive_int() { printf '%s\n' 3; }
        qe_ensure_runtime_for() { return 0; }
        qe_prompt_energy_reference() { printf '%s\n' fermi; }
        qe_embedded_plot_band() { touch "$sandbox/plotted"; }
        qe_run_stage() {
            local output_name="$1"
            printf 'stage\n' >>"$sandbox/stages"
            actual_count="$(wc -l <"$sandbox/stages")"
            if [ "$actual_count" -eq "$fail_stage" ]; then return 2; fi
            printf -v "$output_name" '%s' success
            return 0
        }
        run_qe_band_calculation
    ) >"$sandbox/output"
    rc=$?
    assert_eq 2 "$rc" "bands stage $fail_stage contract error was swallowed" || return 1
    actual_count="$(wc -l <"$sandbox/stages")"
    assert_eq "$fail_stage" "$actual_count" "bands continued after stage $fail_stage contract error" || return 1
    [ ! -e "$sandbox/plotted" ] || fail "bands plotted after stage $fail_stage contract error"
}

test_band_workflow_propagates_root_scf_contract_error() {
    assert_band_stage_contract_error_propagates 1
}

test_band_workflow_propagates_pw_bands_contract_error() {
    assert_band_stage_contract_error_propagates 2
}

test_band_workflow_propagates_bandsx_contract_error() {
    assert_band_stage_contract_error_propagates 3
}

test_band_workflow_preserves_commands_and_failure_short_circuit() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_qe_command_mocks "$bin"
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/mpirun"
    mkdir -p "$sandbox/BAND"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/BAND/sample.bands.in"
    : >"$sandbox/BAND/bands.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        export QBOX_MOCK_FAIL_INPUT='sample.bands.in'
        qe_prompt_calc_prefix() { printf '%s\n' sample; }
        qe_ensure_band_inputs() { return 0; }
        qe_ask_recalculate_band_completed() { printf '%s\n' yes; }
        qe_prompt_positive_int() { printf '%s\n' 3; }
        qe_ensure_runtime_for() { return 0; }
        qe_output_success_for_prefix() { qe_output_success "$1"; }
        qe_band_pw_output_success() { qe_output_success BAND/band.out; }
        qe_bandsx_output_success() { qe_output_success BAND/bands.out && [ -f BAND/bands.dat.gnu ]; }
        run_qe_band_calculation
    ) >"$sandbox/output"
    [ "$?" -ne 0 ] || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 开始 SCF 计算：mpirun -np 3 pw.x -in sample.scf.in 2>&1 | tee scf.out' || return 1
    assert_contains "$output" ' 开始 pw.x bands 计算：mpirun -np 3 pw.x -in BAND/sample.bands.in 2>&1 | tee BAND/band.out' || return 1
    assert_contains "$output" ' 跳过 bands.x 计算：pw.x bands 失败。' || return 1
    assert_contains "$output" ' pw-band 是否计算成功：失败' || return 1
    assert_contains "$output" ' bands 是否计算成功：失败' || return 1
    assert_file_equals <(printf 'mpirun <-np> <3> <pw.x> <-in> <sample.scf.in>\nmpirun <-np> <3> <pw.x> <-in> <BAND/sample.bands.in>\n') "$sandbox/commands.log" \
        'bands.x ran after pw-bands failure or band input argv changed'
}

test_band_workflow_scf_failure_prevents_both_downstream_commands() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_qe_command_mocks "$bin"
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/mpirun"
    mkdir -p "$sandbox/BAND"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/BAND/sample.bands.in"
    : >"$sandbox/BAND/bands.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        export QBOX_MOCK_FAIL_INPUT='sample.scf.in'
        qe_prompt_calc_prefix() { printf '%s\n' sample; }
        qe_ensure_band_inputs() { return 0; }
        qe_ask_recalculate_band_completed() { printf '%s\n' yes; }
        qe_prompt_positive_int() { printf '%s\n' 3; }
        qe_ensure_runtime_for() { return 0; }
        qe_output_success_for_prefix() { qe_output_success "$1"; }
        qe_band_pw_output_success() { qe_output_success BAND/band.out; }
        qe_bandsx_output_success() { qe_output_success BAND/bands.out && [ -f BAND/bands.dat.gnu ]; }
        run_qe_band_calculation
    ) >"$sandbox/output"
    [ "$?" -ne 0 ] || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 跳过 pw.x bands 计算：SCF 失败。' || return 1
    assert_contains "$output" ' 跳过 bands.x 计算：pw.x bands 失败。' || return 1
    assert_file_equals <(printf 'mpirun <-np> <3> <pw.x> <-in> <sample.scf.in>\n') "$sandbox/commands.log" \
        'SCF failure did not prevent both downstream band commands'
}

test_band_workflow_preserves_three_stage_success_summary() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_qe_command_mocks "$bin"
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/mpirun"
    mkdir -p "$sandbox/BAND"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/BAND/sample.bands.in"
    : >"$sandbox/BAND/bands.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        unset QBOX_MOCK_FAIL_INPUT
        qe_prompt_calc_prefix() { printf '%s\n' sample; }
        qe_ensure_band_inputs() { return 0; }
        qe_ask_recalculate_band_completed() { printf '%s\n' yes; }
        qe_prompt_positive_int() { printf '%s\n' 3; }
        qe_ensure_runtime_for() { return 0; }
        qe_output_success_for_prefix() { qe_output_success "$1"; }
        qe_band_pw_output_success() { qe_output_success BAND/band.out; }
        qe_bandsx_output_success() { qe_output_success BAND/bands.out && [ -f BAND/bands.dat.gnu ]; }
        qe_prompt_energy_reference() { printf '%s\n' fermi; }
        qe_embedded_plot_band() { return 0; }
        run_qe_band_calculation
    ) >"$sandbox/output" || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 开始 bands.x 计算：mpirun -np 3 bands.x -in BAND/bands.in 2>&1 | tee BAND/bands.out' || return 1
    assert_contains "$output" ' scf 是否计算成功：成功' || return 1
    assert_contains "$output" ' pw-band 是否计算成功：成功' || return 1
    assert_contains "$output" ' bands 是否计算成功：成功' || return 1
    assert_file_equals <(printf 'mpirun <-np> <3> <pw.x> <-in> <sample.scf.in>\nmpirun <-np> <3> <pw.x> <-in> <BAND/sample.bands.in>\nmpirun <-np> <3> <bands.x> <-in> <BAND/bands.in>\n') "$sandbox/commands.log" \
        'band success stages did not use project-relative input paths'
}

test_band_workflow_preserves_all_skip_messages() {
    local sandbox output
    sandbox="$(new_sandbox)" || return 1
    mkdir -p "$sandbox/BAND"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/BAND/sample.bands.in"
    : >"$sandbox/BAND/bands.in"
    (
        cd "$sandbox" || exit 1
        qe_prompt_calc_prefix() { printf '%s\n' sample; }
        qe_ensure_band_inputs() { return 0; }
        qe_ask_recalculate_band_completed() { printf '%s\n' no; }
        qe_output_success_for_prefix() { return 0; }
        qe_band_pw_output_success() { return 0; }
        qe_bandsx_output_success() { return 0; }
        qe_embedded_plot_band() { return 0; }
        run_qe_band_calculation
    ) >"$sandbox/output" || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 跳过 SCF 计算：已有成功的 scf.out。' || return 1
    assert_contains "$output" ' 跳过 pw.x bands 计算：已有成功的 BAND/band.out。' || return 1
    assert_contains "$output" ' 跳过 bands.x 计算：已有成功的 BAND/bands.out 和 BAND/bands.dat.gnu。' || return 1
    assert_contains "$output" ' 1) 跳过：已有成功的 scf.out 和 tmp/sample.save' || return 1
    assert_contains "$output" ' 2) 跳过：已有成功的 BAND/band.out' || return 1
    assert_contains "$output" ' 3) 跳过：已有成功的 BAND/bands.out 和 BAND/bands.dat.gnu' || return 1
    assert_contains "$output" ' bands 是否计算成功：跳过（已有成功结果）'
}

test_pdos_existing_scf_no_recalculation_skips_scf() {
    local sandbox output
    sandbox="$(new_sandbox)" || return 1
    mkdir -p "$sandbox/PDOS/ATOM_PDOS"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/sample.nscf.in"
    : >"$sandbox/PDOS/pdos.in"
    printf 'JOB DONE.\n' >"$sandbox/scf.out"
    printf 'JOB DONE.\n' >"$sandbox/nscf.out"
    (
        cd "$sandbox" || exit 1
        configure_pdos_workflow_doubles
        qe_pdos_output_success() { return 0; }
        qe_pdos_clean_success() { return 0; }
        qe_pdos_sum_success() { return 0; }
        qe_pdos_plot_success() { return 0; }
        run_qe_pdos_calculation
    ) >"$sandbox/output" || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 跳过 SCF 计算：已有成功的 scf.out。' || return 1
    assert_contains "$output" ' 1) 跳过：已有成功的 scf.out 和 tmp/sample.save' || return 1
    assert_contains "$output" ' scf 是否计算成功：跳过（已有成功结果）'
}

test_pdos_nscf_failure_prevents_projwfc_and_postprocessing() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_qe_command_mocks "$bin"
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/mpirun"
    mkdir -p "$sandbox/PDOS"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/sample.nscf.in"
    : >"$sandbox/PDOS/pdos.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        export QBOX_MOCK_FAIL_INPUT='sample.nscf.in'
        configure_pdos_workflow_doubles
        qe_builtin_clean_pdos() { touch "$sandbox/clean-ran"; }
        qe_builtin_sumdos() { touch "$sandbox/sum-ran"; }
        qe_builtin_plot_pdos() { touch "$sandbox/plot-ran"; }
        run_qe_pdos_calculation
    ) >"$sandbox/output"
    [ "$?" -ne 0 ] || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 跳过 projwfc.x PDOS 计算：NSCF 失败。' || return 1
    assert_contains "$output" ' 跳过 cleanPDOS：projwfc.x PDOS 失败。' || return 1
    [ ! -e "$sandbox/clean-ran" ] || return 1
    [ ! -e "$sandbox/sum-ran" ] || return 1
    [ ! -e "$sandbox/plot-ran" ] || return 1
    assert_file_equals <(printf 'mpirun <-np> <2> <pw.x> <-in> <sample.scf.in>\nmpirun <-np> <2> <pw.x> <-in> <sample.nscf.in>\n') "$sandbox/commands.log" \
        'PDOS downstream commands ran after NSCF failure'
}

test_pdos_success_preserves_clean_sum_plot_order_commands_and_summary() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_qe_command_mocks "$bin"
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/mpirun"
    mkdir -p "$sandbox/PDOS"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/sample.nscf.in"
    : >"$sandbox/PDOS/pdos.in"
    : >"$sandbox/commands.log"
    : >"$sandbox/workflow-order.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        configure_pdos_workflow_doubles
        run_qe_pdos_calculation
    ) >"$sandbox/output" || return 1
    output="$(cat "$sandbox/output")"
    assert_file_equals <(printf 'clean\nsum\nplot\n') "$sandbox/workflow-order.log" \
        'PDOS clean, sumdos, and plot order changed' || return 1
    assert_contains "$output" ' 3) mpirun -np 2 projwfc.x -in PDOS/pdos.in 2>&1 | tee PDOS/pdos.out' || return 1
    assert_contains "$output" ' projwfc/pdos 是否计算成功：成功' || return 1
    assert_contains "$output" ' cleanPDOS 是否处理成功：成功' || return 1
    assert_contains "$output" ' sumdos 是否处理成功：成功' || return 1
    assert_contains "$output" ' plot-pdos 是否绘图成功：成功'
}

test_ldos_nscf_failure_prevents_projwfc_finalize_and_plot() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_qe_command_mocks "$bin"
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/mpirun"
    mkdir -p "$sandbox/LDOS"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/sample.nscf.in"
    : >"$sandbox/LDOS/ldos.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        export QBOX_MOCK_FAIL_INPUT='sample.nscf.in'
        configure_ldos_workflow_doubles
        qe_finalize_ldos_boxes_dat() { touch "$sandbox/finalize-ran"; }
        qe_embedded_plot_ldos() { touch "$sandbox/plot-ran"; }
        run_qe_ldos_calculation
    ) >"$sandbox/output"
    [ "$?" -ne 0 ] || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 跳过 projwfc.x LDOS 计算：NSCF 失败。' || return 1
    assert_contains "$output" ' 跳过 LDOS 数据重命名：projwfc.x LDOS 失败。' || return 1
    [ ! -e "$sandbox/finalize-ran" ] || return 1
    [ ! -e "$sandbox/plot-ran" ] || return 1
    assert_file_equals <(printf 'mpirun <-np> <2> <pw.x> <-in> <sample.scf.in>\nmpirun <-np> <2> <pw.x> <-in> <sample.nscf.in>\n') "$sandbox/commands.log" \
        'LDOS downstream commands ran after NSCF failure'
}

test_ldos_success_preserves_commands_finalize_plot_and_summary() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_qe_command_mocks "$bin"
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/mpirun"
    mkdir -p "$sandbox/LDOS"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/sample.nscf.in"
    : >"$sandbox/LDOS/ldos.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        configure_ldos_workflow_doubles
        run_qe_ldos_calculation
    ) >"$sandbox/output" || return 1
    output="$(cat "$sandbox/output")"
    [ -f "$sandbox/LDOS/sample.pdos.ldos_boxes.dat" ] || return 1
    [ -f "$sandbox/LDOS/sample.pdos.ldos_boxes_fermi.png" ] || return 1
    assert_contains "$output" ' 3) cd LDOS && mpirun -np 2 projwfc.x -in ldos.in 2>&1 | tee ldos.out' || return 1
    assert_contains "$output" ' projwfc/ldos 是否计算成功：成功' || return 1
    assert_contains "$output" ' ldos boxes 是否整理成功：成功' || return 1
    assert_contains "$output" ' plot-ldos 是否绘图成功：成功'
}

test_epsilon_preserves_success_order_commands_and_summary() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_optical_command_mocks "$bin"
    write_even_electron_ho_fixture "$sandbox/sample.scf.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        configure_epsilon_workflow_doubles
        run_qe_epsilon_calculation
    ) >"$sandbox/output" || return 1
    output="$(cat "$sandbox/output")"
    assert_file_equals <(printf 'mpirun <-np> <2> <pw.x> <-in> <sample.epsilon.scf.in>\nmpirun <-np> <2> <pw.x> <-in> <sample.epsilon.nscf.in>\nmpirun <-np> <2> <epsilon.x> <-in> <epsilon.in>\n') "$sandbox/commands.log" \
        'epsilon stages did not preserve SCF, NSCF, epsilon.x order' || return 1
    assert_contains "$output" ' 1) cd Epsilon && mpirun -np 2 pw.x -in sample.epsilon.scf.in 2>&1 | tee scf.out' || return 1
    assert_contains "$output" ' 2) cd Epsilon && mpirun -np 2 pw.x -in sample.epsilon.nscf.in 2>&1 | tee nscf.out' || return 1
    assert_contains "$output" ' 3) cd Epsilon && mpirun -np 2 epsilon.x -in epsilon.in 2>&1 | tee epsilon.out' || return 1
    assert_contains "$output" ' optical scf 是否计算成功：成功' || return 1
    assert_contains "$output" ' optical nscf 是否计算成功：成功' || return 1
    assert_contains "$output" ' epsilon.x 是否计算成功：成功'
}

test_epsilon_scf_failure_prevents_nscf_and_epsilon() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_optical_command_mocks "$bin"
    write_even_electron_ho_fixture "$sandbox/sample.scf.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        export QBOX_MOCK_FAIL_INPUT='sample.epsilon.scf.in'
        configure_epsilon_workflow_doubles
        run_qe_epsilon_calculation
    ) >"$sandbox/output"
    [ "$?" -ne 0 ] || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 跳过 optical NSCF：SCF 失败。' || return 1
    assert_contains "$output" ' 跳过 epsilon.x：NSCF 失败。' || return 1
    assert_file_equals <(printf 'mpirun <-np> <2> <pw.x> <-in> <sample.epsilon.scf.in>\n') "$sandbox/commands.log" \
        'epsilon downstream commands ran after optical SCF failure'
}

test_epsilon_successful_stages_skip_without_recalculation() {
    local sandbox output
    sandbox="$(new_sandbox)" || return 1
    write_even_electron_ho_fixture "$sandbox/sample.scf.in"
    mkdir -p "$sandbox/Epsilon"
    (
        cd "$sandbox" || exit 1
        export QBOX_TEST_RECALC=no
        configure_epsilon_workflow_doubles
        qe_epsilon_scf_success() { return 0; }
        qe_epsilon_nscf_success() { return 0; }
        qe_epsilon_output_success() { return 0; }
        run_qe_epsilon_calculation
    ) >"$sandbox/output" || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 跳过 optical SCF：已有成功的 Epsilon/scf.out。' || return 1
    assert_contains "$output" ' 跳过 optical NSCF：已有成功的 Epsilon/nscf.out。' || return 1
    assert_contains "$output" ' 跳过 epsilon.x：已有成功的 Epsilon/epsilon.out 和 epsr/epsi 数据。' || return 1
    assert_contains "$output" ' epsilon.x 是否计算成功：跳过（已有成功结果）'
}

test_polar_preserves_axis_order_headings_commands_and_summary() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_optical_command_mocks "$bin"
    write_even_electron_ho_fixture "$sandbox/sample.scf.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        configure_polar_workflow_doubles
        run_qe_polar_calculation
    ) >"$sandbox/output" || return 1
    output="$(cat "$sandbox/output")"
    assert_file_equals <(printf 'mpirun <-np> <2> <pw.x> <-in> <sample.scf.in>\nmpirun <-np> <2> <pw.x> <-in> <sample.polar-x.nscf.in>\nmpirun <-np> <2> <pw.x> <-in> <sample.polar-y.nscf.in>\nmpirun <-np> <2> <pw.x> <-in> <sample.polar-z.nscf.in>\n') "$sandbox/commands.log" \
        'polar stages did not preserve SCF, x, y, z order' || return 1
    assert_contains "$output" ' 2) cd Polar && mpirun -np 2 pw.x -in sample.polar-x.nscf.in 2>&1 | tee polar-x.out' || return 1
    assert_contains "$output" ' x 方向极化是否计算成功：成功' || return 1
    assert_contains "$output" ' y 方向极化是否计算成功：成功' || return 1
    assert_contains "$output" ' z 方向极化是否计算成功：成功' || return 1
    assert_contains "$output" ' x 方向：' || return 1
    assert_contains "$output" ' y 方向：' || return 1
    assert_contains "$output" ' z 方向：'
}

test_polar_axis_failure_keeps_other_axes_and_fails_result() {
    local sandbox bin output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_optical_command_mocks "$bin"
    write_even_electron_ho_fixture "$sandbox/sample.scf.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        export QBOX_MOCK_FAIL_INPUT='sample.polar-y.nscf.in'
        configure_polar_workflow_doubles
        run_qe_polar_calculation
    ) >"$sandbox/output"
    [ "$?" -ne 0 ] || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' x 方向极化是否计算成功：成功' || return 1
    assert_contains "$output" ' y 方向极化是否计算成功：失败' || return 1
    assert_contains "$output" ' z 方向极化是否计算成功：成功' || return 1
    assert_file_equals <(printf 'mpirun <-np> <2> <pw.x> <-in> <sample.scf.in>\nmpirun <-np> <2> <pw.x> <-in> <sample.polar-x.nscf.in>\nmpirun <-np> <2> <pw.x> <-in> <sample.polar-y.nscf.in>\nmpirun <-np> <2> <pw.x> <-in> <sample.polar-z.nscf.in>\n') "$sandbox/commands.log" \
        'polar axis failure changed execution of the other axes'
}

test_epsilon_runner_contract_error_stops_every_downstream_stage() {
    local sandbox fail_status rc expected observed status
    for fail_status in scf_status nscf_status epsilon_status; do
        sandbox="$(new_sandbox)" || return 1
        write_even_electron_ho_fixture "$sandbox/sample.scf.in"
        : >"$sandbox/stages.log"
        (
            cd "$sandbox" || exit 1
            configure_epsilon_workflow_doubles
            qe_run_stage() {
                local result_name="$1"
                printf '%s\n' "$result_name" >>"$sandbox/stages.log"
                if [ "$result_name" = "$fail_status" ]; then return 2; fi
                printf -v "$result_name" '%s' success
                return 0
            }
            run_qe_epsilon_calculation
        ) >"$sandbox/output" 2>&1
        rc=$?
        assert_eq 2 "$rc" "epsilon runner contract error at $fail_status was not propagated" || return 1
        expected=''
        for status in scf_status nscf_status epsilon_status; do
            expected="${expected}${status}"$'\n'
            [ "$status" = "$fail_status" ] && break
        done
        observed="$(cat "$sandbox/stages.log")"$'\n'
        assert_eq "$expected" "$observed" "epsilon continued after runner contract error at $fail_status" || return 1
    done
}

test_polar_runner_contract_error_stops_every_downstream_stage() {
    local sandbox fail_status rc expected observed status
    for fail_status in scf_status x_status y_status z_status; do
        sandbox="$(new_sandbox)" || return 1
        write_even_electron_ho_fixture "$sandbox/sample.scf.in"
        : >"$sandbox/stages.log"
        (
            cd "$sandbox" || exit 1
            configure_polar_workflow_doubles
            qe_run_stage() {
                local result_name="$1"
                printf '%s\n' "$result_name" >>"$sandbox/stages.log"
                if [ "$result_name" = "$fail_status" ]; then return 2; fi
                printf -v "$result_name" '%s' success
                return 0
            }
            run_qe_polar_calculation
        ) >"$sandbox/output" 2>&1
        rc=$?
        assert_eq 2 "$rc" "polar runner contract error at $fail_status was not propagated" || return 1
        expected=''
        for status in scf_status x_status y_status z_status; do
            expected="${expected}${status}"$'\n'
            [ "$status" = "$fail_status" ] && break
        done
        observed="$(cat "$sandbox/stages.log")"$'\n'
        assert_eq "$expected" "$observed" "polar continued after runner contract error at $fail_status" || return 1
    done
}

test_pdos_recalculation_eof_runs_no_command() {
    local sandbox rc
    sandbox="$(new_sandbox)" || return 1
    mkdir -p "$sandbox/PDOS"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/sample.nscf.in"
    : >"$sandbox/PDOS/pdos.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        qe_prompt_calc_prefix() { printf '%s\n' sample; }
        qe_output_success_for_prefix() { return 0; }
        qe_pdos_output_success() { return 0; }
        qe_pdos_clean_success() { return 0; }
        qe_pdos_sum_success() { return 0; }
        qe_prompt_yes_no() { return 1; }
        qe_ensure_runtime_for() { printf 'runtime\n' >>"$sandbox/commands.log"; }
        run_qe_pdos_calculation
    ) >"$sandbox/output" 2>&1
    rc=$?
    [ "$rc" -ne 0 ] || return 1
    assert_eq '' "$(cat "$sandbox/commands.log")" 'PDOS prompt EOF executed a command'
}

test_pdos_runner_contract_error_stops_every_downstream_stage() {
    local sandbox fail_status rc observed expected status
    for fail_status in scf_status nscf_status pdos_status clean_status sum_status plot_status; do
        sandbox="$(new_sandbox)" || return 1
        mkdir -p "$sandbox/PDOS"
        : >"$sandbox/sample.scf.in"
        : >"$sandbox/sample.nscf.in"
        : >"$sandbox/PDOS/pdos.in"
        : >"$sandbox/stages.log"
        (
            cd "$sandbox" || exit 1
            configure_pdos_workflow_doubles
            qe_run_stage() {
                local result_name="$1"
                printf '%s\n' "$result_name" >>"$sandbox/stages.log"
                if [ "$result_name" = "$fail_status" ]; then return 2; fi
                printf -v "$result_name" '%s' success
                return 0
            }
            run_qe_pdos_calculation
        ) >"$sandbox/output" 2>&1
        rc=$?
        assert_eq 2 "$rc" "PDOS runner contract error at $fail_status was not propagated" || return 1
        expected=''
        for status in scf_status nscf_status pdos_status clean_status sum_status plot_status; do
            expected="${expected}${status}"$'\n'
            [ "$status" = "$fail_status" ] && break
        done
        observed="$(cat "$sandbox/stages.log")"$'\n'
        assert_eq "$expected" "$observed" "PDOS continued after runner contract error at $fail_status" || return 1
    done
}

test_ldos_runner_contract_error_stops_every_downstream_stage() {
    local sandbox fail_status rc observed expected status
    for fail_status in scf_status nscf_status ldos_status; do
        sandbox="$(new_sandbox)" || return 1
        mkdir -p "$sandbox/LDOS"
        : >"$sandbox/sample.scf.in"
        : >"$sandbox/sample.nscf.in"
        : >"$sandbox/LDOS/ldos.in"
        : >"$sandbox/stages.log"
        (
            cd "$sandbox" || exit 1
            configure_ldos_workflow_doubles
            qe_run_stage() {
                local result_name="$1"
                printf '%s\n' "$result_name" >>"$sandbox/stages.log"
                if [ "$result_name" = "$fail_status" ]; then return 2; fi
                printf -v "$result_name" '%s' success
                return 0
            }
            qe_finalize_ldos_boxes_dat() { touch "$sandbox/finalize-ran"; }
            qe_embedded_plot_ldos() { touch "$sandbox/plot-ran"; }
            run_qe_ldos_calculation
        ) >"$sandbox/output" 2>&1
        rc=$?
        assert_eq 2 "$rc" "LDOS runner contract error at $fail_status was not propagated" || return 1
        expected=''
        for status in scf_status nscf_status ldos_status; do
            expected="${expected}${status}"$'\n'
            [ "$status" = "$fail_status" ] && break
        done
        observed="$(cat "$sandbox/stages.log")"$'\n'
        assert_eq "$expected" "$observed" "LDOS continued after runner contract error at $fail_status" || return 1
        [ ! -e "$sandbox/finalize-ran" ] || return 1
        [ ! -e "$sandbox/plot-ran" ] || return 1
    done
}

test_pdos_batch_stage_executes_real_runner_path() {
    local sandbox bin
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_qe_command_mocks "$bin"
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/mpirun"
    : >"$sandbox/sample.scf.in"
    : >"$sandbox/sample.nscf.in"
    : >"$sandbox/commands.log"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        qe_ensure_runtime_for() { return 0; }
        qe_output_success_for_prefix() { grep -q 'JOB DONE' "$1" 2>/dev/null; }
        QE_PDOS_STAGE=scf QE_PDOS_PREFIX=sample QE_PDOS_NP=5 run_qe_pdos_batch_stage
    ) >"$sandbox/output" || return 1
    assert_file_equals <(printf 'mpirun <-np> <5> <pw.x> <-in> <sample.scf.in>\n') "$sandbox/commands.log" \
        'PDOS batch SCF did not execute through the real stage path' || return 1
    assert_contains "$(cat "$sandbox/scf.out")" 'JOB DONE.'
}

test_completed_ldos_missing_input_preserves_results_and_plotting() {
    local sandbox bin rc output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    write_qe_command_mocks "$bin"
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/mpirun"
    mkdir -p "$sandbox/LDOS" "$sandbox/tmp/sample.save"
    write_even_electron_ho_fixture "$sandbox/sample.scf.in"
    cp "$sandbox/sample.scf.in" "$sandbox/sample.nscf.in"
    printf 'JOB DONE.\n' >"$sandbox/scf.out"
    cat >"$sandbox/nscf.out" <<'EOF_NS_OUTPUT'
Writing output data file ./tmp/sample.save
FFT dimensions: ( 12, 12, 12 )
the Fermi energy is 1.0 ev
JOB DONE.
EOF_NS_OUTPUT
    printf 'JOB DONE.\n' >"$sandbox/LDOS/ldos.out"
    printf 'saved LDOS data\n' >"$sandbox/LDOS/sample.pdos.ldos_boxes.dat"
    : >"$sandbox/other.cif"
    : >"$sandbox/events.log"
    : >"$sandbox/commands.log"
    (
        # The production launcher does not enable nounset; the real input
        # generator has unset local values until it reads the reference output.
        set +u
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        fname1=other.cif
        prefix=other
        qe_prompt_calc_prefix() { printf '%s\n' sample; }
        qe_ask_recalculate_ldos_completed() { printf '%s\n' no; }
        qe_prompt_energy_reference() { printf '%s\n' fermi; }
        qe_ensure_runtime_for() { printf 'environment\n' >>"$sandbox/events.log"; return 1; }
        qe_report_compute_resources() { printf 'resources\n' >>"$sandbox/events.log"; }
        qe_prompt_positive_int_default() { printf 'prompt\n' >>"$sandbox/events.log"; printf '2\n'; }
        qe_embedded_plot_ldos() {
            printf '%s\n' "$1" >"$sandbox/plotted-data"
            touch LDOS/sample.pdos.ldos_boxes_fermi.png
        }
        qe_ldos_output_success sample || exit 1
        run_qe_ldos_calculation <<<0
    ) >"$sandbox/output" 2>&1
    rc=$?
    assert_file_equals /dev/null "$sandbox/commands.log" \
        'completed LDOS rebuilt a missing input and unexpectedly ran projwfc.x' || return 1
    assert_eq 0 "$rc" 'completed LDOS could not reuse its results without ldos.in' || return 1
    assert_file_equals /dev/null "$sandbox/events.log" \
        'completed LDOS requested runtime setup, resources or MPI input' || return 1
    [ ! -e "$sandbox/LDOS/ldos.in" ] || fail 'completed LDOS unnecessarily regenerated ldos.in' || return 1
    assert_file_equals <(printf 'saved LDOS data\n') "$sandbox/LDOS/sample.pdos.ldos_boxes.dat" || return 1
    assert_file_equals <(printf 'LDOS/sample.pdos.ldos_boxes.dat\n') "$sandbox/plotted-data" || return 1
    output="$(cat "$sandbox/output")"
    assert_contains "$output" ' 跳过 projwfc.x LDOS 计算：已有成功的 LDOS 输出。' || return 1
    assert_contains "$output" ' plot-ldos 是否绘图成功：成功'
}

configure_workflow_startup_case() {
    local workflow="$1" sandbox="$2"
    write_qe_command_mocks "$sandbox/bin"
    write_optical_command_mocks "$sandbox/bin"
    write_even_electron_ho_fixture "$sandbox/sample.scf.in"
    cp "$sandbox/sample.scf.in" "$sandbox/sample.nscf.in"
    mkdir -p "$sandbox/"{BAND,PDOS/ATOM_PDOS,LDOS,Epsilon,Polar,EM,UNFOLD}
    touch "$sandbox/BAND/sample.bands.in" "$sandbox/BAND/bands.in" \
        "$sandbox/PDOS/pdos.in" "$sandbox/LDOS/ldos.in" \
        "$sandbox/UNFOLD/sample.scf.in" "$sandbox/UNFOLD/sample.bands.in" "$sandbox/UNFOLD/unfold.in"
    printf 'sample\n' >"$sandbox/UNFOLD/unfold.prefix"
    export PATH="$sandbox/bin:$PATH" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
    export QBOX_TEST_RECALC=no QBOX_MOCK_FAIL_INPUT=sample.scf.in
    : >"$sandbox/commands.log"
    : >"$sandbox/events.log"
    case "$workflow" in
        pdos) configure_pdos_workflow_doubles ;;
        ldos) configure_ldos_workflow_doubles ;;
        epsilon)
            configure_epsilon_workflow_doubles
            export QBOX_MOCK_FAIL_INPUT=sample.epsilon.scf.in
            ;;
        polar) configure_polar_workflow_doubles ;;
        effective_mass)
            qe_detect_prefix_for_em() { printf '%s\n' sample; }
            qe_prepare_em_source_inputs() { return 0; }
            qe_prepare_em_inputs() { return 0; }
            ;;
    esac
    qe_prompt_calc_prefix() { printf '%s\n' sample; }
    qe_ask_recalculate_scf_completed() { printf '%s\n' no; }
    qe_ask_recalculate_band_completed() { printf '%s\n' no; }
    qe_ensure_band_inputs() { return 0; }
    qe_recommend_pw_threads() { printf '%s\n' 2; }
    qe_recommend_projwfc_threads() { printf '%s\n' 2; }
    qe_estimate_atom_count() { printf '%s\n' 3; }
    qe_physical_cpu_cores() { printf '%s\n' 4; }
    qe_ensure_runtime_for() {
        printf 'environment\n' >>"$sandbox/events.log"
        return "${QBOX_TEST_RUNTIME_STATUS:-0}"
    }
    qe_report_compute_resources() { printf 'resources\n' >>"$sandbox/events.log"; }
    qe_prompt_positive_int_default() {
        printf 'prompt\n' >>"$sandbox/events.log"
        printf '%s\n' 2
    }
    qe_prompt_positive_int() { qe_prompt_positive_int_default "$@"; }
}

assert_workflow_selects_environment_before_parallel_input() {
    local workflow="$1" prompt_count="$2" sandbox rc expected i
    sandbox="$(new_sandbox)" || return 1
    (
        configure_workflow_startup_case "$workflow" "$sandbox"
        cd "$sandbox" || exit 1
        "run_qe_${workflow}_calculation" <<<y
    ) >"$sandbox/output" 2>&1
    rc=$?
    assert_eq 1 "$rc" "$workflow did not reach its intentionally failing mock SCF" || return 1
    expected=$'environment\nresources\n'
    for ((i=0; i<prompt_count; i++)); do expected+=$'prompt\n'; done
    assert_file_equals <(printf '%s' "$expected") "$sandbox/events.log" \
        "$workflow did not select environment and report resources before MPI input" || return 1
    [ -s "$sandbox/commands.log" ] || fail "$workflow did not execute the mock calculation"
}

assert_workflow_runtime_cancellation_prevents_parallel_input() {
    local workflow="$1" sandbox rc
    sandbox="$(new_sandbox)" || return 1
    (
        configure_workflow_startup_case "$workflow" "$sandbox"
        export QBOX_TEST_RUNTIME_STATUS=1
        cd "$sandbox" || exit 1
        "run_qe_${workflow}_calculation" <<<y
    ) >"$sandbox/output" 2>&1
    rc=$?
    assert_eq 1 "$rc" "$workflow swallowed runtime selection cancellation" || return 1
    assert_file_equals <(printf 'environment\n') "$sandbox/events.log" \
        "$workflow asked for MPI input or sampled resources after runtime cancellation" || return 1
    assert_file_equals /dev/null "$sandbox/commands.log" \
        "$workflow executed a calculation after runtime cancellation"
}

assert_workflow_parallel_input_cancellation_stops_calculation() {
    local workflow="$1" sandbox rc
    sandbox="$(new_sandbox)" || return 1
    (
        configure_workflow_startup_case "$workflow" "$sandbox"
        qe_prompt_positive_int_default() {
            printf 'prompt\n' >>"$sandbox/events.log"
            return 1
        }
        cd "$sandbox" || exit 1
        "run_qe_${workflow}_calculation" <<<y
    ) >"$sandbox/output" 2>&1
    rc=$?
    assert_eq 1 "$rc" "$workflow swallowed cancellation of MPI input" || return 1
    assert_file_equals <(printf 'environment\nresources\nprompt\n') "$sandbox/events.log" \
        "$workflow kept prompting after MPI input was cancelled" || return 1
    assert_file_equals /dev/null "$sandbox/commands.log" \
        "$workflow executed a calculation after MPI input was cancelled"
}

assert_completed_workflow_skips_runtime_and_resources() {
    local workflow="$1" sandbox
    sandbox="$(new_sandbox)" || return 1
    (
        configure_workflow_startup_case "$workflow" "$sandbox"
        cd "$sandbox" || exit 1
        touch PDOS/ATOM_PDOS/raw-pdos PDOS/ATOM_PDOS/sample_tot.dat \
            LDOS/sample.pdos.ldos_boxes.dat
        qe_output_success_for_prefix() { return 0; }
        qe_band_pw_output_success() { return 0; }
        qe_bandsx_output_success() { return 0; }
        qe_pdos_output_success() { return 0; }
        qe_ldos_output_success() { return 0; }
        qe_epsilon_scf_success() { return 0; }
        qe_epsilon_nscf_success() { return 0; }
        qe_epsilon_output_success() { return 0; }
        qe_polar_output_success() { return 0; }
        "run_qe_${workflow}_calculation"
    ) >"$sandbox/output" 2>&1 || {
        cat "$sandbox/output" >&2
        return 1
    }
    assert_file_equals /dev/null "$sandbox/events.log" \
        "$workflow loaded an environment, sampled resources or asked MPI input when all calculations were skipped" || return 1
    assert_file_equals /dev/null "$sandbox/commands.log" \
        "$workflow ran an external calculation despite all results being complete"
}

run_test 'stage runner success preserves workdir callback and argv' test_stage_runner_success_preserves_workdir_callback_and_argv
run_test 'stage runner predicate failure sets failed' test_stage_runner_predicate_failure_sets_failed
run_test 'stage runner sets common status variable name' test_stage_runner_sets_common_status_variable_name
run_test 'stage runner rejects every reserved internal name' test_stage_runner_rejects_every_reserved_internal_name
run_test 'stage runner rejects readonly output after success' test_stage_runner_rejects_readonly_output_after_success
run_test 'stage runner rejects readonly output after failure' test_stage_runner_rejects_readonly_output_after_failure
run_test 'stage runner preserves command failure through tee' test_stage_runner_preserves_command_failure_through_tee
run_test 'stage runner rejects invalid contract without execution' test_stage_runner_rejects_invalid_contract_without_execution
run_test 'shared recalculation prompt contract' test_shared_recalculation_prompt_contract
run_test 'SCF workflow preserves command and summary' test_scf_workflow_preserves_command_and_summary
run_test 'SCF workflow preserves preloaded runtime with fallbacks configured' test_scf_workflow_preserves_preloaded_runtime_with_fallbacks_configured
run_test 'SCF workflow preserves skip message and command' test_scf_workflow_preserves_skip_message_and_command
run_test 'SCF workflow propagates stage contract error' test_scf_workflow_propagates_stage_contract_error
run_test 'band workflow preserves commands and failure short-circuit' test_band_workflow_preserves_commands_and_failure_short_circuit
run_test 'band workflow SCF failure prevents both downstream commands' test_band_workflow_scf_failure_prevents_both_downstream_commands
run_test 'band workflow preserves three-stage success summary' test_band_workflow_preserves_three_stage_success_summary
run_test 'band workflow preserves all skip messages' test_band_workflow_preserves_all_skip_messages
run_test 'band workflow propagates root SCF contract error' test_band_workflow_propagates_root_scf_contract_error
run_test 'band workflow propagates pw-bands contract error' test_band_workflow_propagates_pw_bands_contract_error
run_test 'band workflow propagates bands.x contract error' test_band_workflow_propagates_bandsx_contract_error
run_test 'PDOS existing SCF no recalculation skips SCF' test_pdos_existing_scf_no_recalculation_skips_scf
run_test 'PDOS NSCF failure prevents projwfc and postprocessing' test_pdos_nscf_failure_prevents_projwfc_and_postprocessing
run_test 'PDOS success preserves clean sum plot order commands and summary' test_pdos_success_preserves_clean_sum_plot_order_commands_and_summary
run_test 'LDOS NSCF failure prevents projwfc finalize and plot' test_ldos_nscf_failure_prevents_projwfc_finalize_and_plot
run_test 'LDOS success preserves commands finalize plot and summary' test_ldos_success_preserves_commands_finalize_plot_and_summary
run_test 'completed LDOS missing input preserves results and plotting' test_completed_ldos_missing_input_preserves_results_and_plotting
run_test 'epsilon preserves success order commands and summary' test_epsilon_preserves_success_order_commands_and_summary
run_test 'epsilon SCF failure prevents NSCF and epsilon.x' test_epsilon_scf_failure_prevents_nscf_and_epsilon
run_test 'epsilon successful stages skip without recalculation' test_epsilon_successful_stages_skip_without_recalculation
run_test 'polar preserves axis order headings commands and summary' test_polar_preserves_axis_order_headings_commands_and_summary
run_test 'polar axis failure keeps other axes and fails result' test_polar_axis_failure_keeps_other_axes_and_fails_result
run_test 'epsilon runner contract error stops every downstream stage' test_epsilon_runner_contract_error_stops_every_downstream_stage
run_test 'polar runner contract error stops every downstream stage' test_polar_runner_contract_error_stops_every_downstream_stage
run_test 'PDOS recalculation EOF runs no command' test_pdos_recalculation_eof_runs_no_command
run_test 'PDOS runner contract error stops every downstream stage' test_pdos_runner_contract_error_stops_every_downstream_stage
run_test 'LDOS runner contract error stops every downstream stage' test_ldos_runner_contract_error_stops_every_downstream_stage
run_test 'PDOS batch stage executes real runner path' test_pdos_batch_stage_executes_real_runner_path
for workflow_case in 'scf 1' 'band 2' 'pdos 3' 'ldos 3' 'epsilon 3' 'polar 4' 'effective_mass 2' 'unfold 2'; do
    read -r workflow_name workflow_prompt_count <<<"$workflow_case"
    run_test "$workflow_name selects environment before MPI input" \
        assert_workflow_selects_environment_before_parallel_input "$workflow_name" "$workflow_prompt_count"
    run_test "$workflow_name runtime cancellation prevents MPI input" \
        assert_workflow_runtime_cancellation_prevents_parallel_input "$workflow_name"
    run_test "$workflow_name MPI input cancellation stops calculation" \
        assert_workflow_parallel_input_cancellation_stops_calculation "$workflow_name"
done
for workflow_name in scf band pdos ldos epsilon polar; do
    run_test "$workflow_name complete results skip environment and resources" \
        assert_completed_workflow_skips_runtime_and_resources "$workflow_name"
done
finish_tests
