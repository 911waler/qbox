#!/bin/sh
# Full same-version scientific source builds; no target-side compilation.
set -eu
export PATH=/build/env/bin:/opt/rh/gcc-toolset-14/root/usr/bin:/usr/local/bin:/usr/bin:/bin
export CC=gcc CXX=g++ FC=gfortran HOME=/build/home PIP_CONFIG_FILE=/dev/null
gcc --version
gfortran --version
ldd --version
rpm -q libgfortran libquadmath libstdc++
/opt/python/cp312-cp312/bin/python -I -B -m venv /build/env
/build/env/bin/python -I -B -m pip --isolated install --no-index --only-binary=:all: --require-hashes --find-links /build/build-wheelhouse -r /build/build-requirements.lock
mkdir -p /build/pkgconfig32 /build/pkgconfig64 /build/raw /build/repaired
for bits in 32 64; do
    cp -a /build/source/OpenBLAS-446c436e10450c348169808f1a6b3fae0925c9f7 /build/openblas-src-$bits
    cd /build/openblas-src-$bits
    if [ "$bits" = 64 ]; then
        interface='INTERFACE64=1 SYMBOLSUFFIX=64_ LIBNAMESUFFIX=64_'
    else
        interface='INTERFACE64=0'
    fi
    # Deliberate full GENERIC kernels: Prescott requires SSE3. No dynamic kernel
    # without a verified v1 fallback is admitted. All four scalar types and full
    # LAPACK remain enabled. Never enable -march=native.
    make -j8 TARGET=GENERIC BINARY=64 DYNAMIC_ARCH=0 USE_OPENMP=0 NUM_THREADS=64 NO_AFFINITY=1 BUILD_LAPACK_DEPRECATED=1 SYMBOLPREFIX=scipy_ LIBNAMEPREFIX=scipy_ FIXED_LIBNAME=1 $interface
    make TARGET=GENERIC BINARY=64 DYNAMIC_ARCH=0 USE_OPENMP=0 NUM_THREADS=64 NO_AFFINITY=1 BUILD_LAPACK_DEPRECATED=1 SYMBOLPREFIX=scipy_ LIBNAMEPREFIX=scipy_ FIXED_LIBNAME=1 $interface PREFIX=/build/blas$bits install
    /build/env/bin/python -I -B /build/pkgconfig.py "$bits"
done
export PKG_CONFIG_PATH=/build/pkgconfig64
cd /build/source/numpy-2.5.3
/build/env/bin/python -I -B -m build --wheel --no-isolation --outdir /build/raw -Cbuild-dir=/build/numpy-build -Csetup-args=-Dcpu-baseline=none -Csetup-args=-Duse-ilp64=true -Csetup-args=-Dblas=scipy-openblas -Csetup-args=-Dlapack=scipy-openblas -Ccompile-args=-j8
/build/env/bin/auditwheel repair --plat manylinux_2_28_x86_64 -w /build/repaired /build/raw/numpy-*.whl
/build/env/bin/python -I -B -m pip --isolated install --no-index --no-deps --force-reinstall /build/repaired/numpy-*.whl
export PKG_CONFIG_PATH=/build/pkgconfig32
cd /build/source/scipy-1.18.1
/build/env/bin/python -I -B -m build --wheel --no-isolation --outdir /build/raw -Cbuild-dir=/build/scipy-build -Csetup-args=-Dblas=scipy-openblas -Csetup-args=-Dlapack=scipy-openblas -Ccompile-args=-j8
/build/env/bin/auditwheel repair --plat manylinux_2_28_x86_64 -w /build/repaired /build/raw/scipy-*.whl
