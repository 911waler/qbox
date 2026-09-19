#!/bin/sh
# Executed only in the digest-pinned private builder, with networking disabled.
set -eu
export PATH=/build/env/bin:/opt/rh/gcc-toolset-14/root/usr/bin:/usr/local/bin:/usr/bin:/bin
export CC=gcc CXX=g++ FC=gfortran
gcc --version
gfortran --version
ldd --version
export HOME=/build/home PIP_CONFIG_FILE=/dev/null
/opt/python/cp312-cp312/bin/python -I -B -m venv /build/env
/build/env/bin/python -I -B -m pip --isolated install --no-index --only-binary=:all: --require-hashes --find-links /build/build-wheelhouse -r /build/build-requirements.lock
mkdir -p /build/pkgconfig /build/raw /build/repaired
/build/env/bin/python -I -B -c 'import scipy_openblas64; print(scipy_openblas64.get_pkg_config())' > /build/pkgconfig/scipy-openblas.pc
export PKG_CONFIG_PATH=/build/pkgconfig
cd /build/source/numpy-2.5.3
/build/env/bin/python -I -B -m build --wheel --no-isolation --outdir /build/raw -Cbuild-dir=/build/numpy-build -Csetup-args=-Dcpu-baseline=none -Csetup-args=-Duse-ilp64=true -Csetup-args=-Dblas=scipy-openblas -Csetup-args=-Dlapack=scipy-openblas -Ccompile-args=-j8
/build/env/bin/auditwheel repair --plat manylinux_2_28_x86_64 -w /build/repaired /build/raw/*.whl
