#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function run_qe_scf_calculation (){
	local calc_prefix scf_input pw_threads recommended_threads atom_count
	local scf_command scf_status recalc_completed stage_rc

	echo
	calc_prefix=`qe_prompt_calc_prefix`
	scf_input="${calc_prefix}.scf.in"

	if [ ! -f "$scf_input" ]; then
		echo
		echo " 缺少 ${scf_input}，转入 pw.x SCF 输入文件生成流程。"
		qe_generate_pwin_for_task "$calc_prefix" "energy" "$scf_input" || {
			echo ' 错误：SCF 输入文件生成失败。'
			return 1
		}
	fi

	if [ ! -f "$scf_input" ]; then
		echo
		echo " 错误：仍缺少 ${scf_input}，已停止执行计算。"
		return 1
	fi

	if ! recalc_completed=`qe_ask_recalculate_scf_completed "$calc_prefix"`; then
		return 1
	fi
	if [ "$recalc_completed" == "no" ] && qe_output_success_for_prefix scf.out "$calc_prefix"; then
		echo
		echo " 跳过 SCF 计算：已有成功的 scf.out。"
		scf_command="跳过：已有成功的 scf.out 和 tmp/${calc_prefix}.save"
		scf_status="skipped"
	else
		qe_ensure_runtime_for mpirun pw.x || {
			echo ' 错误：QE 运行环境未通过检查，已停止 SCF 计算。'
			return 1
		}
		qe_report_compute_resources
		recommended_threads=`qe_recommend_pw_threads "$calc_prefix" "scf"`
		atom_count=`qe_estimate_atom_count "$calc_prefix"`
		if [ -n "$atom_count" ]; then
			pw_threads=`qe_prompt_positive_int_default " SCF pw.x MPI 进程数 N1 [原子数 ${atom_count}，回车 ${recommended_threads}]：" "$recommended_threads"` || return 1
		else
			pw_threads=`qe_prompt_positive_int_default " SCF pw.x MPI 进程数 N1 [回车 ${recommended_threads}]：" "$recommended_threads"` || return 1
		fi

		scf_command="mpirun -np ${pw_threads} pw.x -in ${scf_input} 2>&1 | tee scf.out"

		echo
		echo " 开始 SCF 计算：${scf_command}"
		qe_run_stage scf_status . scf.out qe_output_success scf.out -- \
			mpirun -np "$pw_threads" pw.x -in "$scf_input"
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	echo
	echo '=============================== 使用的计算命令 ==============================='
	echo " 1) ${scf_command}"
	echo '================================================================================'
	echo
	echo '=============================== 计算总结报告 ================================='
	qe_print_status_line 'scf 是否计算成功' "$scf_status"
	echo '================================================================================'
	[ "$scf_status" != "failed" ]
}

function run_qe_band_calculation (){
	local calc_prefix pw_threads bands_threads scf_input pw_band_input bandsx_input
	local scf_run_status pw_band_run_status bands_run_status
	local scf_command pw_band_command bands_command
	local band_zero_reference
	local recalc_completed all_band_steps_done stage_rc

	echo
	calc_prefix=`qe_prompt_calc_prefix`

	qe_ensure_band_inputs "$calc_prefix" || {
		echo
		echo ' 错误：输入文件生成失败，已停止执行计算。'
		return 1
	}

	scf_input="${calc_prefix}.scf.in"
	if [ -f "BAND/${calc_prefix}.bands.in" ]; then
		pw_band_input="BAND/${calc_prefix}.bands.in"
	else
		pw_band_input="BAND/${calc_prefix}.band.in"
	fi
	bandsx_input="BAND/bands.in"

	if [ ! -f "$scf_input" ] || [ ! -f "$pw_band_input" ] || [ ! -f "$bandsx_input" ]; then
		echo
		echo ' 错误：仍缺少必要输入文件，已停止执行计算。'
		echo " scf 输入：$scf_input"
		echo " pw-band 输入：$pw_band_input"
		echo " bands.x 输入：$bandsx_input"
		return 1
	fi

	if ! recalc_completed=`qe_ask_recalculate_band_completed "$calc_prefix"`; then
		return 1
	fi
	all_band_steps_done=0
	if [ "$recalc_completed" == "no" ] && qe_output_success_for_prefix scf.out "$calc_prefix" && qe_band_pw_output_success "$calc_prefix" && qe_bandsx_output_success; then
		all_band_steps_done=1
	fi

	if [ "$all_band_steps_done" == "1" ]; then
		scf_command="跳过：已有成功的 scf.out 和 tmp/${calc_prefix}.save"
		pw_band_command="跳过：已有成功的 BAND/band.out"
		bands_command="跳过：已有成功的 BAND/bands.out 和 BAND/bands.dat.gnu"
	else
		qe_ensure_runtime_for mpirun pw.x bands.x || {
			echo ' 错误：QE 运行环境未通过检查，已停止能带计算。'
			return 1
		}
		qe_report_compute_resources
		pw_threads=`qe_prompt_positive_int ' 请输入 pw.x 使用的 MPI 进程数 N1。'` || return 1
		bands_threads=`qe_prompt_positive_int ' 请输入 bands.x 使用的 MPI 进程数 N2。'` || return 1
		scf_command="mpirun -np ${pw_threads} pw.x -in ${scf_input} 2>&1 | tee scf.out"
		pw_band_command="mpirun -np ${pw_threads} pw.x -in ${pw_band_input} 2>&1 | tee BAND/band.out"
		bands_command="mpirun -np ${bands_threads} bands.x -in ${bandsx_input} 2>&1 | tee BAND/bands.out"
	fi

	echo
	if [ "$recalc_completed" == "no" ] && qe_output_success_for_prefix scf.out "$calc_prefix"; then
		echo " 跳过 SCF 计算：已有成功的 scf.out。"
		scf_run_status="skipped"
	else
		echo " 开始 SCF 计算：${scf_command}"
		qe_run_stage scf_run_status . scf.out qe_output_success scf.out -- \
			mpirun -np "$pw_threads" pw.x -in "$scf_input"
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	echo
	if [ "$recalc_completed" == "no" ] && qe_band_pw_output_success "$calc_prefix"; then
		echo " 跳过 pw.x bands 计算：已有成功的 BAND/band.out。"
		pw_band_run_status="skipped"
	elif [ "$scf_run_status" == "failed" ]; then
		echo " 跳过 pw.x bands 计算：SCF 失败。"
		pw_band_run_status="failed"
	else
		echo " 开始 pw.x bands 计算：${pw_band_command}"
		# Relative outdir/pseudo_dir paths are anchored to the SCF project directory.
		qe_run_stage pw_band_run_status . BAND/band.out qe_output_success BAND/band.out -- \
			mpirun -np "$pw_threads" pw.x -in "$pw_band_input"
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	echo
	if [ "$recalc_completed" == "no" ] && qe_bandsx_output_success; then
		echo " 跳过 bands.x 计算：已有成功的 BAND/bands.out 和 BAND/bands.dat.gnu。"
		bands_run_status="skipped"
	elif [ "$pw_band_run_status" == "failed" ]; then
		echo " 跳过 bands.x 计算：pw.x bands 失败。"
		bands_run_status="failed"
	else
		echo " 开始 bands.x 计算：${bands_command}"
		qe_run_stage bands_run_status . BAND/bands.out qe_output_success BAND/bands.out -- \
			mpirun -np "$bands_threads" bands.x -in "$bandsx_input"
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	if [ "$bands_run_status" != "failed" ]; then
		echo
		echo ' 开始自动绘制 QE 能带图。'
		if [ -f "BAND/bands.dat.gnu" ]; then
			band_zero_reference=`QE_ENERGY_REFERENCE_TIMEOUT=30 QE_ENERGY_REFERENCE_DEFAULT_CHOICE=1 qe_prompt_energy_reference "能带图"`
			qe_embedded_plot_band -i BAND/bands.dat.gnu -o "BAND/${calc_prefix}_band_structure_${band_zero_reference}" --band-input "$pw_band_input" --bands-output BAND/bands.out --zero-reference "$band_zero_reference"
		else
			echo " 警告：未找到 BAND/bands.dat.gnu，跳过绘图。"
		fi
	fi

	echo
	echo '=============================== 使用的计算命令 ==============================='
	echo " 1) ${scf_command}"
	echo " 2) ${pw_band_command}"
	echo " 3) ${bands_command}"
	echo '================================================================================'
	echo
	echo '=============================== 计算总结报告 ================================='
	qe_print_status_line 'scf 是否计算成功' "$scf_run_status"
	qe_print_status_line 'pw-band 是否计算成功' "$pw_band_run_status"
	qe_print_status_line 'bands 是否计算成功' "$bands_run_status"
	echo '================================================================================'
	if [ "$scf_run_status" == "failed" ] || [ "$pw_band_run_status" == "failed" ] || [ "$bands_run_status" == "failed" ]; then
		return 1
	fi
	return 0
}
