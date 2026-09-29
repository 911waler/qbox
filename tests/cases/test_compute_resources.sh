#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

check_runtime_resource_mode() {
    local sandbox="$1" path_mode="$2" loaded="$3" banner="$4" expected="$5" actual
    local bin="$sandbox/qe/$path_mode/7.5/bin"
    mkdir -p "$bin"
    cat >"$bin/pw.x" <<EOF_PW
#!/bin/sh
printf '%s\n' 'Program PWSCF v.7.5' '$banner'
EOF_PW
    chmod +x "$bin/pw.x"
    export PATH="$bin:$PATH" LOADEDMODULES="$loaded" QE_MODULE='qe/gpu/unused'
    qe_ensure_runtime_for pw.x >/dev/null || return 1
    actual="$(qe_runtime_accelerator)" || return 1
    assert_eq "$expected" "$actual" 'resource mode does not match the active pw.x' || return 1
}

test_preloaded_cpu_ignores_gpu_fallback_and_stale_gpu_module() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    check_runtime_resource_mode "$sandbox" cpu 'qe/gpu/7.5' '' cpu
}

test_preloaded_gpu_is_recognized_from_actual_path() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    check_runtime_resource_mode "$sandbox" gpu '' '' gpu
}

test_parent_directory_name_does_not_override_qe_mode() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    check_runtime_resource_mode "$sandbox/cpu-project" gpu '' '' gpu || return 1
    check_runtime_resource_mode "$sandbox/gpu-project" cpu '' '' cpu
}

test_gpu_banner_recognizes_custom_installation() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    check_runtime_resource_mode "$sandbox" custom '' 'GPU acceleration is ACTIVE.' gpu
}

test_loaded_gpu_module_recognizes_generic_install_path() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    check_runtime_resource_mode "$sandbox" custom 'toolchain/nvhpc:qe/gpu/7.5' '' gpu
}

test_cpu_run_after_gpu_run_does_not_reuse_gpu_mode() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    check_runtime_resource_mode "$sandbox" gpu 'qe/gpu/7.5' 'GPU acceleration is ACTIVE.' gpu || return 1
    check_runtime_resource_mode "$sandbox" cpu 'qe/cpu/7.5' '' cpu
}

test_explicit_inactive_gpu_banner_uses_cpu_mode() {
    local sandbox
    sandbox="$(new_sandbox)" || return 1
    check_runtime_resource_mode "$sandbox" gpu 'qe/gpu/7.5' 'GPU acceleration is NOT ACTIVE.' cpu
}

test_fallback_gpu_module_selection_sets_resource_mode() {
    local sandbox bin
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/generic/bin"
    mkdir -p "$bin"
    printf "#!/bin/sh\nprintf 'Program PWSCF v.7.5\\n'\n" >"$bin/pw.x"
    chmod +x "$bin/pw.x"
    export PATH=/usr/bin:/bin QE_MODULE='' LOADEDMODULES='' QBOX_QE_ENV_SCRIPT='' QBOX_ONEAPI_ENV_SCRIPT=''
    module() {
        if [ "$1" = load ]; then
            export PATH="$bin:$PATH" LOADEDMODULES="$2"
        elif [ "$1" = --terse ]; then
            printf 'qe/cpu/7.5\nqe/gpu/7.5\n'
        else
            return 1
        fi
    }
    qe_ensure_runtime_for pw.x <<<2 >/dev/null || return 1
    assert_eq gpu "$(qe_runtime_accelerator)" 'selected GPU module kept the CPU resource mode'
}

run_test 'preloaded CPU ignores GPU fallback and stale module metadata' test_preloaded_cpu_ignores_gpu_fallback_and_stale_gpu_module
run_test 'preloaded GPU uses actual executable path' test_preloaded_gpu_is_recognized_from_actual_path
run_test 'project directory names do not override the QE installation mode' test_parent_directory_name_does_not_override_qe_mode
run_test 'GPU version banner recognizes custom installation' test_gpu_banner_recognizes_custom_installation
run_test 'loaded GPU module recognizes generic installation' test_loaded_gpu_module_recognizes_generic_install_path
run_test 'CPU after GPU does not reuse stale resource mode' test_cpu_run_after_gpu_run_does_not_reuse_gpu_mode
run_test 'explicitly inactive GPU acceleration shows CPU resources' test_explicit_inactive_gpu_banner_uses_cpu_mode
run_test 'fallback GPU module selection sets resource mode' test_fallback_gpu_module_selection_sets_resource_mode
finish_tests
