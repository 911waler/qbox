# qbox 离线安装包

本包包含 qbox、独立 CPython 3.12 运行时和 analysis / structure 的完整锁定依赖。
目标是 Linux x86_64、glibc 2.28+、Bash 4.4+，另需 GNU coreutils、grep、sed、
系统 awk、tar、gzip 和可写、允许执行的用户临时目录。安装无需 sudo、网络、系统
Python、pip、编译器或 Conda。五系统与基础 CPU 的实际验收状态以包外、同 SHA 的
验收记录为准；只有门禁通过才有 release-ready.json，不承诺未来系统版本。

## 校验和安装

将 tar.gz 和配套 .sha256 放在同一个空目录，先核对发布渠道给出的 SHA，再执行：

```bash
sha256sum -c qbox-0.1.0-linux-x86_64-offline.tar.gz.sha256
mkdir unpacked
tar -xzf qbox-0.1.0-linux-x86_64-offline.tar.gz -C unpacked
cd unpacked
bash install.sh
export PATH="$HOME/.local/bin:$PATH"
qbox --help
qbox --list
```

默认安装根目录为 `$HOME/.local/share/qbox`，命令为 `$HOME/.local/bin/qbox`。
自定义目录必须是绝对路径，支持空格：

```bash
bash install.sh --prefix "$HOME/Local Apps/qbox" --bin-dir "$HOME/local commands"
export PATH="$HOME/local commands:$PATH"
qbox --version
```

可将对应 PATH 设置加入自己的 shell 配置；安装器不会修改配置文件。
不要把包内 Python 的 bin 或原生库目录全局加入 PATH / LD_LIBRARY_PATH。
离线入口固定使用私有运行时；如设置了不同的 QBOX_PYTHON 会明确报错，请先
`unset QBOX_PYTHON`。源码入口和普通 wheel 安装仍遵循原 QBOX_PYTHON /
QBOX_SHARED_ROOT 契约。私有运行时不用于执行外部计算程序。

QE、MPI、Multiwfn、unfold.x 和赝势由用户独立提供，不包含在本包中。可通过
PATH 和 QBOX_MULTIWFN_HOME、QBOX_PSEUDO_ROOT、QBOX_QE_ENV_SCRIPT、
QBOX_ONEAPI_ENV_SCRIPT 显式配置；仅当设置时加载环境脚本。
安装目录可以只读；计算结果写工作目录，缓存使用可写的 XDG_CACHE_HOME 或
用户缓存/临时目录。不要将计算结果放入 releases 目录。
为保证基础 x86_64，科学库采用 GENERIC BLAS 构建，可能显著慢于针对本机向量
指令优化的 BLAS；本包优先兼容性，不承诺与优化环境相同性能。

## 完整自检及离线故障诊断

```bash
prefix="$HOME/.local/share/qbox"
release=$(readlink -f -- "$prefix/current")
"$release/python/bin/python3" -I -B "$release/metadata/checks/verify.py" \
  --release "$release" --manifest "$release/metadata/manifest.json" --phase reuse
work=$(mktemp -d)
env -u DISPLAY "$release/python/bin/python3" -I -B "$release/metadata/checks/smoke.py" \
  --release "$release" --work "$work/smoke"
```

校验失败时保留日志，核对外层 SHA、解压目录 SHA256SUMS、磁盘空间、目录所有者、
临时目录执行权限和文件系统 noexec 选项。不要在线补装依赖来掩盖损坏；重新取得
同一经校验的完整包或使用另一个空前缀。manifest.json 绑定载荷和构建提交，
THIRD_PARTY_LICENSES 包含许可及所需对应源码。历史静态审计不是最终 CPU 实测。

## 保留旧版与手工回退

安装新版本会保留旧 releases；current 的原子替换是提交点。不要删除正在使用的
版本。回退必须先检查根标记/版本归属，持安装锁，完整校验和 smoke 通过后才替换
current。以下脚本在自己的沙箱验证过；修改 prefix 和 release_id 为实际路径/版本：

```bash
set -euo pipefail
prefix=$(readlink -m -- "$HOME/.local/share/qbox")
release_id='填写 releases 中保留的完整版本名'
[[ $release_id != */* && $release_id != . && $release_id != .. ]]
[[ -d $prefix && ! -L $prefix && -O $prefix ]]
[[ -f $prefix/.qbox-root && ! -L $prefix/.qbox-root && -O $prefix/.qbox-root ]]
expected=$(printf 'schema_version=1\nuid=%s\nprefix=%s\n' "$EUID" "$prefix" | sha256sum)
actual=$(sha256sum < "$prefix/.qbox-root")
[[ ${expected%% *} == "${actual%% *}" ]]
[[ -d $prefix/releases && ! -L $prefix/releases && -O $prefix/releases ]]
release="$prefix/releases/$release_id"
[[ -d $release && ! -L $release && -O $release ]]
[[ -f $release/metadata/installed.json && ! -L $release/metadata/installed.json ]]
release_identity=$(stat -c '%d:%i' -- "$release")
installed_identity=$(stat -c '%d:%i' -- "$release/metadata/installed.json")
root_id=$(stat -c '%d:%i' -- "$prefix")
marker_id=$(stat -c '%d:%i' -- "$prefix/.qbox-root")
releases_id=$(stat -c '%d:%i' -- "$prefix/releases")
lock="$prefix/.install-lock"
mkdir -- "$lock"   # 失败即停止，绝不抢占现有锁
lock_id=$(stat -c '%d:%i' -- "$lock")
lock_token="manual-rollback $$ $lock_id"
printf '%s\n' "$lock_token" > "$lock/owner"
link="$prefix/.rollback.$$"
link_owned=0
current_id=''
current_value=''
root_owned() {
  [[ -d $prefix && ! -L $prefix && -O $prefix && $(stat -c '%d:%i' -- "$prefix") == "$root_id" &&
     -f $prefix/.qbox-root && ! -L $prefix/.qbox-root && -O $prefix/.qbox-root &&
     $(stat -c '%d:%i' -- "$prefix/.qbox-root") == "$marker_id" &&
     -d $prefix/releases && ! -L $prefix/releases && -O $prefix/releases &&
     $(stat -c '%d:%i' -- "$prefix/releases") == "$releases_id" &&
     -d $release && ! -L $release && -O $release &&
     $(stat -c '%d:%i' -- "$release") == "$release_identity" &&
     -f $release/metadata/installed.json && ! -L $release/metadata && ! -L $release/metadata/installed.json &&
     $(stat -c '%d:%i' -- "$release/metadata/installed.json") == "$installed_identity" ]] || return 1
  actual=$(sha256sum < "$prefix/.qbox-root")
  [[ ${expected%% *} == "${actual%% *}" ]]
}
lock_held() {
  root_owned && [[ -d $lock && ! -L $lock && -O $lock &&
    $(stat -c '%d:%i' -- "$lock") == "$lock_id" &&
    -f $lock/owner && ! -L $lock/owner && -O $lock/owner &&
    $(cat -- "$lock/owner") == "$lock_token" ]]
}
managed_current() {
  [[ -L $prefix/current && -O $prefix/current ]] || return 1
  local target name
  target=$(readlink -- "$prefix/current")
  name=${target#releases/}
  [[ $target == releases/* && -n $name && $name != */* && $name != . && $name != .. &&
     -d $prefix/releases/$name && ! -L $prefix/releases/$name && -O $prefix/releases/$name &&
     -f $prefix/releases/$name/metadata/installed.json &&
     ! -L $prefix/releases/$name/metadata && ! -L $prefix/releases/$name/metadata/installed.json &&
     -O $prefix/releases/$name/metadata/installed.json ]]
}
link_id=''
cleanup() {
  if root_owned && (( link_owned )) && [[ -L $link && $(stat -c '%d:%i' -- "$link") == "$link_id" && $(readlink -- "$link") == "releases/$release_id" ]]; then
    rm -- "$link"
  fi
  if lock_held; then
    rm -- "$lock/owner"
    rmdir -- "$lock"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
lock_held
managed_current
current_id=$(stat -c '%d:%i' -- "$prefix/current")
current_value=$(readlink -- "$prefix/current")
"$release/python/bin/python3" -I -B "$release/metadata/checks/verify.py" \
  --release "$release" --manifest "$release/metadata/manifest.json" --phase reuse
work=$(mktemp -d)
env -u DISPLAY "$release/python/bin/python3" -I -B "$release/metadata/checks/smoke.py" \
  --release "$release" --work "$work/smoke"
ln -sT -- "releases/$release_id" "$link"
link_id=$(stat -c '%d:%i' -- "$link")
link_owned=1
# 验证期间可能失去归属；紧邻提交点再次核对，不覆盖变化后的对象。
lock_held
managed_current
[[ $(stat -c '%d:%i' -- "$prefix/current") == "$current_id" &&
   $(readlink -- "$prefix/current") == "$current_value" &&
   -L $link && $(stat -c '%d:%i' -- "$link") == "$link_id" &&
   $(readlink -- "$link") == "releases/$release_id" ]]
mv -Tf -- "$link" "$prefix/current"
```

自检与回退 smoke 仅在该进程中清除 DISPLAY，适用于图形登录会话。
同一用户的恶意并发进程不属于安全隔离承诺；若发现对象归属变化则停止，并保留无法证明归属的残留。
在记录临时链接归属之前中断，可能保守地留下本次 `.rollback.*`；不要删除未经核验的同名路径。
SIGKILL 或断电可能留下 `.install-lock`、`.stage.*`、`.current.*`。先阅读锁内
owner，核实 PID/进程组已结束、目录所有者、根标记、current 和版本标记，并验证
当前版本完整性后，再由管理员人工处理确定属于该次失败事务的残留。PID 可能复用；
不能仅凭 `kill -0` 失败或文件年龄判断安全。产品不会自动偷锁。

## 卸载

先退出 qbox 和使用该版本的所有作业，将 prefix、bin_dir 设为实际安装路径，
按上节检查 prefix 根标记并取得安装锁。
核对命令确为符号链接且 `readlink "$bin_dir/qbox"` **精确等于**
`"$prefix/current/bin/qbox"` 后，只删除这一个链接：

```bash
: "${prefix:?请先核验安装根目录并取得锁}" "${bin_dir:?请设置实际命令目录}"
[[ -L "$bin_dir/qbox" && $(readlink -- "$bin_dir/qbox") == "$prefix/current/bin/qbox" ]] &&
  rm -- "$bin_dir/qbox"
```

保留安装根目录可以稍后恢复。若要释放空间，在锁内人工逐项核验 releases 中每个
版本的 marker/完整性及目录所有者，仅删除已核验的 qbox 版本，再清理 current、
根标记和自己取得的锁，最后用 rmdir 删除空根目录。不要递归删除未经归属核验的
目录；用户计算数据、缓存和共享工具不属于卸载范围。

## 维护者资料

正式用户交付形式为这个 tar.gz，验证容器和 VM 仅用于维护者。
构建流程为 resolve → 审阅固定锁并显式获取材料 → audit → audit-promote → 两次本地 build → matrix → gate。
构建只接受干净提交和完整固定缓存，不下载材料。产品、锁、安装器、自检或本 README
改变后需重建并重新验收最终包。包外报告可晚于构建提交，但不能改写包的 source_commit。
原始审计全部材料均保留；LicenseRef-qbox-supplemental-audited-material 是聚合索引，
不代表统一许可或新的许可判定。详细配方在仓库 docs/releases/offline-build.md。
