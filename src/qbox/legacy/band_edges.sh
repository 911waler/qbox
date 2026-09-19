#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_extract_band_edge_dat (){
	local band_dir="$1"
	local nelec_file="$2"
	local nelec nelec_integer vbm_index cbm_index available_bands band_input

	if [ ! -f "${band_dir}/bands.dat.gnu" ]; then
		echo " 错误：未找到 ${band_dir}/bands.dat.gnu，无法提取 VBM/CBM 数据。"
		return 1
	fi

	if [ ! -f "$nelec_file" ]; then
		echo " 错误：未找到 ${nelec_file}，无法读取 number of electrons。"
		return 1
	fi

	nelec=`awk '
		/number of electrons[[:space:]]*=/ {
			for(i=1;i<=NF;i++){
				if($i=="=" && (i+1)<=NF){print $(i+1); exit}
			}
		}
	' "$nelec_file"`
	if ! echo "$nelec" | awk 'NF==1 && $1 ~ /^[0-9]+([.][0-9]+)?$/ && $1 > 0 {exit 0} {exit 1}'; then
		echo " 错误：未能从 ${nelec_file} 读取有效 number of electrons。"
		return 1
	fi
	nelec_integer=`awk -v n="$nelec" 'BEGIN{
		rounded=int(n+0.5)
		if(n>0 && (n-rounded<1.0e-7) && (rounded-n<1.0e-7)) printf "%d", rounded
	}'`
	if [ -z "$nelec_integer" ]; then
		echo " 错误：当前电子数 ${nelec} 不是整数，无法自动确定 VBM/CBM band index。"
		echo ' 请使用参考能量方法，或手动确认金属/带电体系的目标能带。'
		return 1
	fi

	if [ $((nelec_integer % 2)) -eq 1 ]; then
		band_input=''
		for band_input in "${band_dir}"/*.bands.in "${band_dir}"/*.band.in; do
			[ -f "$band_input" ] && break
			band_input=''
		done
		if [ -n "$band_input" ] && grep -Eqi "^[[:space:]]*nspin[[:space:]]*=[[:space:]]*2([[:space:],]|$)" "$band_input"; then
			echo " 错误：检测到奇数电子体系（nelec=${nelec_integer}）且 ${band_input} 使用 nspin=2。"
			echo ' 自旋极化结果需要分别确认两个自旋通道的 VBM/CBM，不能按非自旋 band index 自动提取。'
			return 1
		fi
		vbm_index=$(((nelec_integer + 1) / 2))
		qe_print_odd_electron_notice "$nelec_integer" "按非自旋单重占据前沿带提取：VBM/SOMO=band ${vbm_index}，CBM/LUMO=band $((vbm_index + 1))"
	else
		vbm_index=$((nelec_integer / 2))
	fi
	cbm_index=$((vbm_index + 1))

	available_bands=`qbox_python -m qbox.postprocess.band_edges "$band_dir/bands.dat.gnu" "$vbm_index" "$cbm_index" "$band_dir/VBM.dat" "$band_dir/CBM.dat"`
	local py_status=$?

	if [ "$py_status" == "0" ]; then
		echo " 已提取最高价带：${band_dir}/VBM.dat（band ${vbm_index}）"
		echo " 已提取最低导带：${band_dir}/CBM.dat（band ${cbm_index}）"
		return 0
	elif [ "$py_status" == "2" ]; then
		echo " 已提取最高价带：${band_dir}/VBM.dat（band ${vbm_index}）"
		echo " 警告：未能提取 ${band_dir}/CBM.dat。"
		echo " 当前 bands.dat.gnu 只有 ${available_bands} 条能带；最低导带需要 band ${cbm_index}。"
		echo " 请在 ${band_dir}/*.bands.in 的 &SYSTEM 中设置 nbnd >= ${cbm_index}，重新运行 pw.x bands 和 bands.x。"
		return 2
	else
		echo " 错误：未能提取 VBM.dat/CBM.dat。当前 bands.dat.gnu 能带数：${available_bands:-未知}。"
		return 1
	fi
}

function qe_extract_band_edge_dat_by_reference (){
	local band_dir="$1"
	local reference_energy="$2"

	if [ ! -f "${band_dir}/bands.dat.gnu" ]; then
		echo " 错误：未找到 ${band_dir}/bands.dat.gnu，无法提取 VBM/CBM 数据。"
		return 1
	fi

	if ! echo "$reference_energy" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/ {exit 0} {exit 1}'; then
		echo " 错误：参考能量无效：${reference_energy}"
		return 1
	fi

	qbox_python -m qbox.postprocess.band_edges_reference "$band_dir/bands.dat.gnu" "$reference_energy" "$band_dir/VBM.dat" "$band_dir/CBM.dat"
	local status=$?
	if [ "$status" == "0" ]; then
		echo " 已按参考能量 ${reference_energy} eV 提取 ${band_dir}/VBM.dat 和 ${band_dir}/CBM.dat。"
	elif [ "$status" == "2" ]; then
		echo " 警告：仅提取到 VBM.dat 或 CBM.dat 中的一部分。请检查参考能量是否位于带隙或目标能量窗口内。"
	else
		echo " 错误：按参考能量提取失败。请检查参考能量是否位于可分辨的价带和导带之间。"
	fi
	return "$status"
}

function qe_plot_extracted_band_edges (){
	local band_dir="$1"
	local output_prefix="${band_dir}/VBM_CBM_on_band"
	if [ ! -f "${band_dir}/bands.dat.gnu" ]; then
		echo " 警告：未找到 ${band_dir}/bands.dat.gnu，跳过 VBM/CBM 叠加绘图。"
		return 1
	fi
	if [ ! -f "${band_dir}/VBM.dat" ] && [ ! -f "${band_dir}/CBM.dat" ]; then
		echo " 警告：未找到 ${band_dir}/VBM.dat 或 ${band_dir}/CBM.dat，跳过叠加绘图。"
		return 1
	fi

	qbox_python -m qbox.postprocess.band_edges_plot "$band_dir/bands.dat.gnu" "$band_dir/VBM.dat" "$band_dir/CBM.dat" "$output_prefix" "$band_dir/bands.out"
}

function qe_extract_band_edges_for_dir (){
	local band_dir="$1"
	local method status command_desc plot_command plot_status reference_energy

	if [ ! -f "${band_dir}/bands.dat.gnu" ]; then
		echo " 错误：未找到 ${band_dir}/bands.dat.gnu。"
		return 1
	fi

	echo
	echo ' 请选择提取方法：'
	echo '  1) 按电子数确定 band index（非自旋体系；偶数电子取 HOMO/LUMO，奇数电子取 SOMO/LUMO）'
	echo '  2) 输入参考能量：提取参考能量下方第一条完整能带为 VBM，上方第一条完整能带为 CBM'
	read method
	case "$method" in
		1)
			if [ "$band_dir" == "BAND" ]; then
				command_desc="qe_extract_band_edge_dat BAND BAND/band.out"
				qe_extract_band_edge_dat BAND BAND/band.out
			else
				command_desc="qe_extract_band_edge_dat . band.out"
				qe_extract_band_edge_dat . band.out
			fi
			status=$?
			;;
		2)
			echo ' 请输入参考能量，单位 eV。'
			read reference_energy
			while ! echo "$reference_energy" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/ {exit 0} {exit 1}'; do
				echo ' 参考能量无效，请输入一个数字，单位 eV。'
				read reference_energy
			done
			command_desc="qe_extract_band_edge_dat_by_reference ${band_dir} ${reference_energy}"
			qe_extract_band_edge_dat_by_reference "$band_dir" "$reference_energy"
			status=$?
			;;
		*)
			echo ' 错误：无效提取方法。'
			return 1
			;;
	esac

	plot_command="qe_plot_extracted_band_edges ${band_dir}"
	if [ "$status" == "0" ] || [ "$status" == "2" ]; then
		qe_plot_extracted_band_edges "$band_dir"
		plot_status=$?
	else
		plot_status=1
	fi

	echo
	echo '=============================== 使用的命令 ==================================='
	echo " 1) ${command_desc}"
	echo " 2) ${plot_command}"
	echo '================================================================================'
	echo
	echo '=============================== 提取总结报告 ================================='
	if [ "$status" == "0" ]; then
		qe_print_status_line 'VBM/CBM 数据是否提取成功' success
	elif [ "$status" == "2" ]; then
		qe_print_status_line 'VBM/CBM 数据是否提取成功' partial
	else
		qe_print_status_line 'VBM/CBM 数据是否提取成功' failed
	fi
	if [ "$plot_status" == "0" ]; then
		qe_print_status_line 'VBM/CBM 叠加绘图是否成功' success
	else
		qe_print_status_line 'VBM/CBM 叠加绘图是否成功' failed
	fi
	echo '================================================================================'
	if [ "$plot_status" != "0" ]; then
		return 1
	fi
	if [ "$status" == "2" ]; then
		return 2
	fi
	return "$status"
}

function extract_qe_band_edges (){
	local data_source plot_scope band_dir

	echo
	echo ' 该功能只读取已有能带数据，不重新运行 QE。'
	echo ' 请选择数据来源：'
	echo '  1) 普通 QE bands.dat.gnu'
	echo '  2) unfold 的 enk.dat/wnk.dat（指定能量分界）'
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
			qe_extract_unfold_band_edges "$band_dir"
			return $?
			;;
		1) ;;
		*) echo ' 错误：请输入 1 或 2。'; return 1 ;;
	esac

	plot_scope=`qe_prompt_plot_data_scope "能带边数据"`
	if [ "$plot_scope" == "calcdir" ]; then
		band_dir="BAND"
	else
		band_dir="."
	fi
	qe_extract_band_edges_for_dir "$band_dir"
}

function qe_find_band_input_for_dir (){
	local band_dir="$1"
	local f
	for f in "${band_dir}"/*.bands.in "${band_dir}"/*.band.in; do
		[ -f "$f" ] && echo "$f" && return 0
	done
	return 1
}

function qe_find_output_file_for_dir (){
	local band_dir="$1"
	local preferred="$2"
	if [ -f "${band_dir}/${preferred}" ]; then
		echo "${band_dir}/${preferred}"
		return 0
	fi
	if [ "$band_dir" != "." ] && [ -f "$preferred" ]; then
		echo "$preferred"
		return 0
	fi
	return 1
}


# >>> BEGIN BUILTIN PYTHON: plot-pdos-QE.py
