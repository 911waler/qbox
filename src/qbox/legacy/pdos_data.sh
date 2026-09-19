#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function qe_builtin_clean_pdos_next_steps (){
		local target="$1"
		echo
		echo "后续建议："
		echo "  继续使用 13) PDOS计算会自动执行内置 sumdos 与绘图步骤。"
		echo "  若需手动处理，请进入 $target 后确认 sumpdos.x 已在 PATH 中。"
		echo
		echo "绘制元素 DOS 和轨道 DOS："
		echo "  qbox 20"
		echo
		echo "分析掺杂原子及其近邻 PDOS："
		echo "  qbox 28"
	}
function qe_builtin_clean_pdos (){
	local dest recovered pdos_files f
	dest="${1:-ATOM_PDOS}"


	if [ -e "$dest" ] && [ ! -d "$dest" ]; then
		recovered="${dest}.recovered.$(date +%Y%m%d%H%M%S)"
		mv -- "$dest" "$recovered"
		mkdir -p "$dest"
		mv -- "$recovered" "$dest"/
		echo "Warning: '$dest' existed as a file; preserved it as '$dest/$recovered'." >&2
	fi

	mkdir -p "$dest"

	shopt -s nullglob
	pdos_files=( ./*.pdos_tot ./*.pdos_atm#* )
	shopt -u nullglob

	if [ "${#pdos_files[@]}" -eq 0 ]; then
		echo "当前目录没有找到新的 PDOS 文件。"
		echo "期望文件名格式：*.pdos_tot 或 *.pdos_atm#*"
		if [ -d "$dest" ]; then
			echo
			echo "PDOS 文件可能已经被移动到 '$dest'。"
			qe_builtin_clean_pdos_next_steps "$dest"
		fi
		return 0
	fi

	for f in "${pdos_files[@]}"; do
		[ -f "$f" ] || continue
		mv -f -- "$f" "$dest"/
	done

	echo "已移动 ${#pdos_files[@]} 个 PDOS 文件到 '$dest'。"
	qe_builtin_clean_pdos_next_steps "$dest"
}
# <<< END BUILTIN: cleanPDOS.sh

# >>> BEGIN BUILTIN: sumdos.sh
function qe_builtin_sumdos (){
	local pdos_files tmpdir elements_file orbitals_file base count
	local element orbital files outfile log

	qe_ensure_runtime_for sumpdos.x || return 1

	shopt -s nullglob
	pdos_files=( ./*.pdos_atm#* )
	shopt -u nullglob

	if [ "${#pdos_files[@]}" -eq 0 ]; then
		echo "Error: no atomic PDOS files found in current directory." >&2
		echo "Expected files matching: *.pdos_atm#*" >&2
		return 1
	fi

	tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/.qbox-sumdos.XXXXXX")" || return 1
	qe_cleanup_register "$tmpdir" || { rm -rf -- "$tmpdir"; return 1; }
	elements_file="$tmpdir/elements"
	orbitals_file="$tmpdir/orbitals"
	: > "$elements_file"
	: > "$orbitals_file"

	for f in "${pdos_files[@]}"; do
		base="${f##*/}"
		if [[ "$base" =~ pdos_atm#[0-9]+\(Thank_you_for_using_qbox\)_wfc#[0-9]+\(Thank_you_for_using_qbox\) ]]; then
			continue
		fi
		if [[ "$base" =~ pdos_atm#[0-9]+\(([A-Za-z][A-Za-z0-9]*)\)_wfc#[0-9]+\(([A-Za-z0-9_+-]+)\) ]]; then
			printf '%s\n' "${BASH_REMATCH[1]}" >> "$elements_file"
			printf '%s %s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" >> "$orbitals_file"
		fi
	done

	sort -u "$elements_file" -o "$elements_file"
	sort -u "$orbitals_file" -o "$orbitals_file"

	if [ ! -s "$elements_file" ]; then
		echo "Error: could not parse element/orbital names from PDOS filenames." >&2
		rm -rf "$tmpdir"
		qe_cleanup_unregister "$tmpdir"
		return 1
	fi

	count=0
	rm -f ./*_tot.dat ./*_s.dat ./*_p.dat ./*_d.dat ./*_f.dat ./*_g.dat

	while IFS= read -r element; do
		shopt -s nullglob
		files=( ./*.pdos_atm#*"(${element})"* )
		shopt -u nullglob
		if [ "${#files[@]}" -gt 0 ]; then
			outfile="${element}_tot.dat"
			log="$tmpdir/sumpdos.log"
			if ! sumpdos.x "${files[@]}" > "$outfile" 2> "$log"; then
				echo "Error: sumpdos.x failed while writing '$outfile'." >&2
				cat "$log" >&2
				rm -f "$outfile"
				rm -rf "$tmpdir"
				qe_cleanup_unregister "$tmpdir"
				return 1
			fi
			count=$((count + 1))
			echo "Wrote ${element}_tot.dat from ${#files[@]} file(s)."
		fi
	done < "$elements_file"

	while read -r element orbital; do
		[ -n "${element:-}" ] || continue
		[ -n "${orbital:-}" ] || continue
		shopt -s nullglob
		files=( ./*.pdos_atm#*"(${element})"*"_wfc#"*"(${orbital})" )
		shopt -u nullglob
		if [ "${#files[@]}" -gt 0 ]; then
			outfile="${element}_${orbital}.dat"
			log="$tmpdir/sumpdos.log"
			if ! sumpdos.x "${files[@]}" > "$outfile" 2> "$log"; then
				echo "Error: sumpdos.x failed while writing '$outfile'." >&2
				cat "$log" >&2
				rm -f "$outfile"
				rm -rf "$tmpdir"
				qe_cleanup_unregister "$tmpdir"
				return 1
			fi
			count=$((count + 1))
			echo "Wrote ${element}_${orbital}.dat from ${#files[@]} file(s)."
		fi
	done < "$orbitals_file"

	rm -rf "$tmpdir"
	qe_cleanup_unregister "$tmpdir"
	echo "Generated $count summed PDOS file(s)."
}
# <<< END BUILTIN: sumdos.sh
# ===================== End built-in external tools =====================

