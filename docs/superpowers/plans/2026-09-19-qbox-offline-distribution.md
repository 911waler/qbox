# qbox Offline Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可在断网的 Ubuntu 20.04+ / Rocky Linux 8+ x86_64 基础环境中用户级安装的 qbox tar.gz，包含固定 CPython 3.12 和两组 extras 的完整依赖。

**Architecture:** 维护者工具先生成并审查固定载荷锁，再由本地缓存构建发行物；目标机上的 Bash 安装器校验并展开包内运行时，调用包内 Python 完成离线安装、自检和版本事务。离线启动器通过隔离模式进入原 CLI，保留源码/wheel 的配置契约及外部计算环境。安装成功的提交点是 `current` 的原子替换，旧版本保留供回退。

**Tech Stack:** Bash 4.4+、GNU 基础工具、CPython 3.12、python-build-standalone、pip wheel/hash 模式、Python unittest、现有 Bash 回归套件；维护者侧另用 packaging、build、auditwheel、readelf、Docker/Podman 或虚拟机。

**Spec:** [已批准设计](../specs/2026-09-19-qbox-offline-distribution-design.md)，设计提交 `c60279a`，模块化基线 `a360b5f`。设计正文的“等待用户审阅”是旧阶段文字；本计划依据交接中明确的用户批准。

## Global Constraints

- 只提供离线安装包，正式命令和产品名称均为 `qbox`。
- 包含 qbox 的 Bash/Python 模块、独立 Python 运行时及完整 Python 运行依赖。
- 不提供、不安装 QE、MPI、Multiwfn、`unfold.x` 和任何赝势库；这些由用户自行管理。
- 最低目标系统为 Ubuntu 20.04 和 Rocky Linux 8，首版架构为 x86_64。
- 默认普通用户安装，不要求 sudo，不修改系统 Python。
- 整包以 glibc 2.28 为最低系统兼容基线。
- 使用 CPython 3.12 系列的 GNU/glibc、基础 x86_64 `python-build-standalone` 运行时，不选择 x86_64-v2/v3/v4 或静态 musl 构建。
- 初始强制测试矩阵为 Ubuntu 20.04 / 22.04 / 24.04、Rocky Linux 8 / 9 的 x86_64 环境。
- 目标机基础条件为 Bash 4.4+、glibc 2.28+、GNU coreutils、grep、sed、awk、tar、gzip，以及可写的用户临时/缓存目录。
- 无需预装 Python、pip、编译器、Conda、Docker 或网络下载工具。
- 安装界面：`bash install.sh [--prefix DIR] [--bin-dir DIR]`；默认 `$HOME/.local/share/qbox`、`$HOME/.local/bin`；支持包含空格的绝对路径。
- 源码入口和普通 wheel 安装继续保留原有 `QBOX_PYTHON` / `QBOX_SHARED_ROOT` 配置契约。
- 不把包内 Python 的整个 `bin` 或原生库目录全局加入 PATH / `LD_LIBRARY_PATH`。
- 缓存写入用户可写位置；安装目录可只读。
- `lscpu` 保持已有可选回退；不新增 dos2unix、gnuplot 或 gawk 的强制安装要求；`file`、`ldd` 和可选 Lmod 仅属于外部工作流集成条件。
- 不改变科学算法、任务编号、计算文件格式或外部软件发现方式；不迁移本机生产部署，不提供在线安装版、容器交付版、DEB/RPM 或 ARM 包。
- 本文是实现计划。本任务仅保存本文、核查代码和资料；不下载产品依赖、不安装、不实现产品代码、不构建正式包、不推送远端。用户审阅并选择执行方式后才开始下列复选步骤。

## Review Focus

1. **宿主配置泄漏及二次 Python 调用：** 恶意/错误 `PYTHONPATH`、用户 site、激活环境、旧共享根和递归有效质量脚本均不能改变内部解释器，外部替身仍收到原来的环境。归属 Task 4、10。
2. **暂存目录改名和只读安装：** 空格路径、软链接公共入口、暂存目录消失之后，所有内部入口仍可运行，缓存不写安装树。归属 Task 7、8、10。
3. **第一次安装/升级在两个入口之间失败：** bin-dir 与 prefix 可在不同文件系统；竞争、信号、入口冲突不能覆盖用户文件或使旧 current 失效。归属 Task 8、10。
4. **已校验压缩包中的危险成员：** 即使测试重新计算了哈希，绝对路径、父目录穿越、重复成员、链接、特殊文件和文件/目录重叠也必须在展开前失败。归属 Task 1、6、9。
5. **看似完整但实际缺依赖：** extras、平台 marker、pip 自带/vendor 包、wheel 内原生库和许可证必须全部计入；import 成功或 manylinux 标签都不能代替功能与闭包验收。归属 Task 2、3、7、11。

---

## 现状、实现边界与工作顺序

2026-09-19 只读核查：主机 `7B12`；真正工作树 `/home/waler/QEtoolkit/main`；`main` 位于 `c60279a`，干净且领先 `origin/main` 两个提交；未发现项目内额外 `AGENTS.md`。同级历史工作树不参与本计划。当前 `/usr/bin/python3` 是 3.12.3，缺少 seekpath、SciPy、Matplotlib、ASE、pymatgen；本次没有安装这些依赖或宣称原回归已通过。Docker 服务可读，但本次没有拉取/运行镜像。执行时重新核实，不把本机状态当作目标平台证据。

当前重要边界：

| 现有位置 | 当前职责与本次切口 |
|---|---|
| `pyproject.toml` | `analysis=[numpy,matplotlib,scipy,seekpath]`、`structure=[pymatgen,ase]`；保持源码依赖范围，发行锁另存 |
| `src/qbox/cli.py:70` | 总是向 Bash 注入包路径；离线分支需要保留原 PYTHONPATH 原值 |
| `src/qbox/bin/qbox`、`legacy/load.sh` | 递归启动及 source 入口都注入 PYTHONPATH；分别增加离线分支 |
| `legacy/dispatch.sh:76` | `qbox_python` 是主要科学 Python 调用点；离线分支追加 `-I -B` |
| `legacy/bootstrap.sh` | 共享根默认值、PATH 和 Matplotlib 缓存；离线时不注入包 bin，保留外部变量语义 |
| `postprocess/effective_mass_qe.py:202` | 以 `sys.executable` 启动拟合子脚本，必须显式传递隔离参数 |
| `legacy/pdos.sh`、`bin/qbox-dopant-pdos.py` | 辅助脚本经 `qbox_python` 调用；离线包不提供依赖宿主 shebang 的直接辅助命令 |
| `tests/run.sh`、`tests/test_helper.sh` | 完整开发回归需要 seekpath、rg 等；不能直接充当基础目标机安装自检 |
| `tools/verify-wheel.py` | 现有 wheel 验证，依赖开发环境；保留，新增独立离线验证 |

两项需要显式审阅的细化：

- 设计列了两处 awk IGNORECASE；实际第三处在 `legacy/pw_settings.sh:30` 的 `read_upf_cutoffs`。Task 5 将三处一并改成便携匹配，只改解析可移植性，不改单位或科学计算。
- 旧 `bc` 对 `+.5`、`1e2` 报语法错误，对 `1E2`/`1D2` 则可能按非指数数字解释。Task 5 保持已支持十进制输出；指数形式先给出明确“不支持此输入”的失败，不把旧错误隐式升级成新的科学解释。扩展指数频率支持须另立科学行为变更；本计划为 UPF 已支持的 D/E 指数保留回归。

执行时先用 `superpowers:using-git-worktrees` 判断是否已有隔离工作树，再创建/使用实现工作树；不要直接在当前 main 实现。本计划里的相对路径均以该工作树根为准。各任务提交仅是本地审阅点，不包含 push、合并、发布或生产迁移。每个代码步骤先写行为测试、看到预期失败，再实现并验证；长时间下载/矩阵运行是单独操作，其耗时不代表一个编码步骤可无限扩大。

测试命令中的 `python` 指维护者开发解释器。Task 1 和 bootstrap 合成测试只需 stdlib；Task 2 的工具依赖准备属于该任务，必须固定并记录后使用。完整原有回归前先验证开发解释器能导入六个直接依赖，再将 `QBOX_PYTHON` 设为其绝对路径；不让 `tests/test_helper.sh` 的 PATH 自动发现结果替代这个证据。开发 venv 可存在于 `build/offline/dev/`，但绝不复制进发行物；正式 runtime/依赖锁不得从该 venv 的 pip freeze 推导。

依赖顺序：

```text
1 发行数据契约 → 2 固定运行时/依赖 → 3 许可证与二进制审计
       ├→ 6 安装前置校验 ──────────────────┐
4 Python 隔离 → 7 自检 ────────────────────┼→ 8 安装事务
5 awk/bc 适配 ─────────────────────────────┘
1+2+3+4+5+6+7+8 → 9 装配候选包 → 10 故障验收 → 11 跨系统证据与发布门禁
```

这是一个交付链，仍用一份计划；安装器、构建器或启动器单独完成都不能满足用户可安装这一验收。可独立推进 4/5/6 的实现，但只有用户选择多代理执行后才委派。

## 文件职责与稳定接口

| 创建/修改 | 路径 | 单一职责 |
|---|---|---|
| 创建 | `tools/offline/__init__.py`、`__main__.py` | 维护者 CLI 路由；不进入交付物 |
| 创建 | `tools/offline/model.py` | 锁/manifest 校验、规范 JSON、摘要与发行标识 |
| 创建 | `tools/offline/resolve.py` | 获取明确候选元数据、固定运行时和完整 wheel 集合 |
| 创建 | `tools/offline/archive.py` | 维护者侧安全读取、运行时规范化、确定性归档 |
| 创建 | `tools/offline/audit.py` | 许可证、ELF/ABI/CPU 检查和报告 |
| 创建 | `tools/offline/build.py` | 本地缓存装配、文件白名单、SHA256SUMS；禁止下载 |
| 创建 | `tools/offline/matrix.py` | 固定镜像验收及证据汇总/发布门禁 |
| 创建 | `packaging/offline/policy.json` | Python 系列、平台基线、extras、归档布局的可审查策略 |
| 创建 | `packaging/offline/runtime.lock.json` | 精确 CPython 补丁/构建/来源/上游与派生归档哈希 |
| 创建 | `packaging/offline/dependencies.lock.json` | 每个运行依赖 wheel 的版本、来源、标签、哈希和 marker 解析证据 |
| 创建 | `packaging/offline/requirements.lock` | 运行依赖完整精确版本和 wheel 哈希；qbox 项由候选构建补入 |
| 创建 | `packaging/offline/build-requirements.lock` | 维护者构建/审计工具及传递依赖的独立固定锁 |
| 创建 | `packaging/offline/licenses.lock.json` | 每个组件与许可证正文/NOTICE 的路径、来源、SHA-256 |
| 创建 | `packaging/offline/images.lock.json` | 构建/验证镜像 digest、OS 标识、基础包与 awk 实现 |
| 创建 | `packaging/offline/install.sh` | 完整 Bash 安装器；函数分为 preflight/payload/transaction 三组，公开接口只有两个路径参数 |
| 创建 | `packaging/offline/qbox-launcher.sh` | 从自身实际位置解析 release，固定 Python 后 exec |
| 创建 | `packaging/offline/checks/verify.py` | 用包内 stdlib/pip 的固定解析器检查安装清单、extras 与文件完整性 |
| 创建 | `packaging/offline/checks/smoke.py` | 真实科学依赖和 qbox 小数据功能自检 |
| 创建 | `packaging/offline/checks/fixtures/{silicon.cif,bands.dat.gnu,expected.json}` | 人工定义、可独立判断的小型验证数据，不含赝势 |
| 创建 | `packaging/offline/README.zh-CN.md` | 随包安装、故障、回退、卸载说明 |
| 修改 | `src/qbox/{cli.py,bin/qbox,legacy/load.sh,legacy/bootstrap.sh,legacy/dispatch.sh,postprocess/effective_mass_qe.py}` | 离线私有模式和所有内部 Python 隔离 |
| 修改 | `src/qbox/legacy/{unfold.sh,plot_common.sh,pw_settings.sh,input_phonon.sh}` | 便携 awk 和去除运行时 bc |
| 创建 | `tests/offline/{support.py,test_model.py,test_resolve.py,test_audit.py,test_launcher.py,test_bootstrap.py,test_checks.py,test_transaction.py,test_build.py,test_end_to_end.py,test_matrix.py}` | stdlib unittest；合成小载荷与真实候选包验证分开 |
| 创建 | `tests/offline/run-target.sh` | 最低基础系统上的真实归档安装与故障测试驱动 |
| 创建 | `tests/cases/test_portable_awk.sh` | 接入现有 Bash 回归的解析行为测试 |
| 修改 | `tests/python/{test_cli_registry.py,test_entrypoints.py,test_explicit_paths.py}` | 双模式、二次 Python、参数/退出码回归 |
| 修改 | `tests/README.md`、`README.zh-CN.md`、`README.md`、`docs/architecture.md`、`.gitignore` | 测试与用户说明、架构边界和构建输出忽略 |
| 创建 | `docs/releases/offline-build.md`、`docs/releases/offline-validation.md` | 可复现配方、已执行矩阵的索引和不通过项 |

构建输出统一放 `build/offline/`，候选包及其外部 `.sha256` 放 `dist/offline/`；两个目录均已由现有 ignore 大类覆盖，Task 9 只添加必要的明确说明。新增锁、配方、许可证索引、精简验收记录进入 Git；缓存、原始大日志、运行时和 wheel 不进入 Git。

公共维护者命令约定（Task 1 建路由，后续任务实现各子命令）：

```text
python -m tools.offline resolve --policy packaging/offline/policy.json --cache build/offline/cache
python -m tools.offline audit --cache build/offline/cache --output build/offline/audit
python -m tools.offline build --cache build/offline/cache --output dist/offline
python -m tools.offline matrix --candidate dist/offline/candidate.json --engine docker --output build/offline/evidence
python -m tools.offline gate --candidate dist/offline/candidate.json --evidence build/offline/evidence
```

`resolve` 是唯一允许联网的产品载荷工具；明确输出候选锁变更供本地审阅，不能覆盖已锁定版本而不展示差异。`build`/`audit`/`matrix`/`gate` 只消费已固定本地输入。维护者 Python 使用经过验证的独立开发环境，不能在执行计划时假定宿主 `/usr/bin/python3` 的依赖齐全。

### Task 1: 建立发行数据契约和不循环的哈希图

**Files:** 创建 `tools/offline/{__init__.py,__main__.py,model.py}`、`packaging/offline/policy.json`、`tests/offline/{support.py,test_model.py}`。

**Interfaces:**
- `canonical_json(value: dict) -> bytes`：UTF-8、排序 key、紧凑分隔符、末尾一个换行。
- `sha256_file(path: Path) -> str`；`safe_payload_path(value: str) -> str`：只允许相对 POSIX 路径及安全 ASCII 成员名。
- `release_id(version: str, identity: dict) -> str`：`<version>-<完整64位sha256>`。
- `validate_payload_files(files: list[dict]) -> None`：检查路径唯一、非负 size、SHA-256 格式；供 manifest 校验复用。
- `validate_manifest(value: dict) -> None`：不合法抛 `ValueError`，包括重复文件、缺 extras、URL 型 requirements 等。
- `tests/offline/support.py` 仅提供 `run(command, *, cwd, env=None, input="", timeout=20) -> subprocess.CompletedProcess` 和 `write_file(root, relative, text, mode=0o644) -> Path`；不探测 seekpath，不执行宿主科学程序。

- [ ] **Step 1：写失败测试，固定身份与路径边界。**

```python
import unittest
from tools.offline.model import canonical_json, release_id, safe_payload_path

class ModelTests(unittest.TestCase):
    def test_identity_is_stable_and_payload_sensitive(self):
        left = {"qbox_version": "0.1.0", "runtime_sha256": "a" * 64}
        self.assertEqual(canonical_json(left), canonical_json(dict(reversed(list(left.items())))))
        self.assertEqual(release_id("0.1.0", left), release_id("0.1.0", left))
        self.assertNotEqual(release_id("0.1.0", left),
                            release_id("0.1.0", dict(left, runtime_sha256="b" * 64)))

    def test_archive_paths_are_not_install_prefixes(self):
        self.assertEqual(safe_payload_path("runtime/python.tar.gz"), "runtime/python.tar.gz")
        for bad in ("/x", "../x", "a/../x", "a//x", "a\\b", "x\ny", "./x", ""):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                safe_payload_path(bad)
```

- [ ] **Step 2：运行 `python -m unittest discover -s tests/offline -p test_model.py -v`。** 预期因模块缺失失败；不要把测试环境缺解释器误当红灯。
- [ ] **Step 3：实现规范 JSON、路径和身份计算。** 成员名限制不影响安装前缀；前缀可包含空格和中文。示意核心是实际实现的下限：

```python
def canonical_json(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()

def safe_payload_path(value):
    parts = value.split("/")
    if not value or any(p in ("", ".", "..") for p in parts):
        raise ValueError("invalid relative payload path")
    if any(re.fullmatch(r"[A-Za-z0-9._+@=-]+", p) is None for p in parts):
        raise ValueError("unsupported archive member name")
    return value

def release_id(version, identity):
    if re.fullmatch(r"[0-9][A-Za-z0-9.+-]*", version) is None:
        raise ValueError("invalid version")
    return version + "-" + hashlib.sha256(canonical_json(identity)).hexdigest()
```

- [ ] **Step 4：写 manifest 完整性测试并实现 schema。** `schema_version=1`；`platform={os:linux,arch:x86_64,glibc_min:2.28,python_series:3.12,cpu_baseline:x86_64}`；`extras=[analysis,structure]`；`source={commit,dirty:false}`；`runtime`、`wheels`、`bootstrap_packages`、`licenses`、`files`、`identity`、`release_id`。每个载荷必须有相对路径、size、sha256、来源 URL 或项目提交及 license IDs，拒绝未知 schema 和重复路径。

```python
def test_manifest_rejects_duplicate_payload(self):
    entry = {"path": "checks/probe.txt", "size": 1,
             "sha256": hashlib.sha256(b"x").hexdigest()}
    with self.assertRaisesRegex(ValueError, "duplicate"):
        validate_payload_files([entry, dict(entry)])
```

`validate_manifest()` 必须调用同一 `validate_payload_files()`；再以完整字段构成的合成 manifest 分别删去 platform/extras/runtime/license 映射测试缺失字段，不能依赖后续真实下载来测试 schema。

- [ ] **Step 5：固定摘要依赖图并测试没有自引用。** identity 包含源码 commit、qbox wheel SHA、规范运行时 SHA、依赖/构建锁 SHA、安装器和启动器模板 SHA、自检/许可证文件 SHA。identity 不包含生成后的 manifest、SHA256SUMS 或外层归档；`manifest.json` 加入 `release_id` 后再计算其文件哈希；SHA256SUMS 覆盖除自身以外的全部常规文件；外部 `.sha256` 覆盖最终 tar.gz。安装标记另存实际 manifest SHA。来源信息不得带开发机绝对路径/账号。
- [ ] **Step 6：复跑 Task 1 测试后本地提交。**

```bash
python -m unittest discover -s tests/offline -p test_model.py -v
git add tools/offline packaging/offline/policy.json tests/offline/support.py tests/offline/test_model.py
git commit -m "build: define offline release manifest and identity"
```

### Task 2: 固定运行时、构建工具和两组 extras 的完整 wheel 集合

**Files:** 创建 `tools/offline/{resolve.py,archive.py}`、`packaging/offline/{runtime.lock.json,dependencies.lock.json,requirements.lock,build-requirements.lock,images.lock.json}`、`tests/offline/test_resolve.py`；修改 Task 1 CLI/策略。

**Interfaces:**
- 消费 Task 1 规范 JSON/路径接口。
- `allowed_wheel(filename: str, target_tags: set[packaging.tags.Tag]) -> bool`；兼容标签由固定 CPython 3.12 和 manylinux glibc≤2.28 生成，不用维护者宿主 `sys_tags()`。
- `target_tags() -> set[packaging.tags.Tag]`：以下明确平台集合与 CPython/兼容标签的并集。
- `resolve(policy: Path, cache: Path) -> dict`：返回所有候选锁路径和摘要；已存在锁需显示 diff，不静默升级。
- `normalize_runtime(upstream: Path, output: Path) -> dict`：安全读取上游安装树，输出 `python/` 根的 gzip tar，固定 owner/time；正规化后只保留目录和常规文件。

- [ ] **Step 1：写 tag、锁闭包和来源失败测试。**

```python
def test_wheel_policy_rejects_newer_or_unknown_linux(self):
    target = target_tags()
    self.assertTrue(allowed_wheel("demo-1.0-cp312-cp312-manylinux_2_28_x86_64.whl", target))
    self.assertTrue(allowed_wheel("demo-1.0-py3-none-any.whl", target))
    self.assertTrue(allowed_wheel("demo-1.0-cp39-abi3-manylinux2014_x86_64.whl", target))
    for name in ("demo-1.0-cp312-cp312-manylinux_2_34_x86_64.whl",
                 "demo-1.0-cp312-cp312-linux_x86_64.whl",
                 "demo-1.0-cp312-cp312-musllinux_1_2_x86_64.whl",
                 "demo-1.0-cp313-cp313-manylinux_2_28_x86_64.whl", "demo-1.0.tar.gz"):
        self.assertFalse(allowed_wheel(name, target), name)
```

再以本地合成 wheel METADATA 测 `qbox[analysis,structure] → a → b`、平台 marker、仅在 extra 激活时出现的依赖、循环依赖终止、缺一个 wheel、重复规范包名/不同版本、direct URL、sdist、哈希变化；直接写 zip fixture，不下载用来制造红灯。

- [ ] **Step 2：运行 `python -m unittest discover -s tests/offline -p test_resolve.py -v`，确认失败针对未实现接口。**
- [ ] **Step 3：实现固定候选选择和锁输出。** `resolve` 先读取官方 release API/PyPI JSON 保存元数据快照、请求日期和 SHA；只筛 CPython 3.12、baseline `x86_64-unknown-linux-gnu`、正式 release、`install_only`，排除 prerelease、v2/v3/v4/musl。在实现当日已发布且不晚于当日的候选中优先补丁版本较新者，再按构建日期排序；把选中候选的**实际**补丁号、tag、完整资产文件名、固定下载 URL、官方 digest/校验文件及本地计算 SHA 写入 `runtime.lock.json`。禁止把选择表达式、`latest`、空值或示例哈希写入最终锁；缺可核实校验资料就失败。维护者审阅具体锁后，后续构建只读锁。本文不伪造尚未获取的资产版本/哈希。wheel 标签实现采用：

```python
from packaging.tags import cpython_tags, compatible_tags
from packaging.utils import parse_wheel_filename

def target_tags():
    platforms = [f"manylinux_2_{minor}_x86_64" for minor in range(5, 29)]
    platforms += ["manylinux1_x86_64", "manylinux2010_x86_64", "manylinux2014_x86_64"]
    return set(cpython_tags((3, 12), abis=["cp312"], platforms=platforms)) | set(
        compatible_tags((3, 12), interpreter="cp312", platforms=platforms))

def allowed_wheel(filename, target_tags):
    try:
        _, _, _, tags = parse_wheel_filename(filename)
    except ValueError:
        return False
    return bool(tags & target_tags)
```
- [ ] **Step 4：实现下载缓存与运行时规范化。** 缓存按 SHA 分址，用临时文件下载、核对后原子改名；下载失败不留下可用标记。上游 tar 先用 Python `tarfile` 枚举所有成员：拒绝越界路径、设备/FIFO、重复成员、越界/循环链接。安全内部链接在维护者侧解引用为常规文件，复制目标的权限并记录映射；因此目标机 bootstrap 不需要处理链接。仅保留上游 install-only 的 Python 安装树，去掉可重新生成的 `__pycache__`/`.pyc`；不要从 `/usr/lib` 或开发 venv 补文件。上游许可证另保留到许可证材料，组件材料路径规范化为安全 ASCII 名但保留原正文和来源映射。转换前后用该运行时的 `-I -B` 验证 stdlib、SSL、ctypes、sqlite、pip 与 sysconfig，验证可移动；转换输出 SHA 单独锁定。
- [ ] **Step 5：在已固定的 glibc 2.28 基础构建环境、包内 CPython 中解析 extras。** 镜像以 digest 固定，记录平台完整 marker 环境。先构建本地 qbox wheel，再运行如下参数等价命令，所有文件变量由 resolver 内部解析成绝对路径，不由用户填版本通配符：

```python
command = [python_path, "-I", "-B", "-m", "pip", "--isolated",
           "--disable-pip-version-check", "download", "--only-binary=:all:",
           "--dest", str(candidate_wheelhouse),
           "--find-links", str(qbox_wheel.parent),
           f"qbox[analysis,structure]=={qbox_version}"]
subprocess.run(command, env=pip_environment, check=True)
```

以上变量均是 `resolve()` 的局部值：`python_path` 来自规范运行时，`candidate_wheelhouse=cache/'candidate-wheelhouse'`，`qbox_wheel` 是固定源码构建结果，`qbox_version` 从其 METADATA 读取。`pip_environment` 删除全部 `PIP_*` 后设置 `PIP_CONFIG_FILE=/dev/null`。对每个结果再执行 `allowed_wheel()` 和 METADATA 验证；当前环境恰好能安装不构成通过。依赖不兼容时选可兼容的已发布版本并在锁 diff 中解释，不能自动源编译或提升基线。
- [ ] **Step 6：锁定整个闭包并执行一次无网络重装验证。** 解析 METADATA `Requires-Dist` 的 extras/marker 闭包，写每个规范名称的一个精确版本、选中 wheel SHA/URL/tag；requirements 每行形如 `name==version --hash=sha256:<由该文件计算的摘要>`，禁止 URL、editable、`-r` 外部引用。runtime 原带 pip 及 vendored 组件单列 `bootstrap_packages`，既不遗漏也不混入应用锁。构建依赖 `build/setuptools/wheel/packaging/auditwheel` 及闭包另锁，不能提高源码 pyproject 的最低版本约束来迁就构建机。

```python
line = f"{name}=={version} --hash=sha256:{sha256_file(wheel)}\n"
assert "://" not in line and " @ " not in line
```

- [ ] **Step 7：复跑合成测试，审查具体锁 diff，记录无网络重装结果并本地提交。** 缺下载权限/网络时仅完成代码和合成测试，明确锁和候选包仍未完成，不用测试哈希冒充正式锁。

```bash
python -m unittest discover -s tests/offline -p test_resolve.py -v
git diff --check
git add tools/offline packaging/offline tests/offline/test_resolve.py
git commit -m "build: pin standalone Python and offline dependency closure"
```

### Task 3: 审计全部许可证、原生库闭包和 CPU/ABI 基线

**Files:** 创建 `tools/offline/audit.py`、`packaging/offline/licenses.lock.json`、`tests/offline/test_audit.py`；修改维护者 CLI。

**Interfaces:** `audit(cache: Path, output: Path) -> dict`；返回 `license_report_sha256`、`elf_report_sha256`、`status`；任一缺项非零退出。`inspect_elf(path: Path) -> dict` 返回 `needed/rpath/runpath/version_needs/isa`。报告按载荷相对路径标识，不包含本机路径。

- [ ] **Step 1：写审计红灯测试。** 测试 `readelf` 输出解析只使用固定文本 fixture；测试许可证用合成 wheel。fixture 包含 GLIBC_2.28/2.29、GLIBCXX、CXXABI、GNU ISA needed v2、绝对 RPATH、未解析 NEEDED，以及 wheel 中附带 `.libs/libopenblas.so` 的案例。

```python
def test_missing_native_license_is_not_hidden_by_package_license(self):
    report = {"components": [
        {"id": "demo", "licenses": ["MIT"]},
        {"id": "demo/.libs/libblas.so", "licenses": []},
    ]}
    with self.assertRaisesRegex(ValueError, "libblas"):
        validate_license_inventory(report)

def test_glibc_comparison_is_numeric(self):
    self.assertTrue(glibc_allowed("GLIBC_2.9", (2, 28)))
    self.assertFalse(glibc_allowed("GLIBC_2.29", (2, 28)))
```

`validate_license_inventory(report)`、`glibc_allowed(symbol, baseline)` 在本任务 `audit.py` 定义；只检查 ELF **所需符号版本**，不把库提供的版本符号误认成需求。

- [ ] **Step 2：运行 `python -m unittest discover -s tests/offline -p test_audit.py -v` 确认红灯。**
- [ ] **Step 3：实现许可证库存。** 从 runtime 的上游许可证元数据/正文、wheel 的 dist-info licenses/NOTICE 和原生供应库材料建立组件→许可证文件映射；名称/SPDX 字段不代替正文。pip vendored 包、OpenSSL、libffi、压缩库、BLAS/OpenMP/C++ runtime 等实际存在组件均逐项覆盖；缺正文可从同版本官方源码取得并核验来源，进入材料缓存。需要额外声明/源码提供的许可证义务必须有对应材料，无法确认则阻止发行；不默认所有上游依赖都是 MIT。
- [ ] **Step 4：实现静态闭包审计。** 枚举运行时及所有 wheel 的全部 ELF，运行 `readelf -h -d --version-info -n`；native wheel 另运行 `auditwheel show`。检查机器 x86_64、GLIBC≤2.28、禁止不明 linux tag、非相对 RPATH、绝对开发路径；GLIBCXX/CXXABI 也在最低系统上验证，不能只查 GLIBC。每个 DT_NEEDED 必须解析至包内相对库或明确的基础系统库清单，不解析到维护者 Conda/oneAPI 路径。RPATH 修补或额外带库需要来源/许可/新摘要和再次审计，首选改用兼容 wheel；禁止全局 LD_LIBRARY_PATH。
- [ ] **Step 5：验证 CPU 基线而非仅检查标签。** 拒绝声明必须 v2/v3/v4 的 ELF GNU property；对缺 ISA 声明的 native wheel 记录无法靠静态检查证明的限制。Task 11 在屏蔽 AVX/SSE4 等扩展的 baseline x86_64 VM/QEMU CPU 模型运行实际自检，记录 CPU flags；容器使用宿主 CPU，不可替代此项。允许库按检测结果使用高阶优化分支，但 baseline 路径必须可运行。
- [ ] **Step 6：跑真实已锁载荷审计和测试，本地提交。**

```bash
python -m unittest discover -s tests/offline -p test_audit.py -v
python -m tools.offline audit --cache build/offline/cache --output build/offline/audit
git add tools/offline/audit.py tools/offline/__main__.py packaging/offline/licenses.lock.json tests/offline/test_audit.py
git commit -m "build: audit offline licenses and native compatibility"
```

### Task 4: 贯通离线 Python 隔离，同时保留普通安装契约

**Files:** 创建 `packaging/offline/qbox-launcher.sh`、`tests/offline/test_launcher.py`；修改 `src/qbox/cli.py`、`src/qbox/bin/qbox`、`src/qbox/legacy/{load.sh,bootstrap.sh,dispatch.sh}`、`src/qbox/postprocess/effective_mass_qe.py`、`tests/python/{test_cli_registry.py,test_entrypoints.py,test_explicit_paths.py}`。

**Interfaces:** 私有 `_QBOX_OFFLINE_ROOT` 为规范绝对 release 路径，`QBOX_PYTHON` 为该 release 的 `python/bin/python3`；只由安装器/离线入口设置。所有内部 Python 使用 `-I -B`；普通安装没有私有标记时维持原分支。公开命令仍仅 `qbox`，不新增用户配置变量。

- [ ] **Step 1：写 CLI 边界红灯测试。** 在现有 mock exec 测试中增加离线分支；测试夹具在临时目录创建 metadata 安装标记，模拟合法 release。保留全部旧 `QBOX_SHARED_ROOT`/显式 Python 测试，不能把旧断言改成离线语义。

```python
def test_offline_exec_keeps_external_environment(self):
    # self.release 来自本测试 setUp 创建的临时合法 release。
    original = {"_QBOX_OFFLINE_ROOT": str(self.release),
                "QBOX_PYTHON": str(self.release / "python/bin/python3"),
                "PYTHONPATH": "/external/python-libs", "PYTHONHOME": "/external/python",
                "PATH": "/mpi/bin:/usr/bin:/bin", "LD_LIBRARY_PATH": "/mpi/lib",
                "OMPI_MCA_btl": "self,tcp", "QBOX_QE_ENV_SCRIPT": "/external/qe.sh"}
    with patch.dict(os.environ, original, clear=True), patch("qbox.cli.os.execvpe") as execute:
        cli.main(["--task", "6", "input with spaces.in"])
    forwarded = execute.call_args.args[2]
    for key in ("PATH", "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME",
                "OMPI_MCA_btl", "QBOX_QE_ENV_SCRIPT"):
        self.assertEqual(forwarded[key], original[key])
```

单独 mock `subprocess.call` 验证 `effective_mass_qe.main()` 构造的命令在离线时含 `[sys.executable,"-I","-B",script]`，普通模式保持旧行为；用现有显式路径测试的小能带数据触发，不能只检查源代码字符串。

- [ ] **Step 2：运行新增 CLI/显式路径测试，确认因环境注入/缺少隔离参数失败。** 开发 Python 需先按 Task 2 准备，但此处不启动 QE。

```bash
python -m unittest discover -s tests/python -p test_cli_registry.py -v
python -m unittest discover -s tests/python -p test_explicit_paths.py -v
```

- [ ] **Step 3：实现公共离线启动器。** 路径通过启动器的物理路径解析，不通过 cwd、PATH、Conda 或共享根猜测；显式 QBOX_PYTHON 可为指向同一包内解释器的软链接，其他值失败。以下核心逻辑放在 `qbox-launcher.sh`，错误诊断用中文并说明 `unset QBOX_PYTHON`。

```bash
#!/usr/bin/env bash
set -u
launcher=$(readlink -f -- "${BASH_SOURCE[0]}") || exit 1
release=$(cd -- "$(dirname -- "$launcher")/.." && pwd -P) || exit 1
python="$release/python/bin/python3"
if [[ ! -x "$python" || ! -f "$release/metadata/installed.json" ]]; then
    printf 'qbox：安装不完整，请重新验证本版本。\n' >&2
    exit 1
fi
if [[ -n ${QBOX_PYTHON:-} ]] &&
   [[ $(readlink -f -- "$QBOX_PYTHON" 2>/dev/null) != $(readlink -f -- "$python") ]]; then
    printf 'qbox：QBOX_PYTHON 指向包外解释器，请先执行 unset QBOX_PYTHON。\n' >&2
    exit 2
fi
export _QBOX_OFFLINE_ROOT="$release" QBOX_PYTHON="$python"
exec "$python" -I -B -m qbox "$@"
```

`installed.json` 在暂存验证前以 `state=prepared` 写出，最终验证后成为 `state=verified`；Task 8 定义内容。入口验证它属于本 release，不能仅凭同名文件信任用户伪造的普通目录；私有标记不承担对同一用户恶意进程的安全隔离。

上述 shell 只负责先验文件检查；进入 `cli.main()` 后，用 stdlib 读取 marker/manifest，核对 product、release-id、manifest SHA，核对 `Path(sys.prefix).resolve()==root/'python'`、`package_dir` 位于这个 Python 安装目录且 `sys.flags.isolated` 为真，再处理离线参数。普通模式不执行这些判断。mock CLI 边界测试同时模拟对应的 sys.prefix/sys.flags/package_dir，真实解释器路径验证由 Task 10 覆盖；不能为方便 mock 降低生产校验。

- [ ] **Step 4：修改 CLI/load/bootstrap 三个环境入口。** 离线时 CLI 使用实际包版本和名称 `qbox`，不让宿主 `QBOX_NAME/QBOX_VERSION` 冒充发行身份；跳过 PYTHONPATH 注入；使用已设置包内解释器。`load.sh` 同样跳过注入。`bootstrap.sh` 保留外部 Multiwfn/赝势/QE/oneAPI 变量与发现方式，但不把 `script_dir` 或 Python bin 加 PATH，不在变量原本不存在时导出空的 `QBOX_SHARED_ROOT`。已有共享根可以保留外部 Multiwfn 默认语义，绝不能覆盖已固定 Python。

```python
offline = bool(env.get("_QBOX_OFFLINE_ROOT"))
if not offline:
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = package_parent + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
```

离线 `MPLCONFIGDIR` 优先尊重用户指定且可写的位置，否则在可写的绝对 `XDG_CACHE_HOME` 或 `$HOME/.cache/qbox/matplotlib` 建立目录；最终 fallback 用用户 TMPDIR 下独占 `mktemp -d`，不能复用不明归属的共享固定目录。每个分支都验证可写；无法建立时明确失败。不要全局清空 Python 环境变量，它们须继续传给外部程序。

- [ ] **Step 5：修改内部调用点和递归入口。** `qbox_python` 离线分支核对 QBOX_PYTHON 与私有根，再调用 `"$QBOX_PYTHON" -I -B "$@"`；普通分支不变。包内 `bin/qbox` 在离线模式不设置 PYTHONPATH，复用固定 Python 并 exec；`effective_mass_qe.py` 子进程显式传 `-I -B`。PDOS `.py` 继续由 `qbox_python` 执行，离线安装时不将包 bin 加 PATH，并去掉内部 `.py` 兼容脚本的可执行位，不将它作为直接命令宣传；普通 wheel/源码的直接辅助入口仍保留。
- [ ] **Step 6：写并通过进程行为测试。** 临时 release 的 Python 记录替身写出 argv、cwd、stdin、PID/PPID，断言空格/数字参数无变化、stdin 完整、退出 17 原样返回、exec 不多留父包装进程。真实包测试在 Task 10 验证 `sys.flags.isolated==1`、污染目录 `sitecustomize.py` 和同名 qbox/numpy 不执行，以及递归解释器标记一致。错误显式 QBOX_PYTHON、坏私有标记、旧共享根分别测试。
- [ ] **Step 7：运行本任务与旧入口测试后本地提交。**

```bash
python -m unittest discover -s tests/offline -p test_launcher.py -v
python -m unittest discover -s tests/python -p 'test_*paths.py' -v
python -m unittest discover -s tests/python -p 'test_*entry*.py' -v
python -m unittest discover -s tests/python -p test_cli_registry.py -v
git add packaging/offline/qbox-launcher.sh src/qbox tests/python tests/offline/test_launcher.py
git commit -m "feat: isolate bundled Python across qbox entrypoints"
```

### Task 5: 修复 mawk/gawk 差异并消除安装环境对 bc 的要求

**Files:** 修改 `src/qbox/legacy/{unfold.sh,plot_common.sh,pw_settings.sh,input_phonon.sh}`；创建 `tests/cases/test_portable_awk.sh`；更新 `tests/README.md` 的已知输入边界。

**Interfaces:** 原函数 `qe_unfold_read_nbnd(file)`、`qe_estimate_atom_count(prefix)`、`read_upf_cutoffs(file)` 不改签名。新增局部职责函数 `qe_frequency_is_positive(value)` 返回 0=正、1=零/负、2=输入不属于支持的十进制形式。原气相热力学写入函数先验证全部频率，遇 2 在写 `.shm` 前失败，诊断明确指数输入未获支持。

- [ ] **Step 1：写大小写和频率边界红灯测试。** 按现有 `test_helper.sh`/`run_test` 风格，调用真实函数，不复制 awk 表达式到测试中。

```bash
test_uppercase_nbnd_and_nat() (
    local sandbox
    sandbox=$(new_sandbox) || return 1
    cd "$sandbox" || return 1
    source_qbox || return 1
    printf '&SYSTEM\n  NBnD = 12,\n  NAT = 3,\n/\n' > cell.scf.in
    assert_eq 12 "$(qe_unfold_read_nbnd cell.scf.in)" || return 1
    assert_eq 3 "$(qe_estimate_atom_count cell)"
)
test_decimal_frequency_contract() (
    source_qbox || return 1
    qe_frequency_is_positive 0.125 || return 1
    qe_frequency_is_positive .5 || return 1
    qe_frequency_is_positive -0.25; assert_eq 1 "$?" || return 1
    qe_frequency_is_positive 0.0; assert_eq 1 "$?" || return 1
    qe_frequency_is_positive 1e-20; assert_eq 2 "$?" || return 1
    qe_frequency_is_positive 1D-20; assert_eq 2 "$?"
)
```

增加注释行/首个匹配/逗号/空行/未命中用例；`nat` 保持已有 `$3` 语法及 fallback，不借机重写 namelist。UPF 测大小写 `WFC_CUTOFF/RHO_CUTOFF`、`40.0D+0`、`3.2E2` 与输出 `40 320`。既有 `read_upf_cutoffs` 对文本描述分支的任何独立缺陷记为既有问题，不顺手改单位或推断。
- [ ] **Step 2：在 mawk 环境运行 `bash tests/cases/test_portable_awk.sh`，确认大小写用例和未定义辅助函数失败。** 在开发基线记录 GNU bc 对十进制、`+.5`、`1e-20`、`1E-20`、`1D-20` 的原输出和 stderr，保存到测试说明，明确指数原行为不可靠。bc 仅是一次开发期比较工具，不能出现在目标测试前置要求中。
- [ ] **Step 3：实现大小写匹配最小替换。** `nbnd/nat` 的匹配表达式将输入改为 `tolower($0)`，保留对原 `$0/$3` 的取值；UPF 将匹配用 line 转小写，保持原数值变换顺序与输出格式。

```awk
tolower($0) ~ /^[[:space:]]*nbnd[[:space:]]*=/ {
    line=$0; sub(/^[^=]*=/,"",line); gsub(/[,[:space:]]/,"",line)
    print line; exit
}
```

- [ ] **Step 4：实现便携频率判断，保持十进制值文本。** 用字符串判断正负/非零，避免把很小但非零的十进制数转换成浮点零；不求值任何表达式。

```bash
qe_frequency_is_positive() {
    printf '%s\n' "$1" | LC_ALL=C awk '
        NR != 1 {bad=1}
        NR == 1 {v=$0; sub(/^[[:space:]]+/, "", v); sub(/[[:space:]]+$/, "", v)}
        END {
            if (bad || v !~ /^-?([0-9]+([.][0-9]*)?|[.][0-9]+)$/) exit 2
            if (v !~ /^-/ && v ~ /[1-9]/) exit 0
            exit 1
        }'
}
```

在写入函数中用显式 `case "$status" in 0|1|2)` 处理，不让 shell `set -e` 把“非正”当内部失败。原十进制输出按字节保持；指数/无效频率失败必须在截断已有 `.shm` 前，测试已有文件不变。
- [ ] **Step 5：运行 mawk 与 Rocky 默认 awk 两组测试，并禁止 bc 命中。** 用受控 PATH 中 `bc` 失败替身记录调用；气相热力学 fixture 的 `.shm` 与旧十进制 golden 相同。运行原 `test_phonon_writers.sh`、UPF/输入生成相关回归；界面文字中的 bc 历史示例不等于可执行依赖。
- [ ] **Step 6：本地提交。**

```bash
bash tests/cases/test_portable_awk.sh
bash tests/cases/test_phonon_writers.sh
bash tests/cases/test_pw_generation.sh
git add src/qbox/legacy tests/cases/test_portable_awk.sh tests/README.md
git commit -m "fix: make offline shell parsing portable across awk implementations"
```

### Task 6: 实现无需宿主 Python 的前置检查和安全展开

**Files:** 创建 `packaging/offline/install.sh`、`tests/offline/test_bootstrap.py`；扩展 `tools/offline/archive.py` 与合成归档测试。

**Interfaces:** Bash 函数 `parse_options "$@"`、`preflight_platform`、`preflight_paths`、`verify_bundle_files "$bundle"`、`inspect_runtime_archive "$archive"`、`extract_runtime "$archive" "$stage"`；失败非零且中文诊断。脚本仅当 `BASH_SOURCE[0]==$0` 才执行 `main`，测试 source 函数无写入副作用；不新增生产故障注入环境开关。

- [ ] **Step 1：写参数/平台红灯测试。** 通过 subprocess 调用真实 Bash 安装入口，源文件不存在先红灯。测试 `--prefix` 缺值、重复参数、未知参数、相对路径、空值、根目录、不支持架构、Bash 版本低于 4.4、glibc 2.27、glibc 2.28/2.31/2.9 数值比较和缺基础命令。平台读取函数可 source 后替换 `uname`/探测函数进行单测，不把测试探测接口做成安装器公开参数。

```python
def test_relative_prefix_is_rejected_without_writes(self):
    with tempfile.TemporaryDirectory() as directory:
        result = subprocess.run(["bash", str(INSTALL), "--prefix", "relative"],
                                cwd=directory, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("绝对路径", result.stderr)
        self.assertEqual(list(Path(directory).iterdir()), [])
```

`INSTALL = Path(__file__).resolve().parents[2] / 'packaging/offline/install.sh'` 在此测试模块顶层定义。

- [ ] **Step 2：运行 `python -m unittest discover -s tests/offline -p test_bootstrap.py -v` 验证失败。**
- [ ] **Step 3：实现平台和路径检查。** 检查 Bash 内建版本、`uname -s/-m` 和 coreutils/grep/sed/awk/tar/gzip 所需具体命令。glibc 优先用可用的 `getconf GNU_LIBC_VERSION`，否则执行已存在的 `/lib64/ld-linux-x86-64.so.2 --version` 或 `/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 --version`，按已测试发行格式解析；没有可靠结果则明确失败。不要新增 `ldd`、`file`、`flock`、`rg`、`find`、`bc` 或宿主 Python 前置要求。提取后再由包内 `os.confstr('CS_GNU_LIBC_VERSION')` 复核。

路径用 `readlink -m` 解析现有祖先，保留路径中的空格/中文，拒绝换行等控制字符、`/` 和不安全重叠（如 bin-dir 位于 releases/current/暂存目录）。prefix 仅接受不存在、空目录或已有合法根标记的目录；非 qbox 内容不接管。父路径 symlink 规范化后再检查；用户可写不等于可接管。所有 shell 参数加双引号及 `--`，不用 eval。
- [ ] **Step 4：写危险归档测试，再实现严格目录和哈希验证。** 合成 ustar/gzip 包分别含 `../outside`、`/absolute`、内部/外部符号链接、硬链接、FIFO、重复成员、文件作为父目录、被转义的换行文件名和 `python/../x`；每个测试重新生成 SHA256SUMS，证明不是单纯哈希失败。传入展开函数后检查 stage 外的 sentinel 完全未变。

```python
def test_traversal_is_rejected_even_with_fresh_digest(self):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        archive = root / "runtime.tar.gz"
        with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as output:
            member = tarfile.TarInfo("../outside")
            member.size = 1
            output.addfile(member, io.BytesIO(b"x"))
        result = subprocess.run(["bash", "-c",
            'source "$1"; inspect_runtime_archive "$2"', "archive-test", str(INSTALL), str(archive)],
            text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((root / "outside").exists())
```

- [ ] **Step 5：实现 bootstrap 归档语法。** 维护者规范化归档只允许 `python/` 根、普通文件和目录、安全 ASCII 名；installer 用 GNU tar **列举，不展开**：`LC_ALL=C tar --list --verbose --numeric-owner --full-time --quoting-style=escape --absolute-names --gzip --file "$archive"`。严格解析模式/owner/size/date/time/name 六列，只接受普通/目录类型、owner `0/0`、无特殊位、无反斜杠转义、无空白名称；目录名仅允许先去掉一个末尾 `/` 后校验，文件不能这样处理。`safe_payload_path` 的 Bash 等价校验拒绝空分段、`.`、`..`、重复成员、非目录祖先及 python 根之外成员；根只能是目录 `python`。stderr 非空、tar 返回非零、非支持格式均失败。GNU/PAX 影响后的有效名称也必须通过相同检查；不解析链接目标，不给链接例外。GNU tar 每个平台的输出解析都有 fixture 和真实归档测试。

校验 SHA256SUMS 时每行必须是 64 位小写十六进制、两个空格和安全相对路径；限制顶层白名单；用 Bash `globstar/dotglob/nullglob` 枚举已解包 bundle，拒绝 symlink/特殊文件/多余或遗漏文件，SHA256SUMS 自身除外。先校验再执行随包 checks；不信任 manifest JSON 中的 shell 代码，不 source manifest。外层 tar 在发布端保证同样安全；安装器不能追溯保护用户在运行它之前已经执行的错误解压操作。
- [ ] **Step 6：实现受限展开。** Task 8 在锁内创建新 stage，复制 runtime 到 stage 中的独占输入文件并重新核对 SHA，再对该副本列举和展开；拒绝向已有 Python 树叠加。检查必需解释器文件后清除 stage 中的归档副本；发生错误只移除本次归属可证的 stage。

```bash
tar --extract --gzip --file "$runtime_copy" --directory "$stage" \
    --no-same-owner --no-same-permissions --delay-directory-restore
```
- [ ] **Step 7：运行测试和 Bash 语法检查，本地提交。**

```bash
bash -n packaging/offline/install.sh
python -m unittest discover -s tests/offline -p test_bootstrap.py -v
git add packaging/offline/install.sh tools/offline/archive.py tests/offline/test_bootstrap.py
git commit -m "feat: validate offline payload before extracting bundled Python"
```

### Task 7: 编写无外部计算软件的安装后自检

**Files:** 创建 `packaging/offline/checks/{verify.py,smoke.py,fixtures/silicon.cif,fixtures/bands.dat.gnu,fixtures/expected.json}`、`tests/offline/test_checks.py`。

**Interfaces:**
- `verify.py --release DIR --manifest FILE --phase prepared|final|reuse`：用包内 stdlib 和已固定 pip 的 vendored packaging，检查版本/安装文件/必需模块资源与 extras 闭包，输出 JSON 检查项，非零即安装失败。
- `smoke.py --release DIR --work DIR`：用包内 Python `-I -B` 执行；运行实际科学功能，结果写 work；不改安装树。
- 自检报告 `schema_version,release_id,manifest_sha256,phase,checks[{name,status,detail}]`；失败不得被 import fallback 隐藏。

- [ ] **Step 1：写资源/extras 缺失红灯测试。** 使用 `importlib.metadata` distribution fixture 或合成 dist-info 树，测试只做 pip check 本会漏掉的 qbox analysis/structure 依赖、版本约束不满足、marker 分支、缺 `legacy/entry.sh`/`bin/qbox`、错误 manifest、损坏安装文件。`verify.py` 显式遍历 manifest 已解析边及实际 METADATA（含启用的 extras）；固定使用 `pip._vendor.packaging` 的 Requirement/SpecifierSet/Marker 接口，随锁定 pip 验证这个私有 API，不额外依赖宿主 packaging，不能解析失败后绕过检查。

```python
def test_missing_structure_extra_fails(self):
    edges = [{"parent": "qbox", "extra": "structure", "name": "ase", "specifier": ">=3"}]
    installed = {"qbox": "0.1.0", "numpy": "2.0.0"}
    with self.assertRaisesRegex(ValueError, "ase"):
        verify_dependency_edges(edges, installed)
```

`verify_dependency_edges(edges, installed) -> None` 在 `verify.py` 定义；测试用 importlib 按绝对文件加载，模块导入不得自动执行 main。
- [ ] **Step 2：运行 `python -m unittest discover -s tests/offline -p test_checks.py -v` 确认红灯。**
- [ ] **Step 3：实现文件/元数据检查。** 检查 `sys.executable`、3.12 补丁与 manifest、实际 distributions/versions、lock 边完整性、bootstrap packages、包路径全在 release 内、所有 Bash/Python 资源。`pip check` 作为额外一步，不能取代 extras 检查。prepared 阶段建立不可变文件清单；final/reuse 用 SHA 和模式逐项比较；不散列用户缓存，清单本身不自引用。安装时用 `--no-compile`/Python `-B` 防止在改名后制造多余 bytecode。
- [ ] **Step 4：写真实功能 oracle，然后实现 smoke。** fixture `silicon.cif`：立方 5 Å、一个 Si 位于 `(0,0,0)`；`bands.dat.gnu` 为两条带 `[(0,-2),(1,-1)]` 和 `[(0,1),(1,3)]`。`expected.json` 固定元素、原子数、晶格/体积容差、VBM/CBM 文本、Gamma 点/路径点数规则，不从当次程序输出自动更新 golden。

```python
import numpy as np
from scipy.linalg import solve
np.testing.assert_allclose(solve([[3., 1.], [1., 2.]], [9., 8.]), [2., 3.], rtol=1e-12)
from ase.io import read
from pymatgen.core import Structure
atoms = read(str(cif_path))
structure = Structure.from_file(cif_path)
assert atoms.get_chemical_symbols() == ["Si"]
assert len(structure) == 1
assert abs(atoms.get_volume() - 125.0) < 1e-8
assert abs(structure.volume - 125.0) < 1e-8
```

`cif_path` 为 `smoke.py` 同目录 fixtures 文件，不依赖 cwd。额外执行：NumPy BLAS 小矩阵乘法、SciPy 上述 LAPACK 求解；Matplotlib Agg 保存 PNG 并验证 PNG 头/非空尺寸；直接调用 seekpath 获得 Gamma 和非空合法路径；分别通过 `qbox.io.convert_ase`、`convert_pymatgen` 和 `convert_basic` 转换并回读，不允许失败后 fallback 掩盖某组依赖不可用；执行 `qbox.io.kpath` 验证 `K_POINTS` 与坐标；`qbox.postprocess.band_edges` 比较精确 VBM/CBM 输出。原生组件再按 Task 3 清单运行各自导入/最小调用探针，如 spglib；不能把加载 ELF 文件代替 Python extension import。
- [ ] **Step 5：在无 DISPLAY、带污染 PYTHONPATH、工作树之外执行 smoke。** work 为专用临时目录；传入只读 release 时仍通过；`sys.path` 不含当前计算目录/用户 site。安装过程把所有输出留在临时检查目录，成功后可删，自检报告写 metadata。不调用真实 `pw.x/mpirun/Multiwfn/unfold.x`，也不访问在线数据/API。
- [ ] **Step 6：通过检查测试并提交。**

```bash
python -m unittest discover -s tests/offline -p test_checks.py -v
git add packaging/offline/checks tests/offline/test_checks.py
git commit -m "test: verify offline extras and scientific smoke results"
```

### Task 8: 实现离线安装、版本复用与失败回退事务

**Files:** 修改 `packaging/offline/install.sh`；创建 `tests/offline/test_transaction.py`。

**Interfaces:** 消费 Task 6 preflight/校验/展开、Task 4 启动器和 Task 7 自检。新增 Bash 函数 `acquire_install_lock`、`install_wheels`、`verify_release`、`publish_release`、`cleanup_transaction`。`main` 显式顺序调用并检查每一步返回值，不只依赖 `set -e`。磁盘接口如下：

```text
prefix/.qbox-root                    根归属标记（格式版本、uid、规范prefix）
prefix/.install-lock/                mkdir互斥锁，owner文件记录本次token/PID
prefix/.stage.<随机值>/              独占stage及事务归属标记
prefix/releases/<release-id>/python/
prefix/releases/<release-id>/bin/qbox
prefix/releases/<release-id>/metadata/{installed.json,manifest.json,installed-files.json,checks/,THIRD_PARTY_LICENSES/}
prefix/current -> releases/<release-id>
bin-dir/qbox -> prefix/current/bin/qbox
```

`installed.json`：`schema_version=1,product=qbox,release_id,manifest_sha256,state=prepared|verified,inventory_sha256`。事务 token/已创建目录列表仅存本次 stage/锁内，不包装进公共发行物。根标记是目录归属证据，不是权限安全边界。

- [ ] **Step 1：写顺序/回退红灯测试。** 在临时目录 source installer；替换 `install_wheels`/`verify_release` 为记录行为的函数，测试实际 `main`/publish/cleanup；已有老版本用真实文件+合法 marker+symlink，绝不指向用户真实部署。每个测试保存旧 symlink 文本和用户文件 SHA。

```python
def test_failed_final_path_check_keeps_current(self):
    # setUp 建立 temp/prefix 的 old release、current 和 bin/qbox；bundle 为本地小fixture。
    old_target = os.readlink(self.prefix / "current")
    old_bytes = self.sentinel.read_bytes()
    result = self.run_transaction(fail_phase="final-verify")
    self.assertNotEqual(result.returncode, 0)
    self.assertEqual(os.readlink(self.prefix / "current"), old_target)
    self.assertEqual(self.sentinel.read_bytes(), old_bytes)
    self.assertEqual(list(self.prefix.glob(".stage.*")), [])
```

`run_transaction(fail_phase)` 是本测试类方法，构造 Bash 脚本 source 安装器并覆盖对应函数返回 73，其余照常；失败阶段只存在于测试脚本。另测 preflight/pip/prepared-check/final-move/final-check/bin-link/current-switch 任一阶段失败、same-version reuse、损坏旧版、无关同名目录、命令普通文件/断链/外部链接及两个 prefix 争同一 bin-dir。
- [ ] **Step 2：运行 `python -m unittest discover -s tests/offline -p test_transaction.py -v` 确认预期失败。**
- [ ] **Step 3：实现根目录锁和归属记录。** preflight 初查后在 prefix 用原子 `mkdir .install-lock`，失败立即中文报告“安装进行中或遗留锁”，不等待/自动抢锁。获取锁后重新检查所有目标归属；用 `mktemp -d "$prefix/.stage.XXXXXXXX"` 创建 stage 并记录 token。清理函数只操作本次创建且 token/规范路径匹配的对象；不沿 symlink 递归删除。新建父目录只在仍为空且由本次创建时用 `rmdir` 清理；不删除他人后加入的文件。并发 loser 不清理 winner 的锁。
- [ ] **Step 4：实施包内 pip 安装。** `requirements.lock` 已由 Task 9 补入带哈希的 `qbox[analysis,structure]==版本`，轮子分别位于 packages 和 wheelhouse。只在安装子 shell 清理 pip 配置变量，不改用户 shell 或启动外部程序的环境。

```bash
install_wheels() (
    local variable
    while IFS= read -r variable; do unset "$variable"; done < <(compgen -v PIP_)
    export PIP_CONFIG_FILE=/dev/null
    "$stage/python/bin/python3" -I -B -m pip --isolated --disable-pip-version-check \
        install --no-index --only-binary=:all: --require-hashes \
        --no-cache-dir --no-compile --ignore-installed \
        --find-links "$bundle/packages" --find-links "$bundle/wheelhouse" \
        -r "$bundle/requirements.lock"
)
```

`stage`、`bundle` 是 main 内已验证的规范路径，传入函数前赋值；所有 exit code 显式检查。`--ignore-installed` 使运行时预装包不能隐藏缺 wheel；不安装 sdist、不执行 setup.py、不运行 ensurepip 联网、不调用宿主 pip、不通过 pip freeze 建锁。真实锁定 pip 必须经 Task 10 的全局/用户配置污染试验证实这些参数组合有效。
- [ ] **Step 5：安装入口与元数据，完成两次验证。** 从已校验 `checks/qbox-launcher.sh` 复制到 stage/bin/qbox，复制 manifest、全部许可证和 checks；将内部辅助 Python 脚本改为只读数据式权限。创建 prepared marker，运行 pip check、Task 7 verify/smoke、入口三项检查；清除 stage 输入副本及临时输出，建立 installed-files 清单。目标 release 已存在时只允许完整验证后复用，不覆盖/修补损坏版本。

新 release 用同一文件系统上的 rename 移动到尚不存在的 final 路径；重新以 final 路径执行三项入口和完整 smoke/verify，检查临时路径已经不可访问仍能工作。安装器自己的验证子进程明确设 QBOX_PYTHON 为待验证版本的解释器、私有根为该版本、取消 QBOX_TEST_MODE，防止继承用户的调试设置造成假通过；真实用户覆盖冲突另在 Task 10 测试。普通 pip console shebang 不作为公共入口；删除/替换包内生成的 `python/bin/qbox`，公共入口只用 bin/qbox。其余私有 pip console scripts 不公开、不加 PATH，自检均通过 `python -m` 调用。最终成功后写 verified marker。
- [ ] **Step 6：实现入口事务提交。** existing bin/qbox 只有在精确指向本 managed prefix 的 current/bin/qbox、根和 current 所指 release 均已验证时可复用；其他文件/链接一律失败。升级不改这个稳定链接。首次/新增 bin-dir 用不覆盖的 `ln -s` 创建链接，并记下本次所有权；若有人同时占用，失败退出。

```bash
# final 已验证，锁仍持有。临时 current 链接位于 prefix 内同一文件系统。
ln -s -- "releases/$release_id" "$current_temp" || return 1
mv -Tf -- "$current_temp" "$prefix/current" || return 1
committed=1
```

`current_temp` 来自本次独占 token 的不重复路径；创建前确认不存在。替换前再次验证 current 不为普通文件、不指向非受管理位置。已有 bin 链接在整个升级过程中都可解析到旧或新已验证版本；prefix/bin-dir 跨设备不会引入跨设备 rename。首次安装先建指向 current 的链接再提交 current，若提交失败只删本次新建且目标仍相符的链接。提交后不再运行可能令“安装失败”的必要验证步骤；打印提示失败不撤销已安装状态。
- [ ] **Step 7：实现信号与异常清理。** EXIT/INT/TERM trap 在提交前只清理本次对象，INT/TERM 保留惯用非零状态。已移到 final 但未发布的目录须核对 token/未被 current 引用才清理。SIGKILL/断电不能执行 trap：current 的 rename 必须保证旧/新已验证目标二选一；允许留下带归属的锁和孤立目录，下一次保守报错并指导人工核验，不宣称自动崩溃恢复。不要删除仍被已运行工作流使用的旧 release。
- [ ] **Step 8：验证可重复安装与失败保护后提交。** 同载荷完整验证成功返回复用；同 qbox 版本不同 manifest 得不同 release-id，保留旧目录。可用旧版本损坏不是覆盖理由；退出并说明恢复/另装前缀办法。

```bash
bash -n packaging/offline/install.sh
python -m unittest discover -s tests/offline -p test_transaction.py -v
git add packaging/offline/install.sh tests/offline/test_transaction.py
git commit -m "feat: install offline releases with guarded atomic activation"
```

### Task 9: 用本地固定输入装配可复验的候选 tar.gz

**Files:** 创建 `tools/offline/build.py`、`tests/offline/test_build.py`；修改 CLI、`.gitignore`；创建随包 `packaging/offline/README.zh-CN.md` 初版（Task 11 补充实测信息）。

**Interfaces:** `build(cache: Path, output: Path) -> Path` 返回 `candidate.json` 路径；记录 artifact basename/SHA、source commit、manifest SHA、release-id、audit SHA。不输出“兼容已验证”或可发布标记。

- [ ] **Step 1：写白名单/可重复构建红灯测试。** 构建器消费合成小 runtime、qbox wheel/依赖 wheel 与许可证，不需要大下载。fixture 放入 `.git`、`.venv`、`__pycache__`、计算输出、私有配置 sentinel，输出不得包含它们。删除一个 wheel/许可、改一个字节、注入越界路径后失败且不存在 candidate.json。

```python
def test_same_inputs_produce_same_archive(self):
    first = build(self.cache, self.root / "first")
    second = build(self.cache, self.root / "second")
    left = json.loads(first.read_text())
    right = json.loads(second.read_text())
    self.assertEqual(left["artifact_sha256"], right["artifact_sha256"])
    self.assertEqual(left["release_id"], right["release_id"])
```

本测试 setUp 将 source commit、SOURCE_DATE_EPOCH、工具版本和文件权限固定；不将输出目录绝对路径写入包或 candidate 身份。
- [ ] **Step 2：运行 `python -m unittest discover -s tests/offline -p test_build.py -v`，确认构建器未实现而失败。**
- [ ] **Step 3：实现干净源码 wheel 构建。** 拒绝源码未提交变更；允许已忽略的构建缓存存在。固定构建工具环境及 SOURCE_DATE_EPOCH=被打包源码提交时间，通过 `python -m build --wheel --no-isolation` 构建；必须验证 wheel 内模块、Bash 资源、MIT LICENSE、可执行 qbox，排除缓存/测试/本机配置。用现有 `tools/verify-wheel.py` 检查普通 wheel 契约；新增离线资源检查不替换普通 wheel 测试。锁文件可早于最终源码提交，只要依赖输入未变；若 extras/METADATA 变更，必须重新 resolve。
- [ ] **Step 4：按白名单组装目录。** 顶层严格为设计布局：install.sh、runtime/python.tar.gz、packages 中一个 qbox wheel、wheelhouse 中锁定依赖、requirements.lock、manifest.json、checks、README.zh-CN.md、LICENSE、THIRD_PARTY_LICENSES、SHA256SUMS。checks 内增放已校验 qbox-launcher.sh 供 installer 复制。包内 requirements 是仓库运行依赖锁加 qbox wheel 的实际版本/hash，qbox 这一行显式启用两个 extras。

```python
qbox_requirement = f"qbox[analysis,structure]=={version} --hash=sha256:{sha256_file(qbox_wheel)}\n"
requirements = qbox_requirement + dependency_lock.read_text(encoding="utf-8")
```

`version` 从 qbox wheel METADATA 读取，不能硬编码 0.1.0。只复制锁清单文件，不递归复制工作树/机器安装目录。运行时及 wheel 中第三方组件的官方 URL/邮箱/版权必须保留；旧公共源码导出器的“禁止 URL/邮箱”规则不能用于 THIRD_PARTY_LICENSES 或 provenance。隐私扫描仅检查 qbox 自有运行文件及元数据中非来源字段的机器路径。
- [ ] **Step 5：生成身份、文件哈希和确定性归档。** 按 Task 1 顺序生成 release-id/manifest/SHA256SUMS；tar 排序成员、固定 uid/gid=0、uname/gname 为空、mtime=SOURCE_DATE_EPOCH、明确模式；gzip mtime=0、不包含原始输出文件名；所有归档成员再次通过路径/type 校验。文件名 `qbox-<version>-linux-x86_64-offline.tar.gz`，外部校验文件同名加 `.sha256`。相同文件名的另一载荷不能静默覆盖：输出目录已存在异哈希时失败，使用独立候选目录。
- [ ] **Step 6：在禁止网络访问的维护者环境重建两次并比较。** `build` 代码无下载入口，测试 monkeypatch socket/urllib 使网络调用立即失败；实际用 `--network=none` 构建容器验证缓存足够。两次 archive SHA 必须相同，失败要定位到 wheel 时间戳/归档排序等差异；不是将不一致归因于“正常”后略过。
- [ ] **Step 7：通过测试、wheel 验证和本地包自检后提交构建代码。** 源码提交变化后按该提交重新构建候选；本地 smoke 通过仍不能标记五平台兼容。

```bash
python -m unittest discover -s tests/offline -p test_build.py -v
git diff --check
git add tools/offline/build.py tools/offline/__main__.py tests/offline/test_build.py .gitignore packaging/offline/README.zh-CN.md
git commit -m "build: assemble deterministic qbox offline candidates"
python -m tools.offline build --cache build/offline/cache --output dist/offline
```

### Task 10: 用真实候选包验证故障、环境污染、只读运行和进程语义

**Files:** 创建 `tests/offline/test_end_to_end.py`、`tests/offline/run-target.sh`；按失败定位只修改所属安装器/启动器/自检模块及其测试；扩展 `tests/README.md`。

**Interfaces:** `run-target.sh BUNDLE_DIR EVIDENCE_DIR` 在普通用户目标环境执行，只依赖目标机基础命令与随后安装的包内 Python；不 source 现有 `tests/test_helper.sh`。`test_end_to_end.py` 是维护者端 unittest 驱动，读取 `QBOX_OFFLINE_CANDIDATE` 指向 candidate.json；未指定时明确 skip，release gate 把 skip 视为未验证。

- [ ] **Step 1：实现可观测目标 harness，先跑会失败的真实验证。** 在用户 HOME/TMPDIR 下建测试沙箱、源树之外计算目录、命令替身目录；为 python/python3/pip/pip3/bc/gcc/cc/curl/wget/dos2unix/gnuplot 及被排除的计算软件建立记录后退出 97 的替身。安装器仅调用包内绝对解释器，替身日志必须为空。另在独立用例中让 lscpu 不可用并验证已有回退，Ubuntu 不安装 gawk；`file/ldd/module` 不存在时安装及三项轻量 CLI 仍通过。不能删除 OS Python 或用宿主 Python帮助 installer 验证成功。

```bash
#!/usr/bin/env bash
# 单个失败替身的内容，由 harness 写入受控 PATH。
printf '%s\n' "${0##*/}" >> "$QBOX_FORBIDDEN_CALL_LOG"
exit 97
```

harness 通过临时 HOME 隔离用户配置；关闭网络由 Task 11 容器/VM 层保证，失败替身本身不证明离线。首次安装不设置 QBOX_PYTHON，后续专门测试显式冲突。
- [ ] **Step 2：验证正常安装与已发布路径。** 默认目录、自定义空格/中文绝对前缀、包含空格的 bin-dir、从与仓库无关的 cwd 运行三项 CLI；结构转换、kpath、后处理均调用安装后的模块。比较 stage 改名前后结果和 module origin，assert origin 位于 final release；所有旧 stage 路径删除后再次运行。确认没有旧命令别名或宿主 Python 配置变更、没有编辑 `.bashrc`，安装输出给出 PATH 提示。
- [ ] **Step 3：验证所有 Python 隔离入口与外部环境。** 创建宿主污染目录：sitecustomize.py 写 sentinel、同名 qbox/numpy 模块失败；设 PYTHONHOME/PYTHONPATH/PYTHONUSERBASE、旧 QBOX_SHARED_ROOT、VIRTUAL_ENV/CONDA_PREFIX，保持显式 QBOX_PYTHON 为空。检查 public/recursive/qbox_python/有效质量子进程均隔离。再设包外 QBOX_PYTHON 必须中文报错，设指向包内二进制的等价 symlink 可运行。

对外部替身保留调用日志，记录 PATH、LD_LIBRARY_PATH、PYTHONHOME/PYTHONPATH、MPI sentinel、QBOX_MULTIWFN_HOME/QBOX_PSEUDO_ROOT/QBOX_QE_ENV_SCRIPT/QBOX_ONEAPI_ENV_SCRIPT。允许已有外部环境脚本按原工作流修改环境，但离线发行层不得加包内 Python bin/native 库；不能只断言“某个外部变量存在”。外部环境与包内 ELF 发生真实不兼容时明确诊断，不能宣称支持任意强制注入的动态库。
- [ ] **Step 4：验证 stdin、信号、退出码和计算目录。** 通过测试 shell source 已安装 loader 后替换任务处理函数，捕获参数与 cwd，读取两行 stdin，返回 17；再用实际公共入口+PATH 中 Bash 受控替身覆盖 exec 边界，验证参数转发到正确已安装 entry.sh。真实 Bash 任务替身安装 INT/TERM trap，使用 `start_new_session=True` 后向进程组发信号，等待有界结束并断言 trap 被调用、无遗留子进程；不用真实 QE/MPI。另验证 `--task` 后数字文件名、非零退出和递归入口。
- [ ] **Step 5：验证只读安装。** 正常安装后对 release chmod 去掉所有写位，普通用户运行完整 smoke、help/list/version、真实结构转换和有效质量脚本帮助；安装树 SHA/模式不变化，Matplotlib 缓存位于用户缓存。使一个用户缓存路径不可写，验证 fallback；所有缓存/TMP 不可写时明确失败。`noexec` 挂载运行时必须导致诊断和安装失败，旧版继续可用。
- [ ] **Step 6：逐个真实故障检查保护。** 基于候选包的**测试副本**删 wheel、改字节、造坏 gzip、去许可、替换非法 runtime 归档、制造不可写 final/bin-dir、普通文件 current、同名命令普通文件/外部 symlink/断链、无标记的同名 release、同标识损坏 release。模拟缺 wheel的“重哈希副本”也必须被 lock/pip/闭包校验拒绝。每次比较旧 symlink 文本、旧版 `--version` 和用户 sentinel SHA；失败不能删除/修改旧目录。所有测试生成的伪发行物写 `test-fixture` 标签，绝不可进入 candidate/gate。
- [ ] **Step 7：运行竞争/中断/复用与回退。** 同 prefix 启两个 installer，在 pip 验证前用测试 PATH 的命令包装器和 FIFO/barrier 暂停第一个；第二个必须报告锁冲突。两个 prefix 同 bin-dir竞争，以不覆盖 ln 验证最多一个成功，无人覆盖对方链接。对每个阶段发 INT/TERM，验证清理边界；SIGKILL 在切换前后各一次，确认 current 只能指向完整旧/新版本，遗留锁不会被自动抢占。无用固定 sleep；测试等待带 timeout。

同载荷二次安装不能改版本树；用 Task 9 构建帮助函数制作第二个 test-fixture 载荷：保持真实 runtime/wheel，仅修改自检文件中的非执行说明并重新计算身份/manifest/校验和，得到同 qbox 版本不同载荷摘要，验证不同 release-id、旧版本保留；此包不得进入发布门禁。按文档在持锁状态下将 current 原子切回旧 release，再执行自检。断言 release-id 和已安装 manifest，而非只比较可能相同的 `--version` 文本。自动卸载/清理功能不在范围内。
- [ ] **Step 8：运行一次完整原有回归、所有离线单测及真实端到端检查。** 原有回归用 Task 2 开发环境或包内可导入 seekpath 的 Python，所需 rg/find/diff 只存在开发验证环境。不能为了让基础目标机跑完整开发套件而增加最终用户依赖。

```bash
bash tests/run.sh
python -m unittest discover -s tests/offline -v
QBOX_OFFLINE_CANDIDATE="$PWD/dist/offline/candidate.json" \
    python -m unittest discover -s tests/offline -p test_end_to_end.py -v
git add tests/offline/test_end_to_end.py tests/offline/run-target.sh tests/README.md
git commit -m "test: exercise real offline installs and failure rollback"
```

如果修复涉及产品文件，单独提交相应模块与红绿测试，并重新构建候选；Task 11 使用最终候选 SHA，不能沿用修复前证据。

### Task 11: 完成跨系统验收、证据门禁和用户文档

**Files:** 创建 `tools/offline/matrix.py`、`tests/offline/test_matrix.py`、`docs/releases/{offline-build.md,offline-validation.md}`；补全 `packaging/offline/{images.lock.json,README.zh-CN.md}`；更新 `README.zh-CN.md`、`README.md`、`docs/architecture.md`、`tests/README.md`。

**Interfaces:** `matrix(candidate: Path, engine: str, output: Path) -> None`；`gate(candidate: Path, evidence: Path) -> None`。每份系统报告为 `schema_version=1,platform_id,os_release,image_digest,kernel,arch,cpu_flags,glibc,bash,awk,base_packages,network_mode,uid,artifact_sha256,manifest_sha256,source_commit,test_harness_commit,started_at,finished_at,cases,status`。`status` 仅 `passed/failed/not_run`；没有证据不能推断 passed。

- [ ] **Step 1：写 gate 红灯测试。** 构造五份小 JSON 证据；缺一平台、包 hash 不同、harness 不同且未记录、network 非 none、uid 为 root、smoke skip、基础平台不符、许可证/ELF报告缺失、baseline CPU 证据缺失均失败。

```python
def test_five_reports_must_describe_the_same_artifact(self):
    platforms = ("ubuntu-20.04", "ubuntu-22.04", "ubuntu-24.04", "rocky-8", "rocky-9")
    reports = [{"platform_id": name, "artifact_sha256": "a" * 64} for name in platforms]
    reports[3]["artifact_sha256"] = "b" * 64
    with self.assertRaisesRegex(ValueError, "artifact"):
        validate_artifact_binding("a" * 64, reports)
```

`validate_artifact_binding(candidate_sha: str, reports: list[dict]) -> None` 与 `validate_evidence(candidate: dict, reports: list[dict], baseline_cpu_report: dict) -> None` 在 `matrix.py` 定义，后者必须调用前者。完整报告 fixture 含上文全部字段及每项 case，不能只设置总 passed；分别删除每个必需字段/检查项，验证 gate 报错。
- [ ] **Step 2：运行 `python -m unittest discover -s tests/offline -p test_matrix.py -v` 确认失败。**
- [ ] **Step 3：准备并固定最低基础验证镜像。** 镜像来源 ubuntu:20.04/22.04/24.04、rockylinux:8/9 仅用于维护者首次准备，实际执行前解析成不可变 digest，并记录基础包版本/构建配方。准备过程只添加设计列出的基础命令，Ubuntu 保持 mawk、Rocky 用其默认 awk；不添加 qbox 科学依赖、bc、编译器或计算软件。不要卸掉 OS 自身依赖的 Python；用失败替身验证不被使用。镜像只作为维护者测试设施，不作为用户交付形式。
- [ ] **Step 4：实现 matrix 容器命令。** 已准备镜像用 `--pull=never`、`--network=none`、非 root UID、只读 rootfs，`/tmp` 单独可写可执行；bundle/harness 只读挂载，证据目录单独可写；不挂载源码 `src/`、开发 venv、宿主 `/opt` 或用户 HOME。由 host 解析 candidate 的**实际** archive/hash，目标从归档安装。

```python
command = [engine, "run", "--rm", "--pull=never", "--network=none",
           "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
           "--user", f"{os.getuid()}:{os.getgid()}",
           "--tmpfs", "/tmp:rw,exec,mode=1777",
           "--mount", f"type=bind,src={payload_dir},dst=/payload,readonly",
           "--mount", f"type=bind,src={harness_dir},dst=/harness,readonly",
           "--mount", f"type=bind,src={platform_output},dst=/evidence",
           image_digest, "bash", "/harness/run-target.sh", "/payload/bundle", "/evidence"]
```

`payload_dir` 是 host 已验证并展开的候选目录父级，内部固定命名 bundle；`harness_dir` 仅复制测试驱动，不包含 qbox 产品源码；`platform_output` 是各平台独立空目录；三个挂载路径由程序生成而非 shell 拼接。额外 archive-to-install 检查由目标用 tar 在临时目录重新展开原始 archive 进行，以证明交付压缩包而非 host 安装结果可用。保存 engine 实际 inspect 的网络设置和镜像 ID，不能仅记录命令字符串就称断网。
- [ ] **Step 5：运行五系统同包矩阵。** 每个平台跑 Task 10 正常/失败/环境/信号/只读场景和 Task 7 完整功能；记录 OS、glibc、Bash、awk、image digest、payload SHA 及逐项结果。Ubuntu 20.04 与 Rocky 8 是阻断发布的最低版本，不容许用 24.04 代替。宿主内核被容器共享，记录事实；对需要原系统内核或 noexec 挂载的检查，在相应 VM 中完成，不能把容器结果声称成独立内核验证。
- [ ] **Step 6：执行 baseline CPU/原生库加载补充验证。** 用 x86_64 baseline CPU 模型的 Rocky 8 或 Ubuntu 20.04 VM，记录模型与 flags；断网跑完整 smoke。对 Task 3 全部 ELF 闭包在最小镜像上用动态加载跟踪/维护者诊断工具记录解析来源，确认未借助宿主外部库。诊断工具在附加审计环境使用，不作为用户安装前提。未执行则记 not_run，禁止“基础 x86_64 已验证”的发布标记。
- [ ] **Step 7：写用户文档，逐条在测试沙箱验证命令。** 随包中文 README 给出：基础系统需求、外层 SHA 校验/解压、默认与空格路径自定义安装、PATH 提示、QBOX_PYTHON 冲突、外部工具配置、只读缓存、自检入口、离线失败诊断、保留旧版、手工回退/卸载及遗留锁检查。回退先检查 root/release marker 并执行包内 verify/smoke，持安装锁，用同目录临时 symlink+`mv -Tf` 换 current；卸载先核对 bin/qbox 精确目标和 prefix 标记，只删该链接/明确 qbox 根，不给不经归属检查的 `rm -rf` 示例。明确 SIGKILL/断电可能留下锁，人工检查 PID/归属/版本后再处理。

英文 README 与中文 README 都将离线 tar.gz 作为正式用户安装方式，保留源码/wheel 开发说明及其 QBOX_PYTHON 契约。维护者配方解释 resolve→审阅锁→audit→build→matrix→gate，不提供在线用户安装教程。架构文档明确 private marker、双模式和原子提交点。验证索引只列已执行平台，列出未执行/失败项；不写“所有未来 Ubuntu/Rocky 均支持”。
- [ ] **Step 8：实现发布门禁并保存同包证据。** gate 要求全部原有回归、离线测试、许可证/ELF、五平台和 baseline CPU 记录都指向该 artifact/manifest；证据中 failed/not_run/skip 均阻止 `dist/offline/release-ready.json`。证据和 ready 标记不放回 tar 内，避免修改已测试 SHA。产品文件、锁、安装器、自检任何改动都重建/重跑受影响测试，最终五平台使用同一包；纯报告文档提交可以晚于源码 commit，但报告必须保留真实构建 commit，不能声称包来自后来的 HEAD。
- [ ] **Step 9：运行门禁、审阅最终 diff 并本地提交证据索引和文档。** 大日志/归档只留忽略目录；仓库记录每平台关键事实、日志摘要 SHA 和可取得的发布渠道位置，禁止提交含宿主隐私的日志。发布/推送/生产部署仍需另行明确授权。

```bash
python -m unittest discover -s tests/offline -p test_matrix.py -v
python -m tools.offline matrix --candidate dist/offline/candidate.json --engine docker --output build/offline/evidence
python -m tools.offline gate --candidate dist/offline/candidate.json --evidence build/offline/evidence
git diff --check
git add tools/offline/matrix.py tools/offline/__main__.py tests/offline/test_matrix.py \
    packaging/offline/images.lock.json packaging/offline/README.zh-CN.md \
    README.md README.zh-CN.md docs/architecture.md tests/README.md docs/releases
git commit -m "docs: record offline validation and release procedure"
```

## 验收证据和设计覆盖检查

| 设计章节 | 对应任务 | 必须保留的证据 |
|---|---|---|
| §1 目标/排除项 | 1、9、10 | 白名单、内容清单、禁用命令调用日志；无计算软件/赝势 |
| §2 独立 Python + wheelhouse | 2、8、9 | 固定 runtime、qbox wheel、完整锁和离线 pip 日志 |
| §3 平台/运行时 | 2、3、6、11 | runtime SHA、wheel tags、ELF、CPU 和五系统报告 |
| §4 载荷/追溯/许可证 | 1、2、3、9 | 身份摘要图、许可证映射、SHA256SUMS、归档 SHA |
| §5 安装/所有权/失败 | 6、8、10 | 阶段故障测试、锁竞争、old current 与 sentinel 对照 |
| §6 启动/外部隔离 | 4、7、10 | 两模式测试、递归/二次 Python、外部环境和信号记录 |
| §7 awk/bc | 5、11 | mawk/default awk 结果、十进制 golden、指数既有问题记录 |
| §8 发布验收 | 7、9、10、11 | 同包功能、故障、可重复构建和拒绝不完整证据的 gate |
| §9 阶段边界 | 本文交接 | 本次仅计划；实施前用户审阅与执行方式确认 |

实施完成的证据清单（当前全未执行，不能当完成报告）：

- [ ] 具体 runtime/依赖/构建工具锁已审阅；没有浮动 URL/空哈希/源码安装输入。
- [ ] qbox 两组 extras 和所有传递边均覆盖；pip/vendor/native 许可证齐全。
- [ ] 原 Bash/Python 回归通过，源码/wheel 配置兼容性通过。
- [ ] 基础 x86_64、glibc 2.28 原生库闭包和 CPU 验证通过。
- [ ] 同一个 tar.gz 在五系统断网、普通用户、无宿主 Python帮助下通过。
- [ ] 默认/空格路径、只读、升级、复用、回退、竞争和各失败场景通过。
- [ ] 所有内部 Python 隔离而外部环境无包路径污染；exec/stdin/退出码/信号通过。
- [ ] 两次纯本地构建 archive SHA 一致；测试证据与最终候选 SHA 一致。
- [ ] 只有门禁完整通过才生成 ready 标记；不存在 push/部署隐式步骤。

## 技术依据与计划自检

以下为规划时核查的上游规则，具体发行版本仍由 Task 2 实测锁定，不把动态网页版本当作当前产品锁：

- python-build-standalone 的 baseline GNU x86_64 与运行时许可材料：[运行说明](https://gregoryszorc.com/docs/python-build-standalone/main/running.html)。
- CPython `-I` 排除环境 PYTHON 配置、用户 site 和不安全搜索路径；因此每个新 Python 进程都显式携带隔离参数：[3.12 命令行规则](https://docs.python.org/3.12/using/cmdline.html#cmdoption-I)。
- pip hash 模式要求全部依赖精确固定并提供哈希，`--only-binary` 禁止源码分发：[Secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/)；配置禁用须覆盖文件和环境：[Configuration](https://pip.pypa.io/en/stable/topics/configuration/)。
- manylinux 标签表示最低 glibc 兼容要求，不能代替所有 ELF/CPU/实际平台测试：[平台兼容标签规范](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/)。

计划自检结论：设计每节已映射到任务；Review Focus 五项均有所属行为测试；所有新接口在所属任务定义；当前文档中的代码块是未来实现/测试指引，尚未写入产品文件。具体运行时及依赖版本/哈希作为 Task 2 的必交付输出，不是本次已完成下载或验证的声明。未覆盖的科学频率指数支持明确排除；第三处 awk 兼容调整明确列出供本次计划审阅。

## 实施交接

等待用户审阅本计划并确认执行方式后开始 Task 1。

- **子代理逐任务执行（推荐）：** 每任务由新执行代理实现、独立审阅后再进入下一任务，最后整体审阅；成本更高，适合本计划的安装归属、环境隔离和跨平台门禁边界。
- **本任务直接执行：** 主代理顺序实现全部任务，最后独立整体审阅；上下文开销较低，独立审阅发生较晚。

推荐第一种，因为 11 个任务共享 manifest/启动器/安装事务契约，错误可能让用户离线机器无法安装或影响已有入口。无论选择哪种方式，具体锁审阅、失败回退证据和五系统验收都不能省略。
