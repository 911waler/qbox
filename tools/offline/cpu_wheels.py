"""Explicit maintainer builds; normal offline consumers only verify cached wheels.

Custom output sources point to the upstream sdist, never the original PyPI wheel.
The separate build provenance binds recipe, source, toolchain and output bytes.
"""
import base64
import csv
import hashlib
import io
from pathlib import Path
import re
import zipfile

from .model import sha256_file
from .resolve import wheel_metadata


def validate_record(path):
    """Require a complete SHA256 RECORD, including sizes and no extra ZIP members."""
    with zipfile.ZipFile(path) as wheel:
        members = wheel.namelist()
        records = [n for n in members if n.count('/') == 1 and n.endswith('.dist-info/RECORD')]
        if len(records) != 1 or len(set(members)) != len(members):
            raise ValueError('invalid wheel RECORD or duplicate ZIP members')
        rows = list(csv.reader(io.StringIO(wheel.read(records[0]).decode())))
        if any(len(r) != 3 for r in rows) or len({r[0] for r in rows}) != len(rows):
            raise ValueError('invalid RECORD rows')
        if {r[0] for r in rows} != {n for n in members if not n.endswith('/')}:
            raise ValueError('RECORD does not cover exact wheel members')
        for name, digest, size in rows:
            if name == records[0]:
                if digest or size:
                    raise ValueError('RECORD must not hash itself')
                continue
            data = wheel.read(name)
            expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
            if digest != expected or size != str(len(data)):
                raise ValueError('RECORD content mismatch: ' + name)


def select_wheels(lock, cache):
    """No network/build fallback: missing custom bytes need explicit maintainer build."""
    result = []
    seen = set()
    for item in lock['outputs']:
        name = item['filename']
        if Path(name).name != name or item['name'] in seen:
            raise ValueError('unsafe or duplicate CPU wheel selection')
        seen.add(item['name'])
        path = Path(cache)/'cpu-wheelhouse'/name
        if not path.is_file():
            raise ValueError('missing CPU wheel; run explicit cpu-build: '+name)
        if sha256_file(path) != item['sha256']:
            raise ValueError('CPU wheel hash mismatch: '+name)
        metadata = wheel_metadata(path)
        if metadata['name'] != item['name'] or metadata['version'] != item['version']:
            raise ValueError('CPU wheel identity mismatch: '+name)
        validate_record(path)
        result.append(path)
    return result


def validate_recipe(recipe):
    if not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', recipe['image']):
        raise ValueError('builder image requires immutable digest')
    environment = recipe['environment']
    for key, value in environment.items():
        if key.startswith(('LD_', 'PIP_')) or '-march=native' in value or '-mtune=native' in value or '-xHost' in value:
            raise ValueError('native or inherited toolchain flags forbidden')
    for group in ('sources', 'build_packages'):
        for item in recipe[group]:
            source = item['source']
            if not source['url'].startswith('https://') or not re.fullmatch('[0-9a-f]{64}',source['sha256']):
                raise ValueError('build input requires fixed HTTPS source and SHA256')


def compare_builds(first, second):
    a = {p.name: sha256_file(p) for p in first}
    b = {p.name: sha256_file(p) for p in second}
    if not a or a != b:
        raise ValueError('CPU wheel builds are not byte reproducible')
    return a


def normalize_wheel(path, output):
    """Canonical wheel ZIP/RECORD and visible build tag; payload bytes are preserved."""
    from packaging.utils import parse_wheel_filename
    path, output = Path(path), Path(output)
    validate_record(path)
    name, version, _, tags = parse_wheel_filename(path.name)
    parts = path.name[:-4].split('-')
    filename = '-'.join([parts[0], parts[1], '1qboxcpu', *parts[-3:]]) + '.whl'
    with zipfile.ZipFile(path) as wheel:
        files = {n: wheel.read(n) for n in wheel.namelist() if not n.endswith('/')}
    record = next(n for n in files if n.count('/') == 1 and n.endswith('.dist-info/RECORD'))
    metadata = record.rsplit('/', 1)[0] + '/WHEEL'
    lines = [line for line in files[metadata].decode().splitlines() if not line.startswith('Build:')]
    files[metadata] = ('\n'.join(lines).rstrip() + '\nBuild: 1qboxcpu\n').encode()
    del files[record]
    rows = [[n, 'sha256='+base64.urlsafe_b64encode(hashlib.sha256(d).digest()).rstrip(b'=').decode(), str(len(d))] for n,d in sorted(files.items())]
    rows.append([record,'',''])
    stream = io.StringIO(); csv.writer(stream,lineterminator='\n').writerows(rows)
    files[record] = stream.getvalue().encode()
    output.mkdir(parents=True, exist_ok=True)
    dest = output/filename
    with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as wheel:
        for member, data in sorted(files.items()):
            info=zipfile.ZipInfo(member,(2025,9,1,0,0,0))
            info.create_system=3
            info.external_attr=0o100644 << 16
            info.compress_type=zipfile.ZIP_DEFLATED
            wheel.writestr(info,data,compresslevel=9)
    validate_record(dest)
    return dest


def build_wheels(lock_path, cache, output, *, fetch=False):
    """Two clean, network-none builds. Write candidate outputs; never promote locks.

    Acquisition is explicit (`fetch=True`) and uses only input-lock HTTPS/SHA pairs.
    Missing cached inputs otherwise fail before Docker executes.
    """
    import json
    import os
    import shutil
    import subprocess
    import tarfile
    import tempfile
    from .model import canonical_json
    from .resolve import cache_asset, requirements_bytes

    lock_path, cache, output = Path(lock_path).resolve(), Path(cache).resolve(), Path(output).resolve()
    root = Path(__file__).resolve().parents[2]
    recipe = json.loads(lock_path.read_text())
    validate_recipe(recipe)
    recipe_path = root/recipe['recipe']
    code_paths = [Path(__file__).relative_to(root).as_posix(), recipe['recipe']]
    # A real committed recipe precedes artifact construction; the input lock has
    # its own SHA, so no circular commit/output hash is introduced.
    subprocess.run(['git','diff','--exit-code','HEAD','--',*code_paths],cwd=root,check=True,capture_output=True)
    code_commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    recipe_hashes = {p:sha256_file(root/p) for p in code_paths}
    assets={}
    for item in recipe['sources']+recipe['build_packages']:
        source=item['source']; digest=source['sha256']
        path=cache/'sha256'/digest
        if not path.exists() and not fetch:
            raise ValueError('missing pinned build input; use explicit cpu-build --fetch: '+source['filename'])
        path=cache_asset(source['url'],digest,cache/'sha256')
        assets[digest]=path
    output.mkdir(parents=True,exist_ok=True)
    runs=[]; logs=[]
    for number in (1,2):
        with tempfile.TemporaryDirectory(prefix='cpu-build-',dir=cache) as temporary:
            work=Path(temporary)
            (work/'source').mkdir(); (work/'build-wheelhouse').mkdir()
            for item in recipe['sources']:
                with tarfile.open(assets[item['source']['sha256']]) as archive:
                    archive.extractall(work/'source',filter='data')
            for item in recipe['build_packages']:
                shutil.copyfile(assets[item['source']['sha256']],work/'build-wheelhouse'/item['filename'])
            (work/'build-requirements.lock').write_bytes(requirements_bytes(recipe['build_packages']))
            shutil.copyfile(recipe_path,work/'recipe.sh')
            command=['docker','run','--rm','--network','none','--user',f'{os.getuid()}:{os.getgid()}', '-v',f'{work}:/build']
            for key,value in sorted(recipe['environment'].items()):
                command+=['-e',f'{key}={value}']
            command += [recipe['image'],'/bin/sh','/build/recipe.sh']
            log=output/f'build-{number}.log'
            with log.open('wb') as stream:
                subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True)
            wheels=[normalize_wheel(p,output/f'run-{number}') for p in sorted((work/'repaired').glob('*.whl'))]
            runs.append(wheels); logs.append({'filename':log.name,'sha256':sha256_file(log)})
    compare_builds(*runs)
    records=[]
    for path in runs[0]:
        record=wheel_metadata(path)
        source=next(s['source'] for s in recipe['sources'] if s['name']==record['name'])
        record['source']=source
        record['build_provenance']='cpu-build-provenance.json'
        records.append(record)
    provenance={'schema_version':1,'kind':'qbox-maintainer-cpu-build','code_commit':code_commit,
                'recipe_files':recipe_hashes,'patches':recipe['patches'],'image':recipe['image'],
                'input_lock_sha256':sha256_file(lock_path),'sources':[s['source'] for s in recipe['sources']],
                'build_inputs':[{k:p[k] for k in ('name','version','filename','sha256')} for p in recipe['build_packages']],
                'environment':recipe['environment'],'build_options':recipe['build_options'],
                'network':'none','repeat_builds':2,'outputs':records,'logs':logs}
    (output/'cpu-build-provenance.json').write_bytes(canonical_json(provenance))
    target=cache/'cpu-wheelhouse';target.mkdir(exist_ok=True)
    for path in runs[0]:
        dest=target/path.name
        if dest.exists() and sha256_file(dest)!=sha256_file(path):
            raise ValueError('existing CPU wheel differs; review and preserve it before promotion')
        shutil.copyfile(path,dest)
    return provenance


def validate_provenance(proof, input_lock_bytes, packages):
    """Builder/validator contract: bind custom outputs to actual wheel records.

    Deliver cpu-build-provenance.json and cpu-build-inputs.lock.json in checks;
    bind both in manifest identity.checks. Rehash delivered wheel files before
    passing their records here. A readable provenance file alone is insufficient.
    """
    import json
    if hashlib.sha256(input_lock_bytes).hexdigest()!=proof['input_lock_sha256']:
        raise ValueError('CPU build input lock hash mismatch')
    recipe=json.loads(input_lock_bytes)
    if proof['kind']!='qbox-maintainer-cpu-build' or not re.fullmatch('[0-9a-f]{40}',proof['code_commit']):
        raise ValueError('CPU build requires actual recipe code commit')
    if not proof['recipe_files'] or any(not re.fullmatch('[0-9a-f]{64}',v) for v in proof['recipe_files'].values()):
        raise ValueError('CPU build recipe hashes missing')
    if proof['image']!=recipe['image'] or proof['network']!='none' or proof['repeat_builds']!=2:
        raise ValueError('CPU build isolation/reproducibility mismatch')
    inputs={s['name']:s['source'] for s in recipe['sources']}
    outputs={p['name']:p for p in proof['outputs']}
    if len(outputs)!=len(proof['outputs']) or set(outputs)!=set(inputs):
        raise ValueError('CPU build output/source inventory mismatch')
    actual={p['name']:p for p in packages}
    for name,item in outputs.items():
        if name not in actual or any(actual[name][k]!=item[k] for k in ('filename','sha256','source')):
            raise ValueError('CPU build output does not bind delivered wheel: '+name)
        if item['source']!=inputs[name] or '-1qboxcpu-' not in item['filename']:
            raise ValueError('CPU build output source/tag mismatch: '+name)


def apply_selection(wheelhouse, proof, cache):
    """Replace resolver candidates only, using prebuilt hash-verified CPU wheels."""
    import shutil
    replacements=select_wheels(proof,cache)
    names={item['name'] for item in proof['outputs']}
    for path in Path(wheelhouse).glob('*.whl'):
        if wheel_metadata(path)['name'] in names:
            path.unlink()
    for path in replacements:
        shutil.copyfile(path,Path(wheelhouse)/path.name)
