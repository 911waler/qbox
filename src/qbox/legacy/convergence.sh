#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qbox_extract_convergence_data (){
	local qe_output data_file last_file
	local data_stage last_stage staged_data staged_last status=0
	[ "$#" -eq 3 ] || return 2
	qe_output="$1"
	data_file="$2"
	last_file="$3"
	[ -f "$qe_output" ] && [ ! -L "$qe_output" ] || return 1
	qbox_postprocess_prepare_output "$data_file" || return $?
	qbox_postprocess_prepare_output "$last_file" || return $?
	qbox_output_paths_are_equivalent "$data_file" "$last_file" && return 1
	qbox_postprocess_stage_dir "$data_file" convergence-data data_stage || return $?
	qbox_postprocess_stage_dir "$last_file" convergence-last last_stage || {
		qbox_postprocess_remove_stage "$data_stage"
		return 1
	}
	staged_data="$data_stage/energy-all.dat"
	staged_last="$last_stage/energy-last.dat"
	if [ "$status" -eq 0 ]; then
		awk '
			function numeric(value, normalized) {
				normalized=value
				gsub(/[dD]/, "E", normalized)
				return normalized ~ /^[+-]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([Ee][+-]?[0-9]+)?$/
			}
			function energy_value(line, fields, field_count, candidate) {
				sub(/^[[:space:]]+/, "", line)
				sub(/[[:space:]]+$/, "", line)
				if (substr(line, 1, 1) == "!") {
					sub(/^![[:space:]]*/, "", line)
				}
				gsub(/=/, " = ", line)
				field_count=split(line, fields, /[[:space:]]+/)
				if (field_count != 5 || tolower(fields[1]) != "total" || tolower(fields[2]) != "energy" || fields[3] != "=" || tolower(fields[5]) != "ry") return ""
				candidate=fields[4]
				if (!numeric(candidate)) return ""
				gsub(/[dD]/, "E", candidate)
				return candidate
			}
			{
				line=$0
				sub(/^[[:space:]]+/, "", line)
				sub(/[[:space:]]+$/, "", line)
				if (index(line, "!") == 0 && tolower(line) !~ /^total[[:space:]]+energy([[:space:]]|$)/) next
				value=energy_value(line, fields)
				if (length(value) == 0) {
					invalid=1
					next
				}
				count++
				if (count == 1) baseline=value
				printf "%d\t%.12g\n", count, (value-baseline)*13.6057
			}
			END { exit !(invalid == 0 && count > 1) }
		' "$qe_output" >"$staged_data" || status=$?
	fi
	if [ "$status" -eq 0 ] && [ ! -s "$staged_data" ]; then
		status=1
	fi
	if [ "$status" -eq 0 ]; then
		tail -n 5 "$staged_data" >"$staged_last" || status=$?
	fi
	if [ "$status" -eq 0 ]; then
		qbox_postprocess_install_output "$staged_data" "$data_file" || status=$?
	fi
	if [ "$status" -eq 0 ]; then
		qbox_postprocess_install_output "$staged_last" "$last_file" || status=$?
	fi
	qbox_postprocess_remove_stage "$data_stage" || status=$?
	qbox_postprocess_remove_stage "$last_stage" || status=$?
	return "$status"
}

function qbox_plot_convergence_data (){
	local data_file last_file output_prefix
	[ "$#" -eq 3 ] || return 2
	data_file="$1"
	last_file="$2"
	output_prefix="$3"
	[ -s "$data_file" ] && [ -s "$last_file" ] || return 1
	qbox_python -m qbox.postprocess.convergence_plot "$data_file" "$last_file" "$output_prefix"
}

function qbox_conver_in_temp (){
	local temp_dir="$1" qe_output="$2" output_prefix="$3"
	qbox_extract_convergence_data "$qe_output" "$temp_dir/energy-all.dat" "$temp_dir/energy-last.dat" || return 1
	qbox_plot_convergence_data "$temp_dir/energy-all.dat" "$temp_dir/energy-last.dat" "$output_prefix"
}

function conver (){
	local qe_output="${fname1-}" output_prefix="${prefix-}_energy_convergence"
	[ -n "$qe_output" ] && [ -n "${prefix-}" ] || return 1
	qe_with_temp_dir qbox_conver_in_temp "$PWD" convergence "$qe_output" "$output_prefix"
}

function qbox_output_paths_are_equivalent (){
	local first="$1" second="$2" first_dir second_dir first_path second_path
	first_dir="$(cd -- "$(dirname -- "$first")" && pwd -P)" || return 1
	second_dir="$(cd -- "$(dirname -- "$second")" && pwd -P)" || return 1
	first_path="$first_dir/$(basename -- "$first")"
	second_path="$second_dir/$(basename -- "$second")"
	[ "$first_path" = "$second_path" ]
}

function qbox_scan_stage_dir (){
	local scan_dir="$1" label="$2" result_var="$3" parent created_stage_dir
	[ -n "$scan_dir" ] && [ ! -e "$scan_dir" ] && [ ! -L "$scan_dir" ] || return 1
	[[ "$result_var" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 2
	parent="$(dirname -- "$scan_dir")"
	mkdir -p -- "$parent" || return 1
	parent="$(cd -- "$parent" && pwd -P)" || return 1
	created_stage_dir="$(mktemp -d "$parent/.qbox-${label}.XXXXXX")" || return 1
	qe_cleanup_register "$created_stage_dir" || { rm -rf -- "$created_stage_dir"; return 1; }
	printf -v "$result_var" '%s' "$created_stage_dir"
}

function qbox_scan_remove_stage (){
	local stage_dir="$1" status=0
	[ -n "$stage_dir" ] || return 0
	rm -rf -- "$stage_dir" || status=$?
	qe_cleanup_unregister "$stage_dir"
	return "$status"
}

function qbox_scan_publish_stage (){
	local stage_dir="$1" scan_dir="$2"
	[ -d "$stage_dir" ] && [ ! -L "$stage_dir" ] || return 1
	[ ! -e "$scan_dir" ] && [ ! -L "$scan_dir" ] || return 1
	mv -T -- "$stage_dir" "$scan_dir" || return 1
	qe_cleanup_unregister "$stage_dir"
}

function qbox_prepare_ecut_scan (){
	local template scan_dir start step end dual_list
	local ecutwfc dual ecutrho output temporary status stage_dir target_name existing
	local -a ecutwfc_values=() ecutrho_values=() target_names=()
	[ "$#" -eq 6 ] || return 2
	template="$1"
	scan_dir="$2"
	start="$3"
	step="$4"
	end="$5"
	dual_list="$6"
	[ -f "$template" ] && [ ! -L "$template" ] || return 1
	awk -v a="$start" -v b="$step" -v c="$end" 'BEGIN {exit !(a ~ /^[0-9]+([.][0-9]+)?$/ && b ~ /^[0-9]+([.][0-9]+)?$/ && c ~ /^[0-9]+([.][0-9]+)?$/ && a>0 && b>0 && c>=a)}' || return 1
	awk -v list="$dual_list" 'BEGIN {if (list !~ /[^[:space:]]/) exit 1; n=split(list, a, /[[:space:]]+/); if (n < 1) exit 1; for (i=1; i<=n; i++) if (a[i] !~ /^[0-9]+([.][0-9]+)?$/ || a[i]<=0) exit 1}' || return 1
	awk '
		BEGIN {wfc=0; rho=0}
		{low=tolower($0); if (low ~ /^[[:space:]]*ecutwfc[[:space:]]*=/) wfc=1; if (low ~ /^[[:space:]]*ecutrho[[:space:]]*=/) rho=1}
		END {exit !(wfc && rho)}
	' "$template" || return 1
	[ -n "$scan_dir" ] && [ ! -e "$scan_dir" ] && [ ! -L "$scan_dir" ] || return 1
	for ecutwfc in $(seq "$start" "$step" "$end"); do
		for dual in $dual_list; do
			ecutrho="$(awk -v e="$ecutwfc" -v d="$dual" 'BEGIN {printf "%.12g", e*d}')" || return 1
			target_name="scan_${ecutwfc}_${ecutrho}.scf.in"
			for existing in "${target_names[@]}"; do
				[ "$existing" != "$target_name" ] || return 1
			done
			ecutwfc_values+=("$ecutwfc")
			ecutrho_values+=("$ecutrho")
			target_names+=("$target_name")
		done
	done
	[ "${#target_names[@]}" -gt 0 ] || return 1
	qbox_scan_stage_dir "$scan_dir" scan-ecut stage_dir || return $?
	for ((i=0; i<${#target_names[@]}; i++)); do
		ecutwfc="${ecutwfc_values[$i]}"
		ecutrho="${ecutrho_values[$i]}"
		output="$stage_dir/${target_names[$i]}"
		temporary="$(mktemp "$stage_dir/.qbox-scan-input.XXXXXX")" || {
			qbox_scan_remove_stage "$stage_dir"
			return 1
		}
		qe_cleanup_register "$temporary" || {
			rm -f -- "$temporary"
			qbox_scan_remove_stage "$stage_dir"
			return 1
		}
			awk -v ewfc="$ecutwfc" -v erho="$ecutrho" '
				BEGIN {wfc=0; rho=0}
				{low=tolower($0); if (!wfc && low ~ /^[[:space:]]*ecutwfc[[:space:]]*=/) {$0="   ecutwfc = " ewfc; wfc=1} if (!rho && low ~ /^[[:space:]]*ecutrho[[:space:]]*=/) {$0="   ecutrho = " erho; rho=1} print}
				END {exit !(wfc && rho)}
			' "$template" >"$temporary"
			status=$?
			if [ "$status" -eq 0 ]; then
				chmod --reference="$template" -- "$temporary" || status=$?
			fi
			if [ "$status" -eq 0 ]; then
				mv -f -- "$temporary" "$output" || status=$?
			fi
			[ "$status" -eq 0 ] || rm -f -- "$temporary"
			qe_cleanup_unregister "$temporary"
			if [ "$status" -ne 0 ]; then
				qbox_scan_remove_stage "$stage_dir"
				return "$status"
			fi
	done
	qbox_scan_publish_stage "$stage_dir" "$scan_dir" || {
		qbox_scan_remove_stage "$stage_dir"
		return 1
	}
}

function qbox_prepare_kpoint_scan (){
	local template scan_dir mesh_list
	local mesh name output temporary status stage_dir target_name existing
	local -a meshes=() target_names=()
	[ "$#" -eq 3 ] || return 2
	template="$1"
	scan_dir="$2"
	mesh_list="$3"
	[ -f "$template" ] && [ ! -L "$template" ] || return 1
	printf '%s\n' "$mesh_list" | awk -F, 'BEGIN {count=0} {for (i=1; i<=NF; i++) {gsub(/[[:space:]]+/, " ", $i); sub(/^ /, "", $i); sub(/ $/, "", $i); n=split($i, a, " "); if (n != 3 || a[1] !~ /^[1-9][0-9]*$/ || a[2] !~ /^[1-9][0-9]*$/ || a[3] !~ /^[1-9][0-9]*$/) exit 1; count++}} END {exit !(count > 0)}' || return 1
	awk '{if (tolower($0) ~ /^[[:space:]]*k_points[[:space:]]+automatic/) found=1} END {exit !found}' "$template" || return 1
	[ -n "$scan_dir" ] && [ ! -e "$scan_dir" ] && [ ! -L "$scan_dir" ] || return 1
	while IFS= read -r mesh; do
		name="$(printf '%s\n' "$mesh" | tr -d ' ')" || return 1
		target_name="scan_${name}.scf.in"
		for existing in "${target_names[@]}"; do
			[ "$existing" != "$target_name" ] || return 1
		done
		meshes+=("$mesh")
		target_names+=("$target_name")
	done < <(printf '%s\n' "$mesh_list" | awk -F, '{for (i=1; i<=NF; i++) {gsub(/[[:space:]]+/, " ", $i); sub(/^ /, "", $i); sub(/ $/, "", $i); print $i}}')
	[ "${#target_names[@]}" -gt 0 ] || return 1
	qbox_scan_stage_dir "$scan_dir" scan-kpoint stage_dir || return $?
	for ((i=0; i<${#target_names[@]}; i++)); do
		mesh="${meshes[$i]}"
		output="$stage_dir/${target_names[$i]}"
		temporary="$(mktemp "$stage_dir/.qbox-scan-input.XXXXXX")" || {
			qbox_scan_remove_stage "$stage_dir"
			return 1
		}
		qe_cleanup_register "$temporary" || {
			rm -f -- "$temporary"
			qbox_scan_remove_stage "$stage_dir"
			return 1
		}
		awk -v mesh="$mesh" '
			BEGIN {found=0; skip_mesh=0}
			{
				if (skip_mesh) {skip_mesh=0; next}
				low=tolower($0)
				if (!found && low ~ /^[[:space:]]*k_points[[:space:]]+automatic/) {
					print "K_POINTS automatic"
					print "  " mesh " 0 0 0"
					found=1
					skip_mesh=1
					next
				}
				print
			}
			END {exit !found}
		' "$template" >"$temporary"
		status=$?
		if [ "$status" -eq 0 ]; then
			chmod --reference="$template" -- "$temporary" || status=$?
		fi
		if [ "$status" -eq 0 ]; then
			mv -f -- "$temporary" "$output" || status=$?
		fi
		[ "$status" -eq 0 ] || rm -f -- "$temporary"
		qe_cleanup_unregister "$temporary"
		if [ "$status" -ne 0 ]; then
			qbox_scan_remove_stage "$stage_dir"
			return "$status"
		fi
	done
	qbox_scan_publish_stage "$stage_dir" "$scan_dir" || {
		qbox_scan_remove_stage "$stage_dir"
		return 1
	}
}

function qbox_render_scan_batch_script (){
	local target="$1" job_name="$2"
	cat <<EOF
#!/bin/bash
#PBS -S /bin/bash
#PBS -N ${job_name}
#PBS -j oe
#PBS -q intel
#PBS -l walltime=1440:00:00
#PBS -l nodes=1:ppn=9
#PBS -V
 
set -o pipefail

cd \${PBS_O_WORKDIR}
 
n=0
for inf in *.in
do
        n=\$((\$n+1))
        mpirun -np 9 pw.x -i \${inf} &> \${inf//in/out} || exit \$?
        grep -E '^[[:space:]]*![[:space:]]+total[[:space:]]+energy[[:space:]]*=' \${inf//in/out} |awk -v var="\$n" '{print var "\\t" \$5}' >> energy.dat || exit \$?
done
 
EOF
}

function qbox_render_scan_plot_script (){
	cat <<'EOF'
set grid
set xlabel "Number"
set ylabel "Total Energy (Ry)"
unset key
plot 'energy.dat' u 1:2 w lp lw 2 lc rgb "dark-blue" ps 1.5 pt 7,
pause -1
EOF
}

function qbox_write_ecut_batch_script (){
	local scan_dir
	[ "$#" -eq 1 ] || return 2
	scan_dir="$1"
	[ -d "$scan_dir" ] && [ ! -L "$scan_dir" ] || return 1
	qe_atomic_rewrite "$scan_dir/sub_qe.sh" qbox_render_scan_batch_script scan_ecut || return 1
	qe_atomic_rewrite "$scan_dir/scan_ecut.gp" qbox_render_scan_plot_script
}

function qbox_write_kpoint_batch_script (){
	local scan_dir
	[ "$#" -eq 1 ] || return 2
	scan_dir="$1"
	[ -d "$scan_dir" ] && [ ! -L "$scan_dir" ] || return 1
	qe_atomic_rewrite "$scan_dir/sub_qe.sh" qbox_render_scan_batch_script scan_kp || return 1
	qe_atomic_rewrite "$scan_dir/scan_kp.gp" qbox_render_scan_plot_script
}

function qbox_ecut_scan_menu (){
	local template="$1" scan_dir="$2" start step end extra dual_list
	echo ' 请输入 ecutwfc 的起始值、步长和终止值，例如 30 5 60'
	read -r start step end extra || return 1
	[ -z "$extra" ] || return 1
	echo ' 请输入 dual，例如 4'
	echo ' dual 表示 ecutrho = ecutwfc*dual。如果输入多个 dual，例如 4 8 12，则每个 ecutwfc 都会在不同 dual 下扫描。'
	echo ' 经验值：PAW 的 dual 通常约为 4，USPP 通常为 8~12。'
	read -r dual_list || return 1
	qbox_prepare_ecut_scan "$template" "$scan_dir" "$start" "$step" "$end" "$dual_list" || return 1
	qbox_write_ecut_batch_script "$scan_dir"
}

function qbox_kpoint_scan_menu (){
	local template="$1" scan_dir="$2" mesh_list
	echo ' 请输入需要扫描的 K 点网格，例如 1 1 1,2 2 2,4 5 5'
	read -r mesh_list || return 1
	qbox_prepare_kpoint_scan "$template" "$scan_dir" "$mesh_list" || return 1
	qbox_write_kpoint_batch_script "$scan_dir"
}

function ecuttest (){
	qbox_ecut_scan_menu "${fname1-}" "$PWD/scan_ecut"
}

function script_ecut (){
	qbox_write_ecut_batch_script "${1:-$PWD/scan_ecut}"
}

function kptest (){
	qbox_kpoint_scan_menu "${fname1-}" "$PWD/scan_kp"
}

function script_kp (){
	qbox_write_kpoint_batch_script "${1:-$PWD/scan_kp}"
}
 
#--------------------------------- scf.in -> nscf.in converter ----------------------------------------
