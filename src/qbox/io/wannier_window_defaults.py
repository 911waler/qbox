"""Editable trial windows from a verified, complete NSCF spectrum.

The outer window includes all retained states on the sampled mesh. The user's
trial frozen range extends from 5 eV below to 10 eV above an explicit Fermi or
sampled-gap reference. It is intersected with the available outer window and
capped so that no k point contains more frozen states than num_wann. These are
initial settings, not an accuracy criterion for the resulting interpolation.
"""
import hashlib
import math
import re
from pathlib import Path


_BOUNDS = ('dis_win_min', 'dis_win_max', 'dis_froz_min', 'dis_froz_max')


def mark_windows_manual(config):
    """A deliberate edit/clear takes ownership of all energy-window settings."""
    config['windows_manual'] = True
    config.pop('window_defaults', None)


def clear_window_defaults(config):
    """Remove unchanged automatic fields, preserving GUI and saved-JSON edits."""
    values = (config.get('window_defaults') or {}).get('values', {})
    windows = config.get('windows') or {}
    if config.get('windows_manual'):
        config.pop('window_defaults', None)
        return
    if any(windows.get(key) != value for key, value in values.items()):
        mark_windows_manual(config)
        return
    for key in values:
        if key == 'fermi_energy' and 'windows.fermi_energy' in config.get('output_manual_fields', []):
            continue
        windows.pop(key, None)
    config.pop('window_defaults', None)


def _number(value):
    try:
        result = float(str(value).replace('D', 'e').replace('d', 'e'))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _occupation_reference(config, record):
    windows = config.get('windows') or {}
    for value in (windows.get('fermi_energy', windows.get('reference_energy')),
                  (config.get('parameters') or {}).get('fermi_energy'),
                  record.get('fermi_energy')):
        if _number(value) is not None:
            return _number(value)
    gap = record.get('gap_reference') or {}
    if gap.get('method') == 'sampled_midgap':
        return _number(gap.get('value_eV'))
    return None


def _spectrum(config, record):
    """Return per-channel rows only when the current NSCF has the full mesh."""
    from .wannier_inputs import parse_qe
    from .wannier_outputs import (_band_blocks, _kind, _klist,
                                  _nscf_input_matches_output, _points_match)
    stage = (config.get('qe_progress') or {}).get('nscf') or {}
    if (record.get('kind') != 'nscf' or not stage.get('completed')
            or not stage.get('reusable') or not stage.get('input')
            or config.get('nbnd') != stage.get('nbnd')
            or config.get('grid') != stage.get('grid')):
        return None
    try:
        payload = Path(record['path']).read_bytes()
        if hashlib.sha256(payload).hexdigest() != record.get('sha256'):
            return None
        text = payload.decode('utf-8')
        source_bytes = Path(stage['input']).read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != stage.get('sha256'):
            return None
        qe = parse_qe(source_bytes.decode('utf-8'))
        if not _nscf_input_matches_output(text, qe):
            return None
        kind, final = _kind(text, qe)
        if kind != 'nscf':
            return None
        blocks = _band_blocks(final, config['nbnd'])
        count = math.prod(stage['grid'])
        channels = ('up', 'down') if qe.spin_mode == 'collinear' else (None,)
        if len(blocks) != count * len(channels):
            return None
        # A full printed k list alone is not proof that every final energy
        # block is present. Match their actual Cartesian coordinates as well.
        marker = re.search(r'number of k points\s*=\s*\d+', text, re.I)
        points = _klist(text[marker.end():], r'cart\. coord\. in units 2\s*pi/alat', len(blocks))
        if points is None or any(point is None for point, _ in blocks):
            return None
        for index in range(len(channels)):
            start, stop = index * count, (index + 1) * count
            if not _points_match([point for point, _ in blocks[start:stop]], points[start:stop], .0002):
                return None
        rows = [values for _, values in blocks]
        if any(any(not math.isfinite(x) for x in row)
               or any(a > b for a, b in zip(row, row[1:])) for row in rows):
            return None
        return [(channel, rows[index * count:(index + 1) * count])
                for index, channel in enumerate(channels)]
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        return None


def initialize_window_defaults(config):
    """Fill trial values if data allow it; never replace a deliberate choice."""
    if config.get('mode') == 'existing':
        return
    clear_window_defaults(config)
    if config.get('windows_manual') or config.get('source_output_mode') == 'off':
        return
    windows = config.get('windows') or {}
    if any(windows.get(key) is not None for key in _BOUNDS):
        return
    record = config.get('qe_output') or {}
    if not record:
        return
    reference = _occupation_reference(config, record)
    values = {}
    adjustment_note = None
    if ('fermi_energy' not in windows and 'reference_energy' not in windows and reference is not None
            and 'windows.fermi_energy' not in config.get('output_manual_fields', [])):
        values['fermi_energy'] = reference
    if 'reference' not in windows:
        values['reference'] = 'absolute'
    offset = reference if windows.get('reference') == 'fermi' else 0.
    spectrum = _spectrum(config, record)
    retained = []
    from .wannier_inputs import _indices, _integer
    try:
        for channel, rows in spectrum or []:
            model = {**config, **((config.get('channels') or {}).get(channel, {}) if channel else {})}
            if channel and (config.get('channels') or {}).get(channel, {}).get('windows'):
                continue
            excluded = _indices(model.get('exclude_bands'), config['nbnd'], 'exclude_bands')
            dimension = _integer(model.get('num_wann'), 'num_wann')
            if dimension > config['nbnd'] - len(excluded):
                # Normal input validation explains invalid model dimensions.
                continue
            retained.extend((dimension, [e for i, e in enumerate(row, 1) if i not in excluded])
                            for row in rows)
    except (ValueError, TypeError):
        retained = []
    if any(dimension < len(row) for dimension, row in retained) and offset is not None:
        lower = math.floor((min(min(row) for _, row in retained) - .001) * 10) / 10
        upper = math.ceil((max(max(row) for _, row in retained) + .001) * 10) / 10
        values.update(dis_win_min=lower-offset, dis_win_max=upper-offset)
        if reference is not None:
            requested_lower, requested_upper = reference - 5., reference + 10.
            frozen_lower = max(requested_lower, lower)
            frozen_upper = min(requested_upper, upper)
            for dimension, row in retained:
                # Deep states below the lower bound do not consume frozen
                # subspace capacity. Count retained states inside this range.
                above_lower = [energy for energy in row if energy >= frozen_lower]
                if len(above_lower) > dimension:
                    frozen_upper = min(frozen_upper, above_lower[dimension] - .001)
            if (frozen_upper > frozen_lower and
                    any(any(frozen_lower <= energy <= frozen_upper for energy in row)
                        for _, row in retained)):
                values.update(dis_froz_min=frozen_lower-offset, dis_froz_max=frozen_upper-offset)
                if frozen_lower != requested_lower or frozen_upper != requested_upper:
                    adjustment_note = '冻结窗初值已按可用能带和 num_wann 收窄（目标：参考能 −5～+10 eV）。'
            else:
                adjustment_note = '冻结窗初值未设置：目标范围内无可用能带或超出 num_wann；请调整能窗或轨道数。'
    if values:
        config.setdefault('windows', {}).update(values)
        config['window_defaults'] = dict(values=values, source=record['path'], sha256=record['sha256'])
        if adjustment_note:
            config['window_defaults']['adjustment_note'] = adjustment_note
