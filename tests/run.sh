#!/usr/bin/env bash
set -uo pipefail

tests_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$tests_dir/test_helper.sh"
status=0
for test_file in "$tests_dir"/cases/test_*.sh; do
    printf '\n==> %s\n' "${test_file##*/}"
    bash "$test_file" || status=1
done
printf '\n==> Python module tests\n'
PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$QBOX_PYTHON" -m unittest discover -s "$tests_dir/python" -v || status=1
exit "$status"
