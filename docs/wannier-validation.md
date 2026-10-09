# Wannier 输入的本机验证记录

验证日期：2026-10-08。本机 `module load qe/cpu/7.5` 提供 Quantum ESPRESSO **7.5**、
Wannier90 / postw90 **3.1.0**；Wannier90 版本通过 `--version` 实测。

本次已完成从真实 QE SCF、完整网格 NSCF、`pw2wannier90` 接口导出、Wannier 化到六方向
**19 个子项目的实际运行**，并完成同一实际 k 点列表上的 QE / Wannier 能带比较。
这扩大了早期官方配套数据 smoke test 的覆盖范围，但不代表物性收敛或正式发布。

## 本次真实 QE 计算与报告

所有本次计算集中在独立目录：

```text
/media/waler/4TB/Calculation/qe/qe-test/wannier90-all-directions-validation-20261008
```

下文将其简称为 `ROOT`。本机证据包括
[19 项运行报告](/media/waler/4TB/Calculation/qe/qe-test/wannier90-all-directions-validation-20261008/fresh-validation.json)、
[模型误差报告](/media/waler/4TB/Calculation/qe/qe-test/wannier90-all-directions-validation-20261008/model-quality.json)，
以及 `models/<模型>/` 中的 `config.json`、`provenance.json`、`run-events.jsonl`、输入和程序日志。
各任务目录的 `case-config.json` 记录实际参数与测试场景。

| 新算模型 | QE 与 Wannier 模型设置 | 已验证范围 |
| --- | --- | --- |
| Si scalar，`models/si-scalar-6x6x6` | 2 原子；PD04-PBE NC 赝势；`ecutwfc=60 Ry`；6×6×6 完整网格；12 条 QE 带 → 8 个 Wannier 轨道；`Si:sp3` | SCF、NSCF、接口、Wannier 化、电子结构 / 局域模型 / 输运任务及逐点能带对照 |
| Si collinear，`models/si-collinear` | `nspin=2`、零初始磁化；2×2×2 网格；每通道 12 条 QE 带 → 8 个 Wannier 轨道 | 实际 up/down 接口与 Wannier 化、轨道 cube、中心、模型和插值能带；两通道结果一致，验证通道拆分，未测试磁性材料 |
| Te spinor，`models/te-spinor` | 3 原子手性晶胞；真正全相对论 NC 赝势 `Te.rel-pbe-n-nc.UPF`（`relativistic=full`、`has_so=T`）；`noncolin` / `lspinorb` 均为 true；`ecutwfc=40 Ry`；4×4×4 网格；36 条 QE 带 → 24 个 Wannier 轨道；`Te:s;p` | SCF、NSCF、spinor 接口与 Wannier 化、spn / uHu / UNK 导出、spinor cube、逐点能带对照及 Berry / 光学 / 旋光任务 |

模型配置与赝势 SHA-256 可分别在
[Si 配置](/media/waler/4TB/Calculation/qe/qe-test/wannier90-all-directions-validation-20261008/models/si-scalar-6x6x6/config.json)、
[Si 来源](/media/waler/4TB/Calculation/qe/qe-test/wannier90-all-directions-validation-20261008/models/si-scalar-6x6x6/provenance.json)、
[共线配置](/media/waler/4TB/Calculation/qe/qe-test/wannier90-all-directions-validation-20261008/models/si-collinear/config.json)、
[共线来源](/media/waler/4TB/Calculation/qe/qe-test/wannier90-all-directions-validation-20261008/models/si-collinear/provenance.json)、
[Te 配置](/media/waler/4TB/Calculation/qe/qe-test/wannier90-all-directions-validation-20261008/models/te-spinor/config.json)、
[Te 来源](/media/waler/4TB/Calculation/qe/qe-test/wannier90-all-directions-validation-20261008/models/te-spinor/provenance.json) 中核对。
Si 6×6×6 和 Te 最终模型均根据实算 `.eig` 选择冻结能窗，并使用
`num_iter=1000`、`dis_num_iter=1000` 重新生成模型和 checkpoint；未混用旧模型 checkpoint。

`fresh-validation.json` 的 19 项均为 `passed: true`：

| 方向 | 实际运行子项目 | 模型与主要输出 |
| --- | --- | --- |
| 精细电子结构（5） | `bands`、`qe_bands`、`dos`、`projected_dos`、`fermi_surface` | Si；band.dat、QE bands.dat、DOS、BXSF |
| 局域轨道与模型（3） | `orbitals`、`centres`、`model` | Si；cube、centres.xyz、hr.dat |
| 热电与电子输运（1） | `boltzmann` | Si；Seebeck、电导率及热输运系数 K |
| Berry 曲率与霍尔响应（4） | `berry_path`、`berry_slice`、`ahc`、`shc` | Te SOC；路径 / 切片曲率、AHC 日志、SHC 扫描 |
| 光学与非线性响应（2） | `optical`、`shift_current` | Te SOC；Kubo、JDOS、位移电流张量 |
| 轨道磁性与旋光（4） | `orbital_magnetization`、`natural_optical_activity`、`current_induced_optical`、`current_induced_magnetization` | Te SOC；轨道磁化、NOA 的轨道 / 自旋项、C / tildeD、K 的轨道 / 自旋项 |

19 个任务使用本次新算模型，再经已有结果模式生成各自的任务输入。Si 费米面采用刚性能带电子掺杂
`μ = QE 采样 CBM + 0.2 eV`；BoltzWann 采用 `CBM + 0.05…0.55 eV`、300–600 K 和显式测试假设
`τ=10 fs`。Te 电流诱导响应采用 `μ = QE 采样占据带最高值 − 0.1 eV` 的刚性能带空穴掺杂。
这些情景不表示本征 Si 有费米面，也不对应实测掺杂浓度或散射时间。

## 实际 k 点上的模型误差

QE 对照重新使用实际 `seed_band.kpt` 点列；Si 比较 93 个点，Te 比较 175 个点。
每点按本征值升序配对，**不施加能量平移，也不使用最近能带匹配来缩小误差**。
以下数值来自 `ROOT/model-quality.json`；每模型目录另有 `qe-wannier-errors.csv`。

| 模型与比较范围 | 平均绝对误差（MAE） | 最大绝对误差 |
| --- | --- | --- |
| Si 6×6×6：4 条价带 | **5.918 meV** | **45.231 meV** |
| Si 6×6×6：全部 8 条 Wannier 带 | **0.155866 eV** | **1.083061 eV** |
| Te SOC：18 条占据带 | **8.251 meV** | **71.351 meV** |
| Te SOC：全部 24 条 Wannier 带 | 17.149 meV | 140.479 meV |

Si 价带误差明显小于全 8 带误差，高导带仍有约 1.08 eV 的最大偏差，不能以价带结果代表全部
导带、光学或输运精度。Te 占据带对照也不证明响应函数、未占据带或材料物性已经收敛。
报告同时保留先前 Si 模型的误差；最终 Si 结果以 `si-scalar-6x6x6` 条目为准。

## 本次实际运行促成的修复

- 已有 `.win` 能窗的 Fortran `D` / `d` 指数在检查 `.eig` 窗内带数时可正确解析，原输入文本保留。
- 新增 `wannier_plot_radius`（Å，默认 3.5，须为正数）。cube 是否覆盖最终 Wannier 中心及所需
  FFT 点不能在生成输入时保证；可增大 `wannier_plot_supercell`、减小半径或改用 XSF。
  本次最终 Si / Te cube 使用 4×4×4 超胞和 3.5 Å 半径成功导出；生成器默认仍为 2×2×2，
  不将本次成功设置视为所有晶胞的通用解。依据见
  [3.1.0 默认参数](https://github.com/wannier-developers/wannier90/blob/v3.1.0/src/parameters.F90) 与
  [cube 覆盖检查](https://github.com/wannier-developers/wannier90/blob/v3.1.0/src/plot.F90)。
- 新建模型支持顶层 `num_iter` / `dis_num_iter` 正整数配置和菜单编辑；省略时保留原生默认值，
  共线 up/down 共享设置。已有模式导入并锁定原值，不把迭代参数当成可替换的任务参数。
  增加最大迭代次数本身不等于完成收敛判定，仍须检查 `.wout` 的实际迭代变化。
- BoltzWann 的 `*_kappa.dat` 是二阶能量矩得到的热输运系数 **K**，不能直接称为开路电子热导率。
  在一致的张量和单位约定下，`κ_e = K − T Sᵀ σ S`；不含晶格热导率。
  依据见 [3.1.0 BoltzWann 实现](https://github.com/wannier-developers/wannier90/blob/v3.1.0/src/postw90/boltzwann.F90)。

## CIF 入口回归（2026-10-08 补充）

使用用户 `test/relax.cif` 的临时副本（Si₄C₄、8 原子），通过实际终端执行
`qbox relax.cif` → 主菜单 11 → 计算方向 → QE SCF 参数菜单 → Wannier 参数菜单，
生成当前目录下的 SCF、NSCF、win、pw2wan、配置记录与 README。没有启动 QE 计算。
生成的 `.win` 通过本机 Wannier90 3.1.0 的 `-pp`，得到 `.nnkp` 且无 `.werr`。

核对结果：原 CIF 内容和原子顺序不变；晶胞长度、角度一致，周期坐标转换的最大
位置差为 `5.53×10⁻⁷ Å`；SCF 与 NSCF 结构一致；配置及输入不引用已清理的暂存路径。
另通过显式任务入口验证未设置 `QBOX_PSEUDO_ROOT` 时输入库目录，及已有 SCF 的
改名发布，原 SCF 的 SHA-256 与首次生成记录一致。
这些检查验证输入转换与预处理，不替代该 SiC 模型的实际计算和收敛检验。
此次修复后的完整回归为 **288 项 Shell 检查、186 项 Python 测试通过**；
本机日志位于 `/tmp/qbox-cif-bridge-regression.log`。

后续修复源码启动入口未继承安装版本机配置的问题：源码根的 `.qbox-local.sh`
加载与本机安装入口一致的赝势/Multiwfn 默认值，显式环境变量仍优先。
在没有额外导出环境变量的实际终端中，主菜单 11→方向 1 直接进入 SCF 参数菜单，
不再询问赝势总目录；与主菜单 0 生成的 SCF 核对，实际赝势目录、截断能和结构一致。
本次入口修复后 **188 项 Python 测试通过**，发布入口约束检查通过；日志为
`/tmp/qbox-shared-config-python.log`、`/tmp/qbox-shared-config-release.log`。

已有 SCF 复用回归：在用户的实际 `test/` 目录运行 `qbox relax.cif` → 11 → 1，
直接读取 `relax.scf.in` 并进入 Wannier 参数菜单，未启动 SCF 向导或重新发布输入。
这份历史输入的空 `pseudo_dir` 已单独按本机配置补齐，原文备份为
`relax.scf.in.before-pseudo-fix.bak`；`ecutwfc=35`、`ecutrho=450` 等设置保持不变。
另在没有 SCF 输入的临时目录验证仍会进入 QE 参数菜单，取消后仅保留原 CIF。
指定的三条过程说明已删除。最终 Wannier 相关回归日志为
`/tmp/qbox-existing-scf-wannier-final.log`。

## 早期官方数据 smoke test（历史记录）

下列检查先于上述真实 QE 计算完成，使用官方已有 checkpoint / 矩阵；其覆盖仍保留，
不与本次重新计算的 Si / Te 模型混为同一数据来源。

| 检查 | 数据与检查方式 | 结果 |
| --- | --- | --- |
| 19 个子项目完整输入包 | 经 `build_bundle` 生成 `.win`，立方晶胞、2×2×2 网格；逐个执行 `wannier90.x -pp` | 全部生成 `.nnkp`，无 `.werr` |
| DOS / 轨道投影 DOS | 官方 Cu checkpoint 和本征值，生成的 DOS 参数 | postw90 正常完成 |
| Seebeck / 电导率 / 热输运系数 K | 官方 Si 配套数据，生成的 BoltzWann 参数 | postw90 正常完成 |
| Berry 路径 / 切片 / AHC / 复光电导 / 轨道磁化 | 官方 Fe 配套 checkpoint、重叠和所需 uHu | 各模块正常完成 |
| SHC | 官方 Pt spinor 配套 checkpoint 和 spn，3.1.0 原生 Qiao 路径 | postw90 正常完成 |
| 位移电流 | 官方 GaAs 配套数据，生成的 `sc_eta` / `sc_phase_conv` 参数 | postw90 正常完成 |
| NOA / 电流诱导旋光 / 电流诱导磁化 | 官方 Te 配套数据，分别生成 `-noa`、`-dw-c`、`-k-c` | 三类均正常完成 |
| 轨道图和中心 | 官方 GaAs 格式化 UNK 与重叠，实际 Wannier 化 | cube、xsf 和 centres.xyz 均生成 |
| 紧束缚模型、插值能带、费米面 | 官方 Te 配套 checkpoint / 本征值，以 `restart=plot` 运行 | hr.dat、band.kpt、bxsf 均生成 |
| 路径 | SeeK-path 原晶胞接口，交换轴、非标准晶胞、路径断点与实际 band.kpt | Python 测试通过 |

早期还验证了 wheel 在源码目录外安装及生成输入。完成本次实际计算相关修复后的最新全回归为
**288 项 Bash 检查及 162 项 Python 测试通过**，日志见
[本机完整回归日志](/media/waler/4TB/Calculation/qe/qe-test/wannier90-all-directions-validation-20261008/validation-logs/source-regression.log)。测试命令见下文。
原晶胞接口测试使用本机可选科学环境中的 SeeK-path；
普通文本生成与网格功能不依赖它。

不只检查进程退出码：Wannier90 某些输入错误会返回 0，且仅写入 `.wout` / `.wpout`。
预处理确认 `.nnkp`；实际 Wannier / postw90 运行确认日志中的 `All done:` 和预期输出文件；
QE 运行同时检查 `JOB DONE.` 及错误标志。

## 可复现方式

早期 smoke test 脚本位于 [`tools/verify-wannier-native.py`](../tools/verify-wannier-native.py)。只执行 Wannier90
和 postw90 小体系检查，不启动 QE 或 MPI 生产计算。脚本在新建的临时目录中复制官方数据，
不改动源数据；每次运行保留输入、程序日志和 `report.json`。

它不会复现上述真实 QE SCF / NSCF。真实计算应按 `ROOT/models/<模型>/config.json` 和
`scf.in` 在新目录中重建，并按 SCF → 完整网格 NSCF → `wannier90 -pp` → `pw2wannier90` →
Wannier 化 → postw90 顺序运行。模型及任务目录的 `run-events.jsonl` 保留本次实际命令。
对照 QE bands 应在所有接口导出完成后运行，并使用实际 `seed_band.kpt`；不得在网格 NSCF
与接口导出之间插入会覆盖相同 `prefix/outdir` 波函数的计算。

无官方测试数据时，smoke test 脚本仍可检查全部 19 个输入包：

```bash
module load qe/cpu/7.5
qetoolkit-python tools/verify-wannier-native.py
```

完整检查所用数据来自 [Wannier90 官方 v3.1.0 源码归档](https://github.com/wannier-developers/wannier90/archive/refs/tags/v3.1.0.tar.gz)，
其中 `test-suite/tests` 与 `test-suite/checkpoints` 必须保持相对目录和符号链接。
不将这些数据或大型计算输出加入本项目。

在已解压的 `wannier90-3.1.0` 源码树中，使用官方 `w90chk2chk` 工具将可移植文本 checkpoint
转为本机二进制格式。本次使用已有 gfortran、BLAS 和 LAPACK，在 `/tmp` 源码树中设置：

```makefile
F90 = gfortran
FCOPTS = -O0 -fallow-argument-mismatch
LDOPTS = -fallow-argument-mismatch
LIBS = -llapack -lblas
```

将以上保存为该源码树的 `make.inc`，然后在源码树运行 `make -j2 w90chk2chk`。
回到本项目后运行（用实际的解压路径替换示例）：

```bash
module load qe/cpu/7.5
qetoolkit-python tools/verify-wannier-native.py \
  --data-root /tmp/qbox-w90-fixtures/wannier90-3.1.0
```

可通过 `--wannier90`、`--postw90`、`--chk2chk` 指定程序路径，通过 `--output-dir` 指定尚不存在
的输出目录。脚本把数值网格压缩为小规模 smoke test，固定单线程；它检查接口和模块执行。

完整回归：

```bash
QBOX_PYTHON=/opt/nwu911/envs/qetoolkit-python/current/bin/python3 bash tests/run.sh
```

单独运行 Python 测试：

```bash
QBOX_PYTHON=/opt/nwu911/envs/qetoolkit-python/current/bin/python3 \
PYTHONPATH=src qetoolkit-python -m unittest discover -s tests/python -p 'test_*.py'
```

## 科学与格式边界

- 本次覆盖了输入格式、真实 QE 接口、三个自旋分支、19 个子项目执行及指定路径能带误差。
  尚未完成平面波截断、k 网格、展宽、频率范围、能窗及模型大小的系统收敛研究，也未与正式
  材料响应基准逐项比较；“运行通过”不表示材料预测准确。
- 标量 Si、共线 Si up/down 和真实 SOC Te spinor 均有新算波函数、接口与 Wannier 结果；
  Te spinor cube 也已实际导出。共线 Si 是非磁性通道一致性检查，不覆盖磁性体系的可靠性。
- 曾用非正交测试晶胞和极稀疏的 2×1×2 网格进行预处理，触发 3.1.0 的
  `kmesh_get: ... too many nearest neighbours`。该程序近邻壳层限制不由纯文本校验保证避免；
  用户必须运行 `wannier90 -pp` 检查实际晶胞/网格，再做接口导出。立方 2×2×2 完整包检查通过。
- `wannier_plot_format=xsf` 的用户选项被转换为 3.1.0 接受的 `xcrysden` 值；不输出
  `shc_method`、`shc_ryoo`、`sc_use_eta_corr` 或 `explicit_kpath`。
- 重新执行 `restart=plot` 能生成 hr、能带和费米面，但不会因此重新输出 centres.xyz。
  已有结果的中心/展宽应查看原 `.wout`；本次 XYZ 导出检查来自正常 Wannier 化步骤。
- 普通 QE 对照与 Wannier 插值使用相同端点、标签和断点，但各程序采样规则不同。
  逐点对照应读取实际 `seed_band.kpt`，不以相同采样参数推断相同点列。
- SHC 和旋光自旋项要求 spinor 来源。轨道磁化/K 响应导出 uHu；自旋项导出 spn；
  NOA 和 Dw/C 不默认要求 uIu。输出响应张量不等于已包含实验几何和电流条件的最终观测量。
- 时间反演对称 Te 的 AHC、平衡轨道磁化等量可以为零；流程完成不要求每个张量分量非零。
- 本记录不声明正式发布。19 项运行、绘图和独立审计通过后，已删除本次目录内 1280 个中间文件路径（QE 重启二进制、UNK、接口矩阵及转换副本）；目录占用从约 7.92 GiB 降至约 171 MiB。保留结果、体数据、图、模型 checkpoint 和少量复现记录，清理后再次确认所有图的数据来源及声明结果均存在。详见 `ROOT/cleanup-manifest.json`。被删矩阵/UNK 需重新生成才能续算相应任务。

版本依据：[3.1.0 参数源码](https://github.com/wannier-developers/wannier90/blob/v3.1.0/src/parameters.F90)、
[算符读取](https://github.com/wannier-developers/wannier90/blob/v3.1.0/src/postw90/get_oper.F90)、
[gyrotropic 模块](https://github.com/wannier-developers/wannier90/blob/v3.1.0/src/postw90/gyrotropic.F90)、
[SeeK-path 原晶胞接口](https://seekpath.readthedocs.io/en/latest/maindoc.html)。
