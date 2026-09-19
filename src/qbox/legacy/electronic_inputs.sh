#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_generate_pwin_for_task (){
	local calc_prefix task required_file structure_file old_fname1 old_prefix old_noninteractive old_preset old_return_to_exec
	local temporary_cif_alias structure_abs structure_label
	calc_prefix="$1"
	task="$2"
	required_file="$3"
	structure_file="$4"

	if [ -z "$structure_file" ]; then
		structure_file=`qe_find_structure_for_prefix "$calc_prefix"`
	fi
	if [ -n "$structure_file" ]; then
		if [ "$QE_GENERATE_PWIN_COMPACT" != "1" ]; then
			structure_label=`basename "$structure_file"`
			echo
			echo " 将使用结构文件 '$structure_label' 生成 ${required_file}。"
			echo ' 如需改用其他结构文件，请输入文件名；直接回车使用上述文件。'
			read user_structure_file
			if [ -n "$user_structure_file" ]; then
				structure_file="$user_structure_file"
			fi
		fi
	fi

	if [ -z "$structure_file" ]; then
		echo
		echo " 未找到可自动识别的结构文件 ${calc_prefix}.cif/.gjf/.xyz/.vasp/.pdb。"
		echo " 请输入用于生成 ${required_file} 的结构文件。"
		read structure_file
	fi

	while [ -z "$structure_file" ] || [ ! -f "$structure_file" ]; do
		echo " 错误：未找到结构文件 '$structure_file'。请重新输入。"
		read structure_file
	done

	qe_auto_convert_vasp_to_cif "$structure_file" || return 1
	structure_file="$QE_AUTO_CONVERTED_CIF"

	old_fname1="$fname1"
	old_prefix="$prefix"
	old_noninteractive="$NONINTERACTIVE_PWIN"
	old_preset="$PRESET_RTASK"
	old_return_to_exec="$RETURN_TO_EXEC_CALC"

	fname1="$structure_file"
	prefix="$calc_prefix"
	temporary_cif_alias=""
	if [ "$task" == "bands" ] && [ ! -f "${calc_prefix}.cif" ]; then
		if [[ "$structure_file" == *.cif ]]; then
			structure_abs=`readlink -f "$structure_file" 2>/dev/null`
			if [ -n "$structure_abs" ]; then
				ln -s "$structure_abs" "${calc_prefix}.cif"
				temporary_cif_alias="${calc_prefix}.cif"
			fi
		fi
	fi
	PRESET_RTASK="$task"
	RETURN_TO_EXEC_CALC=1
	if [ "$QE_GENERATE_PWIN_COMPACT" == "1" ]; then
		NONINTERACTIVE_PWIN=1
	else
		unset NONINTERACTIVE_PWIN
		echo
		echo " 已进入 ${required_file} 生成菜单。请按需调整参数，选择 0 生成后将继续执行计算。"
	fi
	pwin
	local gen_status=$?

	fname1="$old_fname1"
	prefix="$old_prefix"
	NONINTERACTIVE_PWIN="$old_noninteractive"
	PRESET_RTASK="$old_preset"
	RETURN_TO_EXEC_CALC="$old_return_to_exec"
	if [ -n "$temporary_cif_alias" ]; then
		rm -f "$temporary_cif_alias"
	fi

	return $gen_status
}

function qe_render_bandsx_for_band_dir (){
	local infile="$1"
	awk '
	  BEGIN{filband_done=0}
	  /^[[:space:]]*filband[[:space:]]*=/ {
	    print "   filband         = '\''BAND/bands.dat'\''"
	    filband_done=1
	    next
	  }
	  /^[[:space:]]*\// {
	    if (filband_done==0) {
	      print "   filband         = '\''BAND/bands.dat'\''"
	      filband_done=1
	    }
	    print
	    next
	  }
	  {print}
	' "$infile"
}

function qe_prepare_bandsx_input_for_band_dir (){
	local infile="$1"
	[ -f "$infile" ] || return 1
	qe_atomic_rewrite "$infile" qe_render_bandsx_for_band_dir
}

function qe_render_pdos_for_pdos_dir (){
	local infile="$1"
	awk '
	  BEGIN{filpdos_done=0}
	  /^[[:space:]]*filpdos[[:space:]]*=/ {
	    print "   filpdos         = '\''PDOS/pdos.dat'\''"
	    filpdos_done=1
	    next
	  }
	  /^[[:space:]]*\// {
	    if (filpdos_done==0) {
	      print "   filpdos         = '\''PDOS/pdos.dat'\''"
	      filpdos_done=1
	    }
	    print
	    next
	  }
	  {print}
	' "$infile"
}

function qe_prepare_pdos_input_for_pdos_dir (){
	local infile="$1"
	[ -f "$infile" ] || return 1
	qe_atomic_rewrite "$infile" qe_render_pdos_for_pdos_dir
}

function qe_prompt_band_precision_mode (){
	local mode
	echo >&2
	echo ' 请选择能带计算输入文件生成精度：' >&2
	echo '  1) 普通计算：延续当前默认设置' >&2
	echo '  2) 高精度计算：采用有效质量计算使用的默认精度设置' >&2
	read -r mode || return 1
	while [ "$mode" != "1" ] && [ "$mode" != "2" ]; do
		echo ' 请输入 1 或 2。' >&2
		read -r mode || return 1
	done
	if [ "$mode" == "2" ]; then
		echo "high"
	else
		echo "normal"
	fi
}

function qe_generate_band_scf_input_by_precision (){
	local calc_prefix="$1"
	local precision="$2"
	if [ "$precision" == "high" ]; then
		PWIN_DEFAULT_PSEUDOLIB=PD04 \
		PWIN_DEFAULT_SCF_CONV_THR=1.D-10 \
		PWIN_DEFAULT_KMESH_SCALE=1.2 \
		PWIN_DEFAULT_ODD_ELECTRON_DEGAUSS=0.002 \
		qe_generate_pwin_for_task "$calc_prefix" "energy" "${calc_prefix}.scf.in"
	else
		qe_generate_pwin_for_task "$calc_prefix" "energy" "${calc_prefix}.scf.in"
	fi
}

function qe_generate_band_pw_input_by_precision (){
	local calc_prefix="$1"
	local precision="$2"
	if [ "$precision" == "high" ]; then
		PWIN_DEFAULT_PSEUDOLIB=PD04 \
		PWIN_DEFAULT_BAND_KPATH_MODE=spacing \
		PWIN_DEFAULT_BAND_KPATH_SPACING=0.01 \
		PWIN_DEFAULT_BANDS_NBND_FACTOR=1.2 \
		PWIN_DEFAULT_DIAGO_FULL_ACC=true \
		PWIN_DEFAULT_DIAGO_THR_INIT=1.D-8 \
		PWIN_DEFAULT_DIAGONALIZATION=david \
		PWIN_DEFAULT_DIAGO_DAVID_NDIM=2 \
		PWIN_DEFAULT_ODD_ELECTRON_DEGAUSS=0.002 \
		qe_generate_pwin_for_task "$calc_prefix" "bands" "${calc_prefix}.bands.in"
	else
		qe_generate_pwin_for_task "$calc_prefix" "bands" "${calc_prefix}.bands.in"
	fi
}

function qe_pdos_input_matches_prefix (){
	local infile="$1"
	local calc_prefix="$2"
	[ -f "$infile" ] && awk -v p="$calc_prefix" '
		BEGIN{found=0; ok=1}
		tolower($0) ~ /^[[:space:]]*prefix[[:space:]]*=/ {
			found=1
			line=$0
			sub(/^[^=]*=[[:space:]]*/, "", line)
			gsub(/[[:space:]]*,[[:space:]]*$/, "", line)
			gsub(/^[[:space:]]*["'\'']|["'\''][[:space:]]*$/, "", line)
			ok=(line==p ? 0 : 1)
			exit ok
		}
		END{if(!found) exit 1; exit ok}
	' "$infile"
}

function qe_ensure_band_inputs (){
	local calc_prefix status generated_band_input generated_bandsx_input band_precision_mode need_pwin_generation
	calc_prefix="$1"
	status=0
	generated_band_input=0
	generated_bandsx_input=0
	band_precision_mode="normal"
	need_pwin_generation=0

	mkdir -p BAND

	if [ ! -f "${calc_prefix}.scf.in" ] || { [ ! -f "BAND/${calc_prefix}.bands.in" ] && [ ! -f "BAND/${calc_prefix}.band.in" ]; }; then
		need_pwin_generation=1
	fi
	if [ "$need_pwin_generation" == "1" ]; then
		band_precision_mode=`qe_prompt_band_precision_mode`
		if [ "$band_precision_mode" == "high" ]; then
			echo " 已选择：高精度能带计算输入生成。"
		else
			echo " 已选择：普通能带计算输入生成。"
		fi
	fi

	if [ ! -f "${calc_prefix}.scf.in" ]; then
		qe_print_input_generation_header "${calc_prefix}.scf.in" "pw.x / SCF（能带）"
		echo " 缺少 ${calc_prefix}.scf.in，转入 pw.x 输入文件生成流程。"
		qe_generate_band_scf_input_by_precision "$calc_prefix" "$band_precision_mode" || status=1
	fi

	if [ ! -f "BAND/${calc_prefix}.bands.in" ] && [ ! -f "BAND/${calc_prefix}.band.in" ]; then
		qe_print_input_generation_header "BAND/${calc_prefix}.bands.in" "pw.x / bands"
		echo " 缺少 BAND/${calc_prefix}.bands.in，转入 pw.x bands 输入文件生成流程。"
		qe_generate_band_pw_input_by_precision "$calc_prefix" "$band_precision_mode" && generated_band_input=1 || status=1
	fi

	if [ ! -f "BAND/${calc_prefix}.bands.in" ] && [ -f "${calc_prefix}.bands.in" ]; then
		if [ "$generated_band_input" == "1" ]; then
			mv "${calc_prefix}.bands.in" "BAND/${calc_prefix}.bands.in"
		else
			cp "${calc_prefix}.bands.in" "BAND/${calc_prefix}.bands.in"
		fi
	fi

	if [ ! -f "BAND/${calc_prefix}.band.in" ] && [ -f "${calc_prefix}.band.in" ]; then
		if [ "$generated_band_input" == "1" ]; then
			mv "${calc_prefix}.band.in" "BAND/${calc_prefix}.band.in"
		else
			cp "${calc_prefix}.band.in" "BAND/${calc_prefix}.band.in"
		fi
	fi

	if [ ! -f "BAND/bands.in" ]; then
		qe_print_input_generation_header "BAND/bands.in" "bands.x / 能带后处理"
		echo " 缺少 BAND/bands.in，转入 bands.x 输入文件生成流程。"
		echo " 将使用前缀 '${calc_prefix}' 生成 bands.x 输入文件。直接回车继续，输入 q 取消。"
		read bandsx_confirm
		if [ "$bandsx_confirm" == "q" ]; then
			status=1
		else
		local old_prefix="$prefix"
		prefix="$calc_prefix"
		bandin && generated_bandsx_input=1 || status=1
		prefix="$old_prefix"
		fi
	fi

	if [ ! -f "BAND/bands.in" ] && [ -f "bands.in" ]; then
		if [ "$generated_bandsx_input" == "1" ]; then
			mv bands.in BAND/bands.in
		else
			cp bands.in BAND/bands.in
		fi
	fi

	if [ -f "BAND/bands.in" ]; then
		qe_prepare_bandsx_input_for_band_dir "BAND/bands.in"
	fi

	return $status
}

function qe_output_success (){
	local outfile="$1"
	[ -f "$outfile" ] && grep -q "JOB DONE" "$outfile"
}

function qe_output_success_for_prefix (){
	local outfile="$1"
	local calc_prefix="$2"
	qe_output_success "$outfile" || return 1
	[ -d "tmp/${calc_prefix}.save" ] || return 1
}

function qe_band_pw_output_success (){
	local calc_prefix="$1"
	local band_input=""
	[ -s BAND/band.out ] || return 1
	qe_output_success BAND/band.out || return 1
	if [ -f "BAND/${calc_prefix}.bands.in" ]; then
		band_input="BAND/${calc_prefix}.bands.in"
	elif [ -f "BAND/${calc_prefix}.band.in" ]; then
		band_input="BAND/${calc_prefix}.band.in"
	fi
	if [ -n "$band_input" ]; then
		qe_pdos_input_matches_prefix "$band_input" "$calc_prefix" || return 1
	fi
}

function qe_bandsx_output_success (){
	[ -s BAND/bands.out ] || return 1
	qe_output_success BAND/bands.out || return 1
	[ -s BAND/bands.dat.gnu ] || return 1
}

function qe_pdos_output_success (){
	local calc_prefix="$1"
	[ -s PDOS/pdos.out ] || return 1
	{ grep -q "JOB DONE" PDOS/pdos.out || grep -qi "Writing data to file" PDOS/pdos.out; } || return 1
	if [ -n "$calc_prefix" ] && [ -f PDOS/pdos.in ]; then
		qe_pdos_input_matches_prefix PDOS/pdos.in "$calc_prefix" || return 1
	fi
	{ compgen -G "PDOS/*.pdos_*" >/dev/null || compgen -G "PDOS/ATOM_PDOS/*.pdos_*" >/dev/null; }
}

function qe_pdos_clean_success (){
	[ -d PDOS/ATOM_PDOS ] && compgen -G "PDOS/ATOM_PDOS/*.pdos_atm#*" >/dev/null
}

function qe_pdos_sum_success (){
	[ -d PDOS/ATOM_PDOS ] && { compgen -G "PDOS/ATOM_PDOS/*_tot.dat" >/dev/null || compgen -G "PDOS/ATOM_PDOS/*_s.dat" >/dev/null || compgen -G "PDOS/ATOM_PDOS/*_p.dat" >/dev/null || compgen -G "PDOS/ATOM_PDOS/*_d.dat" >/dev/null; }
}

function qe_pdos_sum_success_in_dir (){
	local pdos_dir="$1"
	[ -d "$pdos_dir" ] && { compgen -G "${pdos_dir}/*_tot.dat" >/dev/null || compgen -G "${pdos_dir}/*_s.dat" >/dev/null || compgen -G "${pdos_dir}/*_p.dat" >/dev/null || compgen -G "${pdos_dir}/*_d.dat" >/dev/null; }
}

function qe_pdos_plot_success (){
	local calc_prefix="$1"
	[ -f "PDOS/ATOM_PDOS/${calc_prefix}_element_dos.png" ] || [ -f "PDOS/ATOM_PDOS/${calc_prefix}_combined_pdos.png" ]
}

function qe_pdos_plot_success_in_dir (){
	local pdos_dir="$1"
	local calc_prefix="$2"
	[ -f "${pdos_dir}/${calc_prefix}_element_dos.png" ] || [ -f "${pdos_dir}/${calc_prefix}_combined_pdos.png" ]
}

function qe_clean_pdos_generated_outputs (){
	local backup file
	backup="PDOS/previous-$(date +%Y%m%d-%H%M%S).$$"
	mkdir -p "$backup" || return 1
	for file in PDOS/pdos.out PDOS/pdos.dat.pdos_* PDOS/*.pdos_* PDOS/*.dat; do
		[ -f "$file" ] && mv -- "$file" "$backup/" || true
	done
	if [ -d PDOS/ATOM_PDOS ]; then
		mkdir -p "$backup/ATOM_PDOS"
		for file in PDOS/ATOM_PDOS/pdos.dat.pdos_* PDOS/ATOM_PDOS/*.pdos_* PDOS/ATOM_PDOS/*_tot.dat PDOS/ATOM_PDOS/*_s.dat PDOS/ATOM_PDOS/*_p.dat PDOS/ATOM_PDOS/*_d.dat PDOS/ATOM_PDOS/*_f.dat PDOS/ATOM_PDOS/*_g.dat PDOS/ATOM_PDOS/*_element_dos.png PDOS/ATOM_PDOS/*_orbital_dos.png PDOS/ATOM_PDOS/*_combined_pdos.png; do
			[ -f "$file" ] && mv -- "$file" "$backup/ATOM_PDOS/" || true
		done
	fi
}

# ======================= Built-in external tools =======================
# >>> BEGIN BUILTIN: cleanPDOS.sh
