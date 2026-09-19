# qbox

[English](README.md) | [简体中文](README.zh-CN.md)

qbox 是一个用于准备、运行和后处理 Quantum ESPRESSO 工作流的命令行工具包，支持常见的 SCF、结构弛豫、NSCF、能带、PDOS、声子、分子动力学和收敛性扫描任务。

## 正式离线安装

正式用户交付形式是完整的 `qbox-0.1.0-linux-x86_64-offline.tar.gz` 及 SHA256 文件。
包内包含独立 CPython 3.12 和所有科学 Python 运行依赖。要求 x86_64 Linux、
glibc 2.28+、Bash 4.4+、GNU coreutils、grep、sed、系统 awk、tar、gzip。
无需系统 Python、编译器、sudo 或网络；QE、MPI、Multiwfn、unfold.x 和赝势需自行提供。

```bash
sha256sum -c qbox-0.1.0-linux-x86_64-offline.tar.gz.sha256
mkdir unpacked
tar -xzf qbox-0.1.0-linux-x86_64-offline.tar.gz -C unpacked
bash unpacked/install.sh
export PATH="$HOME/.local/bin:$PATH"
qbox --help
```

自定义空格路径、只读安装、自检、遗留锁、手工回退及卸载详见
[随包指南](packaging/offline/README.zh-CN.md)。平台支持仅以
[实际验收记录](docs/releases/offline-validation.md)为准。
基础 CPU 兼容采用 GENERIC BLAS，性能可能低于本机优化环境。

## 源码与 wheel 开发模式

完整源码或普通 wheel 使用开发者自行管理的 Python 3.10+ 环境；可用
`python -m pip wheel --no-deps . -w dist` 构建本地 wheel，依赖另行准备。
analysis / structure extras 选择科学依赖；单个 wheel 不是完整离线包。
源码/wheel 模式保留 QBOX_PYTHON / QBOX_SHARED_ROOT 契约；离线模式固定使用
私有解释器并拒绝冲突 QBOX_PYTHON。不要将私有 Python/库路径全局加入环境变量。

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
