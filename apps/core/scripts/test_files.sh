#!/usr/bin/env bash
# Run each test file separately with a timeout; report which one hangs.
cd "$(dirname "$0")/.." || exit 1
for f in tests/test_*.py; do
  printf "%-34s " "$f"
  timeout 30 ../../.venv/bin/pytest "$f" -q -p no:cacheprovider > /tmp/heren-t1.out 2>&1
  rc=$?
  echo "rc=$rc $(grep -oE '[0-9]+ (passed|failed)' /tmp/heren-t1.out | tr '\n' ' ')"
done
