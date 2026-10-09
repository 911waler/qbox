#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox
if [ -f "$PROJECT_ROOT/src/qbox/legacy/phonon_workflows.sh" ]; then
    source "$PROJECT_ROOT/src/qbox/legacy/phonon_workflows.sh"
fi

# The backend is a process boundary tested independently in Python. Keep the
# real menu, resource prompts, stage runner, pipefail and log writing here.
phonon_test_backend() {
    local action="$1" directory='' stage='' source='' item remove=0
    shift
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --directory) directory="$2"; shift 2 ;;
            --stage) stage="$2"; shift 2 ;;
            --source) source="$2"; shift 2 ;;
            *) return 2 ;;
        esac
    done
    [[ "$directory" = /*/PHONON ]] || return 2
    printf '%s|%s|%s\n' "$action" "$stage" "$directory" >>"$QBOX_PHONON_EVENTS"
    case "$action" in
        prepare)
            printf '%s\n' "$source" >"$QBOX_PHONON_SOURCE_LOG"
            [ "${QBOX_PHONON_PREPARE_STATUS:-0}" -eq 0 ] || return "$QBOX_PHONON_PREPARE_STATUS"
            mkdir -p "$directory"
            for item in scf ph q2r matdyn; do
                printf '&input\n nat = 2,\n/\n' >"$directory/sample.$item.in"
            done
            printf '{}\n' >"$directory/sample.path.json"
            ;;
        info) printf '%s\n' "${QBOX_PHONON_INFO:-sample}" ;;
        check) [ -f "$directory/.done.$stage" ] ;;
        begin)
            [ "$stage" != "${QBOX_PHONON_BEGIN_FAIL:-}" ] || return 1
            for item in scf ph q2r matdyn plot; do
                [ "$item" != "$stage" ] || remove=1
                [ "$remove" -eq 0 ] || rm -f "$directory/.done.$item"
            done
            ;;
        finish)
            [ "$stage" != "${QBOX_PHONON_FINISH_FAIL:-}" ] || return 1
            grep -q 'JOB DONE' "$directory/$stage.out" || return 1
            touch "$directory/.done.$stage"
            ;;
        *) return 2 ;;
    esac
}

phonon_test_setup() {
    sandbox="$(new_sandbox)" || return 1
    project="$sandbox/project with spaces"
    mkdir -p "$project" "$sandbox/bin"
    export QBOX_PHONON_COMMANDS="$sandbox/commands" QBOX_PHONON_EVENTS="$sandbox/events"
    export QBOX_PHONON_SOURCE_LOG="$sandbox/source" QBOX_PHONON_EXPECTED_CWD="$project/PHONON"
    : >"$QBOX_PHONON_COMMANDS"
    : >"$QBOX_PHONON_EVENTS"
    cat >"$sandbox/bin/qe-command" <<'EOF_COMMAND'
#!/usr/bin/env bash
program="${0##*/}"
[ "$PWD" = "$QBOX_PHONON_EXPECTED_CWD" ] || exit 91
printf '%s' "$program" >>"$QBOX_PHONON_COMMANDS"
printf ' <%s>' "$@" >>"$QBOX_PHONON_COMMANDS"
printf '\n' >>"$QBOX_PHONON_COMMANDS"
case "$program" in
    pw.x) stage=scf ;;
    ph.x) stage=ph ;;
    q2r.x) stage=q2r ;;
    matdyn.x) stage=matdyn ;;
esac
[ "$stage" != "${QBOX_PHONON_FAIL_STAGE:-}" ] || exit 23
[ "$1" = -in ] && [ -s "$2" ] || exit 92
printf 'JOB DONE.\n'
EOF_COMMAND
    cat >"$sandbox/bin/mpirun" <<'EOF_MPI'
#!/usr/bin/env bash
[ "$1" = -np ] || exit 93
printf 'mpi <%s> <%s>\n' "$2" "$3" >>"$QBOX_PHONON_COMMANDS"
shift 2
exec "$@"
EOF_MPI
    chmod +x "$sandbox/bin/qe-command" "$sandbox/bin/mpirun"
    local program
    for program in pw.x ph.x q2r.x matdyn.x; do
        ln -s qe-command "$sandbox/bin/$program"
    done
    export PATH="$sandbox/bin:$PATH"
    qbox_python() {
        [ "${1-}" = -m ] || return 2
        local module="$2"
        shift 2
        case "$module" in
            qbox.io.phonon_workflow) phonon_test_backend "$@" ;;
            qbox.postprocess.phonon_plot)
                [ "$PWD" = "$QBOX_PHONON_EXPECTED_CWD" ] || return 91
                printf 'plot' >>"$QBOX_PHONON_COMMANDS"
                printf ' <%s>' "$@" >>"$QBOX_PHONON_COMMANDS"
                printf '\n' >>"$QBOX_PHONON_COMMANDS"
                [ "${QBOX_PHONON_FAIL_STAGE:-}" != plot ] || return 23
                printf 'JOB DONE.\n'
                ;;
            *) return 2 ;;
        esac
    }
    qe_ensure_runtime_for() { printf 'runtime <%s>\n' "$*" >>"$QBOX_PHONON_EVENTS"; }
    qe_report_compute_resources() { printf 'resources\n' >>"$QBOX_PHONON_EVENTS"; }
    qe_physical_cpu_cores() { printf '8\n'; }
    cd "$project" || return 1
    fname1="$sandbox/relax input.CIF"
    QE_DIRECT_ACTION=''
    QE_RETURN_TO_MAIN=0
}

phonon_test_run() {
    if ! declare -F run_qe_phonon_calculation >/dev/null; then
        fail 'phonon calculation workflow is not implemented'
        return 1
    fi
    run_qe_phonon_calculation
}

test_phonon_success_uses_isolated_directory_and_serial_postprocessors() {
    local sandbox project
    phonon_test_setup || return 1
    phonon_test_run >"$sandbox/output" 2>&1 <<< $'1\n2\n3' || { cat "$sandbox/output" >&2; return 1; }
    assert_eq "$project" "$PWD" 'workflow changed its caller directory' || return 1
    assert_eq "$fname1" "$(cat "$QBOX_PHONON_SOURCE_LOG")" 'source path with spaces was not preserved' || return 1
    assert_file_equals <(printf '%s\n' \
        'mpi <2> <pw.x>' 'pw.x <-in> <sample.scf.in>' \
        'mpi <3> <ph.x>' 'ph.x <-in> <sample.ph.in>' \
        'q2r.x <-in> <sample.q2r.in>' 'matdyn.x <-in> <sample.matdyn.in>' \
        'plot <-i> <sample.freq.gp> <--path> <sample.path.json>') "$QBOX_PHONON_COMMANDS" || return 1
    local stage
    for stage in scf ph q2r matdyn plot; do
        [ -s "$project/PHONON/$stage.out" ] && [ -f "$project/PHONON/.done.$stage" ] || return 1
    done
    assert_contains "$(cat "$QBOX_PHONON_EVENTS")" 'runtime <mpirun pw.x ph.x q2r.x matdyn.x>' || return 1
    assert_contains "$(cat "$sandbox/output")" "$project/PHONON" || return 1
    assert_eq 0 "$QE_RETURN_TO_MAIN" 'completed calculation requested another main menu'
}

test_phonon_stage_failure_stops_every_downstream_command() {
    local failed sandbox project output rc executed expected
    for failed in scf ph q2r matdyn plot; do
        (
            phonon_test_setup || exit 1
            export QBOX_PHONON_FAIL_STAGE="$failed"
            phonon_test_run >"$sandbox/output" 2>&1 <<< $'1\n2\n3'
            rc=$?
            [ "$rc" -ne 0 ] || { fail "$failed failure returned success"; exit 1; }
            executed="$(sed -nE 's/^(pw.x|ph.x|q2r.x|matdyn.x|plot).*/\1/p' "$QBOX_PHONON_COMMANDS" | paste -sd, -)"
            case "$failed" in
                scf) expected=pw.x ;;
                ph) expected=pw.x,ph.x ;;
                q2r) expected=pw.x,ph.x,q2r.x ;;
                matdyn) expected=pw.x,ph.x,q2r.x,matdyn.x ;;
                plot) expected=pw.x,ph.x,q2r.x,matdyn.x,plot ;;
            esac
            assert_eq "$expected" "$executed" 'failed stage did not stop downstream execution' || exit 1
            [ ! -f "$project/PHONON/.done.$failed" ] || exit 1
            assert_contains "$(cat "$sandbox/output")" '失败' || exit 1
        ) || return 1
    done
}

test_phonon_finish_failure_is_not_marked_success() {
    local sandbox project
    phonon_test_setup || return 1
    QBOX_PHONON_FINISH_FAIL=ph phonon_test_run >"$sandbox/output" 2>&1 <<< $'1\n2\n3'
    [ "$?" -ne 0 ] || return 1
    assert_not_contains "$(cat "$QBOX_PHONON_COMMANDS")" 'q2r.x' || return 1
    [ ! -f "$project/PHONON/.done.ph" ]
}

test_phonon_resume_runs_only_failed_and_later_stages() {
    local sandbox project
    phonon_test_setup || return 1
    export QBOX_PHONON_FAIL_STAGE=ph
    phonon_test_run >"$sandbox/first" 2>&1 <<< $'1\n2\n3'
    [ "$?" -ne 0 ] || return 1
    unset QBOX_PHONON_FAIL_STAGE
    : >"$QBOX_PHONON_COMMANDS"
    phonon_test_run >"$sandbox/second" 2>&1 <<< $'1\n1\n3' || { cat "$sandbox/second" >&2; return 1; }
    assert_not_contains "$(cat "$QBOX_PHONON_COMMANDS")" 'pw.x' || return 1
    assert_contains "$(cat "$QBOX_PHONON_COMMANDS")" 'ph.x <-in> <sample.ph.in>' || return 1
    [ -f "$project/PHONON/.done.plot" ]
}

test_phonon_completed_run_skips_environment_and_all_commands() {
    local sandbox project
    phonon_test_setup || return 1
    phonon_test_run >"$sandbox/first" 2>&1 <<< $'1\n2\n3' || return 1
    : >"$QBOX_PHONON_COMMANDS"
    : >"$QBOX_PHONON_EVENTS"
    phonon_test_run >"$sandbox/second" 2>&1 <<< $'1\n1' || return 1
    [ ! -s "$QBOX_PHONON_COMMANDS" ] || return 1
    assert_not_contains "$(cat "$QBOX_PHONON_EVENTS")" runtime || return 1
    assert_not_contains "$(cat "$QBOX_PHONON_EVENTS")" resources || return 1
    assert_contains "$(cat "$sandbox/second")" '跳过'
}

test_phonon_recalculate_invalidates_completed_downstream() {
    local sandbox project
    phonon_test_setup || return 1
    phonon_test_run >"$sandbox/first" 2>&1 <<< $'1\n2\n3' || return 1
    cp "$QBOX_PHONON_COMMANDS" "$sandbox/expected"
    : >"$QBOX_PHONON_COMMANDS"
    phonon_test_run >"$sandbox/second" 2>&1 <<< $'1\n2\n2\n3' || return 1
    assert_file_equals "$sandbox/expected" "$QBOX_PHONON_COMMANDS" 'recalculation skipped old downstream results'
}

test_phonon_cancel_return_and_eof_launch_no_program() {
    local mode sandbox project rc
    for mode in return direct_return prepare_cancel prepare_failure eof; do
        (
            phonon_test_setup || exit 1
            case "$mode" in
                return) phonon_test_run <<<2 >"$sandbox/output" 2>&1; rc=$? ;;
                direct_return) QE_DIRECT_ACTION=40; phonon_test_run <<<2 >"$sandbox/output" 2>&1; rc=$? ;;
                prepare_cancel) QBOX_PHONON_PREPARE_STATUS=10 phonon_test_run <<<1 >"$sandbox/output" 2>&1; rc=$? ;;
                prepare_failure) QBOX_PHONON_PREPARE_STATUS=1 phonon_test_run <<<1 >"$sandbox/output" 2>&1; rc=$? ;;
                eof) phonon_test_run </dev/null >"$sandbox/output" 2>&1; rc=$? ;;
            esac
            [ ! -s "$QBOX_PHONON_COMMANDS" ] || exit 1
            case "$mode" in
                return|prepare_cancel) assert_eq 0 "$rc" && assert_eq 1 "$QE_RETURN_TO_MAIN" || exit 1 ;;
                direct_return) assert_eq 0 "$rc" && assert_eq 0 "$QE_RETURN_TO_MAIN" || exit 1 ;;
                *) [ "$rc" -ne 0 ] || exit 1 ;;
            esac
        ) || return 1
    done
}

test_phonon_bad_backend_prefix_launches_no_program() {
    local sandbox project
    phonon_test_setup || return 1
    QBOX_PHONON_INFO='../outside' phonon_test_run <<<1 >"$sandbox/output" 2>&1
    [ "$?" -ne 0 ] && [ ! -s "$QBOX_PHONON_COMMANDS" ]
}

test_phonon_defaults_and_mpi_prompt_eof() {
    local sandbox project
    phonon_test_setup || return 1
    phonon_test_run >"$sandbox/first" 2>&1 < <(printf '1\n\n')
    [ "$?" -ne 0 ] && [ ! -s "$QBOX_PHONON_COMMANDS" ] || return 1
    phonon_test_run >"$sandbox/second" 2>&1 <<< $'1\n\n' || return 1
    assert_contains "$(cat "$QBOX_PHONON_COMMANDS")" 'mpi <8> <pw.x>' || return 1
    assert_contains "$(cat "$QBOX_PHONON_COMMANDS")" 'mpi <8> <ph.x>'
}

test_phonon_plot_only_recovery_does_not_request_qe() {
    local sandbox project
    phonon_test_setup || return 1
    phonon_test_run >"$sandbox/first" 2>&1 <<< $'1\n2\n3' || return 1
    rm "$project/PHONON/.done.plot"
    : >"$QBOX_PHONON_COMMANDS"
    : >"$QBOX_PHONON_EVENTS"
    phonon_test_run >"$sandbox/second" 2>&1 <<< $'1\n1' || return 1
    assert_file_equals <(printf '%s\n' 'plot <-i> <sample.freq.gp> <--path> <sample.path.json>') "$QBOX_PHONON_COMMANDS" || return 1
    assert_not_contains "$(cat "$QBOX_PHONON_EVENTS")" runtime
}

test_phonon_recalculation_eof_does_not_invalidate_results() {
    local sandbox project
    phonon_test_setup || return 1
    phonon_test_run >"$sandbox/first" 2>&1 <<< $'1\n2\n3' || return 1
    : >"$QBOX_PHONON_COMMANDS"
    : >"$QBOX_PHONON_EVENTS"
    phonon_test_run >"$sandbox/second" 2>&1 < <(printf '1\n')
    [ "$?" -ne 0 ] && [ ! -s "$QBOX_PHONON_COMMANDS" ] || return 1
    assert_not_contains "$(cat "$QBOX_PHONON_EVENTS")" 'begin|' || return 1
    [ -f "$project/PHONON/.done.plot" ]
}

test_phonon_stage_contract_and_begin_failures_stop_execution() {
    local mode sandbox project rc
    for mode in begin contract runtime; do
        (
            phonon_test_setup || exit 1
            case "$mode" in
                begin) export QBOX_PHONON_BEGIN_FAIL=scf ;;
                contract) qe_run_stage() { return 2; } ;;
                runtime) qe_ensure_runtime_for() { return 1; } ;;
            esac
            phonon_test_run >"$sandbox/output" 2>&1 <<< $'1\n2\n3'
            rc=$?
            if [ "$mode" = contract ]; then
                assert_eq 2 "$rc" 'stage contract error was swallowed' || exit 1
            else
                [ "$rc" -ne 0 ] || exit 1
            fi
            [ ! -s "$QBOX_PHONON_COMMANDS" ] || exit 1
            assert_not_contains "$(cat "$QBOX_PHONON_EVENTS")" 'begin|ph|' || exit 1
        ) || return 1
    done
}

test_phonon_real_backend_and_plotter_validate_mock_qe_products() {
    local sandbox project program
    sandbox="$(new_sandbox)" || return 1
    project="$sandbox/real backend with spaces"
    mkdir -p "$project/pseudo" "$sandbox/bin"
    cat >"$project/source input.scf.in" <<'EOF_SCF'
&CONTROL calculation='scf', prefix='silicon', outdir='../old-tmp', pseudo_dir='./pseudo' /
&SYSTEM ibrav=0, nat=2, ntyp=1, ecutwfc=20, occupations='fixed' /
&ELECTRONS conv_thr=1d-10 /
ATOMIC_SPECIES
Si 28.085 Si.upf
CELL_PARAMETERS angstrom
0 2.7 2.7
2.7 0 2.7
2.7 2.7 0
ATOMIC_POSITIONS crystal
Si 0 0 0
Si .25 .25 .25
K_POINTS automatic
2 2 2 0 0 0
EOF_SCF
    cp "$project/source input.scf.in" "$sandbox/original.scf.in"
    printf '<UPF><PP_HEADER pseudo_type="NC" functional="PBE"/></UPF>\n' >"$project/pseudo/Si.upf"
    cat >"$sandbox/bin/qe-products" <<'EOF_PRODUCTS'
#!/usr/bin/env python3
import json
import math
import os
from pathlib import Path
import sys

root = Path.cwd()
assert str(root) == os.environ['QBOX_PHONON_EXPECTED_CWD']
assert sys.argv[1] == '-in' and Path(sys.argv[2]).is_file()
name = Path(sys.argv[0]).name
with open(os.environ['QBOX_PHONON_COMMANDS'], 'a') as log:
    log.write(name + '\n')
if name == 'pw.x':
    saved = root / 'tmp/silicon.save'
    saved.mkdir(parents=True, exist_ok=True)
    (saved / 'data-file-schema.xml').write_text('<espresso><output/></espresso>')
    (saved / 'charge-density.dat').write_bytes(b'charge data')
    (saved / 'wfc1.dat').write_bytes(b'wave function data')
    print('convergence has been achieved in 8 iterations')
elif name == 'ph.x':
    (root / 'silicon.dyn0').write_text('4 4 4\n1\n0 0 0\n')
    (root / 'silicon.dyn1').write_text('Dynamical matrix file\nforce constants\n')
elif name == 'q2r.x':
    (root / 'silicon.fc').write_text('interatomic force constants\n')
elif name == 'matdyn.x':
    points = json.loads((root / 'silicon.path.json').read_text())['qpoints_matdyn']
    text = f'&plot nbnd=6, nks={len(points)} /\n'
    for row in points:
        text += ' '.join(f'{value:.8f}' for value in row) + '\n-1 0 1 2 3 4\n'
    (root / 'silicon.freq').write_text(text)
    distances = [0.0]
    for first, second in zip(points, points[1:]):
        distances.append(distances[-1] + math.dist(first, second))
    (root / 'silicon.freq.gp').write_text(''.join(f'{distance:.8f} -1 0 1 2 3 4\n' for distance in distances))
else:
    raise AssertionError(name)
print('JOB DONE.')
EOF_PRODUCTS
    cat >"$sandbox/bin/mpirun" <<'EOF_MPI'
#!/usr/bin/env bash
[ "$1" = -np ] || exit 2
shift 2
exec "$@"
EOF_MPI
    chmod +x "$sandbox/bin/qe-products" "$sandbox/bin/mpirun"
    for program in pw.x ph.x q2r.x matdyn.x; do
        ln -s qe-products "$sandbox/bin/$program"
    done
    export PATH="$sandbox/bin:$PATH" MPLBACKEND=Agg
    export QBOX_PHONON_COMMANDS="$sandbox/commands" QBOX_PHONON_EXPECTED_CWD="$project/PHONON"
    : >"$QBOX_PHONON_COMMANDS"
    # Give Python's interactive settings their own input stream, as a human
    # answers those prompts before the later shell MPI prompts appear.
    qbox_python() {
        if [ "${1-}" = -m ] && [ "${2-}" = qbox.io.phonon_workflow ] && [ "${3-}" = prepare ]; then
            "$QBOX_PYTHON" "$@" <<<"${QBOX_PHONON_PREPARE_ANSWERS:-$'3\n'}"
        else
            "$QBOX_PYTHON" "$@"
        fi
    }
    qe_ensure_runtime_for() { return 0; }
    qe_report_compute_resources() { :; }
    qe_physical_cpu_cores() { printf '8\n'; }
    cd "$project" || return 1
    fname1="$project/source input.scf.in"
    QE_DIRECT_ACTION=40
    phonon_test_run >"$sandbox/output" 2>&1 <<< $'1\n2\n3' || { cat "$sandbox/output" >&2; return 1; }
    assert_file_equals "$sandbox/original.scf.in" "$fname1" 'workflow modified the source SCF' || return 1
    assert_file_equals <(printf '%s\n' pw.x ph.x q2r.x matdyn.x) "$QBOX_PHONON_COMMANDS" || return 1
    [ -s PHONON/silicon_phonon.png ] && [ -s PHONON/silicon_phonon.svg ] || return 1
    qbox_python -m qbox.io.phonon_workflow check --directory "$project/PHONON" --stage plot || return 1
    [ ! -e scf.out ] && [ ! -e tmp ] && [ ! -e "$sandbox/old-tmp" ] || return 1
    : >"$QBOX_PHONON_COMMANDS"
    QBOX_PHONON_PREPARE_ANSWERS=0 phonon_test_run >"$sandbox/resume" 2>&1 <<< $'1\n1' || { cat "$sandbox/resume" >&2; return 1; }
    [ ! -s "$QBOX_PHONON_COMMANDS" ]
}

run_test 'phonon workflow preserves cwd paths and serial postprocessing' test_phonon_success_uses_isolated_directory_and_serial_postprocessors
run_test 'phonon stage failures stop every downstream command' test_phonon_stage_failure_stops_every_downstream_command
run_test 'phonon result validation failure stops downstream commands' test_phonon_finish_failure_is_not_marked_success
run_test 'phonon resumes only failed and later stages' test_phonon_resume_runs_only_failed_and_later_stages
run_test 'completed phonon run skips runtime setup and commands' test_phonon_completed_run_skips_environment_and_all_commands
run_test 'phonon recalculation invalidates completed downstream stages' test_phonon_recalculate_invalidates_completed_downstream
run_test 'phonon cancellation return and EOF execute no command' test_phonon_cancel_return_and_eof_launch_no_program
run_test 'phonon rejects an unsafe backend prefix' test_phonon_bad_backend_prefix_launches_no_program
run_test 'phonon MPI defaults work and EOF executes nothing' test_phonon_defaults_and_mpi_prompt_eof
run_test 'phonon plot-only recovery needs no QE environment' test_phonon_plot_only_recovery_does_not_request_qe
run_test 'phonon recalculation EOF preserves completed results' test_phonon_recalculation_eof_does_not_invalidate_results
run_test 'phonon contract begin and runtime failures stop execution' test_phonon_stage_contract_and_begin_failures_stop_execution
run_test 'phonon real backend and plotter validate mock QE products' test_phonon_real_backend_and_plotter_validate_mock_qe_products
finish_tests
