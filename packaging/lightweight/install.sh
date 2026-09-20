#!/usr/bin/env bash
# Keep arguments intact, including spaces, quotes and non-ASCII paths.
set -euo pipefail
original_args=("$@")
python_command=python3
show_help=false
mode_seen=false
prefix_seen=false
bin_seen=false
python_seen=false
fail() { printf 'qbox-installer: %s\n' "$*" >&2; exit 2; }
while (($#)); do
    option=${1%%=*}
    case "$option" in
        --help|-h)
            [[ "$1" == "$option" ]] || fail "unrecognized argument: $1"
            show_help=true; shift ;;
        --user|--system)
            [[ "$1" == "$option" ]] || fail "unrecognized argument: $1"
            [[ "$mode_seen" == false ]] || fail 'installation mode may be selected only once'
            mode_seen=true; shift ;;
        --prefix|--bin-dir|--python)
            case "$option" in
                --prefix) seen=$prefix_seen; prefix_seen=true ;;
                --bin-dir) seen=$bin_seen; bin_seen=true ;;
                --python) seen=$python_seen; python_seen=true ;;
            esac
            [[ "$seen" == false ]] || fail "$option may be supplied only once"
            if [[ "$1" == *=* ]]; then
                value=${1#*=}; shift
            else
                (($# >= 2)) || fail "$option requires a value"
                [[ "$2" != -* ]] || fail "$option requires a value (received $2)"
                value=$2; shift 2
            fi
            [[ -n "${value//[[:space:]]/}" ]] || fail "$option path must not be empty"
            [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || fail "$option path must not contain a line break"
            [[ "$option" != --python ]] || python_command=$value ;;
        *) fail "unrecognized argument: $1" ;;
    esac
done
if [[ "$show_help" == true ]]; then
    printf '%s\n' \
        'Usage: bash install.sh (--user|--system) [--prefix PATH] [--bin-dir PATH] [--python PATH]' \
        '  --user       Install as a normal user; default $HOME/.local/share/qbox' \
        '  --system     Install as root; default /opt/qbox' \
        '  --prefix     Dedicated installation directory; command defaults to PREFIX/bin/qbox' \
        '  --bin-dir    Optional separate command directory' \
        '  --python     Python 3.10+ with venv/pip; defaults to python3 from PATH' \
        'Scientific dependencies require network access. No shell configuration is changed.'
    exit 0
fi
[[ "$mode_seen" == true ]] || fail 'one of --user or --system is required'
# Resolve relative interpreter paths before entering the extracted bundle.
python_path=$(command -v -- "$python_command") || fail "Python interpreter not found: $python_command; supply --python PATH (Python 3.10+)"
[[ "$python_path" == /* ]] || python_path="$PWD/$python_path"
"$python_path" -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "qbox-installer: Python 3.10+ is required; choose --python PATH")' || exit $?
export QBOX_INSTALL_CALLER_CWD="$PWD"
script_path=${BASH_SOURCE[0]}
if [[ "$script_path" == */* ]]; then
    cd -- "${script_path%/*}"
fi
# -E/-s ignore caller Python settings; -B keeps the verified bundle unchanged.
exec "$python_path" -E -s -B -m installer "${original_args[@]}"
