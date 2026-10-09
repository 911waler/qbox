"""Read native MATDYN dispersions and recover only evidenced path labels.

The gnuplot table contains distances and frequencies, not q coordinates or
symmetry names. Prefer checked qbox metadata, then a matching MATDYN input;
otherwise keep the numerical path. No crystal-path generator is used here.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

import numpy as np


class PathAnnotationError(ValueError):
    """An identified qbox path must not fall back to plotting its guard rows."""


def _label(value):
    text = str(value).strip()
    return 'Γ' if text.upper() in ('GAMMA', 'Γ', '\\GAMMA', 'GG') else text


def _numbers(text):
    try:
        values = [float(item.replace('D', 'e').replace('d', 'e')) for item in text.split()]
    except ValueError:
        raise ValueError(f'声子数据含非法数值：{text}') from None
    if not all(np.isfinite(values)):
        raise ValueError('声子数据含非有限数值。')
    return values


def _read_gp(path):
    rows, breaks, pending_break = [], set(), False
    width = None
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            pending_break = bool(rows)
            continue
        body = re.split(r'[#!]', line, maxsplit=1)[0].strip()
        if not body:
            continue
        values = _numbers(body)
        if len(values) < 4 or (len(values) - 1) % 3:
            raise ValueError(f'{path.name} 第 {number} 行需要距离列和 3N 个频率列。')
        if width is not None and len(values) != width:
            raise ValueError(f'{path.name} 第 {number} 行列数与前文不一致。')
        if pending_break:
            breaks.add(len(rows))
        pending_break = False
        width = len(values)
        rows.append(values)
    if len(rows) < 2:
        raise ValueError('声子色散至少需要两个不同的 q 点；空文件或单点频率不适合绘制色散。')
    data = np.asarray(rows, dtype=float)
    return data[:, 0], data[:, 1:], breaks


def _read_freq(path):
    from qbox.postprocess.phonon_plot import read_frequencies
    points, modes = read_frequencies(path.read_text(encoding='utf-8-sig'))
    if len(points) < 2 or modes.shape[1] % 3:
        raise ValueError('声子色散需要至少两个 q 点以及 3N 个频率分支。')
    x = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    return points, modes, x


def _ticks(row_labels, x):
    ticks = []
    for row, name in sorted(row_labels.items()):
        name = _label(name)
        if not name:
            continue
        coordinate = float(x[row])
        if ticks and abs(ticks[-1][0] - coordinate) < 1e-8:
            prior = ticks[-1][1]
            if name not in prior.split('|'):
                ticks[-1] = (ticks[-1][0], prior + '|' + name)
        else:
            ticks.append((coordinate, name))
    return ticks


def _split(x, modes, breaks, row_labels=None):
    """Remove only explicitly established jumps, keeping every frequency row."""
    boundaries = {0, len(x), *breaks, *(int(i) + 1 for i in np.flatnonzero(np.diff(x) <= 0))}
    boundaries = sorted(boundaries)
    segments, mapped = [], np.zeros(len(x), dtype=float)
    cumulative = float(x[0])
    for first, last in zip(boundaries, boundaries[1:]):
        section = x[first:last] - x[first] + cumulative
        mapped[first:last] = section
        segments.append((section, modes[first:last]))
        cumulative = float(section[-1])
    if not any(len(values) > 1 and values[-1] > values[0] for values, _ in segments):
        raise ValueError('数据没有包含两个不同 q 点的连续线段，不适合绘制声子色散。')
    return segments, _ticks(row_labels or {}, mapped)


def _companion(freq_file, modes):
    if not freq_file.exists():
        return None
    points, companion_modes, _ = _read_freq(freq_file)
    if companion_modes.shape != modes.shape or not np.allclose(companion_modes, modes, atol=1.1e-4, rtol=0):
        raise ValueError('同名 .freq 与 .freq.gp 的频率数据不匹配。')
    return points


def _check_axis(x, points):
    if points.shape != (len(x), 3) or not np.all(np.isfinite(points)):
        raise ValueError('频率文件 q 点数或坐标与路径元数据不匹配。')
    expected_steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
    # QE prints the native axis and Cartesian q coordinates with six decimals.
    if abs(x[0]) > 2e-6 or np.any(np.diff(x) < 0) or not np.allclose(
            np.diff(x), expected_steps, atol=4e-6, rtol=0):
        raise ValueError('.freq.gp 累计距离与路径 q 坐标不匹配。')


def _from_json(path, x, modes, points, freq_file):
    from qbox.postprocess.phonon_plot import prepare_segments
    metadata = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(metadata, dict):
        raise ValueError('路径元数据必须为 JSON 对象。')
    if points is None:
        expected = np.asarray(metadata.get('qpoints_matdyn', metadata.get('qpoints', [])), dtype=float)
        _check_axis(x, expected)
        companion = _companion(freq_file, modes)
        if companion is not None and (companion.shape != expected.shape or not np.allclose(
                companion, expected, atol=2e-6, rtol=0)):
            raise ValueError('同名 .freq 的 q 坐标与路径元数据不匹配。')
        points = expected
    return prepare_segments(points, modes, metadata)


def _input_data(path):
    # Reuse qbox's quote/comment-aware Fortran namelist parser so a slash or
    # exclamation mark in a quoted output pathname cannot truncate &INPUT.
    from qbox.io.wannier_inputs import _parse_namelists
    text = path.read_text(encoding='utf-8-sig')
    sections, values, _ = _parse_namelists(text)
    if 'input' not in values:
        raise ValueError('MATDYN 输入缺少 &INPUT。')
    return values['input'], text[sections['input'].end:]


def _matches_output(path, settings, freq_file):
    output = settings.get('flfrq', 'matdyn.freq')
    if not isinstance(output, str) or not output.strip():
        return False
    return (path.parent / output).resolve() == freq_file.resolve()


def _find_matdyn(input_path, freq_file, notes):
    candidates = []
    for path in sorted(input_path.parent.glob('*.in')):
        try:
            settings, _ = _input_data(path)
        except (OSError, ValueError, TypeError):
            continue
        if _matches_output(path, settings, freq_file):
            candidates.append(path)
    if len(candidates) > 1:
        if any(_has_qbox_annotations(_input_data(path)[1]) for path in candidates):
            raise PathAnnotationError('多个 MATDYN 输入指向此数据且含 qbox 路径标记；'
                                      '请明确选择输入，避免绘入保护点。')
        notes.append('多个 MATDYN 输入的 flfrq 指向此数据，未自动采用：' +
                     '、'.join(path.name for path in candidates) + '；可手动指定输入。')
        return None
    return candidates[0] if candidates else None


def _comment_label(comment):
    # Match the electronic-band convention: the first comment token is the
    # supplied point label, and the remaining tokens can explain the point.
    fields = comment.split()
    return _label(fields[0]) if fields and not fields[0].lower().startswith('qbox:') else ''


def _qbox_tokens(comment):
    return [token.lower() for token in comment.split() if token.lower().startswith('qbox:')]


def _has_qbox_annotations(tail):
    return any(_qbox_tokens(line.partition('!')[2]) for line in tail.splitlines())


def _annotated_sections(header_comment, comments, band):
    header = _qbox_tokens(header_comment)
    markers = [_qbox_tokens(comment) for comment in comments]
    if not header and not any(markers):
        return None
    if header != ['qbox:path-v1']:
        raise PathAnnotationError('qbox 路径标记需要唯一且受支持的 qbox:path-v1 版本声明。')
    if band:
        raise PathAnnotationError('qbox:path-v1 仅适用于显式 q 点列表，不能用于插值顶点。')
    sections, guards, start = [], set(), None
    for row, (tokens, comment) in enumerate(zip(markers, comments)):
        if len(tokens) > 1 or any(token not in ('qbox:start', 'qbox:end', 'qbox:guard') for token in tokens):
            raise PathAnnotationError(f'第 {row + 1} 个 q 点含重复、矛盾或未知的 qbox 路径标记。')
        marker = tokens[0] if tokens else None
        if marker == 'qbox:guard':
            if start is not None or _comment_label(comment):
                raise PathAnnotationError('qbox 保护点不能位于绘图线段内，也不能带高对称点标签。')
            guards.add(row)
        elif marker == 'qbox:start':
            if start is not None:
                raise PathAnnotationError('qbox 线段起点重复，前一线段缺少终点。')
            start = row
        elif marker == 'qbox:end':
            if start is None or row <= start:
                raise PathAnnotationError('qbox 线段终点缺少配对起点，或线段不足两个 q 点。')
            sections.append((start, row))
            start = None
        elif start is None:
            raise PathAnnotationError(f'第 {row + 1} 个非保护 q 点未被 qbox 路径线段覆盖。')
    if start is not None or not sections:
        raise PathAnnotationError('qbox 路径必须包含完整配对且至少两个 q 点的线段。')
    return sections, guards


def _parse_q_rows(tail, band, *, return_annotations=False):
    lines = [line for line in tail.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if not lines:
        raise ValueError('MATDYN 输入没有 q 点列表。')
    count_body, _, header_comment = lines[0].partition('!')
    count_text = count_body.strip()
    if not re.fullmatch(r'\d+', count_text) or int(count_text) < 2:
        raise ValueError('MATDYN 路径需要至少两个顶点或 q 点。')
    count = int(count_text)
    if len(lines) - 1 != count:
        raise ValueError('MATDYN q 点行数与声明不匹配。')
    annotations = _annotated_sections(header_comment, [line.partition('!')[2] for line in lines[1:]], band)
    points, counts, labels, named = [], [], {}, None
    for index, line in enumerate(lines[1:]):
        body, _, comment = line.partition('!')
        fields = body.split()
        is_named = bool(fields and re.match(r'[A-Za-zΓ]', fields[0]))
        if named is not None and named != is_named:
            raise ValueError('MATDYN 路径不能混合名称顶点和数值顶点。')
        named = is_named
        if is_named:
            if not band or len(fields) != 2 or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,2}|Γ', fields[0]):
                raise ValueError('无法解析 MATDYN 名称顶点。')
            labels[index] = _label(fields[0])
            count_value = fields[1]
        else:
            if len(fields) < (4 if band else 3):
                raise ValueError('MATDYN q 点缺少坐标或插值数。')
            values = _numbers(' '.join(fields[:3]))
            points.append(values)
            count_value = fields[3] if band else '1'
            label = _comment_label(comment)
            if label:
                labels[index] = label
        if not re.fullmatch(r'\+?\d+', count_value):
            raise ValueError('MATDYN 路径插值数必须为非负整数。')
        counts.append(int(count_value))
    result = (None if named else np.asarray(points)), counts, labels
    return (*result, annotations) if return_annotations else result


def _split_annotated(x, modes, annotations, labels, raw_breaks):
    """Use original row positions; identical Gamma coordinates are not merged."""
    sections, guards = annotations
    if np.any(np.diff(x) < 0):
        raise PathAnnotationError('带 qbox 路径标记的原始累计距离不能回退。')
    segments, mapped = [], np.full(len(x), np.nan)
    cumulative = 0.
    for first, last in sections:
        if any(first < row <= last for row in raw_breaks):
            raise PathAnnotationError('数据空行断点与 qbox 声子路径线段冲突。')
        section = x[first:last + 1] - x[first] + cumulative
        if np.any(np.diff(section) <= 0):
            raise PathAnnotationError('qbox 路径每段的原始距离必须严格递增。')
        mapped[first:last + 1] = section
        segments.append((section, modes[first:last + 1]))
        cumulative = float(section[-1])
    return segments, _ticks({row: label for row, label in labels.items() if row not in guards}, mapped)


def _from_matdyn(path, freq_file, x, modes, points, raw_breaks):
    settings, tail = _input_data(path)
    try:
        return _from_matdyn_data(path, freq_file, x, modes, points, raw_breaks, settings, tail)
    except (ValueError, TypeError, KeyError, IndexError, OSError) as error:
        if _has_qbox_annotations(tail):
            raise PathAnnotationError(f'qbox 路径输入或对应频率数据无效：{error}') from error
        raise


def _from_matdyn_data(path, freq_file, x, modes, points, raw_breaks, settings, tail):
    if not _matches_output(path, settings, freq_file):
        raise ValueError('MATDYN 输入的 flfrq 与当前频率文件不匹配。')
    if settings.get('dos', False):
        raise ValueError('dos=.true. 的 MATDYN 输入不是声子色散路径。')
    if settings.get('readtau', False):
        raise ValueError('readtau=.true. 需要力常数结构信息，无法可靠恢复 q 点行。')
    band = settings.get('q_in_band_form', False)
    crystal = settings.get('q_in_cryst_coord', False)
    if not isinstance(band, bool) or not isinstance(crystal, bool):
        raise ValueError('MATDYN q 路径设置必须为 Fortran 逻辑值。')
    vertices, counts, labels, annotations = _parse_q_rows(tail, band, return_annotations=True)
    row_labels, breaks = {}, set(raw_breaks)
    expanded = None
    if band:
        indices = [0]
        for index, count in enumerate(counts[:-1]):
            indices.append(indices[-1] + max(count, 1))
            if count == 0:
                breaks.add(indices[-1])
        if indices[-1] + 1 != len(x):
            raise ValueError('MATDYN 插值后的 q 点数与频率文件不匹配。')
        row_labels = {indices[index]: label for index, label in labels.items()}
        if vertices is not None:
            expanded = [vertices[0]]
            for index, count in enumerate(counts[:-1]):
                if count:
                    expanded.extend(vertices[index] + fraction / count * (vertices[index + 1] - vertices[index])
                                    for fraction in range(1, count + 1))
                else:
                    expanded.append(vertices[index + 1])
            expanded = np.asarray(expanded)
    else:
        if len(counts) != len(x):
            raise ValueError('MATDYN 显式 q 点数与频率文件不匹配。')
        expanded, row_labels = vertices, labels
    companion = points if points is not None else _companion(freq_file, modes)
    if companion is not None:
        _check_axis(x, companion)
    notes = []
    if expanded is not None and not crystal:
        _check_axis(x, expanded)
        if companion is not None and (companion.shape != expanded.shape or not np.allclose(
                companion, expanded, atol=2e-6, rtol=0)):
            raise ValueError('MATDYN Cartesian q 坐标与同名 .freq 不匹配。')
    else:
        notes.append('MATDYN 路径按 flfrq 和插值点数匹配；缺少晶胞信息，未核验晶体坐标或名称顶点的 Cartesian q 坐标。')
    if annotations is not None:
        segments, ticks = _split_annotated(x, modes, annotations, row_labels, raw_breaks)
        notes.append('按 MATDYN 行尾 qbox 路径标记分段并排除保护点；标签对应原始 q 点行。')
    else:
        segments, ticks = _split(x, modes, breaks, row_labels)
    return segments, ticks, notes


def prepare_plot(input_path, *, path_file=None, matdyn_file=None, tick_rows=None, break_rows=None):
    """Return ``(segments, ticks, notes)`` for a .freq.gp or native .freq.

    ``segments`` are (distance, frequency matrix) arrays; frequencies remain in
    cm^-1, including negative values. Explicit sidecars fail on mismatch;
    automatic sidecars report the issue and fall back. Manual ticks and breaks
    address original, one-based numerical data rows and override sidecars.
    """
    input_path = Path(input_path)
    is_gp = input_path.name.lower().endswith('.freq.gp')
    if is_gp:
        freq_file = input_path.with_suffix('')
        x, modes, raw_breaks = _read_gp(input_path)
        points = None
    else:
        freq_file = input_path
        points, modes, x = _read_freq(input_path)
        raw_breaks = set()
    notes = []
    if tick_rows is not None or break_rows is not None:
        labels, breaks = {}, set(raw_breaks)
        for row, label in (tick_rows or {}).items():
            if type(row) is not int or not 1 <= row <= len(x) or not isinstance(label, str) or not label.strip():
                raise ValueError('手动标签需要有效的原始数据行号（从 1 开始）和非空标签。')
            labels[row - 1] = label
        for row in break_rows or []:
            if type(row) is not int or not 2 <= row <= len(x):
                raise ValueError('手动断点必须是第 2 行至末行之间的新段首行号。')
            breaks.add(row - 1)
        segments, ticks = _split(x, modes, breaks, labels)
        return segments, ticks, ['采用手动原始行号设置，替代自动路径元数据；所有频率行均保留。']
    automatic_path = freq_file.with_suffix('.path.json')
    selected_path = Path(path_file) if path_file is not None else automatic_path
    if path_file is not None or (matdyn_file is None and selected_path.exists()):
        try:
            segments, ticks = _from_json(selected_path, x, modes, points, freq_file)
        except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
            if path_file is not None:
                raise ValueError(f'路径元数据不可用：{error}') from error
            notes.append(f'未采用 {selected_path.name}：{error}')
        else:
            return segments, ticks, notes + [f'高对称路径来源：{selected_path.name}']
    selected_input = Path(matdyn_file) if matdyn_file is not None else _find_matdyn(input_path, freq_file, notes)
    if selected_input is not None:
        try:
            segments, ticks, more_notes = _from_matdyn(selected_input, freq_file, x, modes, points, raw_breaks)
        except PathAnnotationError as error:
            raise PathAnnotationError(f'{selected_input.name}：{error}') from error
        except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
            if matdyn_file is not None:
                raise ValueError(f'MATDYN 路径不可用：{error}') from error
            notes.append(f'未采用 {selected_input.name}：{error}')
        else:
            more_notes.insert(0, f'高对称路径来源：{selected_input.name}')
            if not ticks:
                more_notes.append('MATDYN 输入没有可用的高对称点标签，保留数值横坐标。')
            return segments, ticks, notes + more_notes
    segments, ticks = _split(x, modes, raw_breaks)
    notes.append('没有可靠的高对称点标签；按数据距离绘图，仅在空行及重复或回退的距离处断开。')
    return segments, ticks, notes
