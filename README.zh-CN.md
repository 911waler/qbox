# qbox

[English](README.md) | [简体中文](README.zh-CN.md)

qbox 是一个用于准备、运行和后处理 Quantum ESPRESSO 工作流的命令行工具包，支持常见的 SCF、结构弛豫、NSCF、能带、PDOS、声子、分子动力学和收敛性扫描任务。

## 环境要求

- Bash 4 或更高版本
- 用于执行计算工作流的 Quantum ESPRESSO
- Python 3.10 或更高版本（入口也需要 Python）；分析功能另需科学计算依赖
- 需要 Multiwfn 的分析工作流需安装 Multiwfn

## 安装

可在完整源码目录中直接运行 `./qbox`，也可安装到独立 Python 环境：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install '.[analysis,structure]'
qbox --help
```

`pip install .` 仅安装轻量入口，不安装科学计算依赖。`analysis` 扩展包含 NumPy、
Matplotlib、SciPy、seekpath；`structure` 扩展包含 pymatgen、ASE。QE、MPI、Multiwfn
及赝势仍需单独配置。请使用自己管理的 Python 环境，不要直接修改共享系统环境。

离线分发可用 `python -m pip wheel --no-deps . -w dist` 构建 wheel，再在目标环境中
安装该本地文件。wheel 包含 Python 模块、Bash 工作流资源、兼容入口及 MIT 许可证；
依赖需预先安装或另行提供。模块化后，仅复制根目录的 `qbox` 文件不再构成完整安装。

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

查看可用的命令行选项：

```bash
./qbox --help
```

启动交互式工作流菜单：

```bash
./qbox
```

直接运行可用的工作流操作：

```bash
./qbox ACTION [INPUT ...]
```

使用 `./qbox --version` 查看版本号。

列出任务编号和可读名称，或明确指定一个任务：

```bash
./qbox --list
./qbox --task scf sample.cif
./qbox --task 11 sample.cif
```

原有 0–37 编号、交互菜单、旧参数位置和 PW 快捷选项（例如 `./qbox sample.cif 00`）
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
