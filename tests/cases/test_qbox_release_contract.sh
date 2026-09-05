#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"

test_public_entrypoint() {
    local old_script
    old_script="$(printf 'QE%s' 'toolkit.sh')"
    [ -x "$PROJECT_ROOT/qbox" ] || fail 'qbox must be an executable file'
    [ ! -e "$PROJECT_ROOT/$old_script" ] || fail 'the legacy executable name must not remain'
    assert_contains "$(QBOX_TEST_MODE=1 bash "$PROJECT_ROOT/qbox" --version 2>&1)" 'qbox' \
        'version output must identify qbox'
    assert_contains "$(QBOX_TEST_MODE=1 bash "$PROJECT_ROOT/qbox" --help 2>&1)" 'QBOX_PYTHON' \
        'help output must document the public configuration variables'
    assert_contains "$(QBOX_TEST_MODE=1 bash "$PROJECT_ROOT/qbox" --help 2>&1)" 'QBOX_SHARED_ROOT' \
        'help output must document the shared dependency root'
}

test_shared_root_derives_default_dependency_paths() (
    local sandbox shared expected_python expected_multi
    sandbox="$(new_sandbox)" || return 1
    shared="$sandbox/shared"
    expected_python="$shared/python/bin/python3"
    expected_multi="$shared/multiwfn"
    mkdir -p "${expected_python%/*}" "$expected_multi"
    : >"$expected_python"
    : >"$expected_multi/Multiwfn"
    chmod +x "$expected_python" "$expected_multi/Multiwfn"

    unset QBOX_PYTHON QBOX_MULTIWFN_HOME
    export QBOX_SHARED_ROOT="$shared"
    export QBOX_TEST_MODE=1
    source "$PROJECT_ROOT/qbox"
    assert_eq "$expected_python" "$QBOX_PYTHON" \
        'QBOX_SHARED_ROOT must derive the default Python path'
    assert_eq "$expected_multi" "$QBOX_MULTIWFN_HOME" \
        'QBOX_SHARED_ROOT must derive the default Multiwfn directory'
)

test_explicit_dependency_paths_override_shared_root() (
    local sandbox shared explicit_python explicit_multi
    sandbox="$(new_sandbox)" || return 1
    shared="$sandbox/shared"
    explicit_python="$sandbox/python-explicit"
    explicit_multi="$sandbox/multi-explicit"
    mkdir -p "$shared" "$explicit_multi"
    : >"$explicit_python"
    : >"$explicit_multi/Multiwfn"
    chmod +x "$explicit_python" "$explicit_multi/Multiwfn"

    export QBOX_SHARED_ROOT="$shared"
    export QBOX_PYTHON="$explicit_python"
    export QBOX_MULTIWFN_HOME="$explicit_multi"
    export QBOX_TEST_MODE=1
    source "$PROJECT_ROOT/qbox"
    assert_eq "$explicit_python" "$QBOX_PYTHON" \
        'explicit QBOX_PYTHON must override QBOX_SHARED_ROOT'
    assert_eq "$explicit_multi" "$QBOX_MULTIWFN_HOME" \
        'explicit QBOX_MULTIWFN_HOME must override QBOX_SHARED_ROOT'
)

test_public_names_are_present() {
    local public_file
    for public_file in qbox qbox-dopant-pdos.py README.md LICENSE CITATION.cff; do
        [ -e "$PROJECT_ROOT/$public_file" ] || fail "missing public file: $public_file"
    done
}

test_license_is_mit_and_owned_by_waler() {
    assert_contains "$(cat "$PROJECT_ROOT/LICENSE")" 'MIT License' \
        'public license must be MIT'
    assert_contains "$(cat "$PROJECT_ROOT/LICENSE")" 'Copyright (c) 2026 waler' \
        'public license must name waler as copyright holder'
}

test_test_runtime_selects_python_with_required_modules() {
    [ -n "${QBOX_PYTHON:-}" ] || {
        fail 'test helper must export QBOX_PYTHON before qbox is sourced'
        return 1
    }
    "$QBOX_PYTHON" -c 'import seekpath' >/dev/null 2>&1 || {
        fail 'QBOX_PYTHON must import the required seekpath module'
        return 1
    }
}

test_test_runtime_python_probe_is_bounded() {
    local probe
    probe="$(declare -f qbox_test_python_supports_required_modules)"
    assert_contains "$probe" 'timeout' \
        'test runtime must bound Python module probes with timeout'
}

test_test_runtime_discovery_is_capped_and_path_safe() {
    local discovery
    discovery="$(declare -f qbox_test_configure_python)"
    assert_contains "$discovery" 'max_probe_count' \
        'test runtime must cap automatic Python candidates'
    assert_contains "$discovery" 'probe_count' \
        'test runtime must count automatic Python candidates'
    assert_contains "$discovery" 'for candidate in python3 python;' \
        'test runtime must use only fixed safe Python candidates'
    assert_not_contains "$discovery" 'generic_candidate' \
        'test runtime must not track generic Python candidates'
    assert_not_contains "$discovery" '/*-python' \
        'test runtime must not glob generic Python candidates'
    assert_not_contains "$discovery" '/*python*' \
        'test runtime must not execute arbitrary python-named files'
    assert_contains "$discovery" 'case "$path_entry" in' \
        'test runtime must validate PATH entries before probing'
    assert_contains "$discovery" '/*)' \
        'test runtime must skip non-absolute PATH entries'
}

test_test_runtime_rejects_unrelated_python_and_cleans_on_failure() {
    local parent bin temp_root false_path output status leftovers test_status=0
    parent="$(new_sandbox)" || return 1
    bin="$parent/bin"
    temp_root="$parent/tmp"
    mkdir -p "$bin" "$temp_root" || return 1
    false_path="$(type -P false)" || return 1
    ln -s -- "$false_path" "$bin/python3" || return 1
    ln -s -- "$false_path" "$bin/python" || return 1
    ln -s -- "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/unrelated-python" || return 1

    output="$(
        cd "$parent" || exit 1
        env -i PATH="$bin:/usr/bin:/bin" TMPDIR="$temp_root" \
            QBOX_MOCK_COMMAND_LOG="$parent/unrelated.log" \
            /bin/bash "$PROJECT_ROOT/tests/test_helper.sh" 2>&1
    )"
    status=$?
    [ "$status" -ne 0 ] || {
        printf '%s\n' "$output" >&2
        fail 'test helper executed an unrelated *-python candidate'
        test_status=1
    }
    assert_contains "$output" 'no Python interpreter' \
        'test helper must report the missing seekpath-capable interpreter' || test_status=1
    [ ! -e "$parent/unrelated.log" ] || {
        fail 'test helper executed an unrelated *-python candidate'
        test_status=1
    }
    leftovers="$(find "$temp_root" -mindepth 1 -maxdepth 1 -type d -name '.qbox-tests.*' -print)"
    [ -z "$leftovers" ] || {
        printf '%s\n' "$leftovers" >&2
        fail 'test helper must clean its temporary root after dependency failure'
        test_status=1
    }
    return "$test_status"
}

test_public_source_email_audit_detects_ordinary_email() {
    local email_probe output
    email_probe="$(printf '%s@%s.%s\n' 'name' 'example' 'com')"
    output="$(printf '%s' "$email_probe" | rg -n \
        '[[:alnum:]_.%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}' || true)"
    [ -n "$output" ] || fail 'public source email audit must detect ordinary emails'
}

test_public_source_has_no_private_absolute_paths() {
    local output
    output="$(rg -n \
        '/home/[[:alnum:]_.-]+|/(opt|srv)/[[:alnum:]_.-]+|[[:alnum:]_.%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}' \
        "$PROJECT_ROOT/qbox" "$PROJECT_ROOT/qbox-dopant-pdos.py" 2>/dev/null || true)"
    [ -z "$output" ] || { printf '%s\n' "$output" >&2; fail 'public runtime files contain a private absolute path or email'; }
}

test_public_source_has_no_legacy_namespace() {
    local old_name old_lower old_env old_abbrev output
    old_name="$(printf 'QE%s' 'toolkit')"
    old_lower="$(printf 'q%s' 'etoolkit')"
    old_env="$(printf 'QE%s' '_TOOLKIT')"
    old_abbrev="$(printf 'Q%s' 'ETK')"
    output="$(rg -n -F -e "$old_name" -e "$old_lower" -e "$old_env" -e "$old_abbrev" \
        "$PROJECT_ROOT/qbox" "$PROJECT_ROOT/qbox-dopant-pdos.py" 2>/dev/null || true)"
    [ -z "$output" ] || { printf '%s\n' "$output" >&2; fail 'legacy project namespace remains in public runtime files'; }
}

test_missing_dopant_helper_diagnostic_is_path_neutral() (
    local sandbox install output status
    sandbox="$(new_sandbox)" || return 1
    install="$sandbox/install-root"
    mkdir -p "$install"
    cp -- "$PROJECT_ROOT/qbox" "$install/qbox"
    chmod +x "$install/qbox"

    output="$(
        cd "$sandbox" || exit 1
        QBOX_TEST_MODE=1 bash -c 'source "$1/qbox"; analyze_qe_dopant_pdos' _ "$install" 2>&1
    )"
    status=$?
    [ "$status" -ne 0 ] || {
        printf '%s\n' "$output" >&2
        fail 'missing dopant helper must fail'
        return 1
    }
    assert_contains "$output" '请检查 qbox 安装' \
        'missing dopant helper must provide path-neutral guidance' || return 1
    assert_not_contains "$output" "$install" \
        'missing dopant helper must not print the installation path'
)

test_dopant_command_summary_is_path_neutral() {
    local source
    source="$(sed -n \
        '/^function analyze_qe_dopant_pdos /,/^function qe_embedded_plot_ldos /p' \
        "$PROJECT_ROOT/qbox")"
    assert_not_contains "$source" '${QBOX_PYTHON} ${analysis_script}' \
        'dopant command summary must not expose the Python/helper paths'
    assert_not_contains "$source" '未找到掺杂 PDOS 分析脚本 $analysis_script' \
        'missing dopant helper message must not interpolate its absolute path'
    assert_contains "$source" 'qbox-dopant-pdos.py' \
        'dopant command summary must retain a neutral helper name'
}

test_dopant_report_uses_neutral_basenames() (
    local sandbox structure pdos_dir output_dir report report_text output import_error path_hits
    sandbox="$(new_sandbox)" || return 1
    structure="$sandbox/structure.in"
    pdos_dir="$sandbox/pdos-data"
    output_dir="$sandbox/generated-output"
    report="$output_dir/neighbor_report.txt"
    mkdir -p "$pdos_dir" "$output_dir" "$sandbox/mpl-cache" || return 1

    if ! import_error="$("$QBOX_PYTHON" -c 'import numpy, matplotlib' 2>&1)"; then
        printf 'FAIL: QBOX_PYTHON lacks numpy/matplotlib for qbox-dopant-pdos privacy regression\n%s\n' \
            "$import_error" >&2
        return 1
    fi

    {
        printf '&CONTROL\n/\n'
        printf '&SYSTEM\n  nat = 2, ntyp = 2\n/\n'
        printf 'CELL_PARAMETERS angstrom\n'
        printf '10 0 0\n0 10 0\n0 0 10\n'
        printf 'ATOMIC_POSITIONS angstrom\n'
        printf 'Al 0 0 0\nC 1 0 0\n'
    } > "$structure" || return 1
    printf '0.0 1.0\n1.0 2.0\n' > "$pdos_dir/pdos.dat.pdos_atm#1(Al)_wfc#1(s)" || return 1
    printf '0.0 3.0\n1.0 4.0\n' > "$pdos_dir/pdos.dat.pdos_atm#2(C)_wfc#1(p)" || return 1

    output="$(
        MPLCONFIGDIR="$sandbox/mpl-cache" "$QBOX_PYTHON" "$PROJECT_ROOT/qbox-dopant-pdos.py" \
            --structure "$structure" --pdos-dir "$pdos_dir" --dopant Al --nearest 1 \
            --output-dir "$output_dir" --dpi 20 2>&1
    )" || {
        printf '%s\n' "$output" >&2
        fail 'qbox-dopant-pdos privacy regression must run on the minimal fixture'
        return 1
    }
    [ -s "$report" ] || {
        fail 'qbox-dopant-pdos must generate neighbor_report.txt'
        return 1
    }

    report_text="$(<"$report")"
    assert_contains "$report_text" '结构文件: structure.in' \
        'neighbor report must use the structure basename' || return 1
    assert_contains "$report_text" 'PDOS目录: pdos-data' \
        'neighbor report must use the PDOS directory basename' || return 1
    path_hits="$(rg -a -n -F -- "$sandbox" "$output_dir" 2>/dev/null || true)"
    [ -z "$path_hits" ] || {
        printf '%s\n' "$path_hits" >&2
        fail 'generated PDOS outputs must not expose the sandbox absolute path'
        return 1
    }
)

test_qbox_unfold_generated_metadata_uses_neutral_identifiers() (
    local sandbox report output report_text geometry_output geometry_result geometry_metadata
    local geometry_source geometry_input legacy_metadata_form
    sandbox="$(new_sandbox)" || return 1

    write_cif() {
        local file="$1" first_element="$2" second_element="${3-}"
        {
            printf 'data_probe\n'
            printf '_cell_length_a %s\n' "$([ -n "$second_element" ] && printf '2' || printf '1')"
            printf '_cell_length_b 1\n_cell_length_c 1\n'
            printf '_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\n'
            printf '_symmetry_space_group_name_H-M_alt "P 1"\n_symmetry_Int_Tables_number 1\n'
            printf 'loop_\n_symmetry_equiv_pos_as_xyz\n'
            printf "'x, y, z'\n"
            printf 'loop_\n_atom_site_label\n_atom_site_type_symbol\n_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n'
            printf '%s1 %s 0 0 0\n' "$first_element" "$first_element"
            if [ -n "$second_element" ]; then
                printf '%s2 %s 0.5 0 0\n' "$second_element" "$second_element"
            fi
        } > "$file"
    }

    write_cif "$sandbox/primitive.cif" Si
    write_cif "$sandbox/pristine.cif" Si Si
    write_cif "$sandbox/defect.cif" Si C
    report="$sandbox/generated/unfold-structure-candidates.json"

    source_qbox || return 1
    geometry_output="$sandbox/generated/geometry"
    geometry_result="$(
        qe_unfold_prepare_geometry \
            "$sandbox/primitive.cif" "$sandbox/pristine.cif" "$sandbox/defect.cif" \
            0.5 "$geometry_output"
    )" || {
        printf '%s\n' "$geometry_result" >&2
        fail 'qbox unfold geometry preparation must run on the minimal fixture'
        return 1
    }
    [ -s "$geometry_output/unfold-metadata.json" ] || {
        fail 'qbox unfold geometry preparation must generate unfold-metadata.json'
        return 1
    }

    geometry_metadata="$(<"$geometry_output/unfold-metadata.json")"
    assert_contains "$geometry_metadata" '"primitive_cif": "primitive.cif"' \
        'unfold geometry metadata must use the primitive basename' || return 1
    assert_contains "$geometry_metadata" '"pristine_supercell_cif": "pristine.cif"' \
        'unfold geometry metadata must use the pristine basename' || return 1
    assert_contains "$geometry_metadata" '"defect_supercell_cif": "defect.cif"' \
        'unfold geometry metadata must use the defect basename' || return 1
    assert_not_contains "$geometry_metadata" 'scan/' \
        'unfold geometry metadata must not expose a scan path' || return 1
    assert_not_contains "$geometry_metadata" "$sandbox" \
        'unfold geometry metadata must not expose the sandbox absolute path' || return 1

    geometry_source="$(sed -n \
        '/^function qe_unfold_prepare_geometry /,/^function qe_unfold_patch_bands_input /p' \
        "$PROJECT_ROOT/qbox")"
    assert_contains "$geometry_source" '"primitive_cif": pathlib.Path(primitive_path).name' \
        'geometry metadata must serialize the primitive basename in source' || return 1
    assert_contains "$geometry_source" '"pristine_supercell_cif": pathlib.Path(supercell_path).name' \
        'geometry metadata must serialize the pristine basename in source' || return 1
    assert_contains "$geometry_source" '"defect_supercell_cif": pathlib.Path(defect_path).name' \
        'geometry metadata must serialize the defect basename in source' || return 1
    for geometry_input in primitive_path supercell_path defect_path; do
        legacy_metadata_form="str(pathlib.Path(${geometry_input}).resolve())"
        assert_not_contains "$geometry_source" "$legacy_metadata_form" \
            "geometry metadata must not serialize ${geometry_input} as a resolved path" || return 1
    done

    output="$(qe_unfold_discover_structures "$sandbox" "$report")" || {
        printf '%s\n' "$output" >&2
        fail 'qbox unfold structure discovery must run on the minimal fixture'
        return 1
    }
    [ -s "$report" ] || {
        fail 'qbox unfold discovery must generate its candidate metadata'
        return 1
    }

    report_text="$(<"$report")"
    assert_contains "$report_text" '"scan_directory": "scan"' \
        'unfold metadata must use a neutral scan directory identifier' || return 1
    assert_contains "$report_text" '"primitive.cif"' \
        'unfold metadata must retain the primitive basename' || return 1
    assert_contains "$report_text" '"pristine.cif"' \
        'unfold metadata must retain the pristine basename' || return 1
    assert_contains "$report_text" '"defect.cif"' \
        'unfold metadata must retain the defect basename' || return 1
    assert_not_contains "$report_text" "$sandbox" \
        'unfold metadata must not expose the scan directory absolute path' || return 1
    assert_not_contains "$output" "$sandbox" \
        'unfold discovery output must not expose the scan directory absolute path' || return 1
)

test_public_export_has_only_allowlisted_files() (
    local destination expected_files exported_files public_test_file public_test_files untracked_test_file
    local old_name old_lower old_env old_abbrev output internal_review_prefix url_scheme raw_url_prefix
    [ -x "$PROJECT_ROOT/tools/export-public-tree" ] || return 0
    destination="$(mktemp -d "${TMPDIR:-/tmp}/.qbox-export-contract.XXXXXX")" || fail 'cannot create export destination'
    untracked_test_file="$(mktemp "$PROJECT_ROOT/tests/.qbox-export-untracked.XXXXXX")" || fail 'cannot create untracked test sentinel'
    trap 'rm -rf -- "$destination"; rm -f -- "$untracked_test_file"' EXIT
    rmdir -- "$destination" || fail 'cannot prepare fresh export destination'

    "$PROJECT_ROOT/tools/export-public-tree" "$destination" || fail 'public exporter failed'

    [ -x "$destination/qbox" ] || fail 'exported qbox must be executable'
    [ -x "$destination/qbox-dopant-pdos.py" ] || fail 'exported helper must be executable'

    public_test_files="$(git -C "$PROJECT_ROOT" ls-files -- \
        tests/README.md tests/run.sh tests/test_helper.sh tests/cases tests/fixtures tests/mocks)"
    expected_files="$({
        printf '%s\n' qbox qbox-dopant-pdos.py README.md LICENSE CITATION.cff .gitignore .gitattributes
        printf '%s\n' "$public_test_files"
    } | LC_ALL=C sort)"
    exported_files="$(find "$destination" -type f -printf '%P\n' | LC_ALL=C sort)"
    assert_eq "$expected_files" "$exported_files" 'export must contain only public allowlisted files' || return 1
    [ ! -e "$destination/tests/${untracked_test_file##*/}" ] || fail 'export must not copy untracked test files'

    while IFS= read -r public_test_file; do
        [ -n "$public_test_file" ] || continue
        assert_eq "$(stat -c '%a' "$PROJECT_ROOT/$public_test_file")" \
            "$(stat -c '%a' "$destination/$public_test_file")" \
            "export must preserve mode: $public_test_file" || return 1
    done <<< "$public_test_files"

    output="$(find "$destination" \( -path "$destination/.git" -o -path "$destination/.git/*" \
        -o -path "$destination/docs" -o -path "$destination/docs/*" \
        -o -path "$destination/review.md" -o -path "$destination/tools" -o -path "$destination/tools/*" \
        -o -path '*/__pycache__' -o -path '*/__pycache__/*' -o -path '*/.pytest_cache' -o -path '*/.pytest_cache/*' \
        -o -name '*.pyc' -o -name '*.pyo' \) -print)"
    [ -z "$output" ] || { printf '%s\n' "$output" >&2; fail 'export contains an internal path or cache'; }

    old_name="$(printf 'QE%s' 'toolkit')"
    old_lower="$(printf 'q%s' 'etoolkit')"
    old_env="$(printf 'QE%s' '_TOOLKIT')"
    old_abbrev="$(printf 'Q%s' 'ETK')"
    output="$(rg -n -F -e "$old_name" -e "$old_lower" -e "$old_env" -e "$old_abbrev" "$destination" 2>/dev/null || true)"
    [ -z "$output" ] || { printf '%s\n' "$output" >&2; fail 'export contains a legacy project marker'; }

    output="$(rg -n '/home/[[:alnum:]_.-]+|/(opt|srv)/[[:alnum:]_.-]+|[[:alnum:]_.%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}' \
        "$destination" 2>/dev/null || true)"
    [ -z "$output" ] || { printf '%s\n' "$output" >&2; fail 'export contains a private absolute path or email'; }

    internal_review_prefix="$(printf '%s%s' 'QT' 'K-')"
    output="$(rg -n -F -- "$internal_review_prefix" "$destination" 2>/dev/null || true)"
    [ -z "$output" ] || {
        printf '%s\n' "$output" >&2
        fail 'export contains an internal review marker'
        return 1
    }

    for url_scheme in http https; do
        raw_url_prefix="$(printf '%s%s' "$url_scheme" '://')"
        output="$(rg -n -F -- "$raw_url_prefix" "$destination" 2>/dev/null || true)"
        [ -z "$output" ] || {
            printf '%s\n' "$output" >&2
            fail 'export contains a raw web URL'
            return 1
        }
    done
)

run_test 'qbox entrypoint is executable and self-described' test_public_entrypoint
run_test 'shared root derives dependency defaults' test_shared_root_derives_default_dependency_paths
run_test 'explicit dependency paths override shared root' test_explicit_dependency_paths_override_shared_root
run_test 'public files exist' test_public_names_are_present
run_test 'public license is MIT and names waler' test_license_is_mit_and_owned_by_waler
run_test 'test runtime selects Python with required modules' test_test_runtime_selects_python_with_required_modules
run_test 'test runtime bounds Python module probes' test_test_runtime_python_probe_is_bounded
run_test 'test runtime caps and sanitizes Python discovery' test_test_runtime_discovery_is_capped_and_path_safe
run_test 'test runtime rejects unrelated Python and cleans failures' test_test_runtime_rejects_unrelated_python_and_cleans_on_failure
run_test 'public source email audit detects ordinary emails' test_public_source_email_audit_detects_ordinary_email
run_test 'public runtime files have no private paths or emails' test_public_source_has_no_private_absolute_paths
run_test 'public runtime files have no legacy namespace' test_public_source_has_no_legacy_namespace
run_test 'missing dopant helper diagnostics are path-neutral' test_missing_dopant_helper_diagnostic_is_path_neutral
run_test 'dopant command summaries are path-neutral' test_dopant_command_summary_is_path_neutral
run_test 'dopant report uses neutral basenames' test_dopant_report_uses_neutral_basenames
run_test 'unfold metadata uses neutral identifiers' test_qbox_unfold_generated_metadata_uses_neutral_identifiers
run_test 'public export is allowlisted and sanitized' test_public_export_has_only_allowlisted_files
finish_tests
