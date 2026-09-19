#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_builtin_plot_pdos (){
	qbox_python -m qbox.postprocess.pdos_plot "$@"
}
# <<< END BUILTIN PYTHON: plot-pdos-QE.py

# >>> BEGIN BUILTIN PYTHON: calc_em_from_CBM-vasp.py
function qe_write_builtin_calc_em_vasp_script (){
	local out_file="$1"
	cp -- "$QBOX_PACKAGE_DIR/postprocess/effective_mass_vasp.py" "$out_file" || return 1
	chmod +x "$out_file"
}
# <<< END BUILTIN PYTHON: calc_em_from_CBM-vasp.py

function qe_builtin_calc_em_ainv (){
	local tmpdir vasp_script status
	tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/.qbox-calc-em.XXXXXX")" || return 1
	qe_cleanup_register "$tmpdir" || { rm -rf -- "$tmpdir"; return 1; }
	vasp_script="${tmpdir}/calc_em_from_CBM-vasp.py"
	qe_write_builtin_calc_em_vasp_script "$vasp_script" || {
		rm -rf "$tmpdir"
		qe_cleanup_unregister "$tmpdir"
		return 1
	}
	qbox_python "$vasp_script" "$@"
	status=$?
	rm -rf "$tmpdir"
	qe_cleanup_unregister "$tmpdir"
	return "$status"
}

# >>> BEGIN BUILTIN PYTHON: calc_em_from_CBM-QE.py
function qe_builtin_calc_em_qe (){
	local tmpdir vasp_script status
	tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/.qbox-calc-em.XXXXXX")" || return 1
	qe_cleanup_register "$tmpdir" || { rm -rf -- "$tmpdir"; return 1; }
	vasp_script="${tmpdir}/calc_em_from_CBM-vasp.py"
	qe_write_builtin_calc_em_vasp_script "$vasp_script" || {
		rm -rf "$tmpdir"
		qe_cleanup_unregister "$tmpdir"
		return 1
	}
	qbox_python -m qbox.postprocess.effective_mass_qe --vasp-script "$vasp_script" "$@"
	status=$?
	rm -rf "$tmpdir"
	qe_cleanup_unregister "$tmpdir"
	return "$status"
}
# <<< END BUILTIN PYTHON: calc_em_from_CBM-QE.py

function qe_prepare_unfold_em_inputs (){
	local band_dir="$1"
	local cbm_file metadata_file converted_band labels_file
	cbm_file="${band_dir}/CBM.dat"
	metadata_file="${band_dir}/unfold-metadata.json"
	converted_band="${band_dir}/CBM_Ainv.dat"
	labels_file="${band_dir}/KLABELS_QE_Ainv"

	for file in "$cbm_file" "$metadata_file"; do
		if [ ! -s "$file" ]; then
			echo " 错误：缺少 unfold 有效质量输入：${file}。"
			return 1
		fi
	done

	qbox_python -m qbox.postprocess.unfold_effective_mass_inputs "$cbm_file" "$metadata_file" "$converted_band" "$labels_file"
}

function calc_qe_unfold_effective_mass (){
	local band_dir="$1"
	local npts emin_tol tol valley_Ewin jump_tol command_desc status

	if [ ! -s "${band_dir}/CBM.dat" ] || [ ! -s "${band_dir}/VBM.dat" ]; then
		echo
		echo " 未检测到完整的 ${band_dir}/VBM.dat 和 ${band_dir}/CBM.dat，先进入 unfold 带边提取流程。"
		qe_extract_unfold_band_edges "$band_dir" || return 1
	fi
	qe_prepare_unfold_em_inputs "$band_dir" || return 1

	npts=`qe_prompt_default ' 请输入拟合点数 npts，直接回车使用 6。' '6'`
	emin_tol=`qe_prompt_default ' 请输入 CBM 能谷识别能量容差 emin_tol(eV)，直接回车使用 1e-5。' '1e-5'`
	tol=`qe_prompt_default ' 请输入分段/标签匹配容差 tol，直接回车使用 1e-3。' '1e-3'`
	valley_Ewin=`qe_prompt_default ' 请输入取点能量窗 valley_Ewin(eV)，直接回车使用 0.20。' '0.20'`
	jump_tol=`qe_prompt_default ' 请输入相邻点能量跳跃阈值 jump_tol(eV)，直接回车使用 0.50。' '0.50'`

	command_desc="qbox 内置 calc_em_from_CBM-vasp.py -b ${band_dir}/CBM_Ainv.dat -l ${band_dir}/KLABELS_QE_Ainv -o ${band_dir}/EM.dat --png ${band_dir}/band-em.png --png_detail ${band_dir}/band-em-detail.png --npts ${npts} --emin_tol ${emin_tol} --tol ${tol} --valley_Ewin ${valley_Ewin} --jump_tol ${jump_tol}"
	echo
	echo " 开始从 unfold CBM 包络计算有效质量：${command_desc}"
	if qe_builtin_calc_em_ainv -b "${band_dir}/CBM_Ainv.dat" -l "${band_dir}/KLABELS_QE_Ainv" -o "${band_dir}/EM.dat" --png "${band_dir}/band-em.png" --png_detail "${band_dir}/band-em-detail.png" --npts "$npts" --emin_tol "$emin_tol" --tol "$tol" --valley_Ewin "$valley_Ewin" --jump_tol "$jump_tol"; then
		status=0
	else
		status=1
	fi

	echo
	echo '=============================== 使用的命令 ==================================='
	echo " 1) ${command_desc}"
	echo '================================================================================'
	echo
	echo '=============================== 有效质量总结报告 ============================='
	if [ "$status" == "0" ]; then
		qe_print_status_line 'unfold 有效质量是否计算成功' success
		echo " 输出文件：${band_dir}/EM.dat"
		echo " Å^-1 CBM：${band_dir}/CBM_Ainv.dat"
		echo " 高对称点标签：${band_dir}/KLABELS_QE_Ainv"
	else
		qe_print_status_line 'unfold 有效质量是否计算成功' failed
	fi
	echo '================================================================================'
	return "$status"
}

function calc_qe_effective_mass (){
	local data_source plot_scope band_dir band_input bands_output qe_output scf_output
	local npts emin_tol tol valley_Ewin jump_tol command_desc status

	echo
	echo ' 请选择有效质量数据来源：'
	echo '  1) 普通 QE bands.x 的 CBM.dat'
	echo '  2) QE unfold 的 CBM.dat（K 距离已经是 Å^-1）'
	read data_source
	case "$data_source" in
		2)
			if [ -s "UNFOLD/enk.dat" ] && [ -s "UNFOLD/wnk.dat" ]; then
				band_dir="UNFOLD"
			elif [ -s "enk.dat" ] && [ -s "wnk.dat" ]; then
				band_dir="."
			else
				echo ' 错误：当前目录及 UNFOLD/ 中均未找到完整的 enk.dat/wnk.dat。'
				return 1
			fi
			calc_qe_unfold_effective_mass "$band_dir"
			return $?
			;;
		1) ;;
		*) echo ' 错误：请输入 1 或 2。'; return 1 ;;
	esac

	echo
	echo ' 该流程会自动将 bands.x 的 k 坐标从 2*pi/alat 转换为 Å^-1。'
	plot_scope=`qe_prompt_plot_data_scope "有效质量"`
	if [ "$plot_scope" == "calcdir" ]; then
		band_dir="BAND"
	else
		band_dir="."
	fi

	if [ ! -f "${band_dir}/CBM.dat" ] || [ ! -f "${band_dir}/VBM.dat" ]; then
		echo
		echo " 未检测到完整的 ${band_dir}/VBM.dat 和 ${band_dir}/CBM.dat，先进入 VBM/CBM.dat 提取流程。"
		qe_extract_band_edges_for_dir "$band_dir" || return 1
	fi
	if [ ! -f "${band_dir}/CBM.dat" ]; then
		echo " 错误：仍未找到 ${band_dir}/CBM.dat，无法计算有效质量。"
		return 1
	fi

	band_input=`qe_find_band_input_for_dir "$band_dir"`
	if [ -z "$band_input" ]; then
		echo ' 请输入 pw.x bands 输入文件路径，用于读取 K_POINTS crystal_b 标签。'
		read band_input
	fi
	while [ -z "$band_input" ] || [ ! -f "$band_input" ]; do
		echo " 错误：未找到 bands 输入文件 '$band_input'。请重新输入。"
		read band_input
	done

	bands_output=`qe_find_output_file_for_dir "$band_dir" "bands.out"`
	if [ -z "$bands_output" ]; then
		echo ' 请输入 bands.x 输出文件路径，用于读取高对称点横坐标。'
		read bands_output
	fi
	while [ -z "$bands_output" ] || [ ! -f "$bands_output" ]; do
		echo " 错误：未找到 bands.x 输出文件 '$bands_output'。请重新输入。"
		read bands_output
	done

	qe_output=`qe_find_output_file_for_dir "$band_dir" "band.out"`
	scf_output=`qe_find_output_file_for_dir "$band_dir" "scf.out"`
	[ -z "$scf_output" ] && [ -f "scf.out" ] && scf_output="scf.out"
	if [ -z "$qe_output" ]; then
		echo ' 请输入 pw.x bands 输出文件路径，用于读取 alat。直接回车尝试使用 scf.out。'
		read qe_output
	fi
	if [ -z "$qe_output" ]; then
		qe_output="$scf_output"
	fi
	while [ -z "$qe_output" ] || [ ! -f "$qe_output" ]; do
		echo " 错误：未找到 QE 输出文件 '$qe_output'。请重新输入。"
		read qe_output
	done
	if [ -z "$scf_output" ]; then
		scf_output="$qe_output"
	fi

	npts=`qe_prompt_default ' 请输入拟合点数 npts，直接回车使用 6。' '6'`
	emin_tol=`qe_prompt_default ' 请输入 CBM 能谷识别能量容差 emin_tol(eV)，直接回车使用 1e-5。' '1e-5'`
	tol=`qe_prompt_default ' 请输入分段/标签匹配容差 tol，直接回车使用 1e-3。' '1e-3'`
	valley_Ewin=`qe_prompt_default ' 请输入取点能量窗 valley_Ewin(eV)，直接回车使用 0.20。' '0.20'`
	jump_tol=`qe_prompt_default ' 请输入相邻点能量跳跃阈值 jump_tol(eV)，直接回车使用 0.50。' '0.50'`

	command_desc="qbox 内置 calc_em_from_CBM-QE.py -b ${band_dir}/CBM.dat --band-input ${band_input} --bands-output ${bands_output} --qe-output ${qe_output} --scf-output ${scf_output} --converted-band ${band_dir}/CBM_Ainv.dat --converted-labels ${band_dir}/KLABELS_QE_Ainv -o ${band_dir}/EM.dat --png ${band_dir}/band-em.png --png_detail ${band_dir}/band-em-detail.png --npts ${npts} --emin_tol ${emin_tol} --tol ${tol} --valley_Ewin ${valley_Ewin} --jump_tol ${jump_tol}"
	echo
	echo " 开始计算有效质量：${command_desc}"
	if qe_builtin_calc_em_qe -b "${band_dir}/CBM.dat" --band-input "$band_input" --bands-output "$bands_output" --qe-output "$qe_output" --scf-output "$scf_output" --converted-band "${band_dir}/CBM_Ainv.dat" --converted-labels "${band_dir}/KLABELS_QE_Ainv" -o "${band_dir}/EM.dat" --png "${band_dir}/band-em.png" --png_detail "${band_dir}/band-em-detail.png" --npts "$npts" --emin_tol "$emin_tol" --tol "$tol" --valley_Ewin "$valley_Ewin" --jump_tol "$jump_tol"; then
		status=0
	else
		status=1
	fi

	echo
	echo '=============================== 使用的命令 ==================================='
	echo " 1) ${command_desc}"
	echo '================================================================================'
	echo
	echo '=============================== 有效质量总结报告 ============================='
	if [ "$status" == "0" ]; then
		qe_print_status_line '有效质量是否计算成功' success
		echo " 输出文件：${band_dir}/EM.dat"
		echo " 转换后 CBM：${band_dir}/CBM_Ainv.dat"
		echo " 转换后标签：${band_dir}/KLABELS_QE_Ainv"
	else
		qe_print_status_line '有效质量是否计算成功' failed
	fi
	echo '================================================================================'
	return "$status"
}

function qe_detect_prefix_for_em (){
	local f count=0 candidate selected=""
	if [ -n "$prefix" ] && qe_find_structure_for_prefix "$prefix" >/dev/null 2>&1; then
		echo "$prefix"
		return 0
	fi
	if [ -n "$prefix" ] && [ -f "${prefix}.scf.in" ]; then
		echo "$prefix"
		return 0
	fi
	for f in *.scf.in; do
		[ -f "$f" ] || continue
		selected="${f%.scf.in}"; count=$((count + 1))
	done
	if [ "$count" -gt 1 ]; then
		echo ' 错误：检测到多个 SCF 前缀，请先明确设置 prefix：' >&2
		for f in *.scf.in; do [ -f "$f" ] && echo "   ${f%.scf.in}" >&2; done
		return 1
	fi
	[ "$count" -eq 1 ] && { echo "$selected"; return 0; }
	count=0; selected=""
	for f in *.bands.in; do
		[ -f "$f" ] || continue
		selected="${f%.bands.in}"; count=$((count + 1))
	done
	if [ "$count" -gt 1 ]; then
		echo ' 错误：检测到多个 bands 前缀，请先明确设置 prefix：' >&2
		for f in *.bands.in; do [ -f "$f" ] && echo "   ${f%.bands.in}" >&2; done
		return 1
	fi
	[ "$count" -eq 1 ] && { echo "$selected"; return 0; }
	return 1
}

function qe_prepare_em_source_inputs (){
	local calc_prefix="$1"
	local em_dir="$2"
	local structure_file structure_abs em_odd_degauss
	em_odd_degauss="${QE_EM_ODD_ELECTRON_DEGAUSS:-0.002}"

	structure_file=`qe_find_structure_for_prefix "$calc_prefix"`
	if [ -z "$structure_file" ]; then
		echo
		echo " 请输入结构文件路径："
		read structure_file
	fi
	while [ -z "$structure_file" ] || [ ! -f "$structure_file" ]; do
		echo " 错误：未找到结构文件 '$structure_file'。请重新输入。"
		read structure_file
	done
	structure_abs=`readlink -f "$structure_file" 2>/dev/null`
	if [ -z "$structure_abs" ]; then
		structure_abs="$structure_file"
	fi

	mkdir -p "$em_dir"

	if [ ! -f "${em_dir}/${calc_prefix}.scf.in" ]; then
		qe_print_input_generation_header "${em_dir}/${calc_prefix}.scf.in" "pw.x / SCF（有效质量）"
		echo " 缺少 ${em_dir}/${calc_prefix}.scf.in，进入 SCF 输入生成。"
		( cd "$em_dir" && PWIN_DEFAULT_PSEUDOLIB=PD04 PWIN_DEFAULT_SCF_CONV_THR=1.D-10 PWIN_DEFAULT_ODD_ELECTRON_DEGAUSS="$em_odd_degauss" qe_generate_pwin_for_task "$calc_prefix" "energy" "${calc_prefix}.scf.in" "$structure_abs" ) || return 1
	fi

	if [ ! -f "${em_dir}/${calc_prefix}.bands.in" ]; then
		qe_print_input_generation_header "${em_dir}/${calc_prefix}.bands.in" "pw.x / bands（有效质量）"
		echo " 缺少 ${em_dir}/${calc_prefix}.bands.in，进入 bands 输入生成。"
		( cd "$em_dir" && PWIN_DEFAULT_PSEUDOLIB=PD04 PWIN_DEFAULT_BAND_KPATH_MODE=spacing PWIN_DEFAULT_BAND_KPATH_SPACING=0.01 PWIN_DEFAULT_BANDS_NBND_FACTOR=1.2 PWIN_DEFAULT_DIAGO_FULL_ACC=true PWIN_DEFAULT_DIAGO_THR_INIT=1.D-8 PWIN_DEFAULT_ODD_ELECTRON_DEGAUSS="$em_odd_degauss" qe_generate_pwin_for_task "$calc_prefix" "bands" "${calc_prefix}.bands.in" "$structure_abs" ) || return 1
	fi

	qe_apply_odd_electron_smearing_to_input "${em_dir}/${calc_prefix}.scf.in" "$em_odd_degauss" "高精度有效质量 SCF" || return 1
	qe_apply_odd_electron_smearing_to_input "${em_dir}/${calc_prefix}.bands.in" "$em_odd_degauss" "高精度有效质量 bands" || return 1

	if [ ! -f "${em_dir}/bands.in" ]; then
		qe_print_input_generation_header "${em_dir}/bands.in" "bands.x / 有效质量后处理"
		echo " 缺少 ${em_dir}/bands.in，进入 bands.x 输入生成。"
		( cd "$em_dir" && prefix="$calc_prefix" && bandin ) || return 1
	fi

	if [ ! -f "${em_dir}/${calc_prefix}.scf.in" ]; then
		echo " 错误：仍未找到 ${em_dir}/${calc_prefix}.scf.in。"
		return 1
	fi
	if [ ! -f "${em_dir}/${calc_prefix}.bands.in" ]; then
		echo " 错误：仍未找到 ${em_dir}/${calc_prefix}.bands.in。"
		return 1
	fi
	if [ ! -f "${em_dir}/bands.in" ]; then
		echo " 错误：仍未找到 ${em_dir}/bands.in。"
		return 1
	fi

	return 0
}

function qe_apply_odd_electron_smearing_to_input (){
	local infile="$1"
	local degauss="$2"
	local profile_label="$3"
	local nelec tmpfile input_dir input_base
	[ -f "$infile" ] || return 1
	nelec=`qe_estimate_nelec_from_pwin_file "$infile" 2>/dev/null`
	if ! qe_nelec_is_odd_integer "$nelec"; then
		return 0
	fi
	qe_print_odd_electron_notice "$nelec" "${profile_label} 使用奇数电子占据设置"
	if grep -qi "^[[:space:]]*occupations[[:space:]]*=[[:space:]]*['\"]\?smearing" "$infile"; then
		echo " 当前输入已使用 occupations='smearing'，保留原有 smearing/degauss 参数。"
		return 0
	fi
	input_dir="$(cd "$(dirname -- "$infile")" && pwd)" || return 1
	input_base="$(basename -- "$infile")"
	tmpfile="$(mktemp "$input_dir/.qbox-${input_base}.odd-smearing.XXXXXX")" || return 1
	qe_cleanup_register "$tmpfile" || { rm -f -- "$tmpfile"; return 1; }
	if ! awk -v degauss="$degauss" '
		BEGIN{in_system=0; occupation_written=0}
		{
			lower=tolower($0)
			if(lower ~ /^[[:space:]]*&system([[:space:]]|$)/) in_system=1
			if(in_system && lower ~ /^[[:space:]]*occupations[[:space:]]*=/){
				print "   occupations     = '\''smearing'\''"
				print "   smearing        = '\''marzari-vanderbilt'\''"
				print "   degauss         = " degauss
				occupation_written=1
				next
			}
			if(in_system && lower ~ /^[[:space:]]*(smearing|degauss)[[:space:]]*=/) next
			if(in_system && $0 ~ /^[[:space:]]*\/[[:space:]]*$/){
				if(!occupation_written){
					print "   occupations     = '\''smearing'\''"
					print "   smearing        = '\''marzari-vanderbilt'\''"
					print "   degauss         = " degauss
				}
				in_system=0
			}
			print
		}
	' "$infile" > "$tmpfile"; then
		rm -f "$tmpfile"
		qe_cleanup_unregister "$tmpfile"
		return 1
	fi
	chmod --reference="$infile" "$tmpfile" 2>/dev/null || true
	mv -f "$tmpfile" "$infile" || {
		rm -f "$tmpfile"
		qe_cleanup_unregister "$tmpfile"
		return 1
	}
	qe_cleanup_unregister "$tmpfile"
	echo " 已自动改为 occupations='smearing'、smearing='marzari-vanderbilt'、degauss=${degauss} Ry。"
}

function qe_prepare_em_inputs (){
	local calc_prefix="$1"
	local em_dir="$2"
	local em_kpoints_src="$3"
	local scf_src bands_src bandsx_src

	scf_src="${em_dir}/${calc_prefix}.scf.in"
	bands_src="${em_dir}/${calc_prefix}.bands.in"
	bandsx_src="${em_dir}/bands.in"

	if [ ! -f "$scf_src" ]; then
		echo " 错误：未找到 EM/SCF 输入文件 $scf_src。"
		return 1
	fi
	if [ ! -f "$bands_src" ]; then
		echo " 错误：未找到 EM/bands 输入文件 $bands_src。"
		echo " 请重新进入 16 生成 EM 输入。"
		return 1
	fi
	if [ ! -f "$bandsx_src" ]; then
		echo " 错误：未找到 EM/bands.x 输入 ${bandsx_src}。"
		echo " 请重新进入 16 生成 EM 输入。"
		return 1
	fi

	mkdir -p "$em_dir"

	qbox_python -m qbox.io.effective_mass_inputs "$scf_src" "$bands_src" "$bandsx_src" "$em_dir" "$calc_prefix" "$em_kpoints_src"
}

function run_qe_effective_mass_calculation (){
	local calc_prefix em_dir run_now pw_threads bands_threads
	local scf_status band_status bandsx_status extract_status em_status
	local scf_cmd band_cmd bandsx_cmd em_cmd

	calc_prefix=`qe_detect_prefix_for_em`
	if [ -z "$calc_prefix" ]; then
		echo ' 错误：当前目录未找到 *.scf.in 或 *.bands.in，无法确定计算前缀。'
		return 1
	fi
	em_dir="EM"

	qe_prepare_em_source_inputs "$calc_prefix" "$em_dir" || return 1
	if ! qe_prepare_em_inputs "$calc_prefix" "$em_dir" ""; then
		return 1
	fi

	echo
	echo ' EM 输入已准备。立即运行？[y/N]'
	read run_now
	if [ "$run_now" != "y" ] && [ "$run_now" != "Y" ]; then
		echo " 已停止。输入文件在 ${em_dir}/。"
		return 0
	fi

	pw_threads=`qe_prompt_positive_int ' 请输入 pw.x 使用的线程数 N1。'`
	bands_threads=`qe_prompt_positive_int ' 请输入 bands.x 使用的线程数 N2。'`
	qe_ensure_runtime_for mpirun pw.x bands.x || {
		echo ' 错误：QE 运行环境未通过检查，已停止 EM 计算。'
		return 1
	}

	scf_cmd="cd ${em_dir} && mpirun -np ${pw_threads} pw.x -in ${calc_prefix}.scf.in 2>&1 | tee scf.out"
	band_cmd="cd ${em_dir} && mpirun -np ${pw_threads} pw.x -in ${calc_prefix}.bands.in 2>&1 | tee band.out"
	bandsx_cmd="cd ${em_dir} && mpirun -np ${bands_threads} bands.x -in bands.in 2>&1 | tee bands.out"
	em_cmd="cd ${em_dir} && printf '1\n1\n\n\n\n\n\n' | ${script_dir}/qbox 24"

	echo
	echo " 开始 EM/SCF..."
	if ( cd "$em_dir" && set -o pipefail && mpirun -np "$pw_threads" pw.x -in "${calc_prefix}.scf.in" 2>&1 | tee scf.out ); then
		qe_output_success "${em_dir}/scf.out" && scf_status="success" || scf_status="failed"
	else
		scf_status="failed"
	fi

	if [ "$scf_status" == "failed" ]; then
		band_status="failed"
		bandsx_status="failed"
		extract_status="failed"
		em_status="failed"
	else
		echo
		echo " 开始 EM/bands..."
		if ( cd "$em_dir" && set -o pipefail && mpirun -np "$pw_threads" pw.x -in "${calc_prefix}.bands.in" 2>&1 | tee band.out ); then
			qe_output_success "${em_dir}/band.out" && band_status="success" || band_status="failed"
		else
			band_status="failed"
		fi

		if [ "$band_status" == "failed" ]; then
			bandsx_status="failed"
			extract_status="failed"
			em_status="failed"
		else
			echo
			echo " 开始 EM/bands.x..."
			if ( cd "$em_dir" && set -o pipefail && mpirun -np "$bands_threads" bands.x -in bands.in 2>&1 | tee bands.out ); then
				qe_output_success "${em_dir}/bands.out" && [ -s "${em_dir}/bands.dat.gnu" ] && bandsx_status="success" || bandsx_status="failed"
			else
				bandsx_status="failed"
			fi

			if [ "$bandsx_status" == "failed" ]; then
				extract_status="failed"
				em_status="failed"
			else
				echo
				echo ' 提取 EM/VBM.dat 和 EM/CBM.dat...'
				if ( cd "$em_dir" && printf '1\n1\n' | "${script_dir}/qbox" 23 ); then
					extract_status="success"
				else
					extract_status="failed"
				fi

				echo
				echo ' 计算 EM/EM.dat...'
				if ( cd "$em_dir" && printf '1\n1\n\n\n\n\n\n' | "${script_dir}/qbox" 24 ); then
					em_status="success"
				else
					em_status="failed"
				fi
			fi
		fi
	fi

	echo
	echo '=============================== EM 使用的命令 ================================='
	echo " 1) ${scf_cmd}"
	echo " 2) ${band_cmd}"
	echo " 3) ${bandsx_cmd}"
	echo " 4) cd ${em_dir} && qbox 23"
	echo " 5) ${em_cmd}"
	echo '================================================================================'
	echo
	echo '=============================== EM 计算总结报告 ==============================='
	qe_print_status_line 'EM/SCF 是否成功' "$scf_status"
	qe_print_status_line 'EM/bands 是否成功' "$band_status"
	qe_print_status_line 'EM/bands.x 是否成功' "$bandsx_status"
	qe_print_status_line 'EM/VBM-CBM 提取是否成功' "$extract_status"
	qe_print_status_line 'EM/有效质量是否成功' "$em_status"
	echo '================================================================================'
	if [ "$scf_status" == "failed" ] || [ "$band_status" == "failed" ] || [ "$bandsx_status" == "failed" ] || [ "$extract_status" == "failed" ] || [ "$em_status" == "failed" ]; then
		return 1
	fi
	return 0
}

