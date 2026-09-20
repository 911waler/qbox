# qbox 0.1.0 统一轻量安装包验收

本记录对应 2026-09-21 在本机生成的轻量安装包。仅本地生成，尚未推送或远端发布。
完整离线版是另一个产品，本记录不沿用它的跨平台结论。

## 冻结产物

- 安装包：`qbox-0.1.0-linux-installer.tar.gz`，213068 字节。
- 安装包 SHA256：`0e81786f9124dff9516fc11de88795b59827364d69b0df48207e10370d201788`。
- 包内 wheel：`qbox-0.1.0-py3-none-any.whl`。
- wheel SHA256：`6b4f741fa0672a175c6d7e85b802401b9dfb7a0cceac41a54476b5fd6311c015`。
- 本地目录：`build/lightweight/task3-dist/`（安装包及 `.sha256`）、
  `build/lightweight/task3-wheel/`（wheel）。
- 使用相同 wheel 分别构建到 `build/lightweight/task4-dist-a/` 与
  `build/lightweight/task4-dist-b/`，两份归档与上述冻结文件逐字节相同。
  本验收文档不在安装包内，不影响包内容。

包中只有安装器、qbox wheel、许可、中文指南和校验清单；没有 Multiwfn、Python、
科学依赖 wheelhouse、第三方源码或离线审计载荷。首次安装需要预先准备 Python 3.10+
及其 venv/pip 支持，并联网获取 analysis、structure 依赖。安装器不调用 apt/dnf，
不会更换系统 Python。底层 Python 必须保留，已建 venv 不可移动。

## 可重复的验收方法

在准备好 Docker 镜像后，从仓库根目录运行：

```bash
python tests/installer/run-acceptance.py \
  --archive build/lightweight/task3-dist/qbox-0.1.0-linux-installer.tar.gz \
  --image qbox-lightweight-test:ubuntu22 \
  --output build/lightweight/acceptance/new-ubuntu22-run
```

输出目录必须是新目录，避免覆盖旧证据。镜像需包含 Bash、useradd、runuser 和所选
Python/venv/pip；Rocky 镜像使用 `/usr/bin/python3.11`。镜像构建 Dockerfile、
联网 apt/dnf 日志及解释器检查保存在 `build/lightweight/acceptance-images/`。
测试通过返回 0，缺环境、任何非预期非零退出或断言失败均不能计为通过。

脚本只将归档与自身以只读方式挂入一次性容器；不挂载宿主 Python 或依赖目录。
容器内先用真实 pip 联网构建各平台 wheel 缓存，再以该缓存完成六种安装及重跑验证，
缓存不进入交付包。每条命令的 argv、stdout、stderr、退出码和耗时写入
`commands.jsonl`，其中保存 wheel 缓存哈希、每次安装记录及完整依赖版本。
`result.json` 保存归档身份、镜像 ID/digest、验收脚本哈希和最终结果。
账号和 root 安装均发生在容器内，未在宿主创建账号或安装到 `/opt`、`/usr/local`。

## 实测平台及结果

所有四个平台均使用相同冻结归档；每个平台六次新安装、三次完整匹配复用、九组真实
用户工作流均通过。Ubuntu 各 15 组、Rocky 9 共 16 组、Rocky 8 共 15 组场景通过，
所有四次宿主验收命令均退出 0。

| 容器系统 | Python / 解释器 | 个人三种路径 | 管理员三种路径、双账号 | 证据目录（`build/lightweight/acceptance/` 下） |
|---|---|---|---|---|
| Ubuntu 22.04.5 | 3.10.12 / `/usr/bin/python3` | 通过 | 通过 | `ubuntu22-final/` |
| Ubuntu 24.04.4 | 3.12.3 / `/usr/bin/python3` | 通过 | 通过 | `ubuntu24-final/` |
| Rocky 9.8 | 3.11.13 / `/usr/bin/python3.11` | 通过 | 通过 | `rocky9-final2/` |
| Rocky 8.10 | 3.11.13 / `/usr/bin/python3.11` | 通过 | 通过 | `rocky8-final2/` |

镜像 ID（对应的完整 RepoDigest 也保存在各 `result.json`）：

- Ubuntu 22.04.5：`sha256:0f950c5935077b71041ab3402adea08048782b30a4a1beec3ee81459c136969a`。
- Ubuntu 24.04.4：`sha256:48dc137b4088cf8e63871664c071662c84cd8680a18b60c636439a2da2edbe23`。
- Rocky 9.8：`sha256:796f2ba2e3a1a6f8e1e48dd950a79bc2ecdbb518ddb3d1dd30c62dabff05d3f4`。
- Rocky 8.10：`sha256:ecd7282af9fd61ec96ba463c423264e22b35760441f9ff9f7254715509043767`。

每个平台实际执行并通过：

- 个人默认、含中文/空格 prefix、独立 bin-dir，系统模式同样覆盖三种布局；
  参数顺序的其他排列由安装器单元测试覆盖。
- alice 在安装前存在，bob 在第一次系统安装后创建；两者无需激活环境即可运行帮助、
  任务列表、版本及带空格文件名的 CIF→VASP 转换。
- 每个系统布局执行安装器实际打印的 profile.d 示例，两个账号的登录 shell 都用
  `command -v qbox` 找到所选入口；独立绝对路径调用覆盖批处理方式。
- 带过期 `QBOX_PYTHON`、`PYTHONPATH` 的干净环境仍使用绑定 venv 完成工作流。
- 两个账号均无法写共享 Python、prefix、入口、安装记录；安装树实际为 root 所有且
  无普通用户写权限。各自转换结果、真实 PNG/SVG 绘图及绘图缓存均归对应账号所有。
  实测缓存为 `/tmp/.qbox-mpl-cache-<uid>`，没有依赖 `/root`。
- 既有文件与符号链接入口不被覆盖，普通用户写 `/opt` 失败，实际 UID 模式校验生效；
  不可遍历 prefix/解释器和含可写祖先的系统目录安装均在发布前拒绝。
- Rocky 9 的旧默认 Python 3.9 被明确拒绝，选择 `/usr/bin/python3.11` 后全部通过。
  Rocky 8 镜像未提供 `/usr/bin/python3`，验收明确选择 Python 3.11。

科学依赖实际解析版本如下；完整版本及缓存文件 SHA 在命令日志中：

| 平台 | NumPy | SciPy | Matplotlib | pymatgen | ASE | seekpath |
|---|---|---|---|---|---|---|
| Ubuntu 22.04.5 | 2.2.6 | 1.15.3 | 3.10.9 | 2025.10.7 | 3.29.0 | 2.2.1 |
| Ubuntu 24.04.4 | 2.5.3 | 1.18.1 | 3.11.2 | 2026.5.4 | 3.29.0 | 2.2.1 |
| Rocky 9.8 | 2.4.6 | 1.17.1 | 3.11.2 | 2026.5.4 | 3.29.0 | 2.2.1 |
| Rocky 8.10 | 2.4.6 | 1.17.1 | 3.11.2 | 2026.5.4 | 3.29.0 | 2.2.1 |

其余验证：50 项安装器测试、241 项 shell 检查、54 项 Python 测试及
`tools/verify-wheel.py` 全部通过。已有事务测试覆盖 pip 失败、缺 venv 预检、
中断、并发发布、冲突保留及重装校验。没有改动离线共用代码，也没有重复历史离线 VM 验收。

实测范围与限制：这是 x86_64 Docker 用户空间验收，共享宿主内核；不等同于冷启动 VM、
其他架构或所有 Linux 发行版验证。没有执行 QE/MPI 计算或 Multiwfn。依赖来自当日索引，
以后解析版本可能变化；轻量包没有固定/携带这些科学依赖。初轮 Ubuntu 24 测试缓存
保留 sdist 却缺构建依赖、Rocky 缓存构建缺 `bdist_wheel`，均是验收缓存准备问题：
已改为联网 `pip wheel --use-pep517`，保留失败及人工停止的早期记录，只有上述完成的
四次运行用于通过结论。Ubuntu 完成运行使用相同缓存构建命令但未显式加
`--use-pep517`；其实际构建成功，两个脚本快照及 SHA 保存在证据目录中。
安装器/交付包未为此改动。此前记录的裸程序名 `--python python3.11` 解析限制仍保留，
本文及验收使用解释器绝对路径。


## 审查后补充验收

审查指出旧验收脚本的 Python `assert` 会被优化模式删除，而且独立系统命令目录缺少
防替换证明。验收脚本现已将全部必要检查改为显式 `require()` / `AcceptanceFailure`，
包括实际命令退出码、文件/目录权限、容器边界和最终结果判定；嵌入 Python 脚本也没有
可被优化删除的断言。七项针对性测试在普通及 `-O` 模式下通过，其中以 `-O` 和
`PYTHONOPTIMIZE=1` 分别证明非预期成功/失败不能绕过检查，外层还拒绝失败、缺失及重复结果。

针对新增目录检查，用以下明确限定范围的补充命令在相同四个镜像中各新装一次；
它不代替前述完整矩阵，也不重新宣称完整矩阵是在优化模式下跑完的：

```bash
python -O tests/installer/run-acceptance.py \
  --archive build/lightweight/task3-dist/qbox-0.1.0-linux-installer.tar.gz \
  --image qbox-lightweight-test:ubuntu22 \
  --output build/lightweight/acceptance/new-ubuntu22-supplement \
  --checks command-directory
```

补充范围为 `/opt/lab qbox` 与独立 `/opt/共享 commands`，验证命令目录及完整父目录链
归 root 且无组/其他用户写权限。alice/bob 分别真实尝试创建文件、`os.replace` 替换
qbox 和删除 qbox；每次必须得到 `PermissionError`，入口 inode/SHA 必须保持不变。
同时故意将命令目录和 `/opt` 改成可写，证明检查能拒绝，再恢复权限并完成正常工作流。
这些变动只在一次性容器内发生。脚本的默认完整验收也已调用同一目录检查。

| 平台 | Python | 宿主/容器优化级别 | 普通账号修改拒绝 | 目录/祖先篡改检测 | 结果 |
|---|---|---|---|---|---|
| ubuntu22 | 3.10.12 | 1 / 1 | 6 / 6 | 2 / 2 | 通过 |
| ubuntu24 | 3.12.3 | 1 / 1 | 6 / 6 | 2 / 2 | 通过 |
| rocky9 | 3.11.13 | 1 / 1 | 6 / 6 | 2 / 2 | 通过 |
| rocky8 | 3.11.13 | 1 / 1 | 6 / 6 | 2 / 2 | 通过 |

四次补充命令均退出 0；各执行一次新安装、一次复用及两组真实用户工作流。
证据位于 `build/lightweight/acceptance/<platform>-review1/`，汇总为
`review1-summary.json`。逐项核对了镜像 ID、归档 SHA256 和 wheel SHA256，全部与
原完整矩阵一致。四次运行的验收脚本 SHA256 均为
`64d37c5484abc656cdcec4c82aff028e695a8b1ba219d14264408150bfa52a8c`。


已知的次要限制：输出目录仍应选择全新路径；孤立的旧 `result.json` 在缺少
`commands.jsonl` 时可能被覆盖，该审查项留待最终审查处理。本次所有补充运行均使用
此前不存在的新目录，既有完整矩阵及失败尝试证据均保留。

## 安装与 PATH

先核对旁边的 SHA256 文件，解压后进入 `qbox-0.1.0-linux-installer/`。
个人默认安装：

```bash
bash install.sh --user --python /usr/bin/python3
export PATH="$HOME/.local/share/qbox/bin:$PATH"
hash -r
command -v qbox
qbox --help
```

只指定自定义 prefix 时，入口自动位于它的 `bin/qbox`：

```bash
bash install.sh --user --prefix "$HOME/software/科学 qbox" \
  --python /usr/bin/python3
export PATH="$HOME/software/科学 qbox/bin:$PATH"
```

管理员可选择默认 `/opt/qbox`，或自定义总目录及独立命令目录：

```bash
sudo bash install.sh --system --python /usr/bin/python3.11
sudo bash install.sh --system --prefix /opt/lab/apps/qbox \
  --bin-dir /opt/lab/bin --python /usr/bin/python3.11
```

以上两条是二选一示例。用当前系统实际存在且符合版本要求的解释器绝对路径。
安装器会输出准确的入口路径、个人 PATH 行及管理员 `/etc/profile.d/qbox.sh` 示例，
不会自行修改 shell 配置。管理员检查已有配置后执行输出的示例，例如自定义目录：

```bash
# 在管理员 shell 中执行；noclobber 拒绝覆盖已有文件。
( set -C; printf '%s\n' 'export PATH=/opt/lab/bin:"$PATH"' > /etc/profile.d/qbox.sh ) &&
  chmod 0644 /etc/profile.d/qbox.sh
```

新老用户重新登录后用 `command -v qbox` 检查。批处理可直接使用
`/opt/lab/bin/qbox --task cif-to-vasp 'input with spaces.cif'`，无需激活环境。
如果旧命令或别名优先，先检查实际解析路径。现有无关入口不被覆盖；升级先装新 prefix，
验证后再明确切换 PATH，旧环境保留用于回退。重装和卸载细节见
[安装说明](../installation.md)及包内指南。
