#!/usr/bin/env bash
# Target-side integration: base utilities until the verified bundled Python runs.
set -euo pipefail
[[ $# == 2 ]] || { echo 'usage: run-target.sh BUNDLE_DIR EVIDENCE_DIR' >&2; exit 2; }
bundle=$(readlink -f -- "$1")
evidence=$(readlink -m -- "$2")
[[ $EUID != 0 ]] || { echo 'ordinary user required' >&2; exit 2; }
mkdir -p -- "$evidence"
sandbox=$(mktemp -d "${TMPDIR:-/tmp}/qbox-target.XXXXXXXX")
export HOME="$sandbox/home" TMPDIR="$sandbox/tmp"
mkdir -p "$HOME" "$TMPDIR" "$sandbox/commands" "$sandbox/work"
printf 'private shell configuration\n' > "$HOME/.bashrc"
printf '[global]\nindex-url = http://127.0.0.1:9/poison\nno-binary = :all:\ntarget = /forbidden-user-target\nprefix = /forbidden-user-prefix\n' > "$HOME/pip.conf"
mkdir -p "$HOME/.config/pip" "$HOME/.pip"
cp "$HOME/pip.conf" "$HOME/.config/pip/pip.conf"
cp "$HOME/pip.conf" "$HOME/.pip/pip.conf"
export QBOX_FORBIDDEN_CALL_LOG="$evidence/forbidden.log"
: > "$QBOX_FORBIDDEN_CALL_LOG"
# An allowlist makes file/ldd/module/lscpu/gawk genuinely unavailable.
for name in bash getconf uname readlink stat sha256sum mktemp cp rm mkdir rmdir mv ln chmod cat env grep sed awk tar gzip dirname basename head tail cut sort tr wc date touch mkfifo sleep kill; do
    executable=$(command -v "$name")
    [[ $executable == /* ]] || executable="/bin/$name"
    ln -s "$executable" "$sandbox/commands/$name"
done
for name in python python3 pip pip3 bc gcc cc curl wget dos2unix gnuplot pw.x mpirun mpiexec Multiwfn unfold.x vasp siesta lmp; do
    cat > "$sandbox/commands/$name" <<'STUB'
#!/bin/bash
printf '%s\n' "${0##*/}" >> "$QBOX_FORBIDDEN_CALL_LOG"
exit 97
STUB
    chmod +x "$sandbox/commands/$name"
done
export PATH="$sandbox/commands"
unset QBOX_PYTHON _QBOX_OFFLINE_ROOT DISPLAY BASH_ENV ENV
export PIP_NO_BINARY=:all: PIP_TARGET=/forbidden-env-target PIP_PREFIX=/forbidden-env-prefix
export PIP_CONFIG_FILE="$HOME/pip.conf" PIP_REQUIRE_VIRTUALENV=1
cd "$sandbox/work"
bash "$bundle/install.sh" > "$evidence/default-install.log" 2>&1
[[ ! -s $QBOX_FORBIDDEN_CALL_LOG ]]
grep -q PATH "$evidence/default-install.log"
release=$(readlink -f "$HOME/.local/share/qbox/current")
printf '%s\n' "$sandbox" > "$evidence/sandbox-path"
printf '%s\n' "$release" > "$evidence/release-path"
export QBOX_E2E_BUNDLE="$bundle" QBOX_E2E_EVIDENCE="$evidence" QBOX_E2E_SANDBOX="$sandbox" QBOX_E2E_RELEASE="$release"
"$release/python/bin/python3" -I -B - <<'PY'
import hashlib, importlib.util, io, json, os, pathlib, shutil, signal, stat, subprocess, sys, tarfile, time, unittest
P = pathlib.Path
bundle=P(os.environ['QBOX_E2E_BUNDLE']); evidence=P(os.environ['QBOX_E2E_EVIDENCE'])
sandbox=P(os.environ['QBOX_E2E_SANDBOX']); release=P(os.environ['QBOX_E2E_RELEASE'])
python=release/'python/bin/python3'; package=release/'python/lib/python3.12/site-packages/qbox'
prefix=release.parent.parent; bindir=P(os.environ['HOME'])/'.local/bin'
work=sandbox/'work'; baseenv=dict(os.environ); commands=sandbox/'commands'
manifest=json.loads((bundle/'manifest.json').read_text())
def sha(path):
    h=hashlib.sha256()
    with P(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def run(args, *, env=None, cwd=work, input=None, timeout=600):
    return subprocess.run(list(map(str,args)),env=env or baseenv,cwd=cwd,input=input,text=True,capture_output=True,timeout=timeout)
def shell(code,*args,env=None,input=None):
    return run(['/bin/bash','--noprofile','--norc','-c',code,'target',*args],env=env,input=input)
def write(path,text,mode=None):
    path=P(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    if mode is not None:path.chmod(mode)
    return path

def inventory(root):
    return {p.relative_to(root).as_posix():(stat.S_IMODE(p.lstat().st_mode),
            os.readlink(p) if p.is_symlink() else sha(p) if p.is_file() else None)
            for p in [root,*sorted(root.rglob('*'))]}

def clone(source,dest):
    result=run(['/bin/cp','-a','--reflink=auto',source,dest])
    if result.returncode:raise RuntimeError(result.stderr)
    return dest

# The same pure canonical identity helper used by Task9's builder; no native rebuild.
spec=importlib.util.spec_from_file_location('manifest_contract',bundle/'checks/manifest.py')
contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(contract)
def rehash(tree, *, upgrade=False):
    value=json.loads((tree/'manifest.json').read_text())
    for record in value['files']:
        path=tree/record['path']
        if path.is_file(): record.update(size=path.stat().st_size,sha256=sha(path))
    if upgrade:
        record=next(r for r in value['files'] if r['path']=='checks/smoke.py')
        value['identity']['checks'][record['path']]=record['sha256']
        value['release_id']=contract.release_id(value['qbox_version'],value['identity'])
        contract.validate_manifest(value)
    (tree/'manifest.json').write_bytes(contract.canonical_json(value))
    paths=sorted(p for p in tree.rglob('*') if p.is_file() and p.name!='SHA256SUMS')
    (tree/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(tree)}\n' for p in paths))
    return value

class TargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results=[]
        cls.sentinel=write(sandbox/'user-sentinel','user data, never alter\n')
        cls.sentinel_sha=sha(cls.sentinel)
        cls.version=run([bindir/'qbox','--version']).stdout
        cls.old_link=os.readlink(prefix/'current')
        cls.old_inventory=inventory(release)
        # Every mutated copy is separately rooted and explicitly labelled outside
        # its whitelisted bundle; it cannot masquerade as a candidate.json.
        cls.fixtures=sandbox/'test-fixtures';cls.fixtures.mkdir()
        write(cls.fixtures/'TEST-FIXTURE-NOT-FOR-RELEASE','Not a candidate or gate input.\n')
        cls.upgrade=clone(bundle,cls.fixtures/'upgrade')
        smoke=cls.upgrade/'checks/smoke.py'
        smoke.write_text(smoke.read_text()+'\n# test-fixture: non-executable upgrade identity probe\n')
        cls.newmanifest=rehash(cls.upgrade,upgrade=True)
        write(evidence/'test-fixture-identities.json',json.dumps({
            'label':'test-fixture, NEVER release/gate','old':manifest['release_id'],
            'upgrade':cls.newmanifest['release_id']}))
    def record(self,name,result):
        write(evidence/(name+'.log'),result.stdout+result.stderr)
        return result
    def ok(self,result):self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def origins(self,root,label):
        code='import json,qbox,numpy,qbox.io.convert_basic,qbox.io.kpath,qbox.postprocess.band_edges; print(json.dumps({m.__name__:m.__file__ for m in [qbox,numpy,qbox.io.convert_basic,qbox.io.kpath,qbox.postprocess.band_edges]}))'
        result=run([root/'python/bin/python3','-I','-B','-c',code]);self.ok(result)
        value=json.loads(result.stdout)
        self.assertTrue(all(P(p).is_relative_to(root) for p in value.values()))
        write(evidence/(label+'-origins.json'),json.dumps(value,indent=2))
        return value
    def no_running_group_members(self,pgid):
        # PID1 in a minimal target may defer reaping adopted SIGKILL zombies;
        # zombies execute no work. Record them, and reject every live descendant.
        deadline=time.monotonic()+10
        while True:
            members=[]
            for entry in P('/proc').iterdir():
                if not entry.name.isdecimal():continue
                try:
                    fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                    if int(fields[2])==pgid:members.append((int(entry.name),fields[0]))
                except (FileNotFoundError,ProcessLookupError):pass
            if not any(state!='Z' for _,state in members) or time.monotonic()>=deadline:break
            time.sleep(.02)
        write(evidence/f'process-group-{pgid}.json',json.dumps(members))
        self.assertFalse([p for p,state in members if state!='Z'],members)
    def installer(self,name,tree=bundle,target=prefix,binpath=bindir,env=None):
        return self.record(name,run(['/bin/bash',tree/'install.sh','--prefix',target,'--bin-dir',binpath],env=env))
    def loader(self,code,*args,env=None,input=None):
        selected=dict(baseenv if env is None else env,_QBOX_OFFLINE_ROOT=str(release),QBOX_PYTHON=str(python))
        return shell('source "$1/legacy/load.sh" || exit; shift; '+code,package,*args,env=selected,input=input)
    def preserved(self, *, full=False):
        self.assertEqual(os.readlink(prefix/'current'),self.old_link)
        self.assertEqual(run([release/'bin/qbox','--version']).stdout,self.version)
        self.assertEqual(sha(self.sentinel),self.sentinel_sha)
        self.assertFalse((prefix/'.install-lock').exists())
        self.assertEqual(list(prefix.glob('.stage.*')),[])
        if full:self.assertEqual(inventory(release),self.old_inventory)
    def test_01_final_paths_and_science(self):
        self.assertEqual(json.loads((release/'metadata/installed.json').read_text())['release_id'],manifest['release_id'])
        self.assertEqual(sha(release/'metadata/manifest.json'),sha(bundle/'manifest.json'))
        for name in ['installed.json','manifest.json','verification-prepared.json','verification-final.json','smoke.json']:
            shutil.copyfile(release/'metadata'/name,evidence/('default-'+name))
        self.assertEqual((P(baseenv['HOME'])/'.bashrc').read_text(),'private shell configuration\n')
        for name in ['.pip/pip.conf','.config/pip/pip.conf']:
            self.assertEqual((P(baseenv['HOME'])/name).read_bytes(),(P(baseenv['HOME'])/'pip.conf').read_bytes())
        self.assertEqual(sorted(p.name for p in bindir.iterdir()),['qbox'])
        for option in ['--help','--list','--version']:self.ok(run([bindir/'qbox',option]))
        self.assertFalse(list(prefix.glob('.stage.*')))
        self.origins(release,'default-final')
        self.ok(self.loader('qbox_python -c \'import qbox,numpy,json;print(json.dumps([qbox.__file__,numpy.__file__]))\''))
        for phase in ['prepared','final']:
            report=json.loads((release/f'metadata/verification-{phase}.json').read_text())
            self.assertTrue(all(c['status']=='passed' for c in report['checks']))
        smoke=json.loads((release/'metadata/smoke.json').read_text())
        self.assertEqual(len(smoke['checks']),11)
        origins=smoke['checks'][0]['detail']['sys_path']
        self.assertFalse(any('.stage.' in p for p in origins))
        self.assertTrue(any(str(release) in p for p in origins))
        result=self.loader('qbox_python -m qbox.io.convert_basic cif2vasp "$1" "$2"; qbox_python -m qbox.io.kpath "$1"; qbox_python -m qbox.postprocess.band_edges "$3" 1 2 "$4" "$5"',
            release/'metadata/checks/fixtures/silicon.cif',work/'POSCAR',release/'metadata/checks/fixtures/bands.dat.gnu',work/'VBM.dat',work/'CBM.dat')
        self.ok(self.record('science',result));self.assertIn('K_POINTS {crystal_b}',result.stdout)
        expected=json.loads((release/'metadata/checks/fixtures/expected.json').read_text())
        self.assertEqual((work/'VBM.dat').read_text(),expected['vbm_text'])
        self.assertEqual((work/'CBM.dat').read_text(),expected['cbm_text'])
    def test_02_isolation_all_entries_and_external_environment(self):
        poison=sandbox/'poison';poison.mkdir()
        sentinel=poison/'executed'
        write(poison/'sitecustomize.py',f'open({str(sentinel)!r},"w").write("executed")\n')
        for name in ['numpy','qbox']:write(poison/(name+'.py'),'raise RuntimeError("host poison")\n')
        env=dict(baseenv,PYTHONHOME=str(poison),PYTHONPATH=str(poison),PYTHONUSERBASE=str(poison),
                 QBOX_SHARED_ROOT='/obsolete/shared',VIRTUAL_ENV='/foreign/venv',CONDA_PREFIX='/foreign/conda',QBOX_PYTHON='')
        for option in ['--version','--help','--list']:self.ok(run([bindir/'qbox',option],env=env))
        offline=dict(env,_QBOX_OFFLINE_ROOT=str(release),QBOX_PYTHON=str(python))
        self.ok(run([package/'bin/qbox','--version'],env=offline))
        self.ok(self.loader('qbox_python -c \'import numpy,qbox,sys;assert sys.flags.isolated and sys.dont_write_bytecode;print(qbox.__file__)\'',env=env))
        self.ok(self.loader('qe_builtin_calc_em_ainv --help',env=env))
        write(work/'em-band','0 0\n0.1 0.1\n0.2 0.4\n')
        write(work/'em-input','K_POINTS {crystal_b}\n2\n0 0 0 2 ! G\n0.2 0 0 1 ! X\n')
        write(work/'em-output','high-symmetry x coordinate 0.0\nhigh-symmetry x coordinate 0.2\n')
        child=write(work/'child.py','import sys,numpy,qbox,json\nassert sys.flags.isolated and sys.dont_write_bytecode\nprint("ISOLATED_EFFECTIVE_MASS_CHILD",qbox.__file__)\n')
        result=self.loader('qbox_python -m qbox.postprocess.effective_mass_qe -b "$1" --band-input "$2" --bands-output "$3" --alat-angstrom 5 --vasp-script "$4"',work/'em-band',work/'em-input',work/'em-output',child,env=env)
        self.ok(self.record('effective-mass-child',result));self.assertIn('ISOLATED_EFFECTIVE_MASS_CHILD',result.stdout)
        self.assertIn(str(package),result.stdout)
        self.assertFalse(sentinel.exists())
        rejected=run([bindir/'qbox','--version'],env=dict(env,QBOX_PYTHON='/foreign/python'))
        self.assertEqual(rejected.returncode,2);self.assertIn('包外解释器',rejected.stderr)
        alias=sandbox/'python-alias';alias.symlink_to(python)
        self.ok(run([bindir/'qbox','--version'],env=dict(env,QBOX_PYTHON=str(alias))))
        # The external workflow sees exact caller values, including Python poison.
        keys=['PATH','LD_LIBRARY_PATH','PYTHONHOME','PYTHONPATH','MPI_SENTINEL','QBOX_MULTIWFN_HOME','QBOX_PSEUDO_ROOT','QBOX_QE_ENV_SCRIPT','QBOX_ONEAPI_ENV_SCRIPT']
        ext=write(work/'external', '#!/bin/bash\nprintf "%s\\0" '+ ' '.join('"${'+key+'-}"' for key in keys)+' > "$EXTERNAL_LOG"\n',0o755)
        ext_env=dict(env,LD_LIBRARY_PATH='/external/mpi/lib:/external/qe/lib',MPI_SENTINEL='mpi original',
                     QBOX_MULTIWFN_HOME='/external/multiwfn',QBOX_PSEUDO_ROOT='/external/pseudos',
                     QBOX_QE_ENV_SCRIPT='/external/qe.sh',QBOX_ONEAPI_ENV_SCRIPT='/external/oneapi.sh',EXTERNAL_LOG=str(work/'external.log'))
        self.ok(self.loader('"$1"',ext,env=ext_env))
        actual=(work/'external.log').read_bytes().split(b'\0')[:-1]
        self.assertEqual(actual,[ext_env[key].encode() for key in keys])
        write(evidence/'external-environment.json',json.dumps(dict(zip(keys,[v.decode() for v in actual])),indent=2))
        boundary=sandbox/'external-boundary';boundary.mkdir()
        write(boundary/'bash','#!/bin/bash\nsource "${1%/*}/load.sh" || exit\n"$EXTERNAL_EXE"\n',0o755)
        public_env=dict(ext_env,PATH=str(boundary)+':'+ext_env['PATH'],EXTERNAL_EXE=str(ext))
        self.ok(run(['/bin/bash',bindir/'qbox','--task','1'],env=public_env))
        self.assertEqual((work/'external.log').read_bytes().split(b'\0')[:-1],[public_env[key].encode() for key in keys])
        externalbin=sandbox/'external-calculation-bin';externalbin.mkdir()
        shutil.copyfile(ext,externalbin/'qbox-external-calc');(externalbin/'qbox-external-calc').chmod(0o755)
        script=write(work/'qe-env.sh',f'export PATH="{externalbin}:$PATH"\nexport LD_LIBRARY_PATH="/script/mpi/lib:$LD_LIBRARY_PATH"\nexport MPI_SENTINEL="mpi from script"\n')
        script_env=dict(ext_env,QBOX_QE_ENV_SCRIPT=str(script))
        self.ok(self.loader('qe_ensure_runtime_for qbox-external-calc && qbox-external-calc',env=script_env))
        expected=dict(script_env,PATH=str(externalbin)+':'+script_env['PATH'],LD_LIBRARY_PATH='/script/mpi/lib:'+script_env['LD_LIBRARY_PATH'],MPI_SENTINEL='mpi from script')
        self.assertEqual((work/'external.log').read_bytes().split(b'\0')[:-1],[expected[key].encode() for key in keys])
    def test_03_process_boundaries_stdin_and_signals(self):
        trace=work/'process.json'
        result=self.loader('qe_action_handler() { echo capture; }; capture() { printf "%s\\n" "$PWD" "$@"; IFS= read -r a; IFS= read -r b; printf "%s\\n" "$a" "$b"; return 17; }; qe_dispatch_action 1 "$@"','file with spaces','', '37',input='first line\nsecond line\n')
        self.assertEqual(result.returncode,17);self.assertEqual(result.stdout.splitlines(),[str(work),'file with spaces','','37','first line','second line'])
        stubdir=sandbox/'bash-boundary';stubdir.mkdir()
        stub=write(stubdir/'bash','#!/bin/bash\nprintf "%s\\0" "$@" > "$TRACE"\nprintf "%s\\n" "$QBOX_TASK_ID" >> "$TRACE.task"\ncat > "$TRACE.stdin"\nexit 17\n',0o755)
        env=dict(baseenv,PATH=str(stubdir)+':'+baseenv['PATH'],TRACE=str(trace))
        result=run(['/bin/bash',bindir/'qbox','--task','1','37','input with spaces',''],env=env,input='one\ntwo\n')
        self.assertEqual(result.returncode,17)
        self.assertEqual(trace.read_bytes().split(b'\0')[:-1],[str(package/'legacy/entry.sh').encode(),b'37',b'input with spaces',b''])
        self.assertEqual(P(str(trace)+'.task').read_text(),'1\n');self.assertEqual(P(str(trace)+'.stdin').read_text(),'one\ntwo\n')
        for sig in [signal.SIGINT,signal.SIGTERM]:
            ready=work/f'ready-{sig.name}';called=work/f'trap-{sig.name}'
            fifo=work/f'wait-{sig.name}';os.mkfifo(fifo)
            write(stub,'#!/bin/bash\ntrap \'printf trapped > "$CALLED"; exit 17\' INT TERM\nprintf "%s" "$$" > "$READY"\nexec 9<>"$FIFO"\nread -r -u 9 value\n',0o755)
            selected=dict(env,READY=str(ready),CALLED=str(called),FIFO=str(fifo))
            process=subprocess.Popen(['/bin/bash',str(bindir/'qbox'),'--task','1'],env=selected,cwd=work,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                deadline=time.monotonic()+20
                while not ready.exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(ready.exists());self.assertEqual(int(ready.read_text()),process.pid)
                os.killpg(process.pid,sig);out,err=process.communicate(timeout=20)
                self.assertEqual(process.returncode,17,out+err);self.assertEqual(called.read_text(),'trapped')
                with self.assertRaises(ProcessLookupError):os.killpg(process.pid,0)
            finally:
                if process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.communicate()
        self.assertNotEqual(run([bindir/'qbox','--task','not-a-task']).returncode,0)
        shutil.copyfile(release/'metadata/checks/fixtures/silicon.cif',work/'37')
        result=run([bindir/'qbox','--task','36','37'],input='')
        self.ok(self.record('numeric-filename',result));self.assertTrue((work/'37.vasp').is_file())
        self.assertIn('Si',(work/'37.vasp').read_text())
        self.assertNotEqual(run([bindir/'qbox','--task','36','does-not-exist'],input='').returncode,0)
        offline=dict(baseenv,_QBOX_OFFLINE_ROOT=str(release),QBOX_PYTHON=str(python))
        self.ok(run([package/'bin/qbox','--task','37','37.vasp'],env=offline,input=''))
        self.assertTrue((work/'37.cif').is_file())
    def test_04_optional_tools_and_custom_prefix(self):
        for tool in ['lscpu','file','ldd','module','gawk']:self.assertIsNone(shutil.which(tool))
        result=self.loader('qe_physical_cpu_cores');self.ok(result);self.assertEqual(result.stdout.strip(),'16')
        custom=sandbox/'自定义 prefix';custombin=sandbox/'custom bin'
        self.ok(self.installer('custom-install',target=custom,binpath=custombin))
        for option in ['--help','--list','--version']:self.ok(run([custombin/'qbox',option]))
        self.assertEqual(os.readlink(custom/'current'),'releases/'+manifest['release_id'])
        shutil.rmtree(custom);shutil.rmtree(custombin)
    def test_05_readonly_and_cache_fallback(self):
        saved={p:stat.S_IMODE(p.stat().st_mode) for p in [release,*release.rglob('*')] if not p.is_symlink()}
        try:
            for p,mode in saved.items():p.chmod(mode & ~0o222)
            before=inventory(release)
            for option in ['--help','--list','--version']:self.ok(run([bindir/'qbox',option]))
            self.ok(self.record('readonly-smoke',run([python,'-I','-B',release/'metadata/checks/smoke.py','--release',release,'--work',work/'readonly-smoke'])))
            self.ok(self.loader('qbox_python -m qbox.io.convert_basic cif2vasp "$1" "$2"; qe_builtin_calc_em_ainv --help',release/'metadata/checks/fixtures/silicon.cif',work/'readonly-POSCAR'))
            result=self.loader('qbox_python -c \'import matplotlib;print(matplotlib.get_cachedir())\'');self.ok(result)
            self.assertTrue(result.stdout.strip().startswith(baseenv['HOME']+'/.cache/'))
            locked=sandbox/'unwritable';locked.mkdir();locked.chmod(0o555)
            env=dict(baseenv,MPLCONFIGDIR=str(locked/'mpl'),XDG_CACHE_HOME=str(locked))
            result=self.loader('printf "%s" "$MPLCONFIGDIR"',env=env);self.ok(result)
            self.assertEqual(result.stdout,baseenv['HOME']+'/.cache/qbox/matplotlib')
            env.update(HOME=str(locked),TMPDIR=str(locked))
            result=self.loader(':',env=env);self.assertNotEqual(result.returncode,0);self.assertIn('无法找到可写',result.stderr)
            locked.chmod(0o755)
            self.assertEqual(inventory(release),before)
        finally:
            for p,mode in saved.items():p.chmod(mode)
    def test_06_corrupt_bundle_failures_preserve_old(self):
        cases=['missing-wheel','changed-byte','bad-gzip','missing-license','illegal-runtime','rehashed-missing-wheel']
        for case in cases:
            with self.subTest(case=case):
                tree=clone(bundle,self.fixtures/case)
                try:
                    wheel=next((tree/'wheelhouse').glob('numpy-*.whl'))
                    if case in ['missing-wheel','rehashed-missing-wheel']:wheel.unlink()
                    elif case=='changed-byte':
                        with wheel.open('r+b') as f:f.seek(200);b=f.read(1);f.seek(200);f.write(bytes([b[0]^1]))
                    elif case=='bad-gzip':(tree/'runtime/python.tar.gz').write_bytes(b'not gzip')
                    elif case=='missing-license':(tree/'LICENSE').unlink()
                    elif case=='illegal-runtime':
                        with tarfile.open(tree/'runtime/python.tar.gz','w:gz') as tar:
                            info=tarfile.TarInfo('../escape');info.size=4;tar.addfile(info,io.BytesIO(b'evil'))
                    if case in ['bad-gzip','illegal-runtime','rehashed-missing-wheel']:rehash(tree)
                    result=self.installer(case,tree=tree);self.assertNotEqual(result.returncode,0,result.stdout)
                    if case=='rehashed-missing-wheel':
                        self.assertIn('wheel',result.stderr.lower())
                        fresh=self.installer(case+'-fresh',tree=tree,target=sandbox/'missing-wheel-fresh',binpath=sandbox/'missing-wheel-fresh-bin')
                        self.assertNotEqual(fresh.returncode,0);self.assertIn('wheel',fresh.stderr.lower())
                        self.assertFalse((sandbox/'missing-wheel-fresh').exists())
                    self.preserved()
                finally:shutil.rmtree(tree)
        self.preserved(full=True)
    def test_07_destination_conflicts_preserve_old(self):
        current=prefix/'current';command=bindir/'qbox'
        link=os.readlink(command)
        for kind in ['file','external-symlink','broken-symlink']:
            with self.subTest(kind=kind):
                command.unlink()
                if kind=='file':command.write_text('user command')
                else:command.symlink_to(self.sentinel if kind=='external-symlink' else sandbox/'missing')
                before=os.readlink(command) if command.is_symlink() else command.read_text()
                result=self.installer('command-'+kind);self.assertNotEqual(result.returncode,0)
                self.assertEqual(os.readlink(command) if command.is_symlink() else command.read_text(),before)
                self.preserved();command.unlink();command.symlink_to(link)
        current.unlink();current.write_text('user current')
        try:
            result=self.installer('current-file');self.assertNotEqual(result.returncode,0);self.assertEqual(current.read_text(),'user current')
            self.assertEqual(run([release/'bin/qbox','--version']).stdout,self.version)
        finally:current.unlink();current.symlink_to(self.old_link)
        for label,path in [('prefix',prefix),('bin',bindir),('final-parent',prefix/'releases')]:
            oldmode=stat.S_IMODE(path.stat().st_mode);path.chmod(0o555)
            try:self.assertNotEqual(self.installer('unwritable-'+label,tree=self.upgrade).returncode,0)
            finally:path.chmod(oldmode)
            self.preserved()
        target=prefix/'releases'/self.newmanifest['release_id'];target.mkdir();write(target/'sentinel','foreign release')
        try:
            self.assertNotEqual(self.installer('unmarked-release',tree=self.upgrade).returncode,0)
            self.assertEqual((target/'sentinel').read_text(),'foreign release');self.preserved()
        finally:shutil.rmtree(target)
        damaged=release/'metadata/LICENSE';old=damaged.read_bytes();damaged.write_bytes(b'damaged')
        try:
            self.assertNotEqual(self.installer('corrupt-existing-release').returncode,0)
            self.assertEqual(damaged.read_bytes(),b'damaged');self.preserved()
        finally:damaged.write_bytes(old)
        self.preserved(full=True)
    def test_08_actual_noexec_mount(self):
        value=os.environ.get('QBOX_E2E_NOEXEC')
        if not value:self.skipTest('actual noexec mount not supplied; Task11 must supply it')
        noexec=P(value);probe=write(noexec/'probe','#!/bin/sh\nexit 0\n',0o755)
        with self.assertRaises(PermissionError):subprocess.run([str(probe)],check=True)
        result=self.installer('noexec',target=noexec/'prefix',binpath=noexec/'bin')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('不可执行',result.stderr);self.assertIn('noexec',result.stderr)
        self.preserved(full=True)
    def barrier(self,label,phase,*,tree=None,target=prefix,binpath=bindir):
        directory=sandbox/('barrier-'+label);directory.mkdir()
        fifo=directory/'continue';os.mkfifo(fifo)
        # O_RDWR lets the controller release a masked child after a group signal.
        fd=os.open(fifo,os.O_RDWR|os.O_NONBLOCK)
        ready=directory/'ready';wrapper=directory/'wrappers';wrapper.mkdir()
        code=r'''#!/bin/bash
name=${0##*/}
match=0
case "$PHASE:$name" in
 runtime:cp) [[ "${@: -1}" == *'/.stage.'*'/.runtime-input.'* ]] && match=1 ;;
 metadata:mkdir) [[ " $* " == *'/metadata '* ]] && match=1 ;;
 prepared:mv) [[ "$1" == -Tn ]] && match=1 ;;
 final:cp) [[ "${@: -1}" == */metadata/verification-final.json ]] && match=1 ;;
 bin:ln) [[ "${@: -1}" == "$BINPATH/qbox" ]] && match=1 ;;
 before-current:mv|after-current:mv) [[ "$1" == -Tf && "${@: -1}" == "$TARGET/current" ]] && match=1 ;;
esac
if [[ $match == 1 && "$PHASE" == after-current ]]; then
    "$REAL/$name" "$@" || exit
fi
if [[ $match == 1 ]]; then
    printf '%s\n' "$@" > "$READY"
    # Bounded Bash builtin read; no fixed sleep and no background child.
    IFS= read -r -t 300 line < "$FIFO" || exit 79
fi
[[ $match == 1 && "$PHASE" == after-current ]] || exec "$REAL/$name" "$@"
'''
        for name in ['cp','mkdir','mv','ln']:write(wrapper/name,code,0o755)
        env=dict(baseenv,PATH=str(wrapper)+':'+baseenv['PATH'],PHASE=phase,
                 BINPATH=str(binpath),TARGET=str(target),READY=str(ready),FIFO=str(fifo),REAL=str(commands))
        # Preserve the outer shell solely to report the actual installer's trapped
        # status, while the installer and its children receive real group signals.
        selected=tree or bundle
        log=(evidence/(label+'.log')).open('w')
        process=subprocess.Popen(['/bin/bash','-c','trap : INT TERM; source "$1"; main --prefix "$2" --bin-dir "$3"','target',str(selected/'install.sh'),str(target),str(binpath)],env=env,cwd=work,start_new_session=True,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+600
            while not ready.exists() and time.monotonic()<deadline and process.poll() is None:time.sleep(.05)
            self.assertTrue(ready.exists(),f'{label} failed to reach barrier; see {log.name}')
        except BaseException:
            if process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.wait()
            log.close();os.close(fd);raise
        return process,fd,log,ready
    def finish_barrier(self,state,sig=None):
        process,fd,log,ready=state
        try:
            if sig:os.killpg(process.pid,sig)
            if sig!=signal.SIGKILL:os.write(fd,b'continue\n')
            code=process.wait(timeout=600)
            self.no_running_group_members(process.pid)
            return code
        finally:
            if process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.wait()
            os.close(fd);log.close()
    def test_09_real_lock_contention(self):
        state=self.barrier('lock-winner','runtime')
        try:
            owner=(prefix/'.install-lock/owner').read_text()
            loser=self.installer('lock-loser')
            self.assertNotEqual(loser.returncode,0);self.assertIn('安装进行中或遗留锁',loser.stderr)
            self.assertEqual((prefix/'.install-lock/owner').read_text(),owner)
        finally:self.assertEqual(self.finish_barrier(state),0)
        self.preserved(full=True)
    def test_10_process_group_interruptions(self):
        # Publication boundaries must create a new owned final tree: reusing the
        # active release cannot detect cleanup deleting a just-published upgrade.
        records=[]
        new=prefix/'releases'/self.newmanifest['release_id']
        new_link='releases/'+new.name
        for phase in ['runtime','metadata','prepared','final','bin','before-current','after-current']:
            for sig in [signal.SIGINT,signal.SIGTERM]:
                label=f'{phase}-{sig.name}'
                with self.subTest(phase=phase,signal=sig.name):
                    publication=phase in ['before-current','after-current']
                    selected=self.upgrade if phase in ['metadata','prepared','final'] or publication else bundle
                    trialbin=sandbox/('commands-'+label) if phase=='bin' else bindir
                    self.assertEqual(os.readlink(prefix/'current'),self.old_link)
                    self.assertFalse(new.exists(), 'each interruption must start without the upgrade tree')
                    state=self.barrier(label,phase,tree=selected,binpath=trialbin)
                    observation={'phase':phase,'signal':sig.name,
                                 'selected_release_id':self.newmanifest['release_id'] if selected==self.upgrade else manifest['release_id'],
                                 'upgrade_existed_at_start':False}
                    try:
                        try:
                            if phase=='prepared':
                                stage=next(prefix.glob('.stage.*'))
                                report=json.loads((stage/'metadata/smoke.json').read_text())
                                write(evidence/(label+'-prepared-smoke.json'),json.dumps(report))
                                self.assertTrue(all(c['status']=='passed' for c in report['checks']))
                                self.assertTrue(any(str(stage) in p for p in report['checks'][0]['detail']['sys_path']))
                            if publication:
                                self.assertNotEqual(new.name,release.name)
                                self.assertTrue(new.is_dir())
                                marker=json.loads((new/'metadata/installed.json').read_text())
                                self.assertEqual(marker['state'],'verified')
                                self.assertEqual(marker['release_id'],new.name)
                                self.assertEqual(marker['manifest_sha256'],sha(self.upgrade/'manifest.json'))
                                self.assertEqual(sha(new/'metadata/manifest.json'),sha(self.upgrade/'manifest.json'))
                                expected=new_link if phase=='after-current' else self.old_link
                                self.assertEqual(os.readlink(prefix/'current'),expected)
                                new_inventory=inventory(new)
                                observation.update(current_before_signal=expected,
                                                   upgrade_verified_before_signal=True,
                                                   upgrade_inventory_sha256=hashlib.sha256(json.dumps(new_inventory,sort_keys=True).encode()).hexdigest())
                        finally:
                            code=self.finish_barrier(state,sig)
                        observation.update(exit=code,current=os.readlink(prefix/'current'),
                                           upgrade_exists_after_signal=new.exists())
                        write(evidence/(label+'-observation.json'),json.dumps(observation,indent=2))
                        self.assertEqual(code,128+sig)
                        if phase=='after-current':
                            self.assertEqual(os.readlink(prefix/'current'),new_link)
                            self.assertEqual(inventory(new),new_inventory)
                            self.assertEqual(json.loads((new/'metadata/installed.json').read_text())['state'],'verified')
                            self.assertEqual(sha(new/'metadata/manifest.json'),sha(self.upgrade/'manifest.json'))
                            entry=self.record(label+'-public-entry',run([bindir/'qbox','--version']))
                            self.ok(entry);self.assertEqual(entry.stdout,self.version)
                            self.assertEqual((bindir/'qbox').resolve(),new/'bin/qbox')
                            self.assertEqual(inventory(release),self.old_inventory)
                            self.assertEqual(sha(self.sentinel),self.sentinel_sha)
                            self.assertFalse((prefix/'.install-lock').exists())
                            self.assertEqual(list(prefix.glob('.stage.*')),[])
                            shutil.copyfile(new/'metadata/installed.json',evidence/(label+'-installed.json'))
                            observation.update(upgrade_inventory_unchanged=True,public_entry_exit=entry.returncode,
                                               verified_manifest_sha256=sha(new/'metadata/manifest.json'))
                        else:
                            self.preserved(full=True)
                            self.assertFalse(new.exists())
                        if phase=='bin':self.assertFalse((trialbin/'qbox').is_symlink())
                        observation.update(old_release_unchanged=True,lock_and_stage_removed=True)
                        records.append(observation)
                        write(evidence/'interruption-results.json',json.dumps(records,indent=2))
                    finally:
                        if phase=='after-current':
                            # Record the preserved published tree above before test
                            # teardown. Restore old, then remove only our fixture so
                            # the next signal owns a freshly installed upgrade too.
                            lock=prefix/'.install-lock';lock.mkdir()
                            try:
                                write(lock/'owner','manual rollback: interruption test-fixture\n')
                                temporary=prefix/'.interruption-rollback';temporary.symlink_to(self.old_link)
                                os.replace(temporary,prefix/'current')
                            finally:shutil.rmtree(lock)
                            if new.exists():shutil.rmtree(new)
                    self.preserved(full=True)
                    observation.update(restored_current=os.readlink(prefix/'current'),
                                       upgrade_absent_after_test_teardown=not new.exists())
                    write(evidence/'interruption-results.json',json.dumps(records,indent=2))
        # A clean same-payload retry proves cleanup did not poison installation.
        self.ok(self.installer('after-signals-retry'))
    def test_11_two_prefixes_same_bin_race(self):
        shared=sandbox/'race-bin'
        states=[];targets=[]
        try:
            for label in ['race-one','race-two']:
                target=sandbox/label;targets.append(target)
                states.append(self.barrier(label,'bin',target=target,binpath=shared))
            codes=[self.finish_barrier(state) for state in states];states=[]
            self.assertEqual(sorted(codes),[0,1])
            link=os.readlink(shared/'qbox')
            winners=[t for t in targets if link==str(t/'current/bin/qbox')]
            self.assertEqual(len(winners),1)
            self.ok(run([shared/'qbox','--version']))
            for target,code in zip(targets,codes):
                if code:self.assertFalse(target.exists())
            self.preserved(full=True)
        finally:
            for state in states:self.finish_barrier(state,signal.SIGKILL)
            for target in targets:
                if target.exists():shutil.rmtree(target)
            if shared.exists():shutil.rmtree(shared)
    def test_12_reuse_upgrade_rollback_and_sigkill(self):
        # Identical delivery must retain every byte and mode and the runtime inode.
        inode=python.stat().st_ino;before=inventory(release)
        self.ok(self.installer('reuse'));self.assertEqual(inventory(release),before)
        self.assertEqual(python.stat().st_ino,inode)
        state=self.barrier('upgrade-prepared','prepared',tree=self.upgrade)
        stage=next(prefix.glob('.stage.*'))
        staged=json.loads((stage/'metadata/smoke.json').read_text())
        staged_origins=self.origins(stage,'upgrade-prepared')
        write(evidence/'upgrade-prepared-smoke.json',json.dumps(staged))
        self.assertEqual(self.finish_barrier(state),0)
        new=prefix/'releases'/self.newmanifest['release_id']
        self.assertNotEqual(new.name,release.name)
        self.assertEqual(os.readlink(prefix/'current'),'releases/'+new.name)
        self.assertEqual(sha(new/'metadata/manifest.json'),sha(self.upgrade/'manifest.json'))
        for name in ['installed.json','manifest.json','verification-prepared.json','verification-final.json','smoke.json']:
            shutil.copyfile(new/'metadata'/name,evidence/('test-fixture-upgrade-'+name))
        final=json.loads((new/'metadata/smoke.json').read_text())
        final_origins=self.origins(new,'upgrade-final')
        self.assertEqual({k:str(P(v).relative_to(stage)) for k,v in staged_origins.items()},
                         {k:str(P(v).relative_to(new)) for k,v in final_origins.items()})
        self.assertEqual([c['name'] for c in staged['checks']],[c['name'] for c in final['checks']])
        self.assertEqual([c['status'] for c in staged['checks']],[c['status'] for c in final['checks']])
        self.assertTrue(any(str(new) in p for p in final['checks'][0]['detail']['sys_path']))
        self.assertFalse(list(prefix.glob('.stage.*')))
        self.ok(run([new/'python/bin/python3','-I','-B',new/'metadata/checks/smoke.py','--release',new,'--work',work/'upgrade-smoke']))
        self.assertEqual(inventory(release),before)
        def rollback():
            lock=prefix/'.install-lock';lock.mkdir()
            try:
                write(lock/'owner','manual rollback: test-fixture\n')
                temporary=prefix/'.rollback';temporary.symlink_to(self.old_link)
                os.replace(temporary,prefix/'current')
            finally:shutil.rmtree(lock)
        rollback();self.preserved(full=True)
        for phase in ['before-current','after-current']:
            state=self.barrier('kill-'+phase,phase,tree=self.upgrade)
            self.assertEqual(self.finish_barrier(state,signal.SIGKILL),-signal.SIGKILL)
            lock=prefix/'.install-lock';self.assertTrue(lock.is_dir())
            old_owner=(lock/'owner').read_bytes()
            expected=self.old_link if phase=='before-current' else 'releases/'+new.name
            self.assertEqual(os.readlink(prefix/'current'),expected)
            active=(prefix/'current').resolve()
            self.assertEqual(json.loads((active/'metadata/installed.json').read_text())['state'],'verified')
            self.ok(run([bindir/'qbox','--version']))
            refused=self.installer('stale-lock-'+phase,tree=self.upgrade)
            self.assertNotEqual(refused.returncode,0);self.assertIn('遗留锁',refused.stderr)
            self.assertEqual((lock/'owner').read_bytes(),old_owner)
            # Test-controlled manual recovery only after checking all processes
            # have ended. The product never steals the stale lock.
            self.no_running_group_members(state[0].pid)
            shutil.rmtree(lock)
            for p in prefix.glob('.stage.*'):shutil.rmtree(p)
            for p in prefix.glob('.current.*'):p.unlink()
            if expected!=self.old_link:rollback()
            self.preserved(full=True)
        self.ok(self.record('rollback-smoke',run([python,'-I','-B',release/'metadata/checks/smoke.py','--release',release,'--work',work/'rollback-smoke'])))

selected=[n for n in os.environ.get('QBOX_E2E_CASES','').split(',') if n]
suite=(unittest.TestSuite(TargetTests(name) for name in selected) if selected
       else unittest.defaultTestLoader.loadTestsFromTestCase(TargetTests))
with (evidence/'unittest.log').open('w') as log:
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
failures=[{'test':str(test),'detail':detail} for test,detail in result.failures+result.errors]
report={'schema_version':1,'candidate_release_id':manifest['release_id'],
        'manifest_sha256':sha(bundle/'manifest.json'),'tests_run':result.testsRun,
        'failures':failures,'skipped':[(str(t),why) for t,why in result.skipped],
        'complete_suite':not selected,'selected_cases':selected,
        'scope':'real candidate target tests; network/CPU/VM guarantees belong to invoking layer',
        'test_fixture_release_id':getattr(TargetTests,'newmanifest',{}).get('release_id')}
write(evidence/'results.json',json.dumps(report,indent=2))
print((evidence/'unittest.log').read_text(),end='')
# A release gate cannot silently convert unavailable mount coverage into PASS.
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
PY
[[ ! -s $QBOX_FORBIDDEN_CALL_LOG ]]
