"""Exercise the real installer transaction; expensive payload work is replaced in Bash."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

from test_bootstrap import INSTALL, ENV, make_bundle, hash_bundle

PYTHON = '/opt/nwu911/envs/qetoolkit-python/current/bin/python'
RID = '0.1.0-' + 'a'*64


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='qbox transaction ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root/'bundle'
        make_bundle(self.bundle)
        shutil.copyfile(INSTALL, self.bundle/'install.sh')
        (self.bundle/'manifest.json').write_text(json.dumps({'release_id':RID}))
        (self.bundle/'checks/qbox-launcher.sh').write_text('#!/bin/bash\nexit 0\n')
        hash_bundle(self.bundle)
        self.prefix = self.root/'prefix'
        self.bindir = self.root/'bin'
        self.log = self.root/'events'
        self.sentinel = self.root/'user-file'
        self.sentinel.write_bytes(b'never alter user data')
        self.sentinel_sha = hashlib.sha256(self.sentinel.read_bytes()).hexdigest()

    def old_release(self):
        self.prefix.mkdir()
        (self.prefix/'.qbox-root').write_text(f'schema_version=1\nuid={os.geteuid()}\nprefix={self.prefix}\n')
        release = self.prefix/'releases/old'
        (release/'bin').mkdir(parents=True)
        (release/'bin/qbox').write_text('old entry\n')
        (release/'metadata').mkdir()
        (release/'metadata/installed.json').write_text(json.dumps({'state':'verified'}))
        (release/'payload').write_text('old payload')
        (self.prefix/'current').symlink_to('releases/old')
        self.bindir.mkdir()
        (self.bindir/'qbox').symlink_to(self.prefix/'current/bin/qbox')
        return release

    def script(self, fail='', extra=''):
        return r'''
source "$1/install.sh" || exit
log=$4
fail=$5
read_bundle_identity() { release_id=''' + RID + r'''; manifest_sha256=$(sha256sum < "$bundle/manifest.json"); manifest_sha256=${manifest_sha256%% *}; }
extract_runtime() {
    mkdir -p "$2/python/bin" || return
    printf '#!/bin/bash\nexec %s "$@"\n' ''' + PYTHON + r''' > "$2/python/bin/python3" || return
    chmod +x "$2/python/bin/python3"
}
install_wheels() {
    printf 'pip\n' >> "$log"
    [[ "$fail" != pip ]] || return 73
    mkdir -p "$stage/python/lib/python3.12/site-packages/qbox-0.1.0.dist-info" "$stage/python/lib/python3.12/site-packages/qbox"
    printf 'Name: qbox\nVersion: 0.1.0\n' > "$stage/python/lib/python3.12/site-packages/qbox-0.1.0.dist-info/METADATA"
    printf '../../../bin/qbox,,\nqbox/helper.py,,\nqbox-0.1.0.dist-info/RECORD,,\n' > "$stage/python/lib/python3.12/site-packages/qbox-0.1.0.dist-info/RECORD"
    printf 'generated console' > "$stage/python/bin/qbox"
    printf 'helper' > "$stage/python/lib/python3.12/site-packages/qbox/helper.py"
    chmod +x "$stage/python/lib/python3.12/site-packages/qbox/helper.py"
}
verify_release() {
    printf '%s:%s\n' "$2" "${1##*/}" >> "$log"
    [[ "$fail" != "$2-check" ]] || return 73
    [[ ! -e "$1/corrupt" ]] || return 74
    if [[ "$2" == prepared ]]; then
        printf '{}\n' > "$1/metadata/installed-files.json" || return
    elif [[ "$2" == reuse ]]; then
        grep -q '"state": *"verified"' "$1/metadata/installed.json" || return 75
    fi
}
''' + extra + r'''
main --prefix "$2" --bin-dir "$3"
'''

    def run_transaction(self, fail='', extra='', prefix=None, bindir=None):
        return subprocess.run(['/bin/bash','--noprofile','--norc','-c',self.script(fail, extra),'test',str(self.bundle),str(prefix or self.prefix),str(bindir or self.bindir),str(self.log),fail],env=ENV,text=True,capture_output=True)

    def assert_preserved(self, old='releases/old'):
        self.assertEqual(os.readlink(self.prefix/'current'),old)
        self.assertEqual(hashlib.sha256(self.sentinel.read_bytes()).hexdigest(),self.sentinel_sha)
        self.assertEqual(list(self.prefix.glob('.stage.*')),[])
        self.assertFalse((self.prefix/'.install-lock').exists())

    def test_success_order_and_stable_entry(self):
        old = self.old_release()
        result = self.run_transaction()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('PATH', result.stdout)
        self.assertIn('export PATH=', result.stdout)
        self.assertEqual(os.readlink(self.prefix/'current'),'releases/'+RID)
        self.assertEqual(os.readlink(self.bindir/'qbox'),str(self.prefix/'current/bin/qbox'))
        self.assertEqual((old/'payload').read_text(),'old payload')
        events = self.log.read_text().splitlines()
        self.assertEqual([line.split(':')[0] for line in events],['reuse','pip','prepared','final'])
        final = self.prefix/'releases'/RID
        self.assertFalse((final/'python/bin/qbox').exists())
        self.assertNotIn('../../../bin/qbox',(final/'python/lib/python3.12/site-packages/qbox-0.1.0.dist-info/RECORD').read_text())
        self.assertFalse((final/'python/lib/python3.12/site-packages/qbox/helper.py').stat().st_mode & 0o111)
        self.assertEqual(json.loads((final/'metadata/installed.json').read_text())['state'],'verified')
        self.assertFalse((final/'.qbox-transaction').exists())

    def test_failures_preserve_old_current_and_user_bytes(self):
        self.old_release()
        overrides = {
            'preflight':'preflight_platform() { return 73; }',
            'final-move':'move_release() { return 73; }',
            'bin-link':'prepare_bin_link() { return 73; }',
            'current-switch':'mv() { if [[ "$*" == *"/current" ]]; then return 73; fi; command mv "$@"; }',
        }
        for fail in ['preflight','pip','prepared-check','final-move','final-check','bin-link','current-switch']:
            with self.subTest(phase=fail):
                result = self.run_transaction(fail,overrides.get(fail,''))
                self.assertNotEqual(result.returncode,0,result.stderr)
                if fail in ['prepared-check','final-move','final-check','bin-link','current-switch']:
                    self.assertIn('prepared:',self.log.read_text())
                if fail in ['final-check','bin-link','current-switch']:
                    self.assertIn('final:',self.log.read_text())
                self.assert_preserved()
                self.assertFalse((self.prefix/'releases'/RID).exists())
                self.log.write_text('')

    def test_first_install_current_failure_removes_only_owned_objects(self):
        result = self.run_transaction(extra='publish_release() { return 73; }')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.bindir/'qbox').is_symlink())
        self.assertFalse(self.prefix.exists())
        self.assertFalse(self.bindir.exists())

    def test_same_payload_reuses_verified_release_without_pip(self):
        self.assertEqual(self.run_transaction().returncode,0)
        final = self.prefix/'releases'/RID
        before = (final/'python/lib/python3.12/site-packages/qbox/helper.py').stat()
        self.log.write_text('')
        result = self.run_transaction()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('pip',self.log.read_text())
        self.assertEqual(before.st_ino,(final/'python/lib/python3.12/site-packages/qbox/helper.py').stat().st_ino)

    def test_corrupt_old_release_and_existing_final_are_not_repaired(self):
        old = self.old_release()
        (old/'corrupt').write_text('bad')
        result = self.run_transaction()
        self.assertNotEqual(result.returncode,0)
        self.assert_preserved()
        (old/'corrupt').unlink()
        final = self.prefix/'releases'/RID
        final.mkdir()
        (final/'foreign').write_text('keep')
        result = self.run_transaction()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((final/'foreign').read_text(),'keep')
        self.assert_preserved()

    def test_command_conflicts_are_untouched(self):
        self.old_release()
        command = self.bindir/'qbox'
        command.unlink()
        for target in [None,'missing',str(self.sentinel)]:
            with self.subTest(target=target):
                if target is None: command.write_text('user command')
                else: command.symlink_to(target)
                before = os.readlink(command) if command.is_symlink() else command.read_text()
                result = self.run_transaction()
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(os.readlink(command) if command.is_symlink() else command.read_text(),before)
                self.assert_preserved()
                command.unlink()

    def test_lock_loser_never_removes_winner_lock(self):
        self.old_release()
        lock = self.prefix/'.install-lock'
        lock.mkdir(); (lock/'owner').write_text('winner')
        result = self.run_transaction()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('安装进行中或遗留锁',result.stderr)
        self.assertEqual((lock/'owner').read_text(),'winner')

    def test_term_before_commit_cleans_new_release_keeps_old(self):
        self.old_release()
        result = self.run_transaction(extra='move_release() { command mv -T -- "$stage" "$final" || return; kill -TERM "$BASHPID"; }')
        self.assertEqual(result.returncode,143,result.stderr)
        self.assert_preserved()

    def test_cleanup_preserves_newly_added_user_file(self):
        result = self.run_transaction(extra='install_wheels() { printf keep > "$prefix/user-added"; return 73; }')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.prefix/'user-added').read_text(),'keep')

    def test_signal_immediately_after_current_rename_keeps_live_entry(self):
        result = self.run_transaction(extra=r'''mv() {
            command mv "$@" || return
            if [[ "$*" == *"/current" ]]; then kill -TERM "$BASHPID"; fi
        }''')
        self.assertEqual(result.returncode,143,result.stderr)
        self.assertEqual(os.readlink(self.prefix/'current'),'releases/'+RID)
        self.assertTrue((self.bindir/'qbox').exists())
        self.assertTrue((self.prefix/'releases'/RID).is_dir())

    def test_int_and_partial_extraction_preserve_old_release(self):
        self.old_release()
        for override, expected in [
            ('install_wheels() { kill -INT "$BASHPID"; }',130),
            ('extract_runtime() { mkdir "$2/partial"; return 73; }',1),
        ]:
            result = self.run_transaction(extra=override)
            self.assertEqual(result.returncode,expected,result.stderr)
            self.assert_preserved()

    def test_cleanup_never_follows_replaced_stage_symlink(self):
        self.old_release()
        outside=self.root/'outside'; outside.mkdir(); (outside/'keep').write_text('keep')
        result=self.run_transaction(extra=r'''install_wheels() {
            command mv "$stage" "$stage.saved" || return
            ln -s "$prefix/../outside" "$stage" || return
            return 73
        }''')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((outside/'keep').read_text(),'keep')
        self.assertEqual(len(list(self.prefix.glob('.stage.*.saved'))),1)
        self.assertEqual(os.readlink(self.prefix/'current'),'releases/old')

    def test_concurrently_created_final_is_never_overwritten_or_removed(self):
        self.old_release()
        result=self.run_transaction(extra=r'''mv() {
            if [[ "$1" == -Tn ]]; then mkdir "$final"; printf keep > "$final/foreign"; fi
            command mv "$@"
        }''')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.prefix/'releases'/RID/'foreign').read_text(),'keep')
        self.assert_preserved()

    def test_real_lock_contention(self):
        self.old_release()
        override=r'''eval "$(declare -f install_wheels | sed '1s/install_wheels/real_install_wheels/')"
install_wheels() {
    printf ready > "$prefix/../ready"
    while [[ ! -e "$prefix/../proceed" ]]; do sleep .02; done
    real_install_wheels
}'''
        args=['/bin/bash','--noprofile','--norc','-c',self.script(extra=override),'test',str(self.bundle),str(self.prefix),str(self.bindir),str(self.log),'']
        winner=subprocess.Popen(args,env=ENV,text=True,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+10
            while not (self.root/'ready').exists() and time.monotonic()<deadline: time.sleep(.02)
            self.assertTrue((self.root/'ready').exists())
            owner=(self.prefix/'.install-lock/owner').read_text()
            loser=self.run_transaction()
            self.assertNotEqual(loser.returncode,0)
            self.assertEqual((self.prefix/'.install-lock/owner').read_text(),owner)
            (self.root/'proceed').touch()
            stdout,stderr=winner.communicate(timeout=20)
            self.assertEqual(winner.returncode,0,stderr)
        finally:
            if winner.poll() is None: os.killpg(winner.pid,signal.SIGKILL); winner.communicate()
        self.assertEqual(os.readlink(self.prefix/'current'),'releases/'+RID)
        self.assertFalse((self.prefix/'.install-lock').exists())

    def test_two_prefixes_race_for_same_command_without_overwrite(self):
        override=r'''ln() {
    if [[ "${@: -1}" == "$bin_dir/qbox" ]]; then
        printf ready > "$prefix/../${prefix##*/}.ready"
        while [[ ! -e "$prefix/../one.ready" || ! -e "$prefix/../two.ready" ]]; do sleep .02; done
    fi
    command ln "$@"
}'''
        processes=[]
        for name in ['one','two']:
            prefix=self.root/name
            args=['/bin/bash','--noprofile','--norc','-c',self.script(extra=override),'test',str(self.bundle),str(prefix),str(self.bindir),str(self.root/(name+'.log')),'']
            processes.append(subprocess.Popen(args,env=ENV,text=True,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE))
        try:
            outputs=[p.communicate(timeout=20) for p in processes]
            statuses=[p.returncode for p in processes]
            self.assertEqual(sorted(statuses),[0,1],outputs)
            winner='one' if statuses[0]==0 else 'two'
            loser='two' if winner=='one' else 'one'
            self.assertEqual(os.readlink(self.bindir/'qbox'),str(self.root/winner/'current/bin/qbox'))
            self.assertTrue((self.bindir/'qbox').exists())
            self.assertFalse((self.root/loser).exists())
        finally:
            for process in processes:
                if process.poll() is None: os.killpg(process.pid,signal.SIGKILL); process.communicate()

    def test_partial_first_install_lock_has_actionable_diagnostic(self):
        self.prefix.mkdir()
        lock=self.prefix/'.install-lock';lock.mkdir();(lock/'owner').write_text('other transaction')
        result=self.run_transaction()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('安装进行中或遗留锁',result.stderr)
        self.assertEqual((lock/'owner').read_text(),'other transaction')

    def test_same_version_different_payload_keeps_both_releases(self):
        self.assertEqual(self.run_transaction().returncode,0)
        other='0.1.0-'+'b'*64
        (self.bundle/'manifest.json').write_text(json.dumps({'release_id':other}))
        hash_bundle(self.bundle)
        override='read_bundle_identity() { release_id='+other+'; manifest_sha256=$(sha256sum < "$bundle/manifest.json"); manifest_sha256=${manifest_sha256%% *}; }'
        result=self.run_transaction(extra=override)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(os.readlink(self.prefix/'current'),'releases/'+other)
        self.assertTrue((self.prefix/'releases'/RID).is_dir())
        self.assertTrue((self.prefix/'releases'/other).is_dir())

    def test_prepared_existing_release_is_not_reused_or_repaired(self):
        self.assertEqual(self.run_transaction().returncode,0)
        marker=self.prefix/'releases'/RID/'metadata/installed.json'
        content=json.loads(marker.read_text());content['state']='prepared';marker.write_text(json.dumps(content))
        before=marker.read_bytes()
        result=self.run_transaction()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(marker.read_bytes(),before)
        self.assertEqual(os.readlink(self.prefix/'current'),'releases/'+RID)

    def test_pip_flags_and_environment_are_scoped(self):
        stage=self.root/'fake';(stage/'python/bin').mkdir(parents=True)
        executable=stage/'python/bin/python3'
        executable.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$TRACE/argv"\nenv > "$TRACE/env"\n')
        executable.chmod(0o755)
        environment=dict(ENV,TRACE=str(self.root),PIP_INDEX_URL='https://invalid.example',PIP_TARGET='/never',PIP_CONFIG_FILE='/hostile',PIP_REQUIRE_VIRTUALENV='1')
        result=subprocess.run(['/bin/bash','-c',r'''source "$1"; stage=$2; bundle=$3; install_wheels || exit; printf '%s' "$PIP_TARGET"''','test',str(INSTALL),str(stage),str(self.bundle)],env=environment,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'/never')
        args=(self.root/'argv').read_text().splitlines()
        self.assertEqual(args[:6],['-I','-B','-m','pip','--isolated','--disable-pip-version-check'])
        for flag in ['--no-index','--only-binary=:all:','--require-hashes','--no-cache-dir','--no-compile','--ignore-installed']: self.assertIn(flag,args)
        variables=[line for line in (self.root/'env').read_text().splitlines() if line.startswith('PIP_')]
        self.assertEqual(variables,['PIP_CONFIG_FILE=/dev/null'])

    def test_current_conflicts_are_never_replaced(self):
        old=self.old_release();current=self.prefix/'current';current.unlink()
        for target in [None,str(old),'../outside','releases/missing']:
            with self.subTest(target=target):
                if target is None: current.write_text('user current file')
                else: current.symlink_to(target)
                result=self.run_transaction()
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(os.readlink(current) if current.is_symlink() else current.read_text(),target or 'user current file')
                self.assertEqual((old/'payload').read_text(),'old payload')
                self.assertFalse((self.prefix/'.install-lock').exists())
                current.unlink()

    def test_changed_lock_token_prevents_cleanup_of_claimed_objects(self):
        self.old_release()
        result=self.run_transaction(extra=r'''install_wheels() {
            printf 'another owner' > "$lock/owner"
            return 73
        }''')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.prefix/'.install-lock/owner').read_text(),'another owner')
        self.assertEqual(len(list(self.prefix.glob('.stage.*'))),1)
        self.assertEqual(os.readlink(self.prefix/'current'),'releases/old')

    def test_referenced_final_survives_failed_transaction(self):
        self.old_release()
        result=self.run_transaction(extra=r'''eval "$(declare -f verify_release | sed '1s/verify_release/real_verify_release/')"
verify_release() {
    if [[ "$2" == final ]]; then
        ln -sfn "releases/$release_id" "$prefix/current" || return
        return 73
    fi
    real_verify_release "$@"
}''')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(os.readlink(self.prefix/'current'),'releases/'+RID)
        self.assertTrue((self.prefix/'releases'/RID).is_dir())
        self.assertTrue((self.bindir/'qbox').exists())

    def test_unresolvable_current_during_cleanup_preserves_final(self):
        self.old_release()
        result=self.run_transaction(extra=r'''eval "$(declare -f verify_release | sed '1s/verify_release/real_verify_release/')"
verify_release() {
    if [[ "$2" == final ]]; then
        readlink() { if [[ "$*" == "-m -- $prefix/current" ]]; then return 73; fi; command readlink "$@"; }
        return 73
    fi
    real_verify_release "$@"
}''')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((self.prefix/'releases'/RID).is_dir())
        self.assertEqual(os.readlink(self.prefix/'current'),'releases/old')

    def test_concurrent_command_directory_never_receives_nested_link(self):
        for as_symlink in [False, True]:
            with self.subTest(symlink=as_symlink):
                if self.bindir.exists(): shutil.rmtree(self.bindir)
                outside=self.root/('foreign-link-target' if as_symlink else 'unused')
                if as_symlink:
                    outside.mkdir(); (outside/'sentinel').write_text('foreign bytes')
                override=r'''ln() {
                    if [[ "${@: -1}" == "$bin_dir/qbox" ]]; then
                        ''' + ('command ln -s -- "$prefix/../foreign-link-target" "$bin_dir/qbox"' if as_symlink else 'mkdir -- "$bin_dir/qbox"; printf "foreign bytes" > "$bin_dir/qbox/sentinel"') + r'''
                    fi
                    command ln "$@"
                }'''
                result=self.run_transaction(extra=override)
                self.assertNotEqual(result.returncode,0)
                foreign=outside if as_symlink else self.bindir/'qbox'
                self.assertEqual((foreign/'sentinel').read_text(),'foreign bytes')
                self.assertEqual(sorted(p.name for p in foreign.iterdir()),['sentinel'])
                self.assertFalse(self.prefix.exists())
                self.assertEqual(hashlib.sha256(self.sentinel.read_bytes()).hexdigest(),self.sentinel_sha)

    def test_signal_immediately_after_command_link_creation_allows_retry(self):
        for signal_name,status in [('INT',130),('TERM',143)]:
            with self.subTest(signal=signal_name):
                if self.prefix.exists(): shutil.rmtree(self.prefix)
                if self.bindir.exists(): shutil.rmtree(self.bindir)
                override=r'''ln() {
                    command ln "$@" || return
                    if [[ "${@: -1}" == "$bin_dir/qbox" ]]; then
                        kill -''' + signal_name + r''' "$transaction_pid"
                    fi
                }'''
                result=self.run_transaction(extra=override)
                self.assertEqual(result.returncode,status,result.stderr)
                self.assertFalse((self.bindir/'qbox').is_symlink())
                self.assertFalse(self.prefix.exists())
                retry=self.run_transaction()
                self.assertEqual(retry.returncode,0,retry.stderr)
                shutil.rmtree(self.prefix);shutil.rmtree(self.bindir)

    def test_signal_during_command_identity_recording_allows_retry(self):
        for signal_name,status in [('INT',130),('TERM',143)]:
            with self.subTest(signal=signal_name):
                if self.prefix.exists(): shutil.rmtree(self.prefix)
                if self.bindir.exists(): shutil.rmtree(self.bindir)
                override=r'''stat() {
                    command stat "$@" || return
                    if [[ "${@: -1}" == "$bin_dir/qbox" && -L "$bin_dir/qbox" && -z "$bin_identity" ]]; then
                        kill -''' + signal_name + r''' "$transaction_pid"
                    fi
                }'''
                result=self.run_transaction(extra=override)
                self.assertEqual(result.returncode,status,result.stderr)
                self.assertFalse((self.bindir/'qbox').is_symlink())
                self.assertFalse(self.prefix.exists())
                retry=self.run_transaction()
                self.assertEqual(retry.returncode,0,retry.stderr)
                shutil.rmtree(self.prefix);shutil.rmtree(self.bindir)

    def test_signal_after_command_ownership_recording_allows_retry(self):
        for signal_name,status in [('INT',130),('TERM',143)]:
            with self.subTest(signal=signal_name):
                if self.prefix.exists(): shutil.rmtree(self.prefix)
                if self.bindir.exists(): shutil.rmtree(self.bindir)
                override=r'''eval "$(declare -f prepare_bin_link | sed '1s/prepare_bin_link/real_prepare_bin_link/')"
prepare_bin_link() {
    real_prepare_bin_link || return
    kill -''' + signal_name + r''' "$transaction_pid"
}'''
                result=self.run_transaction(extra=override)
                self.assertEqual(result.returncode,status,result.stderr)
                self.assertFalse((self.bindir/'qbox').is_symlink())
                self.assertFalse(self.prefix.exists())
                retry=self.run_transaction()
                self.assertEqual(retry.returncode,0,retry.stderr)
                shutil.rmtree(self.prefix);shutil.rmtree(self.bindir)


    def test_process_group_signal_during_command_link_creation_allows_retry(self):
        for signal_name,status in [('INT',130),('TERM',143)]:
            with self.subTest(signal=signal_name):
                if self.prefix.exists(): shutil.rmtree(self.prefix)
                if self.bindir.exists(): shutil.rmtree(self.bindir)
                # The outer harness stays alive to report main's conventional
                # status; main and ln still receive the actual group signal.
                override=r'''trap ':' INT TERM
ln() {
    command ln "$@" || return
    if [[ "${@: -1}" == "$bin_dir/qbox" ]]; then
        kill -''' + signal_name + r''' -- "-$$"
    fi
}'''
                args=['/bin/bash','--noprofile','--norc','-c',self.script(extra=override),'test',str(self.bundle),str(self.prefix),str(self.bindir),str(self.log),'']
                result=subprocess.run(args,env=ENV,text=True,capture_output=True,start_new_session=True,timeout=20)
                self.assertEqual(result.returncode,status,result.stderr)
                self.assertFalse((self.bindir/'qbox').is_symlink())
                self.assertFalse(self.prefix.exists())
                retry=self.run_transaction()
                self.assertEqual(retry.returncode,0,retry.stderr)
                shutil.rmtree(self.prefix);shutil.rmtree(self.bindir)

    def test_stat_child_startup_boundary_cannot_leave_unowned_command(self):
        for signal_name,status in [('INT',130),('TERM',143)]:
            with self.subTest(signal=signal_name):
                if self.prefix.exists(): shutil.rmtree(self.prefix)
                if self.bindir.exists(): shutil.rmtree(self.bindir)
                fired=self.root/'stat-startup-signal'
                fired.unlink(missing_ok=True)
                # Exact reviewed boundary: a fresh stat child starts after ln,
                # before its first ignore installation. Fixed code has no such
                # child; then the same signal is delivered during protected stat.
                override=r'''builtin trap ':' INT TERM
trap() {
    if [[ "$#" == 3 && -z "$1" && "$2" == INT && "$3" == TERM && "${bin_created:-0}" == 1 && -z "${bin_identity:-}" && "$BASHPID" != "$transaction_pid" ]]; then
        printf 'unprotected-startup' > "$prefix/../stat-startup-signal"
        kill -''' + signal_name + r''' -- "-$$"
    fi
    builtin trap "$@"
}
ln() {
    command ln "$@" || return
    if [[ "${@: -1}" == "$bin_dir/qbox" ]]; then
        printf '%s' "$BASHPID" > "$prefix/../command-link-child"
    fi
}
stat() {
    if [[ "${@: -1}" == "$bin_dir/qbox" && -z "$bin_identity" && ! -e "$prefix/../stat-startup-signal" ]]; then
        [[ "$BASHPID" == "$(cat "$prefix/../command-link-child")" ]] || return 78
        printf 'protected-stat' > "$prefix/../stat-startup-signal"
        kill -''' + signal_name + r''' -- "-$$"
    fi
    command stat "$@"
}'''
                args=['/bin/bash','--noprofile','--norc','-c',self.script(extra=override),'test',str(self.bundle),str(self.prefix),str(self.bindir),str(self.log),'']
                result=subprocess.run(args,env=ENV,text=True,capture_output=True,start_new_session=True,timeout=20)
                self.assertEqual(result.returncode,status,result.stderr)
                self.assertFalse((self.bindir/'qbox').is_symlink())
                self.assertFalse(self.prefix.exists())
                self.assertEqual(fired.read_text(),'protected-stat')
                retry=self.run_transaction()
                self.assertEqual(retry.returncode,0,retry.stderr)
                shutil.rmtree(self.prefix);shutil.rmtree(self.bindir)

    def test_initial_link_child_startup_signal_creates_no_command(self):
        for signal_name,status in [('INT',130),('TERM',143)]:
            with self.subTest(signal=signal_name):
                if self.prefix.exists(): shutil.rmtree(self.prefix)
                if self.bindir.exists(): shutil.rmtree(self.bindir)
                fired=self.root/'initial-child-signal'
                fired.unlink(missing_ok=True)
                override=r'''builtin trap ':' INT TERM
trap() {
    if [[ "$#" == 3 && -z "$1" && "$2" == INT && "$3" == TERM && "$BASHPID" != "$transaction_pid" && ! -L "$bin_dir/qbox" ]]; then
        printf 'initial-startup' > "$prefix/../initial-child-signal"
        kill -''' + signal_name + r''' -- "-$$"
    fi
    builtin trap "$@"
}'''
                args=['/bin/bash','--noprofile','--norc','-c',self.script(extra=override),'test',str(self.bundle),str(self.prefix),str(self.bindir),str(self.log),'']
                result=subprocess.run(args,env=ENV,text=True,capture_output=True,start_new_session=True,timeout=20)
                self.assertEqual(result.returncode,status,result.stderr)
                self.assertEqual(fired.read_text(),'initial-startup')
                self.assertFalse((self.bindir/'qbox').is_symlink())
                self.assertFalse(self.prefix.exists())
                retry=self.run_transaction()
                self.assertEqual(retry.returncode,0,retry.stderr)
                shutil.rmtree(self.prefix);shutil.rmtree(self.bindir)



if __name__ == '__main__': unittest.main()
