# qbox 个人 / 管理员轻量安装包

同一 `qbox-<版本>-linux-installer.tar.gz` 支持个人和管理员安装。包内仅含 qbox
wheel、安装器、许可证及校验清单，不包含 Python、科学依赖 wheelhouse、第三方源码
材料或 Multiwfn。需要 Linux、Bash 4.4+、预先安装的 Python 3.10+（含 venv、pip /
ensurepip 支持）和首次下载科学依赖的网络。安装器不执行 apt/dnf、不替换系统 Python。

## 校验与解压

从可信渠道取得归档和 `.sha256`，在下载目录运行（替换实际版本）：

```bash
sha256sum -c qbox-0.1.0-linux-installer.tar.gz.sha256
tar -xzf qbox-0.1.0-linux-installer.tar.gz
cd qbox-0.1.0-linux-installer
bash install.sh --help
```

SHA256 用于发现损坏或意外改动，不是数字签名，也不能证明来源可信。安装器还会核验
解压目录的精确文件清单与所有文件 SHA256；请勿在包内添加其他文件。
`--help` 不需要可用 Python，也不创建文件。

## 个人安装

以普通账号运行，必须明确选择 `--user` 或 `--system`。root 不可运行 `--user`。

```bash
bash install.sh --user
```

默认总目录是 `$HOME/.local/share/qbox`，命令为 `$HOME/.local/share/qbox/bin/qbox`。
自定义目录时，只需指定 prefix；入口随之变为 `<prefix>/bin/qbox`：

```bash
bash install.sh --user \
  --prefix "$HOME/software/qbox" \
  --python /absolute/path/to/python3
```

`--python` 默认使用 PATH 中的 python3；需要时显式选择 Python 3.10+。路径支持空格和
中文。虚拟环境固定创建在 `<prefix>/venv`，不能在安装后移动，也不能删除底层 Python。
默认联网安装 analysis（NumPy、Matplotlib、SciPy、seekpath）和 structure（pymatgen、ASE）
依赖。qbox 本体只从包内 wheel 安装，不使用 PyPI 同名项目替代；依赖由 pip 解析，
不保证与完整离线包版本相同。代理、证书及 pip 源配置可沿用；目标目录等配置由安装器控制。

安装成功后按实际输出设置 PATH，例如：

```bash
export PATH="$HOME/software/qbox/bin:$PATH"
hash -r
command -v qbox
qbox --help
qbox --list
```

把实际输出的 `export PATH=...` 行加入一次自己的 shell 配置（交互 Bash 通常是
`~/.bashrc`），以后新终端可以直接运行 qbox，无需激活环境。安装器输出经过 shell
引用的路径，不自动修改配置文件。别名或 PATH 中更靠前的同名命令会影响选择。
固定入口覆盖旧 `QBOX_PYTHON` 值，同时保留任务调用 QE/MPI 所需的用户环境。

## 管理员安装

需有效 UID 0；程序、环境与入口由 root 管理。解释器及所有父目录必须可供普通用户
遍历 / 执行，且不得通过普通用户可写目录承载启动链。普通用户不能写共享安装目录。

```bash
sudo bash install.sh --system
# 默认 /opt/qbox，入口 /opt/qbox/bin/qbox

sudo bash install.sh --system \
  --prefix /opt/lab/apps/qbox \
  --python /usr/bin/python3.11
```

系统安装同样不默认在 `/usr/local/bin` 建入口。管理员可在 root shell 中为登录用户设置
统一 PATH。先检查是否已有 `/etc/profile.d/qbox.sh`；以下 noclobber 示例拒绝覆盖已有文件：

```bash
( set -C; printf '%s\n' 'export PATH=/opt/lab/apps/qbox/bin:"$PATH"' > /etc/profile.d/qbox.sh ) &&
  chmod 0644 /etc/profile.d/qbox.sh
```

安装器会按真实 bin-dir 输出对应示例，含空格和引号的目录也会正确引用。新用户和已有
用户下次登录时采用；非登录 shell / 批处理任务可直接使用入口绝对路径，例如
`/opt/lab/apps/qbox/bin/qbox --help`。计算输出写入用户的工作目录；缓存由各用户管理，
不写入共享程序目录，不依赖 root 的 HOME。QE/MPI 模块仍由用户按工作流需要加载。

## 分离命令目录与已有环境

仅当需要独立的命令目录时使用 `--bin-dir`；不论参数顺序，显式值都覆盖 `<prefix>/bin`：

```bash
bash install.sh --user --prefix "$HOME/software/qbox" --bin-dir "$HOME/bin"
```

已有同名文件、目录或符号链接不会被覆盖。完整离线安装不由此安装器接管。
自行维护 Python 环境时，仍可安装本地 wheel 后运行 `python -m qbox.install --bin-dir ...`；
该命令只创建绑定当前 Python 的入口，不创建或管理本指南的完整环境。

## 验证、重跑与失败恢复

安装器在发布入口前验证 Python、路径、权限、pip 依赖、导入、帮助、任务列表和真实
CIF 转换。完成后 `<prefix>/.qbox-install.json` 记录归属、wheel SHA、环境版本和入口 SHA。
使用相同参数重新运行只复核完全匹配的 ready 安装；不会再次联网安装依赖。
不同版本、Python、目录配置或损坏的环境要求新 prefix / bin-dir。

下载失败、中断或其他错误会返回非零，保留已存在的命令。新建但未完成的环境和 preparing
记录保留，并明确报告位置；不要自动接管或盲删。并发安装使用锁；不要移除仍在使用的锁。
核对错误与保留文件后，通常使用新目录重试最清楚。SIGKILL / 断电残留需人工核查。

## 升级与卸载

升级先安装到新的专用 prefix（如 `$HOME/software/qbox-next`），使用默认的新 `prefix/bin`
或另一个 bin-dir，运行绝对路径的 `qbox --help`、`qbox --list` 和实际工作流。确认后更新
PATH / profile.d 指向新入口，并用 `command -v qbox` 核对。保留旧目录以便回退；不要移动
venv 或原地覆盖旧入口。若复用旧的独立 bin-dir，须先按下述归属核验流程处理旧入口。

卸载前，用原包和原参数重跑验证，并检查 `<prefix>/.qbox-install.json` 的 mode、uid、
prefix、bin_dir、venv_python、state 和 wheel_sha256 与该安装一致。检查入口是本安装
的普通文件而非链接，拥有者是安装账号，且 `sha256sum <bin-dir>/qbox` 与记录的
entry_sha256 完全一致；核对其绑定的 Python 是 `<prefix>/venv/bin/python`。
若任何信息不符，停止并调查，不删除该入口。

确认后，**先移除已确认的 `<bin-dir>/qbox` 入口，再删除该安装专用 prefix 目录**。
删除目录前检查其中没有另存的计算文件或其他用户数据，不删除共享 bin-dir 或 prefix 的
父目录。管理员安装由管理员处理。本文不提供对未核验路径直接执行的递归删除命令。
最后移除自己添加的对应 PATH 配置。用户计算数据、缓存、QE/MPI 和单独的 Multiwfn 保留。

## 外部程序与验收范围

QE、MPI、赝势、unfold.x 和 Multiwfn 单独准备。Multiwfn 可从源码仓库的
`third_party/Multiwfn/` 下载原始 ZIP，解压后设置 `QBOX_MULTIWFN_HOME`；不在本归档、
wheel 或 sdist 内，也不会自动安装。完整离线归档是另一产品；其平台验收结论不适用于
本轻量归档。具体 Ubuntu / Rocky 与 Python 组合以对应轻量版实际验收记录为准。
