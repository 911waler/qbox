#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function run_qe_phonon_calculation (){
    local choice directory file_prefix prepare_status recalculate has_completed=0
    local index stage stage_status stage_rc=0 invalid_upstream=0 compute_required=0
    local scf_processes='' ph_processes='' recommended_processes
    local stages=(scf ph q2r matdyn plot)
    local labels=('SCF' 'ph.x' 'q2r.x' 'matdyn.x' '声子谱绘图')
    local completed=() required=() statuses=(notrun notrun notrun notrun notrun)
    local source_args=() command_args=()

    echo
    echo ' 请选择声子计算任务：'
    echo '  1) 声子谱'
    echo '  2) 返回'
    qe_read_choice choice '1 2' ' 请输入 1 或 2。' || return 1
    if [ "$choice" = 2 ]; then
        [ -n "${QE_DIRECT_ACTION:-}" ] || qe_request_main_menu
        return 0
    fi

    directory="$(pwd -P)/PHONON"
    [ -z "${fname1:-}" ] || source_args=(--source "$fname1")
    qbox_python -m qbox.io.phonon_workflow prepare --directory "$directory" "${source_args[@]}"
    prepare_status=$?
    if [ "$prepare_status" -eq 10 ]; then
        [ -n "${QE_DIRECT_ACTION:-}" ] || qe_request_main_menu
        return 0
    elif [ "$prepare_status" -ne 0 ]; then
        return "$prepare_status"
    fi
    file_prefix="$(qbox_python -m qbox.io.phonon_workflow info --directory "$directory")" || return 1
    qe_validate_calc_prefix "$file_prefix" || return 1

    for stage in "${stages[@]}"; do
        if qbox_python -m qbox.io.phonon_workflow check --directory "$directory" --stage "$stage"; then
            completed+=(1)
            has_completed=1
        else
            completed+=(0)
        fi
    done
    recalculate="$(qe_prompt_recalculate_completed "$has_completed" \
        ' 检测到已有声子计算结果。是否重新计算已完成步骤？')" || return 1

    # Running an upstream stage invalidates all later backend records. Account
    # for that before asking which MPI process counts will actually be needed.
    for index in "${!stages[@]}"; do
        if [ "$recalculate" = yes ] || [ "${completed[$index]}" -eq 0 ]; then
            invalid_upstream=1
        fi
        required+=("$invalid_upstream")
        if [ "$index" -lt 4 ] && [ "$invalid_upstream" -eq 1 ]; then
            compute_required=1
        fi
    done
    if [ "$compute_required" -eq 1 ]; then
        qe_ensure_runtime_for mpirun pw.x ph.x q2r.x matdyn.x || return 1
        qe_report_compute_resources
        recommended_processes="$(cd "$directory" && qe_recommend_pw_threads "$file_prefix" scf)" || return 1
        if [ "${required[0]}" -eq 1 ]; then
            scf_processes="$(qe_prompt_positive_int_default \
                " 请输入 SCF pw.x 使用的 MPI 进程数。直接回车使用推荐值 ${recommended_processes}。" \
                "$recommended_processes")" || return 1
        fi
        if [ "${required[1]}" -eq 1 ]; then
            ph_processes="$(qe_prompt_positive_int_default \
                " 请输入 ph.x 使用的 MPI 进程数。直接回车使用推荐值 ${recommended_processes}。" \
                "$recommended_processes")" || return 1
        fi
    fi

    for index in "${!stages[@]}"; do
        stage="${stages[$index]}"
        if [ "$recalculate" = no ] && \
            qbox_python -m qbox.io.phonon_workflow check --directory "$directory" --stage "$stage"; then
            statuses[$index]=skipped
            continue
        fi
        if ! qbox_python -m qbox.io.phonon_workflow begin --directory "$directory" --stage "$stage"; then
            statuses[$index]=failed
            stage_rc=1
            break
        fi
        case "$stage" in
            scf) command_args=(mpirun -np "$scf_processes" pw.x -in "$file_prefix.scf.in") ;;
            ph) command_args=(mpirun -np "$ph_processes" ph.x -in "$file_prefix.ph.in") ;;
            q2r) command_args=(q2r.x -in "$file_prefix.q2r.in") ;;
            matdyn) command_args=(matdyn.x -in "$file_prefix.matdyn.in") ;;
            plot) command_args=(qbox_python -m qbox.postprocess.phonon_plot \
                -i "$file_prefix.freq.gp" --path "$file_prefix.path.json") ;;
        esac
        echo " 开始 ${labels[$index]}。"
        qe_run_stage stage_status "$directory" "$stage.out" qbox_python \
            -m qbox.io.phonon_workflow finish --directory "$directory" --stage "$stage" -- \
            "${command_args[@]}"
        stage_rc=$?
        if [ "$stage_rc" -ne 0 ]; then
            statuses[$index]=failed
            break
        fi
        statuses[$index]="$stage_status"
    done

    echo
    echo ' 声子计算总结：'
    for index in "${!stages[@]}"; do
        if [ "${statuses[$index]}" = notrun ]; then
            echo " ${labels[$index]}：未执行"
        else
            qe_print_status_line "${labels[$index]}" "${statuses[$index]}"
        fi
    done
    echo " 计算文件与日志：$directory"
    return "$stage_rc"
}
