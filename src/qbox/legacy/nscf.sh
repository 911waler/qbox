#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_scf2nscf_use_tetrahedra (){
	local infile="$1"
	awk '
	  BEGIN{calc_done=0; verb_done=0; has_automatic=0; has_methfessel=0}
	  {
	    line=$0
	    low=tolower(line)
	    if (calc_done==0 && low ~ /^[[:space:]]*calculation[[:space:]]*=.*/) {
	      line="   calculation     = '\''nscf'\''"
	      calc_done=1
	    }
	    low=tolower(line)
	    if (verb_done==0 && low ~ /^[[:space:]]*verbosity[[:space:]]*=.*/) {
	      line="   verbosity       = '\''high'\''"
	      verb_done=1
	    }
	    low=tolower(line)
	    if (low ~ /^[[:space:]]*k_points[[:space:]]+automatic/) has_automatic=1
	    if (low ~ /methfessel-paxton/) has_methfessel=1
	  }
	  END{print (has_automatic && !has_methfessel) ? 1 : 0}
	' "$infile"
}

function qe_render_scf_to_nscf (){
	local infile use_tetrahedra
	if [ "$#" -ge 3 ]; then
		infile="$2"
		use_tetrahedra="$3"
	else
		infile="$1"
		use_tetrahedra="$2"
	fi
	awk -v use_tetrahedra="$use_tetrahedra" '
	  BEGIN{calc_done=0; verb_done=0; in_system=0; occ_done=0; nosym_done=0; noinv_done=0}
	  function isnum(x){ return (x ~ /^[0-9]+$/) }
	  {
	    line=$0
	    low=tolower(line)
	    if (calc_done==0 && low ~ /^[[:space:]]*calculation[[:space:]]*=.*/ ) {
	      print "   calculation     = '\''nscf'\''"
	      calc_done=1
	      next
	    }
	    if (verb_done==0 && low ~ /^[[:space:]]*verbosity[[:space:]]*=.*/ ) {
	      print "   verbosity       = '\''high'\''"
	      verb_done=1
	      next
	    }

	    if (use_tetrahedra==1 && low ~ /^[[:space:]]*&system/) {
	      in_system=1
	      print line
	      next
	    }
	    if (use_tetrahedra==1 && in_system && low ~ /^[[:space:]]*occupations[[:space:]]*=/) {
	      print "   occupations     = '\''tetrahedra'\''"
	      occ_done=1
	      next
	    }
	    if (use_tetrahedra==1 && in_system && low ~ /^[[:space:]]*nosym[[:space:]]*=/) {
	      print "   nosym           = .true."
	      nosym_done=1
	      next
	    }
	    if (use_tetrahedra==1 && in_system && low ~ /^[[:space:]]*noinv[[:space:]]*=/) {
	      print "   noinv           = .true."
	      noinv_done=1
	      next
	    }
	    if (use_tetrahedra==1 && in_system && low ~ /^[[:space:]]*(degauss|smearing)[[:space:]]*=/) {
	      next
	    }
	    if (use_tetrahedra==1 && in_system && line ~ /^[[:space:]]*\//) {
	      if (occ_done==0) {
	        print "   occupations     = '\''tetrahedra'\''"
	        occ_done=1
	      }
	      if (nosym_done==0) print "   nosym           = .true."
	      if (noinv_done==0) print "   noinv           = .true."
	      in_system=0
	      print line
	      next
	    }

	    if (low ~ /^[[:space:]]*k_points[[:space:]]+automatic/) {
	      print line
	      getline meshline
	      while (meshline ~ /^[[:space:]]*$/) {
	        print meshline
	        if (!getline meshline) break
	      }
	      n1=""; n2=""; n3=""; rest=""
	      split(meshline, a, /[[:space:]]+/)
	      cnt=0
	      for (i=1;i<=length(a);i++) {
	        if (a[i] != "") {
	          if (isnum(a[i])) {
	            cnt++
	            if (cnt==1) n1=a[i]
	            else if (cnt==2) n2=a[i]
	            else if (cnt==3) n3=a[i]
	          } else {
	            break
	          }
	        }
	        if (cnt==3) {
	          rest=""
	          for (j=i+1;j<=length(a);j++) {
	            if (a[j] != "") rest = rest " " a[j]
	          }
	          break
	        }
	      }
	      if (n1 != "" && n2 != "" && n3 != "") {
	        printf "%d %d %d%s\n", n1*2, n2*2, n3*2, rest
	      } else {
	        print meshline
	      }
	      next
	    }
	    print line
	  }
	' "$infile"
}

function scf2nscf (){
	local infile outfile before_checksum after_checksum use_tetrahedra outfile_preexisting

	infile="$fname1"
	if [ -z "$infile" ] || { [ -z "${QBOX_TASK_ID:-}" ] && [ "$infile" == "30" ]; }; then
		echo
		echo ' 请输入需要转换的 .scf.in 文件。'
		read infile
	fi

	while [ -z "$infile" ]; do
		echo
		echo ' 请输入需要转换的 .scf.in 文件。'
		read infile
	done

	if [ ! -f "$infile" ]; then
		echo
		echo " 错误：未找到输入文件 '$infile'。"
		return 1
	fi

	outfile="${infile%.scf.in}.nscf.in"
	before_checksum=`cksum "$infile" | awk '{print $1 " " $2}'`
	outfile_preexisting=0
	[ -e "$outfile" ] && outfile_preexisting=1

	use_tetrahedra="$(qe_scf2nscf_use_tetrahedra "$infile")" || use_tetrahedra=0
	[ "$use_tetrahedra" = "1" ] || use_tetrahedra=0

	qe_atomic_rewrite "$outfile" qe_render_scf_to_nscf "$infile" "$use_tetrahedra" || return $?
	if [ "$outfile_preexisting" != "1" ]; then
		chmod --reference="$infile" "$outfile" 2>/dev/null || return 1
	fi

	qe_apply_odd_electron_smearing_to_input "$outfile" "0.01" "SCF 转 NSCF" || return 1

	local nscf_nelec nscf_recommended_nbnd
	nscf_nelec=`qe_read_number_of_electrons "${infile%.scf.in}.out" scf.out 2>/dev/null`
	if ! echo "$nscf_nelec" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
		nscf_nelec=`qe_estimate_nelec_from_pwin_file "$outfile"`
	fi
	if echo "$nscf_nelec" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
		nscf_recommended_nbnd=`qe_recommend_band_nbnd_from_nelec "$nscf_nelec"`
		qe_set_pw_nbnd_in_file "$outfile" "$nscf_recommended_nbnd"
		echo " 已根据电子数 ${nscf_nelec} 为 NSCF 设置推荐 nbnd = ${nscf_recommended_nbnd}。"
	else
		echo " 提示：当前 nscf 输入未设置 nbnd 时可能只包含价带；未能读取电子数，无法自动给出推荐值。"
	fi
	if grep -qi "^[[:space:]]*occupations[[:space:]]*=[[:space:]]*['\"]\?fixed" "$infile"; then
		echo " 提示：原 SCF 使用 occupations='fixed'；bands/nscf 不设置 nbnd 时可能只包含价带。"
	fi

	after_checksum=`cksum "$outfile" | awk '{print $1 " " $2}'`
	if [ "$before_checksum" != "$after_checksum" ]; then
		echo
		echo " 已生成 $outfile。"
	else
		echo
		echo " 已复制为 $outfile，但未发现可自动修改的内容。"
	fi
}

#read main functions
