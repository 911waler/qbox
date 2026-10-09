"""Shared settings for the reviewed Wannier90 3.1.0 shift-current template.

Material energies and orbital dimensions are deliberately not defaults.
This module is used by both the menu and the file renderer.
"""

MODEL_DEFAULTS = dict(num_iter=1000, conv_tol=1e-10, conv_window=5,
                      dis_num_iter=1200, dis_mix_ratio=.5,
                      dis_conv_tol=1e-10, dis_conv_window=3)
MODEL_KEYS = tuple(MODEL_DEFAULTS)
RESPONSE_ENERGIES = ('fermi_energy', 'kubo_freq_max', 'kubo_eigval_max')


def model_settings(config):
    """Return effective settings without mutating manual or existing models."""
    values = {key: config[key] for key in MODEL_KEYS if config.get(key) is not None}
    if config.get('mode', 'new') != 'new' or 'shift_current' not in config.get('tasks', []):
        return values
    # Source initialisation predates task selection and fills the generic 1000.
    # Only this recorded automatic value may be replaced by the SC template.
    if (values.get('dis_num_iter') == 1000
            and 'dis_num_iter' in config.get('basis_defaults', {})
            and 'dis_num_iter' not in config.get('basis_manual_fields', [])):
        values.pop('dis_num_iter')
    return {**MODEL_DEFAULTS, **values}


def pending_response_parameters(config):
    """Missing postw90-only data may be supplied after a new SC model exists."""
    if config.get('mode', 'new') != 'new' or 'shift_current' not in config.get('tasks', []):
        return []
    from .wannier_output_defaults import can_defer_fermi
    parameters = config.get('parameters') or {}
    return [key for key in RESPONSE_ENERGIES if parameters.get(key) is None
            and (key != 'fermi_energy' or can_defer_fermi(config))]
