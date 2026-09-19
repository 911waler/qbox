# qbox 离线安装包设计

状态：范围和兼容基线已经确认；本文等待用户审阅，尚未进入实现。

## 1. 目标与边界

让新用户在断网的 Ubuntu / Rocky Linux 计算机上，通过解压和运行一个安装脚本获得可用的 `qbox` 命令，无需预先配置 Python 科学计算环境。

用户已确认的要求：

- 只提供离线安装包，正式命令和产品名称均为 `qbox`。
- 包含 qbox 的 Bash/Python 模块、独立 Python 运行时及完整 Python 运行依赖。
- 不提供、不安装 QE、MPI、Multiwfn、`unfold.x` 和任何赝势库；这些由用户自行管理。
- 最低目标系统为 Ubuntu 20.04 和 Rocky Linux 8，首版架构为 x86_64。
- 默认普通用户安装，不要求 sudo，不修改系统 Python。

本次不改变科学算法、任务编号、计算文件格式或外部软件发现方式。不自动更新外部计算软件，不迁移本机现有正式安装，不提供在线安装版、容器交付版、DEB/RPM 或 ARM 包。

“离线”约束作用于交付物在用户机器上的安装和 qbox 本地功能验证。维护者准备发行包时可以获取上游运行时和依赖，但正式交付物必须包含安装所需全部载荷。

## 2. 现状与方案选择

当前模块化代码可以构建 wheel；`pyproject.toml` 要求 Python >= 3.10，`analysis` 与 `structure` 两组 extras 定义科学计算依赖。入口和任务目录本身只使用 Python 标准库，实际任务继续通过 Bash 兼容层执行。

选择“独立 Python + qbox wheel + 完整 wheelhouse”的离线压缩包：

- 仅附 wheelhouse 虽然更小，但仍依赖目标机 Python 版本和 ABI，不满足快速部署目标。
- 复制开发机虚拟环境会携带解释器和脚本绝对路径，不作为发布方式；Python 官方也将普通 venv 视为不可直接迁移的环境。[venv 文档](https://docs.python.org/3/library/venv.html)
- 自带运行时统一 Python ABI，在目标目录使用包内 wheel 安装依赖；保持源码模块和现有开发安装方式，不转成单文件可执行程序。

## 3. 平台与运行时契约

- 使用 CPython 3.12 系列的 GNU/glibc、基础 x86_64 `python-build-standalone` 运行时，不选择 x86_64-v2/v3/v4 或静态 musl 构建。发行配置必须固定补丁版本、上游构建标识、下载来源和 SHA-256，禁止浮动的 `latest` 输入。[运行时分发说明](https://gregoryszorc.com/docs/python-build-standalone/main/running.html)
- 整包以 glibc 2.28 为最低系统兼容基线：运行时和所有原生扩展所要求的最低 glibc 不得高于 2.28。不能仅检查 Python 本体，也不能直接复制开发机 `.so`。
- 依赖 wheel 仅接受匹配 CPython 3.12 / 兼容 ABI、x86_64 且符合上述基线的构建，以及纯 Python wheel；拒绝需要更高基线的包、来源不明的 `linux_x86_64` wheel 和安装时才编译的源码包。manylinux 标签描述的是二进制兼容要求，不等同于整包测试通过。[平台兼容标签](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/)
- 目标机基础条件为 Bash 4.4+、glibc 2.28+、GNU coreutils、grep、sed、awk、tar、gzip，以及可写的用户临时/缓存目录。无需预装 Python、pip、编译器、Conda、Docker 或网络下载工具。
- 初始强制测试矩阵为 Ubuntu 20.04 / 22.04 / 24.04、Rocky Linux 8 / 9 的 x86_64 环境。最低版本约束不表示自动保证所有未来版本；其他版本只有经过相同验收后才加入“已验证”列表。
- 运行时和原生依赖的动态库闭包必须在上述基础环境中成立；发现额外系统库依赖时，维护者应选用兼容构建或在许可允许下随包提供并限定其加载范围，不能让最终用户在线补包。

## 4. 交付目录与可追溯性

发布一个 `qbox-<version>-linux-x86_64-offline.tar.gz`，并提供该压缩包的 SHA-256 校验文件。包内结构为：

```text
qbox-<version>-linux-x86_64-offline/
├── install.sh
├── runtime/                 # 固定版本的独立 Python 运行时归档
├── packages/                # qbox wheel，包含全部模块和 Bash 资源
├── wheelhouse/              # 两组 extras 及完整传递依赖的二进制 wheel
├── requirements.lock        # 精确版本、wheel 哈希；不得引用网络地址
├── manifest.json            # qbox 提交、平台、运行时、载荷来源/版本/哈希
├── checks/                  # 不调用外部计算软件的安装自检及小型数据
├── README.zh-CN.md
├── LICENSE                  # 保留项目现有 MIT LICENSE
├── THIRD_PARTY_LICENSES/     # 运行时、Python 包和所带原生库的许可证/声明
└── SHA256SUMS
```

打包采用明确的文件白名单，排除 Git 元数据、开发虚拟环境、缓存、测试计算结果、本机配置、私有路径和设计/开发记录。不会把其他软件安装目录扫描后整体收入包中。

`requirements.lock` 是针对发行平台解析出的完整依赖闭包，不是从开发机任意 `pip freeze` 得到的清单。缺 wheel、缺许可证材料、哈希不符或原生库检查不通过时，构建失败，不生成可发布标记。运行时自带的 pip 等包同样进入版本和许可清单。哈希用于完整性检查，不宣称其本身能够证明发布者身份。

## 5. 安装流程与目录所有权

安装界面：`bash install.sh [--prefix DIR] [--bin-dir DIR]`。默认安装根目录为 `$HOME/.local/share/qbox`，命令目录为 `$HOME/.local/bin`；支持包含空格的绝对路径。参数和错误提示提供中文说明。

```text
<prefix>/
├── releases/<release-id>/
│   ├── python/              # 独立运行时及已安装的 qbox/依赖
│   ├── bin/qbox             # 自行解析所在版本目录的启动器
│   └── metadata/            # 安装标记、manifest、许可证及自检入口
└── current -> releases/<release-id>

<bin-dir>/qbox -> <prefix>/current/bin/qbox
```

`release-id` 由 qbox 版本和载荷清单摘要确定；相同 qbox 版本的不同依赖构建不能互相覆盖。

安装按顺序完成：

1. 检查系统、CPU 架构、基础命令、目标可写性、安装路径和现有入口归属；不执行 sudo、apt 或 dnf。
2. 校验包内文件清单和哈希。拒绝路径穿越、绝对归档成员、越界链接，以及与已存在的非 qbox 文件冲突的目标。
3. 在安装根目录内创建本次操作独占的暂存目录；解包独立运行时，用其 Python/pip 安装本地 wheel。安装禁用索引、网络更新检查、源码构建和用户 pip 配置影响，要求锁定哈希，缺包立即失败。[pip 本地包安装](https://pip.pypa.io/en/stable/user_guide/#installing-from-local-packages)
4. 检查完整依赖、包资源、模块导入和小型功能样例。离线锁明确包含两组 extras；自检不能仅依靠不检查未启用 extras 的 `pip check`。
5. 将暂存目录移到尚不存在的最终版本目录，在最终路径再次验证启动和资源定位，再切换 `current` 和命令入口。公共入口不依赖 pip 在暂存路径生成的绝对 shebang。
6. 输出版本、安装位置、自检结果和 PATH 提示。若命令目录不在 PATH，只打印用户可执行的配置方法，不自动编辑 `.bashrc` 等文件。

安装操作按根目录加互斥锁，阻止并发切换。重复安装相同载荷先验证现有版本；验证通过可复用，损坏则明确失败，不静默覆盖。已存在的非 qbox 命令、普通文件或非受管理链接均不替换。

失败不改变当前可用版本；清理仅限本次创建且验证归属的暂存/失败版本目录。升级保留旧版本，文档说明如何将 `current` 切回已验证版本，以及如何确认归属后卸载；首版不实现自动清理旧版本或后台更新服务。

## 6. 启动与外部环境隔离

- 离线包入口固定使用本版本的 Python，并为内部子任务明确设置 `QBOX_PYTHON` 和私有离线运行标记。该标记用于区分离线入口与普通安装，不作为需要用户配置的新接口。它不能因为系统 PATH、激活的 Conda/venv 或旧 `QBOX_SHARED_ROOT` 而意外选择其他解释器。
- 用户显式设置的 `QBOX_PYTHON` 若不指向包内解释器，离线入口应清楚报错并提示取消该覆盖；不静默混用未验证依赖。源码入口和普通 wheel 安装继续保留原有 `QBOX_PYTHON` / `QBOX_SHARED_ROOT` 配置契约。
- 所有 qbox 自有 Python 调用使用隔离模式，不受宿主 `PYTHONHOME`、`PYTHONPATH` 和用户 site-packages 影响；自身模块由安装目录定位。离线模式不再向 Bash 环境注入包路径。外部程序仍继承用户原有环境，不用清空整个子进程环境的办法解决 Python 隔离。
- 包内辅助 Python 工具和递归启动也必须经过同一隔离入口；如提供辅助工具的直接命令，不允许靠 `#!/usr/bin/env python3` 意外选择宿主解释器。
- 不把包内 Python 的整个 `bin` 或原生库目录全局加入 PATH / `LD_LIBRARY_PATH`。保留用户外部计算环境的 PATH、动态库路径和 MPI 配置；不以隔离 Python 为由清空整个环境。
- 保留 `QBOX_MULTIWFN_HOME`、`QBOX_PSEUDO_ROOT`、`QBOX_QE_ENV_SCRIPT`、`QBOX_ONEAPI_ENV_SCRIPT` 的外部配置语义，离线包不设置它们的机器专用默认值，也不新设 `QBOX_SHARED_ROOT`。
- 启动器通过 `exec` 进入原 CLI，保持计算目录、参数、标准输入、退出码和信号传播。`qbox --help`、`--version`、`--list` 不因缺少外部计算软件而失败。
- 缓存写入用户可写位置；安装目录可只读。公共入口始终使用 `qbox`，不自动创建旧命令别名。

## 7. 必要的跨系统适配范围

现有 Bash 层使用 GNU 基础工具；不能把“Python 依赖齐全”当成“全部运行条件齐全”。已发现两处 `awk IGNORECASE` 和一处实际 `bc` 调用：

- `legacy/unfold.sh` 的 `nbnd` 解析及 `legacy/plot_common.sh` 的 `nat` 解析：改成同时兼容 mawk / gawk 的大小写处理，保留原有解析行为。
- `legacy/input_phonon.sh` 气相热力学输入生成的正频率比较：使用便携 awk 完成等价判断，不要求用户另外安装 bc。

上述改动以现有输入输出和边界用例回归测试约束，不扩展到科学流程重写。`lscpu` 保持已有可选回退；不新增 dos2unix、gnuplot 或 gawk 的强制安装要求。外部 QE 检查所用的 `file`、`ldd` 和可选 Lmod 仍属于外部工作流集成条件，不作为离线包安装成功的前提。

## 8. 发布验收

所有“兼容”和“离线可安装”的结论必须有对应发行载荷的测试证据：

- 原有 Bash / Python 回归测试通过；新增 awk 大小写、科学记数法和频率比较测试。若原比较对某类数据已有错误，单独记录，不借打包悄悄改变科学结果。
- 在测试矩阵的干净系统中断网安装，不预装额外 Python/pip、bc 或被排除的计算软件。通过受控 PATH 中的失败替身验证安装器不调用宿主 Python/pip，不为测试移除操作系统自身依赖的 Python。Ubuntu 验证基础 mawk，Rocky 验证基础 awk，不要求用户额外安装 gawk；模拟错误解释器和外部配置干扰。
- 验证 NumPy、SciPy、Matplotlib 无显示器绘图、seekpath、ASE、pymatgen，以及依赖闭包中的原生模块；使用固定小型数据验证结构转换、能带路径和代表性的后处理结果，不仅执行 import。
- 在源码树外的任意计算目录运行 `qbox --version`、`--help`、`--list`；通过受控测试替身验证任务转发、stdin、退出码和信号，不启动真实 QE/MPI 作业。
- 验证包含空格的安装路径、只读安装目录、默认用户目录、自定义前缀、相同版本复用、新版本安装与旧版本回退，以及外部 PATH / 动态库环境没有被包内路径污染。
- 验证错误 CPU 架构、过低 glibc、缺少基础命令、损坏载荷、缺 wheel、解包失败、权限不足、入口冲突和并发安装；失败后旧版入口及用户文件保持不变。
- 每个平台记录系统版本、测试镜像标识、安装包 SHA-256 和结果。平台未执行或失败时如实标记，不使用宿主机测试替代跨系统结论。

验收记录、锁文件、构建配方和源码可以进入仓库；体积较大的运行时/wheel 缓存和最终离线包进入忽略的构建输出目录，由发布渠道分发，不提交到 Git 源码历史。

## 9. 本阶段交付与下一阶段

本阶段只形成并提交此设计文档，不产生可安装的离线发行包，也不变更现有部署。用户审阅本文后，再编写实现计划，划分构建工具、安装器、启动器、跨系统适配和测试任务；正式实现及发布遵循后续确认的计划。
