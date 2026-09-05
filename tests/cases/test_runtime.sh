#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"

source_qbox

test_version_support_matrix() {
    local version expected actual
    while IFS='|' read -r version expected; do
        [ -n "$version" ] || continue
        if qe_version_is_supported "$version"; then
            actual='accept'
        else
            actual='reject'
        fi
        assert_eq "$expected" "$actual" "unexpected support result for '$version'" || return 1
    done <<'MATRIX'
6.8|reject
7.0|reject
7.0.0|reject
7.0.1|accept
7.1|accept
7.3.1|accept
7.4.1|accept
7.5|accept
8.0|accept
7|reject
7.x|reject
7..1|reject
7.0.|reject
MATRIX
}

test_extracts_real_pw_version_line() {
    local output
    output="$(printf '%s\n' \
        'Program PWSCF v.7.5 starts on 01Sep2026 at 12:00:00' \
        'irrelevant output' | qe_extract_qe_version)" || return 1
    assert_eq '7.5' "$output" 'QE version parser did not recognize PWSCF output'
}

write_pw_mock() {
    local target="$1" version="$2" exit_status="${3:-17}"
    cat >"$target" <<EOF_MOCK
#!/bin/sh
printf '%s\n' 'Program PWSCF v.$version starts on 01Sep2026 at 12:00:00'
printf '%s\n' CRASH > CRASH
exit $exit_status
EOF_MOCK
    chmod +x "$target"
}

write_command_mock() {
    local target="$1"
    cat >"$target" <<'EOF_MOCK'
#!/bin/sh
exit 0
EOF_MOCK
    chmod +x "$target"
}

write_runtime_env_script() {
    local target="$1" bin="$2"
    printf 'export PATH="%s:${PATH}"\n' "$bin" >"$target"
}

prepare_runtime_mocks() {
    local bin="$1" version="$2"
    mkdir -p "$bin"
    write_pw_mock "$bin/pw.x" "$version"
    write_command_mock "$bin/mpirun"
    write_command_mock "$bin/sumpdos.x"
}

test_supported_probe_isolated_and_tolerates_nonzero_pw() {
    local sandbox bin output status
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    prepare_runtime_mocks "$bin" '7.5' || return 1
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT=''
        export QE_MODULE=''
        unset QE_RUNTIME_VERSION
        qe_ensure_runtime_for mpirun pw.x >probe.out 2>probe.err
        status=$?
        [ "$status" -eq 0 ] || exit 1
        output="$(cat probe.out)"
        assert_contains "$output" '已检测到所需命令可运行：mpirun pw.x' || exit 1
        [ "${QE_RUNTIME_VERSION-}" = '7.5' ] || exit 1
        [ ! -e CRASH ] || exit 1
        [ ! -s probe.err ] || exit 1
        [ -z "$(find "$sandbox" -maxdepth 1 -name '.qbox-qe-version.*' -print -quit)" ] || exit 1
    ) || {
        fail 'supported QE version probe was not isolated or did not tolerate nonzero pw.x'
        return 1
    }
}

test_unsupported_probe_reports_support_boundary() {
    local sandbox bin error_file status
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    mkdir -p "$bin"
    write_pw_mock "$bin/pw.x" '7.0'
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH"
        export TMPDIR="$sandbox"
        error_file="$sandbox/unsupported.err"
        qe_require_supported_version "$(command -v pw.x)" 2>"$error_file"
        status=$?
        [ "$status" -ne 0 ] || exit 1
        assert_contains "$(cat "$error_file")" '要求版本严格大于 7.0' || exit 1
        [ ! -e CRASH ] || exit 1
    ) || {
        fail 'QE 7.0 was not rejected with the strict support boundary'
        return 1
    }
}

test_unknown_probe_reports_diagnostic_failure() {
    local sandbox bin error_file status
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    mkdir -p "$bin"
    cat >"$bin/pw.x" <<'EOF_MOCK'
#!/bin/sh
printf '%s\n' 'Quantum ESPRESSO output without a version header'
exit 17
EOF_MOCK
    chmod +x "$bin/pw.x"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH"
        export TMPDIR="$sandbox"
        error_file="$sandbox/unknown.err"
        qe_require_supported_version "$(command -v pw.x)" 2>"$error_file"
        status=$?
        [ "$status" -ne 0 ] || exit 1
        assert_contains "$(cat "$error_file")" '无法识别 Quantum ESPRESSO 版本' || exit 1
        assert_contains "$(cat "$error_file")" '严格大于 7.0' || exit 1
    ) || {
        fail 'unknown QE version output did not produce a diagnostic failure'
        return 1
    }
}

test_sumpdos_runtime_does_not_require_pw() {
    local sandbox bin status
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    mkdir -p "$bin"
    write_command_mock "$bin/sumpdos.x"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:/usr/bin:/bin"
        export HOME="$sandbox"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT=''
        export QBOX_ONEAPI_ENV_SCRIPT=''
        export QE_MODULE=''
        unset QE_RUNTIME_VERSION
        qe_choose_and_load_module() { return 1; }
        qe_ensure_runtime_for sumpdos.x >/dev/null 2>runtime.err
        status=$?
        [ "$status" -eq 0 ] || exit 1
        [ -z "${QE_RUNTIME_VERSION-}" ] || exit 1
        [ ! -e CRASH ] || exit 1
        [ ! -s runtime.err ] || exit 1
    ) || {
        fail 'sumpdos.x incorrectly required pw.x'
        return 1
    }
}

test_sumpdos_runtime_ignores_pw_version() {
    local sandbox bin status
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    mkdir -p "$bin"
    write_command_mock "$bin/sumpdos.x"
    write_pw_mock "$bin/pw.x" '7.0'
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:/usr/bin:/bin"
        export HOME="$sandbox"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT=''
        export QBOX_ONEAPI_ENV_SCRIPT=''
        export QE_MODULE=''
        unset QE_RUNTIME_VERSION
        qe_ensure_runtime_for sumpdos.x >/dev/null 2>runtime.err
        status=$?
        [ "$status" -eq 0 ] || exit 1
        [ -z "${QE_RUNTIME_VERSION-}" ] || exit 1
        [ ! -e CRASH ] || exit 1
        [ ! -s runtime.err ] || exit 1
    ) || {
        fail 'sumpdos.x incorrectly applied the PW version gate'
        return 1
    }
}

test_non_pw_tool_uses_configured_environment() {
    local sandbox initial_bin configured_bin env_script output status
    sandbox="$(new_sandbox)" || return 1
    initial_bin="$sandbox/initial-bin"
    configured_bin="$sandbox/configured-bin"
    env_script="$sandbox/qe-env.sh"
    mkdir -p "$initial_bin" "$configured_bin"
    write_command_mock "$configured_bin/sumpdos.x"
    write_runtime_env_script "$env_script" "$configured_bin"
    (
        cd "$sandbox" || exit 1
        export PATH="$initial_bin:/usr/bin:/bin"
        export HOME="$sandbox"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT="$env_script"
        export QBOX_ONEAPI_ENV_SCRIPT=''
        export QE_MODULE=''
        unset QE_RUNTIME_VERSION
        qe_ensure_runtime_for sumpdos.x >runtime.out 2>runtime.err
        status=$?
        [ "$status" -eq 0 ] || exit 1
        output="$(cat runtime.out)"
        assert_contains "$output" '正在加载 QBOX_QE_ENV_SCRIPT 指定的 QE 运行环境。' || exit 1
        [ "$(command -v sumpdos.x)" = "$configured_bin/sumpdos.x" ] || exit 1
        [ -z "${QE_RUNTIME_VERSION-}" ] || exit 1
        [ ! -e CRASH ] || exit 1
        [ ! -s runtime.err ] || exit 1
    ) || {
        fail 'a missing non-pw tool did not load its configured environment'
        return 1
    }
}

test_non_pw_tool_uses_module_environment() {
    local sandbox initial_bin module_bin output status
    sandbox="$(new_sandbox)" || return 1
    initial_bin="$sandbox/initial-bin"
    module_bin="$sandbox/module-bin"
    mkdir -p "$initial_bin" "$module_bin"
    write_command_mock "$module_bin/sumpdos.x"
    (
        cd "$sandbox" || exit 1
        export PATH="$initial_bin:/usr/bin:/bin"
        export HOME="$sandbox"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT=''
        export QBOX_ONEAPI_ENV_SCRIPT=''
        export QE_MODULE='mock/qe/7.4.1'
        export TEST_RUNTIME_MODULE_BIN="$module_bin"
        unset QE_RUNTIME_VERSION
        qe_choose_and_load_module() {
            printf '%s\n' "$*" >module.args
            [ "$*" = 'sumpdos.x' ] || return 1
            PATH="$TEST_RUNTIME_MODULE_BIN:$PATH"
            export PATH
            hash -r
            return 0
        }
        qe_ensure_runtime_for sumpdos.x >runtime.out 2>runtime.err
        status=$?
        [ "$status" -eq 0 ] || exit 1
        output="$(cat runtime.out)"
        [ "$(command -v sumpdos.x)" = "$module_bin/sumpdos.x" ] || exit 1
        [ -z "${QE_RUNTIME_VERSION-}" ] || exit 1
        assert_eq 'sumpdos.x' "$(cat module.args)" || exit 1
        assert_not_contains "$output" '跳过额外环境脚本加载' || exit 1
        [ ! -e CRASH ] || exit 1
        [ ! -s runtime.err ] || exit 1
    ) || {
        fail 'a missing non-pw tool did not load its module environment'
        return 1
    }
}

test_non_pw_tool_ignores_unrelated_pw() {
    local sandbox tool_bin authority_bin output status
    sandbox="$(new_sandbox)" || return 1
    tool_bin="$sandbox/tool-bin"
    authority_bin="$sandbox/authority-bin"
    mkdir -p "$tool_bin" "$authority_bin"
    write_command_mock "$tool_bin/sumpdos.x"
    write_pw_mock "$authority_bin/pw.x" '7.0'
    (
        cd "$sandbox" || exit 1
        export PATH="$tool_bin:$authority_bin:/usr/bin:/bin"
        export HOME="$sandbox"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT=''
        export QBOX_ONEAPI_ENV_SCRIPT=''
        export QE_MODULE=''
        unset QE_RUNTIME_VERSION
        qe_choose_and_load_module() { return 1; }
        qe_ensure_runtime_for sumpdos.x >runtime.out 2>runtime.err
        status=$?
        [ "$status" -eq 0 ] || exit 1
        output="$(cat runtime.out)"
        [ -z "${QE_RUNTIME_VERSION-}" ] || exit 1
        assert_not_contains "$output" '正在加载' || exit 1
        [ ! -e CRASH ] || exit 1
        [ ! -s runtime.err ] || exit 1
    ) || {
        fail 'a non-pw request incorrectly inspected an unrelated pw.x'
        return 1
    }
}

test_absolute_non_pw_request_does_not_require_pw() {
    local sandbox requested_tool status
    sandbox="$(new_sandbox)" || return 1
    requested_tool="$sandbox/runtime-bin/sumpdos.x"
    mkdir -p "${requested_tool%/*}"
    write_command_mock "$requested_tool"
    (
        cd "$sandbox" || exit 1
        export PATH="/usr/bin:/bin"
        export HOME="$sandbox"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT=''
        export QBOX_ONEAPI_ENV_SCRIPT=''
        export QE_MODULE=''
        unset QE_RUNTIME_VERSION
        qe_choose_and_load_module() { return 1; }
        qe_ensure_runtime_for "$requested_tool" >/dev/null 2>runtime.err
        status=$?
        [ "$status" -eq 0 ] || exit 1
        [ -z "${QE_RUNTIME_VERSION-}" ] || exit 1
        [ ! -e CRASH ] || exit 1
        [ ! -s runtime.err ] || exit 1
    ) || {
        fail 'an absolute non-pw request incorrectly required pw.x'
        return 1
    }
}

test_absolute_pw_request_is_version_authority() {
    local sandbox requested_pw path_pw error_file status
    sandbox="$(new_sandbox)" || return 1
    requested_pw="$sandbox/requested/pw.x"
    path_pw="$sandbox/path-bin/pw.x"
    error_file="$sandbox/absolute-pw.err"
    mkdir -p "${requested_pw%/*}" "${path_pw%/*}"
    write_pw_mock "$requested_pw" '6.8'
    write_pw_mock "$path_pw" '7.5'
    (
        cd "$sandbox" || exit 1
        export PATH="${path_pw%/*}:/usr/bin:/bin"
        export HOME="$sandbox"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT=''
        export QE_MODULE=''
        unset QE_RUNTIME_VERSION
        qe_choose_and_load_module() { return 1; }
        qe_ensure_runtime_for "$requested_pw" 2>"$error_file"
        status=$?
        [ "$status" -ne 0 ] || exit 1
        assert_contains "$(cat "$error_file")" '6.8' || exit 1
        [ "${QE_RUNTIME_VERSION-}" = '' ] || exit 1
        [ ! -e CRASH ] || exit 1
    ) || {
        fail 'absolute pw.x request was incorrectly backed by PATH pw.x'
        return 1
    }
}

test_multiple_absolute_pw_requests_must_share_authority() {
    local sandbox first_pw second_pw error_file status
    sandbox="$(new_sandbox)" || return 1
    first_pw="$sandbox/first/pw.x"
    second_pw="$sandbox/second/pw.x"
    error_file="$sandbox/multiple-pw.err"
    mkdir -p "${first_pw%/*}" "${second_pw%/*}"
    write_pw_mock "$first_pw" '7.5'
    write_pw_mock "$second_pw" '7.4.1'
    (
        cd "$sandbox" || exit 1
        export PATH="/usr/bin:/bin"
        export HOME="$sandbox"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT=''
        export QE_MODULE=''
        unset QE_RUNTIME_VERSION
        qe_choose_and_load_module() { return 1; }
        qe_ensure_runtime_for "$first_pw" "$second_pw" 2>"$error_file"
        status=$?
        [ "$status" -ne 0 ] || exit 1
        assert_contains "$(cat "$error_file")" '多个不同的 pw.x' || exit 1
        [ "${QE_RUNTIME_VERSION-}" = '' ] || exit 1
        [ ! -e CRASH ] || exit 1
    ) || {
        fail 'multiple absolute pw.x requests were not rejected as ambiguous'
        return 1
    }
}

test_equivalent_absolute_pw_requests_share_authority() {
    local sandbox first_pw equivalent_pw status
    sandbox="$(new_sandbox)" || return 1
    first_pw="$sandbox/runtime/pw.x"
    equivalent_pw="$sandbox/alias/pw.x"
    mkdir -p "${first_pw%/*}" "${equivalent_pw%/*}"
    write_pw_mock "$first_pw" '7.5'
    ln -s "$first_pw" "$equivalent_pw"
    (
        cd "$sandbox" || exit 1
        export PATH="/usr/bin:/bin"
        export HOME="$sandbox"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT=''
        export QE_MODULE=''
        unset QE_RUNTIME_VERSION
        qe_ensure_runtime_for "$first_pw" "$equivalent_pw" >/dev/null 2>runtime.err
        status=$?
        [ "$status" -eq 0 ] || exit 1
        [ "${QE_RUNTIME_VERSION-}" = '7.5' ] || exit 1
        [ ! -e CRASH ] || exit 1
        [ ! -s runtime.err ] || exit 1
    ) || {
        fail 'equivalent absolute pw.x requests were rejected'
        return 1
    }
}

test_absolute_pw_authority_overrides_unsupported_path_pw() {
    local sandbox requested_pw path_pw status
    sandbox="$(new_sandbox)" || return 1
    requested_pw="$sandbox/requested/pw.x"
    path_pw="$sandbox/path-bin/pw.x"
    mkdir -p "${requested_pw%/*}" "${path_pw%/*}"
    write_pw_mock "$requested_pw" '7.5'
    write_pw_mock "$path_pw" '7.0'
    (
        cd "$sandbox" || exit 1
        export PATH="${path_pw%/*}:/usr/bin:/bin"
        export HOME="$sandbox"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT=''
        export QE_MODULE=''
        unset QE_RUNTIME_VERSION
        qe_ensure_runtime_for "$requested_pw" >/dev/null 2>runtime.err
        status=$?
        [ "$status" -eq 0 ] || exit 1
        [ "${QE_RUNTIME_VERSION-}" = '7.5' ] || exit 1
        [ ! -e CRASH ] || exit 1
        [ ! -s runtime.err ] || exit 1
    ) || {
        fail 'supported absolute pw.x did not override an unsupported PATH pw.x'
        return 1
    }
}

test_relative_pw_request_uses_canonical_authority() {
    local sandbox runtime_dir relative_pw status
    sandbox="$(new_sandbox)" || return 1
    runtime_dir="$sandbox/runtime"
    relative_pw='./pw.x'
    mkdir -p "$runtime_dir"
    write_pw_mock "$runtime_dir/pw.x" '7.5'
    (
        cd "$runtime_dir" || exit 1
        export PATH="/usr/bin:/bin"
        export HOME="$sandbox"
        export TMPDIR="$sandbox"
        export QBOX_QE_ENV_SCRIPT=''
        export QE_MODULE=''
        unset QE_RUNTIME_VERSION
        qe_ensure_runtime_for "$relative_pw" >/dev/null 2>runtime.err
        status=$?
        [ "$status" -eq 0 ] || exit 1
        [ "${QE_RUNTIME_VERSION-}" = '7.5' ] || exit 1
        [ ! -e CRASH ] || exit 1
        [ ! -s runtime.err ] || exit 1
    ) || {
        fail 'relative ./pw.x authority was not canonicalized before probing'
        return 1
    }
}

test_relative_and_absolute_pw_requests_share_canonical_authority() {
    local sandbox runtime_dir absolute_pw status order
    sandbox="$(new_sandbox)" || return 1
    runtime_dir="$sandbox/runtime"
    mkdir -p "$runtime_dir"
    write_pw_mock "$runtime_dir/pw.x" '7.5'
    absolute_pw="$(readlink -f "$runtime_dir/pw.x")"
    for order in relative-first absolute-first; do
        (
            cd "$runtime_dir" || exit 1
            export PATH="/usr/bin:/bin"
            export HOME="$sandbox"
            export TMPDIR="$sandbox"
            export QBOX_QE_ENV_SCRIPT=''
            export QE_MODULE=''
            unset QE_RUNTIME_VERSION
            if [ "$order" = relative-first ]; then
                qe_ensure_runtime_for ./pw.x "$absolute_pw" >/dev/null 2>runtime.err
            else
                qe_ensure_runtime_for "$absolute_pw" ./pw.x >/dev/null 2>runtime.err
            fi
            status=$?
            [ "$status" -eq 0 ] || exit 1
            [ "${QE_RUNTIME_VERSION-}" = '7.5' ] || exit 1
            [ ! -e CRASH ] || exit 1
            [ ! -s runtime.err ] || exit 1
        ) || {
            fail "relative/absolute pw.x order '$order' did not share canonical authority"
            return 1
        }
    done
}

test_input_generation_does_not_require_pw_executable() {
    local sandbox bin
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    mkdir -p "$bin"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH"
        prefix='runtime'
        QE_STRUCT_TMP="$sandbox/runtime_QE.tmp"
        printf '%s\n' \
            'CELL_PARAMETERS angstrom' \
            '10 0 0' \
            '0 10 0' \
            '0 0 10' \
            'ATOMIC_POSITIONS angstrom' \
            'H 0 0 0' >"$QE_STRUCT_TMP"
        natm=1
        ntyp=1
        begcellpos=1
        endcellpos=3
        begatmpos=6
        endatmpos=6
        atmtype[1]='H'
        Natmtype[1]=1
        magarr[1]=0
        lsda=''
        atm[1]='H'
        atmmass[1]='1.008'
        pseudolib='SSSP'
        systype='Semi-conductor'
        func='PBE'
        dispcorr='None'
        dipcorr='None'
        dftu='No'
        pwin_nosym='No'
        kpmesh='gamma'
        nscf_kpmesh='gamma'
        nbnd='Default'
        pwin_scf_conv_thr='1.D-6'
        pwin_diagonalization='david'
        pwin_diago_david_ndim=2
        pwin_diago_cg_maxiter=20
        pwin_diago_full_acc='true'
        pwin_diago_thr_init='1.D-8'
        pwin_ecutwfc_override=''
        pwin_ecutrho_override=''
        pseudo_dir_by_lib() { printf '%s\n' '/mock/SSSP'; }
        pseudo_file_by_lib() { printf '%s\n' 'H.UPF'; }
        qe_estimate_nelec_from_current_pwin_context() { printf '%s\n' '1'; }
        default_cutoffs_from_pseudos() { printf '%s\n' '35 400'; }
        rtask='energy'
        qe_generate_pw_input >/dev/null 2>generation.err || exit 1
        [ -s runtime.scf.in ] || exit 1
        [ ! -e "$bin/pw.x" ] || exit 1
        [ ! -s generation.err ] || exit 1
    ) || {
        fail 'PW input generation unexpectedly required pw.x'
        return 1
    }
}

test_runtime_call_sites_use_central_loader() {
    local source sumdos_source function_name body private_root private_oneapi_setup
    source="$(cat "$PROJECT_ROOT/qbox")"
    assert_not_contains "$source" 'qe_load_runtime_environment_for' \
        'former runtime loader call remains in source' || return 1
    if grep -Eq '^[[:space:]]+qe_load_runtime_environment([[:space:]]|$)' "$PROJECT_ROOT/qbox"; then
        fail 'legacy runtime wrapper is still called directly'
        return 1
    fi
    sumdos_source="$(sed -n '/^function qe_builtin_sumdos /,/^# <<< END BUILTIN: sumdos.sh/p' "$PROJECT_ROOT/qbox")"
    assert_contains "$sumdos_source" 'qe_ensure_runtime_for sumpdos.x' \
        'sumdos does not call central runtime loader' || return 1
    private_root="$(printf '/o%s' pt)"
    private_oneapi_setup="${private_root}/intel/oneapi/setvars.sh"
    assert_not_contains "$sumdos_source" "$private_oneapi_setup" \
        'sumdos still has private oneAPI setup' || return 1
    for function_name in \
        run_qe_effective_mass_calculation run_qe_scf_calculation \
        run_qe_band_calculation run_qe_pdos_batch_stage run_qe_pdos_calculation \
        run_qe_ldos_calculation run_qe_epsilon_calculation run_qe_polar_calculation \
        run_qe_unfold_calculation; do
        body="$(declare -f "$function_name")"
        assert_contains "$body" 'qe_ensure_runtime_for' \
            "$function_name bypasses the central runtime loader" || return 1
    done
}

run_test 'QE version support matrix' test_version_support_matrix
run_test 'extract real PWSCF version line' test_extracts_real_pw_version_line
run_test 'supported probe is isolated and tolerates nonzero pw.x' test_supported_probe_isolated_and_tolerates_nonzero_pw
run_test 'unsupported probe reports strict support boundary' test_unsupported_probe_reports_support_boundary
run_test 'unknown probe reports diagnostic failure' test_unknown_probe_reports_diagnostic_failure
run_test 'sumpdos runtime does not require pw.x' test_sumpdos_runtime_does_not_require_pw
run_test 'sumpdos runtime ignores pw.x version' test_sumpdos_runtime_ignores_pw_version
run_test 'non-pw tool uses configured environment' test_non_pw_tool_uses_configured_environment
run_test 'non-pw tool uses module environment' test_non_pw_tool_uses_module_environment
run_test 'non-pw tool ignores unrelated pw.x' test_non_pw_tool_ignores_unrelated_pw
run_test 'absolute pw.x request is version authority' test_absolute_pw_request_is_version_authority
run_test 'absolute non-pw request does not require pw.x' test_absolute_non_pw_request_does_not_require_pw
run_test 'multiple absolute pw.x requests share one authority' test_multiple_absolute_pw_requests_must_share_authority
run_test 'equivalent absolute pw.x requests share authority' test_equivalent_absolute_pw_requests_share_authority
run_test 'absolute pw.x overrides unsupported PATH pw.x' test_absolute_pw_authority_overrides_unsupported_path_pw
run_test 'relative pw.x request uses canonical authority' test_relative_pw_request_uses_canonical_authority
run_test 'relative and absolute pw.x requests share canonical authority' test_relative_and_absolute_pw_requests_share_canonical_authority
run_test 'input generation does not require pw.x' test_input_generation_does_not_require_pw_executable
run_test 'runtime call sites use central loader' test_runtime_call_sites_use_central_loader
finish_tests
