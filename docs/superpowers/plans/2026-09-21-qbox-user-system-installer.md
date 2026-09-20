# qbox User and System Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 同一个轻量归档支持个人/管理员安装，默认入口位于 `<prefix>/bin/qbox`，新老用户无需激活 Python 即可运行。

**Architecture:** Bash 入口只选择 Python 并转交参数；包内标准库 Python 安装器验证路径和权限，在最终目录创建 venv、安装本地 wheel 及联网科学依赖，经检查后发布命令。现有 `qbox.install` 保留已有 Python 环境的使用方式；统一安装器复用其固定解释器入口，使用自己的安装归属记录和锁。

**Tech Stack:** Bash、Python 3.10+ 标准库、venv/pip、setuptools/wheel、unittest、隔离 Linux 容器。

**Spec:** `docs/superpowers/specs/2026-09-21-qbox-user-system-installer-design.md`

## Global Constraints

- `--user` 与 `--system` 互斥，必须明确选择一个。
- `--user` 默认 prefix 为 `$HOME/.local/share/qbox`；`--system` 默认 prefix 为 `/opt/qbox`。
- 未给出 `--bin-dir` 时，在解析最终 prefix 后令 bin-dir 为 `<prefix>/bin`，与参数顺序无关。
- `--system` 要求有效 UID 0；root 运行 `--user` 时拒绝。
- 要求用户预先提供 Python 3.10+（含 venv/pip 支持），首次安装联网下载科学依赖。
- qbox 本体来自包内 wheel；默认安装 analysis 与 structure 依赖；不调用 apt/dnf，不替换系统 Python。
- 不包含 Python、科学依赖 wheelhouse、第三方源码审计材料或 Multiwfn。
- Python venv 在最终固定路径创建，不能创建后改名移动；底层 Python 安装本身需保留。
- 管理员安装由 root 管理，普通用户可读/执行、不可写；缓存和计算结果属于各用户。
- 不静默改写 shell 配置；输出个人 PATH 与管理员 `/etc/profile.d/` 示例。
- 不覆盖无关入口、不接管旧离线安装、不自动删除历史环境；失败不得破坏旧命令。
- 不在当前主机创建测试账号或部署到 /opt、/usr/local；只在隔离环境测试管理员模式。
- 不推送或发布远端；保留已验收的历史完整离线归档。

## Review Focus

- venv 解释器符号链接及含空格/单引号路径：绑定路径不 resolve 到系统 Python，Task 2 用真实环境执行验证。
- 管理员可写性不等于其他用户可用：父目录遍历权限、可写祖先和外部 Python 路径由 Task 1 检查，Task 4 用新账号验证。
- 两个不同 prefix 竞争同一 bin-dir：Task 2 的命令发布不能覆盖竞争者，失败不能清除竞争者文件。
- 发布入口前后中断和重跑：Task 2 保留已生效入口、不误报成功，未完成归属不能当作匹配安装复用。
- 默认总目录不在 PATH：Task 4 从安装器实际输出建立登录环境，验证新账号及非登录作业，不把临时 export 当作持久配置。

## 文件与接口分工

- `packaging/lightweight/install.sh`：启动解释器选择，其他验证交给 Python。
- `packaging/lightweight/installer/__init__.py`：安装器包。
- `packaging/lightweight/installer/__main__.py`：CLI、执行阶段、诊断、退出码。
- `packaging/lightweight/installer/paths.py`：参数、规范路径、权限验证。
- `packaging/lightweight/installer/transaction.py`：锁、归属、环境准备、发布和重复安装。
- `packaging/lightweight/README.zh-CN.md`：随安装包交付的指南。
- `tools/build-lightweight-installer.py`：从一个已构建 wheel 生成归档和校验值。
- `tests/installer/test_paths.py`、`test_transaction.py`、`test_bundle.py`：标准库 unittest。
- `tests/installer/run-acceptance.py`：实际归档的隔离系统验收。
- `src/qbox/install.py`：只在必要时提取可复用的命令内容生成逻辑，保持旧命令行为。
- `README.md`、`README.zh-CN.md`、`docs/installation.md`、`docs/releases/lightweight-validation.md`：用户入口及实测记录。

测试安装器时 `PYTHONPATH=packaging/lightweight`；执行命令中的 `python` 指维护者已核实的开发解释器。
本机现有共享 Python 只读使用；需要构建依赖时使用项目内 `build/lightweight/build-env`，不得向共享环境安装包。

### Task 1: 参数、路径及两种权限模型

**Files:** Create `packaging/lightweight/installer/{__init__.py,paths.py}`; test `tests/installer/test_paths.py`.

**Interfaces:**
- `InstallOptions(mode: str, prefix: Path, bin_dir: Path, python: Path)`：冻结 dataclass。
- `parse_options(argv: list[str], *, uid: int, home: Path, default_python: Path) -> InstallOptions`：纯参数/路径解释。
- `validate_paths(options: InstallOptions) -> None`：实际文件系统权限与重叠判断，失败抛 `ValueError`/`OSError`。

- [ ] 写失败测试，核心可直接使用：

```python
from pathlib import Path
from installer.paths import parse_options

def test_prefix_implies_command_directory(self):
    options = parse_options(['--user', '--prefix', '/tmp/qbox 中文'],
                            uid=1000, home=Path('/tmp/home'),
                            default_python=Path('/usr/bin/python3'))
    self.assertEqual(options.bin_dir, Path('/tmp/qbox 中文/bin'))
```

同文件增加模式缺失/重复/冲突、root-user、非root-system、参数顺序、空路径、根目录、危险嵌套、父目录符号链接规范化；系统模式针对 ancestor uid/mode、组/其他写权限和其他用户缺少执行权限断言具体诊断。拒绝路径换行字符，避免生成无法审阅的 shell 配置。
- [ ] 运行 `PYTHONPATH=packaging/lightweight python -m unittest discover -s tests/installer -p test_paths.py -v`，确认因缺实现失败。
- [ ] 实现 argparse 互斥组、最终 prefix 推导以及按路径组件的重叠判断：

```python
prefix = Path(args.prefix).expanduser().absolute() if args.prefix else default_prefix
bin_dir = Path(args.bin_dir).expanduser().absolute() if args.bin_dir else prefix / 'bin'
```

检查现存祖先及解析后的路径；系统模式检查选择的解释器链接路径及最终目标的共享可用性。只验证既有目录，不 chmod/chown 共享父目录。任何不存在目录在创建后都要重新验证。
- [ ] 运行同一测试命令通过。新增临时树测试：不安全祖先拒绝后，原 mode、内容和 inode 不变。
- [ ] 提交 `feat: validate user and system installer paths`。

### Task 2: 环境创建、归属和固定入口发布

**Files:** Create `packaging/lightweight/installer/transaction.py`; test `tests/installer/test_transaction.py`; reuse `src/qbox/install.py`.

**Interfaces:**
- `install(options: InstallOptions, *, wheel: Path, wheel_sha256: str) -> Path`：返回成功可执行入口；失败抛异常，不返回成功路径。
- `verify_install(options: InstallOptions, *, wheel_sha256: str) -> None`：验证匹配安装记录及入口/依赖可用性。
- 记录 `<prefix>/.qbox-install.json`：schema_version=1、mode、uid、规范prefix/bin_dir、Python路径、wheel SHA、安装后的 distributions/version、入口 SHA、state。
- 锁 `<prefix>/.install-lock`：原子 mkdir，加本次唯一令牌与目录 inode；非本事务锁不可移除。
- venv `<prefix>/venv`；入口 `<bin_dir>/qbox`；归属记录 state 顺序为 preparing → ready。

- [ ] 写失败测试，使用真实临时 wheel（在测试 setUpClass 中从项目构建一次到临时目录）及 venv，不以假 pip 的成功替代实际安装。下载失败场景允许使用本地失败索引，并对真实 pip 非零退出断言。

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from installer.paths import InstallOptions
from installer.transaction import install

def test_foreign_entry_unchanged(self):
    with TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / 'commands').mkdir()
        entry = base / 'commands/qbox'
        entry.write_text('foreign command')
        options = InstallOptions('user', base / 'app', entry.parent, self.python)
        with self.assertRaises((ValueError, OSError)):
            install(options, wheel=self.wheel, wheel_sha256=self.wheel_sha)
        self.assertEqual(entry.read_text(), 'foreign command')
```

覆盖相同归属复用、不同版本/配置拒绝、无标记非空 prefix、损坏记录/入口、锁冲突、两个prefix竞争入口、失效链接、同名目录、依赖失败和 INT/TERM；实际入口绑定带引号/空格的 venv，用错误旧 QBOX_PYTHON 启动应成功。
- [ ] 跑 `PYTHONPATH=packaging/lightweight python -m unittest discover -s tests/installer -p test_transaction.py -v`，记录预期失败。
- [ ] 实现清晰的验证→锁→新建最终venv→pip→smoke→发布→ready流程。执行子命令使用参数数组而非 shell 拼接：

```python
subprocess.run([str(options.python), '-m', 'venv', str(options.prefix / 'venv')], check=True)
subprocess.run([str(options.prefix / 'venv/bin/python'), '-m', 'pip', 'install',
                str(wheel) + '[analysis,structure]'], check=True)
```

构建干净安装子进程环境，消除旧 QBOX_/PYTHONHOME/PYTHONPATH/PIP_TARGET/PIP_PREFIX/PIP_USER 干扰；保留明确配置的代理/证书/索引，记录实际依赖版本。root 安装启用仅针对新文件的可读可执行权限。只复用同一身份且验证通过的 ready 安装，复用不重新运行联网 pip。

在发布前从 venv 运行 `pip check`、所需库导入、`qbox --help/--list` 和固定 CIF 转换样例。命令复用现有 `python -m qbox.install --bin-dir` 的不覆盖发布方式。ready 写入失败时诊断保留情况，不能盲目删除已发布入口；重跑必须能区分 ready 与 preparing，报告手动恢复指引。
- [ ] 运行测试至通过。对每个失败断言旧入口字节、无关目录内容不变；新目录残留如保留必须在诊断中标明。断电/SIGKILL只承诺保守残留和手动恢复，不承诺自动抢锁。
- [ ] 提交 `feat: install managed Python environments and publish qbox commands`。

### Task 3: 同一发行归档、CLI 和随包指南

**Files:** Create `packaging/lightweight/install.sh`, `packaging/lightweight/installer/__main__.py`, `packaging/lightweight/README.zh-CN.md`, `tools/build-lightweight-installer.py`, `tests/installer/test_bundle.py`; modify both READMEs and `docs/installation.md`.

**Interfaces:**
- 用户：`bash install.sh (--user|--system) [--prefix PATH] [--bin-dir PATH] [--python PATH]`。
- 构建：`python tools/build-lightweight-installer.py --wheel FILE --output DIR`。
- 输出：`qbox-<wheel元数据版本>-linux-installer.tar.gz`、同名 `.sha256`。
- 归档单根目录含 `install.sh`、`installer/*.py`、`packages/<wheel>`、`README.zh-CN.md`、`LICENSE`、`SHA256SUMS`。

- [ ] 先写真实构建产物测试；由测试 setUpClass 构建 wheel 并调用构建命令：

```python
with tarfile.open(self.archive) as bundle:
    names = bundle.getnames()
self.assertTrue(any(n.endswith('/install.sh') for n in names))
self.assertEqual(sum(n.endswith('.whl') for n in names), 1)
self.assertFalse(any('Multiwfn' in n or 'wheelhouse/' in n or 'runtime/' in n for n in names))
```

增加归档 SHA 校验、错误wheel元数据、重复/额外wheel拒绝、wheel哈希篡改必须在创建prefix前失败、CLI --help 不创建文件、参数未知/缺值不丢失诊断、解压后离开仓库仍能执行。
- [ ] 跑 `PYTHONPATH=packaging/lightweight python -m unittest discover -s tests/installer -p test_bundle.py -v`，确认预期失败。
- [ ] Bash 用数组保留全部原始参数，扫描 `--python` 选择解释器；重复/缺值参数报错，`--help` 无需可用Python。转入安装包根目录，用选定 Python 执行 `-m installer`，启动后验证版本、文件清单和 wheel SHA 再调用 Task 2。checksum是完整性检查，不宣称签名认证。
- [ ] 构建器显式允许列表取文件，固定文件顺序、权限与mtime，拒绝符号链接/意外路径；从 wheel METADATA 读取项目名及版本，不信任文件名猜测。输出若存在不同内容则报错，不覆盖旧归档。
- [ ] 更新两种模式默认示例，强调入口在 prefix/bin、Python仍需系统提供、依赖联网、Multiwfn独立；保留高级 bin-dir 和原 `python -m qbox.install` 方式。打印 shell-quote 后 PATH 行与管理员 profile.d 示例；不自动修改 shell 文件。
- [ ] 指南写明卸载时核对归属与入口SHA，先移除已确认入口，再删除该安装专用目录；升级使用新prefix、验证再改PATH，旧环境保留。文档命令不得对未经验证的路径直接递归删除。
- [ ] 跑产物测试及原 `tests/python/test_install_command.py`，提交 `feat: package a unified lightweight qbox installer`。

### Task 4: 管理员、新用户与发行验收

**Files:** Create `tests/installer/run-acceptance.py`, `docs/releases/lightweight-validation.md`; augment installer tests for findings. Evidence under ignored `build/lightweight/acceptance/`.

**Interfaces:** `python tests/installer/run-acceptance.py --archive FILE --image IMAGE --output DIR`，返回0仅当该镜像全部必需场景通过；缺环境不可记为通过。记录归档SHA、镜像digest、Python版本、实际测试输出及退出码。

- [ ] 先定义可执行验收断言，实际命令执行器必须记录返回码/输出；核心检查：

```python
assert run_as('alice', ['sh', '-lc', 'command -v qbox']).stdout.strip() == expected_command
assert run_as('bob', [expected_command, '--version']).returncode == 0
assert run_as('bob', ['test', '-w', installed_python]).returncode != 0
assert run_as('bob', [expected_command, '--task', 'cif-to-vasp', 'input with spaces.cif']).returncode == 0
```

`run_as(user: str, argv: list[str]) -> subprocess.CompletedProcess` 由验收脚本在容器内调用 runuser 实现，非零结果不隐式忽略。alice 在安装前创建，bob 在安装后创建，均只在隔离容器内。
- [ ] Ubuntu 22.04/Python3.10、Ubuntu24.04/Python3.12、Rocky9/Python3.11 执行相同最终归档；Rocky8/Python3.11 镜像若可准备也覆盖，无法执行则文档明确未验证。镜像准备记录联网系统包安装，禁止借用生产软件目录绕过依赖安装。
- [ ] 每个系统依次运行：普通用户默认安装、自定义带空格prefix、显式bin-dir；root系统默认安装、自定义prefix/bin-dir；两个账号未激活环境的帮助/列表/真实结构转换及绘图缓存检查。安装器返回的 profile.d 示例在容器中执行，随后用登录 shell 验证新账号 PATH。
- [ ] 实测旧入口冲突、普通用户写共享目录失败、错误继承Python、不可遍历prefix/解释器、含可写祖先的系统安装拒绝。记录用户计算目录的输出与缓存归属。
- [ ] 运行当前 `tests/run.sh`、`tests/installer`、`tools/verify-wheel.py`；只在本次改动触及离线共用代码时补跑相关离线单元测试，不重新跑历史完整离线VM验收。
- [ ] 实际构建两次统一归档，校验确定性与同一wheel；最终用于验收的归档须与交付文件SHA一致。文档变更影响随包内容时先冻结再验收，不能拿旧包测试充当新包结论。
- [ ] 保存 `lightweight-validation.md`：归档名/大小/SHA、测试平台、用例结果、实测限制、个人/管理员安装命令与配置示例。失败或受环境阻塞的必需场景必须明示，不宣称管理员验收通过。
- [ ] 提交 `test: verify shared qbox installs for existing and new users`。

## 完成检查及交付

- [ ] 逐项对应设计中的9条验收要求，确认无未覆盖需求。
- [ ] 请求一次全改动审查，修复实际问题并运行受影响测试。
- [ ] 交付统一归档、SHA文件、简洁安装步骤和准确验证范围；说明仅本地生成，尚未远端发布。
- [ ] 保留用户先前选择的“子代理逐任务执行”：任务依次执行，每项独立审查，不能并行编辑共享安装接口。
