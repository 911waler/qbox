#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

qbox_print_version() {
    qbox_python -m qbox --version
}

qbox_print_help() {
    qbox_python -m qbox --help
}
