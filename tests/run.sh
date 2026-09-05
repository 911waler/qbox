#!/usr/bin/env bash
set -uo pipefail

tests_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
status=0
for test_file in "$tests_dir"/cases/test_*.sh; do
    printf '\n==> %s\n' "${test_file##*/}"
    bash "$test_file" || status=1
done
exit "$status"
