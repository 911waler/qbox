#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function pseudo_dir_by_lib (){
	local lib="$1"
	if [ "$lib" == "SSSP" ]; then
		echo "$sssppath"
	elif [ "$lib" == "PD04" ]; then
		echo "$PD04PBEpath"
	elif [ "$lib" == "SG15" ]; then
		echo "$SG15PBEpath"
	fi
}

function pseudo_file_by_lib (){
	local lib="$1"
	local idx="$2"
	if [ "$lib" == "SSSP" ]; then
		echo "${SSSPlib[$idx]}"
	elif [ "$lib" == "PD04" ]; then
		echo "${PD04lib[$idx]}"
	elif [ "$lib" == "SG15" ]; then
		echo "${SG15lib[$idx]}"
	fi
}

function read_upf_cutoffs (){
	local ppfile="$1"
	awk '
		BEGIN{IGNORECASE=1}
		{
			line=$0
			gsub(/[dD]/,"e",line)
			if(line ~ /wfc_cutoff[[:space:]]*=/){
				tmp=line
				sub(/^.*wfc_cutoff[[:space:]]*=[[:space:]]*["'\'']?/,"",tmp)
				sub(/["'\''][^0-9+\-.eE]*.*$/,"",tmp)
				if(tmp+0>0) wfc=tmp+0
			}
			if(line ~ /rho_cutoff[[:space:]]*=/){
				tmp=line
				sub(/^.*rho_cutoff[[:space:]]*=[[:space:]]*["'\'']?/,"",tmp)
				sub(/["'\''][^0-9+\-.eE]*.*$/,"",tmp)
				if(tmp+0>0) rho=tmp+0
			}
			if(line ~ /cutoff/ && line ~ /wavefunctions/){
				tmp=line
				sub(/^.*wavefunctions[^0-9+\-.]*/,"",tmp)
				sub(/[^0-9+\-.eE].*$/,"",tmp)
				if(tmp+0>0) wfc=tmp+0
			}
			if(line ~ /cutoff/ && line ~ /charge density/){
				tmp=line
				sub(/^.*charge density[^0-9+\-.]*/,"",tmp)
				sub(/[^0-9+\-.eE].*$/,"",tmp)
				if(tmp+0>0) rho=tmp+0
			}
		}
		END{
			if(wfc+0>0) printf "%.6g", wfc
			printf " "
			if(rho+0>0) printf "%.6g", rho
			printf "\n"
		}
	' "$ppfile"
}

function qe_read_upf_z_valence (){
	local ppfile="$1"
	[ -f "$ppfile" ] || return 1
	qbox_python -m qbox.io.upf_valence "$ppfile"
}

function qe_estimate_nelec_from_current_pwin_context (){
	local ppdir ppfile atmindex zval total
	ppdir=`pseudo_dir_by_lib "$pseudolib"`
	total=0
	for ((i=1;i<=$ntyp;i++))
	do
		atmindex=''
		for ((j=1;j<=103;j++))
		do
			if [ "${atmtype[$i]}" == "${atm[$j]}" ]; then
				atmindex=$j
			fi
		done
		ppfile=`pseudo_file_by_lib "$pseudolib" "$atmindex"`
		if [ -z "$ppdir" ] || [ -z "$ppfile" ] || [ ! -f "$ppdir/$ppfile" ]; then
			return 1
		fi
		zval=`qe_read_upf_z_valence "$ppdir/$ppfile"`
		if ! echo "$zval" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
			return 1
		fi
		total=`awk -v t="$total" -v z="$zval" -v n="${Natmtype[$i]}" 'BEGIN{printf "%.10g", t+z*n}'`
	done
	echo "$total"
}

function qe_estimate_nelec_from_pwin_file (){
	local infile="$1"
	[ -f "$infile" ] || return 1
	qbox_python -m qbox.io.electron_count "$infile"
}

function qe_nelec_is_odd_integer (){
	local nelec="$1"
	awk -v nelec="$nelec" 'BEGIN{
		nearest=int(nelec+0.5)
		if(nelec<=0 || (nelec-nearest>1.0e-6) || (nearest-nelec>1.0e-6)) exit 1
		exit !(nearest%2)
	}'
}

function qe_print_odd_electron_notice (){
	local nelec="$1"
	local profile_label="$2"
	echo " 提示：检测到奇数电子体系（nelec=${nelec}），已进入奇数电子体系设定。"
	[ -n "$profile_label" ] && echo " 当前流程：${profile_label}。"
}

function qe_recommend_band_nbnd_from_nelec (){
	local nelec="$1"
	awk -v nelec="$nelec" 'BEGIN{
		occ=int(nelec/2)
		if(occ < nelec/2) occ++
		nbnd=int(occ*1.5)
		if(nbnd < occ*1.5) nbnd++
		if(nbnd < occ+8) nbnd=occ+8
		if(nbnd < occ+1) nbnd=occ+1
		printf "%d", nbnd
	}'
}

function qe_recommend_band_nbnd_from_nelec_with_min (){
	local nelec="$1"
	local min_nbnd="$2"
	local recommended
	recommended=`qe_recommend_band_nbnd_from_nelec "$nelec"`
	awk -v r="$recommended" -v m="$min_nbnd" 'BEGIN{
		if(m ~ /^[0-9]+$/ && r < m) r=m
		printf "%d", r
	}'
}

function qe_recommend_band_nbnd_from_nelec_with_factor (){
	local nelec="$1"
	local factor="$2"
	awk -v nelec="$nelec" -v factor="$factor" 'BEGIN{
		occ=int(nelec/2)
		if(occ < nelec/2) occ++
		nbnd=int(occ*factor)
		if(nbnd < occ*factor) nbnd++
		if(nbnd < occ+1) nbnd=occ+1
		printf "%d", nbnd
	}'
}

function pwin_nbnd_label (){
	local pwin_nelec pwin_recommended_nbnd
	if [ "$nbnd" != "Default" ]; then
		echo "$nbnd"
		return 0
	fi
	pwin_nelec=`qe_estimate_nelec_from_current_pwin_context 2>/dev/null`
	if echo "$pwin_nelec" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
		if [ -n "$PWIN_DEFAULT_BANDS_NBND_FACTOR" ]; then
			pwin_recommended_nbnd=`qe_recommend_band_nbnd_from_nelec_with_factor "$pwin_nelec" "$PWIN_DEFAULT_BANDS_NBND_FACTOR"`
			echo "推荐 ${pwin_recommended_nbnd}（电子数 ${pwin_nelec}；占据带数×${PWIN_DEFAULT_BANDS_NBND_FACTOR}）"
		elif [ -n "$PWIN_DEFAULT_BANDS_NBND_MIN" ]; then
			pwin_recommended_nbnd=`qe_recommend_band_nbnd_from_nelec_with_min "$pwin_nelec" "$PWIN_DEFAULT_BANDS_NBND_MIN"`
			echo "推荐 ${pwin_recommended_nbnd}（电子数 ${pwin_nelec}；至少 ${PWIN_DEFAULT_BANDS_NBND_MIN}）"
		else
			pwin_recommended_nbnd=`qe_recommend_band_nbnd_from_nelec "$pwin_nelec"`
			echo "推荐 ${pwin_recommended_nbnd}（电子数 ${pwin_nelec}）"
		fi
	else
		echo "自动（未能估算电子数）"
	fi
}

function qe_render_pw_nbnd (){
	local infile="$1"
	local nbnd="$2"
	awk -v nbnd="$nbnd" '
	  BEGIN{in_system=0; nbnd_done=0}
	  tolower($0) ~ /^[[:space:]]*&system/ {in_system=1; print; next}
	  in_system && /^[[:space:]]*nbnd[[:space:]]*=/ {
	    print "   nbnd            = " nbnd
	    nbnd_done=1
	    next
	  }
	  in_system && /^[[:space:]]*\// {
	    if (nbnd_done==0) {
	      print "   nbnd            = " nbnd
	      nbnd_done=1
	    }
	    in_system=0
	    print
	    next
	  }
	  {print}
	' "$infile"
}

function qe_set_pw_nbnd_in_file (){
	local infile="$1" nbnd_value="$2"
	[ -f "$infile" ] || return 1
	printf '%s\n' "$nbnd_value" | awk 'NF==1 && $1 ~ /^[0-9]+$/ && $1 > 0 {exit 0} {exit 1}' || return 1
	qe_atomic_rewrite "$infile" qe_render_pw_nbnd "$nbnd_value"
}

function default_cutoffs_from_pseudos (){
	local fallback_wfc="$1"
	local fallback_rho="$2"
	local ppdir ppfile cutoffs ewfc erho max_wfc max_rho atmindex
	ppdir=`pseudo_dir_by_lib "$pseudolib"`
	max_wfc=0
	max_rho=0

	for ((i=1;i<=$ntyp;i++))
	do
		atmindex=''
		for ((j=1;j<=103;j++))
		do
			if [ "${atmtype[$i]}" == "${atm[$j]}" ]; then
				atmindex=$j
			fi
		done
		ppfile=`pseudo_file_by_lib "$pseudolib" "$atmindex"`
		if [ -n "$ppdir" ] && [ -n "$ppfile" ] && [ -f "$ppdir/$ppfile" ]; then
			cutoffs=`read_upf_cutoffs "$ppdir/$ppfile"`
			ewfc=`echo "$cutoffs" | awk '{print $1}'`
			erho=`echo "$cutoffs" | awk '{print $2}'`
			if [ -n "$ewfc" ] && awk -v a="$ewfc" -v b="$max_wfc" 'BEGIN{exit !(a>b)}'; then
				max_wfc="$ewfc"
			fi
			if [ -n "$erho" ] && awk -v a="$erho" -v b="$max_rho" 'BEGIN{exit !(a>b)}'; then
				max_rho="$erho"
			fi
		fi
	done

	if ! awk -v v="$max_wfc" 'BEGIN{exit !(v>0)}'; then
		max_wfc="$fallback_wfc"
	fi
	max_wfc=`awk -v w="$max_wfc" 'BEGIN{
		i=int(w)
		if(w>i) i++
		r=i%10
		if(r==0){
			out=i
		}else if(r<=5){
			out=i-r+5
		}else{
			out=i-r+10
		}
		printf "%d", out
	}'`
	if ! awk -v v="$max_rho" 'BEGIN{exit !(v>0)}'; then
		max_rho=`awk -v w="$max_wfc" -v fallback="$fallback_rho" 'BEGIN{
			r=10*w
			if(r<450) r=450
			if(fallback>r) r=fallback
			printf "%d", r
		}'`
	else
		max_rho=`awk -v r="$max_rho" -v w="$max_wfc" 'BEGIN{
			step=50
			out=int((r+step-1.0e-12)/step)*step
			if(out<r) out+=step
			minrho=10*w
			if(out<minrho) out=minrho
			printf "%d", out
		}'`
	fi
	echo "$max_wfc $max_rho"
}
 
#--------------------------------- pw.x module----------------------------------------
function pwin_write_occupation_settings (){
	local outfile="$1"
	local pwin_nelec odd_smearing odd_degauss
	pwin_nelec=`qe_estimate_nelec_from_current_pwin_context 2>/dev/null`
	if qe_nelec_is_odd_integer "$pwin_nelec"; then
		odd_smearing="${PWIN_DEFAULT_ODD_ELECTRON_SMEARING:-marzari-vanderbilt}"
		odd_degauss="${PWIN_DEFAULT_ODD_ELECTRON_DEGAUSS:-0.01}"
		echo "   occupations     = 'smearing'" >> "$outfile"
		echo "   degauss         = ${odd_degauss}" >> "$outfile"
		echo "   smearing        = '${odd_smearing}'" >> "$outfile"
		qe_print_odd_electron_notice "$pwin_nelec" "已自动使用 occupations='smearing'、smearing='${odd_smearing}'、degauss=${odd_degauss} Ry"
		return 0
	fi
	if [ "$systype" == "Insulator" ] || [ "$systype" == "Semi-conductor" ] || [ "$systype" == "Doped-gapped" ]; then
		echo "   occupations     = 'fixed'" >> "$outfile"
	elif [ "$systype" == "Conductor" ] || [ "$systype" == "Doped-metallic" ]; then
		echo "   occupations     = 'smearing'" >> "$outfile"
		echo "   degauss         = 0.01" >> "$outfile"
		echo "   smearing        = 'marzari-vanderbilt'" >> "$outfile"
	elif [ "$systype" == "Molecule" ]; then
		echo "   occupations     = 'fixed'" >> "$outfile"
		echo "   assume_isolated = 'martyna-tuckerman'" >> "$outfile"
	fi
}

function pwin_write_symmetry_settings (){
	local outfile="$1"
	if [ "$pwin_nosym" == "Yes" ]; then
		echo "   nosym           = .true." >> "$outfile"
	fi
}

function pwin_double_kpmesh (){
	local mesh="$1"
	if [ "$mesh" == "gamma" ]; then
		echo "gamma"
	else
		echo "$mesh" | awk -F '*' 'NF==3 {printf "%d*%d*%d\n", $1*2, $2*2, $3*2}'
	fi
}

function pwin_scale_kpmesh (){
	local mesh="$1"
	local scale="$2"
	if [ "$mesh" == "gamma" ]; then
		echo "gamma"
	else
		echo "$mesh" | awk -F '*' -v s="$scale" 'NF==3 {
			for(i=1;i<=3;i++){
				v=int($i*s)
				if(v < $i*s) v++
				if(v < 1) v=1
				out[i]=v
			}
			printf "%d*%d*%d\n", out[1], out[2], out[3]
		}'
	fi
}

function pwin_write_diagonalization_accuracy_settings (){
	local outfile="$1"
	echo "   diago_full_acc  = .$pwin_diago_full_acc." >> "$outfile"
	echo "   diago_thr_init  = $pwin_diago_thr_init" >> "$outfile"
}

function pwin_diagonalization_label (){
	if [ "$pwin_diagonalization" == "cg" ]; then
		echo "diagonalization='cg'；diago_cg_maxiter=$pwin_diago_cg_maxiter"
	else
		echo "diagonalization='david'；diago_david_ndim=$pwin_diago_david_ndim"
	fi
}

function pwin_diagonalization_accuracy_label (){
	echo "diago_full_acc=.$pwin_diago_full_acc.；diago_thr_init=$pwin_diago_thr_init"
}

function pwin_write_diagonalization_settings (){
	local outfile="$1"
	echo "   diagonalization = '$pwin_diagonalization'" >> "$outfile"
	if [ "$pwin_diagonalization" == "cg" ]; then
		echo "   diago_cg_maxiter = $pwin_diago_cg_maxiter" >> "$outfile"
	else
		echo "   diago_david_ndim = $pwin_diago_david_ndim" >> "$outfile"
	fi
}

function qe_render_pwin_kpoints (){
	local infile="$1"
	local mesh="$2"
	awk -v mesh="$mesh" '
	  BEGIN{
	    skip_next=0
	    split(mesh, k, "*")
	  }
	  skip_next {skip_next=0; next}
	  /^[[:space:]]*K_POINTS[[:space:]]+(automatic|gamma)/ {
	    print ""
	    if (mesh=="gamma") {
	      print " K_POINTS gamma"
	    } else {
	      print " K_POINTS automatic"
	      printf " %d %d %d 0 0 0\n", k[1], k[2], k[3]
	      skip_next=1
	    }
	    next
	  }
	  {print}
	' "$infile"
}

function pwin_replace_kpoints_in_file (){
	local infile="$1" mesh="$2"
	[ -f "$infile" ] || return 1
	qe_atomic_rewrite "$infile" qe_render_pwin_kpoints "$mesh"
}

function qe_render_pwin_diagonalization_accuracy (){
	local infile="$1" full_acc="$2" thr="$3"
	awk -v full_acc="$full_acc" -v thr="$thr" '
	  BEGIN{in_electrons=0; full_done=0; thr_done=0}
	  /^[[:space:]]*&ELECTRONS/ {in_electrons=1; print; next}
	  in_electrons && /^[[:space:]]*diago_full_acc[[:space:]]*=/ {
	    print "   diago_full_acc  = " full_acc
	    full_done=1
	    next
	  }
	  in_electrons && /^[[:space:]]*diago_thr_init[[:space:]]*=/ {
	    print "   diago_thr_init  = " thr
	    thr_done=1
	    next
	  }
	  in_electrons && /^[[:space:]]*\// {
	    if (full_done==0) print "   diago_full_acc  = " full_acc
	    if (thr_done==0) print "   diago_thr_init  = " thr
	    in_electrons=0
	    print
	    next
	  }
	  {print}
	' "$infile"
}

function pwin_set_diagonalization_accuracy_in_file (){
	local infile="$1"
	[ -f "$infile" ] || return 1
	qe_atomic_rewrite "$infile" qe_render_pwin_diagonalization_accuracy ".${pwin_diago_full_acc}." "$pwin_diago_thr_init"
}

function qe_render_pwin_diagonalization (){
	local infile="$1" diag="$2" david_ndim="$3" cg_maxiter="$4"
	awk -v diag="$diag" -v david_ndim="$david_ndim" -v cg_maxiter="$cg_maxiter" '
	  BEGIN{in_electrons=0; diag_done=0; sub_done=0}
	  /^[[:space:]]*&ELECTRONS/ {in_electrons=1; print; next}
	  in_electrons && /^[[:space:]]*diagonalization[[:space:]]*=/ {
	    print "   diagonalization = '\''" diag "'\''"
	    diag_done=1
	    next
	  }
	  in_electrons && /^[[:space:]]*(diago_david_ndim|diago_cg_maxiter)[[:space:]]*=/ {
	    if (sub_done==0) {
	      if (diag=="cg") print "   diago_cg_maxiter = " cg_maxiter
	      else print "   diago_david_ndim = " david_ndim
	      sub_done=1
	    }
	    next
	  }
	  in_electrons && /^[[:space:]]*\// {
	    if (diag_done==0) print "   diagonalization = '\''" diag "'\''"
	    if (sub_done==0) {
	      if (diag=="cg") print "   diago_cg_maxiter = " cg_maxiter
	      else print "   diago_david_ndim = " david_ndim
	    }
	    in_electrons=0
	    print
	    next
	  }
	  {print}
	' "$infile"
}

function pwin_set_diagonalization_settings_in_file (){
	local infile="$1"
	[ -f "$infile" ] || return 1
	qe_atomic_rewrite "$infile" qe_render_pwin_diagonalization "$pwin_diagonalization" "$pwin_diago_david_ndim" "$pwin_diago_cg_maxiter"
}

function qe_render_pwin_without_charge_mixing (){
	local infile="$1"
	awk '
	  /^[[:space:]]*&ELECTRONS/ {in_electrons=1; print; next}
	  in_electrons && /默认 1[.]D-6 为较粗糙精度/ {next}
	  in_electrons && /^[[:space:]]*(electron_maxstep|conv_thr|mixing_mode|mixing_beta|mixing_ndim)[[:space:]]*=/ {next}
	  in_electrons && /^[[:space:]]*\// {in_electrons=0; print; next}
	  {print}
	' "$infile"
}

function pwin_remove_charge_mixing_settings_from_file (){
	local infile="$1"
	[ -f "$infile" ] || return 1
	qe_atomic_rewrite "$infile" qe_render_pwin_without_charge_mixing
}

function qe_render_nscf_nbnd_update (){
	local infile="$1"
	awk '
	  BEGIN{in_system=0; calc_done=0; verb_done=0; occ_done=0; nosym_done=0; noinv_done=0}
	  /^[[:space:]]*&CONTROL/ {in_control=1; print; next}
	  in_control && /^[[:space:]]*calculation[[:space:]]*=/ {
	    print "   calculation     = '\''nscf'\''"
	    calc_done=1
	    next
	  }
	  in_control && /^[[:space:]]*verbosity[[:space:]]*=/ {
	    print "   verbosity       = '\''high'\''"
	    verb_done=1
	    next
	  }
	  in_control && /^[[:space:]]*\// {
	    if (calc_done==0) print "   calculation     = '\''nscf'\''"
	    if (verb_done==0) print "   verbosity       = '\''high'\''"
	    in_control=0
	    print
	    next
	  }
	  /^[[:space:]]*&SYSTEM/ {in_system=1; print; next}
	  in_system && /^[[:space:]]*occupations[[:space:]]*=/ {
	    print "   occupations     = '\''tetrahedra'\''"
	    occ_done=1
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
	  in_system && /^[[:space:]]*(degauss|smearing)[[:space:]]*=/ {next}
	  in_system && /^[[:space:]]*\// {
	    if (occ_done==0) print "   occupations     = '\''tetrahedra'\''"
	    if (nosym_done==0) print "   nosym           = .true."
	    if (noinv_done==0) print "   noinv           = .true."
	    in_system=0
	    print
	    next
	  }
	  {print}
	' "$infile"
}

