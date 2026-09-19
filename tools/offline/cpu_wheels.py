"""Explicit maintainer builds; normal offline consumers only verify cached wheels.

Custom output sources point to the upstream sdist, never the original PyPI wheel.
The separate build provenance binds recipe, source, toolchain and output bytes.
"""
import hashlib
from pathlib import Path
import re

from .model import sha256_file
from .resolve import wheel_metadata
from .recipes.wheel_normalize import normalize_wheel, validate_record

BUILD_ORCHESTRATOR = 'tools/offline/cpu_wheels.py'
NORMALIZER_PATH = 'tools/offline/recipes/wheel_normalize.py'
NORMALIZATION_FILES = frozenset({BUILD_ORCHESTRATOR, NORMALIZER_PATH})


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
    import shlex
    allowed_machine_flags = {'-march=x86-64', '-mtune=generic', '-msse', '-msse2', '-m64'}
    for name in ('CFLAGS', 'CXXFLAGS', 'FFLAGS'):
        flags = shlex.split(environment.get(name, ''))
        if '-march=x86-64' not in flags or any(f.startswith('-m') and f not in allowed_machine_flags for f in flags):
            raise ValueError('explicit x86-64 baseline required for C/C++/Fortran global flags')
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
    code_paths = [Path(__file__).relative_to(root).as_posix(), recipe['recipe'], *recipe.get('helpers', {})]
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
            (work/'source').mkdir(); (work/'source-archives').mkdir(); (work/'build-wheelhouse').mkdir()
            for item in recipe['sources']:
                shutil.copyfile(assets[item['source']['sha256']],work/'source-archives'/item['source']['filename'])
                with tarfile.open(assets[item['source']['sha256']]) as archive:
                    archive.extractall(work/'source',filter='data')
            for item in recipe['build_packages']:
                shutil.copyfile(assets[item['source']['sha256']],work/'build-wheelhouse'/item['filename'])
            (work/'build-requirements.lock').write_bytes(requirements_bytes(recipe['build_packages']))
            shutil.copyfile(recipe_path,work/'recipe.sh')
            for relative, target_name in recipe.get('helpers', {}).items():
                if Path(target_name).name != target_name:
                    raise ValueError('unsafe recipe helper name')
                shutil.copyfile(root/relative,work/target_name)
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
        record['build_provenance']=recipe.get('provenance_filename','cpu-build-provenance.json')
        records.append(record)
    provenance={'schema_version':1,'kind':'qbox-maintainer-cpu-build','code_commit':code_commit,
                'recipe_files':recipe_hashes,'patches':recipe['patches'],'image':recipe['image'],
                'input_lock_sha256':sha256_file(lock_path),'sources':[s['source'] for s in recipe['sources']],
                'build_inputs':[{k:p[k] for k in ('name','version','filename','sha256')} for p in recipe['build_packages']],
                'environment':recipe['environment'],'build_options':recipe['build_options'],
                'network':'none','repeat_builds':2,'outputs':records,'logs':logs}
    (output/'cpu-build-provenance.json').write_bytes(canonical_json(provenance))
    return finalize_wheels(output/'cpu-build-provenance.json', cache, output/'final')


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
    required_recipe_files = {BUILD_ORCHESTRATOR, recipe['recipe'], *recipe.get('helpers', {})}
    missing = required_recipe_files - proof['recipe_files'].keys()
    if missing:
        raise ValueError('CPU build recipe inventory missing: ' + ', '.join(sorted(missing)))
    if proof['image']!=recipe['image'] or proof['network']!='none' or proof['repeat_builds']!=2:
        raise ValueError('CPU build isolation/reproducibility mismatch')
    if proof.get('sources') != [s['source'] for s in recipe['sources']]:
        raise ValueError('CPU build source inventory mismatch')
    expected_build_inputs = [{k:p[k] for k in ('name','version','filename','sha256')} for p in recipe.get('build_packages',[])]
    if proof.get('build_inputs',[]) != expected_build_inputs or any(proof.get(key) != recipe.get(key) for key in ('environment','build_options')):
        raise ValueError('CPU build input/options mismatch')
    if proof.get('patches',[]) != recipe.get('patches',[]):
        raise ValueError('CPU build patch inventory mismatch')
    for patch in proof.get('patches',[]):
        if proof['recipe_files'].get(patch['path']) != patch['sha256'] or any(not re.fullmatch('[0-9a-f]{64}',patch[key]) for key in ('upstream_sha256','patched_sha256')):
            raise ValueError('CPU build patch recipe/source binding mismatch')
    inputs={s['name']:s['source'] for s in recipe['sources']}
    outputs={p['name']:p for p in proof['outputs']}
    expected=set(recipe.get('wheel_names',inputs))
    if len(outputs)!=len(proof['outputs']) or set(outputs)!=expected:
        raise ValueError('CPU build output/source inventory mismatch')
    normalization = proof.get('normalization')
    if normalization is None:
        raise ValueError('CPU normalization provenance required')
    if normalization is not None:
        normalized = {p['filename']:p['sha256'] for p in normalization['outputs']}
        expected_outputs = {p['filename']:p['sha256'] for p in proof['outputs']}
        if normalized != expected_outputs or normalization['image'] != proof['image']:
            raise ValueError('CPU normalization does not bind final outputs/image')
        if not re.fullmatch('[0-9a-f]{40}',normalization['code_commit']) or not normalization['recipe_files'] or any(not re.fullmatch('[0-9a-f]{64}', value) for value in normalization['recipe_files'].values()):
            raise ValueError('CPU normalization code identity missing')
        missing = NORMALIZATION_FILES - normalization['recipe_files'].keys()
        if missing:
            raise ValueError('CPU normalization recipe inventory missing: ' + ', '.join(sorted(missing)))
        compiled = {p['filename']:p['sha256'] for p in proof['compilation_outputs']}
        if normalization['network'] != 'none' or normalization['independent_runs'] != 2 or normalization['inputs'] != [{'run':n, 'wheels':compiled} for n in (1,2)]:
            raise ValueError('CPU normalization input/isolation mismatch')
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


def finalize_wheels(provenance_path, cache, output):
    """Canonicalize both compiled runs inside the pinned image, without rebuilding.

    Separate stage commits preserve truthful provenance when completed compiles are
    reused. The final wheel output no longer depends on host zipfile/zlib versions.
    """
    import json
    import os
    import shutil
    import subprocess
    from .model import canonical_json

    provenance_path, cache, output = Path(provenance_path).resolve(), Path(cache).resolve(), Path(output).resolve()
    proof = json.loads(provenance_path.read_text())
    root = Path(__file__).resolve().parents[2]
    paths = sorted(NORMALIZATION_FILES)
    subprocess.run(['git','diff','--exit-code','HEAD','--',*paths],cwd=root,check=True,capture_output=True)
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    image = proof['image']
    if not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', image):
        raise ValueError('normalization image requires immutable digest')
    output.mkdir(parents=True,exist_ok=True)
    runs=[]; inputs=[]
    expected={p['filename']:p['sha256'] for p in proof['outputs']}
    for number in (1,2):
        incoming=provenance_path.parent/f'run-{number}'
        actual={p.name:sha256_file(p) for p in incoming.glob('*.whl')}
        if actual!=expected:
            raise ValueError('normalization input differs from independently compiled wheel records')
        outgoing=output/f'run-{number}';outgoing.mkdir()
        command=['docker','run','--rm','--network','none','--user',f'{os.getuid()}:{os.getgid()}',
                 '-v',f'{incoming}:/input:ro','-v',f'{outgoing}:/output',
                 '-v',f'{root/NORMALIZER_PATH}:/normalize.py:ro',image,
                 '/opt/python/cp312-cp312/bin/python','-I','-B','/normalize.py','/input','/output']
        subprocess.run(command,check=True,capture_output=True)
        runs.append(sorted(outgoing.glob('*.whl')))
        inputs.append({'run':number,'wheels':actual})
    compare_builds(*runs)
    records=[]
    for path in runs[0]:
        old=next(p for p in proof['outputs'] if p['name']==wheel_metadata(path)['name'])
        records.append({**old,**wheel_metadata(path)})
    proof['compilation_outputs']=proof['outputs']
    proof['outputs']=records
    proof['normalization']={'code_commit':commit,'recipe_files':{p:sha256_file(root/p) for p in paths},
                            'image':image,'network':'none','independent_runs':2,'inputs':inputs,
                            'outputs':[{k:p[k] for k in ('name','filename','sha256')} for p in records]}
    (output/'cpu-build-provenance.json').write_bytes(canonical_json(proof))
    target=cache/'cpu-wheelhouse';target.mkdir(exist_ok=True)
    for path in runs[0]:
        dest=target/path.name
        if dest.exists() and sha256_file(dest)!=sha256_file(path):
            raise ValueError('preserve differing cached CPU wheel before final promotion')
        shutil.copyfile(path,dest)
        content=cache/'sha256'/sha256_file(path)
        if content.exists() and sha256_file(content)!=sha256_file(path):
            raise ValueError('corrupt content-addressed CPU wheel cache')
        shutil.copyfile(path,content)
    return proof


def validate_components(components, packages):
    """Validate independently built components without rewriting their histories."""
    ids = set()
    outputs = set()
    for component in components:
        identity = component['id']
        if not re.fullmatch('[a-z][a-z0-9-]*', identity) or identity in ids:
            raise ValueError('invalid or duplicate CPU build component')
        ids.add(identity)
        names = {p['name'] for p in component['proof']['outputs']}
        if outputs.intersection(names):
            raise ValueError('overlapping CPU build component outputs')
        outputs.update(names)
        validate_provenance(component['proof'], component['input_bytes'], packages)
    custom = {p['name'] for p in packages if p.get('build_provenance') or '-1qboxcpu-' in p.get('filename','')}
    if custom != outputs:
        raise ValueError('uncovered CPU build component outputs')
