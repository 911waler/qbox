#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

test_choice_accepts_retry() {
    local result output output_file
    output_file="$(mktemp)" || return 1
    qe_read_choice result '1 2' ' 请输入 1 或 2。' >"$output_file" <<'INPUT'
x
2
INPUT
    output="$(cat "$output_file")"
    rm -f -- "$output_file"
    assert_eq 2 "$result" || return 1
    assert_contains "$output" ' 请输入 1 或 2。'
}

test_choice_eof_returns() {
    local sandbox output_file status
    sandbox="$(new_sandbox)" || return 1
    output_file="$sandbox/prompt.out"
    env -i PATH="$PATH" HOME="${HOME:-/tmp}" TMPDIR="${TMPDIR:-/tmp}" timeout 2 bash --noprofile --norc -c 'QBOX_TEST_MODE=1 source "$1"; qe_read_choice value "1 2" " 请输入 1 或 2。"' _ "$PROJECT_ROOT/qbox" </dev/null >"$output_file" 2>&1
    status=$?
    [ "$status" -ne 124 ] || fail 'EOF loop timed out'
    [ "$(wc -l <"$output_file")" -le 2 ] || fail 'EOF emitted repeated prompts'
}

test_yes_no_accepts_yes() {
    local result output_file output
    output_file="$(mktemp)" || return 1
    qe_prompt_yes_no result ' 是否继续？' '否' '是' >"$output_file" 2>&1 <<'INPUT'
2
INPUT
    output="$(cat "$output_file")"
    rm -f -- "$output_file"
    assert_eq yes "$result" || return 1
    assert_contains "$output" ' 是否继续？'
}

test_choice_timeout_eof_returns() {
    local status
    timeout 2 bash -c 'QBOX_TEST_MODE=1 source "$1"; QBOX_INPUT_MENU_TIMEOUT=1 qe_read_choice_with_timeout value 7' _ "$PROJECT_ROOT/qbox" </dev/null >/dev/null 2>&1
    status=$?
    [ "$status" -ne 124 ] || fail 'timed choice looped on EOF'
    [ "$status" -ne 0 ] || fail 'timed choice treated EOF as timeout default'
}

test_prompt_eof_returns() {
    local function_name status
    for function_name in qe_prompt_plot_data_scope qe_prompt_positive_int qe_prompt_energy_reference qe_prompt_band_precision_mode; do
        timeout 2 bash -c 'QBOX_TEST_MODE=1 source "$1"; "$2" "${@:3}"' _ "$PROJECT_ROOT/qbox" "$function_name" plot 17 </dev/null >/dev/null 2>&1
        status=$?
        [ "$status" -ne 124 ] || fail "$function_name looped on EOF"
        [ "$status" -ne 0 ] || fail "$function_name treated EOF as a value"
    done
    timeout 2 bash -c 'QBOX_TEST_MODE=1 source "$1"; qe_prompt_positive_int_default prompt 17' _ "$PROJECT_ROOT/qbox" </dev/null >/dev/null 2>&1
    status=$?
    [ "$status" -ne 124 ] || fail 'qe_prompt_positive_int_default looped on EOF'
    [ "$status" -ne 0 ] || fail 'qe_prompt_positive_int_default treated EOF as a default'
}

test_choice_timeout_uses_default() {
    local sandbox output_file output status
    sandbox="$(new_sandbox)" || return 1
    output_file="$sandbox/timeout.out"
    timeout 3 bash -c 'QBOX_TEST_MODE=1 source "$1"; QBOX_INPUT_MENU_TIMEOUT=1 qe_read_choice_with_timeout value 7; printf "value=%s\n" "$value"' _ "$PROJECT_ROOT/qbox" < <(sleep 2) >"$output_file" 2>&1
    status=$?
    output="$(cat "$output_file")"
    assert_eq 0 "$status" || return 1
    assert_contains "$output" 'value=7'
}

test_recalculate_retry_keeps_result_clean() {
    local sandbox output stderr_file stderr status
    sandbox="$(new_sandbox)" || return 1
    stderr_file="$sandbox/prompt.err"
    output="$(env -i PATH="$PATH" HOME="${HOME:-/tmp}" TMPDIR="${TMPDIR:-/tmp}" bash --noprofile --norc -c 'cd "$1"; QBOX_TEST_MODE=1 source "$2"; qe_output_success_for_prefix(){ return 0; }; result="$(qe_ask_recalculate_scf_completed sample <<"INPUT"
x
2
INPUT
)"; printf "%s\n" "$result"' _ "$sandbox" "$PROJECT_ROOT/qbox" 2>"$stderr_file")"
    status=$?
    stderr="$(cat "$stderr_file")"
    assert_eq 0 "$status" || return 1
    assert_eq yes "$output" || return 1
    assert_contains "$stderr" ' 请输入 1 或 2。'
}

test_scf_workflow_cancels_on_recalculate_eof() {
    local sandbox marker status reached
    sandbox="$(new_sandbox)" || return 1
    marker="$sandbox/continued"
    printf '&CONTROL\n calculation = '\''scf'\'',\n/\n' >"$sandbox/sample.scf.in"
    env -i PATH="$PATH" HOME="${HOME:-/tmp}" TMPDIR="${TMPDIR:-/tmp}" bash --noprofile --norc -c '
        cd "$1" || exit 1
        QBOX_TEST_MODE=1 source "$2"
        marker="$3"
        qe_output_success_for_prefix(){ return 0; }
        qe_recommend_pw_threads(){ printf "thread-setup\n" >>"$marker"; echo 1; }
        qe_estimate_atom_count(){ echo ""; }
        qe_physical_cpu_cores(){ echo 1; }
        qe_prompt_positive_int_default(){ echo 1; }
        qe_ensure_runtime_for(){ printf "runtime-setup\n" >>"$marker"; return 1; }
        run_qe_scf_calculation
    ' _ "$sandbox" "$PROJECT_ROOT/qbox" "$marker" <<'INPUT' >/dev/null 2>&1
sample
INPUT
    status=$?
    reached="$(cat "$marker" 2>/dev/null || true)"
    [ "$status" -ne 124 ] || fail 'SCF workflow timed out after recalculation EOF'
    assert_not_contains "$reached" 'runtime-setup' 'SCF workflow continued after recalculation EOF'
    assert_not_contains "$reached" 'thread-setup' 'SCF workflow continued to thread setup after recalculation EOF'
}

test_completed_prompt_eof_returns() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    printf 'JOB DONE.\n' >"$sandbox/scf.out"
    timeout 2 bash -c 'cd "$1"; QBOX_TEST_MODE=1 source "$2"; qe_output_success_for_prefix(){ return 0; }; qe_ask_recalculate_scf_completed sample' _ "$sandbox" "$PROJECT_ROOT/qbox" </dev/null >/dev/null 2>&1
    [ "$?" -ne 124 ] || fail 'recalculate prompt loops on EOF'
}

run_test 'choice retries then accepts' test_choice_accepts_retry
run_test 'choice returns on EOF' test_choice_eof_returns
run_test 'yes/no accepts yes' test_yes_no_accepts_yes
run_test 'timed choice returns on EOF' test_choice_timeout_eof_returns
run_test 'simple prompts return on EOF' test_prompt_eof_returns
run_test 'timed choice uses default' test_choice_timeout_uses_default
run_test 'recalculate retry keeps result clean' test_recalculate_retry_keeps_result_clean
run_test 'SCF workflow cancels on recalculation EOF' test_scf_workflow_cancels_on_recalculate_eof
run_test 'completed prompt returns on EOF' test_completed_prompt_eof_returns
finish_tests
