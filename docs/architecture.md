# qbox 模块边界

## 一条入口链

```text
源码 qbox / 安装后的 qbox / python -m qbox
                    ↓
             cli.py + registry.py
                    ↓
            legacy/entry.sh → load.sh
                    ↓
       分领域 Bash 工作流 → io/、postprocess/ Python 算法
```

`registry.py` 的 `TaskSpec` 保存稳定任务编号、可读名称、分组及允许调用的处理器。
菜单、`--list`、显式任务选择和 Bash 分发均使用该表。Bash 不对用户传入的处理器
字符串执行 `eval`。`--task` 后的路径与旧式数字参数的解释分离。

`cli.main()` 用 `exec` 替换为兼容进程，不另加捕获标准输入的中间子进程。
因此原 Bash 管道的 `pipefail`、`tee`、退出码、清理 trap 及终端交互仍由原流程负责。
包路径从入口自身解析，不从计算目录猜测；子流程使用包内启动器，wheel 中也携带
这些资源。`QBOX_PYTHON` 用于选择工作流分析解释器，包路径显式传给它。

## 已迁移的 Python 实现

原 27 段 heredoc 与掺杂 PDOS 工具成为 28 个实现模块，分别归入 `io` 和 `postprocess`。
导入不会解析命令行或启动任务；调用 `main(argv)` 才执行文件型算法。具备独立解析、
拟合或绘图函数的实现保留这些接口，不用 `exec` 执行大段源码字符串。

`postprocess/effective_mass_vasp.py` 同时是可复制、独立执行的兼容脚本；现有有效质量
流程仍在受管理临时目录中运行它。顶层 `qbox-dopant-pdos.py` 是历史调用方式的入口，
实际实现在 `postprocess/dopant_pdos.py`。

部分图形/科学模块导入时需要其可选依赖。主入口和注册表只依赖标准库，因此帮助与
任务列表不要求安装全部科学包。

## 有意保留的 Bash 兼容层

`legacy/load.sh` 按明确顺序加载领域文件，而不是运行任务。`bootstrap.sh` 配置环境；
`dispatch.sh` 兼容旧参数；`state.sh` 管理结构状态与文件事务；`runner.sh` 与
`environment.sh` 管理执行及环境。输入生成、电子结构、MD、声子、光学、收敛和
unfolding 分别位于同名领域文件。

这些文件目前仍共享历史 Bash 变量及动态作用域，不能被视为完全独立的公共 API。
拆文件解决导航和渐进迁移问题，并不自动消除耦合。不要从 Python 任意导入/调用
一个 shell 文件；经由任务注册表和兼容入口执行整个工作流。

后续以领域为单位引入显式结构上下文和 Python runner/文件事务接口。先用固定输出
与失败场景测试定义边界，迁移该领域的实现及调用者，再删除对应 Bash 模块。
不建立无人使用的 Context/Runner 抽象，也不同时维护两套科学算法。

## 兼容性和分发约束

- 保留 0–37 号、旧菜单文本及旧命令位置；新任务名是附加接口。
- `--task` 表示显式选任务，不把后续数字文件名解释为任务或 PW 快捷选项。
- 根启动器仍可被 Bash source，供旧脚本及回归测试调用兼容函数。
- 源码分发需完整目录；wheel 分发需包含 `legacy/*.sh`、`bin/*` 和 Python 模块。
- 保留 MIT `LICENSE`。仅参考 VASPKIT 的功能组织方式，未复制其代码或分发内容。
- 不把工作目录、输出文件、赝势或本机安装路径写入安装包。

## 验证

`tests/run.sh` 运行 Bash 行为测试及 `tests/python` 中的 unittest。旧的单文件源码
检查已改为模块级检查或直接行为验证；保留生成文件、任务映射、错误路径和清理测试。
另需构建 wheel，在源码目录之外安装并验证入口、资源、结构转换和独立有效质量脚本。
