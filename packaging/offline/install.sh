#!/usr/bin/env bash
# Source-safe bootstrap primitives. Transactional installation is added by Task 8.

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

main() {
    parse_options "$@" && preflight_platform && preflight_paths || return 1
    qbox_error '事务安装入口尚未接入，未执行安装'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
