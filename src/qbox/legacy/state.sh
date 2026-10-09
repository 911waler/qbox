#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_read_choice_with_timeout (){
	local variable_name="$1" default_value="$2" timeout input_value read_status
	timeout="${QBOX_INPUT_MENU_TIMEOUT:-}"
	if echo "$timeout" | awk 'NF==1 && $1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
		if read -r -t "$timeout" input_value; then
			:
		else
			read_status=$?
			if [ "$read_status" -le 128 ]; then
				return "$read_status"
			fi
			echo
			echo " ${timeout} 秒内未检测到输入，使用默认选择 ${default_value}。"
			input_value="$default_value"
		fi
	else
		if ! read -r input_value; then
			return 1
		fi
	fi
	printf -v "$variable_name" '%s' "$input_value"
}

function qe_print_input_generation_header (){
	local input_file="$1" task_label="$2" separator
	local input_text task_text input_width task_width separator_width input_padding task_padding
	input_text="生成输入文件：${input_file}"
	task_text="程序与任务：${task_label}"
	input_width=`printf '%s\n' "$input_text" | wc -L`
	task_width=`printf '%s\n' "$task_text" | wc -L`
	separator_width=100
	[ $((input_width + 4)) -gt "$separator_width" ] && separator_width=$((input_width + 4))
	[ $((task_width + 4)) -gt "$separator_width" ] && separator_width=$((task_width + 4))
	input_padding=$(((separator_width - input_width) / 2))
	task_padding=$(((separator_width - task_width) / 2))
	printf -v separator '%*s' "$separator_width" ''
	separator="${separator// /=}"
	echo
	echo "$separator"
	printf '%*s%s\n' "$input_padding" '' "$input_text"
	printf '%*s%s\n' "$task_padding" '' "$task_text"
	echo "$separator"
}

QE_CLEANUP_PATHS=()

function qe_cleanup_path_is_managed (){
    case "${1##*/}" in
        .qbox-*|qbox-*|.*.qbox.*) return 0 ;;
        *) return 1 ;;
    esac
}

function qe_cleanup_register (){
    local path="$1"
    [ -n "$path" ] && qe_cleanup_path_is_managed "$path" || return 2
    QE_CLEANUP_PATHS+=("$path")
}

function qe_cleanup_unregister (){
    local target="$1" path kept=()
    for path in "${QE_CLEANUP_PATHS[@]}"; do [ "$path" = "$target" ] || kept+=("$path"); done
    QE_CLEANUP_PATHS=("${kept[@]}")
}

function qe_cleanup_all (){
    local path
    for path in "${QE_CLEANUP_PATHS[@]}"; do
        qe_cleanup_path_is_managed "$path" && rm -rf -- "$path"
    done
    QE_CLEANUP_PATHS=()
}

function qe_structure_context_reset (){
    local variable_name
    while IFS= read -r variable_name; do
        unset "$variable_name"
    done < <(compgen -A variable QE_STRUCT_)
    unset natm ntyp begcellpos endcellpos begatmpos endatmpos
    unset atmtype Natmtype
    unset a_1 a_2 a_3 k_1 k_2 k_3
}

function qe_release_structure_context (){
    local structure_dir="${QE_STRUCT_DIR-}" path registered=0 status=0
    if [ -n "$structure_dir" ]; then
        for path in "${QE_CLEANUP_PATHS[@]}"; do
            if [ "$path" = "$structure_dir" ]; then
                registered=1
                break
            fi
        done
        if [ "$registered" -eq 1 ]; then
            if [ -e "$structure_dir" ] || [ -L "$structure_dir" ]; then
                rm -rf -- "$structure_dir" || status=$?
                if [ "$status" -ne 0 ]; then
                    return "$status"
                fi
            fi
            qe_cleanup_unregister "$structure_dir"
        fi
    fi
    qe_structure_context_reset
    return "$status"
}

function qe_release_structure_context_with_status (){
    local requested_status="${1-0}" release_status
    qe_release_structure_context
    release_status=$?
    if [ "$release_status" -ne 0 ]; then
        return "$release_status"
    fi
    return "$requested_status"
}

function qe_prepare_structure_context (){
    local input_file="${1-}" converted_file context_dir structure_tmp
    local multiwfn_command multiwfn_log local_input converted_basename
    local local_output='structure_QE.tmp' multiwfn_status parsed parser_status key value
    local i line_index a_var x_var y_var z_var k_var type_var count_var
    local release_status

    qe_release_structure_context
    release_status=$?
    [ "$release_status" -eq 0 ] || return "$release_status"

    [ -n "$input_file" ] || {
        echo ' 错误：结构输入路径不能为空。' >&2
        return 1
    }

    qe_set_input_path "$input_file" || return 1
    qe_auto_convert_vasp_to_cif "$input_file" || return 1
    converted_file="$QE_AUTO_CONVERTED_CIF"
    [ -f "$converted_file" ] || {
        echo " 错误：未找到结构文件 '$converted_file'。" >&2
        return 1
    }
    qe_validate_calc_prefix "$prefix" || return 1
    require_multiwfn || return 1
    multiwfn_command="$(qbox_find_multiwfn)" || return 1

    context_dir="$(mktemp -d "$PWD/.qbox-structure.XXXXXX")" || {
        echo ' 错误：无法创建结构解析临时目录。' >&2
        return 1
    }
    qe_cleanup_register "$context_dir" || {
        rm -rf -- "$context_dir"
        return 1
    }
    structure_tmp="$context_dir/${prefix}_QE.tmp"
    multiwfn_log="$context_dir/multiwfn.log"
    converted_basename="${converted_file##*/}"
    case "$converted_basename" in
        *.*) local_input="structure.${converted_basename##*.}" ;;
        *) local_input='structure' ;;
    esac
    QE_STRUCT_INPUT="$converted_file"
    QE_STRUCT_SOURCE="$input_file"
    QE_STRUCT_DIR="$context_dir"
    QE_STRUCT_TMP="$structure_tmp"
    cp -- "$converted_file" "$context_dir/$local_input" || {
        qe_release_structure_context
        return 1
    }

    echo ' 正在调用 Multiwfn 解析晶胞和原子坐标信息....'
    echo
    # Multiwfn uses fixed-length pathname buffers. Short local names avoid
    # truncation even when the project and its nested staging path are long.
    (
        cd -- "$context_dir" || exit 1
        "$multiwfn_command" "$local_input" << EOF_MWIN
100
2
26
$local_output
0
q
EOF_MWIN
    ) >"$multiwfn_log" 2>&1
    multiwfn_status=$?
    if [ "$multiwfn_status" -ne 0 ]; then
        echo " 错误：Multiwfn 结构解析失败（退出码 $multiwfn_status）。" >&2
        tail -n 20 -- "$multiwfn_log" >&2
        qe_release_structure_context
        return "$multiwfn_status"
    fi

    # Retain the public context filename. Legacy shims may already write that
    # name; they now do so inside the private context, never in the caller cwd.
    if [ "$context_dir/$local_output" != "$structure_tmp" ] && [ -s "$context_dir/$local_output" ]; then
        mv -- "$context_dir/$local_output" "$structure_tmp" || {
            qe_release_structure_context
            return 1
        }
    fi
    if [ ! -s "$structure_tmp" ]; then
        echo ' 错误：Multiwfn 未生成有效的 QE 结构文件，请检查以下解析信息。' >&2
        tail -n 20 -- "$multiwfn_log" >&2
        qe_release_structure_context
        return 1
    fi

    parsed="$(awk '
        function is_number(value) {
            return value ~ /^[+-]?[0-9]+([.][0-9]*)?([eEdD][+-]?[0-9]+)?$/ ||
                value ~ /^[+-]?[.][0-9]+([eEdD][+-]?[0-9]+)?$/
        }
        function set_failure(message) {
            print " 错误：" message > "/dev/stderr"
            failed=1
        }
        function remember_type(symbol) {
            if (!(symbol in atom_counts)) {
                type_total++
                type_name[type_total]=symbol
            }
            atom_counts[symbol]++
        }
        {
            line=$0
            if ($0 ~ /^[[:space:]]*nat([[:space:]]*=[[:space:]]*|[[:space:]])/) {
                sub(/^[[:space:]]*nat[[:space:]]*=?[[:space:]]*/, "", line)
                sub(/[,[:space:]].*$/, "", line)
                if (line ~ /^[0-9]+$/) {nat=line+0; nat_set=1}
            }
            line=$0
            if ($0 ~ /^[[:space:]]*ntyp([[:space:]]*=[[:space:]]*|[[:space:]])/) {
                sub(/^[[:space:]]*ntyp[[:space:]]*=?[[:space:]]*/, "", line)
                sub(/[,[:space:]].*$/, "", line)
                if (line ~ /^[0-9]+$/) {ntyp=line+0; ntyp_set=1}
            }
            if ($0 ~ /^[[:space:]]*CELL_PARAMETERS([[:space:]]|$)/) {
                if (!cell_marker) {cell_marker=NR; cell_start=NR+1}
                next
            }
            if (cell_marker && NR >= cell_start && cell_vectors < 3) {
                if (NF < 3 || !is_number($1) || !is_number($2) || !is_number($3)) {
                    set_failure("CELL_PARAMETERS 中存在无效晶格向量。")
                } else {
                    cell_vectors++
                    cell_x[cell_vectors]=$1+0.0
                    cell_y[cell_vectors]=$2+0.0
                    cell_z[cell_vectors]=$3+0.0
                    cell_raw_x[cell_vectors]=$1
                    cell_raw_y[cell_vectors]=$2
                    cell_raw_z[cell_vectors]=$3
                }
                next
            }
            if ($0 ~ /^[[:space:]]*ATOMIC_POSITIONS([[:space:]]|$)/) {
                if (!atom_marker) {atom_marker=NR; atom_start=NR+1}
                next
            }
            if (atom_marker && NR >= atom_start && atom_total < nat) {
                if (NF < 4 || !is_number($2) || !is_number($3) || !is_number($4)) {
                    set_failure("ATOMIC_POSITIONS 中存在无效原子坐标。")
                } else {
                    atom_total++
                    atom_name[atom_total]=$1
                    atom_x[atom_total]=$2
                    atom_y[atom_total]=$3
                    atom_z[atom_total]=$4
                    remember_type($1)
                }
                next
            }
        }
        END {
            if (!nat_set || nat < 1) set_failure("QE 结构缺少有效 nat。")
            if (!ntyp_set || ntyp < 1) set_failure("QE 结构缺少有效 ntyp。")
            if (!cell_marker || cell_vectors != 3) set_failure("Multiwfn 未能生成完整 CELL_PARAMETERS。")
            if (!atom_marker || atom_total != nat) set_failure("Multiwfn 未能生成完整 ATOMIC_POSITIONS。")
            if (type_total != ntyp) set_failure("原子类型数量与 ntyp 不一致。")
            if (failed) exit 1

            for (i=1; i<=type_total; i++) {
                for (j=i+1; j<=type_total; j++) {
                    if (type_name[j] < type_name[i]) {
                        tmp=type_name[i]; type_name[i]=type_name[j]; type_name[j]=tmp
                    }
                }
            }
            printf "QE_STRUCT_NAT=%d\n", nat
            printf "QE_STRUCT_NTYP=%d\n", ntyp
            printf "QE_STRUCT_BEGCELLPOS=%d\n", cell_start
            printf "QE_STRUCT_ENDCELLPOS=%d\n", cell_start+2
            printf "QE_STRUCT_BEGATMPOS=%d\n", atom_start
            printf "QE_STRUCT_ENDATMPOS=%d\n", atom_start+nat-1
            for (i=1; i<=3; i++) {
                vector_length=sqrt(cell_x[i]*cell_x[i]+cell_y[i]*cell_y[i]+cell_z[i]*cell_z[i])
                vector_length=int(vector_length*1000000000)/1000000000
                if (vector_length <= 0) {print " 错误：晶格向量长度必须大于零。" > "/dev/stderr"; exit 1}
                ratio=int((30.0/vector_length)*1000000000)/1000000000
                kval=(ratio > 1.0) ? int(ratio+0.5) : 1
                printf "QE_STRUCT_CELL_%d_X=%.9f\n", i, cell_x[i]
                printf "QE_STRUCT_CELL_%d_Y=%.9f\n", i, cell_y[i]
                printf "QE_STRUCT_CELL_%d_Z=%.9f\n", i, cell_z[i]
                printf "QE_STRUCT_A_%d=%.9f\n", i, vector_length
                printf "QE_STRUCT_K%d=%d\n", i, kval
                printf "QE_STRUCT_CELL_LINE_%d=%s %s %s\n", i, cell_raw_x[i], cell_raw_y[i], cell_raw_z[i]
            }
            min_z=atom_z[1]+0.0
            for (i=2; i<=atom_total; i++) if ((atom_z[i]+0.0) < min_z) min_z=atom_z[i]+0.0
            for (i=1; i<=atom_total; i++) {
                is_bottom=(((atom_z[i]+0.0)-min_z < 1.0e-5) && (min_z-(atom_z[i]+0.0) < 1.0e-5)) ? 1 : 0
                printf "QE_STRUCT_ATOM_LINE_%d=%s\t%s\t%s\t%s\t%d\n", i, atom_name[i], atom_x[i], atom_y[i], atom_z[i], is_bottom
            }
            for (i=1; i<=type_total; i++) {
                printf "QE_STRUCT_TYPE_%d=%s\n", i, type_name[i]
                printf "QE_STRUCT_COUNT_%d=%d\n", i, atom_counts[type_name[i]]
            }
        }
    ' "$structure_tmp")"
    parser_status=$?
    if [ "$parser_status" -ne 0 ]; then
        tail -n 20 -- "$multiwfn_log" >&2
        qe_release_structure_context
        return 1
    fi

    while IFS='=' read -r key value; do
        case "$key" in
            QE_STRUCT_CELL_LINE_*)
                line_index="${key##*_}"
                QE_STRUCT_CELL_LINES[$line_index]="$value"
                ;;
            QE_STRUCT_ATOM_LINE_*)
                line_index="${key##*_}"
                QE_STRUCT_ATOM_LINES[$line_index]="$value"
                ;;
            QE_STRUCT_*) printf -v "$key" '%s' "$value" ;;
        esac
    done <<< "$parsed"

    QE_STRUCT_BEG_CELL="$QE_STRUCT_BEGCELLPOS"
    QE_STRUCT_END_CELL="$QE_STRUCT_ENDCELLPOS"
    QE_STRUCT_BEG_ATOM="$QE_STRUCT_BEGATMPOS"
    QE_STRUCT_END_ATOM="$QE_STRUCT_ENDATMPOS"
    for i in 1 2 3; do
        a_var="QE_STRUCT_A_${i}"
        x_var="QE_STRUCT_CELL_${i}_X"
        y_var="QE_STRUCT_CELL_${i}_Y"
        z_var="QE_STRUCT_CELL_${i}_Z"
        k_var="QE_STRUCT_K${i}"
        printf -v "QE_STRUCT_A${i}_LENGTH" '%s' "${!a_var}"
        printf -v "QE_STRUCT_A${i}_X" '%s' "${!x_var}"
        printf -v "QE_STRUCT_A${i}_Y" '%s' "${!y_var}"
        printf -v "QE_STRUCT_A${i}_Z" '%s' "${!z_var}"
        printf -v "QE_STRUCT_K_${i}" '%s' "${!k_var}"
    done

    natm="$QE_STRUCT_NAT"
    ntyp="$QE_STRUCT_NTYP"
    begcellpos="$QE_STRUCT_BEGCELLPOS"
    endcellpos="$QE_STRUCT_ENDCELLPOS"
    begatmpos="$QE_STRUCT_BEGATMPOS"
    endatmpos="$QE_STRUCT_ENDATMPOS"
    for ((i=1; i<=ntyp; i++)); do
        type_var="QE_STRUCT_TYPE_${i}"
        count_var="QE_STRUCT_COUNT_${i}"
        atmtype[$i]="${!type_var}"
        Natmtype[$i]="${!count_var}"
    done
    for i in 1 2 3; do
        a_var="QE_STRUCT_A_${i}"
        k_var="QE_STRUCT_K${i}"
        printf -v "a_${i}" '%s' "${!a_var}"
        printf -v "k_${i}" '%s' "${!k_var}"
    done
    return 0
}

function qe_generate_in_staging (){
    local kind="${1-}" output="${2-}" generator="${3-}"
    local stage source source_path stage_output status=0 cleanup_status
    [ -n "$kind" ] && [ -n "$output" ] && [ -n "$generator" ] || return 2
    case "$kind" in
        *[!a-zA-Z0-9_-]*) return 2 ;;
    esac
    case "$output" in
        */*|.|..) return 2 ;;
    esac
    [ -n "${QE_STRUCT_TMP-}" ] && [ -f "$QE_STRUCT_TMP" ] || {
        echo ' 错误：生成输入文件前缺少有效的结构上下文。' >&2
        return 1
    }
    qe_validate_calc_prefix "${prefix-}" || return 1
    if [ -L "$output" ] || [ -h "$output" ] || { [ -e "$output" ] && [ ! -f "$output" ]; }; then
        echo " 错误：无法安全替换输入文件 '$output'。" >&2
        return 1
    fi

    stage="$(mktemp -d "$PWD/.qbox-${kind}.XXXXXX")" || return 1
    qe_cleanup_register "$stage" || {
        rm -rf -- "$stage"
        return 1
    }

    stage_output="$stage/$output"
    ln -s -- "$QE_STRUCT_TMP" "$stage/${prefix}_QE.tmp" || status=$?
    if [ "$status" -eq 0 ]; then
        for source in "${prefix}.cif" "${prefix}.vasp" "${prefix}.gjf" "${prefix}.xyz" "${prefix}.pdb"; do
            if [ -e "$source" ]; then
                source_path="$(readlink -f -- "$source")" || { status=1; break; }
                ln -s -- "$source_path" "$stage/$source" || { status=$?; break; }
            fi
        done
    fi
    if [ "$status" -eq 0 ]; then
        (
            cd "$stage" || exit 1
            "$generator"
        )
        status=$?
    fi
    if [ "$status" -eq 0 ]; then
        if [ ! -s "$stage_output" ] || [ ! -f "$stage_output" ] || [ -L "$stage_output" ]; then
            echo " 错误：输入文件生成器未产生完整输出：$output" >&2
            status=1
        elif [ -L "$output" ] || [ -h "$output" ] || { [ -e "$output" ] && [ ! -f "$output" ]; }; then
            echo " 错误：无法安全替换输入文件 '$output'。" >&2
            status=1
        else
            if [ -e "$output" ]; then
                chmod --reference="$output" -- "$stage_output" || status=$?
            fi
            if [ "$status" -eq 0 ]; then
                mv -f -- "$stage_output" "$output" || status=$?
            fi
        fi
    fi
    rm -rf -- "$stage"
    cleanup_status=$?
    if [ "$cleanup_status" -ne 0 ]; then
        return "$cleanup_status"
    fi
    qe_cleanup_unregister "$stage"
    return "$status"
}

function qe_with_temp_dir (){
    local callback="$1" parent="$2" label="$3" temp_dir status
    shift 3
    parent="$(cd -- "$parent" && pwd)" || return 1
    temp_dir="$(mktemp -d "${parent%/}/.qbox-${label}.XXXXXX")" || return 1
    qe_cleanup_register "$temp_dir" || { rm -rf -- "$temp_dir"; return 1; }
    "$callback" "$temp_dir" "$@"
    status=$?
    rm -rf -- "$temp_dir"
    qe_cleanup_unregister "$temp_dir"
    return "$status"
}

function qbox_postprocess_prepare_output (){
    local output_file="$1" output_dir
    [ -n "$output_file" ] || return 2
    [ -L "$output_file" ] && return 1
    [ -e "$output_file" ] && [ ! -f "$output_file" ] && return 1
    output_dir="$(cd -- "$(dirname -- "$output_file")" && pwd)" || return 1
    [ -d "$output_dir" ]
}

function qbox_postprocess_stage_dir (){
    local output_file="$1" label="$2" result_var="${3-}" output_dir created_stage_dir
    [ -n "$result_var" ] || return 2
    [[ "$result_var" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] || return 2
    qbox_postprocess_prepare_output "$output_file" || return $?
    output_dir="$(cd -- "$(dirname -- "$output_file")" && pwd)" || return 1
    created_stage_dir="$(mktemp -d "${output_dir}/.qbox-${label}.XXXXXX")" || return 1
    qe_cleanup_register "$created_stage_dir" || { rm -rf -- "$created_stage_dir"; return 1; }
    printf -v "$result_var" '%s' "$created_stage_dir"
}

function qbox_postprocess_remove_stage (){
    local stage_dir="$1" status=0
    [ -n "$stage_dir" ] || return 0
    rm -rf -- "$stage_dir" || status=$?
    qe_cleanup_unregister "$stage_dir"
    return "$status"
}

function qbox_postprocess_install_output (){
    local staged_file="$1" output_file="$2" status=0
    [ -f "$staged_file" ] && [ ! -L "$staged_file" ] || return 1
    qbox_postprocess_prepare_output "$output_file" || return $?
    if [ -e "$output_file" ]; then
        chmod --reference="$output_file" -- "$staged_file" || status=$?
    fi
    [ "$status" -eq 0 ] && mv -f -- "$staged_file" "$output_file" || status=$?
    return "$status"
}

function qbox_expand_index_spec (){
    qe_expand_index_spec "$1"
}

function qe_expand_index_spec (){
    local spec="$1"
    printf '%s\n' "$spec" | awk -F, '
        NF == 0 {exit 1}
        {
            for (i=1; i<=NF; i++) {
                if ($i ~ /^[1-9][0-9]*$/) { print $i; continue }
                if ($i ~ /^[1-9][0-9]*-[1-9][0-9]*$/) {
                    split($i, range, "-")
                    if (range[1] > range[2]) exit 1
                    for (j=range[1]; j<=range[2]; j++) print j
                    continue
                }
                exit 1
            }
        }
    '
}

function qe_atomic_rewrite (){
    local target="$1" writer="$2" directory base temp_file status mode
    shift 2
    if [ -L "$target" ] || [ -h "$target" ]; then
        return 1
    fi
    if [ -e "$target" ] && [ ! -f "$target" ]; then
        return 1
    fi
    directory="$(cd "$(dirname -- "$target")" && pwd)" || return 1
    base="$(basename -- "$target")"
    temp_file="$(mktemp "$directory/.qbox-${base}.XXXXXX")" || return 1
    qe_cleanup_register "$temp_file" || { rm -f -- "$temp_file"; return 1; }
    "$writer" "$target" "$@" >"$temp_file"
    status=$?
    if [ "$status" -eq 0 ]; then
        chmod --reference="$target" "$temp_file" 2>/dev/null || true
        mv -f -- "$temp_file" "$target" || status=$?
    fi
    [ "$status" -eq 0 ] || rm -f -- "$temp_file"
    qe_cleanup_unregister "$temp_file"
    return "$status"
}

function qe_install_cleanup_traps (){
    trap 'qe_cleanup_status=$?; trap - EXIT; qe_cleanup_all; exit "$qe_cleanup_status"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
}

#####################################################################################################################
# Python scientific implementations are packaged separately under io/ and
# postprocess/. Compatibility wrappers retain the established Bash API.
