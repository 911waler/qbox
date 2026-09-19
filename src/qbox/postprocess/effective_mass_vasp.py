#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import math
import re
import os
from typing import List, Tuple, Dict, Any, Optional

import numpy as np

# ---- 物理常数（SI）----
HBAR = 1.054571817e-34       # J·s
EV_TO_J = 1.602176634e-19    # J/eV
ANGSTROM_TO_M = 1e-10        # m/Å
M0 = 9.1093837015e-31        # kg


def read_band_dat(path: str) -> Tuple[np.ndarray, np.ndarray]:
    data = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if (not s) or s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            data.append((float(parts[0]), float(parts[1])))
    if not data:
        raise RuntimeError(f"未从 {path} 读到任何有效数据。")
    arr = np.array(data, dtype=float)
    return arr[:, 0], arr[:, 1]


def read_klabels(path: str) -> List[Tuple[str, float]]:
    labels: List[Tuple[str, float]] = []
    pattern = re.compile(r"^\s*([A-Za-z0-9_\|\-]+)\s+([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s*$")
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if (not s) or s.startswith("#") or s.startswith("*"):
                continue
            m = pattern.match(line)
            if m:
                labels.append((m.group(1), float(m.group(2))))
    if not labels:
        raise RuntimeError(f"KLABELS 文件 {path} 中未识别到任何有效 (label, k) 数据行。")
    return labels


def find_label_entry_by_k(k_value: float, labels: List[Tuple[str, float]], tol: float) -> Optional[Tuple[str, float]]:
    best = None
    best_d = 1e100
    for name, kv in labels:
        d = abs(kv - k_value)
        if d < best_d:
            best_d = d
            best = (name, kv)
    if best is not None and best_d <= tol:
        return best
    return None


def resolve_label_for_role(label: str, role: str) -> str:
    """
    处理复合标签 X|Y：
    - seg_start 用 Y（新段从 Y 开始）
    - seg_end   用 X（上一段在 X 结束）
    """
    if "|" not in label:
        return label
    left, right = label.split("|", 1)
    if role == "seg_start":
        return right.strip()
    if role == "seg_end":
        return left.strip()
    return label


def label_at_k_with_role(k_value: float, labels: List[Tuple[str, float]], tol: float, role: str, fallback: str) -> str:
    entry = find_label_entry_by_k(k_value, labels, tol=tol)
    if entry is None:
        return fallback
    name, _ = entry
    return resolve_label_for_role(name, role)


def split_into_segments(k: np.ndarray, tol: float) -> List[Tuple[int, int]]:
    """
    用重复 k（|k[i]-k[i-1]|<=tol）作为分段边界。
    """
    n = len(k)
    boundaries = [0]
    for i in range(1, n):
        if abs(k[i] - k[i - 1]) <= tol:
            boundaries.append(i)
    boundaries.append(n)

    segments: List[Tuple[int, int]] = []
    for a, b in zip(boundaries[:-1], boundaries[1:]):
        if b - a >= 2:
            segments.append((a, b - 1))
    return segments


def find_segments_touching_k0(k: np.ndarray, segments: List[Tuple[int, int]], k0: float, tol: float) -> List[int]:
    hit: List[int] = []
    for si, (s, e) in enumerate(segments):
        if np.any(np.abs(k[s:e+1] - k0) <= tol):
            hit.append(si)
    return hit


def _robust_median_k_step(k: np.ndarray) -> float:
    dk = np.diff(k)
    dk = np.abs(dk)
    dk = dk[dk > 0]
    if dk.size == 0:
        return 0.0
    return float(np.median(dk))


def select_valley_minima_indices(
    k: np.ndarray,
    E: np.ndarray,
    segments: List[Tuple[int, int]],
    emin_tol: float,
    valley_gap_k: Optional[float],
    valley_gap_factor: float,
) -> Tuple[List[int], Dict[int, Dict[str, Any]]]:
    Emin = float(np.min(E))
    raw_candidates = np.where(E <= Emin + emin_tol)[0].astype(int).tolist()
    if not raw_candidates:
        return [], {}

    if valley_gap_k is None or valley_gap_k <= 0:
        dk_med = _robust_median_k_step(k)
        if dk_med <= 0:
            dk_med = 1e-6
        valley_gap_k_eff = valley_gap_factor * dk_med
    else:
        valley_gap_k_eff = float(valley_gap_k)

    valley_minima: List[int] = []
    valley_info: Dict[int, Dict[str, Any]] = {}
    valley_id = 0

    raw_set = set(raw_candidates)

    for si, (s, e) in enumerate(segments):
        seg_candidates = [idx for idx in range(s, e + 1) if idx in raw_set]
        if not seg_candidates:
            continue
        seg_candidates.sort(key=lambda i: k[i])

        cluster: List[int] = [seg_candidates[0]]
        for idx in seg_candidates[1:]:
            prev = cluster[-1]
            if abs(float(k[idx]) - float(k[prev])) <= valley_gap_k_eff:
                cluster.append(idx)
            else:
                rep = min(cluster, key=lambda ii: (E[ii], abs(k[ii] - k[cluster[len(cluster)//2]])))
                valley_minima.append(int(rep))
                valley_info[valley_id] = {
                    "segment_id": si,
                    "members": cluster[:],
                    "rep": int(rep),
                    "rep_k": float(k[rep]),
                    "rep_E": float(E[rep]),
                    "valley_gap_k_eff": valley_gap_k_eff,
                }
                valley_id += 1
                cluster = [idx]

        if cluster:
            rep = min(cluster, key=lambda ii: (E[ii], abs(k[ii] - k[cluster[len(cluster)//2]])))
            valley_minima.append(int(rep))
            valley_info[valley_id] = {
                "segment_id": si,
                "members": cluster[:],
                "rep": int(rep),
                "rep_k": float(k[rep]),
                "rep_E": float(E[rep]),
                "valley_gap_k_eff": valley_gap_k_eff,
            }
            valley_id += 1

    valley_minima.sort(key=lambda i: (E[i], k[i]))
    final: List[int] = []
    for idx in valley_minima:
        if not final:
            final.append(idx)
            continue
        if abs(float(k[idx]) - float(k[final[-1]])) <= valley_gap_k_eff:
            if float(E[idx]) < float(E[final[-1]]) - 1e-12:
                final[-1] = idx
        else:
            final.append(idx)

    return final, valley_info


def quad_fit_effective_mass(k_fit: np.ndarray, E_fit: np.ndarray, k0: float) -> Dict[str, float]:
    x = k_fit - k0
    a, b, c = np.polyfit(x, E_fit, 2)

    E_pred = a * x**2 + b * x + c
    resid = E_fit - E_pred

    mse = float(np.mean(resid**2))
    rmse = float(np.sqrt(mse))

    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((E_fit - float(np.mean(E_fit)))**2))
    r2 = float("nan") if ss_tot <= 0.0 else float(1.0 - ss_res / ss_tot)

    curvature_eVA2 = 2.0 * a
    curvature_SI = curvature_eVA2 * EV_TO_J * (ANGSTROM_TO_M ** 2)

    if curvature_SI <= 0:
        mstar_m0 = float("nan")
    else:
        mstar = (HBAR ** 2) / curvature_SI
        mstar_m0 = float(mstar / M0)

    return {
        "curvature_eVA2": float(curvature_eVA2),
        "mstar_m0": float(mstar_m0),
        "r2": float(r2),
        "rmse_eV": float(rmse),
    }


def pick_points_one_side_indices(
    k: np.ndarray,
    E: np.ndarray,
    idx0: int,
    seg: Tuple[int, int],
    side: str,
    npts: int,
    dk_window: float,
    valley_Ewin: float,
    jump_tol: float,
) -> Tuple[np.ndarray, np.ndarray, List[int]]:
    """
    向某一侧取点，但加入两类“停止条件”，避免走出 CBM 能谷：
      1) 能量窗：E <= E0 + valley_Ewin（valley_Ewin<=0 表示不启用）
      2) 跳跃：相邻点 |ΔE| > jump_tol 则停止
    同时保留 dk_window 限制。
    """
    s, e = seg
    k0 = float(k[idx0])
    E0 = float(E[idx0])

    if side == "left":
        walk = list(range(idx0, s - 1, -1))
    elif side == "right":
        walk = list(range(idx0, e + 1, 1))
    else:
        raise ValueError("side must be 'left' or 'right'.")

    chosen: List[int] = []
    prev_i: Optional[int] = None

    for ii in walk:
        if dk_window > 0 and abs(float(k[ii]) - k0) > dk_window:
            break

        if valley_Ewin > 0 and float(E[ii]) > E0 + valley_Ewin:
            if ii != idx0:
                break

        if prev_i is not None:
            if abs(float(E[ii]) - float(E[prev_i])) > jump_tol:
                break

        chosen.append(ii)
        prev_i = ii
        if len(chosen) >= npts:
            break

    chosen = sorted(set(chosen), key=lambda i: k[i])
    return k[chosen], E[chosen], chosen


def make_direction_name(cbm_label: str, end_label: str) -> str:
    cbm = cbm_label if cbm_label else "CBM"
    end = end_label if end_label else "END"
    return f"{cbm}->{end}"


def _gammaize_label_text(text: str) -> str:
    return text.replace("GAMMA", r"$\Gamma$")


def _merge_klabels(klabels: List[Tuple[str, float]], k_tol: float) -> List[Tuple[float, List[str]]]:
    merged: List[Tuple[float, List[str]]] = []
    for name, kv in klabels:
        placed = False
        for i in range(len(merged)):
            if abs(merged[i][0] - kv) <= k_tol:
                merged[i][1].append(name)
                placed = True
                break
        if not placed:
            merged.append((kv, [name]))
    merged.sort(key=lambda x: x[0])
    return merged


def plot_band_with_fit_points(
    k: np.ndarray, E: np.ndarray,
    cbm_indices: List[int],
    fit_records: List[Dict[str, Any]],
    klabels: List[Tuple[str, float]],
    out_png: str,
    tol: float
) -> None:
    import matplotlib as mpl
    mpl.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure()
    ax = fig.add_subplot(111)

    band_lw = 1.5
    ax.plot(k, E, linewidth=band_lw, label="Band (CBM.dat)")

    cbm_ms = 13.0
    cbm_mew = 0.1 * band_lw
    for t, idx in enumerate(cbm_indices):
        label = "CBM (valley minima)" if t == 0 else None
        ax.plot([k[idx]], [E[idx]],
                marker=r"$\ast$",
                markersize=cbm_ms,
                markeredgewidth=cbm_mew,
                linestyle="None",
                label=label)

    fit_ms = 3.0
    fit_mew = band_lw
    used_legend = set()
    for rec in fit_records:
        name = rec["dir_name"]
        idxs = rec["fit_indices"]
        label = name if name not in used_legend else None
        used_legend.add(name)
        ax.plot(k[idxs], E[idxs],
                marker="o",
                markersize=fit_ms,
                markeredgewidth=fit_mew,
                linestyle="None",
                label=label)

    merged = _merge_klabels(klabels, k_tol=max(5e-4, tol))
    xticks, xticklabels = [], []
    for kv, names in merged:
        ax.axvline(kv, linestyle="--", linewidth=1.0)
        uniq = []
        for n in names:
            if n not in uniq:
                uniq.append(n)
        disp = _gammaize_label_text("/".join(uniq))
        xticks.append(kv)
        xticklabels.append(disp)

    ax.set_xticks(xticks)
    ax.set_xticklabels(xticklabels, rotation=0)
    ax.tick_params(axis="x", labelsize=9)

    ax.set_xlabel("k-path")
    ax.set_ylabel("Energy (eV)")
    ax.set_title("Band with effective-mass fitting points and k-labels")
    ax.grid(True)
    ax.legend(loc="best", fontsize=9)

    try:
        fig.tight_layout()
    except Exception:
        fig.subplots_adjust(left=0.10, right=0.98, top=0.92, bottom=0.16)

    fig.savefig(out_png, dpi=300)
    plt.close(fig)


def plot_band_em_detail(
    k: np.ndarray,
    E: np.ndarray,
    cbm_candidates: List[int],
    fit_records: List[Dict[str, Any]],
    klabels: List[Tuple[str, float]],
    out_png: str,
    tol: float,
    dpi: int = 300,
    max_panels_per_page: int = 12,
) -> None:
    """
    细节图：默认仍按你原来的“横向组图”输出。
    但如果预计像素宽度会超过 Agg 的 2^16 限制，则自动分页输出：root-01.png, root-02.png...

    本版修正（对应你的两条反馈）：
    1) 箭头方向修正为“指向该高对称点相对 CBM 的方向”：
       - 左侧最近高对称点：箭头向左（←）
       - 右侧最近高对称点：箭头向右（→）
       同时“箭头在内侧”：箭头贴近子图内部一侧（左侧放在文本右端；右侧放在文本左端）。
    2) 补充的高对称点标识高度与当前子图的高对称点刻度标签完全对齐：
       - 不再用 ax.text 自行摆放
       - 而是把它们作为额外的 x 轴刻度标签放在 kmin/kmax 位置（与其它 xticklabels 同一基线）
    3) 额外约束：补充点需满足 |k_hsp - k0| >= 0.05（k 单位）
    """
    import matplotlib as mpl
    mpl.use("Agg")
    import matplotlib.pyplot as plt

    if not cbm_candidates:
        return

    Ewin = 0.5
    x_margin = 0.03

    MIN_HSP_DIST = 0.05  # k 单位

    cbm_to_fitidxs: Dict[int, List[int]] = {idx: [] for idx in cbm_candidates}
    for rec in fit_records:
        cbm_idx = rec.get("cbm_idx", None)
        if cbm_idx in cbm_to_fitidxs:
            cbm_to_fitidxs[cbm_idx].extend(list(rec["fit_indices"]))

    merged = _merge_klabels(klabels, k_tol=max(5e-4, tol))

    def _nearest_hsp_labels_around_k0(k0: float) -> Tuple[Optional[str], Optional[str]]:
        """
        返回 (left_label, right_label)：
        - left:  取 kv <= k0 - MIN_HSP_DIST 的最大 kv
        - right: 取 kv >= k0 + MIN_HSP_DIST 的最小 kv
        若不存在则返回 None。
        """
        left = None   # (kv, label)
        right = None  # (kv, label)

        for kv, names in merged:
            uniq = []
            for nm in names:
                if nm not in uniq:
                    uniq.append(nm)
            lab = _gammaize_label_text("/".join(uniq))

            if kv <= k0 - MIN_HSP_DIST + 1e-12:
                if (left is None) or (kv > left[0]):
                    left = (kv, lab)
            if kv >= k0 + MIN_HSP_DIST - 1e-12:
                if (right is None) or (kv < right[0]):
                    right = (kv, lab)

        left_label = None if left is None else left[1]
        right_label = None if right is None else right[1]
        return left_label, right_label

    def _draw_page(cbm_page: List[int], out_file: str):
        n = len(cbm_page)
        fig_w = max(6.0, 4.2 * n)
        fig_h = 4.2

        fig, axes = plt.subplots(1, n, figsize=(fig_w, fig_h), squeeze=False)
        axes = axes[0]

        band_lw = 1.5
        cbm_ms = 13.0
        cbm_mew = 0.1 * band_lw
        fit_ms = 3.0
        fit_mew = band_lw

        for ax_i, cbm_idx in enumerate(cbm_page):
            ax = axes[ax_i]
            k0 = float(k[cbm_idx])
            E0 = float(E[cbm_idx])

            idxs_fit = sorted(set(cbm_to_fitidxs.get(cbm_idx, [])), key=lambda ii: k[ii])

            if idxs_fit:
                kmin = float(np.min(k[idxs_fit])) - x_margin
                kmax = float(np.max(k[idxs_fit])) + x_margin
            else:
                kmin = k0 - x_margin
                kmax = k0 + x_margin

            ymin = E0 - Ewin
            ymax = E0 + Ewin

            mask_x = (k >= kmin) & (k <= kmax)
            if np.any(mask_x):
                ax.plot(k[mask_x], E[mask_x], linewidth=band_lw, label="Band (zoom)")
            else:
                ax.plot([k0], [E0], marker=r"$\ast$", markersize=cbm_ms,
                        markeredgewidth=cbm_mew, linestyle="None", label="CBM")

            ax.plot([k0], [E0], marker=r"$\ast$", markersize=cbm_ms,
                    markeredgewidth=cbm_mew, linestyle="None", label="CBM")

            if idxs_fit:
                ax.plot(k[idxs_fit], E[idxs_fit],
                        marker="o", markersize=fit_ms, markeredgewidth=fit_mew,
                        linestyle="None", label="Fit points")

            # 原始：对落在当前 xlim 的高对称点画竖线与刻度标签
            xticks, xticklabels = [], []
            for kv, names in merged:
                if kv < kmin - 1e-12 or kv > kmax + 1e-12:
                    continue
                ax.axvline(kv, linestyle="--", linewidth=1.0)
                uniq = []
                for nm in names:
                    if nm not in uniq:
                        uniq.append(nm)
                xticks.append(kv)
                xticklabels.append(_gammaize_label_text("/".join(uniq)))

            # 新增：左右“最近高对称点”（满足 >=0.05k）作为额外刻度标签，放在 kmin/kmax
            left_lab, right_lab = _nearest_hsp_labels_around_k0(k0)

            # 为了不和已有刻度重复（或 kmin/kmax 非常接近已有刻度），做一个小容差去重
            k_edge_tol = max(5e-4, tol)

            if left_lab is not None:
                # 左侧箭头应指向左（←），且“箭头在内侧” => 文本右端放箭头
                lab_text = f"{left_lab} \u2190"
                # 若 kmin 已经很接近某个现有刻度，就不再追加
                if not any(abs(kmin - t) <= k_edge_tol for t in xticks):
                    xticks.append(kmin)
                    xticklabels.append(lab_text)

            if right_lab is not None:
                # 右侧箭头应指向右（→），且“箭头在内侧” => 文本左端放箭头
                lab_text = f"\u2192 {right_lab}"
                if not any(abs(kmax - t) <= k_edge_tol for t in xticks):
                    xticks.append(kmax)
                    xticklabels.append(lab_text)

            # 排序（按 tick 位置），保证显示顺序正确
            if xticks:
                order = np.argsort(np.array(xticks, dtype=float))
                xticks_sorted = [xticks[i] for i in order]
                xticklabels_sorted = [xticklabels[i] for i in order]
                ax.set_xticks(xticks_sorted)
                ax.set_xticklabels(xticklabels_sorted, rotation=0, fontsize=9)
            else:
                ax.tick_params(axis="x", labelsize=9)

            ax.set_xlim(kmin, kmax)
            ax.set_ylim(ymin, ymax)

            ax.set_xlabel("k-path")
            if ax_i == 0:
                ax.set_ylabel("Energy (eV)")

            ax.set_title(f"CBM idx={cbm_idx}\nE0={E0:.4f} eV")

            ax.grid(True)
            ax.legend(loc="best", fontsize=9)

        # 适当留底部空间（给较长 ticklabel）
        try:
            fig.tight_layout()
            fig.subplots_adjust(bottom=0.25)
        except Exception:
            fig.subplots_adjust(left=0.06, right=0.98, top=0.90, bottom=0.25, wspace=0.25)

        fig.savefig(out_file, dpi=dpi)
        plt.close(fig)

    # 先按原逻辑估算一下像素宽度，决定是否分页
    n_total = len(cbm_candidates)
    fig_w_est = max(6.0, 4.2 * n_total)
    px_w_est = int(fig_w_est * dpi)

    root, ext = os.path.splitext(out_png)
    if ext.lower() == "":
        ext = ".png"

    if px_w_est < 65000:
        _draw_page(cbm_candidates, out_png)
        return

    # 需要分页
    per = max(1, int(max_panels_per_page))
    n_pages = (n_total + per - 1) // per
    for p in range(n_pages):
        a = p * per
        b = min(n_total, (p + 1) * per)
        out_file = f"{root}-{p+1:02d}{ext}"
        _draw_page(cbm_candidates[a:b], out_file)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="从 CBM.dat 与 KLABELS 计算所有最低能谷(Valley)的电子有效质量，并绘图标记拟合点"
    )
    parser.add_argument("-b", "--band", default="CBM.dat")
    parser.add_argument("-l", "--labels", default="KLABELS")
    parser.add_argument("-o", "--out", default="EM.dat")
    parser.add_argument("--png", default="band-em.png")
    parser.add_argument("--png_detail", default="band-em-detail.png")
    parser.add_argument("--npts", type=int, default=6)
    parser.add_argument("--dk", type=float, default=0.0)
    parser.add_argument("--tol", type=float, default=1e-3, help="重复k分段/标签匹配容差（建议 1e-3）")
    parser.add_argument("--emin_tol", type=float, default=1e-6,
                        help="判定“接近全局最低能量”的容差 (eV)。例如 1e-5~1e-4 可更宽松")

    # valley 聚类参数（保留你现在可正常跑的逻辑）
    parser.add_argument("--valley_gap_k", type=float, default=0.0,
                        help="同一能谷内低能点在 k 上允许的最大间隔。<=0 表示自动估计。")
    parser.add_argument("--valley_gap_factor", type=float, default=3.0,
                        help="valley_gap_k 自动估计系数：valley_gap_k = factor * median(k-step)。默认 3.0。")

    # 新增：解决 M|H 这类重复 k 处“另一段不是 CBM 但仍取点”
    parser.add_argument("--seg_match_etol", type=float, default=5e-3,
                        help="若 k0 命中多个 segment，只保留 |E(seg_k0)-E_ref|<=该阈值 的 segment (eV)。")

    # 新增：取点截断，避免端点不属于谷底还继续取点
    parser.add_argument("--valley_Ewin", type=float, default=0.20,
                        help="取点能量窗：只取 E<=E0+valley_Ewin 的点（eV）。<=0 表示不启用。")
    parser.add_argument("--jump_tol", type=float, default=0.50,
                        help="取点时相邻点能量跳跃超过该值(eV)就停止向外取点。")

    args = parser.parse_args(argv)

    k, E = read_band_dat(args.band)
    labels = read_klabels(args.labels)

    Emin = float(np.min(E))
    raw_candidates = np.where(E <= Emin + args.emin_tol)[0].astype(int).tolist()
    if not raw_candidates:
        raise RuntimeError("未找到 CBM 低能候选点（不应发生）。")

    segments = split_into_segments(k, tol=args.tol)
    if not segments:
        raise RuntimeError("未识别到 segment，请检查 tol 或数据是否含重复 k。")

    cbm_candidates, _ = select_valley_minima_indices(
        k=k, E=E, segments=segments,
        emin_tol=args.emin_tol,
        valley_gap_k=(args.valley_gap_k if args.valley_gap_k > 0 else None),
        valley_gap_factor=args.valley_gap_factor,
    )
    if not cbm_candidates:
        raise RuntimeError("聚类后未得到任何 valley CBM 点（请检查 emin_tol/数据）。")

    fit_records: List[Dict[str, Any]] = []
    written_rows: set = set()
    rows_out: List[str] = []

    for cbm_rank, idx_min in enumerate(cbm_candidates):
        k0 = float(k[idx_min])
        E_ref = float(E[idx_min])  # valley 代表点能量

        seg_ids = find_segments_touching_k0(k, segments, k0, tol=args.tol)
        if not seg_ids:
            for si, (s, e) in enumerate(segments):
                if s <= idx_min <= e:
                    seg_ids = [si]
                    break

        seg_ids_filtered: List[int] = []
        for si in seg_ids:
            s, e = segments[si]
            local_indices = np.arange(s, e + 1)
            j = int(local_indices[np.argmin(np.abs(k[s:e+1] - k0))])
            if abs(float(E[j]) - E_ref) <= args.seg_match_etol:
                seg_ids_filtered.append(si)

        if not seg_ids_filtered:
            for si, (s, e) in enumerate(segments):
                if s <= idx_min <= e:
                    seg_ids_filtered = [si]
                    break

        for si in seg_ids_filtered:
            s, e = segments[si]
            local_indices = np.arange(s, e + 1)
            j = int(local_indices[np.argmin(np.abs(k[s:e+1] - k0))])

            k0_seg = float(k[j])
            E0_seg = float(E[j])

            seg_start_label = label_at_k_with_role(float(k[s]), labels, tol=max(args.tol, 5e-4),
                                                   role="seg_start", fallback="START")
            seg_end_label = label_at_k_with_role(float(k[e]), labels, tol=max(args.tol, 5e-4),
                                                 role="seg_end", fallback="END")

            cbm_role = "point"
            if abs(k0_seg - k[s]) <= max(args.tol, 5e-4):
                cbm_role = "seg_start"
            if abs(k0_seg - k[e]) <= max(args.tol, 5e-4):
                cbm_role = "seg_end"
            cbm_label = label_at_k_with_role(k0_seg, labels, tol=max(args.tol, 5e-4),
                                             role=cbm_role, fallback=f"CBM{cbm_rank+1}")

            # 左
            k_fit, E_fit, idxs = pick_points_one_side_indices(
                k, E, j, (s, e), "left", args.npts, args.dk,
                valley_Ewin=args.valley_Ewin, jump_tol=args.jump_tol
            )
            if len(idxs) >= 3:
                fit = quad_fit_effective_mass(k_fit, E_fit, k0_seg)
                dir_name = make_direction_name(cbm_label, seg_start_label)
                key = (idx_min, si, dir_name)
                if key not in written_rows:
                    written_rows.add(key)
                    fit_records.append({"cbm_idx": idx_min, "dir_name": f"{dir_name} (idx={idx_min})", "fit_indices": idxs})

                    note = "" if math.isfinite(fit["mstar_m0"]) else "WARNING: curvature<=0/拟合失败"
                    rows_out.append(
                        f"{idx_min:6d}  {si:3d}  {dir_name:<18s}  {k0_seg:10.6f}  {E0_seg:10.6f}  "
                        f"{fit['curvature_eVA2']:14.6f}  {fit['mstar_m0']:10.6f}  "
                        f"{fit['r2']:8.5f}  {fit['rmse_eV']:10.6e}  {note}"
                    )

            # 右
            k_fit, E_fit, idxs = pick_points_one_side_indices(
                k, E, j, (s, e), "right", args.npts, args.dk,
                valley_Ewin=args.valley_Ewin, jump_tol=args.jump_tol
            )
            if len(idxs) >= 3:
                fit = quad_fit_effective_mass(k_fit, E_fit, k0_seg)
                dir_name = make_direction_name(cbm_label, seg_end_label)
                key = (idx_min, si, dir_name)
                if key not in written_rows:
                    written_rows.add(key)
                    fit_records.append({"cbm_idx": idx_min, "dir_name": f"{dir_name} (idx={idx_min})", "fit_indices": idxs})

                    note = "" if math.isfinite(fit["mstar_m0"]) else "WARNING: curvature<=0/拟合失败"
                    rows_out.append(
                        f"{idx_min:6d}  {si:3d}  {dir_name:<18s}  {k0_seg:10.6f}  {E0_seg:10.6f}  "
                        f"{fit['curvature_eVA2']:14.6f}  {fit['mstar_m0']:10.6f}  "
                        f"{fit['r2']:8.5f}  {fit['rmse_eV']:10.6e}  {note}"
                    )

    dk_med = _robust_median_k_step(k)
    auto_gap = (args.valley_gap_factor * dk_med) if (args.valley_gap_k <= 0) else args.valley_gap_k

    with open(args.out, "w", encoding="utf-8") as fw:
        fw.write(f"# Emin = {Emin:.10f} eV, emin_tol = {args.emin_tol} eV\n")
        fw.write(f"# raw low-E candidates = {len(raw_candidates)}, valley minima after clustering = {len(cbm_candidates)}\n")
        fw.write(f"# valley_gap_k = {auto_gap:.6g} (k unit), valley_gap_factor={args.valley_gap_factor}, median(k-step)={dk_med:.6g}\n")
        fw.write(f"# seg_match_etol={args.seg_match_etol} eV, valley_Ewin={args.valley_Ewin} eV, jump_tol={args.jump_tol} eV\n")
        fw.write(f"# npts={args.npts}, dk={args.dk}, tol={args.tol}\n")
        fw.write("# cbm_idx  segment_id  direction(CBM->END)  k0  E0  d2E/dk2(eV·Å^2)  m_eff(m0)  R2  RMSE(eV)  note\n")
        for line in rows_out:
            fw.write(line + "\n")

    plot_band_with_fit_points(k, E, cbm_candidates, fit_records, labels, args.png, tol=args.tol)
    plot_band_em_detail(k, E, cbm_candidates, fit_records, labels, args.png_detail, tol=args.tol)

    print(f"[OK] Emin={Emin:.10f} eV, emin_tol={args.emin_tol}")
    print(f"[OK] raw candidates={len(raw_candidates)} -> valley minima={len(cbm_candidates)}")
    print(f"[OK] valley_gap_k={auto_gap:.6g} (k unit), median(k-step)={dk_med:.6g}")
    print(f"[OK] 输出：{args.out}")
    print(f"[OK] 图片：{args.png}")
    print(f"[OK] 细节组图：{args.png_detail}")


if __name__ == "__main__":
    main()
