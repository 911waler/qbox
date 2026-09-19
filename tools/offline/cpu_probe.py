"""Numerical dependency acceptance probe; execute with actual baseline CPU flags.

This is maintainer validation of dependency bytes, not final installer validation.
The caller sets a read-only site path and optional artifact input JSON on sys.path.
"""
import json
import os
from pathlib import Path


def scientific_probe():
    import numpy as np
    print('NUMPY_BASELINE',np._core._multiarray_umath.__cpu_baseline__,flush=True)
    print('NUMPY_FEATURES',np._core._multiarray_umath.__cpu_features__,flush=True)
    assert not set(np._core._multiarray_umath.__cpu_baseline__) - {'SSE','SSE2'}
    print('NUMPY_RANDOM_START',flush=True)
    rng=np.random.default_rng(3817)
    for dtype in (np.float32,np.float64,np.complex64,np.complex128):
        print('NUMPY_LINALG_START',np.dtype(dtype).name,flush=True)
        tolerance=5e-4 if dtype in (np.float32,np.complex64) else 1e-10
        a=rng.standard_normal((96,96)).astype(dtype)
        if np.issubdtype(dtype,np.complexfloating):a+=1j*rng.standard_normal(a.shape)
        a=a.conj().T @ a + np.eye(96,dtype=dtype)*10
        b=np.arange(96,dtype=np.float64).astype(dtype)
        np.testing.assert_allclose(a@np.eye(96,dtype=dtype),a,atol=tolerance,rtol=tolerance)
        np.testing.assert_allclose(a@np.linalg.solve(a,b),b,atol=tolerance,rtol=tolerance)
        u,s,v=np.linalg.svd(a)
        np.testing.assert_allclose((u*s)@v,a,atol=tolerance,rtol=tolerance)
        w,q=np.linalg.eigh(a)
        np.testing.assert_allclose((q*w)@q.conj().T,a,atol=tolerance,rtol=tolerance)
        np.testing.assert_allclose(a@np.linalg.inv(a),np.eye(96),atol=tolerance,rtol=tolerance)
        print('NUMPY_LINALG_OK',np.dtype(dtype).name,flush=True)
    v=np.linspace(-2,2,10001)
    assert np.isfinite(np.sin(v)+np.exp(v)+np.sort(v)).all()
    assert np.allclose(np.fft.ifft(np.fft.fft(v)),v)
    from scipy import linalg,integrate,optimize,special,fft,sparse
    for dtype in (np.float32,np.float64,np.complex64,np.complex128):
        print('SCIPY_LINALG_START',np.dtype(dtype).name,flush=True)
        tol=5e-4 if dtype in (np.float32,np.complex64) else 1e-10
        a=rng.standard_normal((96,96)).astype(dtype)
        if np.issubdtype(dtype,np.complexfloating):a+=1j*rng.standard_normal(a.shape)
        a=a.conj().T@a+np.eye(96,dtype=dtype)*10
        b=np.ones(96,dtype=dtype)
        np.testing.assert_allclose(a@linalg.solve(a,b),b,atol=tol,rtol=tol)
        u,s,vh=linalg.svd(a);np.testing.assert_allclose((u*s)@vh,a,atol=tol,rtol=tol)
        c=linalg.cholesky(a,lower=True);np.testing.assert_allclose(c@c.conj().T,a,atol=tol,rtol=tol)
        gemm=linalg.blas.get_blas_funcs('gemm',(a,));np.testing.assert_allclose(gemm(1,a,a),a@a,atol=tol,rtol=tol)
        print('SCIPY_LINALG_OK',np.dtype(dtype).name,flush=True)
    # Independent children collect all remaining native failures in one VM run.
    import subprocess
    import sys
    sections = {
        'scipy-integrate': "from scipy import integrate; assert abs(integrate.quad(lambda x:x*x,0,1)[0]-1/3)<1e-10",
        'scipy-optimize': "from scipy import optimize; assert abs(optimize.brentq(lambda x:x*x-2,1,2)-2**0.5)<1e-10",
        'scipy-special': "from scipy import special; assert special.gamma(5)==24",
        'scipy-fft': "from scipy import fft; np.testing.assert_allclose(fft.ifft(fft.fft(np.arange(32))),np.arange(32),atol=1e-10)",
        'scipy-sparse': "from scipy import sparse; np.testing.assert_allclose(sparse.linalg.spsolve(sparse.eye(4,format='csc'),np.ones(4)),np.ones(4))",
        'matplotlib': "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; fig,ax=plt.subplots();ax.plot([0,1,2],[0,1,0]);ax.contour(np.arange(16).reshape(4,4));fig.savefig('/tmp/qbox-cpu-probe.png');plt.close(fig); from pathlib import Path; assert Path('/tmp/qbox-cpu-probe.png').stat().st_size>1000",
        'seekpath-spglib': "import seekpath,spglib; cell=(np.eye(3)*3,[[0,0,0]],[14]); assert seekpath.get_path(cell)['path']; assert spglib.get_symmetry_dataset(cell).number==221",
        'ase': "from ase import Atoms; from ase.neighborlist import neighbor_list; atoms=Atoms('Si2',positions=[[0,0,0],[1,0,0]],cell=[3,3,3],pbc=True); assert neighbor_list('d',atoms,1.5).size>0",
        'pymatgen': "from pymatgen.core import Lattice,Structure; from pymatgen.symmetry.analyzer import SpacegroupAnalyzer; structure=Structure(Lattice.cubic(3),['Si'],[[0,0,0]]); assert SpacegroupAnalyzer(structure).get_space_group_number()==221",
        'orjson': "import orjson; assert orjson.loads(orjson.dumps({'v':np.arange(4)},option=orjson.OPT_SERIALIZE_NUMPY))=={'v':[0,1,2,3]}",
        'pandas': "import pandas; assert pandas.DataFrame({'a':[1,2,3]}).a.sum()==6",
        'lxml': """from lxml import etree,objectify
root=etree.XML(b'<a><b>2</b></a>')
assert root.xpath('string(b)')=='2'
assert objectify.fromstring(b'<a><b>2</b></a>').b.pyval==2
style=etree.XML(b'<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"><xsl:template match="/"><out><xsl:value-of select="a/b"/></out></xsl:template></xsl:stylesheet>')
assert str(etree.XSLT(style)(root)).find('<out>2</out>')>=0
schema=etree.XML(b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:element name="a" type="xs:string"/></xs:schema>')
assert etree.XMLSchema(schema).validate(etree.XML(b'<a>ok</a>'))
assert etree.fromstring(b'<?xml version="1.0" encoding="ISO-8859-1"?><a>caf\\xe9</a>').text=='caf\u00e9'
assert etree.LIBXML_COMPILED_VERSION==(2,14,6)
assert etree.LIBXSLT_COMPILED_VERSION==(1,1,43)
print('LXML_NATIVE_VERSIONS',etree.LIBXML_COMPILED_VERSION,etree.LIBXSLT_COMPILED_VERSION,flush=True)
""",
        'pillow': "from PIL import Image; import io; image=Image.new('RGB',(10,10)); data=io.BytesIO();image.save(data,format='PNG');data.seek(0);assert Image.open(data).size==(10,10)",
    }
    failures = []
    for name, code in sections.items():
        print('NATIVE_SECTION_START', name, flush=True)
        preamble = 'import sys,faulthandler,resource;resource.setrlimit(resource.RLIMIT_CORE,(0,0));faulthandler.enable();sys.path.insert(0,sys.argv[1]);import numpy as np;'
        result = subprocess.run([sys.executable, '-I', '-B', '-c', preamble+code, sys.path[0]])
        print('NATIVE_SECTION_EXIT', name, result.returncode, flush=True)
        if result.returncode: failures.append((name,result.returncode))
    assert not failures, failures
    print('QBOX_SCIENTIFIC_CPU_PASS',flush=True)


def verify_baseline_environment():
    import resource
    import signal
    import subprocess
    import sys
    assert os.getuid() != 0, 'baseline probe must run as non-root'
    flags = next(line.split(':',1)[1].split() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('flags'))
    forbidden = {'pni','ssse3','sse4_1','sse4_2','popcnt','cx16','lahf_lm','avx','avx2','fma','f16c','xsave','3dnowprefetch','svm'}
    assert {'sse','sse2'} <= set(flags) and not forbidden.intersection(flags), flags
    print('CPU_FLAGS',json.dumps(flags),flush=True)
    # HADDPS is SSE3. This child must receive SIGILL, proving the emulator rejects
    # the removed instruction as well as hiding its CPUID bit.
    code = "import mmap,ctypes,resource;resource.setrlimit(resource.RLIMIT_CORE,(0,0));m=mmap.mmap(-1,4096,prot=7);m.write(bytes.fromhex('f20f7cc0c3'));ctypes.CFUNCTYPE(None)(ctypes.addressof(ctypes.c_char.from_buffer(m)))()"
    result = subprocess.run([sys.executable,'-I','-B','-c',code])
    print('SSE3_NEGATIVE_CONTROL',result.returncode,flush=True)
    assert result.returncode == -signal.SIGILL, 'emulator did not reject SSE3'


def verify_artifacts(directory):
    import hashlib
    directory=Path(directory)
    inputs=json.loads((directory/'inputs.json').read_text())
    for item in inputs:
        path=directory/item['filename']
        with path.open('rb') as stream:
            actual=hashlib.file_digest(stream,'sha256').hexdigest()
        assert actual==item['sha256'], item['filename']
        print('ARTIFACT_SHA256',item['filename'],actual,flush=True)


if __name__=='__main__':
    import argparse
    import sys
    parser=argparse.ArgumentParser()
    parser.add_argument('site')
    parser.add_argument('--baseline',action='store_true')
    parser.add_argument('--artifacts')
    args=parser.parse_args()
    sys.path.insert(0,args.site)
    import faulthandler
    faulthandler.enable()
    print('UID',os.getuid(),flush=True)
    if args.baseline:verify_baseline_environment()
    if args.artifacts:verify_artifacts(args.artifacts)
    scientific_probe()
