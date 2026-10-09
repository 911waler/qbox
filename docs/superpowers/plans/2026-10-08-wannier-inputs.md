# Wannier90 输入生成实施计划

依据：[已确认设计](../specs/2026-10-08-wannier-input-design.md)。用户已授权实施。

## 约束与接口

- 10 unfold 保留，新增 11 Wannier；旧 11–37 顺延，PW 快捷参数不变。
- 六个方向全部实现；先选方向，再编辑公共和专用参数。
- 默认当前目录；生成与发布分离；不修改来源 SCF 或计算结果。
- 目标官方 Wannier90 3.1.0；基础生成仅标准库，自动路径按需引入 seekpath。
- 公共配置为 JSON 字典：source、run_root、seed、version、mode(new/existing)、grid、nbnd、num_wann、projections、exclude_bands、windows、tasks、parameters；spin channel overrides 使用 channels 字典。
- `wannier_inputs.parse_qe(text)` 返回解析对象；`build_bundle(source_text, config, source_path=None, run_root=None, output_dir=None)` 返回文件名到文本的字典。
- `wannier_profiles.render_profile(tasks, parameters, spin_mode, version='3.1.0')` 返回含 win_lines、pw2_flags、warnings 的 Profile；模块提供方向、子任务、参数定义供菜单消费。
- `wannier_workflow.initial_config(source=None)` 提供菜单初值；`prepare(config, output_dir=None)` 返回完整文件包；`wannier_publish.snapshot(files, directory)` 与 `publish(files, directory, conflict='cancel', expected=None, protected=())` 负责预览及事务。
- `wannier_menu.main(argv=None)` 提供交互与 --config JSON 自动化入口，经 Bash 包装器调用。

## Task 1: 网格、QE 解析与新建文件包

负责 io/kmesh.py、io/wannier_inputs.py、对应 Python 测试。先写失败用例，再实现共享网格、保真 namelist 编辑、单位结构校验、投影和窗口计数、三种自旋分支、输入包及说明。测试覆盖引号路径、多赋值、尾部 HUBBARD、排除带和无效结构。

## Task 2: 六类配置与原晶胞路径

负责 io/wannier_profiles.py、io/wannier_paths.py、对应测试。先定义各项目参数、校验和导出依赖的失败测试，再实现官方 3.1.0 模板。自动路径使用原晶胞接口；支持实际 band.kpt 转换。验证每项及版本不支持参数。

## Task 3: 菜单、入口与编号迁移

负责 registry.py、cli.py、legacy 下必要改动、io/wannier_menu.py、现有编号测试/文档和新菜单测试。完整保留既有 handler/slug。交互公共参数菜单、六方向项目选择、专用参数、预览/生成/返回，自动化 JSON 入口和 kmesh 命令。

## Task 4: 当前目录发布与已有结果

负责 io/wannier_publish.py、io/wannier_workflow.py、对应测试。输入包先校验后发布；源文件保护、非普通文件拒绝、唯一备份、并发摘要复核、失败回滚和恢复清单。已有模式保留模型，仅替换任务参数，检查数据维度及缺失项并记录未验证来源。

## Task 5: 集成验收

运行现有完整测试、各方向生成样例、真实 Wannier90 3.1.0 预处理、wheel 源码外安装验证；独立审查跨模块输入与文件安全。测试结果记入实施记录。不得将预处理成功声称为完整物性计算验证。

## 审查重点

跨模块配置是否一致；保留所有原任务；自旋/导出依赖；任务切换无残留；路径与运行目录；无破坏的冲突、回滚和恢复；真实程序对参数的接受情况。
