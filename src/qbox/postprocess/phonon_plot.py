"""Plot QE phonon dispersions, including external matdyn .freq.gp tables."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

import numpy as np


def _numbers(line):
    try:
        values = [float(value.replace('D', 'e').replace('d', 'e')) for value in line.split()]
    except ValueError:
        raise ValueError(f'频率文件含非法数值：{line}') from None
    if not all(np.isfinite(values)):
        raise ValueError('频率文件含非有限数值。')
    return values


def read_frequencies(text):
    """Read the documented &plot header and q/vector frequency blocks."""
    header = re.search(r'&plot\b(.*?)/', text, re.S | re.I)
    if header is None:
        raise ValueError('频率文件缺少 &plot nbnd=..., nks=... / 头部。')
    counts = dict((key.lower(), int(value)) for key, value in
                  re.findall(r'\b(nbnd|nks)\s*=\s*(\d+)', header[1], re.I))
    branches, count = counts.get('nbnd', 0), counts.get('nks', 0)
    if branches < 1 or count < 1:
        raise ValueError('频率文件 nbnd 和 nks 必须为正整数。')
    lines = [line.strip() for line in text[header.end():].splitlines() if line.strip()]
    cursor, points, modes = 0, [], []
    for index in range(count):
        if cursor >= len(lines):
            raise ValueError(f'频率文件不足 {count} 个 q 点，缺少第 {index + 1} 点。')
        point = _numbers(lines[cursor])
        cursor += 1
        if len(point) not in (3, 4):
            raise ValueError(f'第 {index + 1} 个 q 点需要三个坐标及可选的权重。')
        values = []
        while len(values) < branches and cursor < len(lines):
            values.extend(_numbers(lines[cursor]))
            cursor += 1
        if len(values) != branches:
            raise ValueError(f'第 {index + 1} 个 q 点的频率数与 nbnd={branches} 不符。')
        points.append(point[:3])
        modes.append(values)
    if cursor != len(lines):
        raise ValueError('频率文件含超出 nks/nbnd 声明的数据。')
    return np.asarray(points), np.asarray(modes)


def _label(value):
    return 'Γ' if str(value).upper() in ('GAMMA', 'Γ', '\\GAMMA') else str(value)


def prepare_segments(points, modes, metadata):
    """Validate metadata, exclude guard q points, and preserve disconnected lines."""
    expected = np.asarray(metadata.get('qpoints_matdyn', metadata.get('qpoints', [])), dtype=float)
    if expected.shape != points.shape or not np.allclose(expected, points, atol=2e-6, rtol=0):
        raise ValueError('频率文件 q 点数或坐标与路径元数据不匹配。')
    nat = metadata.get('nat')
    if nat is not None and (not isinstance(nat, int) or nat <= 0 or modes.shape[1] != 3 * nat):
        raise ValueError('频率分支数必须与路径结构的 3×nat 一致。')
    distances = metadata.get('distances', [])
    if len(distances) != len(points):
        raise ValueError('路径距离数量与 q 点数不一致。')
    guards = set(metadata.get('guard_indices', []))
    sections = metadata.get('segments', [])
    if not isinstance(sections, list) or any(not isinstance(section, dict) for section in sections):
        raise ValueError('路径线段必须为包含 start、end 的对象列表。')
    segments, ticks, covered = [], [], set()
    for section in sections:
        start, end = section.get('start'), section.get('end')
        if (not isinstance(start, int) or not isinstance(end, int)
                or not 0 <= start < end < len(points)):
            raise ValueError('路径线段索引不合法。')
        indices = set(range(start, end + 1))
        if indices & guards:
            raise ValueError('用于隔开 Gamma 点方向的保护点不能属于绘图线段。')
        if any(value is None for value in distances[start:end + 1]):
            raise ValueError('绘图线段中缺少路径距离。')
        x = np.asarray(distances[start:end + 1], dtype=float)
        if not np.all(np.isfinite(x)) or np.any(np.diff(x) <= 0):
            raise ValueError('每条路径线段的距离必须有限并严格递增。')
        if segments and x[0] < segments[-1][0][-1] - 1e-9:
            raise ValueError('路径线段顺序与累计距离不匹配。')
        segments.append((x, modes[start:end + 1]))
        covered.update(indices)
        labels = metadata.get('labels', [])
        for index, coordinate, label_key in ((start, x[0], 'start_label'), (end, x[-1], 'end_label')):
            label = _label(section.get(label_key, labels[index] if index < len(labels) else ''))
            if ticks and abs(ticks[-1][0] - coordinate) < 1e-9:
                previous = ticks[-1][1]
                if label and label not in previous.split('|'):
                    ticks[-1] = (float(coordinate), previous + ('|' if previous else '') + label)
            else:
                ticks.append((float(coordinate), label))
    if not segments or covered != set(range(len(points))) - guards:
        raise ValueError('路径线段没有覆盖全部有效 q 点。')
    return segments, ticks


def render_plot(segments, ticks, output_prefix):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    with plt.rc_context({'font.size': 9, 'svg.fonttype': 'none', 'axes.linewidth': .8}):
        # Leave room for adjacent boundary labels such as A|L and M|H.
        width = max(6.4, min(12., .8 * len(ticks)))
        figure, axis = plt.subplots(figsize=(width, 4.2), constrained_layout=True)
        for x, modes in segments:
            if len(x) == 1:
                axis.plot(x, modes, color='#245578', marker='.', markersize=3, linestyle='none')
            else:
                axis.plot(x, modes, color='#245578', linewidth=.9)
        axis.axhline(0, color='#AD4843', linestyle='--', linewidth=.7)
        for coordinate, _ in ticks:
            axis.axvline(coordinate, color='#999999', linewidth=.5, zorder=0)
        if ticks:
            axis.set_xticks([x for x, _ in ticks], [label for _, label in ticks])
        axis.set_xlim(segments[0][0][0], segments[-1][0][-1])
        axis.set_ylabel(r'Frequency (cm$^{-1}$)')
        axis.set_xlabel('Wave vector')
        output_prefix = Path(output_prefix)
        for suffix in ('.png', '.svg'):
            figure.savefig(str(output_prefix) + suffix, dpi=300)
        plt.close(figure)


def parse_tick_rows(value):
    """Parse explicit labels; row numbers count numeric records, not comments."""
    result = {}
    for item in value.replace('，', ',').split(','):
        if not item.strip():
            continue
        match = re.fullmatch(r'\s*([1-9]\d*)\s*[:：]\s*(\S.*?)\s*', item)
        if not match or int(match[1]) in result:
            raise ValueError('标签格式应为 1:Γ,21:X,41:M，行号不能重复。')
        result[int(match[1])] = _label(match[2])
    return result


def parse_break_rows(value):
    result = []
    for item in re.split(r'[,，\s]+', value.strip()):
        if not item:
            continue
        if not re.fullmatch(r'[1-9]\d*', item) or int(item) <= 1 or int(item) in result:
            raise ValueError('断点应为新线段首行编号，例如 42,83，且必须大于 1、不重复。')
        result.append(int(item))
    return sorted(result)


def _output_prefix(source, requested=None):
    if requested is not None:
        target = Path(requested)
        return target.with_suffix('') if target.suffix.lower() in ('.png', '.svg') else target
    name = source.name
    for suffix in ('.freq.gp', '.freq'):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    return source.with_name(name + '_phonon')


def plot_files(files, options=None, *, output_prefix=None, output=print):
    from .phonon_plot_data import prepare_plot
    failed = 0
    options = options or {}
    for source in files:
        try:
            segments, ticks, notes = prepare_plot(source, **options.get(source, {}))
            for note in notes:
                output(f'{source.name}：{note}')
            target = _output_prefix(source, output_prefix)
            render_plot(segments, ticks, target)
            output(f'已生成：{target}.png 和 {target}.svg')
        except (OSError, ValueError, TypeError, KeyError) as error:
            failed += 1
            output(f'绘图失败：{source.name}：{error}')
    if len(files) > 1:
        output(f'声子谱绘图完成：成功 {len(files) - failed}，失败 {failed}。')
    return int(failed != 0)


def _ask(input_fn, prompt):
    try:
        return input_fn(prompt).strip()
    except (EOFError, StopIteration):
        raise EOFError('输入已结束；未执行绘图。') from None


def _edit_path_options(source, options, input_fn, output):
    from .phonon_plot_data import prepare_plot
    while True:
        output(f'路径设置：{source.name}')
        output('  1) 指定配套路径文件（JSON / matdyn 输入）')
        output('  2) 手动设置高对称点与断点')
        output('  3) 恢复自动识别')
        output('  0) 返回')
        action = _ask(input_fn, '选择设置：') or '0'
        try:
            if action == '0':
                return
            if action == '3':
                options.pop(source, None)
                output('已恢复自动识别。')
                continue
            if action == '1':
                raw = _ask(input_fn, '路径文件（回车取消）：')
                if not raw:
                    continue
                path = Path(raw).expanduser().resolve()
                proposed = {'path_file' if path.suffix.lower() == '.json' else 'matdyn_file': path}
            elif action == '2':
                output('行号从 1 开始，只数数据行；空行和注释不计数。')
                output('手动设置将替代自动路径设置。')
                ticks = parse_tick_rows(_ask(input_fn, '高对称点，例如 1:Γ,21:X,41:M（回车不标注）：'))
                breaks = parse_break_rows(_ask(input_fn, '新线段首行，例如 42,83（回车无额外断点）：'))
                proposed = {'tick_rows': ticks, 'break_rows': breaks}
            else:
                output('请输入有效的设置编号。')
                continue
            _, _, notes = prepare_plot(source, **proposed)
            options[source] = proposed
            output('路径设置已保存。')
            for note in notes:
                output(note)
        except (OSError, ValueError, TypeError, KeyError) as error:
            output(f'设置无效：{error}')


def run_interactive(files, options=None, *, output_prefix=None, input_fn=input, output=print):
    options = dict(options or {})
    try:
        while True:
            output(f'声子谱绘图：找到 {len(files)} 个数据文件（cm^-1，保留虚频）。')
            for index, source in enumerate(files, 1):
                state = '，已指定路径设置' if source in options else ''
                output(f'  [{index}] {source.name}{state}')
            output('  自动查找配套路径；缺少信息时使用数值横轴。')
            output('  0) 绘制全部（回车）')
            output('  1) 设置高对称点与断点')
            output('  2) 返回')
            action = _ask(input_fn, '选择操作：') or '0'
            if action == '0':
                return plot_files(files, options, output_prefix=output_prefix, output=output)
            if action == '2':
                return 0
            if action != '1':
                output('请输入有效的操作编号。')
                continue
            answer = _ask(input_fn, '选择文件编号（b 返回）：')
            if answer.lower() == 'b':
                continue
            if not answer.isdigit() or not 1 <= int(answer) <= len(files):
                output('文件编号无效。')
                continue
            _edit_path_options(files[int(answer) - 1], options, input_fn, output)
    except EOFError as error:
        output(str(error))
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description='批量绘制 QE 声子色散（cm^-1，保留虚频）')
    parser.add_argument('-i', '--input', type=Path, action='append',
                        help='matdyn 的 .freq.gp 或 .freq；可重复指定，默认扫描当前目录全部 *.freq.gp')
    parser.add_argument('--directory', type=Path, default=Path('.'), help='批量扫描的目录')
    parser.add_argument('--path', type=Path, help='指定单个数据文件的 .path.json（默认自动查找）')
    parser.add_argument('--matdyn', type=Path, help='指定单个数据文件的 matdyn 输入')
    parser.add_argument('--ticks', help='手动标注：1:Γ,21:X,41:M；行号从 1 开始，只数数据行')
    parser.add_argument('--breaks', help='手动断点：新线段首行编号，例如 42,83')
    parser.add_argument('--interactive', action='store_true', help='打开交互式批量绘图菜单')
    parser.add_argument('-o', '--output', type=Path,
                        help='单个文件的输出前缀；默认 <数据前缀>_phonon，同时生成 PNG 和 SVG')
    args = parser.parse_args(argv)
    try:
        files = list(dict.fromkeys(path.expanduser().resolve() for path in args.input)) if args.input else sorted(
            path.resolve() for path in args.directory.expanduser().glob('*.freq.gp') if path.is_file())
        if not files:
            raise ValueError(f'未找到 *.freq.gp：{args.directory.resolve()}')
        custom = any(value is not None for value in (args.path, args.matdyn, args.ticks, args.breaks, args.output))
        if len(files) != 1 and custom:
            raise ValueError('指定路径、标签、断点或输出前缀时请只选择一个文件；批量设置请使用交互菜单。')
        if sum(value is not None for value in (args.path, args.matdyn)) > 1:
            raise ValueError('--path 和 --matdyn 只能选择一个。')
        if (args.path is not None or args.matdyn is not None) and (args.ticks is not None or args.breaks is not None):
            raise ValueError('配套路径文件与手动行号设置不能同时使用。')
        selected = {}
        if args.path is not None:
            selected['path_file'] = args.path.expanduser().resolve()
        if args.matdyn is not None:
            selected['matdyn_file'] = args.matdyn.expanduser().resolve()
        if args.ticks is not None:
            selected['tick_rows'] = parse_tick_rows(args.ticks)
        if args.breaks is not None:
            selected['break_rows'] = parse_break_rows(args.breaks)
        options = {files[0]: selected} if selected else {}
        if args.interactive:
            return run_interactive(files, options, output_prefix=args.output)
        return plot_files(files, options, output_prefix=args.output)
    except (OSError, ValueError) as error:
        print(f'错误：{error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
