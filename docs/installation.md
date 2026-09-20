# qbox 安装指南

推荐使用同一 `qbox-<版本>-linux-installer.tar.gz` 完成个人或管理员安装，入口默认位于
`<prefix>/bin/qbox`。包内包含 qbox wheel、安装器、MIT 许可证和 SHA256 清单；Python、
科学依赖、QE、MPI、Multiwfn、unfold.x 与赝势单独准备。完整操作与恢复边界见
[随包中文指南](../packaging/lightweight/README.zh-CN.md)。

## 准备 Python 与系统工具

要求 Python 3.10+，含 venv、pip / ensurepip 支持；Linux 工作流还需 Bash 4.4+、
GNU coreutils、awk、sed、grep、find、tar、gzip。首次安装联网获取 analysis / structure
科学依赖。已有适用 Python 可以直接使用，无需预先激活环境。不要替换系统 Python，
不要修改 `/usr/bin/python3`。安装器不会执行系统包管理命令。

以下准备命令由有权限的用户自行执行，系统包可用性取决于启用的仓库。

Ubuntu 22.04 / 24.04：

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
python3 --version
```

Rocky Linux 8 / 9（已更新且启用提供 Python 3.11 的 AppStream 仓库）：

```bash
sudo dnf install python3.11 python3.11-pip
python3.11 --version
```

Ubuntu 20.04 默认 Python 3.8 和部分 Rocky 默认旧 Python 不满足要求；显式传入适用的
`--python /usr/bin/python3.11`，或使用管理员提供的其他 Python 3.10+。个人安装也可用
已有 Conda 的 Python；系统安装的解释器及父目录必须由 root 管理、普通用户可遍历执行
且不可写，不宜指向管理员的私有 HOME 或用户可写环境。基础 Python 必须长期保留。

参考：[Ubuntu Python 环境指南](https://ubuntu.com/developers/docs/howto/python-setup/)、
[Rocky Python 3.11 软件包公告](https://errata.rockylinux.org/RLSA-2026%3A10774)。
这些准备说明不代表任意系统 / Python / 科学依赖版本组合均已验收。完整离线包的
[历史验收记录](releases/offline-validation.md)只适用于该记录标识的归档。

## 下载校验与两种安装模式

在可信来源的归档及 `.sha256` 所在目录执行（替换实际版本）：

```bash
sha256sum -c qbox-0.1.0-linux-installer.tar.gz.sha256
tar -xzf qbox-0.1.0-linux-installer.tar.gz
cd qbox-0.1.0-linux-installer
bash install.sh --help

# 普通账号：默认 $HOME/.local/share/qbox/bin/qbox
bash install.sh --user

# 普通账号自定义总目录：入口 $HOME/software/qbox/bin/qbox
bash install.sh --user --prefix "$HOME/software/qbox" --python /absolute/path/to/python3
```

选择一个适合自己的命令执行；无需把几个示例都安装一遍。`--user` 和 `--system` 互斥且
必须明确选择；root 不能运行 `--user`。SHA256 检测完整性，不是来源签名。
安装器在创建 prefix 前检查精确包内文件清单及 wheel 哈希；不要向解压目录添加文件。

管理员示例：

```bash
# 默认入口 /opt/qbox/bin/qbox
sudo bash install.sh --system

# 自定义总目录，入口 /opt/lab/apps/qbox/bin/qbox
sudo bash install.sh --system --prefix /opt/lab/apps/qbox --python /usr/bin/python3.11
```

系统安装要求有效 UID 0。专用目录、环境和入口由 root 管理，其他用户只读与执行。
安装器不递归改变既有共享父目录的权限；计算输出和缓存仍属于每个执行用户。
两种模式均在最终 `<prefix>/venv` 创建虚拟环境，不在创建后移动它。

高级用途可以显式分离命令目录：

```bash
bash install.sh --user --prefix "$HOME/software/qbox" --bin-dir "$HOME/bin"
```

默认 bin-dir 在解析最终 prefix 后确定；显式 `--bin-dir` 与参数顺序无关。
已有无关文件、目录或符号链接不会被覆盖；不接管旧完整离线安装。

qbox 只来自包内 wheel，不假设 PyPI 同名 qbox 是本项目。pip 获取 analysis（NumPy、
Matplotlib、SciPy、seekpath）和 structure（pymatgen、ASE），解析与当前 Python 兼容的
版本；本轻量包不沿用完整离线版的固定依赖锁。网络代理、证书与 pip 源配置可沿用，
安装目标等写入位置由安装器控制。帮助无需 Python；实际安装需要 Python 3.10+ 和 venv。

## PATH、登录与批处理

默认不会在 `~/.local/bin` 或 `/usr/local/bin` 另建命令。按实际安装器输出添加一次 PATH，
例如个人自定义 prefix：

```bash
export PATH="$HOME/software/qbox/bin:$PATH"
hash -r
command -v qbox
qbox --help
qbox --list
```

新终端无需激活 Python。把输出的 shell-quote 后 PATH 行加入自己的 shell 配置；
交互 Bash 通常读取 `~/.bashrc`。检查已有别名或 PATH 中更靠前的同名 qbox。
固定入口覆盖旧 `QBOX_PYTHON`，并保留 QE/MPI 工作流所需的调用者环境。

管理员可在 root shell 中使用安装器输出的 `/etc/profile.d/` 示例，先检查已有文件。
以下示例拒绝覆盖已有文件；仅成功创建后才设置权限：

```bash
( set -C; printf '%s\n' 'export PATH=/opt/lab/apps/qbox/bin:"$PATH"' > /etc/profile.d/qbox.sh ) &&
  chmod 0644 /etc/profile.d/qbox.sh
```

普通用户下次登录采用此路径。非登录 shell / 集群作业不一定读取这些配置，可直接调用
`/opt/lab/apps/qbox/bin/qbox`。用 Lmod 的工作流仍需加载适用的 QE/MPI 模块。
安装器仅打印这些示例，不自动改写任何 shell 文件。

## 验证、失败恢复和升级卸载

发布入口前安装器会进行 pip check、科学模块导入、qbox 帮助 / 列表及真实 CIF 转换。
可另外用固定入口和该环境检查：

```bash
"$HOME/software/qbox/bin/qbox" --version
"$HOME/software/qbox/venv/bin/python" -m pip check
```

同一包、相同参数重跑会验证完全匹配的 ready 安装，不重新安装依赖。版本、Python、
目录配置或已安装内容改变时，不破坏旧环境，要求新 prefix / bin-dir。
失败与中断返回非零，报告保留目录；preparing 记录、未完成环境或残留锁需人工检查，
不能盲目接管或删除。不要移除仍活动的锁。旧命令与历史环境不会自动删除。

升级安装到新 prefix，用新入口验证实际工作流，再修改 PATH / profile.d 并检查
`command -v qbox`。保留旧安装以便回退；不要移动 venv。卸载前按
[随包指南的归属核验流程](../packaging/lightweight/README.zh-CN.md#升级与卸载)
检查安装记录、所有者、入口 SHA256 和绑定 Python。**先移除已确认的入口，再删除该
安装专用目录**；先确认其中没有另存计算文件，不删除共享 bin-dir 或父目录。
记录或 SHA 不符时停止删除。管理员安装由管理员处理。用户数据和独立 Multiwfn 保留。

## 已有自行管理的 Python 环境

独立 wheel / sdist 继续提供。在已有 Python 3.10+ 环境中，安装实际下载的本地 wheel：

```bash
python -m pip install './qbox-0.1.0-py3-none-any.whl[analysis,structure]'
python -m qbox.install --bin-dir "$HOME/.local/bin"
```

`python -m qbox.install` 默认 `~/.local/bin/qbox`，仅创建绑定当前 Python 的固定入口，
不创建完整托管环境。退出 venv / Conda 后仍可直接运行；设置对应 bin-dir 的 PATH。
相同环境的相同启动器可重复安装，其他同名入口报冲突。不要覆盖旧完整离线命令。
此自行管理方式的升级与依赖由使用者负责；可在该环境中运行 `python -m pip uninstall qbox`
卸载本体，再核实并移除自己的固定入口。不要删除其他安装的同名命令。

源码或 sdist 安装从含 `pyproject.toml` 的根目录运行：

```bash
python -m pip install '.[analysis,structure]'
python -m qbox.install
```

不要用 sudo pip 写入系统 Python。仅入口帮助和任务列表可省略 extras；实际科学任务需
安装相应依赖。只有依赖均已准备时才使用 `--no-deps`，并自行执行完整依赖检查。

## Multiwfn 与完整离线包

Multiwfn 的原始 ZIP、许可证及校验值仅作为
[源码仓库独立下载材料](../third_party/Multiwfn/README.md)提供，不在 qbox 安装归档、
wheel 或 sdist 内。也可访问 [Multiwfn 官方下载页](http://sobereva.com/multiwfn/download.html)。
单独解压后设置实际路径：

```bash
export QBOX_MULTIWFN_HOME="$HOME/.local/opt/Multiwfn_3.8_dev_bin_Linux"
test -x "$QBOX_MULTIWFN_HOME/Multiwfn"
```

其许可证和论文引用要求由原作者规定。qbox 安装过程不会执行或安装该 ZIP。
完全断网且没有 Python / 依赖时，可选择另行分发的完整离线归档，详见
[完整离线指南](../packaging/offline/README.zh-CN.md)。

## 维护者构建

在独立构建环境、仓库根目录运行：

```bash
python -m pip install build
python -m build --outdir dist/lightweight
python tools/build-lightweight-installer.py \
  --wheel dist/lightweight/qbox-0.1.0-py3-none-any.whl \
  --output dist/lightweight
```

构建器从 wheel METADATA 核验项目名与版本，输出 `qbox-<版本>-linux-installer.tar.gz`
及 `.tar.gz.sha256`。显式允许列表仅包含安装器、指南、LICENSE 和一个本地 wheel；
固定顺序、mtime、权限和 gzip 时间戳，同名产物内容不同则拒绝覆盖。SHA256 不提供签名认证。
wheel / sdist 继续独立分发；源码仓库快照中的可选 Multiwfn 文件不同于轻量发行包内容。
