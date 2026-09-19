#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_unfold_discover_structures (){
	local scan_dir="${1:-.}" report_file="${2:-UNFOLD/unfold-structure-candidates.json}"
	local source output key value
	QE_UNFOLD_DISCOVERED_PRIMITIVE=
	QE_UNFOLD_DISCOVERED_PRISTINE=
	QE_UNFOLD_DISCOVERED_DEFECT=
	QE_UNFOLD_DISCOVERY_MODE=
	QE_UNFOLD_DISCOVERY_SUMMARY=

	# Keep converted CIF files as normal user-visible inputs, consistent with menu 37.
	for source in "$scan_dir"/*.[vV][aA][sS][pP]; do
		[ -f "$source" ] || continue
		qe_auto_convert_vasp_to_cif "$source" || return 1
	done

output=`qbox_python -m qbox.postprocess.unfold_discover "$scan_dir" "$report_file"
` || return 1

	while IFS=$'\t' read -r key value; do
		case "$key" in
			PRIMITIVE) QE_UNFOLD_DISCOVERED_PRIMITIVE="$scan_dir/$value" ;;
			PRISTINE) QE_UNFOLD_DISCOVERED_PRISTINE="$scan_dir/$value" ;;
			DEFECT) QE_UNFOLD_DISCOVERED_DEFECT="$scan_dir/$value" ;;
			MODE) QE_UNFOLD_DISCOVERY_MODE="$value" ;;
			SUMMARY) QE_UNFOLD_DISCOVERY_SUMMARY="$value" ;;
		esac
	done <<< "$output"

	[ -n "$QE_UNFOLD_DISCOVERED_PRIMITIVE" ] && [ -n "$QE_UNFOLD_DISCOVERED_PRISTINE" ] && [ -n "$QE_UNFOLD_DISCOVERED_DEFECT" ]
}

function qe_unfold_prepare_geometry (){
	local primitive_cif="$1" pristine_supercell_cif="$2" defect_supercell_cif="$3" k_spacing="$4" output_dir="$5"
	qbox_python -m qbox.postprocess.unfold_geometry "$primitive_cif" "$pristine_supercell_cif" "$defect_supercell_cif" "$k_spacing" "$output_dir"
}

function qe_unfold_patch_bands_input (){
	local bands_input="$1" kpoints_input="$2"
	qbox_python -m qbox.io.unfold_patch_bands "$bands_input" "$kpoints_input"
}

function qe_unfold_read_nbnd (){
	awk 'BEGIN{IGNORECASE=1} /^[[:space:]]*nbnd[[:space:]]*=/ {line=$0; sub(/^[^=]*=/,"",line); gsub(/[,[:space:]]/,"",line); print line; exit}' "$1"
}

function qe_unfold_validate_pw_pair (){
	local scf_input="$1" bands_input="$2"
	local scf_nelec bands_nelec
	scf_nelec=`qe_estimate_nelec_from_pwin_file "$scf_input" 2>/dev/null`
	bands_nelec=`qe_estimate_nelec_from_pwin_file "$bands_input" 2>/dev/null`
	if ! echo "$scf_nelec" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/ && $1 > 0 {exit 0} {exit 1}'; then
		echo " 错误：未能从 ${scf_input} 估算有效电子数。"
		return 1
	fi
	if ! echo "$bands_nelec" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/ && $1 > 0 {exit 0} {exit 1}'; then
		echo " 错误：未能从 ${bands_input} 估算有效电子数。"
		return 1
	fi
	qbox_python -m qbox.io.unfold_validate_pair "$scf_input" "$bands_input" "$scf_nelec" "$bands_nelec"
}

function qe_unfold_validate_nc_pseudos (){
	local input_file="$1"
	qbox_python -m qbox.io.unfold_validate_pseudos "$input_file"
}

function qe_unfold_write_input (){
	local calc_prefix="$1" first_band="$2" last_band="$3" output_dir="$4"
	qbox_python -m qbox.io.unfold_write_input "$calc_prefix" "$first_band" "$last_band" "$output_dir"
}

function qe_unfold_plot_results (){
	local output_dir="${1:-UNFOLD}"
	qbox_python -m qbox.postprocess.unfold_plot "$output_dir"
}

function qe_extract_unfold_band_edges (){
	local output_dir reference_mode reference_value weight_threshold energy_tolerance plot_window value
	output_dir="${1:-UNFOLD}"
	for value in enk.dat wnk.dat unfold-metadata.json; do
		if [ ! -s "${output_dir}/${value}" ]; then
			echo " 错误：缺少 ${output_dir}/${value}。"
			return 1
		fi
	done

	reference_mode="${QE_UNFOLD_EDGE_REFERENCE_MODE:-}"
	if [ "$reference_mode" != "relative" ] && [ "$reference_mode" != "absolute" ]; then
		echo
		echo ' 指定能量将作为价带/导带分界线。请选择能量标尺：'
		echo '  1) 相对于费米能级 E-EF（推荐，与 unfold 图一致）'
		echo '  2) QE 绝对能量'
		read value
		case "$value" in
			1) reference_mode="relative" ;;
			2) reference_mode="absolute" ;;
			*) echo ' 错误：请输入 1 或 2。'; return 1 ;;
		esac
	fi

	reference_value="${QE_UNFOLD_EDGE_REFERENCE_ENERGY:-}"
	while ! echo "$reference_value" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/ {exit 0} {exit 1}'; do
		if [ "$reference_mode" == "relative" ]; then
			echo ' 请输入分界能量 E-EF，单位 eV；直接回车使用 0 eV。'
		else
			echo ' 请输入 QE 绝对分界能量，单位 eV。'
		fi
		read reference_value
		[ -z "$reference_value" ] && [ "$reference_mode" == "relative" ] && reference_value="0"
	done

	weight_threshold="${QE_UNFOLD_EDGE_WEIGHT_THRESHOLD:-}"
	while ! echo "$weight_threshold" | awk 'NF==1 && $1 ~ /^[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/ && $1 >= 0 && $1 <= 1 {exit 0} {exit 1}'; do
		echo ' 请输入全局归一化展开权重阈值 0-1；直接回车使用 0（不过滤）。'
		read weight_threshold
		[ -z "$weight_threshold" ] && weight_threshold="0"
	done

	energy_tolerance="${QE_UNFOLD_EDGE_ENERGY_TOLERANCE:-}"
	while ! echo "$energy_tolerance" | awk 'NF==1 && $1 ~ /^[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/ && $1 > 0 {exit 0} {exit 1}'; do
		echo ' 请输入分界能量容差，单位 eV；直接回车使用 1e-6。'
		read energy_tolerance
		[ -z "$energy_tolerance" ] && energy_tolerance="1e-6"
	done

	plot_window="${QE_UNFOLD_EDGE_PLOT_WINDOW:-}"
	while ! echo "$plot_window" | awk 'NF==1 && $1 ~ /^[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/ && $1 > 0 {exit 0} {exit 1}'; do
		echo ' 请输入总能带图在分界能量上下的显示范围，单位 eV；直接回车使用 5。'
		read plot_window
		[ -z "$plot_window" ] && plot_window="5"
	done

	qbox_python -m qbox.postprocess.unfold_edges "$output_dir" "$reference_mode" "$reference_value" "$weight_threshold" "$energy_tolerance" "$plot_window"
	local status=$?
	if [ "$status" -ne 0 ]; then
		echo ' unfold VBM/CBM 提取失败。'
		return "$status"
	fi
	echo ' 提示：该结果是指定原胞高对称路径上的能量包络，不代表整个布里渊区的全局带边。'
}

function qe_generate_unfold_inputs (){
	local primitive_cif pristine_supercell_cif defect_supercell_cif calc_prefix k_spacing first_band choice value confirm_choice
	local output_dir defect_abs nbnd status input_timeout
	primitive_cif="${QE_UNFOLD_PRIMITIVE_CIF:-}"
	pristine_supercell_cif="${QE_UNFOLD_PRISTINE_SUPERCELL_CIF:-}"
	defect_supercell_cif="${QE_UNFOLD_DEFECT_SUPERCELL_CIF:-}"
	output_dir=UNFOLD
	mkdir -p "$output_dir"
	if [ -z "$primitive_cif" ] && [ -z "$pristine_supercell_cif" ] && [ -z "$defect_supercell_cif" ]; then
		if qe_unfold_discover_structures . "$output_dir/unfold-structure-candidates.json"; then
			echo
			echo '====================== unfold 自动识别候选 ======================'
			echo " 母相原胞结构：        $QE_UNFOLD_DISCOVERED_PRIMITIVE"
			echo " pure 超胞结构：       $QE_UNFOLD_DISCOVERED_PRISTINE"
			echo " 掺杂/缺陷超胞结构：  $QE_UNFOLD_DISCOVERED_DEFECT"
			echo " 结构判定：            $QE_UNFOLD_DISCOVERY_SUMMARY"
			echo '-----------------------------------------------------------------'
			echo ' 0) 确认使用以上三个识别结果'
			echo ' 1) 不采用识别结果，进入手动指定'
			echo ' 2) 取消'
			echo '================================================================='
			while true; do
				echo ' 请确认自动识别结果：'
				if ! read -r confirm_choice; then
					confirm_choice=1
					echo ' 未收到明确确认，不采用自动识别结果。'
				fi
				case "$confirm_choice" in
					0)
						primitive_cif="$QE_UNFOLD_DISCOVERED_PRIMITIVE"
						pristine_supercell_cif="$QE_UNFOLD_DISCOVERED_PRISTINE"
						defect_supercell_cif="$QE_UNFOLD_DISCOVERED_DEFECT"
						echo ' 已确认采用自动识别结果。'
						break
						;;
					1)
						echo ' 未采用自动识别结果，请在参数菜单中手动指定三个结构。'
						break
						;;
					2) return 1 ;;
					*) echo ' 请输入 0、1 或 2。' ;;
				esac
			done
		else
			echo " 自动结构识别未得到唯一结果：$QE_UNFOLD_DISCOVERY_SUMMARY"
			echo ' 请在菜单中手动指定三个结构。'
		fi
	elif [ -z "$primitive_cif" ] || [ -z "$pristine_supercell_cif" ] || [ -z "$defect_supercell_cif" ]; then
		echo ' 检测到不完整的 QE_UNFOLD_*_CIF 环境变量；缺少的结构请在菜单中手动指定。'
	fi
	calc_prefix="${QE_UNFOLD_PREFIX:-${defect_supercell_cif##*/}}"
	[ -n "$calc_prefix" ] || calc_prefix=unfold
	calc_prefix="${calc_prefix%.cif}"
	calc_prefix="${calc_prefix%.[vV][aA][sS][pP]}"
	k_spacing="${QE_UNFOLD_KPATH_SPACING:-0.01}"
	first_band="${QE_UNFOLD_FIRST_BAND:-1}"
	input_timeout="${QE_UNFOLD_INPUT_TIMEOUT:-15}"

	while true; do
		echo
		echo '=========================== unfold 输入参数 ==========================='
		echo " 0) 使用当前参数生成（15 秒无操作自动选择）"
		echo " 1) 母相原胞结构（CIF/VASP）：${primitive_cif}"
		echo " 2) pure 超胞结构（CIF/VASP）：${pristine_supercell_cif}"
		echo " 3) 掺杂/缺陷超胞结构（CIF/VASP）：${defect_supercell_cif}"
		echo " 4) 计算前缀：${calc_prefix}"
		echo " 5) 原胞高对称路径 K 点间距：${k_spacing} 1/Angstrom"
		echo ' 6) 取消'
		echo '======================================================================'
		QBOX_INPUT_MENU_TIMEOUT="$input_timeout" qe_read_choice_with_timeout choice 0
		case "$choice" in
			0) break ;;
			1) echo ' 请输入母相原胞 CIF/VASP：'; read -r value; [ -n "$value" ] && primitive_cif="$value" ;;
			2) echo ' 请输入 pure 超胞 CIF/VASP：'; read -r value; [ -n "$value" ] && pristine_supercell_cif="$value" ;;
			3) echo ' 请输入掺杂/缺陷超胞 CIF/VASP：'; read -r value; [ -n "$value" ] && defect_supercell_cif="$value" ;;
			4) echo ' 请输入计算前缀：'; if read -r value && [ -n "$value" ] && qe_validate_calc_prefix "$value"; then calc_prefix="$value"; fi ;;
			5) echo ' 请输入目标 K 点间距，单位 1/Angstrom：'; read -r value; echo "$value" | awk 'NF==1&&$1~/^[0-9]+([.][0-9]+)?$/&&$1>0{exit 0}{exit 1}' && k_spacing="$value" ;;
			6) return 1 ;;
			*) echo ' 请输入 0-6。' ;;
		esac
	done

	for value in "$primitive_cif" "$pristine_supercell_cif" "$defect_supercell_cif"; do
		[ -n "$value" ] || { echo ' 错误：三个 unfold 结构文件均必须指定。'; return 1; }
	done
	qe_validate_calc_prefix "$calc_prefix" || return 1
	qe_auto_convert_vasp_to_cif "$primitive_cif" || return 1
	primitive_cif="$QE_AUTO_CONVERTED_CIF"
	qe_auto_convert_vasp_to_cif "$pristine_supercell_cif" || return 1
	pristine_supercell_cif="$QE_AUTO_CONVERTED_CIF"
	qe_auto_convert_vasp_to_cif "$defect_supercell_cif" || return 1
	defect_supercell_cif="$QE_AUTO_CONVERTED_CIF"

	for value in "$primitive_cif" "$pristine_supercell_cif" "$defect_supercell_cif"; do
		[ -f "$value" ] || { echo " 错误：缺少结构文件：$value"; return 1; }
	done
	defect_abs=`readlink -f "$defect_supercell_cif"`
	qe_unfold_prepare_geometry "$primitive_cif" "$pristine_supercell_cif" "$defect_supercell_cif" "$k_spacing" "$output_dir" || return 1
	ln -sfn "$defect_abs" "$output_dir/${calc_prefix}.cif"

	qe_print_input_generation_header "${output_dir}/${calc_prefix}.scf.in" "pw.x / SCF（unfold）"
	echo ' 进入 unfold SCF 的 pw.x 参数菜单；15 秒无操作将按当前默认值生成。'
	(
		cd "$output_dir" || exit 1
		fname1="${calc_prefix}.cif" prefix="$calc_prefix" PRESET_RTASK=energy RETURN_TO_EXEC_CALC=1 \
		PWIN_DEFAULT_PSEUDOLIB=PD04 PWIN_DEFAULT_ODD_ELECTRON_DEGAUSS=0.002 \
		QBOX_INPUT_MENU_TIMEOUT="$input_timeout" pwin
	) || return 1

	qe_print_input_generation_header "${output_dir}/${calc_prefix}.bands.in" "pw.x / bands（unfold）"
	echo ' 进入 unfold bands 的 pw.x 参数菜单；15 秒无操作将按当前默认值生成。'
	(
		cd "$output_dir" || exit 1
		fname1="${calc_prefix}.cif" prefix="$calc_prefix" PRESET_RTASK=bands RETURN_TO_EXEC_CALC=1 \
		PWIN_DEFAULT_PSEUDOLIB=PD04 PWIN_DEFAULT_BAND_KPATH_MODE=spacing \
		PWIN_DEFAULT_BAND_KPATH_SPACING="$k_spacing" PWIN_LOCK_BANDS_KPATH=1 \
		PWIN_DEFAULT_BANDS_NBND_FACTOR=1.2 \
		PWIN_DEFAULT_ODD_ELECTRON_DEGAUSS=0.002 QBOX_INPUT_MENU_TIMEOUT="$input_timeout" pwin
	) || return 1

	qe_unfold_patch_bands_input "$output_dir/${calc_prefix}.bands.in" "$output_dir/unfold-kpoints.in" || return 1
	qe_unfold_validate_nc_pseudos "$output_dir/${calc_prefix}.scf.in" || return 1
	qe_unfold_validate_nc_pseudos "$output_dir/${calc_prefix}.bands.in" || return 1
	qe_unfold_validate_pw_pair "$output_dir/${calc_prefix}.scf.in" "$output_dir/${calc_prefix}.bands.in" || return 1
	nbnd=`qe_unfold_read_nbnd "$output_dir/${calc_prefix}.bands.in"`
	if ! echo "$nbnd" | awk '$1~/^[0-9]+$/&&$1>0{exit 0}{exit 1}'; then
		echo " 错误：${output_dir}/${calc_prefix}.bands.in 未显式设置有效 nbnd。"
		return 1
	fi
	if [ "$first_band" -gt "$nbnd" ]; then
		echo " 错误：first_band=${first_band} 大于 nbnd=${nbnd}。"
		return 1
	fi
	qe_print_input_generation_header "${output_dir}/unfold.in" "unfold.x / 能带展开"
	qe_unfold_write_input "$calc_prefix" "$first_band" "$nbnd" "$output_dir" || return 1
	printf '%s\n' "$calc_prefix" > "$output_dir/unfold.prefix"
	echo
	echo " unfold 输入已生成：${output_dir}/${calc_prefix}.scf.in、${output_dir}/${calc_prefix}.bands.in、${output_dir}/unfold.in"
}

function run_qe_unfold_calculation (){
	local output_dir calc_prefix scf_input bands_input pw_threads unfold_threads status value
	output_dir=UNFOLD
	if [ ! -s "$output_dir/unfold.prefix" ]; then
		echo ' 缺少 unfold 输入文件，进入 unfold 输入文件生成功能。'
		qe_generate_unfold_inputs || return 1
	fi
	calc_prefix=`head -n 1 "$output_dir/unfold.prefix"`
	scf_input="${calc_prefix}.scf.in"
	bands_input="${calc_prefix}.bands.in"
	for value in "$output_dir/$scf_input" "$output_dir/$bands_input" "$output_dir/unfold.in"; do
		[ -f "$value" ] || { echo " 缺少 $value，重新进入 unfold 输入文件生成功能。"; qe_generate_unfold_inputs || return 1; break; }
	done
	calc_prefix=`head -n 1 "$output_dir/unfold.prefix"`
	scf_input="${calc_prefix}.scf.in"
	bands_input="${calc_prefix}.bands.in"
	pw_threads=`qe_prompt_positive_int_default ' 请输入 SCF/bands 的 MPI 进程数，直接回车使用 16。' 16`
	unfold_threads=`qe_prompt_positive_int_default ' 请输入 unfold.x 的 MPI 进程数，直接回车使用 16。' 16`
	qe_ensure_runtime_for mpirun pw.x unfold.x || return 1
	(
		cd "$output_dir" || exit 1
		set -o pipefail
		mpirun -np "$pw_threads" pw.x -in "$scf_input" 2>&1 | tee scf.out &&
		qe_output_success scf.out &&
		mpirun -np "$pw_threads" pw.x -in "$bands_input" 2>&1 | tee bands.out &&
		qe_output_success bands.out &&
		mpirun -np "$unfold_threads" unfold.x -in unfold.in 2>&1 | tee unfold.out
	)
	status=$?
	if [ "$status" -eq 0 ] && [ -s "$output_dir/enk.dat" ] && [ -s "$output_dir/wnk.dat" ]; then
		qe_unfold_plot_results "$output_dir" || echo ' 警告：unfold 数据已生成，但自动绘图失败。'
		echo ' unfold 计算完成：UNFOLD/enk.dat、UNFOLD/wnk.dat'
		return 0
	fi
	echo ' unfold 计算失败或未生成 enk.dat/wnk.dat。'
	return 1
}

