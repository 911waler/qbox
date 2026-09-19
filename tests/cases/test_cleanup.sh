#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

test_cleanup_registry_removes_registered_path_only() {
    local parent managed sentinel
    parent="$(new_sandbox)" || return 1
    managed="$parent/.qbox-managed"
    sentinel="$parent/sentinel"
    mkdir -p "$managed"
    printf 'sentinel\n' >"$sentinel"
    qe_cleanup_register "$managed" || return 1
    qe_cleanup_all || return 1
    [ ! -e "$managed" ] || fail 'registered path was not removed'
    [ -f "$sentinel" ] || fail 'unregistered sibling was removed'
    assert_eq sentinel "$(cat "$sentinel")" 'unregistered sibling changed'
}

test_cleanup_registry_rejects_unmanaged_path() {
    local parent unmanaged
    parent="$(new_sandbox)" || return 1
    unmanaged="$parent/not-managed"
    mkdir -p "$unmanaged"
    if qe_cleanup_register "$unmanaged"; then
        fail 'unmanaged path was accepted'
    fi
    qe_cleanup_all || return 1
    [ -d "$unmanaged" ] || fail 'rejected path was removed'
}

test_cleanup_unregister_preserves_unregistered_path() {
    local parent first second
    parent="$(new_sandbox)" || return 1
    first="$parent/.qbox-first"
    second="$parent/.qbox-second"
    mkdir -p "$first" "$second"
    qe_cleanup_register "$first" || return 1
    qe_cleanup_register "$second" || return 1
    qe_cleanup_unregister "$first" || return 1
    qe_cleanup_all || return 1
    [ -d "$first" ] || fail 'unregistered path was removed'
    [ ! -e "$second" ] || fail 'remaining registered path was not removed'
}

test_with_temp_dir_cleans_success() {
    local parent seen
    parent="$(new_sandbox)" || return 1
    callback() { seen="$1"; [ -d "$1" ]; }
    qe_with_temp_dir callback "$parent" unit || return 1
    [ ! -e "$seen" ] || fail 'successful callback left its temp directory'
}

test_with_temp_dir_preserves_status() {
    local parent status
    parent="$(new_sandbox)" || return 1
    callback() { return 23; }
    qe_with_temp_dir callback "$parent" failure
    status=$?
    assert_eq 23 "$status" 'callback status changed'
    [ -z "$(find "$parent" -mindepth 1 -print -quit)" ] || fail 'failure left temp files'
}

test_with_temp_dir_relative_parent_cleans_after_callback_cd() {
    local parent relative_parent sentinel seen status temp_dir
    parent="$(new_sandbox)" || return 1
    relative_parent="$parent/relative"
    sentinel="$relative_parent/sentinel"
    seen="$parent/seen"
    mkdir -p "$relative_parent"
    printf 'keep me\n' >"$sentinel"
    (
        cd "$parent" || exit 1
        callback() {
            cd "$1" || return 1
            printf '%s\n' "$PWD" >"$seen"
        }
        qe_with_temp_dir callback relative unit
        status=$?
        cd "$parent" || exit 1
        [ "$status" -eq 0 ] || exit "$status"
        [ -s "$seen" ] || exit 1
        temp_dir="$(cat "$seen")"
        [ ! -e "$temp_dir" ] || exit 1
        [ -f "$sentinel" ] || exit 1
        [ "$(cat "$sentinel")" = 'keep me' ] || exit 1
    ) || fail 'relative parent cleanup did not survive callback cd'
}

test_atomic_rewrite_rolls_back() {
    local parent target status
    parent="$(new_sandbox)" || return 1
    target="$parent/input.in"
    printf 'original\n' >"$target"
    bad_writer() { printf 'partial\n'; return 9; }
    qe_atomic_rewrite "$target" bad_writer
    status=$?
    assert_eq 9 "$status" 'writer status changed' || return 1
    assert_eq original "$(cat "$target")" 'failed writer replaced target'
}

test_atomic_rewrite_replaces_target() {
    local parent target mode
    parent="$(new_sandbox)" || return 1
    target="$parent/input.in"
    printf 'original\n' >"$target"
    chmod 640 "$target"
    mode="$(stat -c '%a' "$target")"
    good_writer() { printf 'replacement\n'; }
    qe_atomic_rewrite "$target" good_writer || return 1
    assert_eq replacement "$(cat "$target")" 'successful writer did not replace target'
    assert_eq "$mode" "$(stat -c '%a' "$target")" 'target mode changed'
    [ -z "$(find "$parent" -mindepth 1 -name '.*.qbox.*' -print -quit)" ] || fail 'atomic rewrite left temp files'
}

test_atomic_rewrite_rejects_directory_target() {
    local parent target sentinel writer_marker mktemp_marker status
    parent="$(new_sandbox)" || return 1
    target="$parent/output"
    sentinel="$target/sentinel"
    writer_marker="$parent/writer-called"
    mktemp_marker="$parent/mktemp-called"
    mkdir -p "$target"
    printf 'keep me\n' >"$sentinel"
    mktemp() {
        : >"$mktemp_marker"
        command mktemp "$@"
    }
    writer() {
        : >"$writer_marker"
        printf 'replacement\n'
    }
    qe_atomic_rewrite "$target" writer
    status=$?
    [ "$status" -ne 0 ] || { fail 'directory target was accepted'; return 1; }
    [ ! -e "$mktemp_marker" ] || { fail 'directory target created a temp file'; return 1; }
    [ ! -e "$writer_marker" ] || { fail 'directory target called its writer'; return 1; }
    [ -f "$sentinel" ] || { fail 'directory target was modified'; return 1; }
    assert_eq 'keep me' "$(cat "$sentinel")" 'directory target sentinel changed' || return 1
    [ -z "$(find "$target" -mindepth 1 -maxdepth 1 -name '.*.qbox.*' -print -quit)" ] || { fail 'directory target leaked a temp file'; return 1; }
}

test_atomic_rewrite_handles_leading_dash_target() {
    local parent status error_file
    parent="$(new_sandbox)" || return 1
    error_file="$parent/leading-dash.err"
    (
        cd "$parent" || exit 1
        printf 'original\n' >'-input.in'
        writer() { printf 'replacement\n'; }
        qe_atomic_rewrite '-input.in' writer 2>"$error_file"
        status=$?
        [ "$status" -eq 0 ] || exit 1
        [ ! -s "$error_file" ] || exit 1
        [ "$(cat -- '-input.in')" = 'replacement' ] || exit 1
        [ -z "$(find "$parent" -mindepth 1 -name '.*.qbox.*' -print -quit)" ] || exit 1
    ) || fail 'leading-dash target was not atomically replaced'
}

test_atomic_rewrite_rejects_symlink_to_file() {
    local parent source target writer_marker mktemp_marker target_inode status
    parent="$(new_sandbox)" || return 1
    source="$parent/source.in"
    target="$parent/link.in"
    writer_marker="$parent/writer-called"
    mktemp_marker="$parent/mktemp-called"
    printf 'original\n' >"$source"
    ln -s "$(basename "$source")" "$target"
    target_inode="$(stat -c '%i' "$target")"
    mktemp() {
        : >"$mktemp_marker"
        command mktemp "$@"
    }
    writer() {
        : >"$writer_marker"
        printf 'replacement\n'
    }
    qe_atomic_rewrite "$target" writer
    status=$?
    [ "$status" -ne 0 ] || { fail 'symlink-to-file target was accepted'; return 1; }
    [ -L "$target" ] || { fail 'symlink-to-file target was replaced'; return 1; }
    assert_eq source.in "$(readlink "$target")" 'symlink-to-file target changed' || return 1
    assert_eq "$target_inode" "$(stat -c '%i' "$target")" 'symlink-to-file directory entry changed' || return 1
    assert_eq original "$(cat "$target")" 'symlink-to-file destination changed' || return 1
    [ ! -e "$mktemp_marker" ] || { fail 'symlink-to-file target created a temp file'; return 1; }
    [ ! -e "$writer_marker" ] || { fail 'symlink-to-file target called its writer'; return 1; }
    [ -z "$(find "$parent" -name '.*.qbox.*' -print -quit)" ] || { fail 'symlink-to-file target leaked a temp file'; return 1; }
}

test_atomic_rewrite_rejects_dangling_symlink() {
    local parent target destination writer_marker mktemp_marker target_inode status
    parent="$(new_sandbox)" || return 1
    target="$parent/dangling.in"
    destination='missing.in'
    writer_marker="$parent/writer-called"
    mktemp_marker="$parent/mktemp-called"
    ln -s "$destination" "$target"
    target_inode="$(stat -c '%i' "$target")"
    mktemp() {
        : >"$mktemp_marker"
        command mktemp "$@"
    }
    writer() {
        : >"$writer_marker"
        printf 'replacement\n'
    }
    qe_atomic_rewrite "$target" writer
    status=$?
    [ "$status" -ne 0 ] || { fail 'dangling symlink target was accepted'; return 1; }
    [ -L "$target" ] || { fail 'dangling symlink target was replaced'; return 1; }
    assert_eq "$destination" "$(readlink "$target")" 'dangling symlink target changed' || return 1
    assert_eq "$target_inode" "$(stat -c '%i' "$target")" 'dangling symlink directory entry changed' || return 1
    [ ! -e "$target" ] || { fail 'dangling symlink unexpectedly became live'; return 1; }
    [ ! -e "$mktemp_marker" ] || { fail 'dangling symlink target created a temp file'; return 1; }
    [ ! -e "$writer_marker" ] || { fail 'dangling symlink target called its writer'; return 1; }
    [ -z "$(find "$parent" -name '.*.qbox.*' -print -quit)" ] || { fail 'dangling symlink target leaked a temp file'; return 1; }
}

test_test_mode_preserves_caller_traps() {
    env -i PATH="$PATH" HOME="${HOME:-/tmp}" TMPDIR="${TMPDIR:-/tmp}" \
        bash --noprofile --norc -c '
            trap : EXIT
            before="$(trap -p EXIT)"
            QBOX_TEST_MODE=1 source "$1"
            after="$(trap -p EXIT)"
            [ "$before" = "$after" ]
        ' _ "$PROJECT_ROOT/qbox"
}

test_cleanup_trap_removes_exact_directory() {
    local parent sentinel record worker_pid status temp_dir output
    parent="$(new_sandbox)" || return 1
    sentinel="$parent/sentinel"
    record="$parent/record"
    output="$parent/worker.out"
    printf 'keep me\n' >"$sentinel"
    env -i PATH="$PATH" HOME="${HOME:-/tmp}" TMPDIR="${TMPDIR:-/tmp}" \
        bash --noprofile --norc -c '
            QBOX_TEST_MODE=1 source "$1"
            parent="$2"
            record="$3"
            callback() {
                printf "%s\n" "$1" >"$record"
                while :; do sleep 1; done
            }
            qe_install_cleanup_traps
            qe_with_temp_dir callback "$parent" signal
        ' _ "$PROJECT_ROOT/qbox" "$parent" "$record" >"$output" 2>&1 &
    worker_pid=$!

    for _ in $(seq 1 300); do
        [ -s "$record" ] && break
        kill -0 "$worker_pid" 2>/dev/null || break
        sleep 0.01
    done
    [ -s "$record" ] || {
        wait "$worker_pid" 2>/dev/null || true
        output="$(cat "$output" 2>/dev/null || true)"
        fail "cleanup worker did not record its temp directory: $output"
        return 1
    }
    temp_dir="$(cat "$record")"
    [ -d "$temp_dir" ] || fail 'callback did not receive a temp directory' || return 1
    kill -TERM "$worker_pid" 2>/dev/null || true
    wait "$worker_pid"
    status=$?
    assert_eq 143 "$status" 'TERM status changed' || return 1
    [ ! -e "$temp_dir" ] || fail 'TERM left the registered temp directory'
    [ -f "$sentinel" ] || fail 'TERM removed a sibling sentinel'
    assert_eq 'keep me' "$(cat "$sentinel")" 'TERM changed a sibling sentinel'
}

test_conver_preserves_user_energy_file() {
    local parent output sentinel status
    parent="$(new_sandbox)" || return 1
    output="$parent/sample.out"
    sentinel="$parent/sample_ener-user.dat"
    cat >"$output" <<'EOF'
!    total energy              =   -100.0000 Ry
!    total energy              =    -99.9000 Ry
!    total energy              =    -99.8000 Ry
!    total energy              =    -99.7000 Ry
!    total energy              =    -99.6000 Ry
!    total energy              =    -99.5000 Ry
EOF
    printf 'user-owned convergence data\n' >"$sentinel"
    (
        cd "$parent" || exit 1
        fname1="$output"
        prefix='sample'
        conver
    ) >"$parent/conver.out" 2>&1
    status=$?
    assert_eq 0 "$status" 'conver failed with the configured plotting environment' || return 1
    assert_eq 'user-owned convergence data' "$(cat "$sentinel")" 'conver changed the user energy sentinel' || return 1
    [ -s "$parent/sample_energy_convergence.png" ] || { fail 'conver did not create the PNG'; return 1; }
    [ -s "$parent/sample_energy_convergence.svg" ] || { fail 'conver did not create the SVG'; return 1; }
    [ ! -e "$parent/sample_ener1.dat" ] || { fail 'conver left first energy scratch data'; return 1; }
    [ ! -e "$parent/sample_ener2.dat" ] || { fail 'conver left all energy scratch data'; return 1; }
    [ ! -e "$parent/sample_ener3.dat" ] || { fail 'conver left last energy scratch data'; return 1; }
}

test_cluster_velocity_concurrent_sandboxes_preserve_sentinels() {
    local first second barrier_dir first_status second_status first_pid second_pid sandbox
    local first_path second_path test_status
    first="$(new_sandbox)" || return 1
    second="$(new_sandbox)" || return 1
    barrier_dir="$(new_sandbox)" || return 1
    for sandbox in "$first" "$second"; do
        cat >"$sandbox/molecule.cif" <<'EOF'
data_molecule
loop_
_atom_site_type_symbol
_atom_site_label
C C1
H H1
EOF
        printf 'user-owned symbols\n' >"$sandbox/.atomic_velocity_symbols.tmp"
    done

    run_cluster_velocity() {
        local sandbox="$1" label="$2"
        (
            cd "$sandbox" || exit 1
            printf '0\n' | env -i PATH="$PATH" HOME="${HOME:-/tmp}" TMPDIR="${TMPDIR:-/tmp}" \
                QBOX_TEST_MODE=1 bash --noprofile --norc -c '
                    source "$1"
                    fname1="$2"
                    qe_set_input_path "$fname1" || exit 1
                    barrier_dir="$3"
                    barrier_label="$4"
                    barrier_armed=1
                    awk() {
                        local observed
                        if [ "${barrier_armed:-0}" = 1 ] && [ -n "${symbols_file:-}" ]; then
                            barrier_armed=0
                            case "$symbols_file" in
                                /*) observed="$symbols_file" ;;
                                *) observed="$PWD/$symbols_file" ;;
                            esac
                            printf "%s\n" "$observed" >"$barrier_dir/path-$barrier_label"
                            : >"$barrier_dir/ready-$barrier_label"
                            while [ ! -e "$barrier_dir/release" ]; do sleep 0.01; done
                        fi
                        command awk "$@"
                    }
                    cluster_velocities
                ' _ "$PROJECT_ROOT/qbox" "$sandbox/molecule.cif" "$barrier_dir" "$label"
        ) >"$sandbox/cluster.out" 2>&1
    }

    run_cluster_velocity "$first" first & first_pid=$!
    run_cluster_velocity "$second" second & second_pid=$!
    for _ in $(seq 1 500); do
        if [ -e "$barrier_dir/ready-first" ] && [ -e "$barrier_dir/ready-second" ]; then
            break
        fi
        if ! kill -0 "$first_pid" 2>/dev/null || ! kill -0 "$second_pid" 2>/dev/null; then
            break
        fi
        sleep 0.01
    done

    test_status=0
    if [ ! -e "$barrier_dir/ready-first" ] || [ ! -e "$barrier_dir/ready-second" ]; then
        fail 'cluster velocity subprocesses did not reach the in-flight barrier'
        test_status=1
    else
        first_path="$(cat "$barrier_dir/path-first")"
        second_path="$(cat "$barrier_dir/path-second")"
        [ -e "$first_path" ] || { fail 'first cluster scratch path was not active before release'; test_status=1; }
        [ -e "$second_path" ] || { fail 'second cluster scratch path was not active before release'; test_status=1; }
        [ "$first_path" != "$second_path" ] || { fail 'cluster scratch paths collided'; test_status=1; }
        case "$first_path" in
            "$first"/.qbox-cluster-velocities.*/symbols) ;;
            *) fail 'first cluster scratch path escaped its callback directory'; test_status=1 ;;
        esac
        case "$second_path" in
            "$second"/.qbox-cluster-velocities.*/symbols) ;;
            *) fail 'second cluster scratch path escaped its callback directory'; test_status=1 ;;
        esac
        [ ! -e "$first/symbols" ] || { fail 'first caller cwd contains an internal symbols file before release'; test_status=1; }
        [ ! -e "$second/symbols" ] || { fail 'second caller cwd contains an internal symbols file before release'; test_status=1; }
        [ ! -e "$first/molecule_QE.tmp" ] || { fail 'first caller cwd contains a Multiwfn scratch file before release'; test_status=1; }
        [ ! -e "$second/molecule_QE.tmp" ] || { fail 'second caller cwd contains a Multiwfn scratch file before release'; test_status=1; }
        assert_eq 'user-owned symbols' "$(cat "$first/.atomic_velocity_symbols.tmp")" \
            'first cluster process changed the sentinel before release' || test_status=1
        assert_eq 'user-owned symbols' "$(cat "$second/.atomic_velocity_symbols.tmp")" \
            'second cluster process changed the sentinel before release' || test_status=1
    fi

    : >"$barrier_dir/release"
    wait "$first_pid"
    first_status=$?
    wait "$second_pid"
    second_status=$?
    assert_eq 0 "$first_status" 'first cluster velocity subprocess failed' || test_status=1
    assert_eq 0 "$second_status" 'second cluster velocity subprocess failed' || test_status=1

    for sandbox in "$first" "$second"; do
        assert_eq 'user-owned symbols' "$(cat "$sandbox/.atomic_velocity_symbols.tmp")" \
            'cluster velocity changed the user symbols sentinel' || test_status=1
        [ -s "$sandbox/ATOMICs_VELOCITIES" ] || { fail 'cluster velocity did not create its public output'; test_status=1; }
        [ ! -e "$sandbox/symbols" ] || { fail 'cluster velocity left an internal symbols file'; test_status=1; }
        [ ! -e "$sandbox/molecule_QE.tmp" ] || { fail 'cluster velocity left a Multiwfn scratch file'; test_status=1; }
        [ -z "$(find "$sandbox" -maxdepth 1 -type d -name '.qbox-cluster-velocities.*' -print -quit)" ] || {
            fail 'cluster velocity left its temporary callback directory'
            test_status=1
        }
    done
    return "$test_status"
}

run_test 'cleanup removes registered path only' test_cleanup_registry_removes_registered_path_only
run_test 'cleanup rejects unmanaged path' test_cleanup_registry_rejects_unmanaged_path
run_test 'cleanup unregister preserves path' test_cleanup_unregister_preserves_unregistered_path
run_test 'temporary directory cleans on success' test_with_temp_dir_cleans_success
run_test 'temporary directory preserves callback status' test_with_temp_dir_preserves_status
run_test 'relative parent cleanup survives callback cd' test_with_temp_dir_relative_parent_cleans_after_callback_cd
run_test 'atomic rewrite rolls back on writer failure' test_atomic_rewrite_rolls_back
run_test 'atomic rewrite replaces target' test_atomic_rewrite_replaces_target
run_test 'atomic rewrite rejects directory target' test_atomic_rewrite_rejects_directory_target
run_test 'atomic rewrite handles leading-dash target' test_atomic_rewrite_handles_leading_dash_target
run_test 'atomic rewrite rejects symlink-to-file target' test_atomic_rewrite_rejects_symlink_to_file
run_test 'atomic rewrite rejects dangling symlink target' test_atomic_rewrite_rejects_dangling_symlink
run_test 'test mode preserves caller traps' test_test_mode_preserves_caller_traps
run_test 'cleanup trap removes exact directory' test_cleanup_trap_removes_exact_directory
run_test 'conver preserves user energy file' test_conver_preserves_user_energy_file
run_test 'cluster velocity sandboxes preserve sentinels' test_cluster_velocity_concurrent_sandboxes_preserve_sentinels
finish_tests
