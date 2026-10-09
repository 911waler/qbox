#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_prompt_default (){
	local prompt default_value value
	prompt="$1"
	default_value="$2"
	echo "$prompt" >&2
	read value
	if [ -z "$value" ]; then
		value="$default_value"
	fi
	echo "$value"
}

function qe_read_fermi_energy_from_outputs (){
	local file fermi
	for file in nscf.out scf.out; do
		if [ ! -f "$file" ]; then
			continue
		fi
			fermi=`awk '
				/the Fermi energy is/ {val=$(NF-1)}
				/highest occupied/ {
					for(i=1;i<=NF;i++){
						if($i ~ /^[-+]?[0-9]*\.?[0-9]+$/){val=$i; break}
					}
				}
			END{if(val!="") print val}
		' "$file"`
		if echo "$fermi" | awk '$1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ {exit 0} {exit 1}'; then
			echo "$fermi"
			return 0
		fi
	done
	return 1
}

function qe_default_dos_energy_window (){
	local fermi_energy
	fermi_energy=`qe_read_fermi_energy_from_outputs`
	if echo "$fermi_energy" | awk '$1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ {exit 0} {exit 1}'; then
		awk -v ef="$fermi_energy" 'BEGIN{printf "%.3f %.3f\n", ef-10.0, ef+10.0}'
	else
		echo "-20 20"
	fi
}

function qe_write_pdos_input (){
	local calc_prefix pdos_input pdos_type emin emax deltae degauss fermi_energy default_emin default_emax
	calc_prefix="$1"
	pdos_input="$2"

	qe_print_input_generation_header "$pdos_input" "projwfc.x / PDOS"
	echo " 缺少 ${pdos_input}，将生成 projwfc.x 输入文件。"
	echo ' 请选择体系类型：'
	echo '  1) 非金属/有带隙掺杂体系（tetrahedra；不写 degauss）'
	echo '  2) 金属/费米面穿过能带掺杂体系（smearing 展宽）'
	read pdos_type
	while [ "$pdos_type" != "1" ] && [ "$pdos_type" != "2" ]; do
		echo ' 请输入 1 或 2。'
		read pdos_type
	done

	fermi_energy=`qe_read_fermi_energy_from_outputs`
	if echo "$fermi_energy" | awk '$1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ {exit 0} {exit 1}'; then
		default_emin=`awk -v ef="$fermi_energy" 'BEGIN{printf "%.3f", ef-10.0}'`
		default_emax=`awk -v ef="$fermi_energy" 'BEGIN{printf "%.3f", ef+10.0}'`
		echo " 已读取 Fermi level：${fermi_energy} eV；PDOS 默认能量范围设置为 Fermi level 上下 10 eV。"
	else
		default_emin="-20"
		default_emax="20"
		echo " 警告：未能读取 Fermi level；PDOS 默认能量范围回退为 -20 到 20 eV。"
	fi

	emin=`qe_prompt_default " 请输入 PDOS 能量下限 Emin，直接回车使用 ${default_emin}。" "$default_emin"`
	emax=`qe_prompt_default " 请输入 PDOS 能量上限 Emax，直接回车使用 ${default_emax}。" "$default_emax"`
	deltae=`qe_prompt_default ' 请输入能量间隔 DeltaE，直接回车使用 0.01。' '0.01'`

	mkdir -p "$(dirname "$pdos_input")"
	{
		echo '&PROJWFC'
		echo "   prefix          = '${calc_prefix}'"
		echo "   outdir          = './tmp'"
		echo "   filpdos         = 'PDOS/pdos.dat'"
		if [ "$pdos_type" == "1" ]; then
			:
		else
			degauss=`qe_prompt_default ' 请输入 smearing 展宽 degauss，单位 Ry，直接回车使用 0.01。' '0.01'`
			echo "   ngauss          = 0"
			echo "   degauss         = ${degauss}"
		fi
		echo "   DeltaE          = ${deltae}"
		echo "   Emin            = ${emin}"
		echo "   Emax            = ${emax}"
		echo ' /'
	} > "$pdos_input"

	echo
	echo " 已生成 ${pdos_input}。"
}

function qe_render_pdos_batch_pw (){
	local infile="$1"
	local ecutwfc="$2"
	local ecutrho="$3"
	local conv_thr="$4"
	local degauss="$5"
	awk -v ew="$ecutwfc" -v er="$ecutrho" -v ct="$conv_thr" -v dg="$degauss" '
	  BEGIN{section=""; sw=sr=ns=oc=sm=dgdone=cv=0}
	  /^[[:space:]]*&/ {
	    line=tolower($0)
	    if(line ~ /&system/) section="system"
	    else if(line ~ /&electrons/) section="electrons"
	    else section="other"
	    print; next
	  }
	  /^[[:space:]]*\/[[:space:]]*$/ {
	    if(section=="system") {
	      if(!sw) print "   ecutwfc         = " ew
	      if(!sr) print "   ecutrho         = " er
	      if(!ns) print "   nspin           = 1"
	      if(!oc) print "   occupations     = '\''smearing'\''"
	      if(!sm) print "   smearing        = '\''marzari-vanderbilt'\''"
	      if(!dgdone) print "   degauss         = " dg
	    } else if(section=="electrons" && !cv) {
	      print "   conv_thr        = " ct
	    }
	    print; section=""; next
	  }
	  section=="system" && /^[[:space:]]*ecutwfc[[:space:]]*=/ {print "   ecutwfc         = " ew; sw=1; next}
	  section=="system" && /^[[:space:]]*ecutrho[[:space:]]*=/ {print "   ecutrho         = " er; sr=1; next}
	  section=="system" && /^[[:space:]]*nspin[[:space:]]*=/ {print "   nspin           = 1"; ns=1; next}
	  section=="system" && /^[[:space:]]*occupations[[:space:]]*=/ {print "   occupations     = '\''smearing'\''"; oc=1; next}
	  section=="system" && /^[[:space:]]*smearing[[:space:]]*=/ {print "   smearing        = '\''marzari-vanderbilt'\''"; sm=1; next}
	  section=="system" && /^[[:space:]]*degauss[[:space:]]*=/ {print "   degauss         = " dg; dgdone=1; next}
	  section=="system" && /^[[:space:]]*(starting_magnetization|tot_magnetization)[[:space:]_(]/ {next}
	  section=="electrons" && /^[[:space:]]*conv_thr[[:space:]]*=/ {print "   conv_thr        = " ct; cv=1; next}
	  {print}
	' "$infile"
}

function qe_prepare_pdos_batch_pw_input (){
	local infile="$1"
	local ecutwfc="${QE_PDOS_ECUTWFC:-45}"
	local ecutrho="${QE_PDOS_ECUTRHO:-450}"
	local conv_thr="${QE_PDOS_CONV_THR:-1.D-7}"
	local degauss="${QE_PDOS_DEGAUSS:-0.01}"

	[ -f "$infile" ] || { echo " 错误：未找到输入文件 $infile。" >&2; return 1; }
	if ! echo "$ecutwfc $ecutrho $degauss" | awk 'NF==3 && $1>0 && $2>0 && $3>0 {exit 0} {exit 1}'; then
		echo ' 错误：QE_PDOS_ECUTWFC、QE_PDOS_ECUTRHO 或 QE_PDOS_DEGAUSS 不是正数。' >&2
		return 1
	fi
	if ! echo "$conv_thr" | awk 'NF==1 && $1 ~ /^[0-9.]+([dDeE][-+]?[0-9]+)?$/ {exit 0} {exit 1}'; then
		echo " 错误：QE_PDOS_CONV_THR 无效：$conv_thr" >&2
		return 1
	fi

	qe_atomic_rewrite "$infile" qe_render_pdos_batch_pw "$ecutwfc" "$ecutrho" "$conv_thr" "$degauss"
}

function qe_write_pdos_input_batch (){
	local calc_prefix="$1"
	local pdos_input="$2"
	local default_emin default_emax emin emax deltae degauss

	read default_emin default_emax <<< `qe_default_dos_energy_window`
	emin="${QE_PDOS_EMIN:-$default_emin}"
	emax="${QE_PDOS_EMAX:-$default_emax}"
	deltae="${QE_PDOS_DELTAE:-0.01}"
	degauss="${QE_PDOS_DEGAUSS:-0.01}"
	if ! echo "$emin $emax $deltae $degauss" | awk 'NF==4 && $1<$2 && $3>0 && $4>0 {exit 0} {exit 1}'; then
		echo ' 错误：PDOS能量范围、DeltaE或degauss参数无效。' >&2
		return 1
	fi
	mkdir -p "$(dirname "$pdos_input")"
	{
		echo '&PROJWFC'
		echo "   prefix          = '${calc_prefix}'"
		echo "   outdir          = './tmp'"
		echo "   filpdos         = 'PDOS/pdos.dat'"
		echo '   ngauss          = 0'
		echo "   degauss         = ${degauss}"
		echo "   DeltaE          = ${deltae}"
		echo "   Emin            = ${emin}"
		echo "   Emax            = ${emax}"
		echo ' /'
	} > "$pdos_input"
	echo " 已生成批处理PDOS输入：$pdos_input"
}

function run_qe_pdos_batch_stage (){
	local stage="${QE_PDOS_STAGE:-prepare}"
	local calc_prefix="${QE_PDOS_PREFIX:-$prefix}"
	local structure_file="${QE_PDOS_STRUCTURE:-$fname1}"
	local np="${QE_PDOS_NP:-1}"
	local recalc="${QE_PDOS_RECALCULATE:-0}"
	local zero_reference="${QE_PDOS_ZERO_REFERENCE:-fermi}"
	local scf_input nscf_input pdos_input plot_prefix stage_status

	case "$stage" in prepare|scf|nscf|projwfc|post|all) ;; *) echo " 错误：未知QE_PDOS_STAGE：$stage" >&2; return 2 ;; esac
	if [ -z "$calc_prefix" ] || echo "$calc_prefix" | grep -q '/'; then
		echo " 错误：QE_PDOS_PREFIX无效：$calc_prefix" >&2
		return 2
	fi
	if ! echo "$np" | awk 'NF==1 && $1 ~ /^[0-9]+$/ && $1>0 {exit 0} {exit 1}'; then
		echo " 错误：QE_PDOS_NP必须是正整数：$np" >&2
		return 2
	fi
	case "$zero_reference" in fermi|cbm|vbm|none) ;; *) echo " 错误：QE_PDOS_ZERO_REFERENCE无效：$zero_reference" >&2; return 2 ;; esac

	scf_input="${calc_prefix}.scf.in"
	nscf_input="${calc_prefix}.nscf.in"
	pdos_input="PDOS/pdos.in"
	plot_prefix="${calc_prefix}_${zero_reference}"

	if [ "$stage" == "all" ]; then
		local substage
		for substage in prepare scf nscf projwfc post; do
			QE_PDOS_STAGE="$substage" run_qe_pdos_batch_stage || return $?
		done
		return 0
	fi

	if [ "$stage" == "prepare" ]; then
		if [ -z "$structure_file" ] || [ ! -f "$structure_file" ]; then
			structure_file=`qe_find_structure_for_prefix "$calc_prefix"`
		fi
		[ -n "$structure_file" ] && [ -f "$structure_file" ] || {
			echo " 错误：未找到批处理结构文件：$structure_file" >&2
			return 1
		}
		mkdir -p PDOS
		if [ ! -f "$scf_input" ]; then
			QE_GENERATE_PWIN_COMPACT=1 PWIN_DEFAULT_PSEUDOLIB=PD04 \
			PWIN_DEFAULT_SCF_CONV_THR="${QE_PDOS_CONV_THR:-1.D-7}" \
			PWIN_DEFAULT_ODD_ELECTRON_DEGAUSS="${QE_PDOS_DEGAUSS:-0.01}" \
			qe_generate_pwin_for_task "$calc_prefix" energy "$scf_input" "$structure_file" || return 1
		fi
		if [ ! -f "$nscf_input" ]; then
			QE_GENERATE_PWIN_COMPACT=1 PWIN_DEFAULT_PSEUDOLIB=PD04 \
			PWIN_DEFAULT_SCF_CONV_THR="${QE_PDOS_CONV_THR:-1.D-7}" \
			PWIN_DEFAULT_BANDS_NBND_FACTOR="${QE_PDOS_NBND_FACTOR:-1.2}" \
			PWIN_DEFAULT_ODD_ELECTRON_DEGAUSS="${QE_PDOS_DEGAUSS:-0.01}" \
			qe_generate_pwin_for_task "$calc_prefix" nscf "$nscf_input" "$structure_file" || return 1
		fi
		qe_prepare_pdos_batch_pw_input "$scf_input" || return 1
		qe_prepare_pdos_batch_pw_input "$nscf_input" || return 1
		echo " 批处理PDOS输入准备完成：$scf_input、$nscf_input"
		return 0
	fi

	[ -f "$scf_input" ] && [ -f "$nscf_input" ] || {
		echo ' 错误：缺少SCF或NSCF输入，请先执行prepare阶段。' >&2
		return 1
	}

	case "$stage" in
		scf)
			if [ "$recalc" != "1" ] && qe_output_success_for_prefix scf.out "$calc_prefix"; then
				echo ' SCF已有成功结果，跳过。'; return 0
			fi
			qe_ensure_runtime_for mpirun pw.x || return 1
			qe_run_stage stage_status . scf.out qe_output_success_for_prefix scf.out "$calc_prefix" -- \
				mpirun -np "$np" pw.x -in "$scf_input"
			;;
		nscf)
			qe_output_success_for_prefix scf.out "$calc_prefix" || { echo ' 错误：SCF尚未成功。' >&2; return 1; }
			if [ "$recalc" != "1" ] && qe_output_success_for_prefix nscf.out "$calc_prefix"; then
				echo ' NSCF已有成功结果，跳过。'; return 0
			fi
			qe_ensure_runtime_for mpirun pw.x || return 1
			qe_run_stage stage_status . nscf.out qe_output_success_for_prefix nscf.out "$calc_prefix" -- \
				mpirun -np "$np" pw.x -in "$nscf_input"
			;;
		projwfc)
			qe_output_success_for_prefix nscf.out "$calc_prefix" || { echo ' 错误：NSCF尚未成功。' >&2; return 1; }
			if [ "$recalc" != "1" ] && qe_pdos_output_success "$calc_prefix"; then
				echo ' projwfc已有成功结果，跳过。'; return 0
			fi
			if [ ! -f "$pdos_input" ] || ! qe_pdos_input_matches_prefix "$pdos_input" "$calc_prefix"; then
				qe_write_pdos_input_batch "$calc_prefix" "$pdos_input" || return 1
			fi
			qe_ensure_runtime_for mpirun projwfc.x || return 1
			if [ "$recalc" == "1" ]; then
				qe_clean_pdos_generated_outputs || return 1
			fi
			qe_run_stage stage_status . PDOS/pdos.out qe_pdos_output_success "$calc_prefix" -- \
				mpirun -np "$np" projwfc.x -in "$pdos_input"
			;;
		post)
			qe_pdos_output_success "$calc_prefix" || { echo ' 错误：projwfc尚未成功。' >&2; return 1; }
			qe_ensure_runtime_for sumpdos.x || return 1
			if ! qe_pdos_clean_success; then
				qe_run_stage stage_status PDOS /dev/null qe_pdos_clean_success -- qe_builtin_clean_pdos || return 1
			fi
			if ! qe_pdos_sum_success; then
				qe_run_stage stage_status PDOS/ATOM_PDOS /dev/null qe_pdos_sum_success -- qe_builtin_sumdos || return 1
			fi
			if ! qe_pdos_plot_success "$plot_prefix"; then
				qe_run_stage stage_status PDOS/ATOM_PDOS /dev/null qe_pdos_plot_success "$plot_prefix" -- \
					qe_builtin_plot_pdos --output-prefix "$plot_prefix" \
					--zero-reference "$zero_reference" --fermi-from ../../nscf.out ../../scf.out || return 1
			fi
			qe_pdos_clean_success && qe_pdos_sum_success && qe_pdos_plot_success "$plot_prefix"
			;;
	esac
}

function run_qe_pdos_calculation (){
	local calc_prefix pw_threads nscf_threads projwfc_threads
	local scf_input nscf_input pdos_input
	local scf_status nscf_status pdos_status clean_status sum_status plot_status
	local scf_command nscf_command pdos_command clean_command sum_command plot_command
	local old_fname1 old_prefix
	local recalc_completed stage_rc all_pdos_steps_done
	local recommended_scf_threads recommended_nscf_threads recommended_projwfc_threads atom_count
	local pdos_zero_reference plot_prefix

	echo
	calc_prefix=`qe_prompt_calc_prefix`

	if ! recalc_completed=`qe_ask_recalculate_completed "$calc_prefix"`; then
		return 1
	fi
	all_pdos_steps_done=0
	if [ "$recalc_completed" == "no" ] && qe_output_success_for_prefix scf.out "$calc_prefix" && qe_output_success_for_prefix nscf.out "$calc_prefix" && qe_pdos_output_success "$calc_prefix" && qe_pdos_clean_success && qe_pdos_sum_success; then
		all_pdos_steps_done=1
	fi
	if [ "$all_pdos_steps_done" != "1" ]; then
		qe_ensure_runtime_for mpirun pw.x projwfc.x sumpdos.x || {
			echo ' 错误：QE 运行环境未通过检查，已停止 PDOS 计算。'
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
	pdos_zero_reference=`qe_prompt_energy_reference "态密度图"`
	plot_prefix="${calc_prefix}_${pdos_zero_reference}"

	mkdir -p PDOS
	scf_input="${calc_prefix}.scf.in"
	nscf_input="${calc_prefix}.nscf.in"
	pdos_input="PDOS/pdos.in"
	if [ ! -f "$pdos_input" ] && [ -f "pdos.in" ]; then
		echo
		echo " 检测到当前目录已有 pdos.in，将复制为 ${pdos_input} 并调整 filpdos 路径。"
		cp pdos.in "$pdos_input"
		qe_prepare_pdos_input_for_pdos_dir "$pdos_input"
	fi
	if [ -f "$pdos_input" ] && ! qe_pdos_input_matches_prefix "$pdos_input" "$calc_prefix"; then
		echo
		echo " 检测到 ${pdos_input} 的 prefix 与当前前缀 '${calc_prefix}' 不一致，将重新生成。"
		rm -f "$pdos_input"
	fi

	if [ ! -f "$scf_input" ]; then
		qe_print_input_generation_header "$scf_input" "pw.x / SCF（PDOS）"
		echo " 缺少 ${scf_input}，转入 pw.x 输入文件生成流程；PDOS 默认使用 PD04 NC 赝势。"
		PWIN_DEFAULT_PSEUDOLIB=PD04 qe_generate_pwin_for_task "$calc_prefix" "energy" "$scf_input" || {
			echo
			echo ' 错误：SCF 输入文件生成失败，已停止 PDOS 计算。'
			return 1
		}
	fi

	if [ ! -f "$nscf_input" ]; then
		qe_print_input_generation_header "$nscf_input" "pw.x / NSCF（PDOS）"
		echo " 缺少 ${nscf_input}，转入 pw.x NSCF 输入文件生成流程；PDOS 默认使用 PD04 NC 赝势。"
		PWIN_DEFAULT_PSEUDOLIB=PD04 qe_generate_pwin_for_task "$calc_prefix" "nscf" "$nscf_input" || {
			echo
			echo ' 错误：NSCF 输入文件生成失败，已停止 PDOS 计算。'
			return 1
		}
	fi

	if [ ! -f "$scf_input" ] || [ ! -f "$nscf_input" ]; then
		echo
		echo ' 错误：仍缺少必要输入文件，已停止 PDOS 计算。'
		echo " scf 输入：$scf_input"
		echo " nscf 输入：$nscf_input"
		return 1
	fi

	if [ "$recalc_completed" == "yes" ]; then
		echo " 将旧的 PDOS 输出移入时间戳备份目录。"
		qe_clean_pdos_generated_outputs || return 1
	fi

	if [ "$all_pdos_steps_done" == "1" ]; then
		scf_command="跳过：已有成功的 scf.out 和 tmp/${calc_prefix}.save"
		nscf_command="跳过：已有成功的 nscf.out 和 tmp/${calc_prefix}.save"
		pdos_command="跳过：已有成功的 PDOS 输出"
	else
		scf_command="mpirun -np ${pw_threads} pw.x -in ${scf_input} 2>&1 | tee scf.out"
		nscf_command="mpirun -np ${nscf_threads} pw.x -in ${nscf_input} 2>&1 | tee nscf.out"
		pdos_command="mpirun -np ${projwfc_threads} projwfc.x -in ${pdos_input} 2>&1 | tee PDOS/pdos.out"
	fi
	clean_command="cd PDOS && qe_builtin_clean_pdos"
	sum_command="cd PDOS/ATOM_PDOS && qe_builtin_sumdos"
	plot_command="cd PDOS/ATOM_PDOS && qe_builtin_plot_pdos --output-prefix ${plot_prefix} --zero-reference ${pdos_zero_reference} --fermi-from ../../nscf.out ../../scf.out"

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

	if [ "$nscf_status" != "failed" ]; then
		if [ "$recalc_completed" == "yes" ] || [ ! -f "$pdos_input" ]; then
			if [ "$recalc_completed" == "yes" ] && [ -f "$pdos_input" ]; then
				echo
				echo " 将根据最新 Fermi level 重新生成 ${pdos_input}。"
				rm -f "$pdos_input"
			fi
			qe_write_pdos_input "$calc_prefix" "$pdos_input" || {
				echo
				echo ' 错误：PDOS 输入文件生成失败，已停止 PDOS 计算。'
				return 1
			}
		fi
	fi

	if [ "$nscf_status" != "failed" ] && [ ! -f "$pdos_input" ]; then
		echo
		echo " 错误：缺少 projwfc.x 输入文件：$pdos_input"
		return 1
	fi

	echo
	if [ "$recalc_completed" == "no" ] && qe_pdos_output_success "$calc_prefix"; then
		echo " 跳过 projwfc.x PDOS 计算：已有成功的 PDOS 输出。"
		pdos_status="skipped"
	elif [ "$nscf_status" == "failed" ]; then
		echo " 跳过 projwfc.x PDOS 计算：NSCF 失败。"
		pdos_status="failed"
	else
		echo " 开始 projwfc.x PDOS 计算：${pdos_command}"
		qe_run_stage pdos_status . PDOS/pdos.out qe_pdos_output_success "$calc_prefix" -- \
			mpirun -np "$projwfc_threads" projwfc.x -in "$pdos_input"
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	echo
	if [ "$recalc_completed" == "no" ] && qe_pdos_output_success "$calc_prefix" && qe_pdos_clean_success; then
		echo " 跳过 cleanPDOS：已有 PDOS/ATOM_PDOS 原始 PDOS 文件。"
		clean_status="skipped"
	elif [ "$pdos_status" == "failed" ]; then
		echo " 跳过 cleanPDOS：projwfc.x PDOS 失败。"
		clean_status="failed"
	else
		echo " 整理原始 PDOS 文件：${clean_command}"
		qe_run_stage clean_status PDOS /dev/null qe_pdos_clean_success -- \
			qe_builtin_clean_pdos
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	echo
	if [ "$recalc_completed" == "no" ] && qe_pdos_output_success "$calc_prefix" && qe_pdos_sum_success; then
		echo " 跳过 sumdos：已有汇总 PDOS 数据。"
		sum_status="skipped"
	elif [ "$clean_status" == "failed" ]; then
		echo " 跳过 sumdos：cleanPDOS 失败。"
		sum_status="failed"
	else
		echo " 汇总 PDOS 文件：${sum_command}"
		qe_run_stage sum_status PDOS/ATOM_PDOS /dev/null qe_pdos_sum_success -- \
			qe_builtin_sumdos
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	echo
	if [ "$sum_status" == "failed" ]; then
		echo " 跳过 plot-pdos：sumdos 失败。"
		plot_status="failed"
	else
		echo " 绘制 PDOS 图：${plot_command}"
		qe_run_stage plot_status PDOS/ATOM_PDOS /dev/null qe_pdos_plot_success "$plot_prefix" -- \
			qe_builtin_plot_pdos --output-prefix "$plot_prefix" --zero-reference "$pdos_zero_reference" --fermi-from ../../nscf.out ../../scf.out
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	echo
	echo '=============================== 使用的计算命令 ==============================='
	echo " 1) ${scf_command}"
	echo " 2) ${nscf_command}"
	echo " 3) ${pdos_command}"
	echo " 4) ${clean_command}"
	echo " 5) ${sum_command}"
	echo " 6) ${plot_command}"
	echo '================================================================================'
	echo
	echo '=============================== 计算总结报告 ================================='
	qe_print_status_line 'scf 是否计算成功' "$scf_status"
	qe_print_status_line 'nscf 是否计算成功' "$nscf_status"
	qe_print_status_line 'projwfc/pdos 是否计算成功' "$pdos_status"
	qe_print_status_line 'cleanPDOS 是否处理成功' "$clean_status"
	qe_print_status_line 'sumdos 是否处理成功' "$sum_status"
	qe_print_status_line 'plot-pdos 是否绘图成功' "$plot_status"
	echo '================================================================================'
	echo
	echo ' 如需分析掺杂原子及近邻 PDOS，可运行后处理功能：'
	echo " qbox 28"
	if [ "$scf_status" == "failed" ] || [ "$nscf_status" == "failed" ] || [ "$pdos_status" == "failed" ] || [ "$clean_status" == "failed" ] || [ "$sum_status" == "failed" ] || [ "$plot_status" == "failed" ]; then
		return 1
	fi
	return 0
}

function redraw_qe_pdos_plot (){
	local calc_prefix pdos_zero_reference plot_prefix plot_command plot_status
	local plot_scope pdos_dir fermi_from_args

	echo
	echo ' 该功能只重绘已有 PDOS 图，不重新运行 scf/nscf/projwfc/cleanPDOS/sumdos。'
	plot_scope=`qe_prompt_plot_data_scope "PDOS 图"`
	if [ "$plot_scope" == "calcdir" ]; then
		pdos_dir="PDOS/ATOM_PDOS"
		fermi_from_args="../../nscf.out ../../scf.out"
	else
		pdos_dir="."
		fermi_from_args="nscf.out scf.out ../nscf.out ../scf.out ../../nscf.out ../../scf.out"
	fi

	if [ ! -d "$pdos_dir" ]; then
		echo
		echo " 错误：未找到 PDOS 绘图数据目录：$pdos_dir"
		if [ "$plot_scope" == "calcdir" ]; then
			echo ' 请先完成 13) PDOS计算，或确认当前目录是计算主目录。'
		fi
		return 1
	fi

	if ! qe_pdos_sum_success_in_dir "$pdos_dir"; then
		echo
		echo " 错误：${pdos_dir} 中未找到内置 sumdos 汇总后的 *_tot.dat 或轨道 .dat 文件。"
		if [ "$plot_scope" == "calcdir" ]; then
			echo ' 请先完成 13) PDOS计算中的 cleanPDOS 和 sumdos 步骤。'
		fi
		return 1
	fi

	if [ "$plot_scope" == "calcdir" ] && [ ! -f "nscf.out" ] && [ ! -f "scf.out" ]; then
		echo
		echo ' 警告：当前目录未找到 nscf.out 或 scf.out。'
		echo ' 若选择 Fermi/CBM/VBM 归零，绘图脚本可能无法读取能量参考。'
	fi

	calc_prefix=`qe_prompt_calc_prefix`
	pdos_zero_reference=`qe_prompt_energy_reference "态密度图"`
	plot_prefix="${calc_prefix}_${pdos_zero_reference}"
	plot_command="cd ${pdos_dir} && qe_builtin_plot_pdos --output-prefix ${plot_prefix} --zero-reference ${pdos_zero_reference} --fermi-from ${fermi_from_args}"

	echo
	echo " 绘制 PDOS 图：${plot_command}"
	if ( cd "$pdos_dir" && qe_builtin_plot_pdos --output-prefix "$plot_prefix" --zero-reference "$pdos_zero_reference" --fermi-from $fermi_from_args ); then
		if qe_pdos_plot_success_in_dir "$pdos_dir" "$plot_prefix"; then
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
	qe_print_status_line 'plot-pdos 是否绘图成功' "$plot_status"
	echo '================================================================================'
	[ "$plot_status" != "failed" ]
}

function analyze_qe_dopant_pdos (){
	local analysis_script calc_prefix structure_file pdos_dir dopant nearest cutoff output_dir
	local command_desc analysis_status

	analysis_script="${script_dir}/qbox-dopant-pdos.py"
	if [ ! -f "$analysis_script" ]; then
		echo ' 错误：未找到掺杂 PDOS 分析脚本，请检查 qbox 安装。' >&2
		return 1
	fi

	echo
	echo ' 该功能分析 QE projwfc.x 的原始 pdos_atm 文件，输出掺杂原子及近邻原子的局域 PDOS。'

	if [ -n "$fname1" ] && [ -f "$fname1" ] && { [ -n "${QBOX_TASK_ID:-}" ] || [ "$fname1" != "29" ]; }; then
		structure_file="$fname1"
	else
		calc_prefix=`qe_prompt_calc_prefix`
		structure_file=`qe_find_structure_for_prefix "$calc_prefix"`
	fi

	if [ -z "$structure_file" ] || [ ! -f "$structure_file" ]; then
		echo ' 请输入 QE 结构输入文件路径，例如 xxx.scf.in。'
		read structure_file
	fi
	while [ -z "$structure_file" ] || [ ! -f "$structure_file" ]; do
		echo " 错误：未找到结构文件 '$structure_file'。请重新输入。"
		read structure_file
	done
	qe_auto_convert_vasp_to_cif "$structure_file" || return 1
	structure_file="$QE_AUTO_CONVERTED_CIF"

	if [ -d "PDOS/ATOM_PDOS" ]; then
		pdos_dir=`qe_prompt_default ' 请输入原始 pdos_atm 文件目录，直接回车使用 PDOS/ATOM_PDOS。' 'PDOS/ATOM_PDOS'`
	else
		pdos_dir=`qe_prompt_default ' 请输入原始 pdos_atm 文件目录，直接回车使用当前目录。' '.'`
	fi
	while [ -z "$pdos_dir" ] || [ ! -d "$pdos_dir" ]; do
		echo " 错误：未找到 PDOS 目录 '$pdos_dir'。请重新输入。"
		read pdos_dir
	done
	if ! compgen -G "${pdos_dir}/*.pdos_atm#*" >/dev/null; then
		echo " 错误：${pdos_dir} 中未找到原始 *.pdos_atm#* 文件。"
		echo ' 请先完成 13) PDOS计算中的 projwfc.x 和 cleanPDOS 步骤。'
		return 1
	fi

	dopant=`qe_prompt_default ' 请输入掺杂元素符号，直接回车使用 Al。' 'Al'`
	nearest=`qe_prompt_default ' 请输入最近邻原子数 nearest，直接回车使用 4。' '4'`
	echo ' 如需按距离截断选择近邻，请输入 cutoff(Angstrom)；直接回车则使用 nearest。'
	read cutoff
	output_dir=`qe_prompt_default ' 请输入输出目录，直接回车使用 dopant_pdos_analysis。' 'dopant_pdos_analysis'`

	echo
	if [ -n "$cutoff" ]; then
		command_desc='qbox-dopant-pdos.py --structure <input> --pdos-dir <input> --dopant <element> --cutoff <angstrom> --output-dir <output>'
		echo " 开始分析掺杂 PDOS：${command_desc}"
		if qbox_python "$analysis_script" --structure "$structure_file" --pdos-dir "$pdos_dir" --dopant "$dopant" --cutoff "$cutoff" --output-dir "$output_dir"; then
			analysis_status="success"
		else
			analysis_status="failed"
		fi
	else
		command_desc='qbox-dopant-pdos.py --structure <input> --pdos-dir <input> --dopant <element> --nearest <count> --output-dir <output>'
		echo " 开始分析掺杂 PDOS：${command_desc}"
		if qbox_python "$analysis_script" --structure "$structure_file" --pdos-dir "$pdos_dir" --dopant "$dopant" --nearest "$nearest" --output-dir "$output_dir"; then
			analysis_status="success"
		else
			analysis_status="failed"
		fi
	fi

	echo
	echo '=============================== 使用的命令 ==================================='
	echo " 1) ${command_desc}"
	echo '================================================================================'
	echo
	echo '=============================== 掺杂 PDOS 分析总结报告 ========================'
	qe_print_status_line '掺杂 PDOS 是否分析成功' "$analysis_status"
	if [ "$analysis_status" == "success" ]; then
		echo " 输出目录：${output_dir}"
		echo " 近邻报告：${output_dir}/neighbor_report.txt"
	fi
	echo '================================================================================'
	[ "$analysis_status" == "success" ]
}
