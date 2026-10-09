"""Static task catalog shared by the Python CLI and Bash compatibility layer.

Only names declared here can be selected as handlers. This module never imports
scientific libraries or evaluates handler strings as code.
"""

from dataclasses import dataclass
import sys


@dataclass(frozen=True)
class TaskSpec:
    id: int
    slug: str
    title: str
    category: str
    handler: str


TASKS = (
    TaskSpec(0, "pw-input", "生成 pw.x 输入文件", "输入文件生成", "pwin"),
    TaskSpec(1, "neb-input", "生成 neb.x 输入文件", "输入文件生成", "nebin"),
    TaskSpec(2, "phonon-input", "生成 ph.x 输入文件", "输入文件生成", "phin"),
    TaskSpec(3, "hubbard-input", "生成 hp.x 输入文件", "输入文件生成", "hpin"),
    TaskSpec(4, "dos-input", "生成 dos.x 输入文件", "输入文件生成", "dosin"),
    TaskSpec(5, "pdos-input", "生成 projwfc.x 输入文件", "输入文件生成", "projwfcin"),
    TaskSpec(6, "postprocess-input", "生成 pp.x 输入文件", "输入文件生成", "ppin"),
    TaskSpec(7, "bands-input", "生成 bands.x 输入文件", "输入文件生成", "bandin"),
    TaskSpec(8, "md-input", "生成 MD 输入文件", "输入文件生成", "mdin"),
    TaskSpec(9, "optics-input", "生成 epsilon.x 输入文件", "输入文件生成", "epsilonin"),
    TaskSpec(10, "unfold-input", "生成 unfold.x 输入文件", "输入文件生成", "qe_generate_unfold_inputs"),
    TaskSpec(11, "wannier-input", "生成 Wannier90 输入文件", "输入文件生成", "qbox_wannier_menu"),
    TaskSpec(12, "scf", "SCF计算", "执行计算", "run_qe_scf_calculation"),
    TaskSpec(13, "bands", "能带计算", "执行计算", "run_qe_band_calculation"),
    TaskSpec(14, "pdos", "PDOS计算", "执行计算", "qe_action_pdos"),
    TaskSpec(15, "ldos", "LDOS计算", "执行计算", "run_qe_ldos_calculation"),
    TaskSpec(16, "polarization", "结构极性计算", "执行计算", "run_qe_polar_calculation"),
    TaskSpec(17, "optics", "光吸收/介电函数计算", "执行计算", "run_qe_epsilon_calculation"),
    TaskSpec(18, "effective-mass", "有效质量计算", "执行计算", "run_qe_effective_mass_calculation"),
    TaskSpec(19, "unfold", "unfold 能带计算", "执行计算", "run_qe_unfold_calculation"),
    TaskSpec(20, "plot-bands", "绘制 QE 能带图", "绘图功能", "plot_qe_band"),
    TaskSpec(21, "plot-pdos", "绘制 QE PDOS 图/切换能量零点", "绘图功能", "redraw_qe_pdos_plot"),
    TaskSpec(22, "plot-ldos", "绘制 QE LDOS 图", "绘图功能", "redraw_qe_ldos_plot"),
    TaskSpec(23, "plot-optics", "绘制 QE 光吸收/介电函数图", "绘图功能", "plot_qe_epsilon"),
    TaskSpec(24, "band-edges", "从 QE/Unfold 能带数据提取 VBM/CBM.dat", "后处理功能", "extract_qe_band_edges"),
    TaskSpec(25, "fit-effective-mass", "从 QE CBM.dat 计算电子有效质量", "后处理功能", "calc_qe_effective_mass"),
    TaskSpec(26, "relax-to-cif", "从 (vc)relax/MD 输出生成 .cif 文件", "后处理功能", "relax2cif_menu"),
    TaskSpec(27, "md-to-xyz", "从 MD 输出生成 .xyz 轨迹文件", "后处理功能", "qbox_md_to_xyz_menu"),
    TaskSpec(28, "relax-to-nscf", "将 (vc)relax 输出转换为 nscf 输入文件", "后处理功能", "qbox_nscf_menu"),
    TaskSpec(29, "dopant-pdos", "分析 QE 掺杂原子及近邻 PDOS", "后处理功能", "analyze_qe_dopant_pdos"),
    TaskSpec(30, "scf-to-nscf", "将 scf 输入文件转换为 nscf 输入文件", "其他功能", "scf2nscf"),
    TaskSpec(31, "constraints", "固定 slab 模型中的原子", "其他功能", "qbox_constraints_menu"),
    TaskSpec(32, "convergence", "监控 SCF/relax/vc-relax 能量收敛", "其他功能", "conver"),
    TaskSpec(33, "ecut-scan", "ecutwfc 和 ecutrho 收敛性测试", "其他功能", "qe_action_ecut_scan"),
    TaskSpec(34, "kpoint-scan", "K 点网格收敛性测试", "其他功能", "qe_action_kpoint_scan"),
    TaskSpec(35, "cluster-velocities", "为团簇/分子生成指定动能的 ATOMIC_VELOCITIES", "其他功能", "cluster_velocities"),
    TaskSpec(36, "merge-md", "合并 QE 分子动力学输出文件", "其他功能", "merge_md_outputs"),
    TaskSpec(37, "cif-to-vasp", "cif 转 vasp", "其他功能", "qe_action_cif_to_vasp"),
    TaskSpec(38, "vasp-to-cif", "vasp 转 cif", "其他功能", "qe_action_vasp_to_cif"),
    TaskSpec(39, "plot-phonons", "绘制 QE 声子谱图", "绘图功能", "plot_qe_phonon"),
    TaskSpec(40, "phonons", "声子计算", "执行计算", "run_qe_phonon_calculation"),
)

_BY_ID = {str(task.id): task for task in TASKS}
_BY_SLUG = {task.slug: task for task in TASKS}


def get_task(selector):
    """Return a declared task by its exact numeric ID or readable slug."""
    key = str(selector)
    task = _BY_ID.get(key) or _BY_SLUG.get(key)
    if task is None:
        raise ValueError(f"Unknown task: {selector}")
    return task


_MENU_HEADINGS = {
    "输入文件生成": "=============================== 输入文件生成 =================================",
    "执行计算": "=============================== 执行计算 ====================================",
    "绘图功能": "================================ 绘图功能 ===================================",
    "后处理功能": "=============================== 后处理功能 ==================================",
    "其他功能": "================================ 其他功能 ===================================",
}

# Presentation only: compact rows preserve the original menu's spacing. Tasks
# not covered by a compact row automatically receive a row of their own.
_COMPACT_ROWS = (
    ((0, 1, 2), ("        ", "       ")),
    ((3, 4, 5), ("        ", "       ")),
    ((6, 7, 8), ("        ", "     ")),
    ((12, 13, 14, 15), ("\t\t", "\t\t", "\t\t")),
    ((20, 21), ("\t",)),
)


def render_menu(tasks=TASKS):
    """Render every registered task, grouped in first-seen category order."""
    groups = {}
    for task in tasks:
        groups.setdefault(task.category, []).append(task)
    lines = [
        "",
        "注意：以下功能主要面向 ibrav=0 且使用 angstrom 单位的输入/输出文件",
        "",
    ]
    for category, group in groups.items():
        lines.append(_MENU_HEADINGS.get(category, f" {category} ".center(78, "=")))
        index = 0
        while index < len(group):
            task = group[index]
            # Task 10 historically has one leading space; other rows have two.
            line = f"{' ' if task.id == 10 else '  '}{task.id}) {task.title}"
            for row_ids, separators in _COMPACT_ROWS:
                row = group[index:index + len(row_ids)]
                if tuple(item.id for item in row) == row_ids:
                    for separator, item in zip(separators, row[1:]):
                        line += f"{separator}{item.id}) {item.title}"
                    index += len(row_ids)
                    break
            else:
                index += 1
            lines.append(line)
    lines.extend(("================================================================================", ""))
    return "\n".join(lines) + "\n"


def render_list():
    """Render stable numeric IDs alongside discoverable command names."""
    lines = [" ID  Task                  Category      Description"]
    lines.extend(
        f"{task.id:3d}  {task.slug:21s} {task.category}  {task.title}"
        for task in TASKS
    )
    return "\n".join(lines) + "\n"


def main(argv=None):
    """Private, data-only bridge used by the Bash compatibility adapter."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--menu"]:
        print(render_menu(), end="")
        return 0
    if args == ["--ids"]:
        print(" ".join(_BY_ID))
        return 0
    if len(args) == 2 and args[0] == "--handler" and args[1] in _BY_ID:
        print(_BY_ID[args[1]].handler)
        return 0
    print("Usage: python -m qbox.registry --menu | --ids | --handler ID", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
