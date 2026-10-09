"""Editable response limits derived from the frozen energy window."""
import math


_KEYS = ('kubo_freq_max', 'kubo_eigval_max')


def _finite(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace('D', 'e').replace('d', 'e'))
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _absolute_upper(windows):
    """Read the upper bound without imposing new-model rules on existing wins."""
    upper = _finite(windows.get('dis_froz_max'))
    reference = windows.get('reference', 'absolute')
    if upper is None or reference not in ('absolute', 'qe', 'fermi'):
        return None
    if reference == 'fermi':
        offset = _finite(windows.get('fermi_energy', windows.get('reference_energy')))
        if offset is None:
            return None
        upper += offset
    return upper if math.isfinite(upper) else None


def refresh_response_defaults(config):
    """Refresh untouched defaults; preserve manual values and deliberate clears.

    Photon energies are differences, unlike the absolute eigenvalue cutoff.
    Only the photon limit requires the occupation reference. The eigenvalue
    cutoff uses the absolute frozen upper bound, including negative energies.
    Window coordinates may use a different reference from occupations.
    """
    parameters = config.setdefault('parameters', {})
    defaults = config.get('response_parameter_defaults', {})
    automatic = set()
    for key in _KEYS:
        previous = defaults.get(key)
        if key in config.get('output_manual_fields', []):
            defaults.pop(key, None)
            continue
        if previous is not None:
            if isinstance(parameters.get(key), bool) or parameters.get(key) != previous['value']:
                # Saved JSON edits/deletions have the same precedence as
                # deliberate edits in the parameter menu.
                from .wannier_output_defaults import mark_manual
                mark_manual(config, key)
                continue
            parameters.pop(key, None)
            defaults.pop(key, None)
        elif parameters.get(key) is not None:
            continue
        automatic.add(key)

    tasks = set(config.get('tasks') or [])
    if not automatic or not tasks.intersection({'optical', 'shift_current', 'shc'}):
        return
    windows = config.get('windows') or {}
    models = [windows]
    if config.get('spin_mode') == 'collinear':
        channels = config.get('channels') or {}
        models = [(channels.get(channel) or {}).get('windows', windows)
                  for channel in ('up', 'down')]
    upper_bounds = [_absolute_upper(model or {}) for model in models]
    if any(upper is None for upper in upper_bounds):
        return
    upper = upper_bounds[0]
    if any(not math.isclose(upper, bound, rel_tol=1e-12, abs_tol=1e-10)
           for bound in upper_bounds[1:]):
        return

    if 'kubo_eigval_max' in automatic:
        parameters['kubo_eigval_max'] = upper
        config.setdefault('response_parameter_defaults', {})['kubo_eigval_max'] = {
            'value': upper, 'dis_froz_max_absolute': upper}

    if ('kubo_freq_max' not in automatic or
            (tasks.isdisjoint({'optical', 'shift_current'}) and
             not parameters.get('shc_freq_scan', False))):
        return
    reference = _finite(parameters.get('fermi_energy'))
    minimum = _finite(parameters.get('kubo_freq_min', 0.))
    if reference is None or minimum is None:
        return
    value = round(upper - reference, 12)
    if not math.isfinite(value) or value <= max(0., minimum):
        return
    parameters['kubo_freq_max'] = value
    config.setdefault('response_parameter_defaults', {})['kubo_freq_max'] = {
        'value': value, 'dis_froz_max_absolute': upper, 'fermi_energy': reference}
