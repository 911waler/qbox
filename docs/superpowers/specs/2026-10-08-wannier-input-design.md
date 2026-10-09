# qbox Wannier90 六类输入生成设计

日期：2026-10-08。状态：设计已确认并实施；验证记录见 [Wannier90 验证](../../wannier-validation.md)。

## 目标与交付范围

在 qbox 的“输入文件生成”分组中，紧接现有 `10) 生成 unfold.x 输入文件`，
新增 `11) 生成 Wannier90 输入文件`。所有现有功能完整保留。
进入后先选择计算方向，再进入该方向的参数菜单。第一版提供下列六类的实际输入生成能力：

1. 精细电子结构：插值能带、QE 能带对照输入、DOS、Wannier 轨道投影 DOS、费米面。
2. 局域轨道与模型：Wannier 轨道图、中心与展宽、在位能和跃迁矩阵导出。
3. 热电与电子输运：BoltzWann 的 Seebeck 系数、电导率和电子热导率。
4. Berry 曲率与霍尔响应：沿路径/切片的 Berry 曲率、内禀反常霍尔与自旋霍尔电导。
5. 光学与非线性响应：复光电导及其磁光相关分量、位移电流。
6. 轨道磁性与旋光：轨道磁化、自然旋光响应、电流诱导旋光和磁化所需的响应张量。

交付的是经校验的计算输入、必要的接口导出设置、参数来源摘要和运行说明。
生成过程不启动生产 QE/MPI/Wannier90 计算。轨道图由 Wannier90 按输入导出 cube/xsf；
物性响应张量不冒充已经包含实验几何、电流大小等条件的最终观测量。

用户明确要求最终输入默认写入当前工作目录，不新建 `WANNIER/<seed>/` 计算目录。
原生 Python kmesh 能力随本功能实现，保留独立命令供其他输入生成器复用。

## 菜单与编号

`0–10` 保持原映射，`10` 仍为 `unfold-input`。在其后新增 `11` 对应 `wannier-input`，
原 `11–37` 统一顺延为 `12–38`。现有任务的名称、命名入口、所属分组和处理器保持不变，
不删除、替代现有功能，也不将 Wannier 功能合并进 unfold 子菜单。

| 原编号 | 新编号 | 功能 |
| --- | --- | --- |
| 0–9 | 0–9 | 原有输入生成项目 |
| 10 | 10 | unfold-input，生成 unfold.x 输入文件 |
| 无 | 11 | wannier-input，生成 Wannier90 输入文件 |
| 11 | 12 | scf，SCF 计算 |
| 12 | 13 | bands，能带计算 |
| 13–37 | 14–38 | 其余现有任务按原顺序顺延 |

帮助、任务列表、菜单、Bash 中的任务编号引用、测试和架构文档同步更新。
发行说明提供编号迁移表；命名命令如 `--task scf`、`--task unfold-input` 保持兼容。
原有脚本若依赖 `11–37` 的数字任务选择，需要按映射更新；不设置与新编号含义冲突的旧数字别名。
PW 快捷选项等非任务编号参数继续按原语义解释，不随任务编号迁移而改变。

入口：`qbox --task wannier-input scf.in`，或主菜单选择 `11`。可省略文件后交互选择。
六个方向使用上面的名称和顺序；返回操作不写文件。选方向后直接出现参数菜单：

```text
1) 计算项目与生成模式
2) 来源输入、可选输出及原 QE 运行目录
3) Wannier 名称与目标版本
4) 均匀 k 网格
5) 能带数、轨道数与初始投影
6) 解纠缠能窗
7) 当前计算项目的专用参数
8) 输出文件与检查结果
0) 检查并生成
b) 返回方向选择
q) 返回主菜单
```

各项显示当前值、来源及单位；不适用项隐藏或标明原因。方向内的相关计算项目允许多选，
导出要求取并集；不兼容设置指出具体冲突。公共配置保留，返回选择其他方向不丢失已填信息。
切换方向会替换原任务开关，避免残留开关意外运行额外任务。

## 两种生成模式

**新建完整输入。** 从已有 SCF 输入继承物理设置，生成 NSCF、`.win`、`.pw2wan` 和说明。
SCF 输出是可选辅助来源；SCF 尚未运行也能生成准备文件。仅有 CIF/VASP 时先使用 qbox
现有 PW 输入功能，避免在这里重复选择泛函和赝势。relax/vc-relax 初始结构不能充当最终 SCF 结构。

**基于已有 Wannier 结果调整任务。** 读取同名 `.win` 和现有文件信息，保留 seed、晶胞、
原子顺序、网格、带选择、投影、自旋通道及 Wannier 化基础配置，只更新任务/绘图参数。
修改模型基础配置时明确转入重新构建流程，不能继续把旧 `.chk` 标成匹配。
缺失额外算符文件时，可以生成补导出的接口输入和执行说明，但必须标注“需先补齐数据”。
对外部产生的 checkpoint，仅凭同名或文件存在不能证明模型、规范及矩阵维度相符。

## 公共配置与校验

- SCF 原文保真改写：仅修改目标步骤必要的 namelist 键和 K_POINTS；保留赝势、泛函、
  cutoff、磁性、HUBBARD 等物理设置及卡片。支持同一行多赋值、注释、引号、索引键和 D 指数。
  不复用当前简单正则脚本充当通用 QE parser；不以截去 K_POINTS 后全部文本的方式替换网格。
- 首版结构支持 `ibrav=0`，CELL_PARAMETERS 为 angstrom/bohr，ATOMIC_POSITIONS 为
  crystal/angstrom/bohr；校验 nat、ntyp、species 映射、有限数值和非奇异晶胞。
  保留 Fe1/Fe2 等标签与原子顺序。未实现的 alat、非零 ibrav、crystal_sg、表达式坐标明确报错。
- QE `prefix` 与 Wannier `seedname` 分别存储。seed 是当前目录内的安全文件基名，不能含路径。
  原 QE 运行目录默认当前目录并展示给用户；输入文件父目录不被当作可靠的历史运行目录。
  outdir、pseudo_dir、wfcdir 按原运行目录解析，再相对最终当前目录表示；原运行目录相同时
  保留已有相对路径。显式处理源文件缺省值及环境变量，不擅自写死 `./tmp`。
- `nbnd` 提供读取到的初值，最终由用户明确确定。`num_bands = nbnd - 排除带数量`；
  排除带索引去重并检查范围，`1 <= num_wann <= num_bands`。不按“占据带加固定数”猜轨道数。
- 投影编辑器支持按 species/原子和常见 s/p/d/f、杂化轨道选择，并显示实际展开数。
  spinor 投影按实际自旋分量计数；高级投影语法只接受能正确解析和校验的形式。
  投影数、select_projections 与 num_wann 共同校验，不静默截取或补随机投影。
- 能窗以 eV 输入，默认使用与 QE 本征值相同的能量零点。只有已知且明确选用参考能时，
  才把相对费米能的窗口转换为绝对能量；检查上下界和冻结窗包含关系。没有冻结窗是合法选择。
  每个 k 点外窗/冻结窗内带数是否足够，要等 `.eig` 可用后检查，输入阶段不声称完成物理验证。
- 需要费米能、温度、频率、弛豫时间等参数的任务才显示对应字段。来源不明的数值要求输入；
  展宽、网格等建议值注明需要收敛测试。BoltzWann 弛豫时间单位 fs，温度单位 K。
- 所有方向共用同一份网格：正整数维度、Gamma 包含且无位移的完整均匀网格，z 索引最快。
  NSCF 用带权重 crystal 列表，`.win` 用同序三列列表及相同 mp_grid；拒绝直接复制约化点集合。
  新 NSCF 配置适当的 nosym/noinv 并保留波函数；不要求原 SCF 也关闭对称性。
  对依赖旧网格的显式占据或未支持的特殊设置给出具体错误，不静默改变物理模型。

## 自旋分支

| 来源设置 | 生成方式 |
| --- | --- |
| 普通非磁性 | 一个 seed；spinors=false；接口 spin_component=none |
| nspin=2 共线自旋 | 一份共享 NSCF；seed_up/seed_down 两套 win/pw2wan，win 的 spin 与接口通道均指定 up/down |
| noncolin=true | 一个 spinor seed；spinors=true；接口 spin_component=none；保留原 lspinorb |

共线 `nbnd` 不乘二，各通道可以有不同的投影/能窗/num_wann。保留原磁化参数与物种区别。
后处理的 `num_elec_per_state` 按状态计数设置：普通非磁性标量态为 2，共线单通道与 spinor 态为 1；
不能把“未启用 SOC”当作所有情况下均有双重自旋简并。
SHC 及显式自旋矩阵任务检查 spinor 来源；不通过修改 NSCF 开关假装已有 SCF 具备 SOC。
spinor 轨道图明确所绘制的幅值/分量；不能按普通实标量轨道解释符号。

## 六类任务和导出契约

基础接口写出 amn/mmn/eig；按任务联动额外文件，用户界面显示用途，不要求手填内部依赖。
以下默认针对官方 Wannier90 3.1.0。该版本由本机 QE 7.5 随附程序的 `--version` 实测确认。

| 方向与项目 | 核心设置 | 专用参数及额外数据 |
| --- | --- | --- |
| 插值能带与对照 | bands_plot、kpoint_path | 路径、采样；可选 QE bands 输入；同一能量参考 |
| DOS / 轨道投影 DOS | dos；按需 dos_project | 能量区间、步长、展宽、dos_kmesh；投影按 Wannier 轨道编号 |
| 费米面 | fermi_surface_plot | 费米能与插值网格 |
| 轨道图 | wannier_plot | 轨道列表、超胞、cube/xsf；接口 write_unk=true |
| 中心、展宽和紧束缚模型 | write_xyz、write_hr | 中心/展宽读取 wout，中心另导出 xyz，在位能/跃迁来自 hr |
| Seebeck / 电导 / 电子热导 | boltzwann | boltz_kmesh、mu/温度范围、relax_time；普通计算无需额外算符 |
| Berry 曲率路径/切片 | kpath 或 kslice，task=curv | 原胞基底路径或切片平面、采样、费米能 |
| 内禀反常霍尔 | berry=true，berry_task=ahc | 费米能及 berry_kmesh |
| 内禀自旋霍尔 | berry_task=shc | 3.1.0 的 Qiao 路径；write_spn=true；分量与相应积分参数 |
| 复光电导/磁光相关响应 | berry_task=kubo | 频率范围、步长、展宽、费米能、积分网格；输出相应电导张量 |
| 位移电流 | berry_task=sc | 频率/展宽、sc_eta、sc_phase_conv、积分网格及能带上限 |
| 轨道磁化 | berry_task=morb | write_uHu=true；费米能及积分网格 |
| 自然旋光带间响应 | gyrotropic=true，task=-noa | 频率、费米能、gyrotropic_kmesh；含自旋时 -noa-spin 及 write_spn |
| 电流诱导旋光响应 | gyrotropic_task=-dw-c | 有限频率 Berry 曲率偶极及欧姆响应张量；无额外算符文件 |
| 电流诱导磁化响应 | gyrotropic_task=-k-c | 动力学磁电响应；write_uHu；含自旋时 -k-spin-c 及 write_spn |

热电项目来自同一次 BoltzWann 运行，可同时得到三个量；解释弛豫时间假设及电子热导的范围。
磁光相关任务生成复光电导张量输入，不声称仅凭这些设置已经得到完整 Kerr/Faraday 角。
第六类区分 NOA、有限频率 Berry 曲率偶极、K/C 等张量与用户实验条件下的旋转角/磁化强度。
上述第六类接口不默认导出 uIu；轨道磁化/kME 所需 uHu 与自旋项 spn 按任务取并集。

## 版本与已有结果

第一版应内置官方 3.1.0 参数配置，并完成下文验收后提供六个方向的可用模板。
生成不依赖运行时加载 QE/MPI 环境；用户可显式选择目标版本，探测失败不能中止纯文本生成。
其他版本只有经过能力与语法验证后才标记为支持，不用不稳定的“latest”作为序列化目标。

3.1.0 自旋霍尔不写 `shc_method` 或 `shc_ryoo`，位移电流不写 `sc_use_eta_corr`。
未来支持已验证的新版时，再启用相应能力；Ryoo 分支额外联动 sHu/sIu。
不能把文章示例和最新版手册中的所有参数无条件混入本机模板。

已有结果按任务检查 `.win/.chk/.eig/.mmn` 及额外矩阵/UNK；除存在性外，检查可读取的维度、
通道及来源记录。区分“输入已生成”“所需数据检查通过”“计算已验证”三种状态。
补导出必须使用原 Wannier 化的同一批 NSCF 波函数。原波函数已丢失或被覆盖时，重新 NSCF
后应重建相互一致的接口矩阵和 Wannier 结果，不能把新规范的算符矩阵直接配上旧 checkpoint。
只更新后处理参数时保留基础 `.win` 配置及 seed，不改名复制 `.chk` 来伪造新的匹配结果。

## 当前目录文件与发布

新建模式默认生成 `seed.nscf.in`、`seed.win`、`seed.pw2wan`、`seed.qbox.json` 和
`seed.README.txt`。配置记录保存版本、来源摘要、公共参数及生成清单，便于后续复用与核查；
允许无记录的外部输入导入，但显示来源尚未验证。共线模式使用明确的 up/down 文件名。
能带对照额外生成 `seed.bands.in` 与 `seed.bands.pp.in`，避免覆盖通用 `bands.in`。
已有结果模式只更新所需 win/配置/说明；需要补导出时才加入接口输入。

输出预览先列全所有目标文件及覆盖冲突。出现同名文件时，统一选择“备份后覆盖 / 改名 / 取消”；
自动化调用必须显式给出冲突策略。备份仅针对本次输入文件，统一存入当前目录的 `bak/`，
采用 `.bak`、`.bak.1` 等唯一后缀，不覆盖已有备份。源 SCF、checkpoint、矩阵、波函数和已有计算结果不作为替换目标。

全部内容先生成和校验，再在同文件系统暂存；正式替换前复查目标摘要，防止覆盖并发改动。
逐文件替换期间可捕获的失败恢复已覆盖文件并撤回本次新增文件。多文件提交不宣称一次原子操作；
保留小型事务清单及备份用于崩溃后的显式恢复，恢复前核验内容，冲突时报告而非强制覆盖。
符号链接或非普通文件冲突要求改名/取消；清理仅处理本次创建的临时文件。

## 能带对照与运行顺序

公共路径以原 SCF 倒格基底表达，保留原晶胞、原子顺序及磁性物种区别。
自动路径使用适用于原晶胞的 SeeK-path 接口；超胞路径注明关联原胞路径的含义。
几何对称不能证明磁态具有时间反演对称，磁性来源采用保守设置或用户明确选择。

普通对照共享标签、端点和断点，分别按目标程序规则采样。需要逐点误差比较时，提供读取
Wannier 实际输出 `seed_band.kpt` 再生成 QE 对照输入的操作；不把相同采样参数当作相同点列。
3.1.0 模板不使用新版 `explicit_kpath`。能量零点取共同参考，不对两套能带分别任意平移。

运行说明：SCF → 均匀网格 NSCF → wannier90 -pp → pw2wannier90 → wannier90 → 按任务 postw90。
QE 参考 bands 及 bands.x 安排在接口导出和 Wannier 化之后；共享 prefix/outdir 的这些步骤
不能并行运行，也不能把 bands 插入网格 NSCF 与接口导出之间。后续补算算符时复查波函数来源。

## 模块边界与实施顺序

- `io/kmesh.py`：标准库网格与 QE/Wannier 格式化；公开 `qbox kmesh NX NY NZ --format qe|wannier`。
- `io/wannier_inputs.py`：受支持 QE 输入的保真解析、公共配置校验、文件包纯生成接口。
- `io/wannier_profiles.py`：六类任务的版本化参数、单位、默认提示和导出依赖，保持数据驱动。
- `legacy/wannier.sh`：交互与受控发布，经现有注册表/加载链进入，不重新运行通用 pwin 向导。
- 路径模块提取原晶胞路径数据接口，保留旧调用接口；结构和科学可选依赖按实际需要加载。

先完成网格及输入契约，再完成六类模板与参数菜单，最后连接当前目录发布和安装包验证。
这是同一首版的实施顺序，六类全部通过验收后才宣称首版完成；不交付可点却不能生成的空菜单。
本设计不要求系统级安装、远端部署或推送 GitHub，后续发布按用户授权另行执行。

## 验收

1. 验证菜单 10 仍为 unfold、11 新增 Wannier、原 11–37 顺延为 12–38；逐项确认现有任务的
   slug/处理器/行为保留，数字选择与命名选择指向同一功能。六个方向、方向后参数菜单和
   PW 快捷选项另有行为测试，防止编号迁移误改非任务参数。
2. 网格与本机 kmesh.pl 对照，覆盖 1×1×1、非立方、二维网格、无效维度、坐标顺序与权重。
3. 解析覆盖引号路径、同一行多键、单位转换、非正交晶胞、Fe1/Fe2、HUBBARD 尾卡与错误输入；
   修改仅限允许字段，源文件保持原状。
4. 六类每个列出的子任务都有有效输入样例、参数校验及导出依赖断言；有三个自旋分支的样例。
5. 在官方 3.1.0 上核验参数语法和 `wannier90 -pp`；使用可信小体系的配套数据验证各模块读取和
   启动。需完整计算数据的物性测试明确区别于纯文本/格式测试；不声称这些测试证明材料结果收敛。
6. 交换轴/非标准晶胞的路径按笛卡尔 k 向量核对，参考能带和插值能带使用同一物理路径。
7. 当前目录、空格/中文路径、统一备份、校验失败、发布中断、并发冲突、已有结果缺矩阵都验证。
8. 导入无副作用；纯网格/基础文本生成无需安装 QE；wheel 在源码目录外验证模块、菜单和输入生成。

## 依据

- [Wannier90 官方实用程序及 kmesh](https://wannier90.readthedocs.io/en/latest/user_guide/appendices/utilities/)
- [QE pw2wannier90 接口](https://www.quantum-espresso.org/Doc/INPUT_pw2wannier90.html)
- [Wannier90 参数](https://wannier90.readthedocs.io/en/latest/user_guide/wannier90/parameters/)
- [postw90 参数](https://wannier90.readthedocs.io/en/latest/user_guide/postw90/postw90params/)
- [Berry 响应的算符需求](https://wannier90.readthedocs.io/en/latest/user_guide/postw90/berry/#needed-matrix-elements)
- [BoltzWann](https://wannier90.readthedocs.io/en/latest/user_guide/postw90/boltzwann/)
- [Gyrotropic](https://wannier90.readthedocs.io/en/latest/user_guide/postw90/gyrotropic/)
- [固定版本 3.1.0 参数源码](https://github.com/wannier-developers/wannier90/blob/v3.1.0/src/parameters.F90)
- [固定版本 3.1.0 算符读取](https://github.com/wannier-developers/wannier90/blob/v3.1.0/src/postw90/get_oper.F90)
- [固定版本 3.1.0 gyrotropic](https://github.com/wannier-developers/wannier90/blob/v3.1.0/src/postw90/gyrotropic.F90)
- [SeeK-path 原晶胞路径](https://seekpath.readthedocs.io/en/latest/maindoc.html)
