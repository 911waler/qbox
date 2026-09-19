#!/usr/bin/env bash
set -u

launcher=$(readlink -f -- "${BASH_SOURCE[0]}") || exit 1
release=$(cd -- "$(dirname -- "$launcher")/.." && pwd -P) || exit 1
python="$release/python/bin/python3"

if [[ ! -x "$python" || ! -f "$release/metadata/installed.json" ]]; then
    printf 'qbox：安装不完整，请重新验证本版本。\n' >&2
    exit 1
fi

if [[ -n ${QBOX_PYTHON:-} ]] &&
   [[ $(readlink -f -- "$QBOX_PYTHON" 2>/dev/null) != $(readlink -f -- "$python") ]]; then
    printf 'qbox：QBOX_PYTHON 指向包外解释器，请先执行 unset QBOX_PYTHON。\n' >&2
    exit 2
fi

export _QBOX_OFFLINE_ROOT="$release" QBOX_PYTHON="$python"
exec "$python" -I -B -m qbox "$@"
