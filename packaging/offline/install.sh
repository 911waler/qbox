#!/usr/bin/env bash
# Source-safe offline bootstrap and guarded release transaction.
_QBOX_INSTALLER_SOURCE=${BASH_SOURCE[0]}

qbox_error() { printf 'qbox：%s\n' "$*" >&2; return 1; }

parse_options() {
    QBOX_PREFIX="${HOME}/.local/share/qbox"
    QBOX_BIN_DIR="${HOME}/.local/bin"
    local prefix_seen=0 bin_seen=0
    while (( $# )); do
        case "$1" in
            --prefix|--bin-dir)
                local option="$1"
                (( $# >= 2 )) && [[ "$2" != --* ]] || { qbox_error "$option 缺少路径参数"; return 1; }
                [[ -n "$2" ]] || { qbox_error "$option 路径不能为空"; return 1; }
                if [[ "$option" == --prefix ]]; then
                    (( prefix_seen == 0 )) || { qbox_error '重复参数 --prefix'; return 1; }
                    QBOX_PREFIX="$2"; prefix_seen=1
                else
                    (( bin_seen == 0 )) || { qbox_error '重复参数 --bin-dir'; return 1; }
                    QBOX_BIN_DIR="$2"; bin_seen=1
                fi
                shift 2 ;;
            *) qbox_error "未知参数：$1"; return 1 ;;
        esac
    done
}

probe_bash_version() { printf '%s.%s\n' "${BASH_VERSINFO[0]}" "${BASH_VERSINFO[1]}"; }

version_at_least() {
    local value="$1" major="$2" minor="$3"
    [[ "$value" =~ ^([0-9]{1,4})\.([0-9]{1,4})$ ]] || return 1
    (( 10#${BASH_REMATCH[1]} > major || (10#${BASH_REMATCH[1]} == major && 10#${BASH_REMATCH[2]} >= minor) ))
}

parse_loader_glibc() {
    local first="${1%%$'\n'*}"
    # Old loaders lacking --version support fail closed; never parse their errors.
    [[ "$first" =~ ^ld\.so\ \(.+\)\ stable\ release\ version\ ([0-9]+\.[0-9]+)\.$ ]] || return 1
    printf '%s\n' "${BASH_REMATCH[1]}"
}

probe_glibc() {
    local result loader
    if command -v getconf >/dev/null 2>&1; then
        if result=$(LC_ALL=C getconf GNU_LIBC_VERSION 2>/dev/null) && [[ "$result" =~ ^glibc\ ([0-9]+\.[0-9]+)$ ]]; then
            printf '%s\n' "${BASH_REMATCH[1]}"; return 0
        fi
    fi
    for loader in /lib64/ld-linux-x86-64.so.2 /lib/x86_64-linux-gnu/ld-linux-x86-64.so.2; do
        if [[ -x "$loader" ]] && result=$(LC_ALL=C "$loader" --version 2>/dev/null) && parse_loader_glibc "$result"; then
            return 0
        fi
    done
    qbox_error '无法可靠识别 glibc 版本'
}

preflight_platform() {
    local version name tar_version
    version=$(probe_bash_version) && version_at_least "$version" 4 4 || { qbox_error '需要 Bash 4.4 或更新版本'; return 1; }
    # Keep the list explicit: no Python, ldd, file, flock, find, rg or bc required.
    for name in uname readlink stat sha256sum mktemp cp rm mkdir rmdir mv ln chmod cat env grep sed awk tar gzip; do
        command -v "$name" >/dev/null 2>&1 || { qbox_error "缺少基础命令：$name"; return 1; }
    done
    [[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { qbox_error '仅支持 Linux x86_64'; return 1; }
    tar_version=$(LC_ALL=C tar --version) || { qbox_error '无法识别 GNU tar'; return 1; }
    [[ "$tar_version" == 'tar (GNU tar) '* ]] || { qbox_error '需要 GNU tar'; return 1; }
    version=$(probe_glibc) && version_at_least "$version" 2 28 || { qbox_error '需要 glibc 2.28 或更新版本'; return 1; }
}

validate_absolute_path() {
    local LC_ALL=C value="$1"
    [[ -n "$value" ]] || { qbox_error '路径不能为空'; return 1; }
    [[ "$value" != *[[:cntrl:]]* ]] || { qbox_error '路径不能包含控制字符'; return 1; }
    [[ "$value" == /* ]] || { qbox_error '必须使用绝对路径'; return 1; }
    [[ "$value" != / ]] || { qbox_error '不能使用根目录'; return 1; }
}

directory_is_empty() (
    [[ -r "$1" && -x "$1" ]] || return 1
    unset GLOBIGNORE
    shopt -s dotglob nullglob
    local entries=("$1"/*)
    (( ${#entries[@]} == 0 ))
)

validate_root_marker() {
    local prefix="$1" expected actual
    [[ -d "$prefix" && ! -L "$prefix" && -O "$prefix" && -f "$prefix/.qbox-root" && ! -L "$prefix/.qbox-root" && -O "$prefix/.qbox-root" ]] || return 1
    # Exact bytes including the three final LFs; do not source/eval untrusted text.
    expected=$(printf 'schema_version=1\nuid=%s\nprefix=%s\n' "$EUID" "$prefix" | sha256sum) || return 1
    actual=$(sha256sum < "$prefix/.qbox-root") || return 1
    [[ "${expected%% *}" == "${actual%% *}" ]]
}

path_within() { [[ "$1" == "$2" || "$1" == "$2/"* ]]; }

unsafe_bin_overlap() {
    local prefix="$1" bin="$2" original="$3" current ancestor parent leaf
    path_within "$prefix" "$bin" && return 0
    for ancestor in releases current .install-lock .qbox-root; do
        path_within "$bin" "$prefix/$ancestor" && return 0
    done
    [[ "$bin" == "$prefix/".stage.* ]] && return 0
    current=$(readlink -m -- "$prefix/current") || return 0
    path_within "$bin" "$current" && return 0
    # Preserve lexical managed names when a symlink resolves outside the root.
    ancestor="$original"
    while [[ "$ancestor" != / ]]; do
        leaf="${ancestor##*/}"
        parent=$(readlink -m -- "${ancestor%/*}/") || return 0
        if [[ "$parent" == "$prefix" ]]; then
            case "$leaf" in releases|current|.install-lock|.qbox-root|.stage.*) return 0 ;; esac
        fi
        ancestor="${ancestor%/*}"
        [[ -n "$ancestor" ]] || ancestor=/
    done
    return 1
}

writable_path_ancestor() {
    local ancestor="$1"
    while [[ ! -e "$ancestor" && ! -L "$ancestor" ]]; do
        ancestor="${ancestor%/*}"
        [[ -n "$ancestor" ]] || ancestor=/
    done
    [[ -d "$ancestor" && -w "$ancestor" && -x "$ancestor" ]] || { qbox_error '路径现有祖先必须是可写、可进入的目录'; return 1; }
}

preflight_paths() {
    local original_bin
    validate_absolute_path "$QBOX_PREFIX" && validate_absolute_path "$QBOX_BIN_DIR" || return 1
    original_bin=$(readlink -m -s -- "$QBOX_BIN_DIR") || return 1
    QBOX_PREFIX=$(readlink -m -- "$QBOX_PREFIX") && QBOX_BIN_DIR=$(readlink -m -- "$QBOX_BIN_DIR") || { qbox_error '无法规范化路径'; return 1; }
    validate_absolute_path "$QBOX_PREFIX" && validate_absolute_path "$QBOX_BIN_DIR" || return 1
    if unsafe_bin_overlap "$QBOX_PREFIX" "$QBOX_BIN_DIR" "$original_bin"; then
        qbox_error '安装根目录与命令目录存在不安全重叠'; return 1
    fi
    if [[ -e "$QBOX_PREFIX" || -L "$QBOX_PREFIX" ]]; then
        [[ -d "$QBOX_PREFIX" && ! -L "$QBOX_PREFIX" && -O "$QBOX_PREFIX" ]] || { qbox_error '安装根目录必须是当前用户拥有的目录'; return 1; }
        [[ ! -e "$QBOX_PREFIX/.install-lock" && ! -L "$QBOX_PREFIX/.install-lock" ]] || { qbox_error '安装进行中或遗留锁；请人工核验 .install-lock 后再试'; return 1; }
        directory_is_empty "$QBOX_PREFIX" || validate_root_marker "$QBOX_PREFIX" || { qbox_error '安装根目录包含非 qbox 内容或无效根标记'; return 1; }
    fi
    writable_path_ancestor "$QBOX_PREFIX" && writable_path_ancestor "$QBOX_BIN_DIR"
}

safe_payload_path() {
    local LC_ALL=C name="$1"
    [[ "$name" =~ ^[A-Za-z0-9._+@=/-]+$ && "$name" != /* && "$name" != */ && "$name" != *//* ]] || return 1
    [[ "/$name/" != */./* && "/$name/" != */../* ]]
}

bundle_payload_path() {
    safe_payload_path "$1" || return 1
    case "$1" in
        install.sh|manifest.json|requirements.lock|README.zh-CN.md|LICENSE|runtime/python.tar.gz|checks/*|THIRD_PARTY_LICENSES/*|packages/*|wheelhouse/*) return 0 ;;
        *) return 1 ;;
    esac
}

verify_bundle_inventory() (
    # Subshell confines glob settings. The associative inventory is inherited.
    [[ -r "$1" && -x "$1" ]] || { qbox_error '包根目录无法完整枚举'; return 1; }
    unset GLOBIGNORE
    shopt -s globstar dotglob nullglob
    local item name
    for item in "$1"/**; do
        name="${item#"$1/"}"
        [[ "$item" != "$1/" ]] || continue
        [[ ! -L "$item" ]] || { qbox_error "包内不允许符号链接：$name"; return 1; }
        if [[ -d "$item" ]]; then
            [[ -r "$item" && -x "$item" ]] || { qbox_error '包内目录无法完整枚举'; return 1; }
            safe_payload_path "$name" || { qbox_error '包内目录路径不安全'; return 1; }
            case "$name" in
                runtime|checks|THIRD_PARTY_LICENSES|packages|wheelhouse|checks/*|THIRD_PARTY_LICENSES/*|packages/*|wheelhouse/*) ;;
                *) qbox_error "包内目录不在白名单：$name"; return 1 ;;
            esac
        elif [[ -f "$item" ]]; then
            safe_payload_path "$name" || { qbox_error '包内文件路径不安全'; return 1; }
            [[ "$name" == SHA256SUMS || -n "${hashes["$name"]+present}" ]] || { qbox_error "包内有未列出的文件：$name"; return 1; }
        else
            qbox_error "包内不允许特殊文件：$name"; return 1
        fi
    done
)

verify_bundle_files() {
    unset QBOX_RUNTIME_SHA256 QBOX_VERIFIED_BUNDLE
    local LC_ALL=C bundle="$1" line digest name actual required bytes=0 checksum_size
    local -A hashes=()
    [[ -d "$bundle" && ! -L "$bundle" ]] || { qbox_error '离线包目录无效'; return 1; }
    bundle=$(readlink -m -- "$bundle") || return 1
    [[ -f "$bundle/SHA256SUMS" && ! -L "$bundle/SHA256SUMS" ]] || { qbox_error '缺少普通文件 SHA256SUMS'; return 1; }
    while true; do
        line=
        if ! IFS= read -r line; then
            [[ -z "$line" ]] || { qbox_error 'SHA256SUMS 必须以换行结束'; return 1; }
            break
        fi
        (( bytes += ${#line} + 1 ))
        [[ "$line" =~ ^([0-9a-f]{64})\ \ ([A-Za-z0-9._+@=/-]+)$ ]] || { qbox_error 'SHA256SUMS 行格式无效'; return 1; }
        digest="${BASH_REMATCH[1]}"; name="${BASH_REMATCH[2]}"
        bundle_payload_path "$name" || { qbox_error 'SHA256SUMS 路径不在安全白名单'; return 1; }
        [[ -z "${hashes["$name"]+present}" ]] || { qbox_error 'SHA256SUMS 包含重复文件'; return 1; }
        hashes["$name"]="$digest"
    done < "$bundle/SHA256SUMS"
    checksum_size=$(stat -c %s -- "$bundle/SHA256SUMS") || return 1
    [[ "$checksum_size" == "$bytes" ]] || { qbox_error 'SHA256SUMS 包含无效字节'; return 1; }
    for required in install.sh manifest.json requirements.lock README.zh-CN.md LICENSE runtime/python.tar.gz; do
        [[ -n "${hashes["$required"]+present}" ]] || { qbox_error "SHA256SUMS 缺少必需文件：$required"; return 1; }
    done
    verify_bundle_inventory "$bundle" || return 1
    for name in "${!hashes[@]}"; do
        [[ -f "$bundle/$name" && ! -L "$bundle/$name" ]] || { qbox_error "校验文件不存在：$name"; return 1; }
        actual=$(sha256sum < "$bundle/$name") || { qbox_error '无法计算 SHA256'; return 1; }
        [[ "${actual%% *}" == "${hashes["$name"]}" ]] || { qbox_error "SHA256 不匹配：$name"; return 1; }
    done
    QBOX_RUNTIME_SHA256="${hashes[runtime/python.tar.gz]}"
    QBOX_VERIFIED_BUNDLE="$bundle"
}

validate_runtime_listing() {
    local LC_ALL=C line mode name parent type count=0
    local pattern='^([-d][r-][w-][x-][r-][w-][x-][r-][w-][x-]) +0/0 +([0-9]+) +[0-9]{4}-[0-9]{2}-[0-9]{2} +[0-9]{2}:[0-9]{2}:[0-9]{2} +([^[:space:]]+)$'
    local -A seen=() directories=()
    while IFS= read -r line; do
        [[ "$line" =~ $pattern ]] || { qbox_error '运行时归档列举格式、类型或权限无效'; return 1; }
        mode="${BASH_REMATCH[1]}"; name="${BASH_REMATCH[3]}"; type="${mode:0:1}"
        if [[ "$type" == d ]]; then
            [[ "${BASH_REMATCH[2]}" == 0 ]] || { qbox_error '运行时归档目录大小无效'; return 1; }
            name="${name%/}"
        fi
        safe_payload_path "$name" || { qbox_error '运行时归档路径不安全'; return 1; }
        [[ "$name" == python || "$name" == python/* ]] || { qbox_error '运行时归档超出 python 根目录'; return 1; }
        [[ "$name" != python || "$type" == d ]] || { qbox_error '运行时归档 python 根必须为目录'; return 1; }
        [[ -z "${seen["$name"]+present}" ]] || { qbox_error '运行时归档包含重复成员'; return 1; }
        [[ "$type" == d || -z "${directories["$name"]+present}" ]] || { qbox_error '运行时归档以文件充当父目录'; return 1; }
        seen["$name"]="$type"
        parent="$name"
        while [[ "$parent" == */* ]]; do
            parent="${parent%/*}"
            [[ -z "${seen["$parent"]+present}" || "${seen["$parent"]}" == d ]] || { qbox_error '运行时归档父成员不是目录'; return 1; }
            directories["$parent"]=1
        done
        (( count += 1 ))
    done < "$1"
    (( count > 0 )) || { qbox_error '运行时归档为空'; return 1; }
}

inspect_runtime_archive() (
    local archive="$1" scratch
    unset TAR_OPTIONS GZIP
    [[ -f "$archive" && ! -L "$archive" ]] || { qbox_error '运行时归档不是普通文件'; return 1; }
    scratch=$(mktemp -d) || { qbox_error '无法创建归档检查临时目录'; return 1; }
    trap 'rm -f -- "$scratch/list" "$scratch/errors"; rmdir -- "$scratch"' EXIT
    if ! LC_ALL=C tar --list --verbose --numeric-owner --full-time --quoting-style=escape --absolute-names --gzip --file "$archive" > "$scratch/list" 2> "$scratch/errors"; then
        qbox_error '运行时归档无法完整列举'; return 1
    fi
    [[ ! -s "$scratch/errors" ]] || { qbox_error '运行时归档列举产生诊断，拒绝展开'; return 1; }
    validate_runtime_listing "$scratch/list"
)

extract_runtime() (
    local archive="$1" stage="$2" runtime_copy actual canonical
    unset TAR_OPTIONS GZIP
    [[ "${QBOX_RUNTIME_SHA256-}" =~ ^[0-9a-f]{64}$ && -n "${QBOX_VERIFIED_BUNDLE-}" ]] || { qbox_error '运行时归档必须先完成离线包校验'; return 1; }
    canonical=$(readlink -m -- "$archive") || return 1
    [[ "$canonical" == "$QBOX_VERIFIED_BUNDLE/runtime/python.tar.gz" && -f "$archive" && ! -L "$archive" ]] || { qbox_error '运行时归档不属于已校验离线包'; return 1; }
    validate_absolute_path "$stage" || return 1
    [[ -d "$stage" && ! -L "$stage" && -O "$stage" ]] && directory_is_empty "$stage" || { qbox_error '展开归档需要当前用户拥有的空 stage 目录'; return 1; }
    # The caller owns stage and its lock. Only this exclusive input is ours to clean.
    runtime_copy=$(mktemp -- "$stage/.runtime-input.XXXXXXXX") || { qbox_error '无法创建独占归档输入'; return 1; }
    trap 'rm -f -- "$runtime_copy"' EXIT
    cp -- "$archive" "$runtime_copy" || { qbox_error '复制运行时归档失败'; return 1; }
    actual=$(sha256sum < "$runtime_copy") || return 1
    [[ "${actual%% *}" == "$QBOX_RUNTIME_SHA256" ]] || { qbox_error '运行时归档副本 SHA256 不匹配'; return 1; }
    inspect_runtime_archive "$runtime_copy" || return 1
    tar --extract --gzip --file "$runtime_copy" --directory "$stage" --no-same-owner --no-same-permissions --delay-directory-restore || { qbox_error '运行时归档展开失败'; return 1; }
    [[ -f "$stage/python/bin/python3" && ! -L "$stage/python/bin/python3" && -x "$stage/python/bin/python3" && -f "$stage/python/bin/python3.12" && ! -L "$stage/python/bin/python3.12" && -x "$stage/python/bin/python3.12" ]] || { qbox_error '运行时归档缺少必需解释器'; return 1; }
    # The first Python executed is the verified bundled interpreter, in isolated mode.
    "$stage/python/bin/python3" -I -B -c 'import os, sys; v = os.confstr("CS_GNU_LIBC_VERSION"); assert v and v.startswith("glibc "); assert tuple(map(int, v.split()[1].split("."))) >= (2, 28); assert sys.version_info[:2] == (3, 12)' || { qbox_error '包内 Python/glibc 复核失败'; return 1; }
)

# Mutation primitives run only within main's subshell. No traps or shell options
# are installed when this file is sourced.
create_owned_directories() {
    local path="$1" parent identity
    if [[ -e "$path" || -L "$path" ]]; then
        [[ -d "$path" && ! -L "$path" ]] || return 1
        return 0
    fi
    parent="${path%/*}"; [[ -n "$parent" ]] || parent=/
    create_owned_directories "$parent" || return 1
    if ! mkdir -- "$path" 2>/dev/null; then
        [[ -d "$path" && ! -L "$path" && "$(readlink -m -- "$path")" == "$path" ]]
        return $?
    fi
    identity=$(stat -c '%d:%i' -- "$path") || return 1
    created_directories+=("$path")
    created_identities+=("$identity")
    if (( lock_owned )); then
        printf '%s\t%s\n' "$identity" "$path" >> "$lock/created-directories" || return 1
    fi
}

lock_is_ours() {
    [[ "$lock_owned" == 1 && -d "$lock" && ! -L "$lock" && -O "$lock" ]] || return 1
    [[ "$(readlink -m -- "$lock")" == "$lock" && "$(stat -c '%d:%i' -- "$lock")" == "$lock_identity" ]] || return 1
    [[ -f "$lock/owner" && ! -L "$lock/owner" ]] || return 1
    [[ "$(cat -- "$lock/owner")" == "$token $transaction_pid" ]]
}

root_empty_except_lock() (
    unset GLOBIGNORE
    shopt -s dotglob nullglob
    local items=("$prefix"/*)
    (( ${#items[@]} == 1 )) && [[ "${items[0]}" == "$lock" ]]
)

acquire_install_lock() {
    create_owned_directories "$prefix" || { qbox_error '无法创建安装目录'; return 1; }
    lock="$prefix/.install-lock"
    mkdir -- "$lock" 2>/dev/null || { qbox_error '安装进行中或遗留锁；请人工核验 .install-lock 后再试'; return 1; }
    lock_owned=1
    lock_identity=$(stat -c '%d:%i' -- "$lock") || return 1
    printf '%s %s\n' "$token" "$transaction_pid" > "$lock/owner" || return 1
    local index
    for index in "${!created_directories[@]}"; do
        printf '%s\t%s\n' "${created_identities[index]}" "${created_directories[index]}" >> "$lock/created-directories" || return 1
    done
    if ! validate_root_marker "$prefix"; then
        root_empty_except_lock || { qbox_error '锁内复核：根目录归属无效'; return 1; }
        ( set -o noclobber; printf 'schema_version=1\nuid=%s\nprefix=%s\n' "$EUID" "$prefix" > "$prefix/.qbox-root" ) || return 1
        root_created=1
    fi
    validate_root_marker "$prefix" || return 1
    [[ "$(readlink -m -- "$prefix")" == "$prefix" && "$(readlink -m -- "$bin_dir")" == "$bin_dir" ]] || return 1
    if [[ -e "$prefix/releases" || -L "$prefix/releases" ]]; then
        [[ -d "$prefix/releases" && ! -L "$prefix/releases" && -O "$prefix/releases" ]] || { qbox_error 'releases 目录归属无效'; return 1; }
    else
        create_owned_directories "$prefix/releases" || return 1
    fi
}

current_target() {
    local target
    if [[ ! -e "$prefix/current" && ! -L "$prefix/current" ]]; then return 0; fi
    [[ -L "$prefix/current" ]] || { qbox_error 'current 必须是受管理的版本链接'; return 1; }
    target=$(readlink -- "$prefix/current") || return 1
    [[ "$target" =~ ^releases/[A-Za-z0-9][A-Za-z0-9._+-]*$ ]] || { qbox_error 'current 指向非受管理位置'; return 1; }
    [[ -d "$prefix/$target" && ! -L "$prefix/$target" && -O "$prefix/$target" ]] || { qbox_error 'current 版本目录无效'; return 1; }
    printf '%s' "$target"
}

check_bin_target() {
    local entry="$bin_dir/qbox"
    if [[ -e "$entry" || -L "$entry" ]]; then
        [[ -L "$entry" && "$(readlink -- "$entry")" == "$prefix/current/bin/qbox" && -n "$old_current" ]] || { qbox_error '命令 qbox 已存在且不属于此有效安装；请使用其他 --bin-dir'; return 1; }
    fi
}

record_stage() {
    stage_identity=$(stat -c '%d:%i' -- "$stage") || return 1
    printf '%s\n%s\n%s\n' "$token" "$stage" "$stage_identity" > "$lock/stage" || return 1
}

read_bundle_identity() {
    local identity
    identity=$("$stage/python/bin/python3" -I -B - "$bundle" <<'PY'
import hashlib, importlib.util, json, pathlib, sys
bundle=pathlib.Path(sys.argv[1])
spec=importlib.util.spec_from_file_location('qbox_manifest',bundle/'checks/manifest.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
data=(bundle/'manifest.json').read_bytes(); manifest=json.loads(data)
module.validate_manifest(manifest)
print(manifest['release_id']); print(hashlib.sha256(data).hexdigest())
PY
    ) || { qbox_error 'manifest 身份校验失败'; return 1; }
    release_id="${identity%%$'\n'*}"; manifest_sha256="${identity#*$'\n'}"
    [[ "$release_id" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ && "$manifest_sha256" =~ ^[a-f0-9]{64}$ ]] || return 1
}

install_wheels() (
    local variable
    while IFS= read -r variable; do unset "$variable"; done < <(compgen -v PIP_)
    export PIP_CONFIG_FILE=/dev/null
    "$stage/python/bin/python3" -I -B -m pip --isolated --disable-pip-version-check \
        install --no-index --only-binary=:all: --require-hashes \
        --no-cache-dir --no-compile --ignore-installed \
        --find-links "$bundle/packages" --find-links "$bundle/wheelhouse" \
        -r "$bundle/requirements.lock"
)

install_metadata() {
    mkdir -- "$stage/bin" "$stage/metadata" || return 1
    cp -- "$bundle/checks/qbox-launcher.sh" "$stage/bin/qbox" || return 1
    chmod 755 -- "$stage/bin/qbox" || return 1
    cp -- "$bundle/manifest.json" "$bundle/requirements.lock" "$bundle/LICENSE" "$stage/metadata/" || return 1
    cp -R -- "$bundle/checks" "$bundle/THIRD_PARTY_LICENSES" "$stage/metadata/" || return 1
    "$stage/python/bin/python3" -I -B - "$stage" <<'PY'
import csv, importlib.metadata, pathlib, stat, sys
root=pathlib.Path(sys.argv[1]); site=root/'python/lib/python3.12/site-packages'
dists=[d for d in importlib.metadata.distributions(path=[str(site)]) if d.metadata['Name'].lower()=='qbox']
if len(dists)!=1: raise ValueError('expected exactly one installed qbox distribution')
dist=dists[0]; script=root/'python/bin/qbox'
record=next(site/path for path in dist.files if str(path).endswith('.dist-info/RECORD'))
rows=list(csv.reader(record.open(newline='')))
# Remove just the generated entry point, never the package's recursive bin/qbox.
removed=[row for row in rows if row[0]=='../../../bin/qbox']
if len(removed)!=1 or script.is_symlink() or not script.is_file():
    raise ValueError('missing/ambiguous pip generated qbox entry')
script.unlink()
with record.open('w',newline='') as stream:
    csv.writer(stream).writerows(row for row in rows if row[0]!='../../../bin/qbox')
for path in (site/'qbox').rglob('*.py'):
    if path.is_symlink() or not path.is_file(): raise ValueError('unsafe helper')
    path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o333)
PY
}

write_installed_marker() {
    local root="$1" state="$2" digest="$3"
    "$root/python/bin/python3" -I -B - "$root" "$state" "$digest" "$release_id" "$manifest_sha256" <<'PY'
import json, os, pathlib, sys
root=pathlib.Path(sys.argv[1]); state,digest,rid,manifest_sha=sys.argv[2:]
path=root/'metadata/installed.json'; temporary=root/'metadata/.installed-new'
marker={'schema_version':1,'product':'qbox','release_id':rid,'manifest_sha256':manifest_sha,'state':state,'inventory_sha256':digest}
with temporary.open('x') as stream: json.dump(marker,stream,sort_keys=True);stream.write('\n')
os.replace(temporary,path)
PY
}

verify_release() (
    local root="$1" phase="$2" work report
    local -a bundle_args=()
    export QBOX_PYTHON="$root/python/bin/python3" _QBOX_OFFLINE_ROOT="$root"
    unset QBOX_TEST_MODE DISPLAY
    # Keep generated reports/cache/work outside the immutable release. Reuse is
    # read-only: a corrupt release must never be repaired or rewritten.
    work=$(mktemp -d -- "$lock/check.XXXXXXXX") || return 1
    trap 'rm -rf -- "$work"' EXIT
    export MPLCONFIGDIR="$work/matplotlib" XDG_CACHE_HOME="$work/cache"
    "$root/bin/qbox" --help > "$work/help" || { qbox_error '入口 --help 检查失败'; return 1; }
    "$root/bin/qbox" --version > "$work/version" || { qbox_error '入口 --version 检查失败'; return 1; }
    "$root/bin/qbox" --list > "$work/list" || { qbox_error '入口 --list 检查失败'; return 1; }
    "$root/python/bin/python3" -I -B "$root/metadata/checks/smoke.py" --release "$root" --work "$work/smoke" > "$work/smoke.json" || { cat -- "$work/smoke.json" >&2; qbox_error '科学功能自检失败'; return 1; }
    [[ "$phase" != prepared ]] || bundle_args=(--bundle "$bundle")
    "$root/python/bin/python3" -I -B "$root/metadata/checks/verify.py" --release "$root" --manifest "$root/metadata/manifest.json" --phase "$phase" "${bundle_args[@]}" > "$work/verify.json" || { cat -- "$work/verify.json" >&2; qbox_error '完整版本校验失败；请恢复原始版本或另选安装前缀'; return 1; }
    if [[ "$phase" != reuse ]]; then
        for report in "$root/metadata/verification-$phase.json" "$root/metadata/smoke.json"; do
            [[ ! -L "$report" && ( ! -e "$report" || -f "$report" ) ]] || return 1
        done
        cp -- "$work/verify.json" "$root/metadata/verification-$phase.json" || return 1
        cp -- "$work/smoke.json" "$root/metadata/smoke.json" || return 1
    fi
)

move_release() {
    [[ ! -e "$final" && ! -L "$final" ]] || { qbox_error '目标版本已存在，拒绝覆盖'; return 1; }
    # -n never replaces a concurrently created destination; verify it really moved.
    mv -Tn -- "$stage" "$final" || return 1
    [[ ! -e "$stage" && ! -L "$stage" && ! -L "$final" && "$(stat -c '%d:%i' -- "$final")" == "$stage_identity" ]] || return 1
}

prepare_bin_link() {
    check_bin_target || return 1
    create_owned_directories "$bin_dir" || return 1
    if [[ ! -e "$bin_dir/qbox" && ! -L "$bin_dir/qbox" ]]; then
        # Defer catchable signals until the visible link has its ownership record.
        # The bounded child commands ignore the same process-group signal, so ln
        # cannot be interrupted after creating a link but before reporting success.
        local pending_signal=0 link_status=0
        trap '(( pending_signal )) || pending_signal=130' INT
        trap '(( pending_signal )) || pending_signal=143' TERM
        if ( trap '' INT TERM; ln -sT -- "$prefix/current/bin/qbox" "$bin_dir/qbox" ); then
            bin_created=1
            bin_identity=$(trap '' INT TERM; stat -c '%d:%i' -- "$bin_dir/qbox") || link_status=1
        else
            link_status=1
        fi
        trap 'exit 130' INT
        trap 'exit 143' TERM
        (( pending_signal == 0 )) || exit "$pending_signal"
        (( link_status == 0 )) || { qbox_error '命令链接创建或归属记录失败'; return 1; }
    fi
}

publish_release() {
    local current
    lock_is_ours && validate_root_marker "$prefix" || return 1
    current=$(current_target) || return 1
    [[ "$current" == "$old_current" ]] || { qbox_error 'current 在事务期间发生变化，拒绝切换'; return 1; }
    [[ -L "$bin_dir/qbox" && "$(readlink -- "$bin_dir/qbox")" == "$prefix/current/bin/qbox" ]] || return 1
    current_temp="$prefix/.current.$token"
    [[ ! -e "$current_temp" && ! -L "$current_temp" ]] || return 1
    ln -s -- "releases/$release_id" "$current_temp" || return 1
    current_identity=$(stat -c '%d:%i' -- "$current_temp") || return 1
    mv -Tf -- "$current_temp" "$prefix/current" || return 1
    committed=1
}

owned_release_directory() {
    local candidate="$1" recorded resolved_current
    [[ -n "$stage_identity" && -d "$candidate" && ! -L "$candidate" && -O "$candidate" ]] || return 1
    [[ "$(readlink -m -- "$candidate")" == "$candidate" && "$(stat -c '%d:%i' -- "$candidate")" == "$stage_identity" ]] || return 1
    [[ -f "$lock/stage" && ! -L "$lock/stage" ]] || return 1
    recorded=$(printf '%s\n%s\n%s' "$token" "$stage" "$stage_identity")
    [[ "$(cat -- "$lock/stage")" == "$recorded" ]] || return 1
    if [[ "$candidate" == "$final" ]]; then
        [[ -f "$lock/final" && ! -L "$lock/final" && "$(cat -- "$lock/final")" == "$token $final" ]] || return 1
    else
        [[ "$candidate" == "$stage" ]] || return 1
    fi
    # Resolve current conservatively even when someone has changed its text.
    resolved_current=$(readlink -m -- "$prefix/current") || return 1
    ! path_within "$resolved_current" "$candidate"
}

cleanup_transaction() {
    local index path identity
    if lock_is_ours; then
        # A signal may arrive after rename completed but before the assignment.
        if [[ -n "$current_identity" && -L "$prefix/current" && "$(stat -c '%d:%i' -- "$prefix/current")" == "$current_identity" && "$(readlink -- "$prefix/current")" == "releases/$release_id" ]]; then
            committed=1
        fi
        if (( ! committed )); then
            if (( bin_created )) && [[ -L "$bin_dir/qbox" && "$(stat -c '%d:%i' -- "$bin_dir/qbox")" == "$bin_identity" && "$(readlink -- "$bin_dir/qbox")" == "$prefix/current/bin/qbox" ]]; then
                rm -- "$bin_dir/qbox" || :
            fi
            if [[ -n "$current_temp" && -L "$current_temp" && "$(stat -c '%d:%i' -- "$current_temp")" == "$current_identity" && "$(readlink -- "$current_temp")" == "releases/$release_id" ]]; then rm -- "$current_temp" || :; fi
            if owned_release_directory "$stage"; then rm -rf -- "$stage" || :; fi
            if [[ -n "$final" ]] && owned_release_directory "$final"; then rm -rf -- "$final" || :; fi
        else
            # A reuse transaction still has its own disposable extracted stage.
            if owned_release_directory "$stage"; then rm -rf -- "$stage" || :; fi
        fi
        rm -rf -- "$lock" || :
    fi
    # Only empty, same-inode directories created by this transaction are removed.
    if (( ! committed )); then
        for (( index=${#created_directories[@]}-1; index>=0; index-- )); do
            path="${created_directories[index]}"; identity="${created_identities[index]}"
            [[ -d "$path" && ! -L "$path" && "$(readlink -m -- "$path")" == "$path" && "$(stat -c '%d:%i' -- "$path")" == "$identity" ]] || continue
            if [[ "$path" == "$prefix" && "$root_created" == 1 ]] && validate_root_marker "$prefix"; then
                # Do not discard the root marker when a user added other content.
                if ( unset GLOBIGNORE; shopt -s dotglob nullglob; items=("$prefix"/*); (( ${#items[@]} == 1 )) && [[ "${items[0]}" == "$prefix/.qbox-root" ]] ); then
                    rm -- "$prefix/.qbox-root" || :
                fi
            fi
            rmdir -- "$path" 2>/dev/null || :
        done
    fi
    return 0
}

main() (
    # A subshell confines transaction variables, traps, and restrictive umask.
    umask 022
    local prefix bin_dir bundle stage='' final='' release_id='' manifest_sha256=''
    local lock='' lock_owned=0 lock_identity='' token transaction_pid="$BASHPID"
    local root_created=0 stage_identity='' committed=0 bin_created=0 bin_identity='' current_temp='' current_identity='' old_current=''
    local digest result
    local -a created_directories=() created_identities=()
    token="$transaction_pid.$RANDOM.$RANDOM"
    trap 'result=$?; trap - EXIT INT TERM; cleanup_transaction; exit "$result"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    parse_options "$@" || return 1
    preflight_platform || return 1
    preflight_paths || return 1
    prefix="$QBOX_PREFIX"; bin_dir="$QBOX_BIN_DIR"
    bundle=$(readlink -f -- "$_QBOX_INSTALLER_SOURCE") || return 1
    bundle="${bundle%/*}"
    verify_bundle_files "$bundle" || return 1
    acquire_install_lock || return 1
    old_current=$(current_target) || return 1
    check_bin_target || return 1
    stage=$(mktemp -d -- "$prefix/.stage.XXXXXXXX") || return 1
    record_stage || return 1
    extract_runtime "$bundle/runtime/python.tar.gz" "$stage" || return 1
    printf '%s\n%s\n' "$token" "$stage" > "$stage/.qbox-transaction" || return 1
    read_bundle_identity || return 1
    final="$prefix/releases/$release_id"
    if [[ -n "$old_current" ]]; then
        verify_release "$prefix/$old_current" reuse || return 1
    fi
    if [[ -e "$final" || -L "$final" ]]; then
        [[ -d "$final" && ! -L "$final" && -O "$final" ]] || { qbox_error '已有同名版本归属无效，拒绝覆盖'; return 1; }
        # Same release identity must also mean the exact delivered manifest bytes.
        [[ -f "$final/metadata/manifest.json" && ! -L "$final/metadata/manifest.json" ]] || return 1
        digest=$(sha256sum < "$final/metadata/manifest.json") || return 1
        [[ "${digest%% *}" == "$manifest_sha256" ]] || { qbox_error '同名版本 manifest 不一致，拒绝修补'; return 1; }
        if [[ "$prefix/$old_current" != "$final" ]]; then verify_release "$final" reuse || return 1; fi
    else
        install_wheels || { qbox_error '离线 wheel 安装失败'; return 1; }
        install_metadata || return 1
        write_installed_marker "$stage" prepared "$(printf '%064d' 0)" || return 1
        rm -- "$stage/.qbox-transaction" || return 1
        verify_release "$stage" prepared || return 1
        digest=$(sha256sum < "$stage/metadata/installed-files.json") || return 1
        write_installed_marker "$stage" prepared "${digest%% *}" || return 1
        printf '%s %s\n' "$token" "$final" > "$lock/final" || return 1
        move_release || return 1
        verify_release "$final" final || return 1
        write_installed_marker "$final" verified "${digest%% *}" || return 1
    fi
    prepare_bin_link || return 1
    publish_release || return 1
    # No required operation after the commit may relabel a successful install.
    printf 'qbox 安装完成：%s\n命令入口：%s/qbox\n' "$final" "$bin_dir" || :
    return 0
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
