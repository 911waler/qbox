# qbox

[English](README.md) | [简体中文](README.zh-CN.md)

qbox 是一个用于准备、运行和后处理 Quantum ESPRESSO 工作流的命令行工具包，支持常见的 SCF、结构弛豫、NSCF、能带、PDOS、声子、分子动力学和收敛性扫描任务。

## 环境要求

- Bash 4 或更高版本
- 用于执行计算工作流的 Quantum ESPRESSO
- 用于绘图和分析功能的 Python 3
- 需要 Multiwfn 的分析工作流需安装 Multiwfn

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

## 引用

如果 qbox 对你的工作有所帮助，请使用 [`CITATION.cff`](CITATION.cff) 引用本软件。

维护者：waler。

## 许可证

qbox 采用 MIT 许可证发布，详见 [`LICENSE`](LICENSE)。
