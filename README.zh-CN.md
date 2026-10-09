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

从源码目录运行 `./qbox` 时，也可在该目录的 `.qbox-local.sh` 中保存并 `export`
本机配置。此文件被 Git 忽略，不打入安装包；启动脚本会在进入主菜单或 `--task`
之前读取它。建议用 `export QBOX_PSEUDO_ROOT="${QBOX_PSEUDO_ROOT:-/path/to/pseudopotentials}"`
的写法，让命令行已指定的配置优先。直接 `python -m qbox` 或 `source qbox` 不读取此文件。

可以在启动 qbox 前自行 `module load` 所需 QE 版本。自动计算开始前，qbox 只检查该流程所需的命令和动态库；当前环境满足要求时，沿用当前 QE/MPI，不调用 module，也不加载配置的环境脚本。仅生成输入文件不会触发环境加载。

`QBOX_QE_ENV_SCRIPT` 和 `QBOX_ONEAPI_ENV_SCRIPT` 是可选的补充环境。仅在当前环境不足时，qbox 才尝试配置的 QE 脚本、module 选择和编译器/MPI 脚本。`QE_MODULE` 可指定缺少环境时要加载的模块，不会覆盖已满足要求的环境。

需要 `pw.x` 的流程仍检查 QE 版本严格大于 7.0。直接版本探测最多等待 5 秒，并清理探测进程；若未取得版本，使用当前环境的 `mpirun -np 1` 再探测一次，同样最多等待 5 秒，以兼容无法直接启动的 MPI 构建。取得版本后按该版本检查；两次均无法取得版本时停止计算，保留当前环境。

自动计算先确认 QE 运行环境（需要加载时先选择 CPU/GPU module），再输入并行数量。CPU 模式在输入前显示机器在线物理核心总数，以及最近 0.25 秒采样估算的空闲物理核心数；超线程的同核逻辑 CPU 不重复计数。空闲估算按每个核心最忙的逻辑 CPU 折算剩余容量并向下取整。

GPU 模式只显示当前机器 GPU 数量和空闲 GPU 数量，使用有超时限制的 `nvidia-smi` 查询；无计算进程、采样利用率为零且允许计算的 GPU 计为空闲。这里统计驱动可见的物理设备，不是 CUDA 核心数或调度器分配额度。资源信息随负载变化，仅供参考；无法读取时显示“未知”。显示模式依据实际使用的 QE 程序和已加载 module 判断，保留用户预加载环境，不受尚未使用的 `QE_MODULE` 备用配置影响。输入值仍是传给 `mpirun -np` 的 MPI 进程数。全部计算步骤已完成且选择跳过时，不再加载环境或询问并行数量。

自动能带计算的 SCF、`pw.x` bands 和 `bands.x` 三步均从项目目录运行，使输入中的相对 `outdir` 路径指向同一份 SCF 保存数据。能带输入、日志、数据和图像仍放在 `BAND/` 中。

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
qbox --task 12 sample.cif
```

编号 0–10 保持不变，新增 11 为 Wannier90 输入生成，原 11–37 顺延为 12–38。
命名任务、旧参数位置和 PW 快捷选项（例如 `qbox sample.cif 00`）保持兼容。
数字脚本请按[编号迁移表](docs/releases/wannier-inputs.md)更新。使用 `--task` 后，其余参数视为输入路径，不再解释为旧编号或快捷选项，
避免数字文件名与任务编号混淆；任务仍可能询问自身所需的参数。安装后也可通过
`python -m qbox` 启动。

## Wannier90 输入生成

```bash
qbox --task wannier-input sample.cif
qbox --task wannier-input sample.scf.in
qbox --task wannier-input --config settings.json --conflict cancel
qbox kmesh 4 4 2 --format qe
```

先选择六类计算方向，再进入参数菜单编辑项目、来源与运行目录、名称与版本、网格、
能带与投影、能窗和专用参数。切换方向保留公共设置并替换任务开关。
目标为 Wannier90 3.1.0；完成检查与文件预览后写入当前目录。同名输入统一备份、改名或取消。
生成不启动 QE/Wannier90 计算；运行顺序与数据完整性提示写入随包 README。
可直接从 CIF 开始：选择方向后，优先读取当前目录中结构匹配的已有 SCF 输入；
找不到时才进入 QE 参数菜单生成 SCF 输入，再设置 Wannier 参数，无需预先完成 SCF 计算。
新生成的 SCF 输入也保存在当前目录，同名时须换名或取消。
详见[使用与迁移说明](docs/releases/wannier-inputs.md)。

## 声子计算

执行计算分组新增 **40) 声子计算**（`phonons`）。子菜单目前提供声子谱计算：

```bash
qbox --task phonons model.cif
qbox --task phonons model.scf.in
```

流程复用已有输入向导，依次执行 SCF → `ph.x` → `q2r.x` → `matdyn.x` → 声子谱绘图。
CIF 缺少配套 SCF 输入时进入 SCF 生成向导，生成后继续声子设置。
SCF 和 PH 分别设置 MPI 进程数；q2r 和 matdyn 使用串行执行。
所有阶段运行在当前项目的 `PHONON/` 子目录，目录内包含：

```text
PHONON/
├── <前缀>.scf.in、.ph.in、.q2r.in、.matdyn.in、.path.json
├── scf.out、ph.out、q2r.out、matdyn.out、plot.out
├── tmp/、<前缀>.dyn*、<前缀>.fc*、<前缀>.freq、<前缀>.freq.gp
└── <前缀>_phonon.png、<前缀>_phonon.svg
```

原始 SCF 不被修改：工作副本将 scratch 路径移入 `PHONON/`，赝势仍指向原来源解析的目录。
再次进入可复用已有输入并跳过有效完成的阶段，或选择全部重算。流程状态记录输入及必要
产物的变化；上游变化会使后续阶段失效。任何计算或绘图阶段失败均返回非零状态，并停止
尚未执行的下游阶段。Gamma 单点频率、IR 和 Raman 暂不提供执行入口。

开发验收可在加载 QE/MPI 环境后运行 `tools/verify-phonon-native.py --pseudo /path/to/Si.UPF`。
该脚本通过真实 qbox 入口从空目录测试完整链、续算和输入修改后的重新计算；小网格和低
截断能仅用于验证流程，不作为物性收敛参数。脚本不需要 Codex 或网络服务。
增加 `--from-cif` 可从只有 CIF 的长路径目录开始，额外覆盖真实 Multiwfn 转换及 SCF
输入向导；此模式还需配置好 Multiwfn。

## 声子谱绘图

主菜单绘图分组中的 **39) 绘制 QE 声子谱图** 会扫描当前目录全部 `*.freq.gp`，
分别输出 `<前缀>_phonon.png` 和 `<前缀>_phonon.svg`。也可指定一个文件：

```bash
qbox --task plot-phonons
qbox --task plot-phonons sic.freq.gp
```

自动识别时优先使用匹配的 `.path.json`；手动指定的配套文件会覆盖自动识别结果。
没有可用 JSON 时，尝试关联 `matdyn.in` 的路径端点、
各段点数及行尾 `! Γ`、`! X` 等标签。输入文件的 `flfrq` 必须指向对应数据，
展开后的点数也必须吻合。断开的路径分别绘制；负频率保留，纵轴为 cm⁻¹。
只有 `.freq.gp` 也可以绘图，此时使用数值横轴，不凭曲线猜测高对称点名称。

新生成的 MATDYN 输入在高对称点坐标行尾写入标签，并用 `qbox:path-v1` 注释
记录分段边界和 Γ 保护点。因此，即使没有 JSON，配套输入也能恢复标签、分段和
需要排除的保护点；这些注释不改变 QE 的数值输入。旧输入不会被自动改写。
标签按采样行号映射到 `.freq.gp` 的横坐标，配套 `.freq` 用于核验 q 点与频率。
同一 Γ 点可能对应不同方向的极限，不能按重复 q 坐标去重。

交互菜单可指定其他路径文件，或按原始数据行号手动设置标签和断点（空行、注释不计数）。
手动设置替代自动路径设置；断点编号表示新线段的第一行。例如：

```bash
python -m qbox.postprocess.phonon_plot -i sic.freq.gp --ticks '1:Γ,21:X,22:M,42:Γ' --breaks 22
```

该 Python 模块支持 `--directory` 批量绘图以及 `--matdyn` / `--path` 指定配套文件，
也兼容已有的 `.freq + .path.json` 用法。批量任务中某个文件无效时，其他文件继续绘制，
最终返回非零状态并汇总失败数。

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
