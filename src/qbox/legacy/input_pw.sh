#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function pwin (){
	local pwin_gen_status pwin_context_status pwin_submenu_status

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
pwin_context_status=$?
[ "$pwin_context_status" -eq 0 ] || return "$pwin_context_status"
fname1="$QE_STRUCT_INPUT"

#Define pwin menu
systype='Semi-conductor'
rtask='energy'
func='PBE'
dispcorr='None'
dipcorr='None'
dftu='No'
pwin_nosym='No'
#kpmesh='2*2*1'
kpmesh="${k_1}*${k_2}*${k_3}"
if [ -n "$PWIN_DEFAULT_KMESH_SCALE" ]; then
	kpmesh="$(pwin_scale_kpmesh "$kpmesh" "$PWIN_DEFAULT_KMESH_SCALE")"
fi
nscf_kpmesh="$(pwin_double_kpmesh "$kpmesh")"
band_kpath_mode="${PWIN_DEFAULT_BAND_KPATH_MODE:-fixed}"
band_kpath_points="${PWIN_DEFAULT_BAND_KPATH_POINTS:-20}"
band_kpath_spacing="${PWIN_DEFAULT_BAND_KPATH_SPACING:-0.02}"
case "$band_kpath_mode" in
	fixed|spacing) ;;
	*) band_kpath_mode='fixed' ;;
esac
nbnd='Default'
pwin_ecutwfc_override=''
pwin_ecutrho_override=''
pwin_scf_conv_thr="${PWIN_DEFAULT_SCF_CONV_THR:-1.D-6}"
pwin_diagonalization="${PWIN_DEFAULT_DIAGONALIZATION:-david}"
case "$pwin_diagonalization" in
	david|cg) ;;
	*) pwin_diagonalization='david' ;;
esac
pwin_diago_david_ndim="${PWIN_DEFAULT_DIAGO_DAVID_NDIM:-2}"
pwin_diago_cg_maxiter="${PWIN_DEFAULT_DIAGO_CG_MAXITER:-20}"
pwin_diago_full_acc="${PWIN_DEFAULT_DIAGO_FULL_ACC:-true}"
case "$pwin_diago_full_acc" in
	true|false) ;;
	.true.) pwin_diago_full_acc='true' ;;
	.false.) pwin_diago_full_acc='false' ;;
	*) pwin_diago_full_acc='true' ;;
esac
pwin_diago_thr_init="${PWIN_DEFAULT_DIAGO_THR_INIT:-1.D-8}"
pseudolib="${PWIN_DEFAULT_PSEUDOLIB:-SSSP}"
case "$pseudolib" in
	SSSP|PD04|SG15) ;;
	*) pseudolib='SSSP' ;;
esac

# 若外部指定了预设任务（scf/nscf/bands/relax/vc-relax），先覆盖默认 rtask，
# 再显示菜单，避免从“执行计算”跳入生成流程时菜单显示旧任务。
if [[ -n "$PRESET_RTASK" ]]; then
  rtask="$PRESET_RTASK"
fi
if [[ "$rtask" == "bands" && -n "$PWIN_DEFAULT_BANDS_NBND" ]]; then
	nbnd="$PWIN_DEFAULT_BANDS_NBND"
fi









if [[ -z "$PRESET_RTASK" && "$NONINTERACTIVE_PWIN" != "1" ]]; then
	qe_pwin_select_task || {
		qe_release_structure_context_with_status 1
		return $?
	}
fi

qe_pwin_menu
qe_pwin_set_choices

if [[ "$NONINTERACTIVE_PWIN" == "1" ]]; then
  # 直接选择“0) 立即生成输入文件”
  pwin_arg="0"
else
  if ! qe_read_choice_with_timeout pwin_arg 0; then
    qe_release_structure_context_with_status 1
    return $?
  fi
  while ! echo "${pwin_choice[@]}" | grep -wq "$pwin_arg"
  do
    echo "请输入有效的功能编号..."
    if ! read -r pwin_arg; then
      qe_release_structure_context_with_status 1
      return $?
    fi
  done
fi


#generate the input file

# Generate pwin input in a same-filesystem staging directory, then atomically
# replace only the requested output. Existing inputs remain intact on failure.

############################################################################################################################################
############################################################################################################################################
													# 设置每级菜单显示的内容
#Creat item sections for pwin menu.
while [[ "$pwin_arg" != "14" ]]; do
	case $pwin_arg in
		"0")
			echo ' 输入文件已在当前文件夹生成。'
			qe_generate_pw_input
			pwin_gen_status=$?
			qe_release_structure_context_with_status "$pwin_gen_status"
			return $?
			;;
		"1")
			PS3=''
			systype_array=(
				"绝缘体：occupations='fixed'，无展宽"
				"半导体：occupations='fixed'，无展宽"
				"导体/金属：occupations='smearing'，smearing='marzari-vanderbilt'，degauss=0.01 Ry"
				"掺杂体系：有带隙，occupations='fixed'，无展宽"
				"掺杂体系：费米面穿过能带，occupations='smearing'，smearing='marzari-vanderbilt'，degauss=0.01 Ry"
				"分子：occupations='fixed'，无展宽，assume_isolated='martyna-tuckerman'"
			)
			select isystype in "${systype_array[@]}"; do
				case $isystype in
					绝缘体*)
						systype="Insulator"
						qe_pwin_menu
						break
						;;
					半导体*)
						systype="Semi-conductor"
						qe_pwin_menu
						break
						;;
					导体/金属*)
						systype="Conductor"
						qe_pwin_menu
						break
						;;
					掺杂体系：有带隙*)
						systype="Doped-gapped"
						qe_pwin_menu
						break
						;;
					掺杂体系：费米面穿过能带*)
						systype="Doped-metallic"
						qe_pwin_menu
						break
						;;
					分子*)
						systype="Molecule"
						qe_pwin_menu
						break
						;;
					"*")
						;;
				esac
			done
			;;
		"3")
			PS3=''
			func_array=("PBE" "PBE0" "PBEsol" "HSE06" "pz")
			select ifunc in "${func_array[@]}"; do
			case $ifunc in
				"PBE")
					func='PBE'
					qe_pwin_menu
					break
					;;
				"PBE0")
					func='PBE0'
					qe_pwin_menu
					break
					;;
				"PBEsol")
					func='PBEsol'
					qe_pwin_menu
					break
					;;
				"HSE06")
					func='HSE06'
					qe_pwin_menu
					break
					;;
				"pz")
					func='pz'
					qe_pwin_menu
					break
					;;
				"*")
					;;
				esac
			done
			;;
		"8")
			echo ' ##########################################################'
			echo '若需要修改自动选取 K 网格的精度，可以修改 qbox 文件的'
			echo 'result=$(echo "scale=9; 30 / $a_value" | bc) 	中的 30 为其他值'
			echo '---- 20 低精度 结构优化 '
			echo '---- 30 中等精度 能带、态密度计算 '
			echo '---- 40 高精度 光学性质计算、精细能带 '
			echo '---- 50+ 超高精度 不推荐 '
			echo ' ##########################################################'
			echo ' ***手动输入的话，以 2,2,1 这样的格式输入三个方向的 K 点采样密度***'
			echo " 也可以直接输入'gamma', 这样布里渊区会进行Gamma点的单点计算"
			if ! read -r value; then
				qe_release_structure_context_with_status 1
				return $?
			fi
			while [ -z "$value" ]; do
					echo
					echo '  请重新输入三个方向的 K 点网格，例如 2,2,1'
					if ! read -r value; then
						qe_release_structure_context_with_status 1
						return $?
					fi
			done

			if [ "$value" = "gamma" ];
			then
				value='gamma'
			else
				value=`echo $value|awk -F , '{printf "%d*%d*%d\n",$1,$2,$3}'`
			fi
			if [ "$rtask" == "nscf" ]; then
				nscf_kpmesh="$value"
			else
				kpmesh="$value"
			fi
			echo '完成！'
			qe_pwin_menu
			;;
		"9")
			echo ' 请输入需要求解的电子态数 nbnd，例如 50'
			echo ' 如果不输入，则使用 pw.x 默认值，例如绝缘体通常为价电子数的 50%。'
			if ! read -r nbnd; then
				qe_release_structure_context_with_status 1
				return $?
			fi
			if [ -z "$nbnd" ]; then nbnd='Default'; fi
			echo '完成！'
			qe_pwin_menu
			;;
		"10")
			PS3=''
			pseudolib_array=("SSSP" "PD04" "SG15")
			select ipseudolib in "${pseudolib_array[@]}"; do
				case $ipseudolib in
					"SSSP"|"PD04"|"SG15")
						pseudolib="$ipseudolib"
						qe_pwin_menu
						break
						;;
					"*")
						;;
				esac
			done
			;;
		"11")
			qe_pwin_cutoff_menu
			pwin_submenu_status=$?
			if [ "$pwin_submenu_status" -ne 0 ]; then
				qe_release_structure_context_with_status "$pwin_submenu_status"
				return $?
			fi
			qe_pwin_menu
			;;
		"12")
			qe_pwin_advanced_menu
			pwin_submenu_status=$?
			if [ "$pwin_submenu_status" -ne 0 ]; then
				qe_release_structure_context_with_status "$pwin_submenu_status"
				return $?
			fi
			qe_pwin_menu
			;;
		"13")
			echo
			echo ' 请选择能带 K 路径采样方式。该设置只影响 bands 任务中的 K_POINTS {crystal_b}。'
			echo "  1) 每段固定插值点数，当前：${band_kpath_points}"
			echo "  2) 按倒空间 K 点间距自动决定每段点数，当前：${band_kpath_spacing} 1/Angstrom"
			if ! read -r value; then
				qe_release_structure_context_with_status 1
				return $?
			fi
			case "$value" in
				1)
					echo " 请输入每段高对称路径的插值点数。直接回车使用：${band_kpath_points}"
					if ! read -r value; then
						qe_release_structure_context_with_status 1
						return $?
					fi
					if [ -n "$value" ]; then
						if echo "$value" | awk 'NF==1 && $1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
							band_kpath_points="$value"
						else
							echo ' 输入无效，保留原设置。'
						fi
					fi
					band_kpath_mode='fixed'
					;;
				2)
					echo " 请输入目标 K 点间距，单位 1/Angstrom。直接回车使用：${band_kpath_spacing}"
					echo ' 例如 0.02 较细，0.03-0.05 较快；每段点数会按倒空间路径长度自动取整。'
					if ! read -r value; then
						qe_release_structure_context_with_status 1
						return $?
					fi
					if [ -n "$value" ]; then
						if echo "$value" | awk 'NF==1 && $1 ~ /^[0-9]+([.][0-9]+)?$/ && $1 > 0 {exit 0} {exit 1}'; then
							band_kpath_spacing="$value"
						else
							echo ' 输入无效，保留原设置。'
						fi
					fi
					band_kpath_mode='spacing'
					;;
				*)
					echo ' 输入无效，保留原设置。'
					;;
			esac
			echo '完成！'
			qe_pwin_menu
			;;
	esac
	unset pwin_arg
	qe_pwin_set_choices
	if ! qe_read_choice_with_timeout pwin_arg 0; then
		qe_release_structure_context_with_status 1
		return $?
	fi
	while ! echo "${pwin_choice[@]}" | grep -wq "$pwin_arg"
	do
		echo "请输入有效的功能编号..."
		if ! read -r pwin_arg; then
			qe_release_structure_context_with_status 1
			return $?
		fi
	done
done

	qe_release_structure_context_with_status 0 || return $?
	if [[ "$RETURN_TO_EXEC_CALC" == "1" ]]; then
		return 1
	fi
	qe_request_main_menu
	return 0
}
function qe_pwin_select_task (){
	echo
	echo '请选择需要生成的 pw.x 输入文件类型：'
	echo ' 1) SCF'
	echo ' 2) NSCF'
	echo ' 3) bands'
	echo ' 4) relax'
	echo ' 5) vc-relax'
	echo ' 6) 返回'
	if ! read -r pwin_task_choice; then return 1; fi
	while ! echo "1 2 3 4 5 6" | grep -wq "$pwin_task_choice"
	do
		echo "请输入有效的功能编号..."
		if ! read -r pwin_task_choice; then return 1; fi
	done
	case "$pwin_task_choice" in
		1) rtask='energy' ;;
		2) rtask='nscf' ;;
		3) rtask='bands' ;;
		4) rtask='structural optimization(relax)' ;;
		5) rtask='cell optimization(vc-relax)' ;;
		6) return 1 ;;
	esac
	return 0
}

function qe_pwin_advanced_menu (){
	local adv_choice idispcorr idipcorr iatmtype magval idftu inosym idiago value
	while true; do
		echo
		echo " 高级设置："
		echo "  1) 设置色散校正，当前：$dispcorr"
		echo "  2) 设置表面偶极校正，当前：$dipcorr"
		echo "  3) 设置原子初始磁矩"
		echo "  4) 设置 DFT+U，当前：$dftu"
		echo "  5) 设置 nosym 模式，当前：$pwin_nosym"
		echo "  6) 设置 diagonalization，当前：$(pwin_diagonalization_label)"
		if [ "$rtask" == "energy" ] || [ "$rtask" == "energy+force+stress" ]; then
			echo "  7) 设置 SCF conv_thr，当前：$pwin_scf_conv_thr"
			echo '     提示：1.D-6 用于起步，1.D-8 用于正式结果，1.D-10 用于验证；最终以目标物理量在相邻精度档之间是否收敛为准。'
			echo "  8) 返回"
		elif [ "$rtask" == "nscf" ] || [ "$rtask" == "bands" ]; then
			echo "  7) 设置非自洽对角化精度，当前：$(pwin_diagonalization_accuracy_label)"
			echo "  8) 返回"
		else
			echo "  7) 返回"
		fi
		read -r adv_choice || return 1
		case "$adv_choice" in
			1)
				PS3=""
				dispcorr_array=("不使用" "DFT-D2" "DFT-D3" "DFT-D3(BJ)")
				echo "注意：DFT-D3 和 DFT-D3(BJ) 与声子计算不兼容；DFT-D2 支持声子计算。"
				select idispcorr in "${dispcorr_array[@]}"; do
					case $idispcorr in
					"不使用") dispcorr='None'; break ;;
					"DFT-D2") dispcorr='DFT-D2'; break ;;
					"DFT-D3") dispcorr='DFT-D3'; break ;;
					"DFT-D3(BJ)") dispcorr='DFT-D3(BJ)'; break ;;
					"*") ;;
					esac
				done
				;;
			2)
				PS3=''
				dipcorr_array=("不使用" "saw-like potential" "ESM-bc1 (推荐)")
				select idipcorr in "${dipcorr_array[@]}"; do
					case $idipcorr in
						"不使用") dipcorr='None'; break ;;
						"saw-like potential") dipcorr='saw-like potential'; break ;;
						"ESM-bc1 (推荐)") dipcorr='ESM-bc1 (recommend)'; break ;;
						"*") ;;
					esac
				done
				;;
			3)
				echo ' 设置初始磁矩：'
				for ((i=1;i<="${#atmtype[@]}";i++))
				do
					magarr[$i]=0
					echo -e " 类型$i: "${atmtype[$i]}" \t磁矩:"${magarr[$i]}" \t原子数:"${Natmtype[$i]}""
				done
				echo
				echo ' * 磁矩定义为 (nalpha-nbeta)/(nalpha+nbeta)，范围为 -1 到 1。'
				echo ' * 如果要设置反铁磁态，需要将同类原子拆成两组，并分别设置为 -n 和 n。'
				echo ' * 输入 "q" 退出。'
				echo ' 请输入需要设置磁矩的原子类型编号：'
				read -r iatmtype || return 1
				while [ "$iatmtype" != "q" ]; do
					if [[ "$iatmtype" > "${#atmtype[@]}" || "$iatmtype" =~ ^[a-z]+$ ]]; then
						read -r iatmtype || return 1
					fi
					echo ' 请输入磁矩，例如 0.5'
					read -r magval || return 1
					magarr[$iatmtype]=$magval
					echo
					for ((i=1;i<="${#atmtype[@]}";i++))
					do
						echo -e " 类型$i: "${atmtype[$i]}" \t磁矩:"${magarr[$i]}" \t原子数:"${Natmtype[$i]}""
					done
					echo ' 请输入需要设置磁矩的原子类型编号：'
					read -r iatmtype || return 1
				done
				;;
			4)
				PS3=''
				dftu_array=("不使用" "DFT+U" "DFT+U+V")
				echo '注意：当前脚本未针对 gamma 点实现 DFT+U。'
				select idftu in "${dftu_array[@]}"; do
					case $idftu in
						"不使用") dftu='No'; break ;;
						"DFT+U") dftu='DFT+U'; echo ' 当前有效 U 参数为占位值，请手动修改输入文件。'; echo; break ;;
						"DFT+U+V") dftu='DFT+U+V'; echo ' 当前 U 和 V 参数为占位值，请手动修改输入文件。'; echo; break ;;
						"*") ;;
					esac
				done
				;;
			5)
				PS3=''
				echo "注意：默认不开启 nosym，即保持 QE 默认 nosym=.false.。"
				echo "只有确定体系存在较大不对称性时才建议开启，例如缺陷结构、分子动力学快照、明显畸变结构等。"
				nosym_array=("不开启 nosym，保持 QE 默认 nosym=.false." "开启 nosym=.true.")
				select inosym in "${nosym_array[@]}"; do
					case $inosym in
						"不开启 nosym"*) pwin_nosym='No'; break ;;
						"开启 nosym"*) pwin_nosym='Yes'; break ;;
						"*") ;;
					esac
				done
				;;
			6)
				echo
				echo " diagonalization 设置："
				echo "  1) 选择 diagonalization，当前：'$pwin_diagonalization'"
				if [ "$pwin_diagonalization" == "cg" ]; then
					echo "  2) 设置 diago_cg_maxiter，当前：$pwin_diago_cg_maxiter"
				else
					echo "  2) 设置 diago_david_ndim，当前：$pwin_diago_david_ndim"
				fi
				echo "  3) 返回"
				read -r idiago || return 1
				case "$idiago" in
					1)
						PS3=''
						diagonalization_array=("david" "cg")
						select value in "${diagonalization_array[@]}"; do
							case $value in
								"david"|"cg") pwin_diagonalization="$value"; break ;;
								"*") ;;
							esac
						done
						;;
					2)
						if [ "$pwin_diagonalization" == "cg" ]; then
							echo " 请输入 diago_cg_maxiter，正整数。直接回车保留当前值 ${pwin_diago_cg_maxiter}。"
							read -r value || return 1
							if [ -n "$value" ]; then
								if echo "$value" | awk 'NF==1 && $1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
									pwin_diago_cg_maxiter="$value"
								else
									echo ' 输入无效，保留原设置。'
								fi
							fi
						else
							echo " 请输入 diago_david_ndim，正整数且至少为 2。直接回车保留当前值 ${pwin_diago_david_ndim}。"
							read -r value || return 1
							if [ -n "$value" ]; then
								if echo "$value" | awk 'NF==1 && $1 ~ /^[0-9]+$/ && $1 >= 2 {exit 0} {exit 1}'; then
									pwin_diago_david_ndim="$value"
								else
									echo ' 输入无效，保留原设置。'
								fi
							fi
						fi
						;;
					3) ;;
					*) echo "请输入有效的功能编号..." ;;
				esac
				;;
			7)
				if [ "$rtask" == "energy" ] || [ "$rtask" == "energy+force+stress" ]; then
					echo
					echo ' 提示：1.D-6 用于起步，1.D-8 用于正式结果，1.D-10 用于验证；最终以目标物理量在相邻精度档之间是否收敛为准。'
					echo " 请输入 SCF conv_thr，例如 1.D-8。直接回车保留当前值 ${pwin_scf_conv_thr}。"
					read -r value || return 1
					if [ -n "$value" ]; then
						if echo "$value" | awk 'NF==1 && $1 ~ /^([0-9]+([.][0-9]*)?|[.][0-9]+)([dDeE][-+]?[0-9]+)?$/ {exit 0} {exit 1}'; then
							pwin_scf_conv_thr="$value"
						else
							echo ' 输入无效，保留原设置。'
						fi
					fi
				elif [ "$rtask" == "nscf" ] || [ "$rtask" == "bands" ]; then
					echo
					echo " 非自洽对角化精度设置："
					echo "  1) 设置 diago_full_acc，当前：.$pwin_diago_full_acc."
					echo "  2) 设置 diago_thr_init，当前：$pwin_diago_thr_init"
					echo "  3) 返回"
					read -r idiago || return 1
					case "$idiago" in
						1)
							PS3=''
							diago_full_acc_array=("开启 .true.（推荐，空带与占据态同精度）" "关闭 .false.")
							select value in "${diago_full_acc_array[@]}"; do
								case $value in
									"开启 .true."*) pwin_diago_full_acc='true'; break ;;
									"关闭 .false."*) pwin_diago_full_acc='false'; break ;;
									"*") ;;
								esac
							done
							;;
						2)
							echo " 请输入 diago_thr_init，例如 1.D-8。直接回车保留当前值 ${pwin_diago_thr_init}。"
							read -r value || return 1
							if [ -n "$value" ]; then
								if echo "$value" | awk 'NF==1 && $1 ~ /^([0-9]+([.][0-9]*)?|[.][0-9]+)([dDeE][-+]?[0-9]+)?$/ {exit 0} {exit 1}'; then
									pwin_diago_thr_init="$value"
								else
									echo ' 输入无效，保留原设置。'
								fi
							fi
							;;
						3) ;;
						*) echo "请输入有效的功能编号..." ;;
					esac
				else
					break
				fi
				;;
			8)
				if [ "$rtask" == "energy" ] || [ "$rtask" == "energy+force+stress" ] || [ "$rtask" == "nscf" ] || [ "$rtask" == "bands" ]; then
					break
				else
					echo "请输入有效的功能编号..."
				fi
				;;
			*)
				echo "请输入有效的功能编号..."
				;;
		esac
	done
}

function qe_pwin_refresh_cutoff_values (){
	local pwin_cutoffs
	pwin_cutoffs=`default_cutoffs_from_pseudos 35.0 400.0`
	pwin_default_ecutwfc=`echo "$pwin_cutoffs" | awk '{print $1}'`
	pwin_default_ecutrho=`echo "$pwin_cutoffs" | awk '{print $2}'`
	if [ -n "$pwin_ecutwfc_override" ]; then
		pwin_current_ecutwfc="$pwin_ecutwfc_override"
	else
		pwin_current_ecutwfc="$pwin_default_ecutwfc"
	fi
	if [ -n "$pwin_ecutrho_override" ]; then
		pwin_current_ecutrho="$pwin_ecutrho_override"
	else
		pwin_current_ecutrho="$pwin_default_ecutrho"
	fi
}

function qe_pwin_cutoff_label (){
	qe_pwin_refresh_cutoff_values
	if [ -z "$pwin_ecutwfc_override" ] && [ -z "$pwin_ecutrho_override" ]; then
		echo "默认 ecutwfc=${pwin_default_ecutwfc} Ry，ecutrho=${pwin_default_ecutrho} Ry"
	else
		echo "ecutwfc=${pwin_current_ecutwfc} Ry，ecutrho=${pwin_current_ecutrho} Ry（默认 ${pwin_default_ecutwfc}/${pwin_default_ecutrho} Ry）"
	fi
}

function qe_pwin_cutoff_menu (){
	local cutoff_choice cutoff_value
	while true; do
		qe_pwin_refresh_cutoff_values
		echo
		echo " 截断能设置："
		echo "  默认值：ecutwfc=${pwin_default_ecutwfc} Ry，ecutrho=${pwin_default_ecutrho} Ry"
		echo "  当前值：ecutwfc=${pwin_current_ecutwfc} Ry，ecutrho=${pwin_current_ecutrho} Ry"
		echo "  1) 设置 ecutwfc"
		echo "  2) 设置 ecutrho"
		echo "  3) 恢复为当前赝势推荐默认值"
		echo "  4) 返回"
		read -r cutoff_choice || return 1
		case "$cutoff_choice" in
			1)
				echo " 请输入 ecutwfc，单位 Ry。直接回车保留当前值 ${pwin_current_ecutwfc}。"
				read -r cutoff_value || return 1
				if [ -n "$cutoff_value" ]; then
					if echo "$cutoff_value" | awk 'NF==1 && $1 ~ /^[0-9]+([.][0-9]+)?$/ && $1 > 0 {exit 0} {exit 1}'; then
						pwin_ecutwfc_override="$cutoff_value"
					else
						echo ' 输入无效，保留原设置。'
					fi
				fi
				;;
			2)
				echo " 请输入 ecutrho，单位 Ry。直接回车保留当前值 ${pwin_current_ecutrho}。"
				read -r cutoff_value || return 1
				if [ -n "$cutoff_value" ]; then
					if echo "$cutoff_value" | awk 'NF==1 && $1 ~ /^[0-9]+([.][0-9]+)?$/ && $1 > 0 {exit 0} {exit 1}'; then
						pwin_ecutrho_override="$cutoff_value"
					else
						echo ' 输入无效，保留原设置。'
					fi
				fi
				;;
			3)
				pwin_ecutwfc_override=''
				pwin_ecutrho_override=''
				echo ' 已恢复为当前赝势推荐默认值。'
				;;
			4)
				break
				;;
			*)
				echo "请输入有效的功能编号..."
				;;
		esac
	done
}

function qe_pwin_menu (){
	echo " 0) 立即生成输入文件"
	if [ "$rtask" == "bands" ]; then
		echo "------------------------------ band 参数 ------------------------------"
		echo " 1) 设置体系类型，当前：$systype"
		echo " 3) 选择理论方法/泛函，当前：$func"
		echo " 9) 设置能带数 nbnd，当前：$(pwin_nbnd_label)"
		echo " 10) 选择赝势库，当前：$pseudolib"
		echo " 11) 设置 ecutwfc/ecutrho，当前：$(qe_pwin_cutoff_label)"
		echo " 12) 高级设置"
		if [ "$band_kpath_mode" == "spacing" ]; then
			[ "$PWIN_LOCK_BANDS_KPATH" == "1" ] || echo " 13) 设置 bands 高对称路径采样，当前：按间距 ${band_kpath_spacing} 1/Angstrom"
		else
			[ "$PWIN_LOCK_BANDS_KPATH" == "1" ] || echo " 13) 设置 bands 高对称路径采样，当前：每段固定 ${band_kpath_points} 点"
		fi
	elif [ "$rtask" == "nscf" ]; then
		echo "------------------------------ nscf 参数 ------------------------------"
		echo " 1) 设置体系类型，当前：$systype"
		echo " 3) 选择理论方法/泛函，当前：$func"
		echo " 8) 设置 NSCF K 点网格，当前：$nscf_kpmesh（默认 SCF 网格 $kpmesh 的 2 倍）"
		echo " 9) 设置能带数 nbnd，当前：$(pwin_nbnd_label)"
		echo " 10) 选择赝势库，当前：$pseudolib"
		echo " 11) 设置 ecutwfc/ecutrho，当前：$(qe_pwin_cutoff_label)"
		echo " 12) 高级设置"
	elif [ "$rtask" == "structural optimization(relax)" ] || [ "$rtask" == "cell optimization(vc-relax)" ] || [ "$rtask" == "cell optimization for 2D materials" ]; then
		echo "------------------------------ relax 参数 -----------------------------"
		echo " 1) 设置体系类型，当前：$systype"
		echo " 3) 选择理论方法/泛函，当前：$func"
		echo " 8) 设置 K 点网格，当前：$kpmesh"
		echo " 10) 选择赝势库，当前：$pseudolib"
		echo " 11) 设置 ecutwfc/ecutrho，当前：$(qe_pwin_cutoff_label)"
		echo " 12) 高级设置"
	else
		echo "------------------------------ scf 参数 -------------------------------"
		echo " 1) 设置体系类型，当前：$systype"
		echo " 3) 选择理论方法/泛函，当前：$func"
		echo " 8) 设置 K 点网格，当前：$kpmesh"
		echo " 10) 选择赝势库，当前：$pseudolib"
		echo " 11) 设置 ecutwfc/ecutrho，当前：$(qe_pwin_cutoff_label)"
		echo " 12) 高级设置"
	fi
	echo " 14) 返回"
}

function qe_pwin_set_choices (){
	if [ "$rtask" == "bands" ]; then
		if [ "$PWIN_LOCK_BANDS_KPATH" == "1" ]; then
			pwin_choice=("0" "1" "3" "9" "10" "11" "12" "14")
		else
			pwin_choice=("0" "1" "3" "9" "10" "11" "12" "13" "14")
		fi
	elif [ "$rtask" == "nscf" ]; then
		pwin_choice=("0" "1" "3" "8" "9" "10" "11" "12" "14")
	elif [ "$rtask" == "structural optimization(relax)" ] || [ "$rtask" == "cell optimization(vc-relax)" ] || [ "$rtask" == "cell optimization for 2D materials" ]; then
		pwin_choice=("0" "1" "3" "8" "10" "11" "12" "14")
	else
		pwin_choice=("0" "1" "3" "8" "10" "11" "12" "14")
	fi
}

function qe_task_profile (){
	local task="${1:-}"
	QE_TASK_OUTPUT=''
	QE_TASK_CALCULATION=''
	QE_TASK_VERBOSITY=''
	QE_TASK_PRINT_FORCE_STRESS=''
	QE_TASK_ETOT_CONV_THR=''
	QE_TASK_FORC_CONV_THR=''
	QE_TASK_NSTEP=''
	QE_TASK_SYSTEM_KIND=''
	QE_TASK_ELECTRONS_KIND=''
	QE_TASK_KPOINTS_KIND=''
	QE_TASK_WRITE_IONS=''
	QE_TASK_WRITE_CELL=''
	QE_TASK_CELL_DOFREE=''
	case "$task" in
		energy)
			QE_TASK_OUTPUT="$prefix.scf.in"
			QE_TASK_CALCULATION='scf'
			QE_TASK_VERBOSITY='low'
			QE_TASK_PRINT_FORCE_STRESS='0'
			QE_TASK_SYSTEM_KIND='scf'
			QE_TASK_ELECTRONS_KIND='scf'
			QE_TASK_KPOINTS_KIND='automatic'
			QE_TASK_WRITE_IONS='0'
			QE_TASK_WRITE_CELL='0'
			;;
		energy+force+stress)
			QE_TASK_OUTPUT="$prefix.scf.in"
			QE_TASK_CALCULATION='scf'
			QE_TASK_VERBOSITY='low'
			QE_TASK_PRINT_FORCE_STRESS='1'
			QE_TASK_SYSTEM_KIND='scf'
			QE_TASK_ELECTRONS_KIND='scf'
			QE_TASK_KPOINTS_KIND='automatic'
			QE_TASK_WRITE_IONS='0'
			QE_TASK_WRITE_CELL='0'
			;;
		"structural optimization(relax)")
			QE_TASK_OUTPUT="$prefix.relax.in"
			QE_TASK_CALCULATION='relax'
			QE_TASK_VERBOSITY='high'
			QE_TASK_PRINT_FORCE_STRESS='0'
			QE_TASK_ETOT_CONV_THR='1.D-6'
			QE_TASK_FORC_CONV_THR='1.D-4'
			QE_TASK_NSTEP='300'
			QE_TASK_SYSTEM_KIND='relax'
			QE_TASK_ELECTRONS_KIND='relax'
			QE_TASK_KPOINTS_KIND='automatic'
			QE_TASK_WRITE_IONS='1'
			QE_TASK_WRITE_CELL='0'
			;;
		"cell optimization(vc-relax)")
			QE_TASK_OUTPUT="$prefix.vcrelax.in"
			QE_TASK_CALCULATION='vc-relax'
			QE_TASK_VERBOSITY='low'
			QE_TASK_PRINT_FORCE_STRESS='0'
			QE_TASK_ETOT_CONV_THR='1.D-5'
			QE_TASK_FORC_CONV_THR='1.D-3'
			QE_TASK_NSTEP='300'
			QE_TASK_SYSTEM_KIND='vc-relax'
			QE_TASK_ELECTRONS_KIND='vc-relax'
			QE_TASK_KPOINTS_KIND='automatic'
			QE_TASK_WRITE_IONS='1'
			QE_TASK_WRITE_CELL='1'
			;;
		"cell optimization for 2D materials")
			QE_TASK_OUTPUT="$prefix.vcrelax.in"
			QE_TASK_CALCULATION='vc-relax'
			QE_TASK_VERBOSITY='low'
			QE_TASK_PRINT_FORCE_STRESS='0'
			QE_TASK_ETOT_CONV_THR='1.D-5'
			QE_TASK_FORC_CONV_THR='1.D-3'
			QE_TASK_NSTEP='300'
			QE_TASK_SYSTEM_KIND='vc-relax'
			QE_TASK_ELECTRONS_KIND='vc-relax'
			QE_TASK_KPOINTS_KIND='automatic'
			QE_TASK_WRITE_IONS='1'
			QE_TASK_WRITE_CELL='1'
			QE_TASK_CELL_DOFREE='2Dxy'
			;;
		bands)
			QE_TASK_OUTPUT="$prefix.bands.in"
			QE_TASK_CALCULATION='bands'
			QE_TASK_VERBOSITY='high'
			QE_TASK_PRINT_FORCE_STRESS='0'
			QE_TASK_SYSTEM_KIND='bands'
			QE_TASK_ELECTRONS_KIND='bands'
			QE_TASK_KPOINTS_KIND='bands'
			QE_TASK_WRITE_IONS='0'
			QE_TASK_WRITE_CELL='0'
			;;
		nscf)
			QE_TASK_OUTPUT="$prefix.nscf.in"
			QE_TASK_CALCULATION='nscf'
			QE_TASK_VERBOSITY='high'
			QE_TASK_PRINT_FORCE_STRESS='0'
			QE_TASK_SYSTEM_KIND='nscf'
			QE_TASK_ELECTRONS_KIND='nscf'
			QE_TASK_KPOINTS_KIND='automatic'
			QE_TASK_WRITE_IONS='0'
			QE_TASK_WRITE_CELL='0'
			;;
		*)
			echo " 错误：未知 pwin 任务：$task" >&2
			return 1
			;;
	esac
	return 0
}

function qe_write_pw_control (){
	local outfile="$1"
	echo ' &CONTROL' >> "$outfile"
	echo "   calculation     = '$QE_TASK_CALCULATION'" >> "$outfile"
	echo "   restart_mode    = 'from_scratch'" >> "$outfile"
	echo "   outdir          = './tmp'" >> "$outfile"
	echo "   pseudo_dir      = '$(pseudo_dir_by_lib "$pseudolib")'" >> "$outfile"
	echo "   prefix          = '"$prefix"'" >> "$outfile"
	if [ "$QE_TASK_PRINT_FORCE_STRESS" == "1" ]; then
		echo '   tstress         = .true.' >> "$outfile"
		echo '   tprnfor         = .true.' >> "$outfile"
	fi
	echo "   verbosity       = '$QE_TASK_VERBOSITY'" >> "$outfile"
	if [ -n "$QE_TASK_ETOT_CONV_THR" ]; then
		echo "   etot_conv_thr   = $QE_TASK_ETOT_CONV_THR" >> "$outfile"
		echo "   forc_conv_thr   = $QE_TASK_FORC_CONV_THR" >> "$outfile"
		echo "   nstep           = $QE_TASK_NSTEP" >> "$outfile"
	fi
	if [ "$dipcorr" == "saw-like potential" ]; then
		echo "   tefield         = .true." >> "$outfile"
		echo "   dipfield        = .true." >> "$outfile"
	fi
	echo ' /' >> "$outfile"
}

function qe_write_pw_system (){
	local outfile="$1" pwin_nelec pwin_recommended_nbnd
	echo ' &SYSTEM' >> "$outfile"
	echo "   ibrav           = 0" >> "$outfile"
	echo "   nat             = $natm" >> "$outfile"
	echo "   ntyp            = $ntyp" >> "$outfile"
	echo "   ecutwfc         = $pwin_ecutwfc" >> "$outfile"
	echo "   ecutrho         = $pwin_ecutrho" >> "$outfile"
	pwin_write_symmetry_settings "$outfile"

	if [ "$QE_TASK_SYSTEM_KIND" == "bands" ]; then
		if [ "$nbnd" != "Default" ]; then
			echo "   nbnd            = $nbnd" >> "$outfile"
		else
			pwin_nelec=`qe_estimate_nelec_from_current_pwin_context`
			if echo "$pwin_nelec" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
				if [ -n "$PWIN_DEFAULT_BANDS_NBND_FACTOR" ]; then
					pwin_recommended_nbnd=`qe_recommend_band_nbnd_from_nelec_with_factor "$pwin_nelec" "$PWIN_DEFAULT_BANDS_NBND_FACTOR"`
				elif [ -n "$PWIN_DEFAULT_BANDS_NBND_MIN" ]; then
					pwin_recommended_nbnd=`qe_recommend_band_nbnd_from_nelec_with_min "$pwin_nelec" "$PWIN_DEFAULT_BANDS_NBND_MIN"`
				else
					pwin_recommended_nbnd=`qe_recommend_band_nbnd_from_nelec "$pwin_nelec"`
				fi
				echo "   nbnd            = $pwin_recommended_nbnd" >> "$outfile"
				echo " 已根据估算价电子数 $pwin_nelec 为 bands 计算设置推荐 nbnd = $pwin_recommended_nbnd。"
			else
				echo ' 警告：未能从赝势估算电子数，bands 输入文件将保留 pw.x 默认 nbnd。'
			fi
		fi
	else
		if [ "$nbnd" != "Default" ]; then
			echo "   nbnd            = $nbnd" >> "$outfile"
		fi
	fi
	if [ "$QE_TASK_SYSTEM_KIND" == "bands" ]; then
		pwin_nelec=`qe_estimate_nelec_from_current_pwin_context 2>/dev/null`
		if [ "$systype" == "Insulator" ] || [ "$systype" == "Semi-conductor" ] || [ "$systype" == "Doped-gapped" ] || [ "$systype" == "Molecule" ]; then
			if ! qe_nelec_is_odd_integer "$pwin_nelec"; then
				echo " 提示：当前体系使用 occupations='fixed'；bands/nscf 不设置 nbnd 时可能只包含价带。"
			fi
		fi
	fi

	pwin_write_occupation_settings "$outfile"

	# Preserve the lexical magnetic comparison and ambient lsda state.
	for ((i=1;i<="${#atmtype[@]}";i++))
	do
		if [[ "${magarr[$i]}" > "0" ]]; then
			lsda=on
		fi
	done
	if [ "$lsda" == "on" ]; then
		echo "   nspin           = 2" >> "$outfile"
		for ((i=1;i<="${#atmtype[@]}";i++))
		do
			printf '   starting_magnetization(%s) = %s\n' "$i" "${magarr[$i]}" >> "$outfile"
		done
	fi

	if [ "$func" == "pz" ]; then
		echo "   input_dft       = 'pz'" >> "$outfile"
	elif [ "$func" == "HSE06" ]; then
		echo "   input_dft       = 'hse'" >> "$outfile"
		echo "   exxdiv_treatment = 'gygi-baldereschi'" >> "$outfile"
		echo "   x_gamma_extrapolation = .true." >> "$outfile"
		echo "   nqx1            = 1" >> "$outfile"
		echo "   nqx2            = 1" >> "$outfile"
		echo "   nqx3            = 1" >> "$outfile"
	elif [ "$func" == "PBE0" ]; then
		echo "   input_dft       = 'pbe0'" >> "$outfile"
		echo "   exxdiv_treatment = 'gygi-baldereschi'" >> "$outfile"
		echo "   x_gamma_extrapolation = .true." >> "$outfile"
		echo "   nqx1            = 1" >> "$outfile"
		echo "   nqx2            = 1" >> "$outfile"
		echo "   nqx3            = 1" >> "$outfile"
	fi

	if [ "$dipcorr" == "saw-like potential" ]; then
		echo "   edir            = 3" >> "$outfile"
		echo "   emaxpos         = 0.55" >> "$outfile"
		echo "   eopreg          = 0.06" >> "$outfile"
		echo "   eamp            = 0.0005" >> "$outfile"
	elif [ "$dipcorr" == "ESM-bc1 (recommend)" ]; then
		echo "   assume_isolated = 'esm'" >> "$outfile"
		echo "   esm_bc          = 'bc1'" >> "$outfile"
	fi
	if [ "$dispcorr" == "DFT-D2" ]; then
		echo "   vdw_corr        = 'grimme-d2'" >> "$outfile"
	elif [ "$dispcorr" == "DFT-D3" ]; then
		echo "   vdw_corr        = 'grimme-d3'" >> "$outfile"
		echo "   dftd3_version   = 3" >> "$outfile"
	elif [ "$dispcorr" == "DFT-D3(BJ)" ]; then
		echo "   vdw_corr        = 'grimme-d3'" >> "$outfile"
		echo "   dftd3_version   = 4" >> "$outfile"
	fi
	echo ' /' >> "$outfile"
}

function qe_write_pw_electrons (){
	local outfile="$1"
	if [ "$QE_TASK_ELECTRONS_KIND" == "scf" ]; then
		echo ' &ELECTRONS' >> "$outfile"
		echo "   electron_maxstep = 128" >> "$outfile"
		case "$pwin_scf_conv_thr" in
			1.D-6|1.d-6|1.0D-6|1.0d-6)
				echo "   ! 默认 1.D-6 为较粗糙精度；如需更高精度，请改为 1.D-8。" >> "$outfile"
				;;
		esac
		echo "   conv_thr        = $pwin_scf_conv_thr" >> "$outfile"
		echo "   mixing_mode     = 'plain'" >> "$outfile"
		echo "   mixing_beta     = 0.7" >> "$outfile"
		echo "   mixing_ndim     = 8" >> "$outfile"
		pwin_write_diagonalization_settings "$outfile"
		echo ' /' >> "$outfile"
	elif [ "$QE_TASK_ELECTRONS_KIND" == "relax" ] || [ "$QE_TASK_ELECTRONS_KIND" == "vc-relax" ]; then
		echo ' &ELECTRONS' >> "$outfile"
		echo "   electron_maxstep = 128" >> "$outfile"
		echo "   conv_thr        = 1.D-6" >> "$outfile"
		echo "   mixing_mode     = 'plain'" >> "$outfile"
		echo "   mixing_beta     = 0.7" >> "$outfile"
		echo "   mixing_ndim     = 8" >> "$outfile"
		pwin_write_diagonalization_settings "$outfile"
		echo ' /' >> "$outfile"
	elif [ "$QE_TASK_ELECTRONS_KIND" == "bands" ]; then
		echo ' &ELECTRONS' >> "$outfile"
		pwin_write_diagonalization_settings "$outfile"
		pwin_write_diagonalization_accuracy_settings "$outfile"
		echo ' /' >> "$outfile"
	else
		return 1
	fi
}

function qe_write_pw_ions_cell (){
	local outfile="$1"
	if [ "$QE_TASK_WRITE_IONS" == "1" ]; then
		echo ' &IONS' >> "$outfile"
		echo "   ion_dynamics    = 'bfgs'" >> "$outfile"
		echo ' /' >> "$outfile"
	fi
	if [ "$QE_TASK_WRITE_CELL" == "1" ]; then
		echo ' &CELL' >> "$outfile"
		echo "   cell_dynamics   = 'bfgs'" >> "$outfile"
		echo "   press           = 0" >> "$outfile"
		echo "   press_conv_thr  = 0.5" >> "$outfile"
		if [ -n "$QE_TASK_CELL_DOFREE" ]; then
			echo "   cell_dofree     = '$QE_TASK_CELL_DOFREE'" >> "$outfile"
		fi
		echo ' /' >> "$outfile"
	fi
}

function qe_write_pw_structure (){
	local outfile="$1" ppfile structure_file line line_no symbol x y z bottom coord value
	structure_file="${QE_STRUCT_TMP:-${prefix}_QE.tmp}"
	if ! declare -p QE_STRUCT_CELL_LINES &>/dev/null || [ "${#QE_STRUCT_CELL_LINES[@]}" -ne 3 ] ||
	   ! declare -p QE_STRUCT_ATOM_LINES &>/dev/null || [ "${#QE_STRUCT_ATOM_LINES[@]}" -ne "$natm" ]; then
		QE_STRUCT_CELL_LINES=()
		QE_STRUCT_ATOM_LINES=()
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
	echo " CELL_PARAMETERS angstrom" >> "$outfile"
	for ((i=1; i<=3; i++)); do
		read -r x y z <<< "${QE_STRUCT_CELL_LINES[$i]}"
		for coord in x y z; do
			value="${!coord}"
			case "$value" in *[dD]*) value="${value%%[dD]*}" ;; esac
			[[ "$value" =~ ^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$ ]] || value=0
			printf -v "$coord" '%s' "$value"
		done
		printf '     %.9f    %.9f    %.9f\n' "$x" "$y" "$z" >> "$outfile"
	done

	# Preserve the H-Rn lookup range and ambient atmindex state.
	echo " " >> "$outfile"
	echo " ATOMIC_SPECIES" >> "$outfile"
	for ((i=1;i<=$ntyp;i++))
	do
		for ((j=1;j<=86;j++))
		do
			if [ "${atmtype[$i]}" == "${atm[$j]}" ]; then
				atmindex=$j
			fi
		done
		ppfile=$(pseudo_file_by_lib "$pseudolib" "$atmindex")
		echo -e "   "${atmtype[$i]}" \t"${atmmass[$atmindex]}" \t"${ppfile}"" >> "$outfile"
	done

	echo " " >> "$outfile"
	echo " ATOMIC_POSITIONS angstrom" >> "$outfile"
	for ((i=1; i<=natm; i++)); do
		IFS=$'\t' read -r symbol x y z bottom <<< "${QE_STRUCT_ATOM_LINES[$i]}"
		for coord in x y z; do
			value="${!coord}"
			case "$value" in *[dD]*) value="${value%%[dD]*}" ;; esac
			[[ "$value" =~ ^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$ ]] || value=0
			printf -v "$coord" '%s' "$value"
		done
		printf '   %2s      %.9f    %.9f    %.9f\n' "$symbol" "$x" "$y" "$z" >> "$outfile"
	done
}

function qe_write_pw_kpoints (){
	local outfile="$1" kptmp kpath_tmp kpath_err kpath_status
	if [ "$QE_TASK_KPOINTS_KIND" == "bands" ]; then
		echo " " >> "$outfile"
		kpath_tmp="$(mktemp "$PWD/.qbox-kpath.stdout.XXXXXX")" || return 1
		qe_cleanup_register "$kpath_tmp" || {
			rm -f "$kpath_tmp"
			return 1
		}
		kpath_err="$(mktemp "$PWD/.qbox-kpath.stderr.XXXXXX")" || {
			qe_cleanup_unregister "$kpath_tmp"
			rm -f "$kpath_tmp"
			return 1
		}
		qe_cleanup_register "$kpath_err" || {
			qe_cleanup_unregister "$kpath_tmp"
			rm -f "$kpath_tmp" "$kpath_err"
			return 1
		}
		if [ "$band_kpath_mode" == "spacing" ]; then
			qe_embedded_find_path "$prefix.cif" --mode spacing --spacing "$band_kpath_spacing" > "$kpath_tmp" 2> "$kpath_err"
		else
			qe_embedded_find_path "$prefix.cif" --mode fixed --points "$band_kpath_points" > "$kpath_tmp" 2> "$kpath_err"
		fi
		kpath_status=$?
		if [ "$kpath_status" -eq 0 ]; then
			cat "$kpath_tmp" >> "$outfile"
			rm -f "$kpath_tmp" "$kpath_err"
			qe_cleanup_unregister "$kpath_tmp"
			qe_cleanup_unregister "$kpath_err"
			return 0
		fi
		echo " Error: failed to generate K_POINTS path from $prefix.cif." >&2
		cat "$kpath_err" >&2
		rm -f "$kpath_tmp" "$kpath_err"
		qe_cleanup_unregister "$kpath_tmp"
		qe_cleanup_unregister "$kpath_err"
		rm -f "$outfile"
		return 1
	fi
	if [ "$kpmesh" != "gamma" ]; then
		echo " " >> "$outfile"
		echo " K_POINTS automatic" >> "$outfile"
		kptmp=$(echo $kpmesh |sed 's/[*]/ /g')
		echo " $kptmp 0 0 0" >> "$outfile"
	else
		echo " K_POINTS gamma" >> "$outfile"
	fi
}

function qe_write_pw_hubbard (){
	local outfile="$1"
	if [ "$dftu" == "DFT+U" ]; then
		echo ' HUBBARD {ortho-atomic}' >> "$outfile"
		echo " element element-3d u_value" >> "$outfile"
	elif [ "$dftu" == "DFT+U+V" ]; then
		echo ' HUBBARD {ortho-atomic}' >> "$outfile"
		echo " V element1-3d element1-3d 1 1 v_value #This is actualy U value, a equivalent syntax" >> "$outfile"
		echo " V element1-3d element2-2p 1 2 v_value" >> "$outfile"
	fi
}

function qe_generate_pw_input_unsafe (){
	local generation_task="$rtask"
	qe_task_profile "$generation_task" || return 1
	if [ "$generation_task" == "nscf" ]; then
		local original_rtask nscf_status scf_backup scf_had_existing
		scf_backup=""
		scf_had_existing=0
		if [ -f "$prefix.scf.in" ]; then
			scf_backup="$(mktemp "$PWD/.qbox-scf-backup.XXXXXX")" || return 1
			qe_cleanup_register "$scf_backup" || { rm -f -- "$scf_backup"; return 1; }
			cp "$prefix.scf.in" "$scf_backup"
			scf_had_existing=1
		fi
		original_rtask="$rtask"
		rtask="energy"
		qe_generate_pw_input
		nscf_status=$?
		rtask="$original_rtask"
		if [ "$nscf_status" != "0" ] || [ ! -f "$prefix.scf.in" ]; then
			[ "$scf_had_existing" == "1" ] && cp "$scf_backup" "$prefix.scf.in"
			[ -n "$scf_backup" ] && rm -f "$scf_backup"
			[ -n "$scf_backup" ] && qe_cleanup_unregister "$scf_backup"
			return 1
		fi
		cp "$prefix.scf.in" "$prefix.nscf.in"
		qe_atomic_rewrite "$prefix.nscf.in" qe_render_nscf_nbnd_update || return 1
		qe_apply_odd_electron_smearing_to_input "$prefix.nscf.in" "${PWIN_DEFAULT_ODD_ELECTRON_DEGAUSS:-0.01}" "普通 NSCF" || return 1
		pwin_replace_kpoints_in_file "$prefix.nscf.in" "$nscf_kpmesh"
		pwin_remove_charge_mixing_settings_from_file "$prefix.nscf.in"
		pwin_set_diagonalization_settings_in_file "$prefix.nscf.in"
		pwin_set_diagonalization_accuracy_in_file "$prefix.nscf.in"
		if [ "$nbnd" == "Default" ]; then
			local nscf_nelec nscf_recommended_nbnd
			nscf_nelec=`qe_estimate_nelec_from_pwin_file "$prefix.nscf.in"`
			if echo "$nscf_nelec" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
				nscf_recommended_nbnd=`qe_recommend_band_nbnd_from_nelec "$nscf_nelec"`
				qe_set_pw_nbnd_in_file "$prefix.nscf.in" "$nscf_recommended_nbnd"
				echo " 已根据估算价电子数 ${nscf_nelec} 为 nscf 计算设置推荐 nbnd = ${nscf_recommended_nbnd}。"
			fi
		fi
		if [ "$scf_had_existing" == "1" ]; then
			cp "$scf_backup" "$prefix.scf.in"
		else
			rm -f "$prefix.scf.in"
		fi
		[ -n "$scf_backup" ] && rm -f "$scf_backup"
		[ -n "$scf_backup" ] && qe_cleanup_unregister "$scf_backup"
		return 0
	fi

	: > "$QE_TASK_OUTPUT" || return 1
	qe_pwin_refresh_cutoff_values || return 1
	pwin_ecutwfc="$pwin_current_ecutwfc"
	pwin_ecutrho="$pwin_current_ecutrho"
	qe_write_pw_control "$QE_TASK_OUTPUT" || return 1
	qe_write_pw_system "$QE_TASK_OUTPUT" || return 1
	qe_write_pw_electrons "$QE_TASK_OUTPUT" || return 1
	qe_write_pw_ions_cell "$QE_TASK_OUTPUT" || return 1
	qe_write_pw_structure "$QE_TASK_OUTPUT" || return 1
	qe_write_pw_kpoints "$QE_TASK_OUTPUT" || return 1
	qe_write_pw_hubbard "$QE_TASK_OUTPUT" || return 1
}


function qe_generate_pw_input (){
	local output
	qe_validate_calc_prefix "$prefix" || return 1
	qe_task_profile "$rtask" || return 1
	output="$QE_TASK_OUTPUT"
	qe_generate_in_staging pwin "$output" qe_generate_pw_input_unsafe
}

#--------------------------------- pw.x MD input module----------------------------------------






