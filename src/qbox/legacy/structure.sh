#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qbox_parse_relax_output (){
    local output_file="$1" context_file="$2" stage_dir staged_context status
    [ -r "$output_file" ] && [ -f "$output_file" ] && [ -n "$context_file" ] || return 2
    qbox_postprocess_stage_dir "$context_file" context stage_dir || return $?
    staged_context="$stage_dir/context.txt"
    awk '
        function is_number(value) {
            return value ~ /^[+-]?(([0-9]+(\.[0-9]*)?)|(\.[0-9]+))([EeDd][+-]?[0-9]+)?$/
        }
        function unit_from_header(line, fields, count) {
            line=tolower(line)
            sub(/^[[:space:]]*/, "", line)
            sub(/^[^[:space:]]+[[:space:]]*/, "", line)
            gsub(/[()]/, "", line)
            count=split(line, fields)
            return count ? fields[1] : ""
        }
        function value_after_equals(line, fields, count, i) {
            gsub(/[=,]/, " ", line)
            count=split(line, fields)
            for (i=1; i<count; i++) if (fields[i] == "=" || fields[i] == "") ;
            return fields[count]
        }
        /[Bb]ravais-lattice[[:space:]]+index/ {
            for (i=1; i<=NF; i++) if ($i == "=" && (i+1)<=NF) ibrav=$(i+1)
            next
        }
        /number of atoms\/cell/ {
            for (i=1; i<=NF; i++) if ($i == "=" && (i+1)<=NF) nat=$(i+1)
            next
        }
        /JOB DONE/ { normal_exit="YES"; next }
        toupper($1) == "CELL_PARAMETERS" {
            candidate_unit=unit_from_header($0)
            delete candidate_cell
            candidate_count=0
            for (i=1; i<=3 && (getline row)>0; i++) {
                split(row, fields)
                if (length(fields)<3 || !is_number(fields[1]) || !is_number(fields[2]) || !is_number(fields[3])) break
                candidate_count++
                candidate_cell[candidate_count]=fields[1] "\t" fields[2] "\t" fields[3]
            }
            if (candidate_count == 3 && candidate_unit != "") {
                cell_unit=candidate_unit
                for (i=1; i<=3; i++) cell[i]=candidate_cell[i]
                cell_complete=1
            }
            next
        }
        toupper($1) == "ATOMIC_POSITIONS" {
            candidate_atom_unit=unit_from_header($0)
            delete candidate_atom
            candidate_count=0
            candidate_valid=(nat ~ /^[1-9][0-9]*$/ && (candidate_atom_unit == "angstrom" || candidate_atom_unit == "crystal"))
            for (i=1; candidate_valid && i<=nat && (getline row)>0; i++) {
                if (row ~ /JOB DONE/) normal_exit="YES"
                split(row, fields)
                if (length(fields)<4 || fields[1] !~ /^[A-Za-z][A-Za-z0-9_]*$/ || !is_number(fields[2]) || !is_number(fields[3]) || !is_number(fields[4])) { candidate_valid=0; break }
                candidate_count++
                candidate_atom[candidate_count]=fields[1] "\t" fields[2] "\t" fields[3] "\t" fields[4]
            }
            if (candidate_valid && candidate_count == nat) {
                atom_unit=candidate_atom_unit
                for (i=1; i<=nat; i++) atom[i]=candidate_atom[i]
                atom_complete=1
            }
            next
        }
        END {
            if (ibrav != "0" || nat !~ /^[1-9][0-9]*$/ || !cell_complete || !atom_complete || (atom_unit != "angstrom" && atom_unit != "crystal")) exit 1
            print "source_kind\trelax_output"
            print "ibrav\t0"
            print "normal_exit\t" (normal_exit == "YES" ? "YES" : "NO")
            print "nat\t" nat
            print "cell_unit\t" cell_unit
            print "atom_unit\t" atom_unit
            for (i=1; i<=3; i++) print "cell_row\t" i "\t" cell[i]
            for (i=1; i<=nat; i++) print "atom\t" i "\t" atom[i]
        }
    ' "$output_file" >"$staged_context"
    status=$?
    if [ "$status" -eq 0 ]; then
        qbox_postprocess_install_output "$staged_context" "$context_file"
        status=$?
    fi
    qbox_postprocess_remove_stage "$stage_dir" || [ "$status" -ne 0 ] || status=$?
    return "$status"
}

function qbox_parse_pw_input (){
    local input_file="$1" context_file="$2" stage_dir staged_context status
    [ -r "$input_file" ] && [ -f "$input_file" ] && [ -n "$context_file" ] || return 2
    qbox_postprocess_stage_dir "$context_file" context stage_dir || return $?
    staged_context="$stage_dir/context.txt"
    awk '
        function is_number(value) {
            return value ~ /^[+-]?(([0-9]+(\.[0-9]*)?)|(\.[0-9]+))([EeDd][+-]?[0-9]+)?$/
        }
        function header_unit(line, fields, count) {
            line=tolower(line)
            sub(/^[[:space:]]*/, "", line)
            sub(/^[^[:space:]]+[[:space:]]*/, "", line)
            gsub(/[()]/, "", line)
            count=split(line, fields)
            return count ? fields[1] : ""
        }
        {
            lower=tolower($0)
            if (lower ~ /^[[:space:]]*&control([[:space:]]|$)/) control=1
            line=lower
            gsub(/[=,]/, " ", line)
            count=split(line, values)
            for (i=1; i<count; i++) {
                if (values[i] == "ibrav") ibrav=values[i+1]
                if (values[i] == "nat") nat=values[i+1]
            }
        }
        toupper($1) == "CELL_PARAMETERS" {
            candidate_unit=header_unit($0)
            delete candidate_cell
            candidate_count=0
            for (i=1; i<=3 && (getline row)>0; i++) {
                split(row, fields)
                if (length(fields)<3 || !is_number(fields[1]) || !is_number(fields[2]) || !is_number(fields[3])) break
                candidate_count++
                candidate_cell[candidate_count]=fields[1] "\t" fields[2] "\t" fields[3]
            }
            if (candidate_count == 3 && candidate_unit != "") {
                cell_unit=candidate_unit
                for (i=1; i<=3; i++) cell[i]=candidate_cell[i]
                cell_complete=1
            }
            next
        }
        toupper($1) == "ATOMIC_POSITIONS" {
            candidate_atom_unit=header_unit($0)
            delete candidate_atom
            candidate_count=0
            candidate_valid=(nat ~ /^[1-9][0-9]*$/ && (candidate_atom_unit == "angstrom" || candidate_atom_unit == "crystal"))
            for (i=1; candidate_valid && i<=nat && (getline row)>0; i++) {
                split(row, fields)
                if (length(fields)<4 || fields[1] !~ /^[A-Za-z][A-Za-z0-9_]*$/ || !is_number(fields[2]) || !is_number(fields[3]) || !is_number(fields[4])) { candidate_valid=0; break }
                candidate_count++
                candidate_atom[candidate_count]=fields[1] "\t" fields[2] "\t" fields[3] "\t" fields[4]
            }
            if (candidate_valid && candidate_count == nat) {
                atom_unit=candidate_atom_unit
                for (i=1; i<=nat; i++) atom[i]=candidate_atom[i]
                atom_complete=1
            }
            next
        }
        END {
            if (!control || ibrav != "0" || nat !~ /^[1-9][0-9]*$/ || !cell_complete || !atom_complete || (atom_unit != "angstrom" && atom_unit != "crystal")) exit 1
            print "source_kind\tpw_input"
            print "ibrav\t0"
            print "normal_exit\tNO"
            print "nat\t" nat
            print "cell_unit\t" cell_unit
            print "atom_unit\t" atom_unit
            for (i=1; i<=3; i++) print "cell_row\t" i "\t" cell[i]
            for (i=1; i<=nat; i++) print "atom\t" i "\t" atom[i]
        }
    ' "$input_file" >"$staged_context"
    status=$?
    if [ "$status" -eq 0 ]; then
        qbox_postprocess_install_output "$staged_context" "$context_file"
        status=$?
    fi
    qbox_postprocess_remove_stage "$stage_dir" || [ "$status" -ne 0 ] || status=$?
    return "$status"
}

function qbox_write_gjf (){
    local context_file="$1" output_file="$2" stage_dir staged_output status
    [ -r "$context_file" ] && [ -f "$context_file" ] && [ -n "$output_file" ] || return 2
    qbox_postprocess_stage_dir "$output_file" gjf stage_dir || return $?
    staged_output="$stage_dir/structure.gjf"
    awk -F '\t' '
        $1 == "nat" {nat=$2; next}
        $1 == "cell_row" {cell[$2]=$3 "\t" $4 "\t" $5; next}
        $1 == "atom" {atom_n++; atom[atom_n]=$3 "\t" $4 "\t" $5 "\t" $6; next}
        END {
            if (nat !~ /^[1-9][0-9]*$/ || atom_n != nat || !(1 in cell) || !(2 in cell) || !(3 in cell)) exit 1
            print "%mem=10gb"
            print "%nproc=10"
            print "#P B3LYP/6-31G*"
            print ""
            print "Generated by qbox"
            print ""
            print "0 1"
            for (i=1; i<=nat; i++) {
                split(atom[i], a, "\t")
                printf "%s\t%.9f\t%.9f\t%.9f\n", a[1], a[2], a[3], a[4]
            }
            for (i=1; i<=3; i++) {
                split(cell[i], c, "\t")
                printf "TV\t%.9f\t%.9f\t%.9f\n", c[1], c[2], c[3]
            }
            print ""
            print ""
        }
    ' "$context_file" >"$staged_output"
    status=$?
    if [ "$status" -eq 0 ]; then
        qbox_postprocess_install_output "$staged_output" "$output_file"
        status=$?
    fi
    qbox_postprocess_remove_stage "$stage_dir" || [ "$status" -ne 0 ] || status=$?
    return "$status"
}

function qbox_convert_gjf_to_cif (){
    local gjf_file="$1" cif_file="$2" stage_dir staged_output status cleanup_status
    [ -r "$gjf_file" ] && [ -f "$gjf_file" ] && [ -n "$cif_file" ] || return 2
    qbox_postprocess_prepare_output "$cif_file" || return $?
    require_multiwfn || return 1
    qbox_postprocess_stage_dir "$cif_file" cif stage_dir || return $?
    staged_output="$stage_dir/structure.cif"
    qbox_multiwfn "$gjf_file" <<EOF_MW
100
2
33
$staged_output
0
q
EOF_MW
    status=$?
    if [ "$status" -eq 0 ] && { [ ! -f "$staged_output" ] || [ -L "$staged_output" ] || [ ! -s "$staged_output" ]; }; then
        echo ' 错误：Multiwfn 未产生有效的 CIF 输出。' >&2
        status=1
    fi
    if [ "$status" -eq 0 ]; then
        qbox_postprocess_install_output "$staged_output" "$cif_file"
        status=$?
    fi
    qbox_postprocess_remove_stage "$stage_dir"
    cleanup_status=$?
    if [ "$status" -eq 0 ] && [ "$cleanup_status" -ne 0 ]; then
        status="$cleanup_status"
    fi
    return "$status"
}

function qbox_convert_md_to_xyz (){
    local md_output="$1" xyz_output="$2" stage_dir staged_output status
    [ -r "$md_output" ] && [ -f "$md_output" ] && [ -n "$xyz_output" ] || return 2
    qbox_postprocess_stage_dir "$xyz_output" xyz stage_dir || return $?
    staged_output="$stage_dir/trajectory.xyz"
    awk -v xyzout="$staged_output" '
        function unit_from_header(header) {
            header=tolower(header)
            if (index(header, "angstrom")) return "angstrom"
            if (index(header, "crystal")) return "crystal"
            if (index(header, "bohr")) return "bohr"
            if (index(header, "alat")) return "alat"
            return "unknown"
        }
        /number of atoms\/cell/ {nat=$NF; next}
        /Entering Dynamics:[[:space:]]+iteration[[:space:]]*=/ {
            step=$NF
            if (getline > 0 && $0 ~ /time[[:space:]]*=/) time=$3
            next
        }
        tolower($0) ~ /^[[:space:]]*atomic_positions/ {
            unit=unit_from_header($0)
            count=0
            valid=(nat ~ /^[1-9][0-9]*$/)
            delete atom
            while (valid && count < nat && (getline row) > 0) {
                if (row !~ /[^[:space:]]/) continue
                n=split(row, fields)
                if (n < 4 || fields[2] !~ /^[+-]?[0-9.]/ || fields[3] !~ /^[+-]?[0-9.]/ || fields[4] !~ /^[+-]?[0-9.]/) {valid=0; break}
                count++
                atom[count]=sprintf("%-2s %16.8f %16.8f %16.8f", fields[1], fields[2], fields[3], fields[4])
            }
            if (valid && count == nat) {
                print nat >> xyzout
                if (step != "") printf "Step %d, QE iteration = %s, time = %s ps, ATOMIC_POSITIONS unit = %s\n", frame, step, time, unit >> xyzout
                else printf "Step %d, ATOMIC_POSITIONS unit = %s\n", frame, unit >> xyzout
                for (i=1; i<=nat; i++) print atom[i] >> xyzout
                frame++
            }
            next
        }
        END { close(xyzout); exit (frame > 0 ? 0 : 1) }
    ' "$md_output"
    status=$?
    if [ "$status" -eq 0 ]; then
        qbox_postprocess_install_output "$staged_output" "$xyz_output"
        status=$?
    fi
    qbox_postprocess_remove_stage "$stage_dir" || [ "$status" -ne 0 ] || status=$?
    return "$status"
}

function qbox_postprocess_relax () { qbox_parse_relax_output "$1" "$2"; }
function qbox_postprocess_gjf () { qbox_write_gjf "$1" "$2"; }
function qbox_postprocess_cif () { qbox_convert_gjf_to_cif "$1" "$2"; }
function qbox_postprocess_xyz () { qbox_convert_md_to_xyz "$1" "$2"; }

function qbox_render_nscf_input (){
    local input_file="$1" context_file="$2"
    [ -f "$input_file" ] && [ -r "$context_file" ] || return 1
    awk -v context_file="$context_file" '
        function is_number(value) {
            return value ~ /^[+-]?(([0-9]+(\.[0-9]*)?)|(\.[0-9]+))([EeDd][+-]?[0-9]+)?$/
        }
        function complete_block(start, kind, j, count, expected, fields, field_count) {
            expected=(kind == "cell" ? 3 : nat)
            j=start+1
            count=0
            while (j <= line_count && count < expected) {
                if (lines[j] ~ /^[[:space:]]*$/) {
                    j++
                    continue
                }
                field_count=split(lines[j], fields)
                if (kind == "cell") {
                    if (field_count < 3 || !is_number(fields[1]) || !is_number(fields[2]) || !is_number(fields[3])) return 0
                } else if (field_count < 4 || !is_number(fields[2]) || !is_number(fields[3]) || !is_number(fields[4])) {
                    return 0
                }
                count++
                j++
            }
            return count == expected ? j-1 : 0
        }
        BEGIN {
            while ((getline context_line < context_file) > 0) {
                field_count=split(context_line, fields, "\t")
                if (fields[1] == "nat") {
                    nat=fields[2]
                } else if (fields[1] == "cell_row" && field_count >= 5) {
                    cell_x[fields[2]]=fields[3]
                    cell_y[fields[2]]=fields[4]
                    cell_z[fields[2]]=fields[5]
                } else if (fields[1] == "atom_unit" && field_count >= 2) {
                    atom_unit=fields[2]
                } else if (fields[1] == "atom" && field_count >= 6) {
                    atom_symbol[fields[2]]=fields[3]
                    atom_x[fields[2]]=fields[4]
                    atom_y[fields[2]]=fields[5]
                    atom_z[fields[2]]=fields[6]
                }
            }
            close(context_file)
        }
        { lines[NR]=$0; line_count=NR }
        END {
            if (nat !~ /^[1-9][0-9]*$/ || (atom_unit != "angstrom" && atom_unit != "crystal")) exit 1
            for (i=1; i<=3; i++) {
                if (!(i in cell_x) || !(i in cell_y) || !(i in cell_z)) exit 1
            }
            for (i=1; i<=nat; i++) {
                if (!(i in atom_symbol) || !(i in atom_x) || !(i in atom_y) || !(i in atom_z)) exit 1
            }

            in_control=0
            in_system=0
            for (i=1; i<=line_count; i++) {
                lower=tolower(lines[i])
                if (lower ~ /^[[:space:]]*&control([[:space:]]|$)/) in_control=1
                if (lower ~ /^[[:space:]]*&system([[:space:]]|$)/) in_system=1
                if (in_control && lower ~ /^[[:space:]]*calculation[[:space:]]*=/) calculation_line=i
                if (lower ~ /^[[:space:]]*nstep[[:space:]]*=/) remove_line[i]=1
                if (in_system) {
                    normalized=lower
                    gsub(/[=,]/, " ", normalized)
                    field_count=split(normalized, fields)
                    for (j=1; j<field_count; j++) if (fields[j] == "nat") input_nat=fields[j+1]
                }
                if (lower ~ /^[[:space:]]*cell_parameters([[:space:]]|$)/) {
                    block_end=complete_block(i, "cell")
                    if (block_end) {
                        cell_start=i
                        cell_end=block_end
                    }
                }
                if (lower ~ /^[[:space:]]*atomic_positions([[:space:]]|$)/) {
                    block_end=complete_block(i, "atom")
                    if (block_end) {
                        atom_start=i
                        atom_end=block_end
                    }
                }
                if (in_control && lower ~ /^[[:space:]]*\/[[:space:]]*$/) {
                    control_end=i
                    if (calculation_line == 0) calculation_insert=i
                    in_control=0
                }
                if (in_system && lower ~ /^[[:space:]]*\/[[:space:]]*$/) in_system=0
            }

            if (input_nat != nat || control_end == 0 || cell_start == 0 || atom_start == 0) exit 1
            for (i=1; i<=line_count; i++) {
                if (i == cell_start) {
                    print lines[i]
                    for (j=1; j<=3; j++) printf "   %.9f    %.9f    %.9f\n", cell_x[j], cell_y[j], cell_z[j]
                    i=cell_end
                    continue
                }
                if (i == atom_start) {
                    printf " ATOMIC_POSITIONS %s\n", atom_unit
                    for (j=1; j<=nat; j++) printf "   %s      %.9f    %.9f    %.9f\n", atom_symbol[j], atom_x[j], atom_y[j], atom_z[j]
                    i=atom_end
                    continue
                }
                if (i in remove_line) continue
                if (i == calculation_line) {
                    printf "   calculation     = %cnscf%c\n", 39, 39
                    continue
                }
                if (i == calculation_insert) printf "   calculation     = %cnscf%c\n", 39, 39
                print lines[i]
            }
        }
    ' "$input_file"
}

function qbox_build_nscf_input (){
    local relax_input="${1-}" relax_output="${2-}" nscf_output="${3-}"
    local stage_dir staged_input rendered_input input_context relax_context status cleanup_status
    local nscf_nelec nscf_recommended_nbnd
    [ -r "$relax_input" ] && [ -f "$relax_input" ] || return 2
    [ -r "$relax_output" ] && [ -f "$relax_output" ] || return 2
    [ -n "$nscf_output" ] || return 2
    qbox_postprocess_prepare_output "$nscf_output" || return $?
    qbox_postprocess_stage_dir "$nscf_output" nscf stage_dir || return $?
    staged_input="$stage_dir/nscf.in"
    rendered_input="$stage_dir/nscf.rendered"
    input_context="$stage_dir/input.context"
    relax_context="$stage_dir/relax.context"
    status=0

    cp -- "$relax_input" "$staged_input"
    status=$?
    if [ "$status" -eq 0 ]; then
        qbox_parse_pw_input "$relax_input" "$input_context"
        status=$?
    fi
    if [ "$status" -eq 0 ]; then
        qbox_parse_relax_output "$relax_output" "$relax_context"
        status=$?
    fi
    if [ "$status" -eq 0 ]; then
        qbox_render_nscf_input "$staged_input" "$relax_context" >"$rendered_input"
        status=$?
        if [ "$status" -eq 0 ]; then
            mv -f -- "$rendered_input" "$staged_input"
            status=$?
        fi
    fi

    if [ "$status" -eq 0 ]; then
        nscf_nelec="$(qe_read_number_of_electrons "$relax_output" 2>/dev/null)"
        if ! printf '%s\n' "$nscf_nelec" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
            nscf_nelec="$(qe_estimate_nelec_from_pwin_file "$staged_input" 2>/dev/null)"
        fi
        if printf '%s\n' "$nscf_nelec" | awk 'NF==1 && $1 ~ /^[-+]?[0-9]*\.?[0-9]+$/ && $1 > 0 {exit 0} {exit 1}'; then
            nscf_recommended_nbnd="$(qe_recommend_band_nbnd_from_nelec "$nscf_nelec")"
            qe_set_pw_nbnd_in_file "$staged_input" "$nscf_recommended_nbnd"
            status=$?
            if [ "$status" -eq 0 ]; then
                echo " 已根据电子数 ${nscf_nelec} 为 NSCF 设置推荐 nbnd = ${nscf_recommended_nbnd}。"
            fi
        else
            echo ' 提示：当前 nscf 输入未设置 nbnd 时可能只包含价带；未能读取电子数，无法自动给出推荐值。'
        fi
    fi
    if [ "$status" -eq 0 ]; then
        qe_apply_odd_electron_smearing_to_input "$staged_input" "0.01" "relax/vc-relax 转 NSCF"
        status=$?
    fi
    if [ "$status" -eq 0 ] && grep -qi "^[[:space:]]*occupations[[:space:]]*=[[:space:]]*['\"]\?fixed" "$staged_input"; then
        echo " 提示：当前 NSCF 使用 occupations='fixed'；bands/nscf 不设置 nbnd 时可能只包含价带。"
    fi
    if [ "$status" -eq 0 ]; then
        qbox_postprocess_install_output "$staged_input" "$nscf_output"
        status=$?
    fi

    qbox_postprocess_remove_stage "$stage_dir"
    cleanup_status=$?
    if [ "$status" -eq 0 ] && [ "$cleanup_status" -ne 0 ]; then
        status="$cleanup_status"
    fi
    return "$status"
}

function qbox_postprocess_nscf () { qbox_build_nscf_input "$1" "$2" "$3"; }

function qbox_render_fixed_atoms (){
    local input_file="$1" position_line="$2" nat="$3" if_pos="$4" index_file="$5"
    awk -v position_line="$position_line" -v nat="$nat" -v if_pos="$if_pos" -v index_file="$index_file" '
        BEGIN {
            while ((getline idx < index_file) > 0) selected[idx+0]=1
            close(index_file)
        }
        {
            if (NR <= position_line) {
                print
                next
            }
            if (atom_count < nat) {
                if ($0 ~ /^[[:space:]]*$/) {
                    print
                    next
                }
                atom_count++
                if (atom_count in selected) {
                    line=$0
                    sub(/([[:space:]]+[01][[:space:]]+[01][[:space:]]+[01])+[[:space:]]*$/, "", line)
                    print line "    " if_pos
                } else {
                    print
                }
                next
            }
            print
        }
        END { exit (atom_count == nat ? 0 : 1) }
    ' "$input_file"
}

function qbox_apply_constraints (){
    local input_file="${1-}" atom_spec="${2-}" if_pos="${3-}" output_file="${4-}"
    local nat position_line indices stage_dir staged_output status cleanup_status max_index
    [ -r "$input_file" ] && [ -f "$input_file" ] || return 2
    [ -n "$output_file" ] || return 2
    qbox_postprocess_prepare_output "$output_file" || return $?
    if ! printf '%s\n' "$if_pos" | awk 'NF==3 && $1 ~ /^[01]$/ && $2 ~ /^[01]$/ && $3 ~ /^[01]$/ {exit 0} {exit 1}'; then
        return 2
    fi
    nat="$(awk '
        {
            lower=tolower($0)
            if (lower ~ /^[[:space:]]*&system([[:space:]]|$)/) in_system=1
            if (in_system) {
                normalized=lower
                gsub(/[=,]/, " ", normalized)
                field_count=split(normalized, fields)
                for (i=1; i<field_count; i++) if (fields[i] == "nat") {
                    print fields[i+1]
                    exit
                }
            }
            if (in_system && lower ~ /^[[:space:]]*\/[[:space:]]*$/) in_system=0
        }
    ' "$input_file")"
    printf '%s\n' "$nat" | awk 'NF==1 && $1 ~ /^[1-9][0-9]*$/ {exit 0} {exit 1}' || return 1
    position_line="$(awk 'tolower($0) ~ /^[[:space:]]*atomic_positions([[:space:]]|$)/ {print NR; exit}' "$input_file")"
    [ -n "$position_line" ] || return 1
    if ! awk -v position_line="$position_line" -v nat="$nat" '
        BEGIN {valid=1}
        NR <= position_line {next}
        {
            if (atom_count >= nat) next
            if ($0 ~ /^[[:space:]]*$/) next
            field_count=split($0, fields)
            if (field_count < 4 || fields[2] !~ /^[+-]?(([0-9]+(\.[0-9]*)?)|(\.[0-9]+))([EeDd][+-]?[0-9]+)?$/ || fields[3] !~ /^[+-]?(([0-9]+(\.[0-9]*)?)|(\.[0-9]+))([EeDd][+-]?[0-9]+)?$/ || fields[4] !~ /^[+-]?(([0-9]+(\.[0-9]*)?)|(\.[0-9]+))([EeDd][+-]?[0-9]+)?$/) valid=0
            atom_count++
        }
        END {exit !(valid && atom_count == nat)}
    ' "$input_file"; then
        return 1
    fi
    indices="$(qbox_expand_index_spec "$atom_spec")" || return 1
    [ -n "$indices" ] || return 1
    max_index="$(printf '%s\n' "$indices" | awk 'BEGIN{max=0} $1 > max {max=$1} END{if(max>0) print max; else exit 1}')" || return 1
    [ "$max_index" -le "$nat" ] || return 1

    qbox_postprocess_stage_dir "$output_file" constraints stage_dir || return $?
    staged_output="$stage_dir/constraints.in"
    printf '%s\n' "$indices" >"$stage_dir/indices"
    qbox_render_fixed_atoms "$input_file" "$position_line" "$nat" "$if_pos" "$stage_dir/indices" >"$staged_output"
    status=$?
    if [ "$status" -eq 0 ]; then
        qbox_postprocess_install_output "$staged_output" "$output_file"
        status=$?
    fi
    qbox_postprocess_remove_stage "$stage_dir"
    cleanup_status=$?
    if [ "$status" -eq 0 ] && [ "$cleanup_status" -ne 0 ]; then
        status="$cleanup_status"
    fi
    return "$status"
}

function qbox_postprocess_constraints () { qbox_apply_constraints "$1" "$2" "$3" "$4"; }

function qbox_write_md_gjf (){
    local md_file="$1" output_file="$2" nat="$3" cell_header_line="$4" cell_start="$5" cell_end="$6" atom_start="$7" atom_end="$8" alat="$9"
    [ -r "$md_file" ] && [ -f "$md_file" ] && [ -n "$output_file" ] || return 2
    awk -v nat="$nat" -v cell_header_line="$cell_header_line" -v cell_start="$cell_start" -v cell_end="$cell_end" -v atom_start="$atom_start" -v atom_end="$atom_end" -v alat="$alat" '
        function is_number(value) {
            return value ~ /^[+-]?(([0-9]+(\.[0-9]*)?)|(\.[0-9]+))([EeDd][+-]?[0-9]+)?$/
        }
        BEGIN {
            valid=1
            if (nat !~ /^[1-9][0-9]*$/ || atom_start !~ /^[1-9][0-9]*$/ || atom_end < atom_start) valid=0
            if (cell_header_line != "") {
                cell_mode="parameters"
                if (cell_start !~ /^[1-9][0-9]*$/ || cell_end < cell_start) valid=0
            } else {
                cell_mode="axes"
                if (!is_number(alat) || alat <= 0 || cell_start !~ /^[1-9][0-9]*$/ || cell_end < cell_start) valid=0
            }
        }
        NR == cell_header_line {
            header=$0
            sub(/^[[:space:]]*/, "", header)
            header_count=split(header, header_fields)
            unit=tolower(header_fields[2])
            gsub(/[(){}]/, "", unit)
            if (unit == "") valid=0
        }
        NR >= cell_start && NR <= cell_end {
            if (cell_mode == "parameters") {
                if (NF < 3 || !is_number($1) || !is_number($2) || !is_number($3)) valid=0
                else {
                    cell_count++
                    cell_x[cell_count]=$1
                    cell_y[cell_count]=$2
                    cell_z[cell_count]=$3
                }
            } else {
                if (NF < 6 || !is_number($4) || !is_number($5) || !is_number($6)) valid=0
                else {
                    cell_count++
                    cell_x[cell_count]=$4 * alat * 0.5291772
                    cell_y[cell_count]=$5 * alat * 0.5291772
                    cell_z[cell_count]=$6 * alat * 0.5291772
                }
            }
        }
        NR >= atom_start && NR <= atom_end {
            if (NF < 4 || $1 !~ /^[A-Za-z][A-Za-z0-9_]*$/ || !is_number($2) || !is_number($3) || !is_number($4)) valid=0
            else {
                atom_count++
                atom_symbol[atom_count]=$1
                atom_x[atom_count]=$2
                atom_y[atom_count]=$3
                atom_z[atom_count]=$4
            }
        }
        END {
            if (!valid || cell_count != 3 || atom_count != nat) exit 1
            print "%mem=10gb"
            print "%nproc=10"
            print "#P B3LYP/6-31G*"
            print ""
            print "Generated by qbox"
            print ""
            print "0 1"
            for (i=1; i<=nat; i++) printf "%s\t%.9f\t%.9f\t%.9f\n", atom_symbol[i], atom_x[i], atom_y[i], atom_z[i]
            for (i=1; i<=3; i++) printf "TV\t%.9f\t%.9f\t%.9f\n", cell_x[i], cell_y[i], cell_z[i]
            print ""
            print ""
        }
    ' "$md_file" >"$output_file"
}
function md2cif_extract_target (){
    local md_file md_mode md_target md_ibrav natm md_base md_info md_step md_time md_atm_line md_dt_fs md_outprefix
    local begatmpos endatmpos cellinfo begcellpos endcellpos alat stage_dir gjf_file cif_file status cleanup_status
	md_file="$1"
	md_mode="$2"
	md_target="$3"

	md_ibrav=`grep 'bravais-lattice' "$md_file" | awk '{print $4}' | head -1`
	natm=`grep 'number of atoms/cell' "$md_file" | head -1 | awk '{print $5}'`

	if [ "$md_ibrav" != "0" ]; then
		echo ' 输入/输出文件不受支持：此脚本仅支持 ibrav=0。'
		return 1
	fi

	if [ -z "$natm" ]; then
		echo ' 未能在 MD 输出文件中读取有效的原子数。'
		return 1
	fi

	if [ "$md_mode" == "1" ]; then
		md_info=`awk -v target="$md_target" '
			/Entering Dynamics:[[:space:]]+iteration[[:space:]]*=/ {
				step=$NF
				getline
				time=$3
				if(step==target){
					while(getline){
						if($0 ~ /^ATOMIC_POSITIONS/){
							print step, time, NR+1
							exit
						}
						if($0 ~ /Entering Dynamics:[[:space:]]+iteration[[:space:]]*=/) exit
					}
				}
			}
		' "$md_file"`
	else
		md_info=`awk -v target="$md_target" '
			/Entering Dynamics:[[:space:]]+iteration[[:space:]]*=/ {
				step=$NF
				getline
				time=$3
				d=time-target
				if(d<0) d=-d
				if(best=="" || d<best){
					best=d
					best_step=step
					best_time=time
					while(getline){
						if($0 ~ /^ATOMIC_POSITIONS/){
							best_line=NR+1
							break
						}
						if($0 ~ /Entering Dynamics:[[:space:]]+iteration[[:space:]]*=/) break
					}
				}
			}
			END{
				if(best_line!="") print best_step, best_time, best_line
			}
		' "$md_file"`
	fi

	if [ -z "$md_info" ]; then
		echo ' 未在输出文件中找到匹配的 MD ATOMIC_POSITIONS 结构块。'
		return 1
	fi

	md_step=`echo "$md_info" | awk '{print $1}'`
	md_time=`echo "$md_info" | awk '{print $2}'`
	md_atm_line=`echo "$md_info" | awk '{print $3}'`
	begatmpos="$md_atm_line"
	endatmpos=$((${begatmpos} + ${natm} -1))

	cellinfo=`awk -v limit="$((${begatmpos}-1))" 'NR<limit && /CELL_PARAMETERS/{found=NR} END{if(found!="") print found}' "$md_file"`
	if [ -n "${cellinfo}" ]; then
		begcellpos=$((${cellinfo} + 1))
		endcellpos=$((${begcellpos}+2))
	else
		alat=`grep 'lattice parameter (alat)' "$md_file" | awk '{print $5}' | head -1`
		begcellpos=`grep -n 'crystal axes' "$md_file" | awk -F : '{print $1 + 1}' | head -1`
		endcellpos=$((${begcellpos}+2))
	fi

	if [ -z "$begcellpos" ] || [ -z "$alat" -a -z "$cellinfo" ]; then
		echo ' 未能在 MD 输出文件中读取有效的晶胞信息。'
		return 1
	fi

	md_dt_fs=`grep 'Time step' "$md_file" | tail -1 | awk -F',' '{for(i=1;i<=NF;i++){if($i ~ /femto-seconds/){for(j=1;j<=split($i,a," ");j++){if(a[j] ~ /^[+-]?[0-9.]+([eE][+-]?[0-9]+)?$/){print a[j]; exit}}}}}'`
	if [ -z "$md_dt_fs" ]; then
		md_dt_fs=`grep -m 1 '^[[:space:]]*dt[[:space:]]*=' "$md_file" | awk -F= '{gsub(/[ ,]/,"",$2); print $2}' | awk '{printf "%.8f", $1*0.04837768653}'`
	fi

	md_base=`basename "$md_file"`
	md_base="${md_base%.*}"
	if [ "$md_mode" == "1" ]; then
		md_outprefix="${md_base}_step_${md_step}"
	else
		md_outprefix="${md_base}_ps_${md_time}"
	fi

	cif_file="${md_outprefix}.cif"
	qbox_postprocess_stage_dir "$cif_file" md-context stage_dir || return $?
	gjf_file="$stage_dir/structure.gjf"

	echo
	echo " 匹配到的 MD 步数：${md_step}"
	echo " 匹配到的 MD 时间：${md_time} ps"
	if [ -n "$md_dt_fs" ]; then
		echo " 输出/输入文件中的时间步长：${md_dt_fs} fs = `awk -v dt="$md_dt_fs" 'BEGIN{printf "%.8f", dt/1000.0}'` ps"
	fi
	echo " 输出 CIF 文件：${cif_file}"

	status=0
	qbox_write_md_gjf "$md_file" "$gjf_file" "$natm" "$cellinfo" "$begcellpos" "$endcellpos" "$begatmpos" "$endatmpos" "$alat"
	status=$?
	if [ "$status" -eq 0 ]; then
		qbox_postprocess_cif "$gjf_file" "$cif_file"
		status=$?
	fi
	qbox_postprocess_remove_stage "$stage_dir"
	cleanup_status=$?
	if [ "$status" -eq 0 ] && [ "$cleanup_status" -ne 0 ]; then
		status="$cleanup_status"
	fi
	return "$status"
}

function md2cif_read_mode (){
	local md_mode
	echo
	echo ' 请选择 MD 结构提取方式：'
	echo '  1) 按 MD 步数 / iteration 提取'
	echo '  2) 按时间提取，单位 ps'
	read md_mode
	while [ "$md_mode" != "1" ] && [ "$md_mode" != "2" ]
	do
		echo "请输入 1 或 2。"
		read md_mode
	done
	md2cif_selected_mode="$md_mode"
}

function md2cif (){
	if [ -z "$fname1" ]; then
		echo " 请输入 QE 分子动力学输出文件名。"
		read fname1
		while [ -z "$fname1" ]
		do
			echo " 请输入 QE 分子动力学输出文件名。"
			read fname1
		done
	fi

	if [ ! -f "$fname1" ]; then
		echo " 错误：未找到输出文件 '$fname1'。"
		exit 1
	fi

	local md_scope md_mode md_target md_start md_end md_interval md_current md2cif_selected_mode
	echo
	echo ' 请选择 MD CIF 提取范围：'
	echo '  1) 提取单个时间点/步数'
	echo '  2) 连续提取多个时间点/步数'
	read md_scope
	while [ "$md_scope" != "1" ] && [ "$md_scope" != "2" ]
	do
		echo "请输入 1 或 2。"
		read md_scope
	done

	md2cif_read_mode
	md_mode="$md2cif_selected_mode"

	if [ "$md_scope" == "1" ]; then
		if [ "$md_mode" == "1" ]; then
			echo ' 请输入 MD 步数 / iteration，例如 1000'
			read md_target
			while ! echo "$md_target" | awk 'BEGIN{ok=0} /^[0-9]+$/{if($1>0) ok=1} END{exit !ok}'; do
				echo ' 无效步数。请输入正整数。'
				read md_target
			done
		else
			echo ' 请输入 MD 时间，单位 ps，例如 1.5'
			read md_target
			while ! echo "$md_target" | awk '{exit !($1>=0)}'; do
				echo ' 无效时间。请输入非负数，单位 ps。'
				read md_target
			done
		fi
		md2cif_extract_target "$fname1" "$md_mode" "$md_target"
	else
		if [ "$md_mode" == "1" ]; then
			echo ' 请输入开始步数 / iteration，例如 100'
			read md_start
			while ! echo "$md_start" | awk 'BEGIN{ok=0} /^[0-9]+$/{if($1>0) ok=1} END{exit !ok}'; do
				echo ' 无效开始步数。请输入正整数。'
				read md_start
			done
			echo ' 请输入步数间隔，例如 20'
			read md_interval
			while ! echo "$md_interval" | awk 'BEGIN{ok=0} /^[0-9]+$/{if($1>0) ok=1} END{exit !ok}'; do
				echo ' 无效步数间隔。请输入正整数。'
				read md_interval
			done
			echo ' 请输入结束步数 / iteration，例如 1000'
			read md_end
			while ! echo "$md_end" | awk -v s="$md_start" 'BEGIN{ok=0} /^[0-9]+$/{if($1>=s) ok=1} END{exit !ok}'; do
				echo ' 无效结束步数。请输入不小于开始步数的正整数。'
				read md_end
			done
			for md_current in `seq "$md_start" "$md_interval" "$md_end"`
			do
				md2cif_extract_target "$fname1" "$md_mode" "$md_current"
			done
		else
			echo ' 请输入开始时间，单位 ps，例如 0.5'
			read md_start
			while ! echo "$md_start" | awk '{exit !($1>=0)}'; do
				echo ' 无效开始时间。请输入非负数，单位 ps。'
				read md_start
			done
			echo ' 请输入时间间隔，单位 ps，例如 0.5'
			read md_interval
			while ! echo "$md_interval" | awk '{exit !($1>0)}'; do
				echo ' 无效时间间隔。请输入正数，单位 ps。'
				read md_interval
			done
			echo ' 请输入结束时间，单位 ps，例如 10.0'
			read md_end
			while ! echo "$md_end" | awk -v s="$md_start" '{exit !($1>=s)}'; do
				echo ' 无效结束时间。请输入不小于开始时间的数，单位 ps。'
				read md_end
			done
			for md_current in `seq "$md_start" "$md_interval" "$md_end"`
			do
				md2cif_extract_target "$fname1" "$md_mode" "$md_current"
			done
		fi
	fi
}

function relax2cif_menu (){
	local cif_mode relax_input cif_output default_output stage_dir context_file gjf_file status cleanup_status
	echo
	echo ' 请选择 CIF 提取模式：'
	echo '  1) 提取 (vc)relax 最终/最后一个结构'
	echo '  2) 按 MD 步数或 ps 时间提取分子动力学结构'
	read cif_mode
	while [ "$cif_mode" != "1" ] && [ "$cif_mode" != "2" ]
	do
		echo "请输入 1 或 2。"
		read cif_mode
	done

	if [ "$cif_mode" == "1" ]; then
		relax_input="${fname1-}"
		if [ -z "$relax_input" ] && [ -f "${fname2-}" ]; then
			relax_input="$fname2"
			cif_output="${fname3-}"
		else
			cif_output="${fname2-}"
		fi
		if [ -z "$relax_input" ]; then
			echo ' 请输入 (vc)relax 输出文件名。'
			read -r relax_input || return 1
		fi
		[ -f "$relax_input" ] || {
			echo " 错误：未找到输出文件 '$relax_input'。"
			return 1
		}
		default_output="${relax_input%.*}.cif"
		if [ -z "$cif_output" ] || [ "$cif_output" = "$relax_input" ]; then
			echo " 请输入输出 CIF 文件名（默认：$default_output）。"
			read -r cif_output || return 1
			[ -n "$cif_output" ] || cif_output="$default_output"
		fi
		qbox_postprocess_stage_dir "$cif_output" relax-context stage_dir || return $?
		context_file="$stage_dir/context.txt"
		gjf_file="$stage_dir/structure.gjf"
		status=0
		qbox_postprocess_relax "$relax_input" "$context_file"
		status=$?
		if [ "$status" -eq 0 ]; then
			qbox_postprocess_gjf "$context_file" "$gjf_file"
			status=$?
		fi
		if [ "$status" -eq 0 ]; then
			qbox_postprocess_cif "$gjf_file" "$cif_output"
			status=$?
		fi
		qbox_postprocess_remove_stage "$stage_dir"
		cleanup_status=$?
		if [ "$status" -eq 0 ] && [ "$cleanup_status" -ne 0 ]; then
			status="$cleanup_status"
		fi
		return "$status"
	else
		md2cif
	fi
}

function md_output_summary (){
	awk '
		/Entering Dynamics:[[:space:]]+iteration[[:space:]]*=/ {
			step=$NF
			getline
			time=$3
			if(first_step==""){
				first_step=step
				first_time=time
			}
			last_step=step
			last_time=time
			count++
		}
		END{
			if(count>0) print count, first_step, first_time, last_step, last_time
		}
	' "$1"
}

function merge_md_outputs (){
	local md_files_line md_output md_tmp first_file file summary frames first_step first_time last_step last_time
	local prev_last_step prev_last_time start_line append_summary append_frames append_first_step append_first_time append_last_step append_last_time
	local i auto_files

	echo
	echo ' 合并 QE 分子动力学输出文件。'
	echo ' 输入文件必须按时间顺序从旧到新排列，例如 md.out md-1.out'
	echo

	if [ -n "$fname1" ] && [ -f "$fname1" ] && [ -n "$fname2" ] && [ -f "$fname2" ]; then
		md_files_line="$fname1 $fname2"
	else
		auto_files=`{ [ -f md.out ] && printf '%s\n' md.out; ls -1v md-*.out 2>/dev/null; } | awk '!seen[$0]++' | tr '\n' ' '`
		if [ -n "$auto_files" ]; then
			echo " 检测到可能的 MD 输出文件：${auto_files}"
		fi
		echo ' 请按时间顺序输入需要合并的 MD 输出文件。'
		echo ' 如果上面检测到的顺序正确，直接回车即可使用。'
		read md_files_line
		if [ -z "$md_files_line" ]; then
			md_files_line="$auto_files"
		fi
	fi

	if [ -z "$md_files_line" ]; then
		echo ' 未指定 MD 输出文件。'
		return 1
	fi

	echo ' 请输入合并后的输出文件名，默认：merged.md.out'
	read md_output
	if [ -z "$md_output" ]; then
		md_output='merged.md.out'
	fi

	if [ -f "$md_output" ]; then
		echo " 错误：输出文件 '$md_output' 已存在。请先删除它或选择其他文件名。"
		return 1
	fi

	md_tmp="${md_output}.tmp.$$"
	rm -f "$md_tmp"

	i=0
	prev_last_step=""
	for file in $md_files_line; do
		if [ ! -f "$file" ]; then
			echo " 错误：未找到输入文件 '$file'。"
			rm -f "$md_tmp"
			return 1
		fi

		summary=`md_output_summary "$file"`
		if [ -z "$summary" ]; then
			echo " 错误：在 '$file' 中未找到 MD dynamics 结构块。"
			rm -f "$md_tmp"
			return 1
		fi

		frames=`echo "$summary" | awk '{print $1}'`
		first_step=`echo "$summary" | awk '{print $2}'`
		first_time=`echo "$summary" | awk '{print $3}'`
		last_step=`echo "$summary" | awk '{print $4}'`
		last_time=`echo "$summary" | awk '{print $5}'`

		i=$(($i + 1))
		if [ "$i" -eq 1 ]; then
			cat "$file" > "$md_tmp"
			prev_last_step="$last_step"
			prev_last_time="$last_time"
			echo " 已加入完整文件：$file，帧数=${frames}，步数 ${first_step}-${last_step}，时间 ${first_time}-${last_time} ps"
			continue
		fi

		start_line=`awk -v last="$prev_last_step" '
			/Entering Dynamics:[[:space:]]+iteration[[:space:]]*=/ {
				step=$NF
				if(step+0 > last+0){
					print NR
					exit
				}
			}
		' "$file"`

		if [ -z "$start_line" ]; then
			echo " 警告：'$file' 中没有比前一段最后步数 ${prev_last_step} 更新的 MD 步，已跳过。"
			continue
		fi

		append_summary=`awk -v sline="$start_line" '
			NR>=sline && /Entering Dynamics:[[:space:]]+iteration[[:space:]]*=/ {
				step=$NF
				getline
				time=$3
				if(first_step==""){
					first_step=step
					first_time=time
				}
				last_step=step
				last_time=time
				count++
			}
			END{
				if(count>0) print count, first_step, first_time, last_step, last_time
			}
		' "$file"`

		append_frames=`echo "$append_summary" | awk '{print $1}'`
		append_first_step=`echo "$append_summary" | awk '{print $2}'`
		append_first_time=`echo "$append_summary" | awk '{print $3}'`
		append_last_step=`echo "$append_summary" | awk '{print $4}'`
		append_last_time=`echo "$append_summary" | awk '{print $5}'`

		if [ "$((${append_first_step} - ${prev_last_step}))" -ne 1 ]; then
			echo " 警告：前一段最后步数 ${prev_last_step} 与追加段第一步 ${append_first_step} 不严格连续。"
		fi

		echo "" >> "$md_tmp"
		echo "===== qbox merged restart segment from ${file}; original header omitted =====" >> "$md_tmp"
		sed -n "${start_line},\$p" "$file" >> "$md_tmp"
		prev_last_step="$append_last_step"
		prev_last_time="$append_last_time"
		echo " 已追加文件尾段：$file，帧数=${append_frames}，步数 ${append_first_step}-${append_last_step}，时间 ${append_first_time}-${append_last_time} ps"
	done

	mv "$md_tmp" "$md_output"
	echo
	echo " 合并后的输出文件：${md_output}"
	echo " 最终 MD 步数：${prev_last_step}"
	echo " 最终 MD 时间：${prev_last_time} ps"
}
 
function qbox_md_to_xyz_menu (){
    local md_output="${fname1-}" xyz_output="${fname2-}" default_output

    if [ -z "$md_output" ] && [ -f "$xyz_output" ]; then
        md_output="$xyz_output"
        xyz_output=''
    fi
    if [ -z "$md_output" ]; then
        echo ' 请输入 QE 分子动力学输出文件，例如 merged.md.out'
        read -r md_output || return 1
    fi
    [ -f "$md_output" ] || {
        echo " 错误：未找到 MD 输出文件 '$md_output'。"
        return 1
    }

    if [ -z "$xyz_output" ]; then
        if [[ "$md_output" == *.md.out ]]; then
            default_output="${md_output%.md.out}.md.xyz"
        else
            default_output="${md_output%.*}.xyz"
        fi
        echo " 请输入输出 XYZ 文件名（默认：$default_output）。"
        read -r xyz_output || true
        [ -n "$xyz_output" ] || xyz_output="$default_output"
    fi

    qbox_postprocess_xyz "$md_output" "$xyz_output" || return $?
    echo " 已写出 xyz 轨迹文件：$xyz_output"
}
function qbox_nscf_menu (){
    local relax_input="${fname1-}" relax_output="${fname2-}" nscf_output="${fname3-}" default_output

    if [ -z "$relax_input" ]; then
        echo ' 请输入 (vc)relax 输入文件。'
        read -r relax_input || return 1
    fi
    [ -f "$relax_input" ] || {
        echo " 错误：未找到输入文件 '$relax_input'。"
        return 1
    }

    if [ -z "$relax_output" ]; then
        echo ' 请输入对应的 (vc)relax 输出文件。'
        read -r relax_output || return 1
    fi
    [ -f "$relax_output" ] || {
        echo " 错误：未找到输出文件 '$relax_output'。"
        return 1
    }

    if [ -z "$nscf_output" ]; then
        default_output="${relax_input%.in}.nscf.in"
        echo " 请输入输出 NSCF 文件名（默认：$default_output）。"
        read -r nscf_output || true
        [ -n "$nscf_output" ] || nscf_output="$default_output"
    fi

    qbox_postprocess_nscf "$relax_input" "$relax_output" "$nscf_output" || return $?
    echo " 已写出 NSCF 输入文件：$nscf_output"
}
#--------------------------------- other functions ----------------------------------------
function qbox_constraints_menu (){
    local input_file="${fname1-}" atom_spec="${fname2-}" if_pos="${fname3-}" output_file default_output

    if [ -z "$input_file" ]; then
        echo ' 请输入 QE 输入文件。'
        read -r input_file || return 1
    fi
    [ -f "$input_file" ] || {
        echo " 错误：未找到输入文件 '$input_file'."
        return 1
    }

    if [ -z "$atom_spec" ]; then
        echo ' 请输入需要固定的原子编号，例如 1,5,9-12,14-18'
        read -r atom_spec || return 1
    fi
    if [ -z "$if_pos" ]; then
        echo ' 请输入 if_pos(i)，例如 0 0 0 表示同时固定 x、y、z 三个方向。'
        read -r if_pos || return 1
    fi

    default_output="${input_file%.in}.fixed.in"
    echo " 请输入输出 QE 输入文件名（默认：$default_output）。"
    read -r output_file || true
    [ -n "$output_file" ] || output_file="$default_output"

    qbox_postprocess_constraints "$input_file" "$atom_spec" "$if_pos" "$output_file" || return $?
    echo " 已写出带约束的 QE 输入文件：$output_file"
}
function structure_format_convert (){
	local mode="$1"
	local in_ext out_ext label infile outfile

	if [ "$mode" == "cif2vasp" ]; then
		in_ext="cif"
		out_ext="vasp"
		label="cif 转 vasp"
	elif [ "$mode" == "vasp2cif" ]; then
		in_ext="vasp"
		out_ext="cif"
		label="vasp 转 cif"
	else
		echo
		echo " 错误：未知转换模式 '$mode'。"
		return 1
	fi

	infile="$fname1"
	if [ -z "$infile" ] || { [ -z "${QBOX_TASK_ID:-}" ] && { [ "$infile" == "37" ] || [ "$infile" == "38" ]; }; }; then
		echo
		echo " 请输入需要转换的 .${in_ext} 文件。"
		read infile
	fi

	while [ -z "$infile" ]; do
		echo
		echo " 请输入需要转换的 .${in_ext} 文件。"
		read infile
	done

	if [ ! -f "$infile" ]; then
		echo
		echo " 错误：未找到输入文件 '$infile'。"
		return 1
	fi

	case "$infile" in
		*.${in_ext}|*.${in_ext^^}) ;;
		*)
			echo
			echo " 警告：输入文件后缀不是 .${in_ext}，仍将尝试转换。"
			;;
	esac

	outfile="${infile%.*}.${out_ext}"
	if [ "$outfile" == "$infile" ]; then
		outfile="${infile}.${out_ext}"
	fi

	echo
	echo " 正在执行 ${label}："
	echo " 输入文件：$infile"
	echo " 输出文件：$outfile"

	if qbox_python -m qbox.io.convert_pymatgen "$mode" "$infile" "$outfile"
	then
		echo
		echo " 转换完成：$outfile"
		return 0
	fi

	echo
	echo " pymatgen 转换失败，正在尝试使用 ASE 兜底转换...."

	if qbox_python -m qbox.io.convert_ase "$infile" "$outfile"
	then
		echo
		echo " 转换完成：$outfile"
		return 0
	fi

	echo
	echo " ASE 转换失败，正在尝试内置结构转换...."

	if qbox_python -m qbox.io.convert_basic "$mode" "$infile" "$outfile"
	then
		echo
		echo " 转换完成：$outfile"
		return 0
	fi

	echo
	echo " 错误：转换失败。pymatgen、ASE 和内置结构转换均无法读取该文件。"
	return 1
}

function qe_is_vasp_structure_file (){
	case "${1##*/}" in
		*.vasp|*.VASP) return 0 ;;
		*) return 1 ;;
	esac
}

function qe_auto_convert_vasp_to_cif (){
	local input_file output_file old_fname1 convert_status
	input_file="$1"
	QE_AUTO_CONVERTED_CIF="$input_file"

	qe_is_vasp_structure_file "$input_file" || return 0
	if [ ! -f "$input_file" ]; then
		echo " 错误：未找到 VASP 结构文件 '$input_file'。" >&2
		return 1
	fi

	output_file="${input_file%.*}.cif"
	if [ -s "$output_file" ] && [ ! "$input_file" -nt "$output_file" ]; then
		echo " 检测到 VASP 结构文件，复用已有 CIF：$output_file"
		QE_AUTO_CONVERTED_CIF="$output_file"
		return 0
	fi

	echo " 检测到 VASP 结构文件，自动调用 37) vasp 转 cif。"
	old_fname1="$fname1"
	fname1="$input_file"
	if structure_format_convert "vasp2cif"; then
		convert_status=0
	else
		convert_status=1
	fi
	fname1="$old_fname1"

	if [ "$convert_status" -ne 0 ] || [ ! -s "$output_file" ]; then
		echo " 错误：无法将 '$input_file' 自动转换为 CIF，已停止后续功能。" >&2
		return 1
	fi

	QE_AUTO_CONVERTED_CIF="$output_file"
	echo " 后续功能将使用并保留：$QE_AUTO_CONVERTED_CIF"
	return 0
}
