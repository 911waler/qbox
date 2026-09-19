#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function hpin (){
#print how to calculate hubbard U parameters
echo ' 提示：'
echo ' * 非磁性体系：'
echo '  步骤 1：在 pw.x 输入文件中开启 Hubbard U，并为对应元素设置一个非零 U 值，例如 1.D-8。'
echo '  步骤 2：使用 hp.x 计算 U 值。'
echo 
echo ' * 反铁磁/磁性绝缘体：'
echo '   步骤 1：在 pw.x 输入文件中开启 Hubbard U，并为对应元素设置非零 U 值，例如 1.D-8，同时设置磁矩。'
echo '   步骤 2：复制上一步输入文件，做以下修改后再次运行：'
echo '   * 将 occupations 改为 fixed'
echo '   * 设置 tot_magnetization 和 nbnd，这些值可从上一次 pw.x 输出文件中获取'
echo "   * 在 &ELECTRON 段加入 startingpot='file', startingwfc='file'"
echo '   步骤 3：使用 hp.x 计算 U 值。'
echo 
echo " * 如果要计算两种元素的 U，先运行 hp.element1.in，再运行 hp.element2.in，最后运行 hp.tot.in。"
echo 
echo ' * 计算 DFT+U+V 时，hp.x 输入文件格式与 DFT+U 相同。'
echo '   运行命令示例：mpirun -np 16 hp.x -i hp.in > hp.out'
echo 
 
PS3=''
hpin_array=("只计算一种元素的 U" "计算两种元素的 U" "返回")
select ihpin in "${hpin_array[@]}"; do
	case $ihpin in 
		"只计算一种元素的 U")
			: > hp.in
			echo '&INPUTHP' >> hp.in
			echo "   prefix          = '"${prefix}"'" >> hp.in
			echo "   outdir          = './tmp'" >> hp.in
			echo "   iverbosity      = 2" >> hp.in
			echo "   nq1             = 2" >> hp.in
			echo "   nq2             = 2" >> hp.in
			echo "   nq3             = 2" >> hp.in
			echo "   conv_thr_chi    = 1.0d-5" >> hp.in
			echo '/' >> hp.in
			break
			;;
		"计算两种元素的 U")
			: > hp.element1.in
			: > hp.element2.in
			: > hp.tot.in
			echo '&INPUTHP' >> hp.element1.in
			echo "   prefix          = '"${prefix}"'" >> hp.element1.in
			echo "   outdir          = './tmp'" >> hp.element1.in
			echo "   iverbosity      = 2" >> hp.element1.in
			echo "   nq1             = 2" >> hp.element1.in
			echo "   nq2             = 2" >> hp.element1.in
			echo "   nq3             = 2" >> hp.element1.in
			echo "   conv_thr_chi    = 1.0d-5" >> hp.element1.in
			echo "   perturb_only_atom(1) = .true." >> hp.element1.in
			echo '/' >> hp.element1.in
			
			echo '&INPUTHP' >> hp.element2.in
			echo "   prefix          = '"${prefix}"'" >> hp.element2.in
			echo "   outdir          = './tmp'" >> hp.element2.in
			echo "   iverbosity      = 2" >> hp.element2.in
			echo "   nq1             = 2" >> hp.element2.in
			echo "   nq2             = 2" >> hp.element2.in
			echo "   nq3             = 2" >> hp.element2.in
			echo "   conv_thr_chi    = 1.0d-5" >> hp.element2.in
			echo "   perturb_only_atom(2) = .true." >> hp.element2.in
			echo '/' >> hp.element2.in
			
			echo '&INPUTHP' >> hp.tot.in
			echo "   prefix          = '"${prefix}"'" >> hp.tot.in
			echo "   outdir          = './tmp'" >> hp.tot.in
			echo "   iverbosity      = 2" >> hp.tot.in
			echo "   nq1             = 2" >> hp.tot.in
			echo "   nq2             = 2" >> hp.tot.in
			echo "   nq3             = 2" >> hp.tot.in
			echo "   conv_thr_chi    = 1.0d-5" >> hp.tot.in
			echo "   compute_hp      = .true." >> hp.tot.in
			echo '/' >> hp.tot.in
			break
			;;
		"返回")
			qe_request_main_menu
			return 0
			;;
		"*")
			;;
	esac
done
}
 
 
 
 





#--------------------------------- epsilon.x module----------------------------------------
function epsilonin (){
	local choice value calc_prefix outdir smeartype intersmear intrasmear wmin wmax nbndmin nbndmax nw shift
	if [ -n "$prefix" ] && [ "$prefix" != "$fname1" ]; then
		calc_prefix="$prefix"
	elif [ -n "$fname1" ] && [ -f "$fname1" ]; then
		calc_prefix="${fname1##*/}"
		calc_prefix="${calc_prefix%.*}"
	else
		calc_prefix="prefix"
	fi
	outdir="./tmp"
	smeartype="gauss"
	intersmear="0.50"
	intrasmear="0.0"
	wmin="0.0"
	wmax="60.0"
	nbndmin="1"
	nbndmax="0"
	nw="2000"
	shift="0.0"

	while true; do
		echo
		echo '=========================== epsilon.x 输入文件设置 ==========================='
		echo ' 0) 生成 epsilon.in'
		echo " 1) 计算文件前缀：${calc_prefix}"
		echo " 2) outdir：${outdir}"
		echo " 3) 展宽函数 smeartype：${smeartype}"
		echo " 4) 带间跃迁展宽 intersmear：${intersmear} eV"
		echo " 5) 带内展宽 intrasmear：${intrasmear} eV"
		echo " 6) 能量范围：${wmin} 到 ${wmax} eV"
		echo " 7) 能量网格点数 nw：${nw}"
		echo " 8) 能带范围：nbndmin=${nbndmin}, nbndmax=${nbndmax}"
		echo " 9) 虚部刚性平移 shift：${shift} eV"
		echo ' 10) 返回'
		echo '========================================================================'
		echo ' 请输入要修改/执行的编号。'
		read choice
		case "$choice" in
			"0")
				{
					echo '&inputpp'
					echo "    calculation = 'eps',"
					echo "    prefix      = '${calc_prefix}',"
					echo "    outdir      = '${outdir}',"
					echo '/'
					echo '&energy_grid'
					echo "    smeartype  = '${smeartype}'"
					echo "    intersmear = ${intersmear}"
					echo "    intrasmear = ${intrasmear}"
					echo "    wmin       = ${wmin}"
					echo "    wmax       = ${wmax}"
					echo "    nbndmin    = ${nbndmin}"
					echo "    nbndmax    = ${nbndmax}"
					echo "    nw         = ${nw}"
					echo "    shift      = ${shift}"
					echo '/'
				} > epsilon.in
				echo
				echo ' 已生成 epsilon.in。'
				echo ' 参考计算命令：mpirun -np N epsilon.x -in epsilon.in 2>&1 | tee epsilon.out'
				return 0
				;;
			"1")
				echo " 请输入计算文件前缀。直接回车使用：${calc_prefix}"
				read value
				[ -n "$value" ] && calc_prefix="$value"
				;;
			"2")
				echo " 请输入 outdir。直接回车使用：${outdir}"
				read value
				[ -n "$value" ] && outdir="$value"
				;;
			"3")
				echo ' 请选择 smeartype：1) gauss  2) lorentz'
				read value
				case "$value" in
					2|lorentz|Lorentz) smeartype="lorentz" ;;
					*) smeartype="gauss" ;;
				esac
				;;
			"4")
				echo ' intersmear 控制带间跃迁展宽；越大谱越平滑但细节更少。常用 0.10-0.50 eV。'
				echo " 请输入 intersmear，单位 eV。直接回车使用：${intersmear}"
				read value
				if echo "$value" | awk '$1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 >= 0 {exit 0} {exit 1}'; then intersmear="$value"; fi
				;;
			"5")
				echo ' intrasmear 是带内展宽；半导体/绝缘体通常设 0.0，金属体系才需要考虑非零值。'
				echo " 请输入 intrasmear，单位 eV。直接回车使用：${intrasmear}"
				read value
				if echo "$value" | awk '$1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 >= 0 {exit 0} {exit 1}'; then intrasmear="$value"; fi
				;;
			"6")
				echo " 请输入 wmin wmax，单位 eV。直接回车使用：${wmin} ${wmax}"
				read value
				if echo "$value" | awk 'NF==2 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $2 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $2>$1 {exit 0} {exit 1}'; then
					wmin=`echo "$value" | awk '{print $1}'`
					wmax=`echo "$value" | awk '{print $2}'`
				fi
				;;
			"7")
				echo ' nw 是能量网格点数；越大输出分辨率越高。常用 1000-3000。'
				echo " 请输入 nw。直接回车使用：${nw}"
				read value
				if echo "$value" | awk '$1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then nw="$value"; fi
				;;
			"8")
				echo ' nbndmax=0 表示不限制上限；吸收谱通常需要 NSCF 中设置足够大的 nbnd。'
				echo " 请输入 nbndmin nbndmax。直接回车使用：${nbndmin} ${nbndmax}"
				read value
				if echo "$value" | awk 'NF==2 && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ {exit 0} {exit 1}'; then
					nbndmin=`echo "$value" | awk '{print $1}'`
					nbndmax=`echo "$value" | awk '{print $2}'`
				fi
				;;
			"9")
				echo " 请输入 shift，单位 eV。直接回车使用：${shift}"
				read value
				if echo "$value" | awk '$1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ {exit 0} {exit 1}'; then shift="$value"; fi
				;;
			"10")
				return 0
				;;
			*)
				echo ' 请输入有效编号。'
				;;
		esac
	done
}

#--------------------------------- Dos.x module----------------------------------------
function qe_write_dos_input (){
	local mode="$1"
	echo ' &DOS' >> dos.in
	echo "   prefix          = '"${prefix}"'" >> dos.in
	echo "   outdir          = './tmp'" >> dos.in
	if [ "$mode" == "tetrahedra" ]; then
		echo "   bz_sum          = 'tetrahedra'" >> dos.in
	else
		echo "   bz_sum          = 'smearing'" >> dos.in
		echo "   ngauss          = 0" >> dos.in
		echo "   degauss         = 0.01" >> dos.in
	fi
	echo "   DeltaE          = 0.01" >> dos.in
	echo "   Emin            = ${dos_default_emin}" >> dos.in
	echo "   Emax            = ${dos_default_emax}" >> dos.in
	echo "   fildos          = '"${prefix}".dos'   " >> dos.in
	echo ' /' >> dos.in
}

function dosin (){
local dos_default_emin dos_default_emax dos_fermi_energy
read dos_default_emin dos_default_emax <<< `qe_default_dos_energy_window`
dos_fermi_energy=`qe_read_fermi_energy_from_outputs`
 
echo ' 提示：'
echo " * 非金属/有带隙掺杂体系建议使用 tetrahedra 方法得到更清晰的 DOS，相关数据应由 pw.x 使用 occupations='tetrahedra' 生成。"
echo " * tetrahedra 方法需要更密的 K 点。注意 QE 中 'k1 k2 k3 0 0 0' 的 Monkhorst-Pack 网格总是经过 Gamma 点。"
echo " * 金属/费米面穿过能带的掺杂体系将使用 smearing 展宽方法。"
echo ' * 运行命令示例：mpirun -np 6 dos.x -i dos.in > dos.out'
if echo "$dos_fermi_energy" | awk '$1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ {exit 0} {exit 1}'; then
	echo " * 已读取 Fermi level：${dos_fermi_energy} eV，默认 DOS 能量范围：${dos_default_emin} 到 ${dos_default_emax} eV。"
else
	echo " * 未读取到 Fermi level，默认 DOS 能量范围：${dos_default_emin} 到 ${dos_default_emax} eV。"
fi
echo
PS3=''
dosin_array=("非金属/有带隙掺杂体系" "金属/费米面穿过能带掺杂体系" "返回")
select idosin in "${dosin_array[@]}"; do 
	case $idosin in 
		"非金属/有带隙掺杂体系")
			qe_write_dos_input "tetrahedra"
			break
			;;
		"金属/费米面穿过能带掺杂体系")
			qe_write_dos_input "smearing"
			break
			;;
		"返回")
			qe_request_main_menu
			return 0
			;;
		"*")
			;;
	esac
done
}
 
#--------------------------------- Projwfc.x module----------------------------------------
function qe_ldos_det_choices (){
	local n
	n="$1"
	awk -v n="$n" '
		BEGIN{
			count=0
			for(i=3;i<=n;i++){
				if(n%i==0){
					print i
					count++
					if(count==3) exit
				}
			}
			if(count==0){
				for(i=1;i<=n;i++){
					if(n%i==0){
						print i
						count++
						if(count==3) exit
					}
				}
			}
		}
	'
}

function qe_ldos_generate_boxes (){
	local axis x y z det
	axis="$1"
	x="$2"
	y="$3"
	z="$4"
	det="$5"
	awk -v axis="$axis" -v x="$x" -v y="$y" -v z="$z" -v det="$det" '
		BEGIN{
			naxis=(axis=="x"?x:(axis=="y"?y:z))
			boxes=naxis/det
			for(i=1;i<=boxes;i++){
				xmin=1; xmax=x
				ymin=1; ymax=y
				zmin=1; zmax=z
				if(axis=="x"){xmin=1+det*(i-1); xmax=det*i}
				if(axis=="y"){ymin=1+det*(i-1); ymax=det*i}
				if(axis=="z"){zmin=1+det*(i-1); zmax=det*i}
				printf "   irmin(1,%d) = %d, irmax(1,%d) = %d, irmin(2,%d) = %d, irmax(2,%d) = %d, irmin(3,%d) = %d, irmax(3,%d) = %d,\n", i, xmin, i, xmax, i, ymin, i, ymax, i, zmin, i, zmax
			}
		}
	'
}

function qe_ldos_read_reference_info (){
	local reference_out
	reference_out="$1"
	qbox_python -m qbox.io.ldos_reference "$reference_out"
}

function qe_find_ldos_reference_out (){
	local base_dir candidate count
	base_dir="$1"
	if [ -z "$base_dir" ]; then
		base_dir="."
	fi
	if [ -f "${base_dir}/nscf.out" ]; then
		echo "${base_dir}/nscf.out"
		return 0
	fi
	count=0
	for candidate in "${base_dir}"/*nscf.out; do
		if [ -f "$candidate" ]; then
			count=$((count + 1))
			if [ "$count" -eq 1 ]; then
				echo "$candidate"
			fi
		fi
	done
	if [ "$count" -gt 0 ]; then
		return 0
	fi
	if [ -f "${base_dir}/scf.out" ]; then
		echo "${base_dir}/scf.out"
		return 0
	fi
	count=0
	for candidate in "${base_dir}"/*scf.out; do
		if [ -f "$candidate" ]; then
			count=$((count + 1))
			if [ "$count" -eq 1 ]; then
				echo "$candidate"
			fi
		fi
	done
	if [ "$count" -gt 0 ]; then
		return 0
	fi
	return 1
}

function qe_generate_ldos_input (){
	local gen_mode gen_dir scf_out outdir calc_prefix info_prefix fermi_energy xgrid ygrid zgrid
	local axis axis_grid det_choices det_choice1 det_choice2 det_choice3 det width emin emax delta_label deltae
	local choice value output_file info_file box_count calc_command reference_out run_note reference_search_dir display_reference_path plotboxes broadening_warning

	if [ "`basename "$PWD"`" == "LDOS" ]; then
		gen_mode="current"
	else
		gen_mode="ldosdir"
	fi
	axis="z"
	width="5"
	delta_label="精细"
	deltae="0.01"
	plotboxes=".true."

	while true; do
		if [ "$gen_mode" == "ldosdir" ]; then
			gen_dir="LDOS"
			reference_search_dir="."
			outdir="../tmp"
			run_note="计算时在 LDOS/ 内运行"
		else
			gen_dir="."
			if [ "`basename "$PWD"`" == "LDOS" ]; then
				reference_search_dir=".."
				outdir="../tmp"
				run_note="计算时在当前 LDOS 目录内运行"
			else
				reference_search_dir="."
				outdir="./tmp"
				run_note="计算时在当前目录运行"
			fi
		fi

		reference_out=`qe_find_ldos_reference_out "$reference_search_dir"`
		if [ -z "$reference_out" ]; then
			if [ "$reference_search_dir" == "." ]; then
				display_reference_path="nscf.out、*nscf.out、scf.out 或 *scf.out"
			else
				display_reference_path="${reference_search_dir}/nscf.out、${reference_search_dir}/*nscf.out、${reference_search_dir}/scf.out 或 ${reference_search_dir}/*scf.out"
			fi
		else
			display_reference_path="$reference_out"
		fi

		if [ -n "$reference_out" ] && [ -f "$reference_out" ]; then
			read info_prefix fermi_energy xgrid ygrid zgrid <<< `qe_ldos_read_reference_info "$reference_out"`
			if grep -qi "Gaussian smearing, width (Ry)=" "$reference_out"; then
				broadening_warning="yes"
			else
				broadening_warning="no"
			fi
		else
			info_prefix=""
			fermi_energy=""
			xgrid=""
			ygrid=""
			zgrid=""
			broadening_warning="no"
		fi

		if [ -z "$calc_prefix" ]; then
			if [ -n "$fname1" ] && [ -f "$fname1" ]; then
				calc_prefix="${fname1##*/}"
				calc_prefix="${calc_prefix%.*}"
			elif [ -n "$prefix" ] && [ "$prefix" != "$fname1" ]; then
				calc_prefix="$prefix"
			elif [ -n "$info_prefix" ]; then
				calc_prefix="$info_prefix"
			fi
		fi
		if [ -z "$calc_prefix" ] && [ -n "$info_prefix" ]; then
			calc_prefix="$info_prefix"
		fi

		case "$axis" in
			x) axis_grid="$xgrid" ;;
			y) axis_grid="$ygrid" ;;
			*) axis_grid="$zgrid" ;;
		esac
		if echo "$axis_grid" | awk '$1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
			read det_choice1 det_choice2 det_choice3 <<< `qe_ldos_det_choices "$axis_grid" | tr '\n' ' '`
			if [ -z "$det" ]; then
				det="$det_choice1"
			fi
			if ! echo "$det" | awk -v n="$axis_grid" '$1 ~ /^[0-9]+$/ && $1 > 0 && n % $1 == 0 {exit 0} {exit 1}'; then
				det="$det_choice1"
			fi
			box_count=$((axis_grid / det))
		else
			det_choice1=""
			det_choice2=""
			det_choice3=""
			box_count=""
		fi

		if echo "$fermi_energy" | awk '$1 ~ /^[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/ {exit 0} {exit 1}'; then
			emin=`awk -v f="$fermi_energy" -v w="$width" 'BEGIN{printf "%.8f", f-w}'`
			emax=`awk -v f="$fermi_energy" -v w="$width" 'BEGIN{printf "%.8f", f+w}'`
		else
			emin=""
			emax=""
		fi

		echo
		echo '=========================== LDOS 输入文件设置 ==========================='
		echo " 0) 生成 ldos.in"
		echo " 1) 生成位置：$([ "$gen_mode" == "ldosdir" ] && echo "LDOS/ldos.in" || echo "./ldos.in")"
		echo " 2) 计算文件前缀：${calc_prefix:-未设置}"
		echo " 3) outdir：${outdir}"
		echo " 4) LDOS 分层方向：${axis}"
		echo " 5) det：${det:-未设置}"
		echo " 6) 能量范围：Fermi ± ${width} eV"
		echo " 7) DeltaE：${delta_label} (${deltae} eV)"
		echo " 8) 输出 box 可视化文件：$([ "$plotboxes" == ".true." ] && echo "是" || echo "否")"
		echo ' 9) 返回'
		echo '========================================================================'
		if echo "$QE_LDOS_AUTO_GENERATE_TIMEOUT" | awk '$1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
			echo " 请输入要修改/执行的编号。${QE_LDOS_AUTO_GENERATE_TIMEOUT} 秒内无输入将使用当前默认设置生成 ldos.in。"
			if read -t "$QE_LDOS_AUTO_GENERATE_TIMEOUT" choice; then
				:
			else
				echo
				echo " 未检测到输入，使用当前默认设置生成 ldos.in。"
				choice="0"
			fi
			QE_LDOS_AUTO_GENERATE_TIMEOUT=""
		else
			echo ' 请输入要修改/执行的编号。'
			read choice
		fi
		case "$choice" in
			"0")
				if [ -z "$calc_prefix" ]; then
					echo ' 错误：计算文件前缀未设置。'
					continue
				fi
				if [ -z "$reference_out" ] || [ ! -f "$reference_out" ]; then
					echo " 错误：未找到 nscf.out、*nscf.out、scf.out 或 *scf.out。"
					continue
				fi
				if [ -z "$xgrid" ] || [ -z "$fermi_energy" ]; then
					echo " 错误：未能从 ${reference_out} 读取 FFT 网格或 Fermi level。"
					continue
				fi
				if [ -z "$det" ]; then
					echo ' 错误：det 未设置。'
					continue
				fi
				mkdir -p "$gen_dir"
				output_file="${gen_dir}/ldos.in"
				info_file="${gen_dir}/info_ldos"
				grep -E "Dense|Fermi|FFT dimensions|highest occupied|lowest unoccupied|Gaussian smearing|tetrahedra|\\.save" "$reference_out" > "$info_file"
				{
					echo '&PROJWFC'
					echo "   prefix        = '${calc_prefix}',"
					echo "   outdir        = '${outdir}',"
					echo "   ngauss        = 0,"
					echo "   degauss       = 0.003,"
					echo "   Emin          = ${emin},"
					echo "   Emax          = ${emax},"
					echo "   DeltaE        = ${deltae},"
					echo "   lsym          = .true.,"
					echo "   filpdos       = '${calc_prefix}.pdos',"
					echo "   filproj       = '${calc_prefix}.proj',"
					echo "   tdosinboxes   = .true.,"
					echo "   n_proj_boxes  = ${box_count},"
					if [ "$plotboxes" == ".true." ]; then
						echo "   plotboxes     = .true.,"
					fi
					qe_ldos_generate_boxes "$axis" "$xgrid" "$ygrid" "$zgrid" "$det"
					echo ' /'
				} > "$output_file"
				echo
				echo " 已生成：${output_file}"
				echo " 已生成：${info_file}"
				if [ "$broadening_warning" == "yes" ]; then
					echo ' 警告：参考输出显示使用 Gaussian smearing。半导体/绝缘体 LDOS 可能出现带隙拖尾；建议重新计算 tetrahedra NSCF 后再运行 projwfc.x。'
				fi
				if [ "$gen_dir" == "." ]; then
					calc_command="mpirun -np N projwfc.x -in ldos.in 2>&1 | tee ldos.out"
				else
					calc_command="cd LDOS && mpirun -np N projwfc.x -in ldos.in 2>&1 | tee ldos.out"
				fi
				echo " 参考计算命令：${calc_command}"
				return 0
				;;
			"1")
				echo
				echo ' 当前设置：'
				if [ "$gen_mode" == "ldosdir" ]; then
					echo " 生成位置：LDOS/ldos.in"
					echo " ${run_note}"
					echo " ldos.in 中 outdir 将使用：${outdir}"
				else
					echo " 生成位置：当前目录 ./ldos.in"
					echo " ${run_note}"
					echo " ldos.in 中 outdir 将使用：${outdir}"
				fi
				echo ' 按回车切换生成位置。'
				read value
				if [ "$gen_mode" == "ldosdir" ]; then
					gen_mode="current"
				else
					gen_mode="ldosdir"
				fi
				det=""
				;;
			"2")
				echo
				echo " 请输入计算文件前缀。直接回车使用：${calc_prefix:-${info_prefix}}"
				read value
				if [ -n "$value" ]; then
					calc_prefix="$value"
				elif [ -z "$calc_prefix" ] && [ -n "$info_prefix" ]; then
					calc_prefix="$info_prefix"
				fi
				;;
			"3")
				echo
				echo " 当前 outdir：${outdir}"
				echo ' outdir 会根据生成位置自动设置：'
				echo '  - 在 LDOS/ 内运行时使用 ../tmp'
				echo '  - 在当前主目录运行时使用 ./tmp'
				echo ' 如需修改，请先通过 1) 生成位置 切换运行目录。'
				;;
			"4")
				echo
				if [ -n "$xgrid" ]; then
					echo " 已读取 FFT 网格：X=${xgrid}, Y=${ygrid}, Z=${zgrid}"
				else
					echo ' 未读取到 FFT 网格，请确认已存在 nscf.out、*nscf.out、scf.out 或 *scf.out。'
				fi
				echo " 当前参考输出：${display_reference_path}"
				echo ' 请选择 LDOS 分层方向：1) x  2) y  3) z'
				read value
				case "$value" in
					1|x|X) axis="x" ;;
					2|y|Y) axis="y" ;;
					3|z|Z|"") axis="z" ;;
					*) echo ' 无效方向，保持原设置。' ;;
				esac
				det=""
				;;
			"5")
				echo
				if [ -z "$det_choice1" ]; then
					echo ' 未读取到 FFT 网格，无法设置 det。'
				else
					echo " 当前分层方向：${axis}"
					echo " 当前方向 FFT 网格点数：${axis_grid}"
					echo " 当前 det：${det}，box 数：${box_count}"
					echo " 请选择 det：1) ${det_choice1}${det_choice2:+  2) ${det_choice2}}${det_choice3:+  3) ${det_choice3}}"
					if ! read -r value; then return 1; fi
					case "$value" in
						1|"") det="$det_choice1" ;;
						2) [ -n "$det_choice2" ] && det="$det_choice2" ;;
						3) [ -n "$det_choice3" ] && det="$det_choice3" ;;
						*) echo ' 无效 det 选项，保持原设置。' ;;
					esac
				fi
				;;
			"6")
				echo
				if [ -n "$fermi_energy" ]; then
					echo " 已读取 Fermi level：${fermi_energy} eV"
					echo " 当前能量范围：${emin} 到 ${emax} eV"
					echo " 当前参考输出：${display_reference_path}"
					if [ "$broadening_warning" == "yes" ]; then
						echo ' 警告：该参考输出使用 Gaussian smearing。若体系应有带隙，建议改用 tetrahedra NSCF 后重新生成。'
					fi
				else
					echo ' 未读取到 Fermi level，请确认 nscf.out、*nscf.out、scf.out 或 *scf.out 中包含 Fermi 信息。'
				fi
				echo " 请输入 Fermi 两侧能量宽度，单位 eV。直接回车使用：${width}"
				read value
				if echo "$value" | awk '$1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
					width="$value"
				elif [ -n "$value" ]; then
					echo ' 无效宽度，保持原设置。'
				fi
				;;
			"7")
				echo
				echo ' DeltaE 控制能量网格间隔；间隔越小，曲线越细、文件越大、projwfc.x 输出越慢。'
				echo ' 请选择 DeltaE：'
				echo '  1) 粗糙 0.02 eV，适合快速预览'
				echo '  2) 中等 0.01 eV，平衡文件大小和分辨率'
				echo '  3) 精细 0.005 eV，默认，适合最终出图或细节检查'
				read value
				case "$value" in
					1) delta_label="粗糙"; deltae="0.02" ;;
					2) delta_label="中等"; deltae="0.01" ;;
					3|"") delta_label="精细"; deltae="0.005" ;;
					*) echo ' 无效选项，保持原设置。' ;;
				esac
				;;
			"8")
				echo
				echo ' 开启后，projwfc.x 会把每个 LDOS box 写成 XSF 3D datagrid 文件：'
				echo '  - box 内部网格点的值为 1.0'
				echo '  - box 外部网格点的值为 0.0'
				echo '  - 可以用 VESTA、XCrySDen 等软件打开，用 0.5 等值面检查 box 是否覆盖了预期空间区域'
				echo " 当前设置：$([ "$plotboxes" == ".true." ] && echo "开启" || echo "关闭")"
				echo ' 按回车切换是否输出 box 可视化文件。'
				read value
				if [ "$plotboxes" == ".true." ]; then
					plotboxes=".false."
				else
					plotboxes=".true."
				fi
				;;
			"9")
				return 0
				;;
			*)
				echo ' 请输入有效编号。'
				;;
		esac
	done
}

function qe_generate_pdos_input (){
local pdos_default_emin pdos_default_emax pdos_fermi_energy
read pdos_default_emin pdos_default_emax <<< `qe_default_dos_energy_window`
pdos_fermi_energy=`qe_read_fermi_energy_from_outputs`
 
echo ' 提示：'
echo " * 非金属/有带隙掺杂体系建议使用 tetrahedra 方法得到更清晰的 PDOS，相关数据应由 pw.x 使用 occupations='tetrahedra' 生成。"
echo " * tetrahedra 方法需要更密的 K 点。注意 QE 中 'k1 k2 k3 0 0 0' 的 Monkhorst-Pack 网格总是经过 Gamma 点。"
echo " * 金属/费米面穿过能带的掺杂体系将使用 smearing 展宽方法。"
echo ' * 运行命令示例：mpirun -np 6 projwfc.x -i pdos.in > projwfc.out'
if echo "$pdos_fermi_energy" | awk '$1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ {exit 0} {exit 1}'; then
	echo " * 已读取 Fermi level：${pdos_fermi_energy} eV，默认 PDOS 能量范围：${pdos_default_emin} 到 ${pdos_default_emax} eV。"
else
	echo " * 未读取到 Fermi level，默认 PDOS 能量范围：${pdos_default_emin} 到 ${pdos_default_emax} eV。"
fi
echo
PS3=''
dosin_array=("非金属/有带隙掺杂体系" "金属/费米面穿过能带掺杂体系" "返回")
select idosin in "${dosin_array[@]}"; do 
	case $idosin in 
		"非金属/有带隙掺杂体系")
			echo '&PROJWFC' >> pdos.in
			echo "   prefix          = '"${prefix}"'" >> pdos.in
			echo "   outdir          = './tmp'" >> pdos.in
			echo "   filpdos         = 'pdos.dat' "	>> pdos.in
			echo "   DeltaE          = 0.01" >> pdos.in
			echo "   Emin            = ${pdos_default_emin}" >> pdos.in
			echo "   Emax            = ${pdos_default_emax}" >> pdos.in
			echo ' /' >> pdos.in
			break
			;;
		"金属/费米面穿过能带掺杂体系")
			echo '&PROJWFC' >> pdos.in
			echo "   prefix          = '"${prefix}"'" >> pdos.in
			echo "   outdir          = './tmp'" >> pdos.in
			echo "	 filpdos		 = 'pdos.dat'"	>>pdos.in		
			echo "   ngauss          = 0" >> pdos.in
			echo "   degauss         = 0.01" >> pdos.in
			echo "   DeltaE          = 0.01" >> pdos.in
			echo "   Emin            = ${pdos_default_emin}" >> pdos.in
			echo "   Emax            = ${pdos_default_emax}" >> pdos.in
			echo ' /' >> pdos.in
			break
			;;
		"返回")
			qe_request_main_menu
			return 0
			;;
		"*")
			;;
	esac
done
}

function projwfcin (){
echo
echo ' 请选择 projwfc.x 输入文件类型：'
echo '  1) PDOS 输入文件'
echo '  2) LDOS 输入文件'
echo '  3) 返回'
read projwfc_input_type
while [ "$projwfc_input_type" != "1" ] && [ "$projwfc_input_type" != "2" ] && [ "$projwfc_input_type" != "3" ]
do
	echo ' 请输入 1、2 或 3。'
	read projwfc_input_type
done

case "$projwfc_input_type" in
	"1")
		qe_generate_pdos_input
		;;
	"2")
		qe_generate_ldos_input
		;;
	"3")
		qe_request_main_menu
		return 0
		;;
esac
}
 
#--------------------------------- PP.x module----------------------------------------
function ppin (){
echo "  * 1~9 功能会生成 Gaussian-type cube 文件，可继续用 Multiwfn、Vesta、VMD 等程序处理。"
echo "  * 差分电荷密度表示总电荷密度减去原子电荷密度叠加。"
echo '  * 运行命令示例：mpirun -np 6 pp.x -i xxx.pp.in > xxx.pp.out'
echo
PS3=''
ppin_array=("电荷密度" "自旋密度" "ELF" "差分电荷密度" "静电势 ESP" "RDG" "Sign(lambda2)rho" "DORI" "绘制轨道" "STM" "返回")
select ippin in "${ppin_array[@]}"; do
	case $ippin in 
		"电荷密度")
			: > chgden.pp.in
			echo '&INPUTPP' >> chgden.pp.in
			echo "   prefix          = '"${prefix}"'" >> chgden.pp.in
			echo "   outdir          = './tmp'" >> chgden.pp.in
			echo "   filplot         = 'chgden.dat'" >> chgden.pp.in
			echo "   plot_num        = 0" >> chgden.pp.in
			echo ' /' >> chgden.pp.in
			echo '&PLOT' >> chgden.pp.in
			echo "   nfile           = 1" >> chgden.pp.in 
			echo "   filepp(1)       = 'chgden.dat'" >> chgden.pp.in
			echo "   weight(1)       = 1.0" >> chgden.pp.in
			echo "   fileout         = 'chgden.cube'" >> chgden.pp.in
			echo "   iflag           = 3" >> chgden.pp.in
			echo "   output_format   = 6" >> chgden.pp.in
			echo ' /' >> chgden.pp.in
			break
			;;
		"自旋密度")
			: > spinden.pp.in
			echo '&INPUTPP' >> spinden.pp.in
			echo "   prefix          = '"${prefix}"'" >> spinden.pp.in
			echo "   outdir          = './tmp'" >> spinden.pp.in
			echo "   filplot         = 'spinden.dat'" >> spinden.pp.in
			echo "   plot_num        = 6" >> spinden.pp.in
			echo ' /' >> spinden.pp.in
			echo '&PLOT' >> spinden.pp.in
			echo "   nfile           = 1" >> spinden.pp.in 
			echo "   filepp(1)       = 'spinden.dat'" >> spinden.pp.in
			echo "   weight(1)       = 1.0" >> spinden.pp.in
			echo "   fileout         = 'spinden.cube'" >> spinden.pp.in
			echo "   iflag           = 3" >> spinden.pp.in
			echo "   output_format   = 6" >> spinden.pp.in
			echo ' /' >> spinden.pp.in
			break
			;;
		"ELF")
			: > elf.pp.in
			echo '&INPUTPP' >> elf.pp.in
			echo "   prefix          = '"${prefix}"'" >> elf.pp.in
			echo "   outdir          = './tmp'" >> elf.pp.in
			echo "   filplot         = 'elf.dat'" >> elf.pp.in
			echo "   plot_num        = 8" >> elf.pp.in
			echo ' /' >> elf.pp.in
			echo '&PLOT' >> elf.pp.in
			echo "   nfile           = 1" >> elf.pp.in 
			echo "   filepp(1)       = 'elf.dat'" >> elf.pp.in
			echo "   weight(1)       = 1.0" >> elf.pp.in
			echo "   fileout         = 'elf.cube'" >> elf.pp.in
			echo "   iflag           = 3" >> elf.pp.in
			echo "   output_format   = 6" >> elf.pp.in
			echo ' /' >> elf.pp.in
			break
			;;
		"差分电荷密度")
			: > defden.pp.in
			echo '&INPUTPP' >> defden.pp.in
			echo "   prefix          = '"${prefix}"'" >> defden.pp.in
			echo "   outdir          = './tmp'" >> defden.pp.in
			echo "   filplot         = 'defden.dat'" >> defden.pp.in
			echo "   plot_num        = 9" >> defden.pp.in
			echo ' /' >> defden.pp.in
			echo '&PLOT' >> defden.pp.in
			echo "   nfile           = 1" >> defden.pp.in 
			echo "   filepp(1)       = 'defden.dat'" >> defden.pp.in
			echo "   weight(1)       = 1.0" >> defden.pp.in
			echo "   fileout         = 'defden.cube'" >> defden.pp.in
			echo "   iflag           = 3" >> defden.pp.in
			echo "   output_format   = 6" >> defden.pp.in
			echo ' /' >> defden.pp.in
			break
			;;
 
		#静电势计算
		"静电势 ESP")		
			: > esp.pp.in
			echo '&INPUTPP' >> esp.pp.in
			echo "   prefix          = '"${prefix}"'" >> esp.pp.in
			echo "   outdir          = './tmp'" >> esp.pp.in
			echo "   filplot         = 'pp11.dat'" >> esp.pp.in
			echo "   plot_num        = 11" >> esp.pp.in
			echo ' /' >> esp.pp.in
			echo '&PLOT' >> esp.pp.in
			echo "   nfile           = 1" >> esp.pp.in 
			echo "   filepp(1)       = 'pp11.dat'" >> esp.pp.in
			echo "   weight(1)       = 1.0" >> esp.pp.in
			echo "   fileout         = 'esp.cube'" >> esp.pp.in
			echo "   iflag           = 3" >> esp.pp.in
			echo "   output_format   = 6" >> esp.pp.in
			echo ' /' >> esp.pp.in
			break
			;;
		"RDG")
			: > rdg.pp.in
			echo '&INPUTPP' >> rdg.pp.in
			echo "   prefix          = '"${prefix}"'" >> rdg.pp.in
			echo "   outdir          = './tmp'" >> rdg.pp.in
			echo "   filplot         = 'rdg.dat'" >> rdg.pp.in
			echo "   plot_num        = 19" >> rdg.pp.in
			echo ' /' >> rdg.pp.in
			echo '&PLOT' >> rdg.pp.in
			echo "   nfile           = 1" >> rdg.pp.in 
			echo "   filepp(1)       = 'rdg.dat'" >> rdg.pp.in
			echo "   weight(1)       = 1.0" >> rdg.pp.in
			echo "   fileout         = 'rdg.cube'" >> rdg.pp.in
			echo "   iflag           = 3" >> rdg.pp.in
			echo "   output_format   = 6" >> rdg.pp.in
			echo ' /' >> rdg.pp.in
			break
			;;
		"Sign(lambda2)rho")
			: > sign_lambda2_rho.pp.in
			echo '&INPUTPP' >> sign_lambda2_rho.pp.in
			echo "   prefix          = '"${prefix}"'" >> sign_lambda2_rho.pp.in
			echo "   outdir          = './tmp'" >> sign_lambda2_rho.pp.in
			echo "   filplot         = 'sign_lambda2_rho.dat'" >> sign_lambda2_rho.pp.in
			echo "   plot_num        = 20" >> sign_lambda2_rho.pp.in
			echo ' /' >> sign_lambda2_rho.pp.in
			echo '&PLOT' >> sign_lambda2_rho.pp.in
			echo "   nfile           = 1" >> sign_lambda2_rho.pp.in 
			echo "   filepp(1)       = 'sign_lambda2_rho.dat'" >> sign_lambda2_rho.pp.in
			echo "   weight(1)       = 1.0" >> sign_lambda2_rho.pp.in
			echo "   fileout         = 'sign_lambda2_rho.cube'" >> sign_lambda2_rho.pp.in
			echo "   iflag           = 3" >> sign_lambda2_rho.pp.in
			echo "   output_format   = 6" >> sign_lambda2_rho.pp.in
			echo ' /' >> sign_lambda2_rho.pp.in
			break
			;;
		"DORI")
			: > dori.pp.in
			echo '&INPUTPP' >> dori.pp.in
			echo "   prefix          = '"${prefix}"'" >> dori.pp.in
			echo "   outdir          = './tmp'" >> dori.pp.in
			echo "   filplot         = 'dori.dat'" >> dori.pp.in
			echo "   plot_num        = 123" >> dori.pp.in
			echo ' /' >> dori.pp.in
			echo '&PLOT' >> dori.pp.in
			echo "   nfile           = 1" >> dori.pp.in 
			echo "   filepp(1)       = 'dori.dat'" >> dori.pp.in
			echo "   weight(1)       = 1.0" >> dori.pp.in
			echo "   fileout         = 'dori.cube'" >> dori.pp.in
			echo "   iflag           = 3" >> dori.pp.in
			echo "   output_format   = 6" >> dori.pp.in
			echo ' /' >> dori.pp.in
			break
			;;
		"绘制轨道")
			: > orb.pp.in
			echo '&INPUTPP' >> orb.pp.in
			echo "   prefix          = '"${prefix}"'" >> orb.pp.in
			echo "   outdir          = './tmp'" >> orb.pp.in
			echo "   filplot         = 'orb.dat'" >> orb.pp.in
			echo "   plot_num        = 7" >> orb.pp.in
			echo "   kpoint(1)       = 1" >> orb.pp.in
			echo "   kpoint(2)       = 1" >> orb.pp.in
			echo "   kband(1)        = 1" >> orb.pp.in
			echo "   kband(2)        = 16" >> orb.pp.in
			echo "   lsign           = .true." >> orb.pp.in
			echo ' /' >> orb.pp.in
			echo '&PLOT' >> orb.pp.in
			echo "   nfile           = 1" >> orb.pp.in 
			echo "   filepp(1)       = 'orb.dat'" >> orb.pp.in
			echo "   weight(1)       = 1.0" >> orb.pp.in
			echo "   fileout         = 'orb.cube'" >> orb.pp.in
			echo "   iflag           = 3" >> orb.pp.in
			echo "   output_format   = 6" >> orb.pp.in
			echo ' /' >> orb.pp.in
			break
			;;
		"STM")
			: > stm.pp.in
			echo '&INPUTPP' >> stm.pp.in
			echo "   prefix          = '"${prefix}"'" >> stm.pp.in
			echo "   outdir          = './tmp'" >> stm.pp.in
			echo "   filplot         = 'stm.dat'" >> stm.pp.in
			echo "   plot_num        = 5" >> stm.pp.in
			echo "   sample_bias     = -0.0735" >> stm.pp.in
			echo ' /' >> stm.pp.in
			echo '&PLOT' >> stm.pp.in
			echo "   nfile           = 1" >> stm.pp.in 
			echo "   filepp(1)       = 'stm.dat'" >> stm.pp.in
			echo "   weight(1)       = 1.0" >> stm.pp.in
			echo "   fileout         = 'stm.cube'" >> stm.pp.in
			echo "   iflag           = 2" >> stm.pp.in
			echo "   output_format   = 7" >> stm.pp.in
			echo "   e1(1)           = 7" >> stm.pp.in
			echo "   e1(2)           = 0" >> stm.pp.in
			echo "   e1(3)           = 0" >> stm.pp.in
			echo "   e2(1)           = 0" >> stm.pp.in
			echo "   e2(2)           = 9.9" >> stm.pp.in
			echo "   e2(3)           = 0" >> stm.pp.in
			echo "   x0(1)           = 0" >> stm.pp.in
			echo "   x0(2)           = 1.37" >> stm.pp.in
			echo "   x0(3)           = 3.55" >> stm.pp.in
			echo "   nx              = 400" >> stm.pp.in
			echo "   ny              = 300" >> stm.pp.in
			echo ' /' >> stm.pp.in
			break
			;;
		"返回")
			qe_request_main_menu
			return 0
			;;
		"*")
			;;
	esac
done	
}	
 
#--------------------------------- Bands.x module----------------------------------------
function qe_bandin_menu (){
	echo " 0) 立即生成 bands.x 输入文件"
	echo " 1) 设置 lsym，当前：.${bands_lsym}."
	echo " 2) 返回"
}
function bandin (){
local bands_lsym bands_arg bands_lsym_choice
bands_lsym="${QE_BANDIN_DEFAULT_LSYM:-false}"
case "$bands_lsym" in
	true|false) ;;
	.true.) bands_lsym='true' ;;
	.false.) bands_lsym='false' ;;
	*) bands_lsym='false' ;;
esac


if [ "$QE_BANDIN_COMPACT" != "1" ]; then
	echo " * 运行命令示例：mpirun -np 6 bands.x -i bands.in > bands.out"
	echo " * lsym=.false. 会保持输入 K 路径顺序，适合常规能带绘图和有效质量分析。"
	echo " * lsym=.true. 会让 bands.x 使用小群对称性分析能带。"
	echo
	qe_bandin_menu
	read bands_arg
	while [ "$bands_arg" != "0" ]; do
		case "$bands_arg" in
			1)
				PS3=''
				bands_lsym_array=("保持 lsym=.false.（推荐用于常规能带路径）" "开启 lsym=.true.（对称性分析）")
				select bands_lsym_choice in "${bands_lsym_array[@]}"; do
					case $bands_lsym_choice in
						"保持 lsym=.false."*) bands_lsym='false'; break ;;
						"开启 lsym=.true."*) bands_lsym='true'; break ;;
						"*") ;;
					esac
				done
				;;
			2)
				return 1
				;;
			*)
				echo "请输入有效的功能编号..."
				;;
		esac
		qe_bandin_menu
		read bands_arg
	done
fi

rm -f bands.in
echo "&BANDS" >> bands.in
echo "   prefix          = '"${prefix}"'" >> bands.in
echo "   outdir          = './tmp'" >> bands.in
echo "   filband         = 'bands.dat'" >> bands.in
echo "   lsym            = .${bands_lsym}." >> bands.in
echo ' /' >> bands.in
}
 
 
 
 
 
#--------------------------------- post processing ----------------------------------------
