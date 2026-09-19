"""Pure, standalone component provenance contracts shared by build and install."""
import hashlib
import re

BUILD_ORCHESTRATOR = 'tools/offline/cpu_wheels.py'
NORMALIZER_PATH = 'tools/offline/recipes/wheel_normalize.py'
NORMALIZATION_FILES = frozenset({BUILD_ORCHESTRATOR, NORMALIZER_PATH})


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
    if not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}',proof['image']):
        raise ValueError('CPU builder image requires immutable digest')
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
