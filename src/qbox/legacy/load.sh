#!/usr/bin/env bash
# One compatibility boundary while workflows are migrated domain by domain.
QBOX_PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export QBOX_PACKAGE_DIR
if [ -z "${_QBOX_OFFLINE_ROOT:-}" ]; then
    export PYTHONPATH="$(dirname "$QBOX_PACKAGE_DIR")${PYTHONPATH:+:$PYTHONPATH}"
fi

# Order is explicit: bootstrap sets the environment; modules define functions
# and the historical shared state. Do not execute a workflow while sourcing.
for _qbox_module in bootstrap dispatch state band_io pw_settings input_pw \
    input_md input_phonon input_postprocess structure plot_common \
    electronic_inputs pdos_data runner band_edges effective_mass environment \
    electronic_workflows pdos ldos optics convergence nscf unfold menu cluster help; do
    source "$QBOX_PACKAGE_DIR/legacy/$_qbox_module.sh" || return 1
done
unset _qbox_module
