#!/usr/bin/env bash
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test_helper.sh"
source_qbox

# Exercise the real input preparation and stage runner. The mock executables
# enforce QE's directory/prefix contract instead of accepting empty inputs.
test_band_stages_share_scf_data() {
    local sandbox bin scratch="$1" reuse="$2" output
    sandbox="$(new_sandbox)" || return 1
    bin="$sandbox/bin"
    mkdir -p "$bin" "$sandbox/BAND"
    [ "$scratch" != absolute ] || scratch="$sandbox/custom scratch"
    cat >"$sandbox/sample.scf.in" <<EOF_SCF
&CONTROL
 calculation = 'scf',
 prefix = 'sample',
 outdir = '$scratch',
/
EOF_SCF
    sed "s/'scf'/'bands'/" "$sandbox/sample.scf.in" >"$sandbox/BAND/sample.bands.in"
    cat >"$sandbox/BAND/bands.in" <<EOF_BANDS
&BANDS
 prefix = 'sample',
 outdir = '$scratch',
 filband = 'bands.dat',
/
EOF_BANDS
    cat >"$bin/qe-mock" <<'EOF_MOCK'
#!/usr/bin/env python3
import os
from pathlib import Path
import re
import sys

text = Path(sys.argv[sys.argv.index('-in') + 1]).read_text()
def value(name):
    return re.search(r"\b" + name + r"\s*=\s*'([^']+)'", text).group(1)
saved = Path(value('outdir')) / (value('prefix') + '.save')
stage = value('calculation') if Path(sys.argv[0]).name == 'pw.x' else 'bands.x'
with open(os.environ['QBOX_HANDOFF_LOG'], 'a') as log:
    log.write(stage + '|' + str(saved.resolve()) + '\n')
if stage == 'scf':
    saved.mkdir(parents=True, exist_ok=True)
    (saved / 'charge-density.dat').write_text('SCF data')
elif not (saved / 'charge-density.dat').is_file():
    print('Error in routine iosys (1):')
    print('bands or non-scf calculation not possible: needed files are missing')
    sys.exit(1)
if stage == 'bands.x':
    Path(value('filband') + '.gnu').write_text('0.0 1.0\n')
print('JOB DONE.')
EOF_MOCK
    chmod +x "$bin/qe-mock"
    ln -s qe-mock "$bin/pw.x"
    ln -s qe-mock "$bin/bands.x"
    cp "$PROJECT_ROOT/tests/mocks/mpirun" "$bin/mpirun"
    chmod +x "$bin/mpirun"
    (
        cd "$sandbox" || exit 1
        export PATH="$bin:$PATH" QBOX_HANDOFF_LOG="$sandbox/stages.log" QBOX_MOCK_COMMAND_LOG="$sandbox/commands.log"
        if [ "$reuse" = yes ]; then
            mkdir -p "$scratch/sample.save"
            printf 'SCF data' >"$scratch/sample.save/charge-density.dat"
            printf 'JOB DONE.\n' >scf.out
        fi
        qe_prompt_calc_prefix() { printf 'sample\n'; }
        qe_ask_recalculate_band_completed() { printf 'no\n'; }
        qe_prompt_positive_int() { printf '1\n'; }
        qe_ensure_runtime_for() { return 0; }
        qe_report_compute_resources() { :; }
        qe_prompt_energy_reference() { printf 'fermi\n'; }
        qe_embedded_plot_band() { touch "$sandbox/plotted"; }
        run_qe_band_calculation
    ) >"$sandbox/output" 2>&1 || {
        cat "$sandbox/output" >&2
        fail 'bands could not read the SCF save directory'
        return 1
    }
    output="$(cat "$sandbox/output")"
    [ -s "$sandbox/BAND/bands.dat.gnu" ] || { fail 'bands.x wrote outside BAND'; return 1; }
    [ -f "$sandbox/plotted" ] || { fail 'band result was not plotted'; return 1; }
    [ ! -e "$sandbox/BAND/tmp" ] && [ ! -e "$sandbox/BAND/BAND" ] || return 1
    assert_eq 1 "$(cut -d '|' -f 2 "$sandbox/stages.log" | sort -u | wc -l)" \
        'SCF, bands and bands.x resolved different save directories' || return 1
    if [ "$reuse" = yes ]; then
        assert_contains "$output" '跳过 SCF 计算' || return 1
        assert_eq 2 "$(wc -l <"$sandbox/stages.log")" 'existing SCF was recomputed' || return 1
    fi
}

run_test 'band stages share default SCF save directory' test_band_stages_share_scf_data ./tmp no
run_test 'band stages share custom relative SCF save directory' test_band_stages_share_scf_data './scratch data' no
run_test 'band stages share absolute SCF save directory' test_band_stages_share_scf_data absolute no
run_test 'bands resumes a completed SCF from the project directory' test_band_stages_share_scf_data ./tmp yes
finish_tests
