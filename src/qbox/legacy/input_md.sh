#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function mdin (){
	local md_gen_status md_context_status

#check the input file
if [ -z "$fname1" ]; then
    echo
    echo ' 请输入结构文件，例如 .cif、.vasp 或 .gjf。'
    if ! read -r fname1; then
        qe_release_structure_context_with_status 1
        return $?
    fi
    while [ -z "$fname1" ]; do
        echo
        echo ' 请输入结构文件，例如 .cif、.vasp 或 .gjf。'
        if ! read -r fname1; then
            qe_release_structure_context_with_status 1
            return $?
        fi
    done
    qe_set_input_path "$fname1" || {
        qe_release_structure_context_with_status 1
        return $?
    }
fi

qe_prepare_structure_context "$fname1"
md_context_status=$?
[ "$md_context_status" -eq 0 ] || return "$md_context_status"
fname1="$QE_STRUCT_INPUT"


kpmesh='gamma'
pseudolib='SSSP'
md_time_ps='5'
md_timestep_fs='0.25'
md_fix_bottom='YES'
md_use_atomic_velocities='YES'






qe_md_menu
md_choice=("0" "1" "2" "3" "4" "5" "6" "7")
if ! read -r md_arg; then
    qe_release_structure_context_with_status 1
    return $?
fi
while ! echo "${md_choice[@]}" | grep -wq "$md_arg"
do
    echo "请输入有效的功能编号..."
    if ! read -r md_arg; then
        qe_release_structure_context_with_status 1
        return $?
    fi
done

while [[ "$md_arg" != "7" ]]; do
    case $md_arg in
        "0")
            echo ' MD 输入文件已在当前文件夹生成。'
            qe_generate_md_input
            md_gen_status=$?
            qe_release_structure_context_with_status "$md_gen_status"
            return $?
            ;;
        "1")
            echo ' ##########################################################'
            echo '若需要修改自动选取 K 网格的精度，可以修改 qbox 文件的'
            echo 'result=$(echo "scale=9; 30 / $a_value" | bc) 中的 30 为其他值'
            echo '---- 20 低精度 结构优化 '
            echo '---- 30 中等精度 能带、态密度计算 '
            echo '---- 40 高精度 光学性质计算、精细能带 '
            echo '---- 50+ 超高精度 不推荐 '
            echo ' ##########################################################'
            echo ' ***手动输入的话，以 2,2,1 这样的格式输入三个方向的 K 点采样密度***'
            echo " 也可以直接输入'gamma', 这样布里渊区会进行Gamma点的单点计算"
            if ! read -r kpmesh; then
                qe_release_structure_context_with_status 1
                return $?
            fi
            while [ -z "$kpmesh" ]; do
                echo
                echo '  请重新输入三个方向的 K 点网格，例如 2,2,1'
                if ! read -r kpmesh; then
                    qe_release_structure_context_with_status 1
                    return $?
                fi
            done
            if [ "$kpmesh" = "gamma" ]; then
                kpmesh='gamma'
            else
                kpmesh=`echo $kpmesh|awk -F , '{printf "%d*%d*%d\n",$1,$2,$3}'`
            fi
            echo '完成！'
            qe_md_menu
            ;;
        "2")
            PS3=''
            pseudolib_array=("SSSP" "PD04" "SG15")
            select ipseudolib in "${pseudolib_array[@]}"; do
                case $ipseudolib in
                    "SSSP"|"PD04"|"SG15") pseudolib="$ipseudolib"; qe_md_menu; break ;;
                    "*") ;;
                esac
            done
            ;;
        "3")
            echo '请输入 MD 模拟总时间，单位 ps，例如 8'
            if ! read -r md_time_ps; then
                qe_release_structure_context_with_status 1
                return $?
            fi
            while [ -z "$md_time_ps" ]; do
                echo '请重新输入 MD 模拟总时间，单位 ps，例如 8'
                if ! read -r md_time_ps; then
                    qe_release_structure_context_with_status 1
                    return $?
                fi
            done
            echo '完成！'
            qe_md_menu
            ;;
        "4")
            PS3=''
            md_fix_array=("YES" "NO")
            select ifixbottom in "${md_fix_array[@]}"; do
                case $ifixbottom in
                    "YES") md_fix_bottom='YES'; qe_md_menu; break ;;
                    "NO") md_fix_bottom='NO'; qe_md_menu; break ;;
                    "*") ;;
                esac
            done
            ;;
        "5")
            echo '请输入 MD 时间步长，单位 fs，例如 0.01'
            if ! read -r md_timestep_fs; then
                qe_release_structure_context_with_status 1
                return $?
            fi
            while [ -z "$md_timestep_fs" ]; do
                echo '请重新输入 MD 时间步长，单位 fs，例如 0.01'
                if ! read -r md_timestep_fs; then
                    qe_release_structure_context_with_status 1
                    return $?
                fi
            done
            echo '完成！'
            qe_md_menu
            ;;
        "6")
            PS3=''
            md_vel_array=("YES" "NO")
            select iusevel in "${md_vel_array[@]}"; do
                case $iusevel in
                    "YES") md_use_atomic_velocities='YES'; qe_md_menu; break ;;
                    "NO") md_use_atomic_velocities='NO'; qe_md_menu; break ;;
                    "*") ;;
                esac
            done
            ;;
    esac
    unset md_arg
    if ! read -r md_arg; then
        qe_release_structure_context_with_status 1
        return $?
    fi
    while ! echo "${md_choice[@]}" | grep -wq "$md_arg"
    do
        echo "请输入有效的功能编号..."
        if ! read -r md_arg; then
            qe_release_structure_context_with_status 1
            return $?
        fi
    done
done

if [[ "$md_arg" == "7" ]]; then
    qe_release_structure_context_with_status 0 || return $?
    qe_request_main_menu
    return 0
fi
}
function qe_md_menu (){
    echo " 0) 立即生成 MD 输入文件"
    echo " 1) 设置 K 点网格，当前：$kpmesh"
    echo " 2) 选择赝势库，当前：$pseudolib"
    echo " 3) 设置模拟总时间，当前：${md_time_ps} ps"
    echo " 4) 固定底层原子，当前：$md_fix_bottom"
    echo " 5) 设置时间步长，当前：${md_timestep_fs} fs"
    echo " 6) 使用 ATOMICs_VELOCITIES 设置团簇/分子速度，当前：$md_use_atomic_velocities"
    echo " 7) 返回"
}

function qe_md_pseudo_dir (){
    pseudo_dir_by_lib "$pseudolib"
}

function qe_md_pseudo_file (){
    local idx=$1
    pseudo_file_by_lib "$pseudolib" "$idx"
}

function qe_generate_md_input_unsafe (){
	    local md_nelec structure_file line line_no symbol x y z bottom coord value cached_bottom_flags=1
	    mdfile="${prefix}.md.in"
    rm -f "$mdfile"

    structure_file="${QE_STRUCT_TMP:-${prefix}_QE.tmp}"
    if ! declare -p QE_STRUCT_CELL_LINES &>/dev/null || [ "${#QE_STRUCT_CELL_LINES[@]}" -ne 3 ] ||
       ! declare -p QE_STRUCT_ATOM_LINES &>/dev/null || [ "${#QE_STRUCT_ATOM_LINES[@]}" -ne "$natm" ]; then
        QE_STRUCT_CELL_LINES=()
        QE_STRUCT_ATOM_LINES=()
        cached_bottom_flags=0
        line_no=0
        while IFS= read -r line; do
            line_no=$((line_no + 1))
            if [ "$line_no" -ge "$begcellpos" ] && [ "$line_no" -le "$endcellpos" ]; then
                read -r x y z _ <<< "$line"
                QE_STRUCT_CELL_LINES[$((line_no - begcellpos + 1))]="$x $y $z"
            elif [ "$line_no" -ge "$begatmpos" ] && [ "$line_no" -le "$endatmpos" ]; then
                read -r symbol x y z _ <<< "$line"
                QE_STRUCT_ATOM_LINES[$((line_no - begatmpos + 1))]="$symbol"$'\t'"$x"$'\t'"$y"$'\t'"$z"$'\t'
            fi
        done < "$structure_file"
    fi
    IFS=$'\t' read -r symbol x y z bottom <<< "${QE_STRUCT_ATOM_LINES[1]}"
    case "$bottom" in 0|1) ;; *) cached_bottom_flags=0 ;; esac

    # QE pw.x uses Rydberg atomic time units for dt.
    # 1 QE time unit = hbar/Ry = 0.048377686531714 fs.
    # Examples: 0.25 fs -> dt=5.167672; 0.50 fs -> dt=10.335343; 1.50 fs -> dt=31.006030.
    md_dt_au="$(awk -v fs="$md_timestep_fs" 'BEGIN{printf "%.6f", fs/0.048377686531714}')"
    # Physical conversion: 1 ps = 1000 fs, nstep = total_time(fs)/time_step(fs).
    md_nstep="$(awk -v ps="$md_time_ps" -v fs="$md_timestep_fs" 'BEGIN{printf "%d", (ps*1000.0/fs)+0.5}')"
    md_pseudodir="$(qe_md_pseudo_dir)"
    md_cutoffs="$(default_cutoffs_from_pseudos 45 400)"
    read -r md_ecutwfc md_ecutrho <<< "$md_cutoffs"

    echo ' &CONTROL' >> "$mdfile"
    echo "   calculation     = 'md'" >> "$mdfile"
    echo "   restart_mode    = 'from_scratch'" >> "$mdfile"
    echo "   prefix          = '${prefix}_md'" >> "$mdfile"
    echo "   pseudo_dir      = '$md_pseudodir'" >> "$mdfile"
    echo "   outdir          = './tmp_md'" >> "$mdfile"
    echo "   tprnfor         = .true." >> "$mdfile"
    echo "   tstress         = .false." >> "$mdfile"
    echo "   disk_io         = 'low'" >> "$mdfile"
    echo "   nstep           = $md_nstep" >> "$mdfile"
    echo "   dt              = $md_dt_au" >> "$mdfile"
    echo ' /' >> "$mdfile"
    echo '' >> "$mdfile"

    echo ' &SYSTEM' >> "$mdfile"
    echo "   ibrav           = 0" >> "$mdfile"
    echo "   nat             = $natm" >> "$mdfile"
    echo "   ntyp            = $ntyp" >> "$mdfile"
    echo "   ecutwfc         = $md_ecutwfc" >> "$mdfile"
    echo "   ecutrho         = $md_ecutrho" >> "$mdfile"
    echo "   input_dft       = 'PBE'" >> "$mdfile"
    echo "   occupations     = 'smearing'" >> "$mdfile"
    echo "   smearing        = 'gaussian'" >> "$mdfile"
	    echo "   degauss         = 0.02" >> "$mdfile"
	    echo ' /' >> "$mdfile"
	    echo '' >> "$mdfile"
	    md_nelec="$(qe_estimate_nelec_from_current_pwin_context 2>/dev/null)"
	    if qe_nelec_is_odd_integer "$md_nelec"; then
	        qe_print_odd_electron_notice "$md_nelec" "MD 已使用 occupations='smearing'、smearing='gaussian'、degauss=0.02 Ry"
	    fi

    echo ' &ELECTRONS' >> "$mdfile"
    echo "   conv_thr         = 1.0d-6" >> "$mdfile"
    echo "   electron_maxstep = 300" >> "$mdfile"
    echo "   mixing_beta      = 0.07" >> "$mdfile"
    echo "   mixing_mode      = 'local-TF'" >> "$mdfile"
    echo "   mixing_ndim      = 8" >> "$mdfile"
    echo "   diagonalization  = 'david'" >> "$mdfile"
    echo "   diago_david_ndim = 2" >> "$mdfile"
    echo "   startingpot      = 'atomic'" >> "$mdfile"
    echo "   startingwfc      = 'atomic'" >> "$mdfile"
    echo ' /' >> "$mdfile"
    echo '' >> "$mdfile"

    echo ' &IONS' >> "$mdfile"
    echo "   ion_dynamics     = 'verlet'" >> "$mdfile"
    echo "   ion_velocities   = 'from_input'" >> "$mdfile"
    echo "   ion_temperature  = 'not_controlled'" >> "$mdfile"
    echo ' /' >> "$mdfile"
    echo '' >> "$mdfile"

    echo ' ATOMIC_SPECIES' >> "$mdfile"
    for ((i=1;i<=$ntyp;i++))
    do
        atmindex=''
        for ((j=1;j<=103;j++))
        do
            if [ "${atmtype[$i]}" == "${atm[$j]}" ]; then
                atmindex=$j
            fi
        done
        ppfile="$(qe_md_pseudo_file "$atmindex")"
        echo -e "   ${atmtype[$i]} \t${atmmass[$atmindex]} \t${ppfile}" >> "$mdfile"
    done
    echo '' >> "$mdfile"

    echo ' CELL_PARAMETERS angstrom' >> "$mdfile"
    for ((i=1; i<=3; i++)); do
        read -r x y z <<< "${QE_STRUCT_CELL_LINES[$i]}"
        for coord in x y z; do
            value="${!coord}"
            case "$value" in *[dD]*) value="${value%%[dD]*}" ;; esac
            [[ "$value" =~ ^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$ ]] || value=0
            printf -v "$coord" '%s' "$value"
        done
        printf '     %.10f    %.10f    %.10f\n' "$x" "$y" "$z" >> "$mdfile"
    done
    echo '' >> "$mdfile"

    echo ' ATOMIC_POSITIONS angstrom' >> "$mdfile"
    if [ "$md_fix_bottom" == "YES" ]; then
        # Fix atoms in the lowest Cartesian-z layer. Atoms with z equal to the
        # minimum z coordinate within a small tolerance are written with 0 0 0.
        if [ "$cached_bottom_flags" -eq 1 ]; then
            for ((i=1; i<=natm; i++)); do
                IFS=$'\t' read -r symbol x y z bottom <<< "${QE_STRUCT_ATOM_LINES[$i]}"
                for coord in x y z; do
                    value="${!coord}"
                    case "$value" in *[dD]*) value="${value%%[dD]*}" ;; esac
                    [[ "$value" =~ ^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$ ]] || value=0
                    printf -v "$coord" '%s' "$value"
                done
                if [ "$bottom" = 1 ]; then
                    printf '   %2s      %.10f    %.10f    %.10f   0 0 0\n' "$symbol" "$x" "$y" "$z" >> "$mdfile"
                else
                    printf '   %2s      %.10f    %.10f    %.10f   1 1 1\n' "$symbol" "$x" "$y" "$z" >> "$mdfile"
                fi
            done
        else
            awk -v first="$begatmpos" -v last="$endatmpos" '
            NR < first || NR > last {next}
            NR==1{minz=$4}
            {count++; line[count]=$0; if(count==1 || $4<minz) minz=$4}
            END{
                tol=1.0e-5;
                for(i=1;i<=count;i++){
                    split(line[i],a);
                    if((a[4]-minz < tol) && (minz-a[4] < tol)){
                        printf "   %2s      %.10f    %.10f    %.10f   0 0 0\n",a[1],a[2],a[3],a[4];
                    }else{
                        printf "   %2s      %.10f    %.10f    %.10f   1 1 1\n",a[1],a[2],a[3],a[4];
                    }
                }
            }' "$structure_file" >> "$mdfile"
        fi
    else
        for ((i=1; i<=natm; i++)); do
            IFS=$'\t' read -r symbol x y z bottom <<< "${QE_STRUCT_ATOM_LINES[$i]}"
            for coord in x y z; do
                value="${!coord}"
                case "$value" in *[dD]*) value="${value%%[dD]*}" ;; esac
                [[ "$value" =~ ^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$ ]] || value=0
                printf -v "$coord" '%s' "$value"
            done
            printf '   %2s      %.10f    %.10f    %.10f\n' "$symbol" "$x" "$y" "$z" >> "$mdfile"
        done
    fi
    echo '' >> "$mdfile"

    echo ' ATOMIC_VELOCITIES a.u.' >> "$mdfile"
    if [ "$md_use_atomic_velocities" == "YES" ]; then
        if [ -f "ATOMICs_VELOCITIES" ]; then
            # Read ATOMICs_VELOCITIES and assign the velocities only to the matched
            # cluster/molecule atoms. The matching rule is intentionally strict:
            # the element sequence in ATOMICs_VELOCITIES must occur as one unique
            # contiguous block in the current ATOMIC_POSITIONS list. This avoids
            # assigning velocities to slab/substrate atoms with the same elements.
            sed -n "${begatmpos},${endatmpos}p" ${prefix}_QE.tmp | awk -v vfile="ATOMICs_VELOCITIES" '
                BEGIN{
                    nv=0;
                    while((getline line < vfile)>0){
                        gsub(/^[ \t]+|[ \t]+$/,"",line);
                        if(line=="") continue;
                        split(line,tmp);
                        if(tmp[1]=="ATOMIC_VELOCITIES") continue;
                        if(tmp[1] ~ /^#/) continue;
                        if(tmp[1] ~ /^[A-Z][a-z]?$/ && tmp[2] ~ /^[-+0-9.eEdD]+$/ && tmp[3] ~ /^[-+0-9.eEdD]+$/ && tmp[4] ~ /^[-+0-9.eEdD]+$/){
                            nv++;
                            vel_elem[nv]=tmp[1];
                            vx[nv]=tmp[2]; vy[nv]=tmp[3]; vz[nv]=tmp[4];
                        }
                    }
                    close(vfile);
                }
                {
                    n++;
                    elem[n]=$1;
                }
                END{
                    if(nv<1){
                        print "Warning: ATOMICs_VELOCITIES contains no valid velocity lines. All velocities are set to zero." > "/dev/stderr";
                        for(i=1;i<=n;i++) printf "   %2s    0.000000000    0.000000000    0.000000000\n", elem[i];
                        exit;
                    }
                    if(nv>n){
                        print "Warning: ATOMICs_VELOCITIES has more atoms than the MD structure. All velocities are set to zero." > "/dev/stderr";
                        for(i=1;i<=n;i++) printf "   %2s    0.000000000    0.000000000    0.000000000\n", elem[i];
                        exit;
                    }
                    match_count=0;
                    for(start=1; start<=n-nv+1; start++){
                        ok=1;
                        for(j=1; j<=nv; j++){
                            if(elem[start+j-1] != vel_elem[j]){ok=0; break;}
                        }
                        if(ok){
                            match_count++;
                            match_start=start;
                        }
                    }
                    if(match_count==1){
                        match_end=match_start+nv-1;
                        for(i=1;i<=n;i++){
                            if(i>=match_start && i<=match_end){
                                j=i-match_start+1;
                                printf "   %2s    %.9f    %.9f    %.9f\n", elem[i], vx[j], vy[j], vz[j];
                            }else{
                                printf "   %2s    0.000000000    0.000000000    0.000000000\n", elem[i];
                            }
                        }
                        printf "Info: Cluster velocity block matched atoms %d-%d using ATOMICs_VELOCITIES.\n", match_start, match_end > "/dev/stderr";
                    }else if(match_count==0){
                        print "Warning: The element sequence in ATOMICs_VELOCITIES was not found in ATOMIC_POSITIONS. All velocities are set to zero to avoid wrong assignment." > "/dev/stderr";
                        for(i=1;i<=n;i++) printf "   %2s    0.000000000    0.000000000    0.000000000\n", elem[i];
                    }else{
                        printf "Warning: The element sequence in ATOMICs_VELOCITIES matched %d possible blocks. All velocities are set to zero to avoid assigning cluster velocity to the wrong atoms.\n", match_count > "/dev/stderr";
                        for(i=1;i<=n;i++) printf "   %2s    0.000000000    0.000000000    0.000000000\n", elem[i];
                    }
                }' >> "$mdfile"
        else
            echo ' Warning: ATOMICs_VELOCITIES was not found. All initial velocities are set to zero.'
            for ((i=1; i<=natm; i++)); do
                IFS=$'\t' read -r symbol x y z bottom <<< "${QE_STRUCT_ATOM_LINES[$i]}"
                printf '   %2s    0.000000000    0.000000000    0.000000000\n' "$symbol" >> "$mdfile"
            done
        fi
    else
        for ((i=1; i<=natm; i++)); do
            IFS=$'\t' read -r symbol x y z bottom <<< "${QE_STRUCT_ATOM_LINES[$i]}"
            printf '   %2s    0.000000000    0.000000000    0.000000000\n' "$symbol" >> "$mdfile"
        done
    fi
    echo '' >> "$mdfile"

    if [ "$kpmesh" != "gamma" ]; then
        echo ' K_POINTS automatic' >> "$mdfile"
        kptmp="${kpmesh//\*/ }"
        echo " $kptmp 0 0 0" >> "$mdfile"
    else
        echo ' K_POINTS gamma' >> "$mdfile"
    fi
}

function qe_generate_md_input (){
	local output
	qe_validate_calc_prefix "$prefix" || return 1
	output="${prefix}.md.in"
	qe_generate_in_staging md "$output" qe_generate_md_input_unsafe
}

#--------------------------------- neb.x module----------------------------------------
