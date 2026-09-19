#!/bin/bash
 
script_dir="$QBOX_PACKAGE_DIR/bin"
QBOX_NAME="${QBOX_NAME:-qbox}"
QBOX_VERSION="${QBOX_VERSION:-0.1.0}"
QBOX_AUTHOR="${QBOX_AUTHOR:-waler}"
QBOX_PYTHON="${QBOX_PYTHON:-}"
QBOX_MULTIWFN_HOME="${QBOX_MULTIWFN_HOME:-}"
QBOX_PSEUDO_ROOT="${QBOX_PSEUDO_ROOT:-}"
QBOX_QE_ENV_SCRIPT="${QBOX_QE_ENV_SCRIPT:-}"
QBOX_ONEAPI_ENV_SCRIPT="${QBOX_ONEAPI_ENV_SCRIPT:-}"
QBOX_TEST_MODE="${QBOX_TEST_MODE:-0}"

if [ -n "${QBOX_SHARED_ROOT:-}" ]; then
    if [ -z "${_QBOX_OFFLINE_ROOT:-}" ]; then
        QBOX_PYTHON="${QBOX_PYTHON:-$QBOX_SHARED_ROOT/python/bin/python3}"
    fi
    QBOX_MULTIWFN_HOME="${QBOX_MULTIWFN_HOME:-$QBOX_SHARED_ROOT/multiwfn}"
fi
if [ -z "${_QBOX_OFFLINE_ROOT:-}" ]; then
    QBOX_SHARED_ROOT="${QBOX_SHARED_ROOT:-}"
    QBOX_PYTHON="${QBOX_PYTHON:-$(command -v python3 2>/dev/null || true)}"
fi

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
if [ -z "${_QBOX_OFFLINE_ROOT:-}" ]; then
    PATH="$script_dir:$PATH"
fi
export PATH QBOX_NAME QBOX_VERSION QBOX_AUTHOR QBOX_PYTHON
if [ -z "${_QBOX_OFFLINE_ROOT:-}" ] || [[ -v QBOX_SHARED_ROOT ]]; then
    export QBOX_SHARED_ROOT
fi
export QBOX_MULTIWFN_HOME QBOX_PSEUDO_ROOT QBOX_QE_ENV_SCRIPT QBOX_ONEAPI_ENV_SCRIPT QBOX_TEST_MODE

qbox_prepare_mplconfigdir() {
    local candidate temp_root
    if [ -n "${MPLCONFIGDIR:-}" ]; then
        candidate="$MPLCONFIGDIR"
        if mkdir -p -- "$candidate" 2>/dev/null && [ -d "$candidate" ] &&
           [ -w "$candidate" ] && [ -x "$candidate" ]; then
            export MPLCONFIGDIR="$candidate"
            return 0
        fi
    fi
    if [[ "${XDG_CACHE_HOME:-}" = /* ]]; then
        candidate="$XDG_CACHE_HOME/qbox/matplotlib"
        if mkdir -p -- "$candidate" 2>/dev/null && [ -d "$candidate" ] &&
           [ -w "$candidate" ] && [ -x "$candidate" ]; then
            export MPLCONFIGDIR="$candidate"
            return 0
        fi
    fi
    if [[ "${HOME:-}" = /* ]]; then
        candidate="$HOME/.cache/qbox/matplotlib"
        if mkdir -p -- "$candidate" 2>/dev/null && [ -d "$candidate" ] &&
           [ -w "$candidate" ] && [ -x "$candidate" ]; then
            export MPLCONFIGDIR="$candidate"
            return 0
        fi
    fi
    temp_root="${TMPDIR:-/tmp}"
    if [[ "$temp_root" != /* ]] || [ ! -d "$temp_root" ] ||
       [ ! -w "$temp_root" ] || [ ! -x "$temp_root" ]; then
        echo '错误：无法找到可写的绝对临时目录来创建 MPLCONFIGDIR。' >&2
        return 1
    fi
    candidate="$(mktemp -d -- "$temp_root/qbox-matplotlib.XXXXXXXX")" || {
        echo '错误：无法创建独占的 MPLCONFIGDIR 临时目录。' >&2
        return 1
    }
    if [ -d "$candidate" ] && [ -w "$candidate" ] && [ -x "$candidate" ]; then
        MPLCONFIGDIR="$candidate"
        export MPLCONFIGDIR
        return 0
    fi
    rmdir -- "$candidate" 2>/dev/null || true
    echo '错误：无法创建可写的独占 MPLCONFIGDIR 临时目录。' >&2
    return 1
}

if [ -n "${_QBOX_OFFLINE_ROOT:-}" ]; then
    qbox_prepare_mplconfigdir || return 1
else
    export MPLCONFIGDIR="${MPLCONFIGDIR:-${TMPDIR:-/tmp}/.qbox-mpl-cache-${UID:-user}}"
    mkdir -p "$MPLCONFIGDIR" 2>/dev/null || true
fi
 
#echo '>===============================================================================<'
#echo '>-                                                                             -<'
#echo '>-                              Version - W - 3.0                              -<'
#echo '>-                                                                             -<'
#echo '>===============================================================================<'
