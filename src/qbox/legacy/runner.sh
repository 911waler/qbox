#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_prompt_recalculate_completed (){
	local has_completed="$1" question="$2" answer
	if [ "$has_completed" != "1" ]; then
		echo "no"
		return 0
	fi
	qe_prompt_yes_no answer \
		"$question" \
		'否，跳过已经成功完成的步骤' \
		'是，全部重新计算' 1>&2 || return 1
	echo "$answer"
}

function qe_ask_recalculate_completed (){
	local calc_prefix has_completed
	calc_prefix="$1"
	has_completed=0
	qe_output_success_for_prefix scf.out "$calc_prefix" && has_completed=1
	qe_output_success_for_prefix nscf.out "$calc_prefix" && has_completed=1
	qe_pdos_output_success "$calc_prefix" && has_completed=1
	{ qe_pdos_output_success "$calc_prefix" && qe_pdos_clean_success; } && has_completed=1
	{ qe_pdos_output_success "$calc_prefix" && qe_pdos_sum_success; } && has_completed=1

	qe_prompt_recalculate_completed "$has_completed" \
		' 检测到当前目录已有部分 PDOS 流程结果。是否重新计算已完成步骤？'
}

function qe_ask_recalculate_scf_completed (){
	local calc_prefix has_completed
	calc_prefix="$1"
	has_completed=0
	qe_output_success_for_prefix scf.out "$calc_prefix" && has_completed=1
	qe_prompt_recalculate_completed "$has_completed" \
		' 检测到当前目录已有成功的 SCF 结果。是否重新计算？'
}

function qe_ask_recalculate_band_completed (){
	local calc_prefix has_completed
	calc_prefix="$1"
	has_completed=0
	qe_output_success_for_prefix scf.out "$calc_prefix" && has_completed=1
	qe_band_pw_output_success "$calc_prefix" && has_completed=1
	qe_bandsx_output_success && has_completed=1

	qe_prompt_recalculate_completed "$has_completed" \
		' 检测到当前目录已有部分能带计算结果。是否重新计算已完成步骤？'
}

function qe_run_stage (){
	[ "$#" -ge 4 ] || return 2
	local _qe_stage_result_name="$1" _qe_stage_workdir="$2" _qe_stage_log_file="$3" _qe_stage_success_fn="$4"
	local _qe_stage_exit_status=0 _qe_stage_found_separator=0
	local _qe_stage_success_args=() _qe_stage_command_args=()
	[[ "$_qe_stage_result_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 2
	case "$_qe_stage_result_name" in
		_qe_stage_*) return 2 ;;
	esac
	shift 4
	while [ "$#" -gt 0 ]; do
		if [ "$1" = "--" ]; then
			_qe_stage_found_separator=1
			shift
			break
		fi
		_qe_stage_success_args+=("$1")
		shift
	done
	[ "$_qe_stage_found_separator" = "1" ] && [ "$#" -gt 0 ] || return 2
	_qe_stage_command_args=("$@")
	(
		cd "$_qe_stage_workdir" || exit 1
		set -o pipefail
		"${_qe_stage_command_args[@]}" 2>&1 | tee "$_qe_stage_log_file"
	) || _qe_stage_exit_status=$?
	if [ "$_qe_stage_exit_status" -eq 0 ] && "$_qe_stage_success_fn" "${_qe_stage_success_args[@]}"; then
		printf -v "$_qe_stage_result_name" '%s' success || return 2
		return 0
	fi
	printf -v "$_qe_stage_result_name" '%s' failed || return 2
	return 1
}

function qe_print_status_line (){
	local label="$1"
	local status="$2"
	if [ "$status" == "success" ]; then
		echo " ${label}：成功"
	elif [ "$status" == "skipped" ]; then
		echo " ${label}：跳过（已有成功结果）"
	elif [ "$status" == "partial" ]; then
		echo " ${label}：部分成功"
	else
		echo " ${label}：失败"
	fi
}

