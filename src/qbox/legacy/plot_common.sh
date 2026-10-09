#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function plot_qe_phonon (){
	local source_args=()
	case "${fname1-}" in
		*.freq.gp|*.freq)
			source_args=(-i "$fname1")
			;;
	esac
	qbox_python -m qbox.postprocess.phonon_plot --interactive "${source_args[@]}"
}

function plot_qe_band (){
	local bands_file output_prefix zero_reference zero_arg band_input_file bands_output_file
	local plot_scope calc_prefix band_input_path
	local band_input_arg=()
	local bands_output_arg=()

	plot_scope=`qe_prompt_plot_data_scope "能带图"`
	if [ "$plot_scope" == "calcdir" ]; then
		calc_prefix=`qe_prompt_calc_prefix`
		bands_file="BAND/bands.dat.gnu"
		if [ ! -f "$bands_file" ]; then
			echo
			echo " 错误：未找到执行计算目录中的能带数据文件：$bands_file"
			return 1
		fi
		band_input_path=""
		if [ -f "BAND/${calc_prefix}.bands.in" ]; then
			band_input_path="${calc_prefix}.bands.in"
		elif [ -f "BAND/${calc_prefix}.band.in" ]; then
			band_input_path="${calc_prefix}.band.in"
		fi
		if [ -n "$band_input_path" ]; then
			band_input_arg=(--band-input "$band_input_path")
		fi
		if [ -f "BAND/bands.out" ]; then
			bands_output_arg=(--bands-output "bands.out")
		fi
		zero_reference=`qe_prompt_energy_reference "能带图"`
		output_prefix="${calc_prefix}_band_structure_${zero_reference}"
		(
			cd BAND || exit 1
			qe_embedded_plot_band -i bands.dat.gnu -o "$output_prefix" "${band_input_arg[@]}" "${bands_output_arg[@]}" --zero-reference "$zero_reference"
		)
		return $?
	fi

	bands_file="$fname1"
	if [ -z "${QBOX_TASK_ID:-}" ] && [ "$fname2" == "20" ]; then
		case "$bands_file" in
			*.cif|*.gjf|*.xyz|*.vasp|POSCAR|CONTCAR) bands_file="" ;;
		esac
	fi
	if [ -z "$bands_file" ] || { [ -z "${QBOX_TASK_ID:-}" ] && [ "$bands_file" == "20" ]; }; then
		bands_file="bands.dat.gnu"
	fi

	if [ ! -f "$bands_file" ]; then
		echo
		echo " 错误：未找到能带数据文件 '$bands_file'。请在含 bands.dat.gnu 的目录运行，或指定文件路径。"
		return 1
	fi

	echo
	echo ' 请输入 pw.x bands 计算输入文件，用于读取高对称点标签。直接回车自动寻找包含 K_POINTS crystal_b 的 .in 文件。'
	read band_input_file
	if [ -n "$band_input_file" ]; then
		if [ ! -f "$band_input_file" ]; then
			echo
			echo " 错误：未找到输入文件 '$band_input_file'。"
			return 1
		fi
		band_input_arg=(--band-input "$band_input_file")
	fi

	echo
	echo ' 请输入 bands.x 输出文件，用于读取高对称点横坐标。直接回车自动寻找 bands.out/band.out。'
	read bands_output_file
	if [ -n "$bands_output_file" ]; then
		if [ ! -f "$bands_output_file" ]; then
			echo
			echo " 错误：未找到输出文件 '$bands_output_file'。"
			return 1
		fi
		bands_output_arg=(--bands-output "$bands_output_file")
	fi

	echo
	echo ' 请输入输出文件名前缀，直接回车使用 band_structure。'
	read output_prefix
	if [ -z "$output_prefix" ]; then
		output_prefix="band_structure"
	fi

	echo
	zero_reference=`qe_prompt_energy_reference "能带图"`
	zero_arg="--zero-reference ${zero_reference}"

	qe_embedded_plot_band -i "$bands_file" -o "$output_prefix" "${band_input_arg[@]}" "${bands_output_arg[@]}" --zero-reference "$zero_reference"
}

function qe_prompt_plot_data_scope (){
	local context="$1"
	local choice
	echo >&2
	echo " 请选择${context}绘图数据位置：" >&2
	echo '  1) 当前目录' >&2
	echo '  2) 按执行计算目录寻找' >&2
	read -r choice || return 1
	while [ "$choice" != "1" ] && [ "$choice" != "2" ]; do
		echo ' 请输入 1 或 2。' >&2
		read -r choice || return 1
	done
	if [ "$choice" == "2" ]; then
		echo "calcdir"
	else
		echo "current"
	fi
}

function qe_prompt_positive_int (){
	local prompt value
	prompt="$1"
	while true; do
		echo "$prompt" >&2
		read -r value || return 1
		if echo "$value" | awk 'NF==1 && $1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
			echo "$value"
			return 0
		fi
		echo ' 请输入正整数。' >&2
	done
}

function qe_prompt_energy_reference (){
	local context="$1"
	local choice timeout default_choice read_status
	timeout="$QE_ENERGY_REFERENCE_TIMEOUT"
	default_choice="$QE_ENERGY_REFERENCE_DEFAULT_CHOICE"
	if [ -z "$default_choice" ]; then
		default_choice="1"
	fi
	echo " 请选择${context}的能量零点：" >&2
	echo '  1) Fermi level 归零' >&2
	echo '  2) CBM 归零' >&2
	echo '  3) VBM 归零' >&2
	echo '  4) 不平移' >&2
	if echo "$timeout" | awk '$1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
		if read -r -t "$timeout" choice; then
			:
		else
			read_status=$?
			if [ "$read_status" -le 128 ]; then
				return "$read_status"
			fi
			echo >&2
			echo " 未检测到输入，默认选择 Fermi level 归零。" >&2
			choice="$default_choice"
		fi
	else
		if ! read -r choice; then
			return 1
		fi
	fi
	while [ "$choice" != "1" ] && [ "$choice" != "2" ] && [ "$choice" != "3" ] && [ "$choice" != "4" ]; do
		echo ' 请输入 1、2、3 或 4。' >&2
		read -r choice || return 1
	done

	if [ "$choice" == "1" ]; then
		echo "fermi"
	elif [ "$choice" == "2" ]; then
		echo "cbm"
	elif [ "$choice" == "3" ]; then
		echo "vbm"
	else
		echo "none"
	fi
}

function qe_prompt_positive_int_default (){
	local prompt default_value value
	prompt="$1"
	default_value="$2"
	while true; do
		echo "$prompt" >&2
		read -r value || return 1
		if [ -z "$value" ]; then
			value="$default_value"
		fi
		if echo "$value" | awk 'NF==1 && $1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
			echo "$value"
			return 0
		fi
		echo ' 请输入正整数。' >&2
	done
}

function qe_prompt_calc_prefix (){
	local default_prefix calc_prefix_input
	default_prefix=""
	if [ -n "$fname1" ] && [ -f "$fname1" ]; then
		default_prefix="$(qe_calc_prefix_from_path "$fname1")" || default_prefix=""
	fi

	if [ -n "$default_prefix" ]; then
		echo " 请输入计算文件前缀。直接回车使用：${default_prefix}" >&2
	else
		echo ' 请输入计算文件前缀。' >&2
	fi

	if ! read -r calc_prefix_input; then
		return 1
	fi
	if [ -z "$calc_prefix_input" ] && [ -n "$default_prefix" ]; then
		calc_prefix_input="$default_prefix"
	fi

	while [ -z "$calc_prefix_input" ]; do
		echo ' 请输入计算文件前缀。' >&2
		if ! read -r calc_prefix_input; then
			return 1
		fi
	done
	qe_validate_calc_prefix "$calc_prefix_input" || return 1
	echo "$calc_prefix_input"
}

function qe_validate_calc_prefix (){
	local value="$1"
	if [ -z "$value" ] || [[ "$value" == *[!a-zA-Z0-9._-]* ]] || [[ "$value" == .* ]] || [[ "$value" == *..* ]]; then
		echo " 错误：计算前缀只能包含字母、数字、下划线、连字符和单个点，禁止路径分隔符、空格和 ..。" >&2
		return 1
	fi
	return 0
}

function qe_find_structure_for_prefix (){
	local calc_prefix candidate
	calc_prefix="$1"
	for candidate in "${calc_prefix}.cif" "${calc_prefix}.gjf" "${calc_prefix}.xyz" "${calc_prefix}.vasp" "${calc_prefix}.pdb"; do
		if [ -f "$candidate" ]; then
			echo "$candidate"
			return 0
		fi
	done
	for candidate in *.cif *.gjf *.xyz *.vasp *.pdb; do
		if [ -f "$candidate" ]; then
			echo "$candidate"
			return 0
		fi
	done
	return 1
}

function qe_count_atoms_from_structure_file (){
	local structure_file="$1"
	case "$structure_file" in
		*.cif)
			awk '
				BEGIN{in_loop=0; in_atom=0; n=0}
				/^[ \t]*loop_[ \t]*$/ {in_loop=1; in_atom=0; next}
				in_loop && /^[ \t]*_atom_site_/ {in_atom=1; next}
				in_loop && in_atom && /^[ \t]*_/ {next}
				in_loop && in_atom && NF>0 {
					if($1 ~ /^#/) next
					if($1=="loop_" || $1 ~ /^data_/) {print n; exit}
					n++
				}
				END{if(n>0) print n}
			' "$structure_file" | tail -n 1
			;;
		*.xyz)
			awk 'NR==1 && $1 ~ /^[0-9]+$/ {print $1}' "$structure_file"
			;;
		*)
			echo ""
			;;
	esac
}

function qe_estimate_atom_count (){
	local calc_prefix scf_file structure_file nat
	calc_prefix="$1"
	scf_file="${calc_prefix}.scf.in"

	if [ -f "$scf_file" ]; then
		nat=`awk 'tolower($0) ~ /^[[:space:]]*nat[[:space:]]*=/ {gsub(/,/, "", $3); print $3; exit}' "$scf_file"`
		if echo "$nat" | awk '$1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
			echo "$nat"
			return 0
		fi
	fi

	structure_file=`qe_find_structure_for_prefix "$calc_prefix"`
	if [ -n "$structure_file" ]; then
		nat=`qe_count_atoms_from_structure_file "$structure_file"`
		if echo "$nat" | awk '$1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
			echo "$nat"
			return 0
		fi
	fi

	echo ""
}

function qe_recommend_projwfc_threads (){
	local calc_prefix nat
	calc_prefix="$1"
	nat=`qe_estimate_atom_count "$calc_prefix"`

	if ! echo "$nat" | awk '$1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
		echo "16"
		return 0
	fi

	if [ "$nat" -le 20 ]; then
		echo "4"
	elif [ "$nat" -le 100 ]; then
		echo "8"
	elif [ "$nat" -le 300 ]; then
		echo "16"
	elif [ "$nat" -le 800 ]; then
		echo "24"
	else
		echo "32"
	fi
}

function qe_physical_cpu_cores (){
	local physical
	physical="$(qbox_python -m qbox.cpu_resources --physical-count 2>/dev/null)"
	if [[ "$physical" =~ ^[1-9][0-9]*$ ]]; then
		echo "$physical"
		return 0
	fi
	# A conservative recommendation when physical topology is unavailable.
	# The resource report shows 'unknown'; never label logical CPUs as cores.
	echo "1"
}

function qe_report_cpu_resources (){
	qbox_python -m qbox.cpu_resources >&2 || {
		printf ' 当前机器物理核心总数：未知\n 估算空闲物理核心数：未知\n' >&2
	}
}

function qe_report_compute_resources (){
	if [ "$(qe_runtime_accelerator)" = gpu ]; then
		qbox_python -m qbox.gpu_resources >&2 || {
			printf ' 当前机器 GPU 数量：未知\n 空闲 GPU 数量：未知\n' >&2
		}
	else
		qe_report_cpu_resources
	fi
}

function qe_min_positive_int (){
	local a="$1"
	local b="$2"
	if [ "$a" -le "$b" ]; then
		echo "$a"
	else
		echo "$b"
	fi
}

function qe_recommend_pw_threads (){
	local calc_prefix task nat cores target
	calc_prefix="$1"
	task="$2"
	nat=`qe_estimate_atom_count "$calc_prefix"`
	cores=`qe_physical_cpu_cores`

	if ! echo "$nat" | awk '$1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
		if [ "$task" == "nscf" ]; then
			target=32
		else
			target=16
		fi
		qe_min_positive_int "$target" "$cores"
		return 0
	fi

	if [ "$task" == "nscf" ]; then
		if [ "$nat" -le 20 ]; then
			target=24
		elif [ "$nat" -le 100 ]; then
			target=48
		elif [ "$nat" -le 300 ]; then
			target=96
		elif [ "$nat" -le 800 ]; then
			target=128
		else
			target=192
		fi
	else
		if [ "$nat" -le 20 ]; then
			target=16
		elif [ "$nat" -le 100 ]; then
			target=32
		elif [ "$nat" -le 300 ]; then
			target=64
		elif [ "$nat" -le 800 ]; then
			target=96
		else
			target=128
		fi
	fi

	qe_min_positive_int "$target" "$cores"
}
