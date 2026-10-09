#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_embedded_plot_ldos (){
qbox_python -m qbox.postprocess.ldos_plot "$@"
}

function qe_find_ldos_plot_data_in_dir (){
	local ldos_dir calc_prefix candidate
	ldos_dir="$1"
	calc_prefix="$2"
	if [ -n "$calc_prefix" ]; then
		for candidate in "${ldos_dir}/${calc_prefix}.pdos.ldos_boxes.dat" "${ldos_dir}/${calc_prefix}.pdos.ldos_boxes"; do
			if [ -f "$candidate" ]; then
				echo "$candidate"
				return 0
			fi
		done
	fi
	for candidate in "${ldos_dir}"/*.pdos.ldos_boxes.dat "${ldos_dir}"/*.pdos.ldos_boxes; do
		if [ -f "$candidate" ]; then
			echo "$candidate"
			return 0
		fi
	done
	return 1
}

function redraw_qe_ldos_plot (){
	local plot_scope ldos_dir calc_prefix ldos_file ldos_zero_reference output_prefix plot_status
	local fermi_from_args plot_command

	echo
	echo ' 该功能只重绘已有 LDOS 图，不重新运行 scf/projwfc。'
	plot_scope=`qe_prompt_plot_data_scope "LDOS 图"`
	if [ "$plot_scope" == "calcdir" ]; then
		ldos_dir="LDOS"
		fermi_from_args="scf.out nscf.out"
	else
		ldos_dir="."
		fermi_from_args="scf.out nscf.out ../scf.out ../nscf.out ../../scf.out ../../nscf.out"
	fi

	if [ ! -d "$ldos_dir" ]; then
		echo
		echo " 错误：未找到 LDOS 绘图数据目录：$ldos_dir"
		return 1
	fi

	calc_prefix=`qe_prompt_calc_prefix`
	ldos_file=`qe_find_ldos_plot_data_in_dir "$ldos_dir" "$calc_prefix"`
	if [ -z "$ldos_file" ]; then
		echo
		echo " 错误：${ldos_dir} 中未找到 ${calc_prefix}.pdos.ldos_boxes(.dat) 或其他 *.pdos.ldos_boxes 数据文件。"
		return 1
	fi

	ldos_zero_reference=`qe_prompt_energy_reference "LDOS 图"`
	output_prefix="${ldos_file%.*}"
	if [[ "$ldos_file" == *.dat ]]; then
		output_prefix="${ldos_file%.dat}"
	fi
	output_prefix="${output_prefix}_${ldos_zero_reference}"
	plot_command="qe_embedded_plot_ldos ${ldos_file} --output-prefix ${output_prefix} --zero-reference ${ldos_zero_reference} --fermi-from ${fermi_from_args}"

	echo
	echo " 绘制 LDOS 图：${plot_command}"
	if qe_embedded_plot_ldos "$ldos_file" --output-prefix "$output_prefix" --zero-reference "$ldos_zero_reference" --fermi-from $fermi_from_args; then
		if [ -f "${output_prefix}.png" ] && [ -f "${output_prefix}.pdf" ]; then
			plot_status="success"
		else
			plot_status="failed"
		fi
	else
		plot_status="failed"
	fi

	echo
	echo '=============================== 使用的计算命令 ==============================='
	echo " 1) ${plot_command}"
	echo '================================================================================'
	echo
	echo '=============================== 绘图总结报告 ================================='
	qe_print_status_line 'plot-ldos 是否绘图成功' "$plot_status"
	echo '================================================================================'
	[ "$plot_status" != "failed" ]
}

function qe_ldos_output_success (){
	local calc_prefix="$1"
	[ -s LDOS/ldos.out ] || return 1
	{ grep -q "JOB DONE" LDOS/ldos.out || grep -qi "Writing data to file" LDOS/ldos.out; } || return 1
	if [ -n "$calc_prefix" ] && [ -f LDOS/ldos.in ]; then
		qe_pdos_input_matches_prefix LDOS/ldos.in "$calc_prefix" || return 1
	fi
	{ compgen -G "LDOS/*.pdos.ldos_boxes" >/dev/null || compgen -G "LDOS/*.pdos.ldos_boxes.dat" >/dev/null; }
}

function qe_ldos_plot_success (){
	local calc_prefix="$1"
	local zero_reference="$2"
	[ -f "LDOS/${calc_prefix}.pdos.ldos_boxes_${zero_reference}.png" ] || [ -f "LDOS/${calc_prefix}.pdos.ldos_boxes_${zero_reference}.pdf" ]
}

function qe_clean_ldos_generated_outputs (){
	local backup file
	backup="LDOS/previous-$(date +%Y%m%d-%H%M%S).$$"
	mkdir -p "$backup" || return 1
	for file in LDOS/ldos.out LDOS/*.proj LDOS/*.pdos.ldos_boxes LDOS/*.pdos.ldos_boxes.dat LDOS/*.pdos.ldos_boxes_*.png LDOS/*.pdos.ldos_boxes_*.pdf LDOS/*.xsf; do
		[ -f "$file" ] && mv -- "$file" "$backup/" || true
	done
}

function qe_finalize_ldos_boxes_dat (){
	local file
	for file in LDOS/*.pdos.ldos_boxes; do
		if [ -f "$file" ]; then
			mv "$file" "${file}.dat"
		fi
	done
}

function qe_ask_recalculate_ldos_completed (){
	local calc_prefix has_completed
	calc_prefix="$1"
	has_completed=0
	qe_output_success_for_prefix scf.out "$calc_prefix" && has_completed=1
	qe_output_success_for_prefix nscf.out "$calc_prefix" && has_completed=1
	qe_ldos_output_success "$calc_prefix" && has_completed=1

	qe_prompt_recalculate_completed "$has_completed" \
		' 检测到当前目录已有部分 LDOS 流程结果。是否重新计算已完成步骤？'
}

function run_qe_ldos_calculation (){
	local calc_prefix pw_threads nscf_threads projwfc_threads
	local scf_input nscf_input ldos_input ldos_file
	local scf_status nscf_status ldos_status rename_status plot_status
	local scf_command nscf_command ldos_command rename_command plot_command
	local old_fname1 old_prefix recalc_completed stage_rc all_ldos_steps_done
	local recommended_scf_threads recommended_nscf_threads recommended_projwfc_threads atom_count
	local ldos_zero_reference output_prefix

	echo
	calc_prefix=`qe_prompt_calc_prefix`

	if ! recalc_completed=`qe_ask_recalculate_ldos_completed "$calc_prefix"`; then
		return 1
	fi
	all_ldos_steps_done=0
	if [ "$recalc_completed" == "no" ] && qe_output_success_for_prefix scf.out "$calc_prefix" && qe_output_success_for_prefix nscf.out "$calc_prefix" && qe_ldos_output_success "$calc_prefix"; then
		all_ldos_steps_done=1
	fi
	if [ "$all_ldos_steps_done" != "1" ]; then
		qe_ensure_runtime_for mpirun pw.x projwfc.x || {
			echo ' 错误：QE 运行环境未通过检查，已停止 LDOS 计算。'
			return 1
		}
		qe_report_compute_resources
		recommended_scf_threads=`qe_recommend_pw_threads "$calc_prefix" "scf"`
		recommended_nscf_threads=`qe_recommend_pw_threads "$calc_prefix" "nscf"`
		recommended_projwfc_threads=`qe_recommend_projwfc_threads "$calc_prefix"`
		atom_count=`qe_estimate_atom_count "$calc_prefix"`

		if [ -n "$atom_count" ]; then
			pw_threads=`qe_prompt_positive_int_default " SCF pw.x MPI 进程数 N1 [原子数 ${atom_count}，回车 ${recommended_scf_threads}]：" "$recommended_scf_threads"` || return 1
			nscf_threads=`qe_prompt_positive_int_default " NSCF pw.x MPI 进程数 N2 [原子数 ${atom_count}，回车 ${recommended_nscf_threads}]：" "$recommended_nscf_threads"` || return 1
			projwfc_threads=`qe_prompt_positive_int_default " projwfc.x MPI 进程数 N3 [原子数 ${atom_count}，回车 ${recommended_projwfc_threads}]：" "$recommended_projwfc_threads"` || return 1
		else
			pw_threads=`qe_prompt_positive_int_default " SCF pw.x MPI 进程数 N1 [回车 ${recommended_scf_threads}]：" "$recommended_scf_threads"` || return 1
			nscf_threads=`qe_prompt_positive_int_default " NSCF pw.x MPI 进程数 N2 [回车 ${recommended_nscf_threads}]：" "$recommended_nscf_threads"` || return 1
			projwfc_threads=`qe_prompt_positive_int_default " projwfc.x MPI 进程数 N3 [回车 ${recommended_projwfc_threads}]：" "$recommended_projwfc_threads"` || return 1
		fi
	fi
	ldos_zero_reference=`qe_prompt_energy_reference "LDOS 图"`

	mkdir -p LDOS
	scf_input="${calc_prefix}.scf.in"
	nscf_input="${calc_prefix}.nscf.in"
	ldos_input="LDOS/ldos.in"
	if [ -f "$ldos_input" ] && ! qe_pdos_input_matches_prefix "$ldos_input" "$calc_prefix"; then
		echo
		echo " 检测到 ${ldos_input} 的 prefix 与当前前缀 '${calc_prefix}' 不一致，将重新生成。"
		rm -f "$ldos_input"
	fi

	if [ ! -f "$scf_input" ]; then
		qe_print_input_generation_header "$scf_input" "pw.x / SCF（LDOS）"
		echo " 缺少 ${scf_input}，转入 pw.x SCF 输入文件生成流程。"
		qe_generate_pwin_for_task "$calc_prefix" "energy" "$scf_input" || {
			echo
			echo ' 错误：SCF 输入文件生成失败，已停止 LDOS 计算。'
			return 1
		}
	fi

	if [ ! -f "$nscf_input" ]; then
		qe_print_input_generation_header "$nscf_input" "pw.x / NSCF（LDOS）"
		echo " 缺少 ${nscf_input}，转入 pw.x NSCF 输入文件生成流程。"
		qe_generate_pwin_for_task "$calc_prefix" "nscf" "$nscf_input" || {
			echo
			echo ' 错误：NSCF 输入文件生成失败，已停止 LDOS 计算。'
			return 1
		}
	fi

	if [ ! -f "$scf_input" ] || [ ! -f "$nscf_input" ]; then
		echo
		echo ' 错误：仍缺少必要输入文件，已停止 LDOS 计算。'
		echo " scf 输入：$scf_input"
		echo " nscf 输入：$nscf_input"
		return 1
	fi

	if [ "$recalc_completed" == "yes" ]; then
		echo " 将旧的 LDOS 输出移入时间戳备份目录。"
		qe_clean_ldos_generated_outputs || return 1
	fi

	if [ "$all_ldos_steps_done" == "1" ]; then
		scf_command="跳过：已有成功的 scf.out 和 tmp/${calc_prefix}.save"
		nscf_command="跳过：已有成功的 nscf.out 和 tmp/${calc_prefix}.save"
		ldos_command="跳过：已有成功的 LDOS 输出"
	else
		scf_command="mpirun -np ${pw_threads} pw.x -in ${scf_input} 2>&1 | tee scf.out"
		nscf_command="mpirun -np ${nscf_threads} pw.x -in ${nscf_input} 2>&1 | tee nscf.out"
		ldos_command="cd LDOS && mpirun -np ${projwfc_threads} projwfc.x -in ldos.in 2>&1 | tee ldos.out"
	fi
	rename_command="mv LDOS/*.pdos.ldos_boxes LDOS/*.pdos.ldos_boxes.dat"

	echo
	if [ "$recalc_completed" == "no" ] && qe_output_success_for_prefix scf.out "$calc_prefix"; then
		echo " 跳过 SCF 计算：已有成功的 scf.out。"
		scf_status="skipped"
	else
		echo " 开始 SCF 计算：${scf_command}"
		qe_run_stage scf_status . scf.out qe_output_success scf.out -- \
			mpirun -np "$pw_threads" pw.x -in "$scf_input"
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	echo
	if [ "$recalc_completed" == "no" ] && qe_output_success_for_prefix nscf.out "$calc_prefix"; then
		echo " 跳过 NSCF 计算：已有成功的 nscf.out。"
		nscf_status="skipped"
	elif [ "$scf_status" == "failed" ]; then
		echo " 跳过 NSCF 计算：SCF 失败。"
		nscf_status="failed"
	else
		echo " 开始 NSCF 计算：${nscf_command}"
		qe_run_stage nscf_status . nscf.out qe_output_success nscf.out -- \
			mpirun -np "$nscf_threads" pw.x -in "$nscf_input"
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	if [ "$all_ldos_steps_done" != "1" ] && [ "$nscf_status" != "failed" ]; then
		if [ "$recalc_completed" == "yes" ] || [ ! -f "$ldos_input" ]; then
			if [ "$recalc_completed" == "yes" ] && [ -f "$ldos_input" ]; then
				echo
				echo " 将根据最新 nscf.out 重新生成 ${ldos_input}。"
				rm -f "$ldos_input"
			fi
			qe_print_input_generation_header "$ldos_input" "projwfc.x / LDOS"
			old_fname1="$fname1"
			old_prefix="$prefix"
			prefix="$calc_prefix"
			if [ -f "${calc_prefix}.cif" ]; then
				fname1="${calc_prefix}.cif"
			fi
			qe_generate_ldos_input || {
				fname1="$old_fname1"
				prefix="$old_prefix"
				echo
				echo ' 错误：LDOS 输入文件生成失败，已停止 LDOS 计算。'
				return 1
			}
			fname1="$old_fname1"
			prefix="$old_prefix"
		fi
	fi

	if [ "$all_ldos_steps_done" != "1" ] && [ "$nscf_status" != "failed" ] && [ ! -f "$ldos_input" ]; then
		echo
		echo " 错误：缺少 projwfc.x LDOS 输入文件：$ldos_input"
		return 1
	fi

	echo
	if [ "$recalc_completed" == "no" ] && qe_ldos_output_success "$calc_prefix"; then
		echo " 跳过 projwfc.x LDOS 计算：已有成功的 LDOS 输出。"
		ldos_status="skipped"
	elif [ "$nscf_status" == "failed" ]; then
		echo " 跳过 projwfc.x LDOS 计算：NSCF 失败。"
		ldos_status="failed"
	else
		echo " 开始 projwfc.x LDOS 计算：${ldos_command}"
		qe_run_stage ldos_status LDOS ldos.out qe_ldos_output_success "$calc_prefix" -- \
			mpirun -np "$projwfc_threads" projwfc.x -in ldos.in
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	echo
	if [ "$ldos_status" == "failed" ]; then
		echo " 跳过 LDOS 数据重命名：projwfc.x LDOS 失败。"
		rename_status="failed"
	else
		echo " 整理 LDOS box 数据：${rename_command}"
		qe_finalize_ldos_boxes_dat
		if compgen -G "LDOS/*.pdos.ldos_boxes.dat" >/dev/null; then
			rename_status="success"
		else
			rename_status="failed"
		fi
	fi

	ldos_file=`qe_find_ldos_plot_data_in_dir "LDOS" "$calc_prefix"`
	if [ -n "$ldos_file" ]; then
		output_prefix="${ldos_file%.dat}_${ldos_zero_reference}"
	else
		output_prefix="LDOS/${calc_prefix}.pdos.ldos_boxes_${ldos_zero_reference}"
	fi
	plot_command="qe_embedded_plot_ldos ${ldos_file:-LDOS/${calc_prefix}.pdos.ldos_boxes.dat} --output-prefix ${output_prefix} --zero-reference ${ldos_zero_reference} --fermi-from nscf.out scf.out"

	echo
	if [ "$rename_status" == "failed" ]; then
		echo " 跳过 plot-ldos：LDOS box 数据整理失败。"
		plot_status="failed"
	else
		echo " 绘制 LDOS 图：${plot_command}"
		if qe_embedded_plot_ldos "$ldos_file" --output-prefix "$output_prefix" --zero-reference "$ldos_zero_reference" --fermi-from nscf.out scf.out; then
			if qe_ldos_plot_success "$calc_prefix" "$ldos_zero_reference"; then plot_status="success"; else plot_status="failed"; fi
		else
			plot_status="failed"
		fi
	fi

	echo
	echo '=============================== 使用的计算命令 ==============================='
	echo " 1) ${scf_command}"
	echo " 2) ${nscf_command}"
	echo " 3) ${ldos_command}"
	echo " 4) ${rename_command}"
	echo " 5) ${plot_command}"
	echo '================================================================================'
	echo
	echo '=============================== 计算总结报告 ================================='
	qe_print_status_line 'scf 是否计算成功' "$scf_status"
	qe_print_status_line 'nscf 是否计算成功' "$nscf_status"
	qe_print_status_line 'projwfc/ldos 是否计算成功' "$ldos_status"
	qe_print_status_line 'ldos boxes 是否整理成功' "$rename_status"
	qe_print_status_line 'plot-ldos 是否绘图成功' "$plot_status"
	echo '================================================================================'
	if [ "$scf_status" == "failed" ] || [ "$nscf_status" == "failed" ] || [ "$ldos_status" == "failed" ] || [ "$rename_status" == "failed" ] || [ "$plot_status" == "failed" ]; then
		return 1
	fi
	return 0
}

# Optical-property formulas used by the epsilon plotting helper.
#
# Literature basis: Journal of Physics D: Applied Physics 54, 405303 (2021),
# equations (3)-(6), and 55, 375303 (2022), equations (3)-(4), define the
# refractive index, extinction coefficient, energy-loss function and absorption.
#
# Both papers use the dielectric function epsilon(E)=epsilon1(E)+i*epsilon2(E).
# With the complex refractive index N(E)=n(E)+i*kappa(E)=sqrt(epsilon(E)):
#   n(E)     = sqrt((sqrt(epsilon1^2+epsilon2^2)+epsilon1)/2)
#              refractive index; phase velocity reduction in the material.
#   kappa(E) = sqrt((sqrt(epsilon1^2+epsilon2^2)-epsilon1)/2)
#              extinction coefficient; attenuation part of the complex index.
#   alpha(E) = 2*E*kappa(E)/(hbar*c)
#            = sqrt(2)*E/(hbar*c)*sqrt(sqrt(epsilon1^2+epsilon2^2)-epsilon1)
#              absorption coefficient; exponential intensity attenuation.
#
# Code-unit convention:
#   QE epsilon.x outputs photon energy E in eV. The code converts E to angular
#   frequency as omega=E*e/hbar, so alpha=2*omega*kappa/c is identical to the
#   paper formula alpha=2*E*kappa/(hbar*c). The output alpha is converted from
#   m^-1 to cm^-1 by dividing by 100.
#
# Extra post-processing quantities:
#   A(E) = 1-exp(-alpha(E)*d)
#          single-pass absorptance for thickness d, neglecting interface
#          reflection and multiple internal reflections.
#   R(E) = ((n-1)^2+kappa^2)/((n+1)^2+kappa^2)
#          normal-incidence reflectance from air/vacuum.
#
# Formula check:
# The n and kappa equations follow exactly from equating
# (n+i*kappa)^2 = epsilon1+i*epsilon2. The alpha equation follows from
# I(z)=I0*exp(-alpha*z). The reflectance equation is the normal-incidence
# Fresnel expression for a complex refractive index. A(E) is correct only for
# the simple single-pass estimate above, so the plotting function asks for d.
