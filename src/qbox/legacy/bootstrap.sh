#!/bin/bash
 
script_dir="$QBOX_PACKAGE_DIR/bin"
QBOX_NAME="${QBOX_NAME:-qbox}"
QBOX_VERSION="${QBOX_VERSION:-0.1.0}"
QBOX_AUTHOR="${QBOX_AUTHOR:-waler}"
QBOX_SHARED_ROOT="${QBOX_SHARED_ROOT:-}"
QBOX_PYTHON="${QBOX_PYTHON:-}"
QBOX_MULTIWFN_HOME="${QBOX_MULTIWFN_HOME:-}"
QBOX_PSEUDO_ROOT="${QBOX_PSEUDO_ROOT:-}"
QBOX_QE_ENV_SCRIPT="${QBOX_QE_ENV_SCRIPT:-}"
QBOX_ONEAPI_ENV_SCRIPT="${QBOX_ONEAPI_ENV_SCRIPT:-}"
QBOX_TEST_MODE="${QBOX_TEST_MODE:-0}"

if [ -n "$QBOX_SHARED_ROOT" ]; then
    QBOX_PYTHON="${QBOX_PYTHON:-$QBOX_SHARED_ROOT/python/bin/python3}"
    QBOX_MULTIWFN_HOME="${QBOX_MULTIWFN_HOME:-$QBOX_SHARED_ROOT/multiwfn}"
fi
QBOX_PYTHON="${QBOX_PYTHON:-$(command -v python3 2>/dev/null || true)}"

if [ -n "$QBOX_PSEUDO_ROOT" ]; then
    sssppath="$QBOX_PSEUDO_ROOT/QE/SSSP"
    PD04PBEpath="$QBOX_PSEUDO_ROOT/QE/NCPP-PD04-PBE"
    SG15PBEpath="$QBOX_PSEUDO_ROOT/PWmat/NCPP-SG15-PBE"
else
    sssppath=''
    PD04PBEpath=''
    SG15PBEpath=''
fi

if [ -n "$QBOX_MULTIWFN_HOME" ] && [ -d "$QBOX_MULTIWFN_HOME" ]; then
    PATH="$QBOX_MULTIWFN_HOME:$PATH"
fi
PATH="$script_dir:$PATH"
export PATH QBOX_NAME QBOX_VERSION QBOX_AUTHOR QBOX_SHARED_ROOT QBOX_PYTHON
export QBOX_MULTIWFN_HOME QBOX_PSEUDO_ROOT QBOX_QE_ENV_SCRIPT QBOX_ONEAPI_ENV_SCRIPT QBOX_TEST_MODE
export MPLCONFIGDIR="${MPLCONFIGDIR:-${TMPDIR:-/tmp}/.qbox-mpl-cache-${UID:-user}}"
mkdir -p "$MPLCONFIGDIR" 2>/dev/null || true
 
#echo '>===============================================================================<'
#echo '>-                                                                             -<'
#echo '>-                              Version - W - 3.0                              -<'
#echo '>-                                                                             -<'
#echo '>===============================================================================<'
