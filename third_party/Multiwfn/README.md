# Multiwfn 独立下载 / Optional download

这里保存可选的 **Multiwfn 3.8(dev)、Linux x86_64 原始安装压缩包**，供 qbox 用户单独获取。
它不是 qbox 的组成代码，也不会随 qbox wheel、源码发行包（sdist）或完整离线安装包安装。
完整 Git 仓库和仓库源码快照会包含此目录。

- [下载原始 ZIP](Multiwfn_3.8_dev_bin_Linux.zip)（33,618,174 字节，约 33.6 MB）
- [SHA256SUMS](SHA256SUMS)
- [原始许可证](LICENSE.txt)
- [来源及版本记录](provenance.json)
- [官方主页](http://sobereva.com/multiwfn/) / [官方新版本下载](http://sobereva.com/multiwfn/download.html)

在 GitHub 文件页选择 **Download raw file** 下载 ZIP，也可只获取上述 ZIP 和 SHA256SUMS，
不必克隆整个仓库。qbox 发行包里不包含本目录，请从源码仓库或官网另行获取。

本副本来自维护者已保存的原始压缩包，字节未作修改；没有原始下载时间和官网公布校验值的记录。
这里的 SHA-256 用于核对此副本的完整性，不代表上游签名。ZIP 中主程序时间戳为
2025-03-24（时区未知），不将它作为已经核实的发布日期，也不宣称这是最新版本。

## 手动安装

在下载的 ZIP 和 SHA256SUMS 所在目录运行。需要 `unzip`；请选择没有同名已有安装的目标目录。

```bash
sha256sum -c SHA256SUMS
mkdir -p "$HOME/.local/opt"
unzip -n Multiwfn_3.8_dev_bin_Linux.zip -d "$HOME/.local/opt"
chmod u+x "$HOME/.local/opt/Multiwfn_3.8_dev_bin_Linux/Multiwfn"
export QBOX_MULTIWFN_HOME="$HOME/.local/opt/Multiwfn_3.8_dev_bin_Linux"
export Multiwfnpath="$QBOX_MULTIWFN_HOME"
test -x "$QBOX_MULTIWFN_HOME/Multiwfn"
```

`unzip -n` 不覆盖已有文件，但不应借此进行版本升级或混装；已有安装时使用一个新的解压目录。
把两个 export 设置写入自己的 shell 或作业环境配置。qbox 会使用 `QBOX_MULTIWFN_HOME`；
若没有设置它，也可从 PATH 查找 `Multiwfn`。MPI/QE 环境无需因此改动。

此处记录的是下载材料，不是 Ubuntu/Rocky 的兼容认证。Multiwfn 自身的动态库、图形和
线程设置请按 ZIP 中的快速入门文档及官方手册配置；这里不会安装系统库或自动运行它。

## 许可证与引用

原始 LICENSE.txt 原样保留，完整压缩包也保留原作者的示例、说明和引用文档。
阅读并遵守这些条件；qbox 的 MIT 许可证不覆盖 Multiwfn。
使用 Multiwfn 得到研究结果时，按包内 `How to cite Multiwfn.pdf` 和许可证要求引用：

- Tian Lu, Feiwu Chen, *J. Comput. Chem.* **33**, 580–592 (2012).
- Tian Lu, *J. Chem. Phys.* **161**, 082503 (2024).

## English summary

This is an optional, unmodified local archive of Multiwfn 3.8(dev) for Linux x86_64,
not a claim to mirror the latest upstream release. Download the ZIP separately,
verify SHA256SUMS, extract it into a fresh directory, and set `QBOX_MULTIWFN_HOME`
and `Multiwfnpath`. qbox never installs it automatically. The wheel and sdist
exclude this directory; a full repository checkout includes it. Read the original
LICENSE.txt and citation documents before use.
