"""pkg-config for the explicitly rebuilt, prefixed OpenBLAS ABI."""
import ctypes
from pathlib import Path
import sys
bits = sys.argv[1]
root = Path('/build/blas'+bits)
library = root/'lib'/('libscipy_openblas64_.so' if bits=='64' else 'libscipy_openblas.so')
lib = ctypes.CDLL(str(library))
function = getattr(lib,'scipy_openblas_get_config64_' if bits=='64' else 'scipy_openblas_get_config')
function.restype = ctypes.c_char_p
config = function().decode()
assert 'DYNAMIC_ARCH' not in config and 'generic' in config.lower(), config
flags = '-DBLAS_SYMBOL_PREFIX=scipy_'
if bits=='64':
    flags += ' -DBLAS_SYMBOL_SUFFIX=64_ -DHAVE_BLAS_ILP64 -DOPENBLAS_ILP64_NAMING_SCHEME'
text=f'''libdir={root}/lib
includedir={root}/include
openblas_config={config}
Name: scipy-openblas
Description: qbox baseline GENERIC OpenBLAS
Version: {config.split()[1]}
Libs: {library} -Wl,-rpath,{root}/lib
Cflags: -I{root}/include {flags}
'''
Path('/build/pkgconfig'+bits+'/scipy-openblas.pc').write_text(text)
print(text,flush=True)
