# qbox 个人与管理员统一轻量安装设计

## 用户目标与已确认范围

同一轻量安装包同时服务个人用户和管理员。安装完成后直接输入 `qbox`，无需激活
Python 环境。两种模式均可独立选择程序安装目录和命令入口目录。Multiwfn 继续作为
源码仓库中的独立下载文件，不进入任何 qbox 安装包，不自动安装。

本设计扩展现有 wheel 和固定 Python 启动器，保持科学算法、任务编号及 QE/MPI 调用方式。
已确认的对话方案是一个包、两种模式；本文件补齐路径、权限、失败处理和验证要求。

## 交付方案

新增 `qbox-<版本>-linux-installer.tar.gz`，包含本地 qbox wheel、`install.sh`、安装器
所需实现、使用说明和 SHA256 清单。同一文件支持两种模式，不按模式重复分发 wheel。
继续提供独立 wheel/sdist；原完整离线归档作为另一个可选产品，原验收结论只对应原归档。

该轻量安装包不含 Python、科学依赖 wheelhouse、第三方源码审计材料或 Multiwfn。
要求用户预先提供 Python 3.10+（含 venv/pip 支持），首次安装联网下载科学依赖。
不调用 apt/dnf 自动修改系统、不替换系统 Python、不假设 PyPI 同名 qbox 即本项目。
安装 qbox 本体必须使用包内 wheel；默认安装 analysis 与 structure 依赖。

## 用户接口

```bash
# 个人默认路径
bash install.sh --user

# 个人自定义路径；最终命令为 $HOME/bin/qbox
bash install.sh --user \
  --prefix "$HOME/software/qbox" \
  --bin-dir "$HOME/bin" \
  --python /absolute/path/to/python3

# 管理员默认路径
sudo bash install.sh --system

# 管理员自定义路径；最终命令为 /opt/lab/bin/qbox
sudo bash install.sh --system \
  --prefix /opt/lab/apps/qbox \
  --bin-dir /opt/lab/bin \
  --python /usr/bin/python3.11
```

- `--user` 与 `--system` 互斥，必须明确选择一个；避免误判 sudo 下的 HOME。
- `--user` 默认 prefix 为 `$HOME/.local/share/qbox`，bin-dir 为 `$HOME/.local/bin`。
- `--system` 默认 prefix 为 `/opt/qbox`，bin-dir 为 `/usr/local/bin`，要求有效 UID 0。
- root 运行 `--user` 时拒绝并说明应使用普通账号或显式 `--system`。
- `--python` 可选，缺省检查 PATH 中的 python3，版本不足时要求明确选择合适解释器。
- `--prefix` 与 `--bin-dir` 互相独立；最终入口始终为 `<bin-dir>/qbox`，不增加改名功能。
- 解析绝对路径并支持空格/中文；拒绝空值、根目录和会覆盖受管理内部文件的路径关系。
  可允许安全的 `<prefix>/bin`；拒绝把 prefix 放入 bin-dir、入口放进 venv/releases/current。
- `--help` 无副作用；任何既有、非本安装所有的文件、目录或符号链接都不得覆盖。

## 程序和 Python 环境

在 prefix 内创建专用虚拟环境，与系统 Python 包及其他用户环境分离。
入口绑定该环境的 Python，不依赖执行用户 HOME 或 PATH 中的 Python，也不跟随其
QBOX_PYTHON 旧值。保留 QE/MPI 需要的调用者环境，不把私有库路径全局注入环境。
Python venv 不可通过创建后移动目录来发布：环境需在最终固定路径创建，成功检查后再
公布入口。底层 Python 安装本身需保留，venv 不是可独立搬移的自包含运行时。

个人安装由当前用户管理；系统安装的专用环境、程序和入口由 root 管理，普通用户可读、
可执行但不可写。验证系统 Python、prefix 和入口的父目录可被其他用户遍历，且不通过
普通用户可写目录承载管理员启动链。不递归改变既有共享父目录或无关文件的权限。

计算输出仍写用户当前工作目录，缓存使用各自可写的用户目录或独占临时目录。
安装器不得留下依赖 root HOME、root 私有缓存路径或安装阶段临时目录的运行配置。

## 命令发现与 PATH

安装器总是输出入口绝对路径和针对所选 bin-dir 的 PATH 配置，提示用 `command -v qbox`
检查实际选中命令。自定义 bin-dir 不自动成为所有用户的 PATH。

个人模式给出 shell 配置指引；系统模式同时给出管理员在 `/etc/profile.d/` 统一配置的
准确示例，供新老用户登录时采用。安装器不静默改写现有 shell 配置；用户已有别名或
更靠前的 qbox 会被提示排查。非登录 shell/批处理作业可以使用入口绝对路径。

## 失败、重装和升级边界

安装开始前核验包内文件、Python、权限及路径冲突。科学依赖安装和入口/导入检查成功
后才发布命令；下载、pip、检查失败均返回非零，保留已有可用入口。
同一安装并发执行必须互斥。只能清理本事务新建并能证明归属的文件，不能递归删除
用户预先存在的目录。新建 venv 若在中断后残留，应报告位置，不盲目接管。

初版重跑可验证并复用完全匹配的受管理安装；不同版本或配置不原地破坏已有环境。
升级先安装到新 prefix（必要时使用另一 bin-dir），验证后按文档切换已确认归属的入口；
旧环境保留用于回退。不在本次引入自动删除历史环境、自动接管旧离线安装或自动迁移。
卸载文档需先核验入口目标与安装归属，再移除该入口和专用目录，保留用户数据和 Multiwfn。

## 代码组织和兼容性

安装入口、路径/权限/归属判断、环境创建与依赖安装、命令发布分别保持清晰边界。
复用现有固定解释器启动行为及已有路径安全规则；不把完整离线验证链强加给联网轻量包。
`python -m qbox.install --bin-dir ...` 继续服务已有自行管理的 Python 环境，明确区别于
负责创建整个环境的 `install.sh`。中英文 README 的默认路径统一指向新的两模式指南。

## 验收

1. 从同一发行归档运行个人和管理员模式，核验所用 qbox wheel 身份一致。
2. 默认路径、自定义 prefix、独立 bin-dir、中文/空格路径均能安装并运行真实工作流样例。
3. 新 shell 未激活 Python 且旧 QBOX_PYTHON 指向别处时，入口仍使用绑定环境。
4. 隔离测试系统中由 root 安装，至少两个普通账号（含安装后新建账号）可运行；它们不能
   修改共享程序，且缓存/输出分别属于各自用户。不得在当前生产主机创建测试账号或部署软件。
5. 模拟失败、重装、并发及同名文件/链接冲突，验证不覆盖无关文件、不破坏旧入口。
6. 自定义系统 bin-dir 的统一 PATH 示例应在新用户登录 shell 实测；批处理测试绝对路径。
7. Python 版本不足、缺 venv、目录不可遍历/可被普通用户修改时有明确诊断。
8. 检查归档不含 Multiwfn、私有 Python 或科学依赖载荷；执行现有回归及安装产物测试。
9. 准确报告实际测过的 Ubuntu/Rocky 与解释器组合，不沿用完整离线版的跨平台认证。

本设计不授权将软件实际安装到当前主机的 /opt 或 /usr/local，不授权推送或发布远端。
