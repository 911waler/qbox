"""Assemble deterministic candidates from committed source and fixed local inputs.

The cache/audit descriptor pins prior static reports; those reports remain original
historical evidence. Only unchanged runtime/dependency bytes inherit that evidence.
The current qbox wheel is inspected anew. No function downloads or resolves inputs.
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from email.parser import BytesParser

from .model import canonical_json, release_id, safe_payload_path, sha256_file, validate_manifest
from .resolve import wheel_metadata, requirements_bytes, load_cpu_builds
from .cpu_wheels import validate_components
from .audit import validate_license_inventory, wheel_inventory

ROOT = Path(__file__).resolve().parents[2]
CHECKS = ('verify.py', 'smoke.py', 'manifest.py', 'provenance.py',
          'fixtures/silicon.cif', 'fixtures/bands.dat.gnu', 'fixtures/expected.json')


def _git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def _source_identity():
    if _git('status', '--porcelain', '--untracked-files=all').strip():
        raise ValueError('source must be clean: commit uncommitted files first')
    return _git('rev-parse', 'HEAD').decode().strip(), int(_git('show', '-s', '--format=%ct', 'HEAD'))


def _input(root, name, record=None):
    safe_payload_path(name)
    path = root / name
    # Do not follow symlinks, including parent components, even if they stay inside.
    for part in (path, *path.parents):
        if part == root.parent:
            break
        if part.is_symlink():
            raise ValueError('symlink input: ' + name)
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('missing or unsafe input: ' + name)
    if record and (sha256_file(path) != record['sha256'] or
                   ('size' in record and path.stat().st_size != record['size'])):
        raise ValueError('input hash/size mismatch: ' + name)
    return path


def _json(path):
    return json.loads(path.read_bytes())


def _runtime_members(path):
    with tarfile.open(path, 'r:gz') as archive:
        seen = set()
        for member in archive:
            safe_payload_path(member.name)
            if member.name in seen or not (member.isfile() or member.isdir()):
                raise ValueError('unsafe runtime member: ' + member.name)
            if member.name != 'python' and not member.name.startswith('python/'):
                raise ValueError('runtime outside python tree')
            seen.add(member.name)
        return seen


def _build_wheel(cache, work, commit, epoch, dependencies, runtime):
    """Use the locked runtime and build wheels in a fresh private environment."""
    source = work / 'source'; source.mkdir()
    # git archive, not a recursive worktree copy: ignored build/cache/private files
    # never enter the build backend's source tree.
    with tarfile.open(fileobj=io.BytesIO(_git('archive', '--format=tar', commit))) as archive:
        for member in archive:
            safe_payload_path(member.name)
            if not (member.isfile() or member.isdir()):
                raise ValueError('source archive requires regular files/directories')
        archive.extractall(source, filter='data')
    with tarfile.open(cache / 'python.tar.gz') as archive:
        archive.extractall(work, filter='data')
    python = work / 'python/bin/python3'
    env = {k:v for k,v in os.environ.items() if not k.startswith(('PIP_', 'PYTHON', 'QBOX_', 'BASH_FUNC_'))}
    env.update(SOURCE_DATE_EPOCH=str(epoch), PYTHONDONTWRITEBYTECODE='1',
               PIP_CONFIG_FILE='/dev/null', HOME=str(work), LC_ALL='C', TZ='UTC')
    def run(*args):
        result=subprocess.run(list(map(str,args)), cwd=source, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError('offline wheel command failed: '+str(args[0])+'\n'+
                               (result.stdout+result.stderr).decode(errors='replace')[-8000:])
    run(python, '-I', '-B', '-m', 'venv', work/'build-env')
    build_python=work/'build-env/bin/python'
    for package in dependencies['build_packages']:
        _input(cache/'build-wheelhouse',package['filename'],package)
    if (ROOT/'packaging/offline/build-requirements.lock').read_bytes() != requirements_bytes(dependencies['build_packages']):
        raise ValueError('build tool lock does not match resolved build packages')
    run(build_python, '-I', '-B', '-m', 'pip', '--isolated', '--disable-pip-version-check',
        'install', '--no-index', '--no-cache-dir', '--no-compile', '--require-hashes',
        '--only-binary=:all:', '--find-links', cache/'build-wheelhouse',
        '-r', source/'packaging/offline/build-requirements.lock')
    run(build_python, '-I', '-B', '-m', 'build', '--wheel', '--no-isolation', '--outdir', work/'wheels', source)
    wheels=list((work/'wheels').glob('*.whl'))
    if len(wheels)!=1:
        raise ValueError('build must produce exactly one qbox wheel')
    # Exercise the existing ordinary-wheel contract with the same locked closure.
    run(build_python, '-I', '-B', '-m', 'pip', '--isolated', '--disable-pip-version-check',
        'install', '--no-index', '--no-cache-dir', '--no-compile', '--require-hashes',
        '--only-binary=:all:', '--find-links', cache/'candidate-wheelhouse',
        '-r', source/'packaging/offline/requirements.lock')
    run(build_python, '-B', source/'tools/verify-wheel.py', wheels[0])
    print('PASS: tools/verify-wheel.py using locked runtime/build/dependency inputs')
    return wheels[0]


def _inspect_qbox(path, resolution):
    metadata=wheel_metadata(path)
    if metadata['name']!='qbox' or sorted(metadata['requires_dist'])!=sorted(resolution['requires_dist']):
        raise ValueError('qbox METADATA dependency change: resolve locks again')
    with zipfile.ZipFile(path) as wheel:
        names=wheel.namelist()
        if len(names)!=len(set(names)):
            raise ValueError('duplicate qbox wheel member')
        for name in names:
            safe_payload_path(name.rstrip('/'))
            mode=wheel.getinfo(name).external_attr>>16
            if stat.S_ISLNK(mode):
                raise ValueError('qbox wheel link forbidden')
            parts=name.split('/')
            if any(p in ('.git','.venv','__pycache__','tests') for p in parts) or name.endswith(('.pyc','.pyo','.out','.log')):
                raise ValueError('private/cache/test qbox wheel member: '+name)
            if not (name.startswith('qbox/') or name.startswith('qbox-') and '.dist-info/' in name):
                raise ValueError('unexpected qbox wheel resource: '+name)
            data=wheel.read(name)
            if data.startswith(b'\x7fELF'):
                raise ValueError('new native qbox content requires audit')
            if any(value in data for value in (str(ROOT).encode(),b'/home/waler/',b'/opt/nwu911/',b'/srv/nwu911/')):
                raise ValueError('machine path in qbox-owned wheel member: '+name)
        required=('qbox/registry.py','qbox/legacy/load.sh','qbox/legacy/entry.sh',
                  'qbox/bin/qbox','qbox/bin/qbox-dopant-pdos.py','qbox/postprocess/effective_mass_vasp.py')
        if not set(required)<=set(names) or not wheel.getinfo('qbox/bin/qbox').external_attr>>16&0o111:
            raise ValueError('missing/nonexecutable qbox resource')
        license_names=[n for n in names if n.endswith('/LICENSE')]
        if not license_names or any(wheel.read(n)!=(ROOT/'LICENSE').read_bytes() for n in license_names):
            raise ValueError('qbox wheel MIT license must match source')
        meta=BytesParser().parsebytes(wheel.read(next(n for n in names if n.endswith('.dist-info/METADATA'))))
        if set(meta.get_all('Provides-Extra',[]))!={'analysis','structure'}:
            raise ValueError('qbox extras METADATA changed: resolve locks again')
    return metadata


def _audit_inputs(cache, locks, runtime, dependencies):
    base=cache/'audit'
    descriptor=_json(_input(base,'descriptor.json'))
    for name in ('licenses','elf'):
        if set(descriptor[name])!={'path','sha256','size'}:
            raise ValueError('audit descriptor requires path, SHA and size')
    reports={name:_json(_input(base,descriptor[name]['path'],descriptor[name])) for name in ('licenses','elf')}
    report=reports['licenses']
    for value in reports.values():
        if value['status']!='passed-static' or value['errors']:
            raise ValueError('cached static audit is not passing')
    if report['lock_sha256']!=sha256_file(locks/'licenses.lock.json'):
        raise ValueError('license audit lock mismatch')
    license_lock=_json(locks/'licenses.lock.json')
    if report['payload_inputs']['runtime']!=runtime['normalized'] or license_lock['runtime_sha256']!=runtime['normalized']['sha256']:
        raise ValueError('audit does not bind delivered runtime')
    for package in dependencies['packages']:
        if report['payload_inputs']['wheels'].get(package['filename'])!=package['sha256'] or license_lock['wheels'][package['filename']]['sha256']!=package['sha256']:
            raise ValueError('audit does not bind delivered dependency')
    validate_license_inventory(report)
    for item in report['materials']:
        _input(base,item['path'],item)
    for item in reports['elf'].get('auditwheel',[]):
        if item['exit_code']:
            raise ValueError('failed historical auditwheel evidence')
        _input(base,item['path'],item)
    return descriptor,reports


def _archive(tree, path, epoch):
    with path.open('wb') as raw, gzip.GzipFile(fileobj=raw,filename='',mode='wb',mtime=0) as gz, tarfile.open(fileobj=gz,mode='w',format=tarfile.PAX_FORMAT) as archive:
        for source in sorted(tree.rglob('*')):
            name=source.relative_to(tree).as_posix();safe_payload_path(name)
            if source.is_symlink() or not (source.is_file() or source.is_dir()):
                raise ValueError('unsafe final archive member: '+name)
            info=tarfile.TarInfo(name);info.uid=info.gid=0;info.uname=info.gname='';info.mtime=epoch
            info.type=tarfile.DIRTYPE if source.is_dir() else tarfile.REGTYPE
            info.mode=0o755 if source.is_dir() or name in ('install.sh','checks/qbox-launcher.sh') else 0o644
            if source.is_file():
                info.size=source.stat().st_size
                with source.open('rb') as stream:archive.addfile(info,stream)
            else:archive.addfile(info)


def build(cache: Path, output: Path) -> Path:
    cache,output=Path(cache).resolve(),Path(output).absolute()
    commit,epoch=_source_identity()
    locks=ROOT/'packaging/offline'
    runtime=_json(_input(locks,'runtime.lock.json'));dependencies=_json(_input(locks,'dependencies.lock.json'))
    _input(cache,'python.tar.gz',runtime['normalized']);_runtime_members(cache/'python.tar.gz')
    for package in dependencies['packages']:
        _input(cache/'candidate-wheelhouse',package['filename'],package)
    if (locks/'requirements.lock').read_bytes()!=requirements_bytes(dependencies['packages']):
        raise ValueError('dependency requirements do not match resolved packages')
    descriptor,reports=_audit_inputs(cache,locks,runtime,dependencies)
    components=load_cpu_builds(dependencies['cpu_build'],locks) if dependencies.get('cpu_build') else []
    validate_components(components,dependencies['packages'])
    for package in dependencies['packages']:
        with zipfile.ZipFile(cache/'candidate-wheelhouse'/package['filename']) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)):
                raise ValueError('duplicate dependency wheel member')
            for info in archive.infolist():
                safe_payload_path(info.filename.rstrip('/'))
                if stat.S_ISLNK(info.external_attr>>16):
                    raise ValueError('dependency wheel symlink forbidden')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.qbox-candidate-',dir=output.parent) as temporary:
        work=Path(temporary);tree=work/'bundle';tree.mkdir()
        wheel=_build_wheel(cache,work,commit,epoch,dependencies,runtime)
        qbox=_inspect_qbox(wheel,dependencies['qbox_resolution_wheel'])
        files={};license_map={'MIT':['LICENSE']}
        def add(name, source, *, provenance=None, licenses=None, expected=None):
            safe_payload_path(name)
            if name in files:raise ValueError('duplicate payload: '+name)
            destination=tree/name;destination.parent.mkdir(parents=True,exist_ok=True)
            if isinstance(source,bytes):destination.write_bytes(source)
            else:shutil.copyfile(source,destination)
            destination.chmod(0o755 if name in ('install.sh','checks/qbox-launcher.sh') else 0o644)
            files[name]=dict(path=name,size=destination.stat().st_size,sha256=sha256_file(destination),source=provenance or {'commit':commit},license_ids=licenses or ['MIT'])
            if expected and any(files[name][key]!=expected[key] for key in ('sha256','size') if key in expected):
                raise ValueError('delivered payload differs from locked input: '+name)
        for name in ('install.sh','README.zh-CN.md'):
            add(name,_input(locks,name))
        add('LICENSE',_input(ROOT,'LICENSE'))
        add('checks/qbox-launcher.sh',_input(locks,'qbox-launcher.sh'))
        for name in CHECKS:add('checks/'+name,_input(locks/'checks',name))
        for name in ('runtime.lock.json','dependencies.lock.json','build-requirements.lock','licenses.lock.json'):
            add('checks/'+name,_input(locks,name))
        for component in components:
            binding=component['binding'];proof=component['proof']
            for key in ('inputs','provenance'):add('checks/'+binding[key],_input(locks,binding[key]))
            for stage,record in (('compile',proof),('normalize',proof['normalization'])):
                for name,digest in sorted(record['recipe_files'].items()):
                    safe_payload_path(name)
                    data=_git('show',record['code_commit']+':'+name)
                    if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('historical recipe hash mismatch')
                    add('checks/cpu-build/'+stage+'/'+component['id']+'/'+name,data,provenance={'commit':record['code_commit']})
        # Preserve original audit evidence with its original artifact associations.
        for name in ('licenses','elf'):
            add('checks/source-audit/'+name+'.json',_input(cache/'audit',descriptor[name]['path'],descriptor[name]))
        for item in reports['elf'].get('auditwheel',[]):
            add('checks/source-audit/'+item['path'],_input(cache/'audit',item['path'],item))
        for name,item in sorted(descriptor.get('checks',{}).items()):
            add('checks/'+name,_input(cache/'audit',item['path'],item))
        add('checks/source-audit/descriptor.json',canonical_json(descriptor))
        # Re-audit this exact current wheel, never relabel the resolution wheel.
        with zipfile.ZipFile(wheel) as archive:license_names=[n for n in archive.namelist() if n.endswith('/LICENSE')]
        current=wheel_inventory(wheel,work/'qbox-materials',{'package':{'licenses':['MIT'],'materials':license_names}},source={'commit':commit})
        validate_license_inventory(current)
        for component in current['components']:
            component['materials']=['LICENSE']
            component['license_ids']=['MIT']
        if current['native']:raise ValueError('qbox native payload requires new static audit')
        original=reports['licenses']
        retained=[c for c in original['components'] if not c['id'].startswith(('qbox==','qbox/'))]
        used={p for c in retained for p in c['materials']+c.get('sources',[])}
        material_records={m['path']:m for m in original['materials']}
        material_licenses={}
        for component in retained:
            for identifier in component['license_ids']:
                paths=component['materials']+component.get('sources',[])
                license_map[identifier]=sorted({'THIRD_PARTY_LICENSES/'+p for p in paths})
                for path in paths:material_licenses.setdefault(path,set()).add(identifier)
        for path in sorted(used):
            record=material_records[path];provenance=record['source']
            if set(provenance)!={'url','sha256','filename'}:provenance={'commit':commit}
            add('THIRD_PARTY_LICENSES/'+path,_input(cache/'audit',path,record),provenance=provenance,licenses=sorted(material_licenses[path]),expected=record)
        def component_licenses(name):
            matches=[c for c in retained if c['id']==name or c['id'].startswith((name+'==',name+'/'))]
            if not matches:raise ValueError('missing component license mapping: '+name)
            return sorted({i for c in matches for i in c['license_ids']})
        runtime_ids=sorted({i for c in retained if c['id']=='cpython' or c['id'].startswith(('runtime/','pip')) for i in c['license_ids']})
        if not runtime_ids:raise ValueError('runtime licenses missing')
        add('runtime/python.tar.gz',cache/'python.tar.gz',provenance=runtime['source'],licenses=runtime_ids,expected=runtime['normalized'])
        wheels=[]
        for package in dependencies['packages']:
            name='wheelhouse/'+package['filename']
            add(name,cache/'candidate-wheelhouse'/package['filename'],provenance=package['source'],licenses=component_licenses(package['name']),expected=package)
            wheels.append({**files[name],**{k:package[k] for k in ('name','version')},'requirement':package['name']+'=='+package['version']})
        qbox_path='packages/'+wheel.name;add(qbox_path,wheel,expected=qbox)
        wheels.append({**files[qbox_path],'name':'qbox','version':qbox['version'],'requirement':'qbox[analysis,structure]=='+qbox['version']})
        requirements=f'qbox[analysis,structure]=={qbox["version"]} --hash=sha256:{qbox["sha256"]}\n'.encode()+(locks/'requirements.lock').read_bytes()
        add('requirements.lock',requirements)
        # This audit is fresh composition, with exact source-report references and
        # final paths. It deliberately does not claim rerunning unchanged ELF scans.
        audit={'schema_version':1,'status':'passed-static','cpu_baseline_verified':False,
               'source_commit':commit,'historical_reports':{n:files['checks/source-audit/'+n+'.json']['sha256'] for n in ('licenses','elf')},
               'qbox':{'path':qbox_path,'sha256':qbox['sha256'],'components':current['components'],'native':[]},
               'payloads':{p:files[p]['sha256'] for p in sorted(files) if p.startswith(('runtime/','wheelhouse/','packages/','THIRD_PARTY_LICENSES/'))},
               'license_map':license_map,'errors':[]}
        add('checks/final-payload-audit.json',canonical_json(audit))
        identity={'qbox_version':qbox['version'],'source_commit':commit,'qbox_wheel_sha256':qbox['sha256'],
                  'runtime_sha256':runtime['normalized']['sha256'],'dependencies_lock_sha256':files['requirements.lock']['sha256'],
                  'build_requirements_lock_sha256':files['checks/build-requirements.lock']['sha256'],
                  'installer_template_sha256':files['install.sh']['sha256'],'launcher_template_sha256':files['checks/qbox-launcher.sh']['sha256'],
                  'checks':{p:r['sha256'] for p,r in files.items() if p.startswith('checks/') and p!='checks/qbox-launcher.sh'},
                  'licenses':{p:files[p]['sha256'] for paths in license_map.values() for p in paths}}
        manifest={'schema_version':1,'product':'qbox','qbox_version':qbox['version'],
                  'platform':{'os':'linux','arch':'x86_64','glibc_min':'2.28','python_series':'3.12','cpu_baseline':'x86_64'},
                  'extras':['analysis','structure'],'source':{'commit':commit,'dirty':False},
                  'runtime':{**files['runtime/python.tar.gz'],'implementation':'cpython','version':runtime['version']},
                  'wheels':sorted(wheels,key=lambda x:x['name']),
                  'bootstrap_packages':[{'name':p['name'],'version':p['version'],'source':runtime['source'],
                                         'license_ids':component_licenses(p['name']) if any(c['id']==p['name'] for c in retained) else runtime_ids} for p in runtime['bootstrap_packages']],
                  'licenses':license_map,'files':[files[p] for p in sorted(files)],'identity':identity,'release_id':release_id(qbox['version'],identity)}
        validate_manifest(manifest)
        (tree/'manifest.json').write_bytes(canonical_json(manifest))
        sums=''.join(sha256_file(tree/p)+'  '+p+'\n' for p in sorted([*files,'manifest.json']))
        (tree/'SHA256SUMS').write_text(sums,encoding='ascii')
        artifact=f'qbox-{qbox["version"]}-linux-x86_64-offline.tar.gz'
        _archive(tree,work/artifact,epoch)
        candidate={'schema_version':1,'artifact':artifact,'artifact_sha256':sha256_file(work/artifact),
                   'source_commit':commit,'manifest_sha256':sha256_file(tree/'manifest.json'),
                   'release_id':manifest['release_id'],'audit_sha256':files['checks/final-payload-audit.json']['sha256']}
        (work/(artifact+'.sha256')).write_text(candidate['artifact_sha256']+'  '+artifact+'\n')
        (work/'candidate.json').write_bytes(canonical_json(candidate))
        # Candidate publication is a directory rename. Existing outputs are either
        # byte-identical complete candidates or a conflict; never partially replace.
        publication=work/'publication';publication.mkdir()
        for name in (artifact,artifact+'.sha256','candidate.json'):shutil.move(work/name,publication/name)
        if output.exists() or output.is_symlink():
            if output.is_symlink() or not output.is_dir() or set(p.name for p in output.iterdir())!=set(p.name for p in publication.iterdir()) or any(not (output/p.name).is_file() or (output/p.name).is_symlink() or sha256_file(output/p.name)!=sha256_file(p) for p in publication.iterdir()):
                raise ValueError('output already exists with different or incomplete payload; use a separate candidate directory')
        else:
            if _source_identity()!=(commit,epoch):
                raise ValueError('source changed during candidate assembly')
            publication.rename(output)
    return output/'candidate.json'
