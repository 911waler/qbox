#!/bin/sh
# Rebuild the complete, same-version lxml static closure for baseline x86-64.
set -eu
export PATH=/build/env/bin:/opt/rh/gcc-toolset-14/root/usr/bin:/usr/local/bin:/usr/bin:/bin
export CC=gcc CXX=g++ FC=gfortran HOME=/build/home PIP_CONFIG_FILE=/dev/null
gcc --version
ldd --version
/opt/python/cp312-cp312/bin/python -I -B -m venv /build/env
/build/env/bin/python -I -B -m pip --isolated install --no-index --only-binary=:all: --require-hashes --find-links /build/build-wheelhouse -r /build/build-requirements.lock
mkdir -p /build/raw /build/repaired
cd /build/source/lxml-6.1.3
patch -p1 < /build/lxml-offline.patch
mkdir -p libs
cp /build/source-archives/* libs/
export STATICBUILD=1 WITHOUT_CYTHON=true MULTICORE=8
export LIBXML2_VERSION=2.14.6 LIBXSLT_VERSION=1.1.43 LIBICONV_VERSION=1.18 ZLIB_VERSION=1.3.2
/build/env/bin/python -I -B -m build --wheel --no-isolation --outdir /build/raw
/build/env/bin/auditwheel repair --plat manylinux_2_28_x86_64 -w /build/repaired /build/raw/lxml-*.whl
