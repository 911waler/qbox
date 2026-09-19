"""Fail-closed, byte-bound license and native audits for offline release inputs.

This is a static audit. Passing it never establishes a baseline CPU execution
proof: Task 11 must run the delivered payload with a constrained x86_64 CPU.
"""
from __future__ import annotations

from email.parser import BytesParser
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

LOCKS = Path(__file__).resolve().parents[2] / 'packaging/offline'
BASE_LIBRARIES = frozenset({'libc.so.6', 'libm.so.6', 'libdl.so.2', 'libpthread.so.0',
    'librt.so.1', 'libutil.so.1', 'libresolv.so.2', 'libcrypt.so.1',
    'libgcc_s.so.1', 'libstdc++.so.6', 'ld-linux-x86-64.so.2'})


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _write_json(path: Path, data: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return _digest(path)


def _safe(name: str) -> str:
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or '\\' in name:
        raise ValueError(f'unsafe archive member: {name}')
    return name


def glibc_allowed(symbol: str, baseline: tuple[int, ...]) -> bool:
    match = re.fullmatch(r'GLIBC_(\d+(?:\.\d+)+)', symbol)
    return bool(match and tuple(map(int, match[1].split('.'))) <= baseline)


def parse_readelf(text: str) -> dict:
    """Parse readelf needs separately from definitions (definitions are not needs)."""
    result = {'needed': [], 'rpath': [], 'runpath': [], 'version_needs': [],
              'version_files': {}, 'version_definitions': [], 'isa': [], 'machine': '', 'elf_class': ''}
    section = None
    file = None
    for line in text.splitlines():
        if 'Class:' in line:
            result['elf_class'] = line.split('Class:',1)[1].strip()
        if 'Machine:' in line:
            result['machine'] = line.split('Machine:', 1)[1].strip()
        for tag, key in [('NEEDED','needed'), ('RPATH','rpath'), ('RUNPATH','runpath')]:
            if f'({tag})' in line:
                match = re.search(r'\[([^]]*)\]', line)
                if match:
                    result[key].extend(match[1].split(':') if key != 'needed' else [match[1]])
        if line.startswith('Version needs section'):
            section = 'needs'
        elif line.startswith('Version definition section'):
            section = 'definitions'
        elif line.startswith(('Version symbols section', 'Displaying notes')):
            section = None
        if section == 'needs':
            match = re.search(r'\bFile:\s+(\S+)', line)
            if match:
                file = match[1]
            match = re.search(r'\bName:\s+(\S+)', line)
            if match:
                result['version_needs'].append(match[1])
                if file:
                    result['version_files'].setdefault(file, []).append(match[1])
        elif section == 'definitions':
            match = re.search(r'\bName:\s+(\S+)', line)
            if match:
                result['version_definitions'].append(match[1])
        if 'x86 ISA needed:' in line:
            result['isa'].extend(re.findall(r'x86-64(?:-baseline|-v[234])?', line.split('x86 ISA needed:',1)[1]))
    for key in ['needed','version_needs','version_definitions','isa']:
        result[key] = sorted(set(result[key]))
    return result


def inspect_elf(path: Path) -> dict:
    completed = subprocess.run(['/usr/bin/readelf', '-h', '-d', '--version-info', '-n', str(path)],
        check=True, capture_output=True, text=True, env={**os.environ, 'LC_ALL':'C'})
    return parse_readelf(completed.stdout)


def validate_elf(record: dict) -> None:
    if record.get('elf_class') != 'ELF64':
        raise ValueError('unsupported ELF class')
    if record['machine'] != 'Advanced Micro Devices X86-64':
        raise ValueError(f"unsupported ELF machine: {record['machine']}")
    for version in record['version_needs']:
        if version.startswith('GLIBC_') and not glibc_allowed(version, (2,28)):
            raise ValueError(f'unsupported required symbol {version}')
    for key in ('rpath','runpath'):
        for entry in record[key]:
            if not re.fullmatch(r'(?:\$ORIGIN|\$\{ORIGIN\})(?:/[^:$]*)?', entry):
                raise ValueError(f'unsafe {key.upper()}: {entry}')
    if any(x in record['isa'] for x in ('x86-64-v2','x86-64-v3','x86-64-v4')):
        raise ValueError('required ISA exceeds baseline x86_64')


def resolve_needed(path: str, record: dict, files: set[str], base: dict, inherited=()) -> dict:
    """Resolve through the object's actual origin search directories, never host paths."""
    origin = posixpath.dirname(path)
    group='/'.join(path.split('/')[:2]) if path.startswith(('runtime/','wheels/')) else None
    directories = []
    for entry in record['runpath'] or record['rpath']:
        directory = posixpath.normpath(entry.replace('${ORIGIN}', origin).replace('$ORIGIN', origin))
        if directory == '..' or directory.startswith('../') or directory.startswith('/'):
            raise ValueError(f'loader search path escapes payload: {path}')
        if group and not (directory==group or directory.startswith(group+'/')):
            raise ValueError(f'loader path escapes its install tree: {path}')
        directories.append(directory)
    directories.extend(inherited)
    resolved = {}
    for needed in record['needed']:
        if '/' in needed:
            if not needed.startswith(('$ORIGIN/', '${ORIGIN}/')):
                raise ValueError(f'unsafe DT_NEEDED: {needed}')
            expanded=posixpath.normpath(needed.replace('${ORIGIN}',origin).replace('$ORIGIN',origin))
            if expanded not in files or expanded.startswith(('../','/')) or (group and not expanded.startswith(group+'/')):
                raise ValueError(f'unresolved relative DT_NEEDED: {needed}')
            resolved[needed]=expanded
            continue
        candidates = [posixpath.join(d, needed) for d in directories]
        found = next((p for p in candidates if p in files), None)
        if found:
            resolved[needed] = found
        elif needed in BASE_LIBRARIES and needed in base:
            resolved[needed] = 'system/' + needed
        else:
            raise ValueError(f'unresolved DT_NEEDED {needed} in {path}')
    return resolved


def validate_symbol_versions(record: dict, providers: dict) -> None:
    for library, versions in record['version_files'].items():
        if library not in providers:
            raise ValueError('version needs without resolved provider: '+library)
        missing=set(versions)-set(providers[library])
        if missing:
            raise ValueError('provider '+library+' missing '+','.join(sorted(missing)))


def validate_license_inventory(report: dict) -> None:
    failures = []
    if not report.get('components'):
        raise ValueError('empty license inventory')
    seen=set()
    for component in report['components']:
        if component['id'] in seen:
            failures.append('duplicate component: '+component['id'])
        seen.add(component['id'])
        if not component.get('licenses') or not component.get('materials'):
            failures.append(f"{component['id']}: missing license body or license identity")
        failures.extend(f"{component['id']}: {issue}" for issue in component.get('unresolved', []))
    if failures:
        raise ValueError('\n'.join(failures))


def _license_member(name: str) -> bool:
    base = PurePosixPath(name).name.lower()
    return '.github/workflows/' not in name and not name.endswith(('/', '.py', '.pyc')) and (any(word in base for word in ('license','licence','copying','notice','copyright')) or base == 'authors')


def _material(data: bytes, output: Path, source: dict, member: str) -> dict | None:
    if not data.strip():
        return None
    digest = _sha(data)
    dest = output / digest
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {'path': 'materials/' + digest, 'sha256':digest,'size':len(data),
            'source':source, 'source_member':member}


def _component(identifier: str, rule: dict, available: dict[str, dict], member=None) -> dict:
    selected = {name: material for name,material in available.items()
                if any(fnmatch.fnmatchcase(name, pattern) for pattern in rule.get('materials', []))}
    issues = list(rule.get('unresolved', []))
    for pattern in rule.get('materials', []):
        if not any(fnmatch.fnmatchcase(name,pattern) for name in selected):
            issues.append(f'missing required material {pattern}')
    source_materials=[]
    for pattern in rule.get('sources', []):
        found=[m['path'] for name,m in available.items() if fnmatch.fnmatchcase(name,pattern)]
        if not found:
            issues.append('missing required source material '+pattern)
        source_materials.extend(found)
    result = {'id':identifier, 'licenses':rule.get('licenses', []),
              'sources':sorted(set(source_materials)),
              'materials': sorted(set(m['path'] for m in selected.values())),
              'unresolved':issues}
    if member:
        result['member'] = member
    for key in ('kind','version','provenance','limitations'):
        if key in rule:
            result[key]=rule[key]
    return result


def wheel_inventory(path: Path, output: Path, rules: dict, source=None, supplemental=None) -> dict:
    """Preserve license bytes; every bundled ELF needs an independent explicit rule."""
    source = source or {'sha256':_digest(path),'filename':path.name}
    components, materials, native = [], dict(supplemental or {}), []
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f'duplicate wheel members: {path.name}')
        for name in names:
            _safe(name)
        metadata = [n for n in names if len(PurePosixPath(n).parts) == 2
                    and n.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise ValueError(f'wheel must have one root METADATA: {path.name}')
        meta = BytesParser().parsebytes(wheel.read(metadata[0]))
        name, version = meta['Name'], meta['Version']
        for member in names:
            if member.endswith('/'):
                continue
            with wheel.open(member) as stream:
                magic = stream.read(4)
            if magic == b'\x7fELF':
                native.append(member)
            if _license_member(member) or member == metadata[0]:
                material = _material(wheel.read(member),output,source,member)
                if material:
                    materials[member] = material
        root = metadata[0].split('/')[0]
        default = {'licenses':[meta.get('License-Expression') or 'LicenseRef-' + name],
                   'materials':[root+'/*'], 'unresolved':['component license review missing']}
        package_rule = rules.get('package', default)
        components.append(_component(name+'=='+version, package_rule, materials))
        for member in native:
            matches = [r for r in rules.get('native',[]) if fnmatch.fnmatchcase(member,r['pattern'])]
            bundled = '.libs/' in member or '/.libs/' in member or (PurePosixPath(member).name.startswith('lib') and '.cpython-' not in member)
            rule = matches[0] if len(matches)==1 else ({} if bundled else {k:v for k,v in package_rule.items() if k != 'unresolved'})
            binary_digest=_sha(wheel.read(member))
            if rule.get('binary_sha256',binary_digest)!=binary_digest:
                raise ValueError('native provenance digest mismatch: '+member)
            component=_component(name+'/'+member,rule,materials,member)
            component['binary_sha256']=binary_digest
            components.append(component)
        for index, rule in enumerate(rules.get('embedded', [])):
            components.append(_component(name+'/'+rule['id'],rule,materials))
        if native and not rules.get('native_review_complete',False):
            components[0]['unresolved'].append('native/static third-party inventory review incomplete')
    return {'components':components, 'materials':list(materials.values()),'native':native}


def validate_native_comparisons(comparisons: list, wheels: dict) -> None:
    """Bind source-section comparison evidence to the actual shipped native bytes."""
    seen = set()
    for record in comparisons:
        key = (record['wheel'], record['member'])
        if key in seen or record['wheel'] not in wheels:
            raise ValueError('duplicate or unknown native comparison wheel/member')
        seen.add(key)
        with zipfile.ZipFile(wheels[record['wheel']]) as wheel:
            if record['member'] not in wheel.namelist():
                raise ValueError('missing native comparison member: ' + record['member'])
            if _sha(wheel.read(record['member'])) != record['native']['sha256']:
                raise ValueError('native comparison member digest mismatch: ' + record['member'])
        native, original = record['native'], record['original']
        if (set(native['sections']) != {'.text', '.rodata', '.eh_frame'} or
                native['sections'] != original['sections'] or not native['build_id'] or
                native['build_id'] != original['build_id']):
            raise ValueError('native comparison source sections/build ID mismatch')


def _extract_runtime(archive: Path, target: Path) -> None:
    with tarfile.open(archive, 'r:gz') as tar:
        seen=set()
        for member in tar:
            _safe(member.name)
            if member.name in seen or not (member.isfile() or member.isdir()):
                raise ValueError('normalized runtime has duplicate or non-regular member')
            seen.add(member.name)
            path=target/member.name
            if member.isdir():
                path.mkdir(parents=True,exist_ok=True)
            else:
                path.parent.mkdir(parents=True,exist_ok=True)
                with tar.extractfile(member) as src, path.open('wb') as dst:
                    shutil.copyfileobj(src,dst)
                path.chmod(member.mode & 0o777)


def _runtime_inventory(tree: Path, cache: Path, output: Path, runtime: dict, rules: dict, supplemental=None) -> dict:
    materials=dict(supplemental or {})
    handoff=runtime['companion_archive']['materials']
    directory=cache/handoff['directory']
    index_path=directory/handoff['index']
    if _digest(index_path)!=handoff['index_sha256']:
        raise ValueError('runtime license material index hash mismatch')
    index=json.loads(index_path.read_text())
    for item in index['materials']:
        path=directory/_safe(item['path'])
        data=path.read_bytes()
        if _sha(data)!=item['sha256'] or len(data)!=item['size']:
            raise ValueError('runtime license material bytes mismatch: '+item['path'])
        if item['source_member'].endswith('PYTHON.json'):
            continue
        materials[item['source_member']]=_material(data,output,index['source'],item['source_member'])
    for path in sorted(tree.rglob('*')):
        if path.is_file() and _license_member(path.name):
            member=path.relative_to(tree).as_posix()
            source=runtime['source']
            source_member=member
            if member=='python/licenses/LICENSE.libz-system.txt':
                origin=runtime['native_repair']['inputs']['zlib_rpm']
                source=origin['source']
                source_member=origin['license_member']
            material=_material(path.read_bytes(),output,source,source_member)
            if material:
                materials[member]=material
    components=[_component(rule['id'],rule,materials) for rule in rules['components']]
    # Metadata itself is hashed in the handoff, and is authoritative for static links.
    metadata_path=next(directory/i['path'] for i in index['materials'] if i['source_member']=='python/PYTHON.json')
    metadata=json.loads(metadata_path.read_text())
    mapped={r.get('link') for r in rules['components']}
    for extension, variants in metadata['build_info']['extensions'].items():
        for variant in variants:
            for link in variant.get('links',[]):
                if link.get('path_static') and link['name'] not in mapped:
                    components.append({'id':'runtime/static/'+link['name'], 'licenses':[],
                       'materials':[], 'unresolved':['unmapped static link in '+extension]})
    for bootstrap in runtime['bootstrap_packages']:
        if bootstrap['name'] not in {r['id'] for r in rules['components']}:
            components.append({'id':bootstrap['name'], 'licenses':[], 'materials':[],
                               'unresolved':['bootstrap package not mapped']})
    return {'components':components,'materials':list(materials.values())}


def _supplemental_materials(cache: Path, output: Path, sources: list) -> dict:
    """Sources and notices are delivered byte-for-byte, bound to their reviewed input."""
    materials={}
    for item in sources:
        source=item['source']
        archive=cache/'sha256'/source['sha256']
        if not archive.exists():
            from .resolve import cache_asset
            failures=[]
            for url in [source['url'],*item.get('retrieval_urls',[])]:
                try:
                    cache_asset(url,source['sha256'],cache/'sha256')
                    break
                except (OSError,ValueError) as error:
                    failures.append(str(error))
            else:
                raise ValueError('cannot acquire pinned material '+source['filename']+': '+'; '.join(failures))
        if _digest(archive)!=source['sha256']:
            raise ValueError('supplemental source hash mismatch: '+item['name'])
        key='sources/'+source['filename']
        if item.get('deliver_archive',True):
            materials[key]=_material(archive.read_bytes(),output,source,source['filename'])
            materials[key]['kind']=item.get('kind','corresponding-source')
            materials[key]['version']=item['version']
            if item.get('archive_kind')=='file' and item.get('kind')=='license-body':
                materials['source-licenses/'+item['name']+'/'+source['filename']]=materials[key]
        if item.get('archive_kind') == 'zip':
            with zipfile.ZipFile(archive) as wheel:
                if len(wheel.namelist()) != len(set(wheel.namelist())):
                    raise ValueError('duplicate ZIP license source members')
                for member in item['license_members']:
                    _safe(member)
                    if member not in wheel.namelist():
                        raise ValueError('missing ZIP license member: '+member)
                    material=_material(wheel.read(member),output,source,member)
                    if material:
                        materials['source-licenses/'+item['name']+'/'+member]=material
        if item.get('archive_kind','tar') == 'tar':
            with tarfile.open(archive) as tar:
                for member in tar:
                    if member.isfile() and (member.name in item['license_members'] if 'license_members' in item else (_license_member(member.name) or member.name in item.get('additional_members',[]))):
                        name='source-licenses/'+item['name']+'/'+_safe(member.name)
                        material=_material(tar.extractfile(member).read(),output,source,member.name)
                        if material:
                            materials[name]=material
    return materials


def _base_libraries(cache: Path, image: str, key: str) -> dict:
    """Copy baseline userspace libraries read-only, pinned to the exact image digest."""
    directory=cache/'audit-base'/key
    directory.mkdir(parents=True,exist_ok=True)
    command=['docker','run','--rm','--network','none',image,'/sbin/ldconfig','-p']
    listing=subprocess.run(command,check=True,capture_output=True,text=True).stdout
    paths={}
    for line in listing.splitlines():
        match=re.match(r'\s*(\S+)\s+\(.*x86-64.*\)\s+=>\s+(\S+)',line)
        if match and match[1] in BASE_LIBRARIES:
            paths.setdefault(match[1],match[2])
    container=subprocess.run(['docker','create','--network','none',image],check=True,capture_output=True,text=True).stdout.strip()
    result={}
    try:
        for name,path in sorted(paths.items()):
            dest=directory/name
            subprocess.run(['docker','cp','-L',container+':'+path,str(dest)],check=True,capture_output=True)
            record=inspect_elf(dest)
            result[name]={'sha256':_digest(dest),'versions':record['version_definitions'], 'image':image}
    finally:
        subprocess.run(['docker','rm',container],check=True,capture_output=True)
    return result


def _prepare_auditwheel(cache: Path, tree: Path, dependencies: dict) -> list:
    """Install locked audit tools afresh offline, using the verified runtime bytes."""
    from .resolve import requirements_bytes
    repository=LOCKS.parent.parent
    relative=cache.relative_to(repository).as_posix()
    for package in dependencies['build_packages']:
        path=cache/'build-wheelhouse'/package['filename']
        if _digest(path)!=package['sha256']:
            raise ValueError('audit tool wheel hash mismatch: '+package['filename'])
    expected=requirements_bytes(dependencies['build_packages'])
    if (LOCKS/'build-requirements.lock').read_bytes()!=expected:
        raise ValueError('build requirements do not match locked audit tools')
    environment=cache/'audit-tool-env'
    if environment.exists():
        shutil.rmtree(environment)
    command=['docker','run','--rm','--network','none','--user',str(os.getuid())+':'+str(os.getgid()),
        '-e','HOME=/tmp','-e','PIP_CONFIG_FILE=/dev/null',
        '-v',str(repository)+':/work','-v',str(tree)+':/payload:ro',dependencies['build_image']]
    target='/work/'+relative+'/audit-tool-env'
    subprocess.run(command+['/payload/runtime/python/bin/python3','-I','-B','-m','venv',target],
        check=True,capture_output=True)
    installed=subprocess.run(command+[target+'/bin/python','-I','-B','-m','pip','--isolated','install',
        '--no-index','--require-hashes','--only-binary=:all:',
        '--find-links','/work/'+relative+'/build-wheelhouse',
        '-r','/work/packaging/offline/build-requirements.lock'],check=True,capture_output=True,text=True)
    (cache/'audit-tool-install.log').write_text(installed.stdout+installed.stderr)
    return command+[target+'/bin/python','-I','-B','-m','auditwheel','show']


def _native_report(tree: Path, baseline: dict) -> dict:
    records, errors = {}, []
    for path in sorted(tree.rglob('*')):
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            if stream.read(4)!=b'\x7fELF':
                continue
        relative=path.relative_to(tree).as_posix()
        record=inspect_elf(path)
        record['sha256']=_digest(path)
        record['cpu_evidence']='property-only; baseline execution required' if record['isa'] else 'no ISA property; static proof unavailable'
        records[relative]=record
    executable=records.get('runtime/python/bin/python3.12')
    if executable is None or executable['rpath'] != ['$ORIGIN/../lib'] or executable['runpath']:
        errors.append('runtime interpreter inherited RPATH contract is missing')
    for path,record in records.items():
        try:
            validate_elf(record)
            for target,base in baseline.items():
                resolved=resolve_needed(path,record,set(records),base, inherited=('runtime/python/lib',))
                record.setdefault('resolved',{})[target]=resolved
                providers={library:(base[library]['versions'] if provider.startswith('system/') else records[provider]['version_definitions']) for library,provider in resolved.items()}
                validate_symbol_versions(record,providers)
        except ValueError as error:
            errors.append(path+': '+str(error))
    return {'elf':records,'errors':errors,'baseline_system_libraries':baseline,
            'cpu_baseline_verified':False, 'cpu_validation_required':'Task 11 baseline x86_64 VM/QEMU; containers inherit host CPU'}


def audit(cache: Path, output: Path) -> dict:
    cache,output=cache.resolve(),output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    runtime=json.loads((LOCKS/'runtime.lock.json').read_text())
    dependencies=json.loads((LOCKS/'dependencies.lock.json').read_text())
    lock_bytes=(LOCKS/'licenses.lock.json').read_bytes()
    lock=json.loads(lock_bytes)
    lock_digest=_sha(lock_bytes)
    policy=json.loads((LOCKS/'policy.json').read_text())
    errors=[]
    wheel_errors=[]
    inventory={'components':[], 'materials':[], 'provenance':{}}
    inventory['provenance']=lock.get('provenance_records',{})
    if "cpu_build" in dependencies:
        from .cpu_wheels import validate_components, select_wheels
        from .resolve import load_cpu_builds
        components = load_cpu_builds(dependencies['cpu_build'], LOCKS)
        validate_components(components, dependencies['packages'])
        for component in components:
            select_wheels(component['proof'], cache)
        inventory['cpu_build_provenance'] = {item['id']:item['proof'] for item in components}
    supplemental=_supplemental_materials(cache,output/'materials',lock.get('sources',[]))
    for notice in lock.get('notices',[]):
        data=notice['text'].encode('utf-8')
        supplemental[notice['name']]=_material(data,output/'materials',{'kind':'qbox-authored-notice','license_lock_sha256':lock_digest},notice['name'])
    if _digest(cache/'python.tar.gz')!=runtime['normalized']['sha256']:
        raise ValueError('normalized runtime hash mismatch')
    if lock['runtime_sha256']!=runtime['normalized']['sha256']:
        raise ValueError('license lock does not bind runtime')
    with tempfile.TemporaryDirectory(prefix='qbox-audit-') as temporary:
        tree=Path(temporary)
        _extract_runtime(cache/'python.tar.gz',tree/'runtime')
        auditwheel_command=_prepare_auditwheel(cache,tree,dependencies)
        report=_runtime_inventory(tree/'runtime',cache,output/'materials',runtime,lock['runtime'],supplemental)
        inventory['components'].extend(report['components'])
        inventory['materials'].extend(report['materials'])
        wheels=dependencies['packages']+[dependencies['qbox_resolution_wheel']]
        validate_native_comparisons(lock.get('provenance_records', {}).get('cpu-build/native-runtime-comparison', []),
                                   {p['filename']:cache/'candidate-wheelhouse'/p['filename'] for p in wheels})
        auditwheel_logs=[]
        for package in wheels:
            filename=package['filename']
            path=cache/'candidate-wheelhouse'/filename
            if _digest(path)!=package['sha256']:
                raise ValueError('wheel hash mismatch: '+filename)
            rules=lock['wheels'].get(filename,{})
            if rules.get('sha256')!=package['sha256']:
                raise ValueError('license lock does not bind wheel: '+filename)
            report=wheel_inventory(path,output/'materials',rules,package.get('source',{'filename':filename,'sha256':package['sha256']}),supplemental)
            inventory['components'].extend(report['components'])
            inventory['materials'].extend(report['materials'])
            # Separate wheel roots preserve installation-relative origin lookups while
            # preventing an accidental unrelated wheel from satisfying a dependency.
            with zipfile.ZipFile(path) as wheel:
                for member in report['native']:
                    dest=tree/'wheels'/filename/member
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    dest.write_bytes(wheel.read(member))
            if report['native']:
                from .resolve import allowed_wheel, target_tags
                if not allowed_wheel(filename,target_tags()):
                    wheel_errors.append(filename+': disallowed native wheel tag')
                repository=LOCKS.parent.parent
                relative=path.relative_to(repository).as_posix()
                completed=subprocess.run(auditwheel_command+['/work/'+relative],capture_output=True,text=True,env={**os.environ,'LC_ALL':'C'})
                log=(completed.stdout+completed.stderr).replace(str(cache),'<cache>').replace(str(tree),'<payload>')
                logpath=output/'auditwheel'/ (filename+'.txt')
                logpath.parent.mkdir(parents=True,exist_ok=True)
                logpath.write_text(log)
                auditwheel_logs.append({'path':'auditwheel/'+logpath.name,'sha256':_digest(logpath),'exit_code':completed.returncode})
                if completed.returncode:
                    errors.append(filename+': auditwheel show failed')
        targets=policy['resolver']['validation_images']
        baseline={key:_base_libraries(cache,targets[tag],key) for key,tag in
                  [('rocky8','quay.io/rockylinux/rockylinux:8'),('ubuntu20','public.ecr.aws/ubuntu/ubuntu:20.04')]}
        elf_report=_native_report(tree,baseline)
        elf_report['errors'].extend(wheel_errors)
        elf_report['auditwheel']=auditwheel_logs
    try:
        validate_license_inventory(inventory)
    except ValueError as error:
        errors.extend(str(error).splitlines())
    errors.extend(elf_report['errors'])
    inventory['materials']=list({(m['path'],m['source_member']):m for m in inventory['materials']}.values())
    inventory['runtime_transformations']=runtime.get('native_repair',{})
    inventory['payload_inputs']={'runtime':runtime['normalized'], 'wheels':{p['filename']:p['sha256'] for p in wheels}}
    inventory['license_map']={}
    for component in inventory['components']:
        identifier='LicenseRef-qbox-'+_sha(component['id'].encode())[:20]
        component['license_ids']=[identifier]
        inventory['license_map'][identifier]=sorted(set(component['materials']+component.get('sources',[])))
    inventory['errors']=errors
    inventory['status']='blocked' if errors else 'passed-static'
    inventory['lock_sha256']=lock_digest
    elf_report['status']='blocked' if elf_report['errors'] or any(x['exit_code'] for x in auditwheel_logs) else 'passed-static'
    return {'license_report_sha256':_write_json(output/'licenses.json',inventory),
            'elf_report_sha256':_write_json(output/'elf.json',elf_report),
            'status':'blocked' if errors else 'passed-static', 'errors':errors}
