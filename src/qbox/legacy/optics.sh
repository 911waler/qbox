#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_embedded_plot_epsilon (){
qbox_python -m qbox.postprocess.optics_plot "$@"
}

function qe_find_epsilon_plot_data_in_dir (){
	local epsilon_dir="$1"
	local calc_prefix="$2"
	if [ -n "$calc_prefix" ] && [ -f "${epsilon_dir}/epsr_${calc_prefix}.dat" ] && [ -f "${epsilon_dir}/epsi_${calc_prefix}.dat" ]; then
		echo "$calc_prefix"
		return 0
	fi
	for candidate in "${epsilon_dir}"/epsr_*.dat; do
		if [ -f "$candidate" ]; then
			local suffix="${candidate##*/epsr_}"
			suffix="${suffix%.dat}"
			if [ -f "${epsilon_dir}/epsi_${suffix}.dat" ]; then
				echo "$suffix"
				return 0
			fi
		fi
	done
	return 1
}

function qe_epsilon_quantity_description (){
	case "$1" in
		dielectric)
			echo "复介电函数描述材料对外电磁场的整体线性响应；实部 epsilon1 主要反映极化/色散，虚部 epsilon2 主要反映光吸收和能量损耗。"
			;;
		n)
			echo "折射率 n 描述光在材料中的相速度降低和传播方向改变，数值越大通常表示光在材料中传播越慢。"
			;;
		kappa)
			echo "消光系数 kappa 是复折射率的虚部，描述电磁波在材料中因吸收而衰减的强弱。"
			;;
		alpha)
			echo "吸收系数 alpha 描述了吸收光谱。"
			;;
		absorptance)
			echo "吸收率 A 表示厚度为 d 的样品单程吸收比例，使用 A=1-exp(-alpha*d)，该估计忽略界面反射和多重反射。"
			;;
		reflectance)
			echo "正入射反射率 R 表示光从空气/真空垂直入射到材料表面时被反射的强度比例。"
			;;
		*)
			echo ""
			;;
	esac
}

function plot_qe_epsilon (){
	local plot_scope epsilon_dir calc_prefix found_prefix choice kind thickness_nm output_prefix plot_command plot_status kind_label kind_description output_suffix

	echo
	echo ' 该功能绘制已有 epsilon.x 输出，不重新运行 scf/nscf/epsilon.x。'
	plot_scope=`qe_prompt_plot_data_scope "光吸收/介电函数"`
	if [ "$plot_scope" == "calcdir" ]; then
		epsilon_dir="Epsilon"
	else
		epsilon_dir="."
	fi
	if [ ! -d "$epsilon_dir" ]; then
		echo
		echo " 错误：未找到 epsilon 绘图数据目录：$epsilon_dir"
		return 1
	fi

	calc_prefix=`qe_prompt_calc_prefix`
	found_prefix=`qe_find_epsilon_plot_data_in_dir "$epsilon_dir" "$calc_prefix"`
	if [ -z "$found_prefix" ]; then
		echo
		echo " 错误：${epsilon_dir} 中未找到 epsr_${calc_prefix}.dat / epsi_${calc_prefix}.dat 或其他 epsr/epsi 配对文件。"
		return 1
	fi
	if [ "$found_prefix" != "$calc_prefix" ]; then
		echo " 未找到指定前缀数据，改用检测到的数据前缀：${found_prefix}"
		calc_prefix="$found_prefix"
	fi

	echo
	echo ' 请选择要绘制的光学量：'
	echo "  1) 复介电函数 epsilon = epsilon1 + i epsilon2：`qe_epsilon_quantity_description dielectric`"
	echo "  2) 折射率 n：`qe_epsilon_quantity_description n`"
	echo "  3) 消光系数 kappa：`qe_epsilon_quantity_description kappa`"
	echo "  4) 吸收系数 alpha：`qe_epsilon_quantity_description alpha`"
	echo "  5) 吸收率 A = 1 - exp(-alpha*d)：`qe_epsilon_quantity_description absorptance`"
	echo "  6) 正入射反射率 R：`qe_epsilon_quantity_description reflectance`"
	read choice
	case "$choice" in
		1) kind="dielectric"; kind_label="复介电函数" ;;
		2) kind="n"; kind_label="折射率" ;;
		3) kind="kappa"; kind_label="消光系数" ;;
		4) kind="alpha"; kind_label="吸收系数" ;;
		5) kind="absorptance"; kind_label="吸收率" ;;
		6) kind="reflectance"; kind_label="正入射反射率" ;;
		*) echo ' 无效选项，默认绘制复介电函数。'; kind="dielectric"; kind_label="复介电函数" ;;
	esac
	kind_description=`qe_epsilon_quantity_description "$kind"`

	thickness_nm="100"
	if [ "$kind" == "absorptance" ]; then
		echo
		echo ' 吸收率公式 A=1-exp(-alpha*d) 需要样品厚度 d，并忽略界面反射和多重反射。'
		echo ' 请输入样品厚度，单位 nm。直接回车使用 100。'
		read thickness_input
		if echo "$thickness_input" | awk 'NF==1 && $1 ~ /^[0-9]+([.][0-9]+)?$/ && $1 > 0 {exit 0} {exit 1}'; then
			thickness_nm="$thickness_input"
		fi
	fi

	output_suffix="$kind"
	if [ "$kind" == "alpha" ]; then
		output_suffix="吸收光谱"
	fi
	output_prefix="${epsilon_dir}/${calc_prefix}_${output_suffix}"
	plot_command="qe_embedded_plot_epsilon --directory ${epsilon_dir} --prefix ${calc_prefix} --kind ${kind} --output-prefix ${output_prefix}"
	if [ "$kind" == "absorptance" ]; then
		plot_command="${plot_command} --thickness-nm ${thickness_nm}"
	fi

	echo
	echo " 绘制 ${kind_label}：${plot_command}"
	echo " 图中物理量含义：${kind_description}"
	if [ "$kind" == "absorptance" ]; then
		qe_embedded_plot_epsilon --directory "$epsilon_dir" --prefix "$calc_prefix" --kind "$kind" --output-prefix "$output_prefix" --thickness-nm "$thickness_nm"
	else
		qe_embedded_plot_epsilon --directory "$epsilon_dir" --prefix "$calc_prefix" --kind "$kind" --output-prefix "$output_prefix"
	fi
	if [ $? -eq 0 ] && [ -f "${output_prefix}.png" ] && [ -f "${output_prefix}.svg" ]; then
		plot_status="success"
	else
		plot_status="failed"
	fi

	echo
	echo '=============================== 使用的计算命令 ==============================='
	echo " 1) ${plot_command}"
	echo '================================================================================'
	echo
	echo '=============================== 绘图总结报告 ================================='
	qe_print_status_line 'plot-epsilon 是否绘图成功' "$plot_status"
	echo " ${kind_label} 图代表的物理含义：${kind_description}"
	echo '================================================================================'
	[ "$plot_status" != "failed" ]
}

function qe_polar_output_success (){
	local axis="$1"
	[ -s "Polar/polar-${axis}.out" ] || return 1
	qe_output_success "Polar/polar-${axis}.out" || return 1
	grep -q "POLARIZATION CALCULATION" "Polar/polar-${axis}.out" || return 1
}

function qe_ask_recalculate_polar_completed (){
	local calc_prefix has_completed answer
	calc_prefix="$1"
	has_completed=0
	qe_output_success_for_prefix scf.out "$calc_prefix" && has_completed=1
	qe_polar_output_success x && has_completed=1
	qe_polar_output_success y && has_completed=1
	qe_polar_output_success z && has_completed=1

	if [ "$has_completed" != "1" ]; then
		echo "no"
		return 0
	fi

	qe_prompt_yes_no answer \
		' 检测到当前目录已有部分结构极性计算结果。是否重新计算已完成步骤？' \
		'否，跳过已经成功完成的步骤' \
		'是，全部重新计算' 1>&2 || return 1
	echo "$answer"
}

function qe_prepare_polar_input (){
	local infile="$1"
	local outfile="$2"
	local gdir="$3"
	local nppstr="$4"
	local kfactor="$5"

	awk -v gdir="$gdir" -v nppstr="$nppstr" -v kfactor="$kfactor" '
	  BEGIN{in_control=0; in_system=0; control_done=0; occ_done=0}
	  function isnum(x){ return (x ~ /^[0-9]+$/) }
	  tolower($0) ~ /^[[:space:]]*&control/ {in_control=1; print; next}
	  in_control && /^[[:space:]]*calculation[[:space:]]*=/ {
	    print "   calculation     = '\''nscf'\''"
	    next
	  }
	  in_control && /^[[:space:]]*outdir[[:space:]]*=/ {
	    print "   outdir          = '\''../tmp'\''"
	    next
	  }
	  in_control && /^[[:space:]]*verbosity[[:space:]]*=/ {
	    print "   verbosity       = '\''high'\''"
	    next
	  }
	  in_control && /^[[:space:]]*(lberry|gdir|nppstr)[[:space:]]*=/ {next}
	  in_control && /^[[:space:]]*\// {
	    print "   lberry         = .true.,"
	    print "   gdir           = " gdir ","
	    print "   nppstr         = " nppstr ","
	    in_control=0
	    print
	    next
	  }
	  tolower($0) ~ /^[[:space:]]*&system/ {in_system=1; print; next}
	  in_system && /^[[:space:]]*occupations[[:space:]]*=/ {
	    print "   occupations     = '\''fixed'\''"
	    occ_done=1
	    next
	  }
	  in_system && /^[[:space:]]*(degauss|smearing)[[:space:]]*=/ {next}
	  in_system && /^[[:space:]]*\// {
	    if (occ_done==0) {
	      print "   occupations     = '\''fixed'\''"
	      occ_done=1
	    }
	    in_system=0
	    print
	    next
	  }
	  tolower($0) ~ /^[[:space:]]*k_points[[:space:]]+automatic/ {
	    print
	    getline meshline
	    split(meshline, a, /[[:space:]]+/)
	    cnt=0; rest=""
	    for (i=1;i<=length(a);i++) {
	      if (a[i] != "") {
	        cnt++
	        tok[cnt]=a[i]
	      }
	    }
	    if (cnt >= 3 && isnum(tok[1]) && isnum(tok[2]) && isnum(tok[3])) {
	      n1=tok[1]; n2=tok[2]; n3=tok[3]
	      if (gdir==1) n1*=kfactor
	      if (gdir==2) n2*=kfactor
	      if (gdir==3) n3*=kfactor
	      for (j=4;j<=cnt;j++) rest = rest " " tok[j]
	      printf "%d %d %d%s\n", n1, n2, n3, rest
	    } else {
	      print meshline
	    }
	    next
	  }
	  {print}
	' "$infile" > "$outfile"
}

function qe_print_polarization_summary (){
	local outfile="$1"
	if [ ! -f "$outfile" ]; then
		return 0
	fi
	grep -E "P =|\\(e/Omega\\)\\.bohr|e/bohr\\^2|C/m\\^2" "$outfile" | tail -n 8
}

function qe_write_polarization_data (){
	local data_file="Polar/Polar-data.txt"
	{
		echo "Generated by qbox"
		echo "Date: `date '+%Y-%m-%d %H:%M:%S'`"
		echo
		echo "[x direction]"
		qe_print_polarization_summary Polar/polar-x.out
		echo
		echo "[y direction]"
		qe_print_polarization_summary Polar/polar-y.out
		echo
		echo "[z direction]"
		qe_print_polarization_summary Polar/polar-z.out
	} > "$data_file"
	echo " 极化数据已保存：${data_file}"
}

function qe_element_index_from_symbol (){
	local symbol="$1"
	local idx
	for ((idx=1;idx<=103;idx++)); do
		if [ "${atm[$idx]}" == "$symbol" ]; then
			echo "$idx"
			return 0
		fi
	done
	return 1
}

function qe_render_pd04_pseudos (){
	local infile="$1"
	local line in_species symbol mass idx ppfile pd04dir
	pd04dir=`pseudo_dir_by_lib "PD04"`
	in_species=0
	while IFS= read -r line || [ -n "$line" ]; do
		if echo "$line" | grep -Eq "^[[:space:]]*pseudo_dir[[:space:]]*="; then
			echo "   pseudo_dir      = '${pd04dir}'"
			continue
		fi
		if echo "$line" | grep -Eq "^[[:space:]]*ATOMIC_SPECIES"; then
			echo "$line"
			in_species=1
			continue
		fi
		if [ "$in_species" == "1" ] && echo "$line" | grep -Eq "^[[:space:]]*(ATOMIC_POSITIONS|CELL_PARAMETERS|K_POINTS|&|/)" ; then
			in_species=0
			echo "$line"
			continue
		fi
		if [ "$in_species" == "1" ] && echo "$line" | grep -Eq "^[[:space:]]*[A-Za-z][A-Za-z]?[[:space:]]+"; then
			symbol=`echo "$line" | awk '{print $1}'`
			mass=`echo "$line" | awk '{print $2}'`
			idx=`qe_element_index_from_symbol "$symbol"`
			ppfile=`pseudo_file_by_lib "PD04" "$idx"`
			if [ -n "$ppfile" ]; then
				echo "   ${symbol}  ${mass}  ${ppfile}"
			else
				echo "$line"
			fi
			continue
		fi
		echo "$line"
	done < "$infile"
}

function qe_rewrite_pseudopotentials_to_pd04 (){
	local infile="$1"
	[ -f "$infile" ] || return 1
	qe_atomic_rewrite "$infile" qe_render_pd04_pseudos
}

function qe_prepare_epsilon_scf_input (){
	local infile="$1"
	local outfile="$2"
	local occ="$3"
	local smearing="$4"
	local degauss="$5"
	awk -v occ="$occ" -v smearing="$smearing" -v degauss="$degauss" -v pd04dir="$PD04PBEpath" '
	  BEGIN{in_control=0; in_system=0; occ_done=0}
	  tolower($0) ~ /^[[:space:]]*&control/ {in_control=1; print; next}
	  in_control && /^[[:space:]]*calculation[[:space:]]*=/ {
	    print "   calculation     = '\''scf'\''"
	    next
	  }
	  in_control && /^[[:space:]]*outdir[[:space:]]*=/ {
	    print "   outdir          = '\''./tmp'\''"
	    next
	  }
	  in_control && /^[[:space:]]*pseudo_dir[[:space:]]*=/ {
	    print "   pseudo_dir      = '\''" pd04dir "'\''"
	    next
	  }
	  in_control && /^[[:space:]]*\// {in_control=0; print; next}
	  tolower($0) ~ /^[[:space:]]*&system/ {in_system=1; print; next}
	  in_system && /^[[:space:]]*occupations[[:space:]]*=/ {
	    print "   occupations     = '\''" occ "'\''"
	    if (occ=="smearing") {
	      print "   smearing        = '\''" smearing "'\''"
	      print "   degauss         = " degauss
	    }
	    occ_done=1
	    next
	  }
	  in_system && /^[[:space:]]*(smearing|degauss)[[:space:]]*=/ {next}
	  in_system && /^[[:space:]]*\// {
	    if (occ_done==0) {
	      print "   occupations     = '\''" occ "'\''"
	      if (occ=="smearing") {
	        print "   smearing        = '\''" smearing "'\''"
	        print "   degauss         = " degauss
	      }
	    }
	    in_system=0
	    print
	    next
	  }
	  {print}
	' "$infile" > "$outfile"
	qe_rewrite_pseudopotentials_to_pd04 "$outfile"
}

function qe_prepare_epsilon_nscf_input (){
	local infile="$1"
	local outfile="$2"
	local nbnd="$3"
	local kfactor="$4"
	local occ="$5"
	local smearing="$6"
	local degauss="$7"
	awk -v nbnd="$nbnd" -v kfactor="$kfactor" -v occ="$occ" -v smearing="$smearing" -v degauss="$degauss" -v pd04dir="$PD04PBEpath" '
		  BEGIN{in_control=0; in_system=0; nbnd_done=0; occ_done=0; nosym_done=0; noinv_done=0}
	  function isnum(x){ return (x ~ /^[0-9]+$/) }
	  tolower($0) ~ /^[[:space:]]*&control/ {in_control=1; print; next}
	  in_control && /^[[:space:]]*calculation[[:space:]]*=/ {
	    print "   calculation     = '\''nscf'\''"
	    next
	  }
	  in_control && /^[[:space:]]*outdir[[:space:]]*=/ {
	    print "   outdir          = '\''./tmp'\''"
	    next
	  }
	  in_control && /^[[:space:]]*pseudo_dir[[:space:]]*=/ {
	    print "   pseudo_dir      = '\''" pd04dir "'\''"
	    next
	  }
	  in_control && /^[[:space:]]*verbosity[[:space:]]*=/ {
	    print "   verbosity       = '\''high'\''"
	    next
	  }
	  in_control && /^[[:space:]]*\// {in_control=0; print; next}
	  tolower($0) ~ /^[[:space:]]*&system/ {in_system=1; print; next}
		  in_system && /^[[:space:]]*nbnd[[:space:]]*=/ {
		    print "   nbnd            = " nbnd
		    nbnd_done=1
		    next
		  }
		  in_system && tolower($0) ~ /^[[:space:]]*nosym[[:space:]]*=/ {
		    print "   nosym           = .true."
		    nosym_done=1
		    next
		  }
		  in_system && tolower($0) ~ /^[[:space:]]*noinv[[:space:]]*=/ {
		    print "   noinv           = .true."
		    noinv_done=1
		    next
		  }
	  in_system && /^[[:space:]]*occupations[[:space:]]*=/ {
	    print "   occupations     = '\''" occ "'\''"
	    if (occ=="smearing") {
	      print "   smearing        = '\''" smearing "'\''"
	      print "   degauss         = " degauss
	    }
	    occ_done=1
	    next
	  }
	  in_system && /^[[:space:]]*(smearing|degauss)[[:space:]]*=/ {next}
		  in_system && /^[[:space:]]*\// {
		    if (nbnd_done==0) print "   nbnd            = " nbnd
		    if (nosym_done==0) print "   nosym           = .true."
		    if (noinv_done==0) print "   noinv           = .true."
		    if (occ_done==0) {
	      print "   occupations     = '\''" occ "'\''"
	      if (occ=="smearing") {
	        print "   smearing        = '\''" smearing "'\''"
	        print "   degauss         = " degauss
	      }
	    }
	    in_system=0
	    print
	    next
	  }
	  tolower($0) ~ /^[[:space:]]*k_points[[:space:]]+automatic/ {
	    print
	    getline meshline
	    split(meshline, a, /[[:space:]]+/)
	    cnt=0; rest=""
	    for (i=1;i<=length(a);i++) {
	      if (a[i] != "") {cnt++; tok[cnt]=a[i]}
	    }
	    if (cnt >= 3 && isnum(tok[1]) && isnum(tok[2]) && isnum(tok[3])) {
	      n1=tok[1]*kfactor; n2=tok[2]*kfactor; n3=tok[3]*kfactor
	      for (j=4;j<=cnt;j++) rest = rest " " tok[j]
	      printf "%d %d %d%s\n", n1, n2, n3, rest
	    } else {
	      print meshline
	    }
	    next
	  }
	  {print}
	' "$infile" > "$outfile"
	qe_rewrite_pseudopotentials_to_pd04 "$outfile"
}

function qe_write_epsilon_input_file (){
	local outfile="$1"
	local calc_prefix="$2"
	local outdir="$3"
	local intersmear="$4"
	local intrasmear="$5"
	local wmin="$6"
	local wmax="$7"
	local nw="$8"
	{
		echo '&inputpp'
		echo "    calculation = 'eps',"
		echo "    prefix      = '${calc_prefix}',"
		echo "    outdir      = '${outdir}',"
		echo '/'
		echo '&energy_grid'
		echo "    smeartype  = 'gauss'"
		echo "    intersmear = ${intersmear}"
		echo "    intrasmear = ${intrasmear}"
		echo "    wmin       = ${wmin}"
		echo "    wmax       = ${wmax}"
		echo "    nbndmin    = 1"
		echo "    nbndmax    = 0"
		echo "    nw         = ${nw}"
		echo "    shift      = 0.0"
		echo '/'
	} > "$outfile"
}

function qe_epsilon_scf_success (){
	local calc_prefix="$1"
	qe_output_success Epsilon/scf.out || return 1
	[ -d "Epsilon/tmp/${calc_prefix}.save" ] || return 1
}

function qe_epsilon_nscf_success (){
	local calc_prefix="$1"
	qe_output_success Epsilon/nscf.out || return 1
	[ -d "Epsilon/tmp/${calc_prefix}.save" ] || return 1
}

function qe_epsilon_output_success (){
	qe_output_success Epsilon/epsilon.out || return 1
	{ compgen -G "Epsilon/epsi_*.dat" >/dev/null && compgen -G "Epsilon/epsr_*.dat" >/dev/null; }
}

function qe_ask_recalculate_epsilon_completed (){
	local calc_prefix has_completed answer
	calc_prefix="$1"
	has_completed=0
	qe_epsilon_scf_success "$calc_prefix" && has_completed=1
	qe_epsilon_nscf_success "$calc_prefix" && has_completed=1
	qe_epsilon_output_success && has_completed=1
	if [ "$has_completed" != "1" ]; then
		echo "no"
		return 0
	fi
	qe_prompt_yes_no answer \
		' 检测到当前目录已有部分光吸收/介电函数计算结果。是否重新计算已完成步骤？' \
		'否，跳过已经成功完成的步骤' \
		'是，全部重新计算' 1>&2 || return 1
	echo "$answer"
}

function qe_read_number_of_electrons (){
	local file nelec
	for file in "$@"; do
		[ -f "$file" ] || continue
		nelec=`awk '
			/number of electrons[[:space:]]*=/ {
				for(i=1;i<=NF;i++){
					if($i=="=" && (i+1)<=NF){val=$(i+1)}
				}
			}
			END{if(val!="") print val}
		' "$file"`
		if echo "$nelec" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
			echo "$nelec"
			return 0
		fi
	done
	return 1
}

function qe_recommend_nbnd_from_nelec (){
	local nelec="$1"
	local factor="$2"
	awk -v nelec="$nelec" -v factor="$factor" 'BEGIN{
		nbnd=int(nelec*factor)
		if(nbnd < nelec*factor) nbnd++
		if(nbnd < 1) nbnd=1
		printf "%d", nbnd
	}'
}

function qe_epsilon_occupation_label (){
	local occ="$1"
	local smearing="$2"
	local degauss="$3"
	if [ "$occ" == "smearing" ]; then
		echo "occupations='smearing', smearing='${smearing}', degauss=${degauss} Ry"
	else
		echo "occupations='fixed'，无展宽"
	fi
}

function qe_epsilon_system_label (){
	case "$1" in
		Insulator) echo "绝缘体" ;;
		Semi-conductor) echo "半导体" ;;
		Conductor) echo "导体/金属" ;;
		Doped-gapped) echo "掺杂体系：有带隙" ;;
		Doped-metallic) echo "掺杂体系：费米面穿过能带" ;;
		*) echo "半导体" ;;
	esac
}

function qe_epsilon_recommended_value (){
	local system_type="$1"
	local field="$2"
	case "$system_type:$field" in
		Insulator:kfactor|Semi-conductor:kfactor|Doped-gapped:kfactor) echo "2" ;;
		Conductor:kfactor|Doped-metallic:kfactor) echo "3" ;;
		Insulator:intersmear) echo "0.10" ;;
		Semi-conductor:intersmear|Doped-gapped:intersmear) echo "0.20" ;;
		Conductor:intersmear|Doped-metallic:intersmear) echo "0.50" ;;
		Insulator:intrasmear|Semi-conductor:intrasmear|Doped-gapped:intrasmear) echo "0.0" ;;
		Conductor:intrasmear|Doped-metallic:intrasmear) echo "0.10" ;;
		Insulator:wmin|Semi-conductor:wmin|Conductor:wmin|Doped-gapped:wmin|Doped-metallic:wmin) echo "0.0" ;;
		Insulator:wmax|Semi-conductor:wmax|Doped-gapped:wmax) echo "30.0" ;;
		Conductor:wmax|Doped-metallic:wmax) echo "20.0" ;;
		Insulator:nw|Semi-conductor:nw|Doped-gapped:nw) echo "3000" ;;
		Conductor:nw|Doped-metallic:nw) echo "2000" ;;
		*) echo "" ;;
	esac
}

function qe_apply_epsilon_system_recommendations (){
	epsilon_kfactor=`qe_epsilon_recommended_value "$epsilon_system_type" kfactor`
	epsilon_intersmear=`qe_epsilon_recommended_value "$epsilon_system_type" intersmear`
	epsilon_intrasmear=`qe_epsilon_recommended_value "$epsilon_system_type" intrasmear`
	epsilon_wmin=`qe_epsilon_recommended_value "$epsilon_system_type" wmin`
	epsilon_wmax=`qe_epsilon_recommended_value "$epsilon_system_type" wmax`
	epsilon_nw=`qe_epsilon_recommended_value "$epsilon_system_type" nw`
}

function qe_epsilon_recommendation_summary (){
	local system_type="$1"
	echo "K点加密=`qe_epsilon_recommended_value "$system_type" kfactor`，intersmear=`qe_epsilon_recommended_value "$system_type" intersmear` eV，intrasmear=`qe_epsilon_recommended_value "$system_type" intrasmear` eV，能量范围=`qe_epsilon_recommended_value "$system_type" wmin`-`qe_epsilon_recommended_value "$system_type" wmax` eV，nw=`qe_epsilon_recommended_value "$system_type" nw`"
}

function qe_epsilon_settings_menu (){
	local choice value wmax_input
	while true; do
		echo
		echo '========================= 光吸收/介电函数输入文件设置 ========================='
		if qe_nelec_is_odd_integer "$epsilon_nelec"; then
			echo " 奇数电子设定已锁定：occupations='smearing'、smearing='marzari-vanderbilt'、degauss=0.002 Ry"
		fi
		echo ' 0) 生成/更新 Epsilon 输入文件并继续计算'
		echo " 1) SCF/NSCF 体系类型：`qe_epsilon_system_label "$epsilon_system_type"`；`qe_epsilon_occupation_label "$epsilon_occ" "$epsilon_smearing" "$epsilon_degauss"`"
		echo " 2) NSCF K 点加密倍数：${epsilon_kfactor}"
		echo " 3) nbnd 推荐倍数：number of electrons × ${epsilon_nbnd_factor}"
		echo " 4) epsilon.x 带间展宽 intersmear：${epsilon_intersmear} eV"
		echo " 5) epsilon.x 带内展宽 intrasmear：${epsilon_intrasmear} eV"
		echo " 6) epsilon.x 能量范围：${epsilon_wmin} 到 ${epsilon_wmax} eV"
		echo " 7) epsilon.x 能量网格点数 nw：${epsilon_nw}"
		echo ' 8) 返回'
		echo '========================================================================'
		echo ' 请输入要修改/执行的编号。'
		read choice
		case "$choice" in
			"0")
				return 0
				;;
			"1")
				echo
				echo " 当前体系类型：`qe_epsilon_system_label "$epsilon_system_type"`"
				echo " 当前 occupations 设置：`qe_epsilon_occupation_label "$epsilon_occ" "$epsilon_smearing" "$epsilon_degauss"`"
				echo ' 更改体系类型将重置 K 点、展宽和能量网格参数。'
				echo
				echo ' 请选择体系类型：'
				echo "  1) 绝缘体：occupations='fixed'，无展宽；推荐 `qe_epsilon_recommendation_summary Insulator`"
				echo "  2) 半导体：occupations='fixed'，无展宽；推荐 `qe_epsilon_recommendation_summary Semi-conductor`"
				echo "  3) 导体/金属：occupations='smearing', smearing='gauss', degauss=1.0d-4 Ry；推荐 `qe_epsilon_recommendation_summary Conductor`"
				echo "  4) 掺杂体系：有带隙，occupations='fixed'，无展宽；推荐 `qe_epsilon_recommendation_summary Doped-gapped`"
				echo "  5) 掺杂体系：费米面穿过能带，occupations='smearing', smearing='gauss', degauss=1.0d-4 Ry；推荐 `qe_epsilon_recommendation_summary Doped-metallic`"
				read value
				case "$value" in
					1) epsilon_system_type="Insulator"; epsilon_occ="fixed"; epsilon_smearing="gauss"; epsilon_degauss="1.0d-4"; qe_apply_epsilon_system_recommendations ;;
					2) epsilon_system_type="Semi-conductor"; epsilon_occ="fixed"; epsilon_smearing="gauss"; epsilon_degauss="1.0d-4"; qe_apply_epsilon_system_recommendations ;;
					3) epsilon_system_type="Conductor"; epsilon_occ="smearing"; epsilon_smearing="gauss"; epsilon_degauss="1.0d-4"; qe_apply_epsilon_system_recommendations ;;
					4) epsilon_system_type="Doped-gapped"; epsilon_occ="fixed"; epsilon_smearing="gauss"; epsilon_degauss="1.0d-4"; qe_apply_epsilon_system_recommendations ;;
					5) epsilon_system_type="Doped-metallic"; epsilon_occ="smearing"; epsilon_smearing="gauss"; epsilon_degauss="1.0d-4"; qe_apply_epsilon_system_recommendations ;;
				esac
				;;
			"2")
				echo
				epsilon_kfactor=`qe_prompt_positive_int_default " NSCF K 点加密倍数 [当前 ${epsilon_kfactor}，回车保留]：" "$epsilon_kfactor"`
				;;
			"3")
				echo
				echo " 当前 nbnd 推荐倍数：number of electrons × ${epsilon_nbnd_factor}"
				echo " 请输入倍数。直接回车使用：${epsilon_nbnd_factor}"
				read value
				if echo "$value" | awk 'NF==1 && $1 ~ /^[0-9]+([.][0-9]+)?$/ && $1 > 0 {exit 0} {exit 1}'; then epsilon_nbnd_factor="$value"; fi
				;;
			"4")
				echo
				epsilon_intersmear=`qe_prompt_default " 带间展宽 intersmear (eV) [当前 ${epsilon_intersmear}，回车保留]：" "$epsilon_intersmear"`
				;;
			"5")
				echo
				epsilon_intrasmear=`qe_prompt_default " 带内展宽 intrasmear (eV) [当前 ${epsilon_intrasmear}，回车保留]：" "$epsilon_intrasmear"`
				;;
			"6")
				echo
				echo " 能量范围 wmin wmax (eV) [当前 ${epsilon_wmin} ${epsilon_wmax}，回车保留]："
				read value wmax_input
				if [ -n "$value" ] && [ -n "$wmax_input" ]; then
					epsilon_wmin="$value"
					epsilon_wmax="$wmax_input"
				fi
				;;
			"7")
				echo
				epsilon_nw=`qe_prompt_positive_int_default " 能量网格点数 nw [当前 ${epsilon_nw}，回车保留]：" "$epsilon_nw"`
				;;
			"8")
				return 1
				;;
			*)
				echo ' 请输入有效编号。'
				;;
		esac
	done
}

function run_qe_epsilon_calculation (){
	local calc_prefix base_scf scf_input nscf_input epsilon_input
	local recalc_completed all_epsilon_steps_done scf_threads nscf_threads epsilon_threads nbnd nelec epsilon_nelec
	local scf_status nscf_status epsilon_status
	local scf_command nscf_command epsilon_command
	local recommended_scf_threads recommended_nscf_threads atom_count
	local old_pwin_default_pseudolib stage_rc

	echo
	calc_prefix=`qe_prompt_calc_prefix`
	base_scf="${calc_prefix}.scf.in"
	mkdir -p Epsilon
	scf_input="Epsilon/${calc_prefix}.epsilon.scf.in"
	nscf_input="Epsilon/${calc_prefix}.epsilon.nscf.in"
	epsilon_input="Epsilon/epsilon.in"

	if [ ! -f "$base_scf" ]; then
		qe_print_input_generation_header "$base_scf" "pw.x / SCF（光学）"
		echo " 缺少 ${base_scf}，转入 pw.x SCF 输入文件生成流程。"
		old_pwin_default_pseudolib="$PWIN_DEFAULT_PSEUDOLIB"
		PWIN_DEFAULT_PSEUDOLIB="PD04"
		qe_generate_pwin_for_task "$calc_prefix" "energy" "$base_scf" || {
			PWIN_DEFAULT_PSEUDOLIB="$old_pwin_default_pseudolib"
			echo ' 错误：SCF 输入文件生成失败。'
			return 1
		}
		PWIN_DEFAULT_PSEUDOLIB="$old_pwin_default_pseudolib"
	fi
	if [ ! -f "$base_scf" ]; then
		echo " 错误：仍缺少 ${base_scf}，已停止光吸收/介电函数计算。"
		return 1
	fi

	if ! recalc_completed=`qe_ask_recalculate_epsilon_completed "$calc_prefix"`; then
		return 1
	fi
	all_epsilon_steps_done=0
	if [ "$recalc_completed" == "no" ] && qe_epsilon_scf_success "$calc_prefix" && qe_epsilon_nscf_success "$calc_prefix" && qe_epsilon_output_success; then
		all_epsilon_steps_done=1
	fi
	epsilon_system_type="Semi-conductor"
	epsilon_occ="fixed"
	epsilon_smearing="gauss"
	epsilon_degauss="1.0d-4"
	epsilon_nbnd_factor="3"
	qe_apply_epsilon_system_recommendations
	epsilon_nelec=`qe_estimate_nelec_from_pwin_file "$base_scf" 2>/dev/null`
	if qe_nelec_is_odd_integer "$epsilon_nelec"; then
		epsilon_occ="smearing"
		epsilon_smearing="marzari-vanderbilt"
		epsilon_degauss="0.002"
		qe_print_odd_electron_notice "$epsilon_nelec" "光学 SCF/NSCF 使用 occupations='smearing'、smearing='marzari-vanderbilt'、degauss=0.002 Ry"
	fi
	if [ "$all_epsilon_steps_done" != "1" ]; then
		qe_epsilon_settings_menu || return 0
	fi
	if qe_nelec_is_odd_integer "$epsilon_nelec"; then
		if [ "$epsilon_occ" != "smearing" ] || [ "$epsilon_smearing" != "marzari-vanderbilt" ] || [ "$epsilon_degauss" != "0.002" ]; then
			epsilon_occ="smearing"
			epsilon_smearing="marzari-vanderbilt"
			epsilon_degauss="0.002"
			qe_print_odd_electron_notice "$epsilon_nelec" "已覆盖菜单中的占据设置；光学 SCF/NSCF 使用 occupations='smearing'、smearing='marzari-vanderbilt'、degauss=0.002 Ry"
		fi
	fi

	if [ "$all_epsilon_steps_done" != "1" ]; then
		qe_ensure_runtime_for mpirun pw.x epsilon.x || {
			echo ' 错误：QE 运行环境未通过检查，已停止光学计算。'
			return 1
		}
		qe_report_compute_resources
		recommended_scf_threads=`qe_recommend_pw_threads "$calc_prefix" "scf"`
		recommended_nscf_threads=`qe_recommend_pw_threads "$calc_prefix" "nscf"`
		atom_count=`qe_estimate_atom_count "$calc_prefix"`
		if [ -n "$atom_count" ]; then
			scf_threads=`qe_prompt_positive_int_default " optical SCF pw.x MPI 进程数 N1 [原子数 ${atom_count}，回车 ${recommended_scf_threads}]：" "$recommended_scf_threads"` || return 1
			nscf_threads=`qe_prompt_positive_int_default " optical NSCF pw.x MPI 进程数 N2 [原子数 ${atom_count}，回车 ${recommended_nscf_threads}]：" "$recommended_nscf_threads"` || return 1
		else
			scf_threads=`qe_prompt_positive_int_default " optical SCF pw.x MPI 进程数 N1 [回车 ${recommended_scf_threads}]：" "$recommended_scf_threads"` || return 1
			nscf_threads=`qe_prompt_positive_int_default " optical NSCF pw.x MPI 进程数 N2 [回车 ${recommended_nscf_threads}]：" "$recommended_nscf_threads"` || return 1
		fi
		epsilon_threads=`qe_prompt_positive_int_default ' 请输入 epsilon.x 使用的 MPI 进程数 N3。直接回车使用 16。' '16'` || return 1
	fi

	echo
	echo ' 光吸收/介电函数输入文件将自动使用 PD04 Norm-conserving 赝势库。'

	if [ "$recalc_completed" == "yes" ] || [ ! -f "$scf_input" ]; then
		qe_print_input_generation_header "$scf_input" "pw.x / optical SCF"
		qe_prepare_epsilon_scf_input "$base_scf" "$scf_input" "$epsilon_occ" "$epsilon_smearing" "$epsilon_degauss"
	fi

	if [ "$all_epsilon_steps_done" == "1" ]; then
		scf_command="跳过：已有成功的 Epsilon/scf.out"
		nscf_command="跳过：已有成功的 Epsilon/nscf.out"
		epsilon_command="跳过：已有成功的 Epsilon/epsilon.out 和 epsr/epsi 数据"
	else
		scf_command="cd Epsilon && mpirun -np ${scf_threads} pw.x -in ${calc_prefix}.epsilon.scf.in 2>&1 | tee scf.out"
		nscf_command="cd Epsilon && mpirun -np ${nscf_threads} pw.x -in ${calc_prefix}.epsilon.nscf.in 2>&1 | tee nscf.out"
		epsilon_command="cd Epsilon && mpirun -np ${epsilon_threads} epsilon.x -in epsilon.in 2>&1 | tee epsilon.out"
	fi

	echo
	if [ "$recalc_completed" == "no" ] && qe_epsilon_scf_success "$calc_prefix"; then
		echo " 跳过 optical SCF：已有成功的 Epsilon/scf.out。"
		scf_status="skipped"
	else
		echo " 开始 optical SCF：${scf_command}"
		qe_run_stage scf_status Epsilon scf.out qe_epsilon_scf_success "$calc_prefix" -- \
			mpirun -np "$scf_threads" pw.x -in "${calc_prefix}.epsilon.scf.in"
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	if [ "$scf_status" != "failed" ]; then
		nelec=`qe_read_number_of_electrons Epsilon/scf.out scf.out`
		if [ -n "$nelec" ]; then
			nbnd=`qe_recommend_nbnd_from_nelec "$nelec" "$epsilon_nbnd_factor"`
			echo
			echo " 已读取 number of electrons = ${nelec}；设置 optical NSCF nbnd = ${nbnd}。"
		else
			nbnd="300"
			echo
			echo " 警告：未能读取 number of electrons；optical NSCF nbnd 回退为 ${nbnd}。"
		fi
		if [ "$recalc_completed" == "yes" ] || [ ! -f "$nscf_input" ]; then
			qe_print_input_generation_header "$nscf_input" "pw.x / optical NSCF"
			qe_prepare_epsilon_nscf_input "$base_scf" "$nscf_input" "$nbnd" "$epsilon_kfactor" "$epsilon_occ" "$epsilon_smearing" "$epsilon_degauss"
		fi
		if [ "$recalc_completed" == "yes" ] || [ ! -f "$epsilon_input" ]; then
			qe_print_input_generation_header "$epsilon_input" "epsilon.x / 光吸收与介电函数"
			qe_write_epsilon_input_file "$epsilon_input" "$calc_prefix" "./tmp" "$epsilon_intersmear" "$epsilon_intrasmear" "$epsilon_wmin" "$epsilon_wmax" "$epsilon_nw"
		fi
	fi

	echo
	if [ "$recalc_completed" == "no" ] && qe_epsilon_nscf_success "$calc_prefix"; then
		echo " 跳过 optical NSCF：已有成功的 Epsilon/nscf.out。"
		nscf_status="skipped"
	elif [ "$scf_status" == "failed" ]; then
		echo " 跳过 optical NSCF：SCF 失败。"
		nscf_status="failed"
	else
		echo " 开始 optical NSCF：${nscf_command}"
		qe_run_stage nscf_status Epsilon nscf.out qe_epsilon_nscf_success "$calc_prefix" -- \
			mpirun -np "$nscf_threads" pw.x -in "${calc_prefix}.epsilon.nscf.in"
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	echo
	if [ "$recalc_completed" == "no" ] && qe_epsilon_output_success; then
		echo " 跳过 epsilon.x：已有成功的 Epsilon/epsilon.out 和 epsr/epsi 数据。"
		epsilon_status="skipped"
	elif [ "$nscf_status" == "failed" ]; then
		echo " 跳过 epsilon.x：NSCF 失败。"
		epsilon_status="failed"
	else
		echo " 开始 epsilon.x：${epsilon_command}"
		qe_run_stage epsilon_status Epsilon epsilon.out qe_epsilon_output_success -- \
			mpirun -np "$epsilon_threads" epsilon.x -in epsilon.in
		stage_rc=$?
		case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
	fi

	echo
	echo '=============================== 使用的计算命令 ==============================='
	echo " 1) ${scf_command}"
	echo " 2) ${nscf_command}"
	echo " 3) ${epsilon_command}"
	echo '================================================================================'
	echo
	echo '=============================== 计算总结报告 ================================='
	qe_print_status_line 'optical scf 是否计算成功' "$scf_status"
	qe_print_status_line 'optical nscf 是否计算成功' "$nscf_status"
	qe_print_status_line 'epsilon.x 是否计算成功' "$epsilon_status"
	echo '================================================================================'
	if [ "$scf_status" == "failed" ] || [ "$nscf_status" == "failed" ] || [ "$epsilon_status" == "failed" ]; then
		return 1
	fi
	return 0
}

function run_qe_polar_calculation (){
	local calc_prefix scf_input pw_threads polar_threads recommended_threads atom_count
	local recommended_scf_threads recommended_polar_threads
	local recalc_completed all_polar_steps_done scf_status x_status y_status z_status
	local scf_command x_command y_command z_command
	local nppstr kfactor axis gdir infile outfile status_var polar_nelec stage_rc

	echo
	calc_prefix=`qe_prompt_calc_prefix`
	scf_input="${calc_prefix}.scf.in"

	if [ ! -f "$scf_input" ]; then
		qe_print_input_generation_header "$scf_input" "pw.x / SCF（结构极性）"
		echo " 缺少 ${scf_input}，转入 pw.x SCF 输入文件生成流程。"
		qe_generate_pwin_for_task "$calc_prefix" "energy" "$scf_input" || {
			echo ' 错误：SCF 输入文件生成失败。'
			return 1
		}
	fi

	if [ ! -f "$scf_input" ]; then
		echo
		echo " 错误：仍缺少 ${scf_input}，已停止结构极性计算。"
		return 1
	fi
	polar_nelec=`qe_estimate_nelec_from_pwin_file "$scf_input" 2>/dev/null`
	if qe_nelec_is_odd_integer "$polar_nelec"; then
		qe_print_odd_electron_notice "$polar_nelec" "Berry phase 极化需要绝缘态和整数占据，不能使用普通奇数电子 smearing 设置"
		if grep -Eqi "^[[:space:]]*nspin[[:space:]]*=[[:space:]]*2([[:space:]]*,?[[:space:]]*)$" "$scf_input"; then
			echo " 检测到 nspin=2；极化 NSCF 将保持 occupations='fixed'，按自旋极化绝缘态处理。"
		else
			echo " 错误：当前奇数电子 SCF 未设置 nspin=2。Berry phase 极化流程已停止。"
			echo " 请先确认体系为自旋极化绝缘态，并在 SCF 输入中设置 nspin=2 与合理初始磁矩。"
			return 1
		fi
	fi

	if ! recalc_completed=`qe_ask_recalculate_polar_completed "$calc_prefix"`; then
		return 1
	fi
	all_polar_steps_done=0
	if [ "$recalc_completed" == "no" ] && qe_output_success_for_prefix scf.out "$calc_prefix" && qe_polar_output_success x && qe_polar_output_success y && qe_polar_output_success z; then
		all_polar_steps_done=1
	fi
	if [ "$all_polar_steps_done" != "1" ]; then
		qe_ensure_runtime_for mpirun pw.x || {
			echo ' 错误：QE 运行环境未通过检查，已停止极性计算。'
			return 1
		}
		qe_report_compute_resources
		recommended_scf_threads=`qe_recommend_pw_threads "$calc_prefix" "scf"`
		recommended_polar_threads=`qe_recommend_pw_threads "$calc_prefix" "nscf"`
		atom_count=`qe_estimate_atom_count "$calc_prefix"`
		if [ -n "$atom_count" ]; then
			pw_threads=`qe_prompt_positive_int_default " SCF pw.x MPI 进程数 N1 [原子数 ${atom_count}，回车 ${recommended_scf_threads}]：" "$recommended_scf_threads"` || return 1
			polar_threads=`qe_prompt_positive_int_default " Berry phase NSCF pw.x MPI 进程数 N2 [原子数 ${atom_count}，回车 ${recommended_polar_threads}]：" "$recommended_polar_threads"` || return 1
		else
			pw_threads=`qe_prompt_positive_int_default " SCF pw.x MPI 进程数 N1 [回车 ${recommended_scf_threads}]：" "$recommended_scf_threads"` || return 1
			polar_threads=`qe_prompt_positive_int_default " Berry phase NSCF pw.x MPI 进程数 N2 [回车 ${recommended_polar_threads}]：" "$recommended_polar_threads"` || return 1
		fi
		echo
		nppstr=`qe_prompt_positive_int_default ' 请输入 Berry phase 的 nppstr。默认 12。' '12'` || return 1
		echo
		kfactor=`qe_prompt_positive_int_default ' 请输入 Berry phase 方向 K 点加密倍数。默认 3。' '3'` || return 1
	else
		nppstr=12
		kfactor=3
	fi

	mkdir -p Polar

	if [ "$all_polar_steps_done" == "1" ]; then
		scf_command="跳过：已有成功的 scf.out 和 tmp/${calc_prefix}.save"
		x_command="跳过：已有成功的 Polar/polar-x.out"
		y_command="跳过：已有成功的 Polar/polar-y.out"
		z_command="跳过：已有成功的 Polar/polar-z.out"
	else
		scf_command="mpirun -np ${pw_threads} pw.x -in ${scf_input} 2>&1 | tee scf.out"
		x_command="cd Polar && mpirun -np ${polar_threads} pw.x -in ${calc_prefix}.polar-x.nscf.in 2>&1 | tee polar-x.out"
		y_command="cd Polar && mpirun -np ${polar_threads} pw.x -in ${calc_prefix}.polar-y.nscf.in 2>&1 | tee polar-y.out"
		z_command="cd Polar && mpirun -np ${polar_threads} pw.x -in ${calc_prefix}.polar-z.nscf.in 2>&1 | tee polar-z.out"
	fi

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

	for axis in x y z; do
		case "$axis" in
			x) gdir=1 ;;
			y) gdir=2 ;;
			z) gdir=3 ;;
		esac
		infile="Polar/${calc_prefix}.polar-${axis}.nscf.in"
		if [ "$recalc_completed" == "yes" ] || [ ! -f "$infile" ]; then
			qe_print_input_generation_header "$infile" "pw.x / Berry phase ${axis} 方向 NSCF"
			qe_prepare_polar_input "$scf_input" "$infile" "$gdir" "$nppstr" "$kfactor"
		fi
	done

	for axis in x y z; do
		status_var="${axis}_status"
		if [ "$recalc_completed" == "no" ] && qe_polar_output_success "$axis"; then
			echo
			echo " 跳过 ${axis} 方向 Berry phase NSCF：已有成功的 Polar/polar-${axis}.out。"
			printf -v "$status_var" '%s' skipped
		elif [ "$scf_status" == "failed" ]; then
			echo
			echo " 跳过 ${axis} 方向 Berry phase NSCF：SCF 失败。"
			printf -v "$status_var" '%s' failed
		else
			echo
			echo " 开始 ${axis} 方向 Berry phase NSCF：cd Polar && mpirun -np ${polar_threads} pw.x -in ${calc_prefix}.polar-${axis}.nscf.in 2>&1 | tee polar-${axis}.out"
			qe_run_stage "$status_var" Polar "polar-${axis}.out" qe_polar_output_success "$axis" -- \
				mpirun -np "$polar_threads" pw.x -in "${calc_prefix}.polar-${axis}.nscf.in"
			stage_rc=$?
			case "$stage_rc" in 0|1) ;; *) return "$stage_rc" ;; esac
		fi
	done

	echo
	echo '=============================== 使用的计算命令 ==============================='
	echo " 1) ${scf_command}"
	echo " 2) ${x_command}"
	echo " 3) ${y_command}"
	echo " 4) ${z_command}"
	echo '================================================================================'
	echo
	echo '=============================== 计算总结报告 ================================='
	qe_print_status_line 'scf 是否计算成功' "$scf_status"
	qe_print_status_line 'x 方向极化是否计算成功' "$x_status"
	qe_print_status_line 'y 方向极化是否计算成功' "$y_status"
	qe_print_status_line 'z 方向极化是否计算成功' "$z_status"
	echo '================================================================================'
	echo
	echo '=============================== 极化结果摘录 ================================='
	echo ' x 方向：'
	qe_print_polarization_summary Polar/polar-x.out
	echo ' y 方向：'
	qe_print_polarization_summary Polar/polar-y.out
	echo ' z 方向：'
	qe_print_polarization_summary Polar/polar-z.out
	qe_write_polarization_data
	echo '================================================================================'
	if [ "$scf_status" == "failed" ] || [ "$x_status" == "failed" ] || [ "$y_status" == "failed" ] || [ "$z_status" == "failed" ]; then
		return 1
	fi
	return 0
}
 
