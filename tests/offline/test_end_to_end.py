"""Maintainer driver for an actual candidate, never a release acceptance shortcut.

QBOX_OFFLINE_CANDIDATE is mandatory for the real test. The target has no host
Python: run-target.sh installs first, then uses that release's isolated Python.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


@unittest.skipUnless(os.environ.get('QBOX_OFFLINE_CANDIDATE'),
                     'QBOX_OFFLINE_CANDIDATE not set: actual candidate NOT VERIFIED')
class ActualCandidateTests(unittest.TestCase):
    def test_candidate_in_private_offline_target(self):
        candidate_path = Path(os.environ['QBOX_OFFLINE_CANDIDATE']).resolve(strict=True)
        candidate = json.loads(candidate_path.read_text())
        self.assertNotIn('test-fixture', candidate)
        self.assertEqual(Path(candidate['artifact']).name, candidate['artifact'])
        archive = candidate_path.parent / candidate['artifact']
        self.assertEqual(digest(archive), candidate['artifact_sha256'])
        evidence = Path(os.environ.get('QBOX_E2E_EVIDENCE',
                                       ROOT / 'build/offline/end-to-end')).resolve()
        evidence.mkdir(parents=True, exist_ok=True)
        harness=evidence/'run-target.sh'
        harness.write_bytes((ROOT/'tests/offline/run-target.sh').read_bytes())
        # Reuse a verified extraction only after checking its entire byte inventory.
        bundle = Path(os.environ.get('QBOX_E2E_BUNDLE', evidence / 'bundle')).resolve()
        if not bundle.exists():
            bundle.mkdir()
            with tarfile.open(archive) as source:
                for member in source:
                    parts = Path(member.name).parts
                    self.assertFalse(Path(member.name).is_absolute())
                    self.assertNotIn('..', parts)
                    self.assertTrue(member.isfile() or member.isdir())
                source.extractall(bundle, filter='data')
        self.assertEqual(digest(bundle / 'manifest.json'), candidate['manifest_sha256'])
        manifest = json.loads((bundle / 'manifest.json').read_text())
        self.assertEqual(manifest['release_id'], candidate['release_id'])
        self.assertEqual(manifest['source']['commit'], candidate['source_commit'])
        self.assertEqual(digest(bundle / 'checks/final-payload-audit.json'), candidate['audit_sha256'])
        expected = {r['path'] for r in manifest['files']} | {'manifest.json', 'SHA256SUMS'}
        self.assertEqual({p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}, expected)
        self.assertFalse(any(p.is_symlink() for p in bundle.rglob('*')))
        for record in manifest['files']:
            self.assertEqual(digest(bundle / record['path']), record['sha256'], record['path'])
            self.assertEqual((bundle / record['path']).stat().st_size, record['size'])
        config = evidence / 'hostile-global-pip.conf'
        config.write_text('[global]\nindex-url = http://127.0.0.1:9/poison\n'
                          'no-binary = :all:\ntarget = /forbidden-global-target\n'
                          'prefix = /forbidden-global-prefix\n')
        images = json.loads((ROOT / 'packaging/offline/images.lock.json').read_text())
        image = os.environ.get('QBOX_E2E_IMAGE', images['validation']['public.ecr.aws/ubuntu/ubuntu:20.04'])
        self.assertIn(image, images['validation'].values())
        command = ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only',
                   '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                   '--user', f'{os.getuid()}:{os.getgid()}',
                   '--tmpfs', '/tmp:rw,exec,mode=1777',
                   '--tmpfs', '/noexec:rw,noexec,mode=1777',
                   '-v', f'{bundle}:/bundle:ro',
                   '-v', f'{harness}:/run-target.sh:ro',
                   '-v', f'{evidence}:/evidence:rw',
                   '-v', f'{config}:/etc/pip.conf:ro',
                   '-v', f'{config}:/etc/xdg/pip/pip.conf:ro',
                   '-e', 'QBOX_E2E_NOEXEC=/noexec',
                   '-e', 'QBOX_E2E_CASES=' + os.environ.get('QBOX_E2E_CASES', ''),
                   image, '/bin/bash', '/run-target.sh', '/bundle', '/evidence/target']
        (evidence / 'invocation.json').write_text(json.dumps({
            'candidate': candidate, 'command': command, 'target_harness_sha256':digest(harness),
            'scope': 'Task10 container shares host kernel; not strict CPU/VM acceptance'}, indent=2))
        with (evidence / 'target.log').open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=7200)
        self.assertEqual(result.returncode, 0, (evidence / 'target.log').read_text()[-12000:])
        report = json.loads((evidence / 'target/results.json').read_text())
        self.assertEqual(report['candidate_release_id'], candidate['release_id'])
        self.assertEqual(report['manifest_sha256'], candidate['manifest_sha256'])
        self.assertEqual(report['failures'], [])
        if not os.environ.get('QBOX_E2E_CASES'):
            self.assertTrue(report['complete_suite'])
            self.assertEqual(report['tests_run'], 12)
        else:
            self.assertGreater(report['tests_run'], 0)
        self.assertEqual((evidence / 'target/forbidden.log').read_bytes(), b'')


if __name__ == '__main__':
    unittest.main()
