# qbox 轻量安装指南

默认交付普通 wheel，使用用户提供的 Python 环境。qbox 主程序和辅助脚本在包内；
Python、科学依赖、QE、MPI、Multiwfn、unfold.x 和赝势均单独准备。
本指南使用 Bash；不要求安装 qbox 时拥有管理员权限。

## 1. 准备 Python

要求 Python 3.10 或以上。已有合适的 Conda/虚拟环境时可以直接使用，跳到下一节。
以下系统包命令由有权限的用户执行；不要替换系统 Python 或修改 `/usr/bin/python3`。

Ubuntu 22.04 / 24.04：

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
python3 --version
python3 -m venv "$HOME/.venvs/qbox"
```

Rocky Linux 8 / 9（已更新且启用提供 Python 3.11 的 AppStream 仓库）：

```bash
sudo dnf install python3.11 python3.11-pip
python3.11 --version
python3.11 -m venv "$HOME/.venvs/qbox"
```

Ubuntu 20.04 的默认 Python 3.8，以及 Rocky 的默认旧 Python，不能直接满足要求。
若系统仓库没有上述包，可使用管理员提供的 Python 3.10+，或已安装的 Conda：

```bash
conda create -n qbox python=3.12 pip
conda activate qbox
```

venv 用户激活环境：

```bash
source "$HOME/.venvs/qbox/bin/activate"
```

Conda 用户保持 `conda activate qbox` 即可，不执行 venv 的激活命令。
系统基础工具还包括 Bash 4.4+、GNU coreutils、awk、sed、grep、find、tar、gzip；
具体计算任务另需对应的 QE/MPI 等程序。Multiwfn ZIP 的解压需要 `unzip`。

参考：[Ubuntu Python 环境指南](https://ubuntu.com/developers/docs/howto/python-setup/)、
[Rocky Python 3.11 软件包公告](https://errata.rockylinux.org/RLSA-2026%3A10774)。
这些命令是安装准备说明，不等同于对每种系统与科学依赖版本组合的兼容认证。

## 2. 安装 qbox 和科学依赖

下载 qbox wheel 后，在该文件所在目录、已激活的环境中执行：

```bash
python -m pip install './qbox-0.1.0-py3-none-any.whl[analysis,structure]'
```

`analysis` 包含 NumPy、Matplotlib、SciPy、seekpath；`structure` 包含 pymatgen、ASE。
pip 会联网解析并获取与当前 Python 兼容的依赖；此模式没有沿用完整离线版的固定依赖锁。
如果只需要入口帮助和任务列表，可不加 extras；实际分析/结构任务仍需要相应依赖。
不要直接执行 `pip install qbox` 来替代本地文件安装，本文没有假设同名 PyPI 项目是本项目。

从仓库或解压后的 qbox 源码发行包安装时，在含 `pyproject.toml` 的根目录执行：

```bash
python -m pip install '.[analysis,structure]'
```

如依赖均已由用户准备，才使用 `--no-deps`，然后执行下面的完整检查。
不要使用 `sudo pip` 把这些依赖装入系统 Python。

## 3. 安装固定启动命令（只需一次）

安装 wheel 或源码包后，在同一个 Python 环境执行：

```bash
python -m qbox.install
```

默认创建 `~/.local/bin/qbox`，固定使用执行这一步的 Python 环境，包括科学依赖。
启动时会在 qbox 子进程中设置 `QBOX_PYTHON`，覆盖旧值及共享目录推导的解释器；
不会激活环境、全局注入虚拟环境 PATH，或更改 QE/MPI 的库路径。
已有文件、目录或符号链接会报冲突；相同环境生成的同一启动器可重复安装。
不要直接覆盖完整离线版的命令；保留它或使用 `--bin-dir "$HOME/bin"` 等另一目录。

venv 用户现在可以执行 `deactivate`；Conda 用户执行 `conda deactivate`。
对当前终端设置一次 PATH：

```bash
export PATH="$HOME/.local/bin:$PATH"
hash -r
command -v qbox
qbox --help
```

若 `~/.bashrc` 尚未设置该 PATH，把上述 export 行加入一次，新开交互式 Bash 终端
即可直接运行 `qbox`。其他 shell 使用对应配置文件。安装命令只打印说明，不自动改写配置。
`command -v qbox` 应显示刚创建的命令；仍激活的环境、别名或其他同名命令可能影响选择。
集群作业脚本通常不读取 `~/.bashrc`，可直接调用 `"$HOME/.local/bin/qbox"`。

请勿移动或删除所绑定的 Python 环境。原地升级 qbox 不需重新生成启动器；更换环境时，
检查旧 `~/.local/bin/qbox` 确实是此启动器后自行移除，再用新环境运行 `python -m qbox.install`。
缺失解释器时启动器会给出修复提示。

## 4. 检查依赖与工作流环境

下面的 Python 检查使用安装时的环境（激活它，或使用其 Python 绝对路径）：

```bash
python -c 'import sys; assert sys.version_info >= (3, 10); import numpy, scipy, matplotlib, seekpath, ase; from pymatgen.core import Structure; print("Python / scientific dependencies OK")'
python -m pip check
qbox --version
qbox --help
qbox --list
```

以上检查不启动 QE/MPI 计算。固定命令不需要激活 Python；使用 Lmod 管理 QE/MPI 时，
仍按任务需要在终端或作业脚本中加载对应模块。qbox 不提供 QE、赝势或 MPI 的自动安装。

## 5. 单独安装 Multiwfn（按需）

源码仓库中提供 `third_party/Multiwfn/Multiwfn_3.8_dev_bin_Linux.zip`、校验值及说明。
见[独立下载说明](../third_party/Multiwfn/README.md)。它不在 wheel 或 sdist 内；
若你拿到的是发行包，请到源码仓库单独下载该目录中的文件，或访问
[Multiwfn 官方下载页](http://sobereva.com/multiwfn/download.html)。

解压完成后设置实际目录：

```bash
export QBOX_MULTIWFN_HOME="$HOME/.local/opt/Multiwfn_3.8_dev_bin_Linux"
test -x "$QBOX_MULTIWFN_HOME/Multiwfn"
```

只在使用 Multiwfn 相关工作流时需要它。其许可证和论文引用要求由原作者规定，
不适用 qbox 的 MIT 许可证。qbox 安装过程不会执行或安装这个压缩包。

## 升级、卸载和离线使用

升级时激活同一环境，再用 `python -m pip install --upgrade './新文件名.whl[analysis,structure]'`
安装实际下载的新 wheel。卸载使用该环境的 `python -m pip uninstall qbox`，再检查并移除
自己创建的固定启动器（默认 `~/.local/bin/qbox`）；不要删除其他安装提供的同名命令。
科学依赖和手动安装的 Multiwfn 会保留。用户计算文件不受影响。

完全断网并且没有预先准备 Python/依赖的机器，可以选择完整离线发行包。
其指南在完整源码仓库的 `packaging/offline/README.zh-CN.md`；已验收离线包的记录
在 `docs/releases/offline-validation.md`。轻量包不会携带私有运行时和第三方源码审计归档。

## 维护者构建

在独立的构建环境中安装构建工具，然后从仓库根目录执行：

```bash
python -m pip install build
python -m build --outdir dist/lightweight
```

这会生成 wheel 和 sdist。`MANIFEST.in` 排除 `third_party/`，wheel 仅打包 `src/qbox/`
中的程序资源。完整 Git 仓库（及 GitHub 仓库源码快照）会包含可选 Multiwfn 压缩包；
它们不同于上述轻量 sdist。更新 Multiwfn 时须保留原始 ZIP、许可证、来源说明与 SHA-256。
