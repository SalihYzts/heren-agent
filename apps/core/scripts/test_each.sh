#!/usr/bin/env bash
# Run each test in a file separately with a timeout; report which hang.
cd "$(dirname "$0")/.." || exit 1
FILE=${1:-tests/test_app_ui.py}
for t in $(LC_ALL=C grep -oE '^(async )?def test_[A-Za-z_0-9]+' "$FILE" | awk '{print $NF}'); do
  printf "%-60s " "$t"
  timeout 10 ../../.venv/bin/pytest "$FILE::$t" -q -p no:cacheprovider > /tmp/nero-t1.out 2>&1
  rc=$?
  echo "rc=$rc $(grep -E 'passed|failed' /tmp/nero-t1.out | tail -1)"
done
