#!/usr/bin/env bash
# Internal compatibility adapter; all generation stays in the Python workflow.
qbox_wannier_menu() {
    local status=0
    if [ -n "${fname1:-}" ]; then
        qbox_python -m qbox.io.wannier_menu --from-main-menu "$fname1" || status=$?
    else
        qbox_python -m qbox.io.wannier_menu --from-main-menu || status=$?
    fi
    # Python returns 10 only for explicit menu navigation, 0 after generation.
    if [ "$status" = 10 ]; then
        if [ -z "${QE_DIRECT_ACTION:-}" ]; then
            qe_request_main_menu
        fi
        return 0
    fi
    return "$status"
}
