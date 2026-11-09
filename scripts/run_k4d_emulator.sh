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

# Headless emulators can ANR the launcher while the model loads; the modal
# "isn't responding" dialog steals window focus (so the IME never shows) and
# covers every screenshot. Suppress system error dialogs from the first moment.
adb shell settings put global hide_error_dialogs 1 || true
adb shell settings put global show_first_crash_dialog 0 || true
adb shell settings put secure anr_show_background 0 || true

BOOT_DEADLINE=$(( $(date +%s) + 900 ))
until [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do
  if [ "$(date +%s)" -ge "$BOOT_DEADLINE" ]; then
    echo "ERROR: emulator did not report sys.boot_completed=1 within 900s" >&2
    exit 1
  fi
  sleep 2
done

BOOT_OBSERVED=$(date +%s)
# Re-apply the dialog suppression now that the settings provider is up.
adb shell settings put global hide_error_dialogs 1 || true
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

K5B_DIR=build/reports/k5b
APP_ID=com.medai.assistant
DEVICE_FILES=/sdcard/Android/data/$APP_ID/files
mkdir -p "$K5B_DIR"

# Copy an internal app directory (files/<name>) into a host directory.
# API 34 hides /sdcard/Android/data from the adb shell user, so stream a tar
# through `run-as` (the debug build is debuggable) instead of using adb pull.
pull_internal_dir() {
  local name="$1"
  local dest="$2"
  local staging="${dest}.staging"
  rm -rf "$staging" "$dest"
  mkdir -p "$staging" "$dest"
  if adb exec-out run-as "$APP_ID" tar -C files -cf - "$name" \
      > "$staging/pull.tar" 2>/dev/null && [ -s "$staging/pull.tar" ]; then
    tar -xf "$staging/pull.tar" -C "$staging" 2>/dev/null || true
    if [ -d "$staging/$name" ]; then
      cp -a "$staging/$name/." "$dest/" 2>/dev/null || true
    fi
    echo "pulled_internal_dir=$name bytes=$(stat -c%s "$staging/pull.tar")"
  else
    # Fallback for an app that wrote to external storage instead.
    local remote="$DEVICE_FILES/$name"
    if adb shell "ls '$remote'" >/dev/null 2>&1; then
      adb pull "$remote" "$staging" >/dev/null 2>&1 || true
      if [ -d "$staging/$name" ]; then
        cp -a "$staging/$name/." "$dest/" 2>/dev/null || true
      fi
    else
      echo "WARNING: device directory missing: files/$name (and $remote)" >&2
    fi
  fi
  rm -rf "$staging"
}

# AVDs expose a hardware keyboard, which suppresses the soft IME. K5b case 10
# asserts that the input sits above a real IME inset, so force the IME on and
# restart Gboard so it re-reads the setting instead of a cached value from boot.
IME_ID=com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME
adb shell settings put secure show_ime_with_hard_keyboard 1 || true
adb shell settings put secure default_input_method "$IME_ID" || true
adb shell am force-stop com.google.android.inputmethod.latin || true
adb shell ime disable "$IME_ID" || true
adb shell ime enable "$IME_ID" || true
# The emulator is a Pixel profile, whose screen timeout is short; synthetic
# instrumentation touches do not reset it, so the display can sleep mid-suite
# (no focused window, no IME). Keep it on for the whole run.
adb shell settings put system screen_off_timeout 2147483647 || true
adb shell svc power stayon true || true
# `ime set` after a force-stop can leave Gboard in the stopped state; retry
# until its process really exists so the first showSoftInput() does not race a
# failed service start.
IME_PID=""
for _ in $(seq 1 30); do
  adb shell ime set "$IME_ID" >/dev/null 2>&1 || true
  # toybox `pidof` exits 1 when no process matches; with `set -o pipefail`
  # that would abort the whole script on the first retry, so swallow it.
  IME_PID=$(adb shell pidof com.google.android.inputmethod.latin 2>/dev/null | tr -d '\r' || true)
  # A bare `[ ... ] && break` returns 1 on the first empty pid and, with
  # `set -e`, aborts this script before the emulator tests even start.
  if [ -n "$IME_PID" ]; then
    break
  fi
  sleep 1
done
if [ -z "$IME_PID" ]; then
  # Last resort: launch Gboard's own activity to create the process, then
  # return to the home screen.
  adb shell monkey -p com.google.android.inputmethod.latin \
    -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
  sleep 3
  adb shell input keyevent KEYCODE_HOME || true
  IME_PID=$(adb shell pidof com.google.android.inputmethod.latin 2>/dev/null | tr -d '\r' || true)
fi
# Let the IME process come back and read show_ime_with_hard_keyboard before the
# first field is focused; otherwise the first showSoftInput() can race startup.
sleep 5
adb shell wm dismiss-keyguard || true
adb shell input keyevent KEYCODE_WAKEUP || true
# The launcher is not needed by the instrumented tests. Stop it so a late ANR
# cannot put a system dialog back on top of the app.
adb shell am force-stop com.google.android.apps.nexuslauncher || true
adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS || true
{
  echo "ime_pid=${IME_PID:-none}"
  echo "screen_off_timeout=$(adb shell settings get system screen_off_timeout | tr -d '\r')"
  echo "imes=$(adb shell ime list -s | tr -d '\r' | tr '\n' ' ')"
  echo "default_input_method=$(adb shell settings get secure default_input_method | tr -d '\r')"
  echo "show_ime_with_hard_keyboard=$(adb shell settings get secure show_ime_with_hard_keyboard | tr -d '\r')"
  echo "current_ime=$(adb shell dumpsys input_method 2>/dev/null | grep -m1 'mCurMethodId' | tr -d '\r' || true)"
} | tee -a "$REPORT_DIR/device_info.txt"

TEST_START=$(date +%s)
set +e
# Keep the debug APKs installed after the run: AGP otherwise uninstalls them,
# which deletes the app's internal files before the artifact pull below.
./gradlew connectedDebugAndroidTest --no-daemon --stacktrace \
  -Pandroid.injected.androidTest.leaveApksInstalledAfterRun=true
TEST_STATUS=$?
set -e
TEST_END=$(date +%s)
echo "connected_test_seconds=$((TEST_END - TEST_START))" | tee -a "$REPORT_DIR/device_info.txt"
echo "connected_test_exit_code=$TEST_STATUS" | tee -a "$REPORT_DIR/device_info.txt"

# Pull K5b-A/B reports and K5b-C screenshots even when a test failed: the
# report explains the failure and the screenshots still prove what rendered.
pull_internal_dir reports "$K5B_DIR"
pull_internal_dir ui-screenshots "$K5B_DIR/ui-screenshots"
pull_internal_dir ui-screenshots-v3 "build/reports/k5d/ui-screenshots-v3"
pull_internal_dir design-gallery "build/reports/design-gallery"
if [ -d "build/reports/design-gallery" ]; then
  cp -a build/reports/design-gallery/*.png "$K5B_DIR/ui-screenshots/" 2>/dev/null || true
fi

{
  echo "pulled_k5b_report_files=$(find "$K5B_DIR" -maxdepth 1 -type f | wc -l)"
  echo "pulled_screenshots=$(find "$K5B_DIR/ui-screenshots" -type f -name '*.png' 2>/dev/null | wc -l)"
  echo "pulled_screenshot_bytes=$(du -sb "$K5B_DIR/ui-screenshots" 2>/dev/null | awk '{print $1}')"
  echo "pulled_gallery_screenshots=$(find build/reports/design-gallery -type f -name '*.png' 2>/dev/null | wc -l)"
  echo "pulled_gallery_bytes=$(du -sb build/reports/design-gallery 2>/dev/null | awk '{print $1}')"
} | tee -a "$REPORT_DIR/device_info.txt"

exit "$TEST_STATUS"
