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
    rng=np.random.default_rng(3817)
    for dtype in (np.float32,np.float64,np.complex64,np.complex128):
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
    assert abs(integrate.quad(lambda x:x*x,0,1)[0]-1/3)<1e-10
    assert abs(optimize.brentq(lambda x:x*x-2,1,2)-2**0.5)<1e-10
    assert special.gamma(5)==24
    np.testing.assert_allclose(fft.ifft(fft.fft(np.arange(32))),np.arange(32),atol=1e-10)
    np.testing.assert_allclose(sparse.linalg.spsolve(sparse.eye(4,format='csc'),np.ones(4)),np.ones(4))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots();ax.plot([0,1,2],[0,1,0]);ax.contour(np.arange(16).reshape(4,4));fig.savefig('/tmp/qbox-cpu-probe.png');plt.close(fig)
    assert Path('/tmp/qbox-cpu-probe.png').stat().st_size>1000
    import seekpath,spglib
    cell=(np.eye(3)*3,[[0,0,0]],[14])
    assert seekpath.get_path(cell)['path']
    assert spglib.get_symmetry_dataset(cell).number==221
    from ase import Atoms
    from ase.neighborlist import neighbor_list
    atoms=Atoms('Si2',positions=[[0,0,0],[1,0,0]],cell=[3,3,3],pbc=True)
    assert neighbor_list('d',atoms,1.5).size>0
    from pymatgen.core import Lattice,Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    structure=Structure(Lattice.cubic(3),['Si'],[[0,0,0]])
    assert SpacegroupAnalyzer(structure).get_space_group_number()==221
    import orjson,pandas,lxml.etree
    assert orjson.loads(orjson.dumps({'v':np.arange(4)},option=orjson.OPT_SERIALIZE_NUMPY))=={'v':[0,1,2,3]}
    assert pandas.DataFrame({'a':[1,2,3]}).a.sum()==6
    assert lxml.etree.fromstring(b'<a>ok</a>').text=='ok'
    from PIL import Image
    assert Image.open('/tmp/qbox-cpu-probe.png').size[0]>1
    print('QBOX_SCIENTIFIC_CPU_PASS',flush=True)


if __name__=='__main__':
    import sys
    if len(sys.argv)>1:sys.path.insert(0,sys.argv[1])
    print('UID',os.getuid(),flush=True)
    scientific_probe()
