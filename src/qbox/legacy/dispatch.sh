#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function main_menu (){
    qbox_python -m qbox.registry --menu
}

function qe_calc_prefix_from_path (){
    local path="${1-}" base
    [ -n "$path" ] || { echo ' 错误：输入路径不能为空。' >&2; return 1; }
    base="${path##*/}"
    case "$base" in
        *.vcrelax.in) base="${base%.vcrelax.in}" ;;
        *.relax.in) base="${base%.relax.in}" ;;
        *.nscf.in) base="${base%.nscf.in}" ;;
        *.bands.in) base="${base%.bands.in}" ;;
        *.band.in) base="${base%.band.in}" ;;
        *.scf.in) base="${base%.scf.in}" ;;
        *.in) base="${base%.in}" ;;
        *.[cC][iI][fF]) base="${base%.[cC][iI][fF]}" ;;
        *.[vV][aA][sS][pP]) base="${base%.[vV][aA][sS][pP]}" ;;
        *.gjf) base="${base%.gjf}" ;;
        *.xyz) base="${base%.xyz}" ;;
        *.pdb) base="${base%.pdb}" ;;
        *.*) base="${base%.*}" ;;
    esac
    [ -n "$base" ] && [ "$base" != '.' ] && [ "$base" != '..' ] || {
        echo " 错误：无法从 '$path' 得到有效前缀。" >&2
        return 1
    }
    printf '%s\n' "$base"
}

function qe_set_input_path (){
    fname1="${1-}"
    if [ -n "$fname1" ]; then
        prefix="$(qe_calc_prefix_from_path "$fname1")" || return 1
    else
        prefix=''
    fi
}

 
fname1=''
fname2=''
fname3=''
prefix=''
#####################################################################################################################
 
 
 
qbox_find_multiwfn() {
    if [ -n "${QBOX_MULTIWFN_HOME:-}" ] && [ -x "$QBOX_MULTIWFN_HOME/Multiwfn" ]; then
        printf '%s\n' "$QBOX_MULTIWFN_HOME/Multiwfn"
        return 0
    fi
    command -v Multiwfn 2>/dev/null
}

qbox_multiwfn() {
    local command_path
    command_path="$(qbox_find_multiwfn)" || {
        echo '错误：未找到 Multiwfn，请设置 QBOX_MULTIWFN_HOME 或将 Multiwfn 加入 PATH。' >&2
        return 1
    }
    "$command_path" "$@"
}

require_multiwfn() {
    qbox_find_multiwfn >/dev/null || {
        echo '错误：未找到 Multiwfn，请设置 QBOX_MULTIWFN_HOME 或将 Multiwfn 加入 PATH。' >&2
        return 1
    }
}

qbox_python() {
    if [ -z "${QBOX_PYTHON:-}" ] || [ ! -x "$QBOX_PYTHON" ]; then
        echo '错误：Python 环境不可用，请设置 QBOX_PYTHON。' >&2
        return 1
    fi
    "$QBOX_PYTHON" "$@"
}

function qe_read_choice (){
	local output_var="$1" allowed="$2" invalid_message="$3" input_value
	[[ "$output_var" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 2
	while true; do
		if ! IFS= read -r input_value; then
			return 1
		fi
		case " $allowed " in
			*" $input_value "*) printf -v "$output_var" '%s' "$input_value"; return 0 ;;
		esac
		echo "$invalid_message"
	done
}

function qe_prompt_yes_no (){
	local output_var="$1" question="$2" no_label="$3" yes_label="$4" selected_choice
	echo >&2
	echo "$question" >&2
	echo "  1) $no_label" >&2
	echo "  2) $yes_label" >&2
	qe_read_choice selected_choice '1 2' ' 请输入 1 或 2。' || return 1
	if [ "$selected_choice" = 2 ]; then
		printf -v "$output_var" '%s' yes
	else
		printf -v "$output_var" '%s' no
	fi
}

function qe_request_main_menu (){
	QE_RETURN_TO_MAIN=1
	return 0
}

function qe_invocation_action_id (){
	local arg1="${1-}" arg2="${2-}" arg3="${3-}" action_id
	if [ -n "${QBOX_TASK_ID:-}" ]; then
		qe_action_handler "$QBOX_TASK_ID" >/dev/null || return 1
		printf '%s\n' "$QBOX_TASK_ID"
		return 0
	fi
	if [ -f "$arg1" ] && [ -f "$arg2" ] && [ -f "$arg3" ]; then
		printf '%s\n' 1
		return 0
	fi
	for action_id in {9..37}; do
		if [ "$arg1" = "$action_id" ] || [ "$arg2" = "$action_id" ] ||
			{ [ "$action_id" = 35 ] && [ "$arg3" = "$action_id" ]; }; then
			printf '%s\n' "$action_id"
			return 0
		fi
	done
	case "$arg2" in
		00|0250|0260|0230|0240)
			printf '%s\n' 0
			return 0
			;;
		7)
			printf '%s\n' 7
			return 0
			;;
	esac
	return 1
}

function qe_prepare_invocation (){
	local direct_action
	if [ "${QE_INVOCATION_PREPARED:-0}" = 1 ]; then
		NONINTERACTIVE_PWIN=''
		PRESET_RTASK=''
		DIRECT_BANDIN=''
	fi
	fname1="${1-}"		# 当输入命令为 qbox structure.cif/.vasp 时保存第一个文件名
	fname2="${2-}"
	fname3="${3-}"
	prefix=''
	QE_INVOCATION_ARG1="$fname1"
	QE_INVOCATION_ARG2="$fname2"
	QE_INVOCATION_ARG3="$fname3"
	QE_INVOCATION_PREPARED=1
	QE_DIRECT_ACTION=''
	if [ -n "$fname1" ]; then
		prefix="$(qe_calc_prefix_from_path "$fname1")" || return 1
	fi

	# Explicit --task inputs are data, never legacy numeric selectors/presets.
	if [ -n "${QBOX_TASK_ID:-}" ]; then
		qe_action_handler "$QBOX_TASK_ID" >/dev/null || return 1
		return 0
	fi

	case "$fname2" in
		00)
			export NONINTERACTIVE_PWIN=1
			export PRESET_RTASK='energy'   # scf
			;;
		0250)
			export NONINTERACTIVE_PWIN=1
			export PRESET_RTASK='nscf'     # pw.x nscf
			;;
		0260)
			export NONINTERACTIVE_PWIN=1
			export PRESET_RTASK='bands'    # pw.x bands
			;;
		7)
			export DIRECT_BANDIN=1         # bands.x input
			;;
		0230)
			export NONINTERACTIVE_PWIN=1
			export PRESET_RTASK='structural optimization(relax)'  # QE relax
			;;
		0240)
			export NONINTERACTIVE_PWIN=1
			export PRESET_RTASK='cell optimization(vc-relax)'     # QE vc-relax
			;;
	esac

	if direct_action="$(qe_invocation_action_id "$QE_INVOCATION_ARG1" "$QE_INVOCATION_ARG2" "$QE_INVOCATION_ARG3")"; then
		case "$direct_action" in
			9|11|12|13|14|15|16|17|19|29|30|31|32|33|34|36|37)
				if [ "$QE_INVOCATION_ARG1" = "$direct_action" ]; then
					qe_set_input_path "$QE_INVOCATION_ARG2" || return 1
				fi
				;;
			10|18)
				;;
			20|21|22|23|24|25|26)
				if [ "$QE_INVOCATION_ARG1" = "$direct_action" ]; then
					fname1=''
				fi
				;;
			27)
				if [ "$QE_INVOCATION_ARG1" = 27 ]; then
					qe_set_input_path "$QE_INVOCATION_ARG2" || return 1
				fi
				fname2="$QE_INVOCATION_ARG3"
				;;
			28)
				if [ "$QE_INVOCATION_ARG1" = 28 ]; then
					fname1="$QE_INVOCATION_ARG2"
				fi
				;;
			35)
				if [ "$QE_INVOCATION_ARG1" = 35 ]; then
					fname1=''
				fi
				if [ "$QE_INVOCATION_ARG2" = 35 ]; then
					fname2=''
				fi
				;;
		esac
	fi
}

function qe_detect_direct_action (){
	local arg1 arg2 arg3 action_id
	QE_DIRECT_ACTION=''
	if [ "${QE_INVOCATION_PREPARED:-0}" = 1 ]; then
		arg1="${QE_INVOCATION_ARG1-}"
		arg2="${QE_INVOCATION_ARG2-}"
		arg3="${QE_INVOCATION_ARG3-}"
	else
		arg1="${fname1-}"
		arg2="${fname2-}"
		arg3="${fname3-}"
	fi
	if action_id="$(qe_invocation_action_id "$arg1" "$arg2" "$arg3")"; then
		QE_DIRECT_ACTION="$action_id"
		return 0
	fi
	return 1
}

function qe_action_pdos (){
	if [ "${QE_PDOS_BATCH_MODE:-0}" = 1 ]; then
		run_qe_pdos_batch_stage
	else
		run_qe_pdos_calculation
	fi
}

function qbox_require_pw_input (){
	while [ -z "${fname1-}" ]; do
		echo ' 请输入 pw.x 输入文件名。'
		read -r fname1 || return 1
	done
	if [ ! -f "$fname1" ] || [ -L "$fname1" ] || \
		! grep -q '&CONTROL' "$fname1" || \
		! grep -q 'CELL_PARAMETERS' "$fname1" || \
		! grep -q 'angstrom' "$fname1"; then
		echo ' 输入文件格式不受支持！'
		return 1
	fi
	qe_set_input_path "$fname1"
}

function qe_action_fix_atoms (){
	qbox_constraints_menu
}

function qe_action_ecut_scan (){
	qbox_require_pw_input && qbox_ecut_scan_menu "$fname1" "$PWD/scan_ecut"
}

function qe_action_kpoint_scan (){
	qbox_require_pw_input && qbox_kpoint_scan_menu "$fname1" "$PWD/scan_kp"
}

function qe_action_cif_to_vasp (){
	structure_format_convert cif2vasp
}

function qe_action_vasp_to_cif (){
	structure_format_convert vasp2cif
}

function qe_action_handler (){
	qbox_python -m qbox.registry --handler "${1-}"
}

function qe_dispatch_action (){
	local action_id handler
	[ "$#" -ge 1 ] || return 2
	action_id="$1"
	shift
	handler="$(qe_action_handler "$action_id")" || return 1
	[ -n "$handler" ] || return 1
	"$handler" "$@"
}

function qe_main_loop (){
	local status
	while true; do
		QE_RETURN_TO_MAIN=0
		main_menu
		rmainfunc
		status=$?
		[ "${QE_RETURN_TO_MAIN:-0}" = 1 ] || return "$status"
	done
}

function qe_main (){
	local invocation_first invocation_second
	qe_install_cleanup_traps
	qe_prepare_invocation "$@" || return 1
	invocation_first="${QE_INVOCATION_ARG1-}"
	invocation_second="${QE_INVOCATION_ARG2-}"
	# In explicit mode every positional argument is data, including 36 and 37.
	if qe_is_vasp_structure_file "$invocation_first" && \
		[ "${QBOX_TASK_ID:-}" != 36 ] && [ "${QBOX_TASK_ID:-}" != 37 ] && \
		{ [ -n "${QBOX_TASK_ID:-}" ] || { [ "$invocation_second" != 36 ] && [ "$invocation_second" != 37 ]; }; }; then
		qe_auto_convert_vasp_to_cif "$invocation_first" || return 1
		qe_set_input_path "$QE_AUTO_CONVERTED_CIF" || return 1
	fi
	if qe_detect_direct_action; then
		qe_dispatch_action "$QE_DIRECT_ACTION"
		return $?
	fi
	qe_main_loop
}
