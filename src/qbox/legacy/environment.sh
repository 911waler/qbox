#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_commands_available (){
	local exe
	for exe in "$@"; do
		command -v "$exe" >/dev/null 2>&1 || return 1
	done
	return 0
}

function qe_command_runtime_ready_for (){
	local exe exe_path ldd_output

	qe_commands_available "$@" || return 1

	for exe in "$@"; do
		exe_path=`command -v "$exe" 2>/dev/null`
		if [ -n "$exe_path" ] && file "$exe_path" 2>/dev/null | grep -q "ELF"; then
			ldd_output=`ldd "$exe_path" 2>/dev/null || true`
			if echo "$ldd_output" | grep -q "not found"; then
				return 1
			fi
		fi
	done

	return 0
}

function qe_initialize_module_command (){
	if type module >/dev/null 2>&1; then
		return 0
	fi

	if [ -r /etc/profile.d/lmod.sh ]; then
		source /etc/profile.d/lmod.sh
	elif [ -r /etc/profile.d/modules.sh ]; then
		source /etc/profile.d/modules.sh
	elif [ -r /usr/share/lmod/lmod/init/bash ]; then
		source /usr/share/lmod/lmod/init/bash
	fi

	type module >/dev/null 2>&1
}

function qe_list_available_modules (){
	qe_initialize_module_command || return 1
	module --terse avail qe 2>&1 | tr '[:space:]' '\n' | sed \
		-e 's/^[[:space:]]*//' \
		-e 's/[[:space:]]*$//' \
		-e 's/(default)$//' \
		-e 's/(D)$//' | awk '
		/^qe\/[^/[:space:]]+\/[^/[:space:]]+$/ && !seen[$0]++ {print}
	'
}

function qe_report_runtime_issues (){
	local exe exe_path ldd_output
	for exe in "$@"; do
		exe_path=`command -v "$exe" 2>/dev/null`
		if [ -z "$exe_path" ]; then
			echo " 错误：当前 QE 环境未找到 $exe。"
			continue
		fi
		if file "$exe_path" 2>/dev/null | grep -q "ELF"; then
			ldd_output=`ldd "$exe_path" 2>/dev/null || true`
			if echo "$ldd_output" | grep -q "not found"; then
				echo " 错误：$exe_path 存在未解析的动态库："
			echo "$ldd_output" | grep "not found"
			fi
		fi
	done
}

function qe_choose_and_load_module (){
	local commands=("$@") modules=() selected choice i

	qe_initialize_module_command || return 2
	mapfile -t modules < <(qe_list_available_modules)
	if [ "${#modules[@]}" -eq 0 ]; then
		return 2
	fi

	echo
	echo ' 当前未检测到可运行的 QE 环境。请选择要加载的 module：'
	for ((i=0; i<${#modules[@]}; i++)); do
		printf '  %d) %s\n' "$((i + 1))" "${modules[$i]}"
	done
	echo '  0) 停止计算'

	if [ -n "${QE_MODULE:-}" ]; then
		selected="$QE_MODULE"
		echo " 使用 QE_MODULE 指定的环境：$selected"
	else
		while true; do
			echo ' 请输入编号：'
			if ! read -r choice; then
				echo ' 输入已结束，未加载 QE 环境。'
				return 1
			fi
			if [ "$choice" = "0" ]; then
				echo ' 已停止：未加载 QE 环境。'
				return 1
			fi
			if echo "$choice" | grep -Eq '^[1-9][0-9]*$' && [ "$choice" -le "${#modules[@]}" ]; then
				selected="${modules[$((choice - 1))]}"
				break
			fi
			echo " 请输入 0 到 ${#modules[@]} 之间的编号。"
		done
	fi

	if ! printf '%s\n' "${modules[@]}" | grep -Fxq "$selected"; then
		echo " 错误：module 列表中不存在 $selected。"
		return 1
	fi

	echo
	echo " 正在加载 QE 环境：module load $selected"
	if ! module load "$selected"; then
		echo " 错误：无法加载 QE 环境 $selected。"
		return 1
	fi
	hash -r

	if ! qe_runtime_commands_ready_for "${commands[@]}"; then
		echo
		echo " 错误：$selected 已加载，但运行环境检查未通过。"
		qe_report_runtime_issues "${commands[@]}"
		return 1
	fi

	echo
	echo " QE 环境检查通过：$selected"
	for exe in "${commands[@]}"; do
		echo "  $exe：$(command -v "$exe")"
	done
	return 0
}

function qe_runtime_qe_tools_share_environment (){
	local pw_executable="$1" exe exe_path pw_resolved exe_resolved
	shift

	[ -n "$pw_executable" ] || return 1
	pw_resolved="$(readlink -f -- "$pw_executable" 2>/dev/null || printf '%s' "$pw_executable")"
	for exe in "$@"; do
		case "${exe##*/}" in
			pw.x) continue ;;
			*.x) ;;
			*) continue ;;
		esac
		exe_path="$(command -v "$exe" 2>/dev/null || true)"
		[ -n "$exe_path" ] || return 1
		exe_resolved="$(readlink -f -- "$exe_path" 2>/dev/null || printf '%s' "$exe_path")"
		[ "${pw_resolved%/*}" = "${exe_resolved%/*}" ] || return 1
	done
}

function qe_runtime_pw_requests_are_unambiguous (){
	local authority='' exe exe_path resolved

	for exe in "$@"; do
		[ "${exe##*/}" = 'pw.x' ] || continue
		exe_path="$(command -v "$exe" 2>/dev/null || true)"
		[ -n "$exe_path" ] || continue
		resolved="$(readlink -f -- "$exe_path" 2>/dev/null || printf '%s' "$exe_path")"
		if [ -n "$authority" ] && [ "$authority" != "$resolved" ]; then
			return 1
		fi
		authority="$resolved"
	done
}

function qe_runtime_pw_executable_for (){
	local exe exe_path authority='' resolved

	for exe in "$@"; do
		[ "${exe##*/}" = 'pw.x' ] || continue
		exe_path="$(command -v "$exe" 2>/dev/null || true)"
		[ -n "$exe_path" ] || return 1
		resolved="$(readlink -f -- "$exe_path" 2>/dev/null || printf '%s' "$exe_path")"
		if [ -n "$authority" ] && [ "$authority" != "$resolved" ]; then
			return 1
		fi
		authority="$resolved"
	done
	[ -n "$authority" ] || return 1
	printf '%s\n' "$authority"
}

function qe_runtime_commands_ready_for (){
	local pw_executable command

	qe_command_runtime_ready_for "$@" || return 1
	for command in "$@"; do
		if [ "${command##*/}" = 'pw.x' ]; then
			pw_executable="$(qe_runtime_pw_executable_for "$@")" || return 1
			qe_runtime_qe_tools_share_environment "$pw_executable" "$@"
			return $?
		fi
	done
	return 0
}

function qe_extract_qe_version (){
	sed -nE 's/.*Program PWSCF v\.([0-9]+(\.[0-9]+)+).*/\1/p' | head -n 1
}

function qe_version_is_supported (){
	local version="$1" part index
	local parts=()
	[[ "$version" =~ ^[0-9]+(\.[0-9]+)+$ ]] || return 1
	IFS=. read -r -a parts <<<"$version"
	[ "$((10#${parts[0]}))" -gt 7 ] && return 0
	[ "$((10#${parts[0]}))" -eq 7 ] || return 1
	for ((index=1; index<${#parts[@]}; index++)); do
		part="${parts[$index]}"
		[ "$((10#$part))" -gt 0 ] && return 0
	done
	return 1
}

function qe_capture_qe_version_output (){
	local temp_dir="$1" pw_executable="$2" launcher
	launcher="$(command -v mpirun 2>/dev/null || true)"
	[ -x "$launcher" ] || launcher=''
	qbox_python -m qbox.runtime "$pw_executable" "$temp_dir" "$launcher"
}

function qe_detect_runtime_accelerator (){
	local executable="${1,,}" version_output="$2" loaded_module
	local loaded_modules=()
	# The probe describes the executable actually selected by PATH. QE_MODULE
	# only chooses a fallback and must never override a preloaded CPU/GPU runtime.
	if [[ "$version_output" == *'GPU acceleration is ACTIVE'* ]]; then
		echo gpu
		return 0
	elif [[ "$version_output" == *'GPU acceleration is NOT ACTIVE'* ]]; then
		echo cpu
		return 0
	fi
	if [[ "$executable" =~ /qe/(cpu|gpu)/ ]]; then
		echo "${BASH_REMATCH[1]}"
		return 0
	fi
	IFS=: read -r -a loaded_modules <<<"${LOADEDMODULES:-}"
	for loaded_module in "${loaded_modules[@]}"; do
		case "$loaded_module" in
			qe/gpu/*) echo gpu; return 0 ;;
			qe/cpu/*) echo cpu; return 0 ;;
		esac
	done
	echo cpu
}

function qe_runtime_accelerator (){
	local executable
	executable="$(qe_runtime_pw_executable_for pw.x 2>/dev/null || true)"
	if [ -n "$executable" ] && [ "$executable" = "${_QE_RUNTIME_PW_EXECUTABLE:-}" ] &&
	   [[ "${_QE_RUNTIME_ACCELERATOR:-}" =~ ^(cpu|gpu)$ ]]; then
		echo "$_QE_RUNTIME_ACCELERATOR"
	else
		qe_detect_runtime_accelerator "$executable" ''
	fi
}

function qe_require_supported_version (){
	local pw_executable="${1-}" version_output version probe_status=0
	[ -x "$pw_executable" ] || {
		echo " 错误：Quantum ESPRESSO 可执行文件不可用：$pw_executable" >&2
		return 1
	}
	version_output="$(qe_with_temp_dir qe_capture_qe_version_output "${TMPDIR:-/tmp}" qe-version "$pw_executable")" || probe_status=$?
	case "$probe_status" in
		0|124) ;;
		*) return 1 ;;
	esac
	version="$(printf '%s\n' "$version_output" | qe_extract_qe_version)"
	[ -n "$version" ] || {
		if [ "$probe_status" -eq 124 ]; then
			echo ' 错误：Quantum ESPRESSO 版本检测超时，已停止探测；保留当前环境，请检查该环境中的 pw.x/MPI。' >&2
			return 1
		fi
		echo ' 错误：无法识别 Quantum ESPRESSO 版本；仅支持严格大于 7.0 的版本。' >&2
		return 1
	}
	qe_version_is_supported "$version" || {
		echo " 错误：Quantum ESPRESSO $version 不受支持；要求版本严格大于 7.0。" >&2
		return 1
	}
	QE_RUNTIME_VERSION="$version"
	export QE_RUNTIME_VERSION
	_QE_RUNTIME_PW_EXECUTABLE="$(readlink -f -- "$pw_executable")"
	_QE_RUNTIME_ACCELERATOR="$(qe_detect_runtime_accelerator "$_QE_RUNTIME_PW_EXECUTABLE" "$version_output")"
}

function qe_ensure_runtime_for (){
	local commands=("$@") required_commands=() command module_status pw_executable runtime_reported=0 runtime_args=()
	local has_pw=0

	[ "${#commands[@]}" -gt 0 ] || return 2
	required_commands=("${commands[@]}")
	if ! qe_runtime_pw_requests_are_unambiguous "${required_commands[@]}"; then
		echo ' 错误：本次请求包含多个不同的 pw.x；所有 pw.x 必须 canonical 为同一 executable。' >&2
		return 1
	fi
	for command in "${required_commands[@]}"; do
		if [ "${command##*/}" = 'pw.x' ]; then
			has_pw=1
			break
		fi
	done
	if qe_runtime_commands_ready_for "${required_commands[@]}"; then
		# The caller's loaded QE/MPI takes precedence even when fallback scripts
		# or QE_MODULE are configured. Version failures must not replace it.
		echo
		echo " 已检测到所需命令可运行：${commands[*]}，跳过额外环境脚本加载。"
	else
		if [ -n "${QBOX_QE_ENV_SCRIPT:-}" ] && [ -f "$QBOX_QE_ENV_SCRIPT" ] && [ -r "$QBOX_QE_ENV_SCRIPT" ]; then
			echo
			echo ' 正在加载 QBOX_QE_ENV_SCRIPT 指定的 QE 运行环境。'
			source "$QBOX_QE_ENV_SCRIPT"
			hash -r
			if qe_runtime_commands_ready_for "${required_commands[@]}"; then
				echo ' QBOX_QE_ENV_SCRIPT 环境检查通过。'
				runtime_reported=1
			fi
		elif [ -n "${QBOX_QE_ENV_SCRIPT:-}" ]; then
			echo
			echo ' 警告：QBOX_QE_ENV_SCRIPT 指向的文件不可读。'
		fi

		if ! qe_runtime_commands_ready_for "${required_commands[@]}"; then
			qe_choose_and_load_module "${required_commands[@]}"
			module_status=$?
			if [ "$module_status" -eq 1 ]; then
				echo ' 错误：已停止：未加载包含所需 QE 命令的环境。' >&2
				return 1
			fi
			if [ "$module_status" -eq 0 ]; then
				runtime_reported=1
			fi
		fi

		if ! qe_runtime_commands_ready_for "${required_commands[@]}" && [ -n "${QBOX_ONEAPI_ENV_SCRIPT:-}" ] && [ -f "$QBOX_ONEAPI_ENV_SCRIPT" ] && [ -r "$QBOX_ONEAPI_ENV_SCRIPT" ]; then
			echo
			echo ' 正在加载 QBOX_ONEAPI_ENV_SCRIPT 指定的编译器/MPI 运行环境。'
			runtime_args=("$@")
			set --
			source "$QBOX_ONEAPI_ENV_SCRIPT"
			set -- "${runtime_args[@]}"
			hash -r
		elif ! qe_runtime_commands_ready_for "${required_commands[@]}" && [ -n "${QBOX_ONEAPI_ENV_SCRIPT:-}" ]; then
			echo
			echo ' 警告：QBOX_ONEAPI_ENV_SCRIPT 指向的文件不可读。'
		fi

		if ! qe_runtime_commands_ready_for "${required_commands[@]}"; then
			echo
			echo " 错误：仍未找到可运行的 QE 环境，已停止计算。"
			qe_report_runtime_issues "${required_commands[@]}"
			return 1
		fi

		if [ "$runtime_reported" -eq 0 ]; then
			echo
			echo " QE 环境检查通过：${commands[*]}"
		fi
	fi

	if [ "$has_pw" -eq 1 ]; then
		pw_executable="$(qe_runtime_pw_executable_for "${required_commands[@]}")" || return 1
		qe_require_supported_version "$pw_executable" || return 1
	fi
	return 0
}

function qe_load_runtime_environment (){
	qe_ensure_runtime_for mpirun pw.x bands.x
}
