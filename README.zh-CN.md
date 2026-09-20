# qbox

[English](README.md) | [简体中文](README.zh-CN.md)

qbox 是一个用于准备、运行和后处理 Quantum ESPRESSO 工作流的命令行工具包，支持常见的 SCF、结构弛豫、NSCF、能带、PDOS、声子、分子动力学和收敛性扫描任务。

## 安装（推荐）

同一 `qbox-<版本>-linux-installer.tar.gz` 支持个人与管理员安装。预先准备 Python 3.10+
（含 venv/pip）、Bash 4.4+，首次安装需联网下载科学依赖。用随包 `.sha256` 校验归档，
解压并进入安装包目录后执行：

```bash
# 普通账号；默认入口 $HOME/.local/share/qbox/bin/qbox
bash install.sh --user

# 自定义总目录；入口随之为 $HOME/software/qbox/bin/qbox
bash install.sh --user --prefix "$HOME/software/qbox" --python /absolute/path/to/python3

# 管理员；默认入口 /opt/qbox/bin/qbox
sudo bash install.sh --system
```

必须明确选择 `--user` 或 `--system`。安装器创建固定路径的专用 venv，安装包内 qbox
wheel 和 analysis / structure 科学依赖，验证后发布 `<prefix>/bin/qbox`。
按输出设置一次 PATH 后，新终端可直接运行 qbox，无需激活 Python；使用
`command -v qbox` 检查命令选择。管理员还会获得 `/etc/profile.d/` 配置示例。
不会自动修改 shell 文件；请保留 venv 及底层 Python，不要在安装后移动它们。

高级选项 `--bin-dir PATH` 可分离命令目录；已有无关入口不会被覆盖。
自行维护 Python 环境时，安装本地 wheel 后仍可使用原来的
`python -m qbox.install --bin-dir PATH`。两种模式、Python 准备、PATH、检查、升级及
核对归属后卸载的方法见[安装指南](docs/installation.md)和
[随包指南](packaging/lightweight/README.zh-CN.md)。安装器不替换系统 Python、不执行
apt/dnf。SHA256 是完整性检查，不是签名认证。

QE、MPI、Multiwfn、unfold.x 和赝势需单独准备。源码仓库的
[独立 Multiwfn 下载材料](third_party/Multiwfn/README.md)提供原始 ZIP、许可证及校验值。
单独下载解压后设置 `QBOX_MULTIWFN_HOME`；它不进入任何 qbox 安装归档、wheel 或 sdist，
也不会自动安装。

## 完整离线包（可选）

断网且没有适用 Python 环境时，可选用
`qbox-0.1.0-linux-x86_64-offline.tar.gz` 及 SHA256 文件。
它包含私有 CPython 3.12 和固定科学依赖，因此体积明显更大；仍不包含 Multiwfn。
安装、回滚和卸载见[离线指南](packaging/offline/README.zh-CN.md)，平台验收范围见
[实际验收记录](docs/releases/offline-validation.md)。这些记录只适用于所记录的
离线归档，不代表任意外部 Python 环境已经通过相同验收。

## 源码安装与构建

在完整仓库根目录、已激活的 Python 环境中执行：

```bash
python -m pip install '.[analysis,structure]'
python -m qbox.install
```

维护者构建 wheel 和统一轻量安装包：

```bash
python -m pip wheel --no-deps . -w dist/lightweight
python tools/build-lightweight-installer.py --wheel dist/lightweight/qbox-0.1.0-py3-none-any.whl --output dist/lightweight
```

构建器从 wheel 元数据读取版本，输出确定性归档及 `.sha256`；同名已有产物内容不同时拒绝覆盖。
analysis / structure extras 分别选择分析和结构处理依赖。
普通安装保留 `QBOX_PYTHON` / `QBOX_SHARED_ROOT` 配置；离线安装固定使用私有解释器。

## 配置

qbox 会从 `PATH` 中查找标准命令行工具。只有在需要显式指定安装位置时，才需要设置以下配置变量：

```bash
export QBOX_SHARED_ROOT=/path/to/shared-dependencies
export QBOX_PYTHON=/path/to/python3
export QBOX_MULTIWFN_HOME=/path/to/multiwfn
export QBOX_PSEUDO_ROOT=/path/to/pseudopotentials
export QBOX_QE_ENV_SCRIPT=/path/to/qe-environment.sh
export QBOX_ONEAPI_ENV_SCRIPT=/path/to/compiler-mpi-environment.sh
```

`QBOX_QE_ENV_SCRIPT` 和 `QBOX_ONEAPI_ENV_SCRIPT` 是可选项。只有设置了相应变量时，qbox 才会加载环境脚本。

未设置 `QBOX_PYTHON` 或 `QBOX_MULTIWFN_HOME` 时，qbox 会分别从共享根目录下的 `python/bin/python3` 和 `multiwfn` 推导默认路径。显式设置的依赖路径始终优先。

## 使用方法

下列示例使用安装后的 `qbox` 命令；在源码仓库中运行时改用 `./qbox`。

查看可用的命令行选项：

```bash
qbox --help
```

启动交互式工作流菜单：

```bash
qbox
```

直接运行可用的工作流操作：

```bash
qbox ACTION [INPUT ...]
```

使用 `qbox --version` 查看版本号。

列出任务编号和可读名称，或明确指定一个任务：

```bash
qbox --list
qbox --task scf sample.cif
qbox --task 11 sample.cif
```

原有 0–37 编号、交互菜单、旧参数位置和 PW 快捷选项（例如 `qbox sample.cif 00`）
保持兼容。使用 `--task` 后，其余参数视为输入路径，不再解释为旧编号或快捷选项，
避免数字文件名与任务编号混淆；任务仍可能询问自身所需的参数。安装后也可通过
`python -m qbox` 启动。

## 模块布局与开发

- `qbox`：源码启动器，同时兼容 Bash `source` 调用。
- `src/qbox/cli.py`、`registry.py`：入口参数和统一任务注册表。
- `src/qbox/io/`：结构转换、QE 输入解析、准备和校验。
- `src/qbox/postprocess/`：能带、态密度、光学、有效质量及 unfolding 算法。
- `src/qbox/legacy/`：按领域拆分的 Bash 兼容工作流，保留 QE/MPI 执行、文件事务及交互。

Python 算法可安全导入，并提供 `main(argv=None)` 入口。这是渐进式迁移：计算流程
编排目前仍使用 Bash，尚不是全 Python 重写。新增算法应放入 Python 模块，不再嵌入
主文件。详细边界及后续迁移原则见[架构说明](docs/architecture.md)。

使用包含科学计算依赖的 Python 运行回归测试：

```bash
QBOX_PYTHON=/path/to/python3 bash tests/run.sh
```

测试通过固定样例验证输出、菜单、任务分发、失败传播、清理和 Python 模块行为，
不运行生产 QE 计算。
构建 wheel 后，可在具备分析依赖的环境中执行
`python tools/verify-wheel.py dist/qbox-0.1.0-py3-none-any.whl`，验证独立临时目录安装。

## 引用

如果 qbox 对你的工作有所帮助，请使用 [`CITATION.cff`](CITATION.cff) 引用本软件。

维护者：waler。

## 许可证

qbox 采用 MIT 许可证发布，详见 [`LICENSE`](LICENSE)。

单独提供的 Multiwfn 下载材料遵循其原始许可证，不属于 qbox 的 MIT 授权范围。
