#!/usr/bin/env bash
# Stage K4d: emulator boot capture + on-device androidTest run.
#
# The android-emulator-runner action executes each line of its `script:`
# input separately through `/usr/bin/sh -c`, so multi-line shell compound
# commands (until/do/done, { ... } | tee) cannot be written inline.
# Keeping the whole sequence in one bash script makes the action call a
# single command and preserves normal shell syntax.
set -euo pipefail

REPORT_DIR=build/reports/k4d
mkdir -p "$REPORT_DIR"

adb wait-for-device

BOOT_DEADLINE=$(( $(date +%s) + 900 ))
until [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do
  if [ "$(date +%s)" -ge "$BOOT_DEADLINE" ]; then
    echo "ERROR: emulator did not report sys.boot_completed=1 within 900s" >&2
    exit 1
  fi
  sleep 2
done

BOOT_OBSERVED=$(date +%s)
{
  echo "boot_completed_at_epoch=$BOOT_OBSERVED"
  echo "emulator_boot_seconds=$((BOOT_OBSERVED - ${K4D_EMULATOR_START:-$BOOT_OBSERVED}))"
  echo "model=$(adb shell getprop ro.product.model | tr -d '\r')"
  echo "device=$(adb shell getprop ro.product.device | tr -d '\r')"
  echo "api=$(adb shell getprop ro.build.version.sdk | tr -d '\r')"
  echo "release=$(adb shell getprop ro.build.version.release | tr -d '\r')"
  echo "abi=$(adb shell getprop ro.product.cpu.abi | tr -d '\r')"
  echo "abilist=$(adb shell getprop ro.product.cpu.abilist | tr -d '\r')"
} | tee "$REPORT_DIR/device_info.txt"

adb shell df -h /data | tee -a "$REPORT_DIR/device_info.txt"
free -h | tee -a "$REPORT_DIR/device_info.txt"
df -h . | tee -a "$REPORT_DIR/device_info.txt"

TEST_START=$(date +%s)
./gradlew connectedDebugAndroidTest --no-daemon --stacktrace
TEST_END=$(date +%s)
echo "connected_test_seconds=$((TEST_END - TEST_START))" | tee -a "$REPORT_DIR/device_info.txt"
