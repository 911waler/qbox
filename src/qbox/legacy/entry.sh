#!/usr/bin/env bash
# Executed (not sourced) by the Python CLI so signals and status stay native.
source "$(dirname "${BASH_SOURCE[0]}")/load.sh" || exit 1
if [ "$QBOX_TEST_MODE" != 1 ]; then
    qe_main "$@"
fi
