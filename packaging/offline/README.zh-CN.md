# qbox 离线候选包

本包包含 qbox、独立 CPython 3.12 运行时和 analysis / structure 的锁定依赖。
目标为 Linux x86_64、glibc 2.28+、Bash 4.4+；最终五平台及基础 CPU 验收尚未完成。

先核对包旁的 SHA256 校验文件，解压后执行：

```bash
sha256sum -c qbox-*-linux-x86_64-offline.tar.gz.sha256
tar -xzf qbox-*-linux-x86_64-offline.tar.gz
bash install.sh
```

默认安装到 `$HOME/.local/share/qbox`，命令链接位于 `$HOME/.local/bin/qbox`。
也可指定包含空格的绝对路径：

```bash
bash install.sh --prefix "$HOME/Local Apps/qbox" --bin-dir "$HOME/local commands"
```

安装无需 sudo、网络、系统 Python、pip、编译器或 Conda。系统需具备 GNU
coreutils、grep、sed、awk、tar、gzip，并提供可写的用户临时/缓存目录。
将所选 bin 目录加入 PATH 后运行 `qbox --help`、`qbox --list`。
不要把包内 Python 的 bin 或原生库目录全局加入 PATH / LD_LIBRARY_PATH。

QE、MPI、Multiwfn、unfold.x、赝势库由用户另外提供。本包不安装这些工具。
源码入口及普通 wheel 安装仍保留 QBOX_PYTHON / QBOX_SHARED_ROOT 契约。
安装目录可以只读，科学计算结果和缓存写入用户工作目录。

manifest.json 和 SHA256SUMS 记录实际载荷身份。checks 包含校验程序、固定
测试数据、原始依赖审计、CPU 构建输入及历史配方；THIRD_PARTY_LICENSES 保留
第三方完整许可及所需对应源码。历史原生依赖检查不等于本候选包的最终兼容性验收。
本候选包尚无发布或五平台兼容承诺。

维护者仅可从干净源码提交及固定本地缓存运行 `python -m tools.offline build`。
缓存需包含 python.tar.gz、candidate-wheelhouse、build-wheelhouse 和 audit/descriptor.json。
描述符的 licenses / elf 对象各有相对 path、sha256、size；所有材料及审计日志按原报告
相对路径保存在 audit/ 下。可选 checks 映射也需上述三项，禁止越界路径或符号链接。
构建不会下载材料；缺少或损坏输入必须先独立修复缓存。不同载荷使用不同输出目录。
