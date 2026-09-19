"""Exercise the real patched upstream loader, including fail-closed error paths."""
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile

spec = importlib.util.spec_from_file_location('offline_lxml', Path.cwd()/'buildlibxml.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def no_network(*args, **kwargs):
    raise AssertionError('offline source loader attempted network')

module.read_url = module.urlopen = module.urlretrieve = no_network
assert os.environ['QBOX_OFFLINE_BUILD'] == '1'
with tempfile.TemporaryDirectory() as temporary:
    target = Path(temporary)
    for name, version, extension in [('libxml2','2.14.6','xz'),('libxslt','1.1.43','xz'),
                                      ('libiconv','1.18','gz'),('zlib','1.3.2','gz')]:
        filename = f'{name}-{version}.tar.{extension}'
        archive = target/filename
        shutil.copyfile(Path('libs')/filename, archive)
        loader = getattr(module, 'download_'+name)
        assert Path(loader(str(target), version)) == archive
        archive.write_bytes(b'wrong source hash')
        for exists in (True, False):
            if not exists:
                archive.unlink()
            try:
                loader(str(target), version)
            except ValueError as error:
                assert 'Missing or mismatched offline source' in str(error)
            else:
                raise AssertionError('offline loader accepted missing/corrupt archive')
        print(name, 'offline loader: valid bytes accepted, missing/corrupt bytes rejected')
