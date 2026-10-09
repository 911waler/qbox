#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function nebin (){
	local neb_output
 
#run tips
#read the input files.
if [ -z "$fname1" ]; then 
	echo 
	echo ' 请输入 xxx.relax1.in 文件，它将作为生成 neb.x 输入文件的模板。'
	if ! read -r fname1; then return 1; fi
	while [ -z "$fname1" ]; do
        echo
        echo ' 请输入 xxx.relax1.in 文件，它将作为生成 neb.x 输入文件的模板。'
        if ! read -r fname1; then return 1; fi
    done
	qe_set_input_path "$fname1" || return 1
fi

if [ -z "$fname2" ]; then
	echo 
	echo ' 请输入 xxx.relax1.out 文件，其中包含初态优化结构。'
	if ! read -r fname2; then return 1; fi
	while [ -z "$fname2" ]; do
        echo
        echo ' 请输入 xxx.relax1.out 文件，其中包含初态优化结构。'
        if ! read -r fname2; then return 1; fi
    done
fi
if [ -z "$fname3" ]; then
	echo 
	echo ' 请输入 xxx.relax2.out 文件，其中包含末态优化结构。'
	if ! read -r fname3; then return 1; fi
	while [ -z "$fname3" ]; do
        echo
        echo ' 请输入 xxx.relax2.out 文件，其中包含末态优化结构。'
        if ! read -r fname3; then return 1; fi
    done
fi

if [ ! -f "$fname1" ] || [ ! -f "$fname2" ] || [ ! -f "$fname3" ]; then
	echo " 错误：NEB 输入模板、初态输出或末态输出文件不存在。"
	return 1
fi
	qe_validate_calc_prefix "$prefix" || return 1
	neb_output="${prefix}.neb.in.tmp.$$"
 
#delete atomic_positions section
natm=`awk -F= 'tolower($1) ~ /^[[:space:]]*nat[[:space:]]*$/ {gsub(/[ ,]/, "", $2); print $2; exit}' "$fname1"`
begdel=`grep -n 'ATOMIC_POSITIONS' "$fname1" | tail -1 | awk -F : '{print $1}'`
if ! echo "$natm" | grep -Eq '^[1-9][0-9]*$' || [ -z "$begdel" ]; then
	echo " 错误：无法从 '$fname1' 读取 nat 或 ATOMIC_POSITIONS。"
	return 1
fi
enddel=$((${begdel}+${natm}))
cp -- "$fname1" "${prefix}.neb.tmp" || return 1
sed -i "${begdel},${enddel}d" "${prefix}.neb.tmp" || { rm -f -- "${prefix}.neb.tmp"; return 1; }
awk '
	BEGIN{skip_ionic=0}
	/^[[:space:]]*&(IONS|CELL)([[:space:]]|$)/ {skip_ionic=1; next}
	skip_ionic && /^[[:space:]]*\// {skip_ionic=0; next}
	skip_ionic {next}
	tolower($0) ~ /^[[:space:]]*calculation[[:space:]]*=/ {
		print "   calculation     = '\''scf'\''"
		next
	}
	tolower($0) ~ /^[[:space:]]*(nstep|etot_conv_thr|forc_conv_thr)[[:space:]]*=/ {next}
	{print}
' "${prefix}.neb.tmp" > "${prefix}.neb.tmp.clean" && mv "${prefix}.neb.tmp.clean" "${prefix}.neb.tmp"
 
#get initial and finial atomic positions 
begatmpos1=`grep -n 'ATOMIC_POSITIONS' ${fname2} |tail -1|awk -F : '{print $1 + 1}'`
endatmpos1=`grep -n 'End final coordinates' ${fname2} |tail -1|awk -F : '{print $1 - 1}'`
begatmpos2=`grep -n 'ATOMIC_POSITIONS' ${fname3} |tail -1|awk -F : '{print $1 + 1}'`
endatmpos2=`grep -n 'End final coordinates' ${fname3} |tail -1|awk -F : '{print $1 - 1}'`
if [ -z "$begatmpos1" ] || [ -z "$endatmpos1" ] || [ -z "$begatmpos2" ] || [ -z "$endatmpos2" ] || \
	[ "$endatmpos1" -lt "$begatmpos1" ] || [ "$endatmpos2" -lt "$begatmpos2" ]; then
	rm -f "${prefix}.neb.tmp"
	echo " 错误：初态或末态输出中未找到完整的最终原子坐标。"
	return 1
fi
 
#generate neb input file
: > "$neb_output" || return 1
echo 'BEGIN' >> "$neb_output"
echo 'BEGIN_PATH_INPUT' >> "$neb_output"
echo '&PATH' >> "$neb_output"
echo "   string_method   = 'neb'" >> "$neb_output"
echo "   restart_mode    = 'from_scratch'" >> "$neb_output"
echo "   num_of_images   = 5" >> "$neb_output"
echo "   nstep_path     = 100" >> "$neb_output"
echo "   opt_scheme      = 'broyden'" >> "$neb_output"
echo "   CI_scheme       = 'auto'" >> "$neb_output"
echo "   path_thr        = 0.05" >> "$neb_output"
echo "   k_max           = 0.3" >> "$neb_output"
echo "   k_min           = 0.2" >> "$neb_output"
echo ' /' >> "$neb_output"
echo "END_PATH_INPUT" >> "$neb_output"
echo "BEGIN_ENGINE_INPUT" >> "$neb_output"
cat -- "${prefix}.neb.tmp" >> "$neb_output"
echo 'BEGIN_POSITIONS' >> "$neb_output"
echo 'FIRST_IMAGE' >> "$neb_output"
echo 'ATOMIC_POSITIONS angstrom' >> "$neb_output"
for i in $(seq ${begatmpos1} ${endatmpos1})
do
	sed -n "${i}p" "$fname2" | awk '{printf "%2s  %.9f  %.9f  %.9f\n",$1,$2,$3,$4}' >> "$neb_output"
done
echo 'LAST_IMAGE' >> "$neb_output"
echo 'ATOMIC_POSITIONS angstrom' >> "$neb_output"
for j in $(seq ${begatmpos2} ${endatmpos2})
do
	sed -n "${j}p" "$fname3" | awk '{printf "%2s  %.9f  %.9f  %.9f\n",$1,$2,$3,$4}' >> "$neb_output"
done
echo 'END_POSITIONS' >> "$neb_output"
echo 'END_ENGINE_INPUT' >> "$neb_output"
echo 'END' >> "$neb_output"
if [ ! -s "$neb_output" ] || ! mv -f -- "$neb_output" "${prefix}.neb.in"; then
	rm -f -- "$neb_output" "${prefix}.neb.tmp"
	echo ' 错误：NEB 输入文件生成失败，未替换原文件。' >&2
	return 1
fi
rm -f -- "${prefix}.neb.tmp"
echo " 已生成 NEB 输入文件：${prefix}.neb.in"
return 0
}
 
#--------------------------------- ph.x module----------------------------------------
#define ph.x menu
function qe_phonon_menu (){
echo " 1) 表面/吸附模型"
echo " 2) 气相分子"
echo " 3) 非极性材料"
echo " 4) 极性材料"
echo " 5) 返回"
}

#-----------Phonon frequency of adsorbed molecule at gamma-----------
function qe_phonon_adsorbed_frequency (){
echo ' 吸附分子 Gamma 点振动输入'
echo 
echo ' 请输入需要参与线性响应计算的原子编号，例如 3,5,10-15'
read atmphon

local atmphon_expanded
atmphon_expanded="$(qe_expand_index_spec "$atmphon")" || return 1
mapfile -t atmphon_arry <<< "$atmphon_expanded"
: > "${prefix}.ph.in"
 
#generate ph.x input file
echo '&inputph' >> ${prefix}.ph.in
echo "   prefix='"${prefix}"'," >> ${prefix}.ph.in
echo "   tr2_ph=1.0d-12," >> ${prefix}.ph.in
echo "   nmix_ph=16," >> ${prefix}.ph.in
for ((i=1;i<=$ntyp;i++))
do
	for ((j=1;j<=86;j++))
	do
		if [ "${atmtype[$i]}" == "${atm[$j]}" ]; then 
			atmindex=$j
		fi
	done
	echo "   amass($i)="${atmmass[$atmindex]}"," >> ${prefix}.ph.in
done
echo "   outdir='./tmp'," >> ${prefix}.ph.in
echo "   fildyn='${prefix}.dynG'," >> ${prefix}.ph.in
echo "   nat_todo="${#atmphon_arry[@]}"," >> ${prefix}.ph.in
echo ' /' >> ${prefix}.ph.in
echo "0.0 0.0 0.0" >> ${prefix}.ph.in
echo "${atmphon_arry[@]}" >> ${prefix}.ph.in
}

#-----------Thermodynamic properties of adsorbed molecule-----------
function qe_phonon_adsorbed_thermo (){
	: > "${prefix}.shm"
 
echo ' 吸附分子 Shermo 输入'
echo
if [ -z "$fname2" ]; then
	echo " 本功能需要读取 ph.x 输出文件，例如 xxx.ph.out"
	read fname2
	while [ -z "$fname2" ]
	do
		echo "本功能需要读取 ph.x 输出文件，例如 xxx.ph.out"
		read fname2
	done
fi
 
#read which atom will be used in the linear response calculation
ncol=`grep 'Compute atoms' $fname2 |awk '{print NF}'`
acc=0
for ((i=3;i<=$ncol;i++))
do
        dophonatm[$acc]=`grep 'Compute atoms' $fname2 |awk -v var="$i" '{printf "%d\n",$var}'`
        acc=$(($acc+1))
done
 
#read which irreducible representations will be calculate
acc=0
for ((i=1;i<=$(("${#dophonatm[@]}"*3));i++))
do
        domodes[$acc]=`grep 'To be done' $fname2 | awk -v var="$i" 'NR==var{print $2}'`
        acc=$(($acc+1))
done
 
#record the frequency of irreducible representations to be calculated
for ((i=0;i<"${#domodes[@]}";i++))
do
	adsfreq[$i]=`grep "freq (  "${domodes[$i]}")" $fname2 |awk '{print $8}'`
done
 
#write Shermo input file
echo '*E' >> ${prefix}.shm
echo "  Input electronic energy in Hartree unit rather than Ry unit." >> ${prefix}.shm
echo '*wavenum' >> ${prefix}.shm
for ((i=0;i<"${#domodes[@]}";i++))
do
	echo "${adsfreq[$i]}" >> ${prefix}.shm
done
echo "*atoms" >> ${prefix}.shm
for ((i=0;i<"${#dophonatm[@]}";i++))
do
	dophonatmpos=$(($begatmpos+"${dophonatm[$i]}"-1))
	dophonatmtype=`sed -n "${dophonatmpos}p" $fname1 |awk '{print $1}'`
	dophonatmcoord=`sed -n "${dophonatmpos}p" $fname1 |awk '{printf "%.9f    %.9f    %.9f\n",$2,$3,$4}'`
	for ((j=1;j<=86;j++))
	do
		if [ "$dophonatmtype" == "${atm[$j]}" ]; then 
			atmindex=$j
		fi
	done
	echo -e "$dophonatmtype \t"${atmmass[$atmindex]}" \t $dophonatmcoord" >> ${prefix}.shm	
done
echo '*elevel' >> ${prefix}.shm
echo '0.00    1' >> ${prefix}.shm
}

# Write the atomic masses shared by all ph.x inputs. Keep the established
# lookup range and ambient atmindex semantics for compatibility.
function qe_write_ph_masses (){
    local outfile="$1"
    local i j

    for ((i=1;i<=$ntyp;i++)); do
        # Preserve the original H--Rn lookup range and ambient atmindex
        # behavior; do not reset or localize atmindex here.
        for ((j=1;j<=86;j++)); do
            if [ "${atmtype[$i]}" == "${atm[$j]}" ]; then
                atmindex=$j
            fi
        done
        echo "   amass($i)=${atmmass[$atmindex]}," >> "$outfile"
    done
}

# Write the common ph.x input, leaving mode-specific lines to the caller.
# lraman and ldisp belong before outdir/fildyn in the reviewed input order;
# dispersion's nq lines are therefore supplied as extra lines in that branch.
function qe_write_ph_input (){
    local outfile="$1"
    local fildyn="$2"
    local epsil="$3"
    local lraman="$4"
    local ldisp="$5"
    local qpoint="$6"
    local extra epsil_line

    : > "$outfile" || return 1
    {
        echo '&inputph'
        echo "   prefix='${prefix}',"
        echo '   tr2_ph=1.0d-12,'
        echo '   nmix_ph=16,'
    } >> "$outfile" || return 1
    qe_write_ph_masses "$outfile" || return 1

    if [ -n "$lraman" ]; then
        echo "   lraman=$lraman" >> "$outfile" || return 1
    fi
    if [ -n "$ldisp" ]; then
        echo "   ldisp=$ldisp" >> "$outfile" || return 1
        for extra in "${@:7}"; do
            echo "   $extra" >> "$outfile" || return 1
        done
    fi

    {
        echo "   outdir='./tmp',"
        echo "   fildyn='${fildyn}',"
    } >> "$outfile" || return 1

    if [ -n "$epsil" ]; then
        for extra in "${@:7}"; do
            echo "   $extra" >> "$outfile" || return 1
        done
        epsil_line="$epsil"
        case "$epsil_line" in
            epsil=*) ;;
            *) epsil_line="epsil=$epsil_line" ;;
        esac
        case "$epsil_line" in
            *,) ;;
            *) epsil_line="$epsil_line," ;;
        esac
        echo "   $epsil_line" >> "$outfile" || return 1
    elif [ -z "$ldisp" ]; then
        for extra in "${@:7}"; do
            echo "   $extra" >> "$outfile" || return 1
        done
    fi

    echo ' /' >> "$outfile" || return 1
    if [ -n "$qpoint" ]; then
        echo "$qpoint" >> "$outfile" || return 1
    fi
}

# Write dynmat.x input while retaining the reviewed placement of q() lines:
# metadata extras precede asr, whereas q-point extras follow it.
function qe_write_dynmat_input (){
    local outfile="$1"
    local fildyn="$2"
    local asr="$3"
    local extra
    local -a qpoint_extras=()

    : > "$outfile" || return 1
    echo '&input' >> "$outfile" || return 1
    echo "fildyn='${fildyn}'," >> "$outfile" || return 1
    for extra in "${@:4}"; do
        case "$extra" in
            q\(*) qpoint_extras+=("$extra") ;;
            *) echo "$extra" >> "$outfile" || return 1 ;;
        esac
    done
    echo "asr=$asr" >> "$outfile" || return 1
    for extra in "${qpoint_extras[@]}"; do
        echo "$extra" >> "$outfile" || return 1
    done
    echo '/' >> "$outfile" || return 1
}

# Write the three post-processing inputs used by both dispersion modes.
function qe_write_dispersion_post_inputs (){
    local prefix="$1"

    : > "${prefix}.q2r.in" || return 1
    {
        echo '&input'
        echo "   fildyn='${prefix}.dyn',"
        echo "   zasr='simple',"
        echo "   flfrc='${prefix}.fc',"
        echo ' /'
    } >> "${prefix}.q2r.in" || return 1

    : > "${prefix}.matdyn.in" || return 1
    {
        echo '&input'
        echo "   asr='simple',"
        echo "   flfrc='${prefix}.fc',"
        echo "   flfreq='${prefix}.freq',"
        echo '   q_in_cryst_coord=.true.'
        echo ' /'
        echo ' Input q-points path, same in bands.'
    } >> "${prefix}.matdyn.in" || return 1

    : > "${prefix}.plotband.in" || return 1
    {
        echo "${prefix}.freq"
        echo '0 700'
        echo 'freq.plot'
        echo 'freq.ps'
        echo '0.0'
        echo '100.0 0.0'
    } >> "${prefix}.plotband.in" || return 1
}

# Generate the shared ph.x/q2r.x/matdyn.x/plotband.x dispersion inputs.
function qe_generate_phonon_dispersion_inputs (){
    local prefix="$1"

    qe_write_ph_input "${prefix}.ph.in" "${prefix}.dyn" '' '' '.true.' '' \
        'nq1=4,' 'nq2=4,' 'nq3=4,' || return 1
    qe_write_dispersion_post_inputs "$prefix"
}

#-----------Phonon frequency of gaseous molecule at gamma-----------
function qe_phonon_gas_frequency (){
echo ' 气相分子 Gamma 点振动输入'
echo

    qe_write_ph_input "${prefix}.ph.in" "${prefix}.dynG" '' '' '' \
        '0.0 0.0 0.0' 'asr= .true.,' || return 1
    qe_write_dynmat_input "${prefix}.dynmat.in" "${prefix}.dynG" "'zero-dim'"
}

function qe_frequency_is_positive (){
	printf '%s\n' "$1" | LC_ALL=C awk '
		NR != 1 {bad=1}
		NR == 1 {v=$0; sub(/^[[:space:]]+/, "", v); sub(/[[:space:]]+$/, "", v)}
		END {
			if (bad || v !~ /^-?([0-9]+([.][0-9]*)?|[.][0-9]+)$/) exit 2
			if (v !~ /^-/ && v ~ /[1-9]/) exit 0
			exit 1
		}'
}

#-----------Thermodynamic properties of gaseous molecule-----------
function qe_phonon_gas_thermo (){
local status last_frequency_line
local -a gasfreq=()
echo ' 气相分子 Shermo 输入'
echo 
 
if [ -z "$(ls dynmat.mold 2>/dev/null)" ]; then 
	echo " The 'dynmat.mold' file does not exist!"
	exit 1
fi
 
#read frequency from dynmat.mold
acc=0
last_frequency_line=`grep -n 'FR-COORD' dynmat.mold |awk -F \: '{print $1}'`
for ((i=3;i<last_frequency_line;i++))
do
	val=`sed -n "${i}p" dynmat.mold`
	if qe_frequency_is_positive "$val"; then
		status=0
	else
		status=$?
	fi
	case "$status" in
		0)
			gasfreq[$acc]="$val"
			acc=$(($acc+1))
			;;
		1)
			;;
		2)
			case "$val" in
				*[0-9][eEdD][+-][0-9]*|*[0-9][eEdD][0-9]*)
					echo " 错误：频率 '$val' 使用了不支持指数记数法；仅支持普通十进制。" >&2
					;;
				*)
					echo " 错误：频率 '$val' 不是支持的普通十进制形式。" >&2
					;;
			esac
			return 2
			;;
	esac
done

#write Shermo input file
: > "${prefix}.shm"
echo '*E' >> ${prefix}.shm
echo "  Input electronic energy in Hartree unit rather than Ry unit." >> ${prefix}.shm
echo '*wavenum' >> ${prefix}.shm
for ((i=0;i<"${#gasfreq[@]}";i++))
do
	echo "${gasfreq[$i]}" >> ${prefix}.shm
done
echo "*atoms" >> ${prefix}.shm
for ((i=0;i<"$natm";i++))
do
	gasmolpos=$((${begatmpos}+$i))
	gasatmtype=`sed -n "${gasmolpos}p" $fname1 |awk '{print $1}'`
	gasatmcoord=`sed -n "${gasmolpos}p" $fname1 |awk '{printf "%.9f    %.9f    %.9f\n",$2,$3,$4}'`
	for ((j=1;j<=86;j++))
	do
		if [ "$gasatmtype" == "${atm[$j]}" ]; then 
			atmindex=$j
		fi
	done
	echo -e "$gasatmtype \t"${atmmass[$atmindex]}" \t $gasatmcoord" >> ${prefix}.shm	
done
echo '*elevel' >> ${prefix}.shm
echo '0.00    1' >> ${prefix}.shm
}

#---------Non-polar materials Phonon frequency at gamma-------
function qe_phonon_nonpolar_frequency (){
echo ' 非极性材料 Gamma 点声子输入'
echo

    qe_write_ph_input "${prefix}.ph.in" "${prefix}.dynG" '' '' '' \
        '0.0 0.0 0.0' || return 1
    qe_write_dynmat_input "${prefix}.dynmat.in" "${prefix}.dynG" "'simple'"
}

# Gamma-point IR input. Born effective charges and dielectric response require
# an unperturbed insulating ground state and epsil=.true. in ph.x.
function qe_phonon_ir (){
	echo ' 红外光谱 IR 输入（绝缘体/半导体）'
	echo


    qe_write_ph_input "${prefix}.ph.in" "${prefix}.dynG" '.true.,' '' '' \
        '0.0 0.0 0.0' 'trans=.true.,' || return 1
    qe_write_dynmat_input "${prefix}.dynmat.in" "${prefix}.dynG" "'simple'" \
        "filout='${prefix}.dynmat.out'," "fileig='${prefix}.modes',"
}

#---------Non-polar materials Phonon dispersion-------
function qe_phonon_nonpolar_dispersion (){
echo ' 非极性材料声子色散输入'
echo 

    qe_generate_phonon_dispersion_inputs "$prefix"
}

#---------Non-polar materials raman-------
function qe_phonon_nonpolar_raman (){
echo ' 非极性材料 Raman 输入（LDA / NC 赝势）'
echo

    qe_write_ph_input "${prefix}.ph.in" "${prefix}.dynG" '' '.true.' '' \
        '0.0 0.0 0.0' || return 1
    qe_write_dynmat_input "${prefix}.dynmat.in" "${prefix}.dynG" "'simple',"
}

#---------polar materials Phonon frequency at gamma-------
function qe_phonon_polar_frequency (){
echo ' 极性材料 Gamma 点声子输入'
echo

    qe_write_ph_input "${prefix}.ph.in" "${prefix}.dynG" '' '' '' \
        '0.0 0.0 0.0' || return 1
    qe_write_dynmat_input "${prefix}.dynmat.in" "${prefix}.dynG" "'simple'," \
        'q(1)=1.0,' 'q(2)=0.0,' 'q(3)=0.0,'
}

#---------polar materials Phonon dispersion-------
function qe_phonon_polar_dispersion (){
echo ' 极性材料声子色散输入'
echo 

    qe_generate_phonon_dispersion_inputs "$prefix"
}

#---------polar materials raman-------
function qe_phonon_polar_raman (){
echo ' 极性材料 Raman 输入（LDA / NC 赝势）'
echo

    qe_write_ph_input "${prefix}.ph.in" "${prefix}.dynG" '' '.true.' '' \
        '0.0 0.0 0.0' || return 1
    qe_write_dynmat_input "${prefix}.dynmat.in" "${prefix}.dynG" "'simple'" \
        'q(1)=1.0,' 'q(2)=0.0,' 'q(3)=0.0,'
}
function phin (){
    local phonon_args=(--from-main-menu) status=0
    if [ -n "${fname1:-}" ]; then
        phonon_args+=(--source "$fname1")
    fi
    qbox_python -m qbox.io.phonon_menu "${phonon_args[@]}" || status=$?
    # Only explicit navigation returns to the main menu; generation exits.
    if [ "$status" = 10 ]; then
        if [ -z "${QE_DIRECT_ACTION:-}" ]; then
            qe_request_main_menu
        fi
        return 0
    fi
    return "$status"
}
