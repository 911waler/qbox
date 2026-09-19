"""Standalone release verification. Run the bundled python with -I -B.

Only first prepared verification creates metadata/installed-files.json. Reports go to
stdout; the caller may persist them at the explicitly excluded report paths.
"""
import argparse
import base64
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import zipfile

# A deliberately pinned private API: absence or parse errors are fatal.
_PACKAGING_ERROR = None
try:
    from pip._vendor.packaging.markers import Marker
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.specifiers import SpecifierSet
    from pip._vendor.packaging.utils import canonicalize_name
except ImportError as exc:
    _PACKAGING_ERROR = str(exc)

EXCLUDED = frozenset('metadata/'+name for name in (
    'installed.json', 'installed-files.json', 'verification-prepared.json',
    'verification-final.json', 'verification-reuse.json', 'smoke.json'))


def canonical(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def within(root, path):
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('path escapes release: '+str(path))
    return path


def relative(root, name):
    if not isinstance(name,str) or name.startswith('/') or any(p in ('','.','..') for p in name.split('/')):
        raise ValueError('unsafe relative path: '+str(name))
    return within(root, root/name)


def sibling(name):
    spec = importlib.util.spec_from_file_location('qbox_check_'+name,Path(__file__).with_name(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_dependency_edges(edges, installed):
    versions = {canonicalize_name(k):v for k,v in installed.items()}
    for edge in edges:
        if edge.get('marker') and not Marker(edge['marker']).evaluate({'extra':edge.get('extra','')}):
            continue
        name = canonicalize_name(edge['name'])
        if name not in versions:
            raise ValueError('missing dependency: '+name)
        if not SpecifierSet(edge.get('specifier','')).contains(versions[name],prereleases=True):
            raise ValueError('dependency version mismatch: '+name)


def resolve_edges(requirements, enabled):
    """Resolve actual target markers and propagate requested transitive extras."""
    active = {canonicalize_name(k):set(v)|{''} for k,v in enabled.items()}
    records = {canonicalize_name(k):v for k,v in requirements.items()}
    result = {}
    changed = True
    while changed:
        changed = False
        for parent, extras in list(active.items()):
            if parent not in records:
                raise ValueError('missing dependency METADATA: '+parent)
            for raw in records[parent]:
                requirement = Requirement(raw)
                if requirement.url:
                    raise ValueError('URL dependency forbidden: '+raw)
                for extra in sorted(extras):
                    if requirement.marker and not requirement.marker.evaluate({'extra':extra}):
                        continue
                    name = canonicalize_name(requirement.name)
                    edge = {'parent':parent,'extra':extra,'name':name,'specifier':str(requirement.specifier),'marker':str(requirement.marker) if requirement.marker else ''}
                    result[canonical(edge)] = edge
                    old = active.setdefault(name,set())
                    additions = {''}|set(requirement.extras)
                    if not additions <= old:
                        old.update(additions); changed = True
    return [result[k] for k in sorted(result)]


def inventory(root):
    """Hash every installed entry, without following directory symlinks."""
    entries = []
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        within(root,path)
        if name in EXCLUDED:
            if path.is_symlink() or not path.is_file():
                raise ValueError('excluded metadata must be a regular file: '+name)
            continue
        info = path.lstat()
        entry = {'path':name,'mode':stat.S_IMODE(info.st_mode)}
        if path.is_symlink():
            if not path.exists(): raise ValueError('dangling release link: '+name)
            entry.update(kind='symlink',target=os.readlink(path))
        elif path.is_file():
            entry.update(kind='file',size=info.st_size,sha256=sha256(path))
        elif path.is_dir():
            entry.update(kind='directory')
        else:
            raise ValueError('unsupported installed file: '+name)
        entries.append(entry)
    return {'schema_version':1,'files':entries}


def compare_inventory(root, expected):
    if inventory(root) != expected:
        raise ValueError('installed inventory bytes, mode, target or path mismatch')


def check_inventory(root, phase, digest):
    path=within(root,root/'metadata/installed-files.json')
    if path.is_symlink(): raise ValueError('installed inventory cannot be a symlink')
    if phase == 'prepared' and not path.exists():
        if digest != '0'*64:
            raise ValueError('missing sealed installed inventory')
        # Exclusive creation prevents a repeated prepared check blessing corruption.
        with path.open('xb') as stream: stream.write(canonical(inventory(root)))
    else:
        if sha256(path) != digest:
            raise ValueError('installed inventory digest mismatch')
        compare_inventory(root,json.loads(path.read_bytes()))
    return sha256(path)


def verify_resources(root, package):
    for path in (root/'bin/qbox',package/'legacy/entry.sh'):
        within(root,path)
        if not path.is_file(): raise ValueError('missing required resource: '+path.name)
    if not os.access(root/'bin/qbox',os.X_OK):
        raise ValueError('bin/qbox is not executable')


def verify_record(dist, root):
    files = dist.files
    if not files: raise ValueError('missing installed RECORD: '+dist.metadata['Name'])
    for item in files:
        path = within(root, Path(dist.locate_file(item)))
        if not path.is_file(): raise ValueError('missing installed file: '+str(item))
        if item.hash:
            if item.hash.mode != 'sha256': raise ValueError('unsupported RECORD hash: '+str(item))
            actual = base64.urlsafe_b64encode(bytes.fromhex(sha256(path))).rstrip(b'=').decode()
            if actual != item.hash.value: raise ValueError('corrupt installed file: '+str(item))
        if item.size is not None and path.stat().st_size != item.size:
            raise ValueError('installed file size mismatch: '+str(item))


def verify_interpreter(root, manifest):
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise ValueError('bundled interpreter must run with -I -B')
    if Path(sys.executable).resolve() != (root/'python/bin/python3').resolve() or Path(sys.prefix).resolve() != root/'python':
        raise ValueError('wrong bundled interpreter/prefix')
    if '.'.join(map(str,sys.version_info[:3])) != manifest['runtime']['version'] or sys.version_info[:2] != (3,12):
        raise ValueError('Python patch version mismatch')
    for entry in sys.path:
        if not entry or not Path(entry).resolve().is_relative_to(root/'python'):
            raise ValueError('non-bundled sys.path entry: '+entry)


def verify_distributions(root, manifest, lock):
    installed = {}
    distributions = {}
    for dist in metadata.distributions():
        name = canonicalize_name(dist.metadata['Name'])
        if name in installed: raise ValueError('duplicate distribution: '+name)
        installed[name]=dist.version; distributions[name]=dist
        within(root,Path(dist.locate_file('')))
        if name != 'pip': verify_record(dist,root)
    expected = {canonicalize_name(p['name']):p['version'] for p in manifest['wheels']}
    # Runtime pip vendors are embedded packages, not separate distributions.
    bootstrap = manifest['bootstrap_packages']
    for item in bootstrap:
        if not item['name'].startswith('pip-vendor-'):
            expected[canonicalize_name(item['name'])]=item['version']
    if installed != expected: raise ValueError('installed distribution/version inventory differs from manifest')
    pip = distributions['pip']
    vendor_text = Path(pip.locate_file('pip/_vendor/vendor.txt')).read_text()
    vendor_pins = {}
    for raw in vendor_text.splitlines():
        raw = raw.split('#',1)[0].strip()
        if raw:
            req=Requirement(raw)
            vendor_pins['pip-vendor-'+canonicalize_name(req.name)]=str(req.specifier).removeprefix('==')
    for item in bootstrap:
        if item['name'].startswith('pip-vendor-') and vendor_pins.get(item['name']) != item['version']:
            raise ValueError('pip vendored package version mismatch: '+item['name'])
    locked = {canonicalize_name(p['name']):p for p in lock['packages']}
    locked['qbox']=lock['qbox_resolution_wheel']
    records = {}
    for name,item in locked.items():
        if installed.get(name) != item['version']: raise ValueError('lock version mismatch: '+name)
        actual=distributions[name].requires or []
        if sorted(str(Requirement(r)) for r in actual) != sorted(str(Requirement(r)) for r in item['requires_dist']):
            raise ValueError('METADATA requirements differ from lock: '+name)
        records[name]=actual
    if set(locked) != {canonicalize_name(p['name']) for p in manifest['wheels']}:
        raise ValueError('lock wheel inventory differs from manifest')
    enabled={name:set() for name in records}; enabled['qbox']=set(manifest['extras'])
    edges=resolve_edges(records,enabled)
    verify_dependency_edges(edges,installed)
    import qbox
    if qbox.__version__ != manifest['qbox_version']:
        raise ValueError('imported qbox version differs from manifest')
    package=Path(qbox.__file__).resolve().parent
    within(root/'python',package)
    verify_resources(root,package)
    return {'distributions':len(installed),'resolved_edges':len(edges)}



def verify_manifest(root, path, manifest):
    sibling('manifest').validate_manifest(manifest)
    within(root,path)
    if path.is_symlink(): raise ValueError('manifest cannot be a symlink')
    if path.resolve() != (root/'metadata/manifest.json').resolve():
        raise ValueError('manifest must be the installed metadata/manifest.json')
    return manifest['release_id']


def verify_marker(root, manifest, phase, digest):
    path=within(root,root/'metadata/installed.json')
    if path.is_symlink(): raise ValueError('installed marker cannot be a symlink')
    marker=json.loads(path.read_bytes())
    if set(marker) != {'schema_version','product','release_id','manifest_sha256','state','inventory_sha256'}:
        raise ValueError('invalid installed marker fields')
    if marker['schema_version'] != 1 or marker['product'] != 'qbox' or marker['release_id'] != manifest['release_id'] or marker['manifest_sha256'] != digest:
        raise ValueError('installed marker identity mismatch')
    states={'prepared':{'prepared'},'final':{'prepared','verified'},'reuse':{'verified'}}
    if marker['state'] not in states[phase]: raise ValueError('invalid marker state for '+phase)
    if not isinstance(marker['inventory_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',marker['inventory_sha256']):
        raise ValueError('invalid inventory digest in marker')
    return marker



def verify_runtime_files(root, archive_path):
    # Normalized runtime has relocated pip shebangs. Its tar bytes, not pip's
    # historical RECORD, are authoritative for the complete bootstrap runtime.
    with tarfile.open(archive_path,'r:gz') as archive:
        for member in archive:
            path=relative(root,member.name.rstrip('/'))
            if member.isdir():
                if not path.is_dir(): raise ValueError('missing runtime directory: '+member.name)
            elif member.isfile():
                with archive.extractfile(member) as stream:
                    digest=hashlib.file_digest(stream,'sha256').hexdigest()
                if not path.is_file() or sha256(path) != digest:
                    raise ValueError('installed runtime file differs from normalized archive: '+member.name)
            else:
                raise ValueError('normalized runtime must contain dereferenced files: '+member.name)


def verify_wheel_files(root, archive_path):
    site=root/'python/lib/python3.12/site-packages'
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            if member.is_dir() or member.filename.endswith('.dist-info/RECORD'):
                continue
            name=member.filename
            if '.data/' in name:
                _,kind,name=name.split('/',2)
                if kind == 'scripts':
                    # pip transforms shebangs; the installed RECORD covers these.
                    continue
                if kind in ('purelib','platlib'): path=relative(site,name)
                elif kind == 'data': path=relative(root/'python',name)
                else: raise ValueError('unsupported wheel installation scheme: '+kind)
            else:
                path=relative(site,name)
            with archive.open(member) as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if not path.is_file() or sha256(path) != digest:
                raise ValueError('installed wheel file differs from archive: '+member.filename)

def verify_payload(root, manifest, bundle=None):
    """Bind retained evidence; only prepared can rehash original archive bytes."""
    files={p['path']:p for p in manifest['files']}
    if bundle is not None:
        if (bundle/'manifest.json').read_bytes() != (root/'metadata/manifest.json').read_bytes():
            raise ValueError('bundle and installed manifest differ')
        for name,item in files.items():
            path=relative(bundle,name)
            if not path.is_file() or path.is_symlink() or path.stat().st_size != item['size'] or sha256(path) != item['sha256']:
                raise ValueError('bundle artifact mismatch: '+name)
    if bundle is not None:
        verify_runtime_files(root,relative(bundle,manifest['runtime']['path']))
        for wheel in manifest['wheels']:
            verify_wheel_files(root,relative(bundle,wheel['path']))
    for name,item in files.items():
        if name.startswith('checks/'):
            path=relative(root/'metadata',name)
        elif name == 'requirements.lock':
            path=root/'metadata/requirements.lock'
        else:
            continue
        if not path.is_file() or path.is_symlink() or path.stat().st_size != item['size'] or sha256(path) != item['sha256']:
            raise ValueError('retained evidence mismatch: '+name)
    for required in ('checks/dependencies.lock.json','checks/runtime.lock.json','checks/verify.py','checks/manifest.py','checks/provenance.py','checks/smoke.py'):
        if required not in manifest['identity']['checks']:
            raise ValueError('required check missing from identity: '+required)
    if sha256(root/'bin/qbox') != files['checks/qbox-launcher.sh']['sha256']:
        raise ValueError('installed launcher differs from manifest')
    lock=json.loads((root/'metadata/checks/dependencies.lock.json').read_bytes())
    runtime=json.loads((root/'metadata/checks/runtime.lock.json').read_bytes())
    if runtime['version'] != manifest['runtime']['version'] or runtime['normalized']['sha256'] != manifest['runtime']['sha256']:
        raise ValueError('runtime lock identity mismatch')
    if {(p['name'],p['version']) for p in runtime['bootstrap_packages']} != {(p['name'],p['version']) for p in manifest['bootstrap_packages']}:
        raise ValueError('bootstrap package inventory differs from runtime lock')
    if lock['extras'] != manifest['extras']:
        raise ValueError('lock extras differ from manifest')
    locked={canonicalize_name(p['name']):p for p in lock['packages']}
    actual=[]
    for wheel in manifest['wheels']:
        name=canonicalize_name(wheel['name'])
        if name == 'qbox': continue
        if name not in locked: raise ValueError('manifest wheel missing from lock: '+name)
        record=locked[name]
        if any(record[key] != wheel[key] for key in ('name','version','sha256','size','source')) or record['filename'] != Path(wheel['path']).name:
            raise ValueError('manifest wheel differs from lock: '+name)
        actual.append(record)
    if len(actual) != len(locked): raise ValueError('lock package inventory mismatch')
    components=[]
    for item in lock['cpu_build']:
        inputs=relative(root/'metadata','checks/'+item['inputs'])
        proof_path=relative(root/'metadata','checks/'+item['provenance'])
        for path,digest in ((inputs,item['inputs_sha256']),(proof_path,item['provenance_sha256'])):
            name=path.relative_to(root/'metadata').as_posix()
            if manifest['identity']['checks'].get(name) != digest or sha256(path) != digest:
                raise ValueError('component proof/input digest mismatch: '+name)
        proof=json.loads(proof_path.read_bytes())
        for stage,record in (('compile',proof),('normalize',proof['normalization'])):
            for name,digest in record['recipe_files'].items():
                delivered='checks/cpu-build/'+stage+'/'+item['id']+'/'+name
                path=relative(root/'metadata',delivered)
                if manifest['identity']['checks'].get(delivered) != digest or sha256(path) != digest:
                    raise ValueError('CPU recipe digest mismatch: '+delivered)
        components.append({'id':item['id'],'input_bytes':inputs.read_bytes(),'proof':proof})
    sibling('provenance').validate_components(components,actual)
    return lock

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True,type=Path)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--bundle',type=Path,help='original bundle, required for prepared phase')
    parser.add_argument('--phase',required=True,choices=('prepared','final','reuse'))
    args=parser.parse_args(argv)
    report={'schema_version':1,'release_id':None,'manifest_sha256':None,'phase':args.phase,'checks':[]}
    def check(name, action):
        try: detail=action()
        except Exception as exc:
            report['checks'].append({'name':name,'status':'failed','detail':str(exc)})
            raise
        report['checks'].append({'name':name,'status':'passed','detail':detail})
        return detail
    try:
        if _PACKAGING_ERROR:
            raise ValueError('pinned pip vendored packaging unavailable: '+_PACKAGING_ERROR)
        root=args.release.resolve(strict=True)
        if args.phase == 'prepared' and args.bundle is None:
            raise ValueError('--bundle is required for prepared phase')
        manifest=json.loads(args.manifest.read_bytes())
        report.update(release_id=manifest.get('release_id'),manifest_sha256=sha256(args.manifest))
        check('manifest', lambda: verify_manifest(root,args.manifest,manifest))
        marker=check('marker',lambda: verify_marker(root,manifest,args.phase,report['manifest_sha256']))
        check('interpreter',lambda:verify_interpreter(root,manifest))
        lock=check('payload-provenance',lambda:verify_payload(root,manifest,args.bundle.resolve(strict=True) if args.phase == 'prepared' else None))
        report['checks'][-1]['detail']={'components':len(lock['cpu_build']),'original_bundle_rehashed':args.phase=='prepared'}
        check('distributions-resources-extras',lambda:verify_distributions(root,manifest,lock))
        def pip_check():
            result=subprocess.run([sys.executable,'-I','-B','-m','pip','--isolated','check'],capture_output=True,text=True)
            if result.returncode: raise ValueError(result.stdout+result.stderr)
            return result.stdout.strip()
        check('pip-check',pip_check)
        check('inventory',lambda:check_inventory(root,args.phase,marker['inventory_sha256']))
    except Exception as exc:
        if not report['checks'] or report['checks'][-1]['status'] != 'failed':
            report['checks'].append({'name':'input','status':'failed','detail':str(exc)})
        print(json.dumps(report,sort_keys=True));return 1
    print(json.dumps(report,sort_keys=True));return 0


if __name__ == '__main__':
    raise SystemExit(main())
