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
printf '%s  %s\n' 'be99cde194739f2676e415e7b457d1dc6b94c00c5d86cae60ead44fcf3ea4c00' buildlibxml.py | sha256sum -c -
patch -p1 < /build/lxml-offline.patch
printf '%s  %s\n' '07edec3396856b1752dc19dfce14d7ad5536909ce526eecbb00e423206d2d293' buildlibxml.py | sha256sum -c -
mkdir -p libs
cp /build/source-archives/* libs/
export QBOX_OFFLINE_BUILD=1 STATICBUILD=1 WITHOUT_CYTHON=true MULTICORE=8
export LIBXML2_VERSION=2.14.6 LIBXSLT_VERSION=1.1.43 LIBICONV_VERSION=1.18 ZLIB_VERSION=1.3.2
/build/env/bin/python -I -B /build/check_lxml_offline.py
/build/env/bin/python -I -B -m build --wheel --no-isolation --outdir /build/raw
/build/env/bin/auditwheel repair --plat manylinux_2_28_x86_64 -w /build/repaired /build/raw/lxml-*.whl
