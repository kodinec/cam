#!/bin/sh
set -eu

DEVICE="${CAM2_DEVICE:-/dev/v4l/by-id/usb-rockchip_UVC_2020-video-index0}"
FPS="${CAM2_FPS:-15}"
RES="${CAM2_RES:-1024x768}"
PRESET="${CAM2_X264_PRESET:-veryfast}"
TUNE="${CAM2_X264_TUNE:-zerolatency}"
CRF="${CAM2_CRF:-23}"
GOP="${CAM2_GOP:-15}"
RTSP_URL="${CAM2_RTSP_URL:-rtsp://mediamtx:8554/cam2}"
HARD_RESET="${CAM2_USB_HARD_RESET:-true}"
RESET_AFTER_MISSING="${CAM2_USB_RESET_AFTER_MISSING:-20}"
RESET_OFF_SECONDS="${CAM2_USB_RESET_OFF_SECONDS:-20}"
RESET_COOLDOWN="${CAM2_USB_RESET_COOLDOWN:-60}"
RESET_WAIT_AFTER_ON="${CAM2_USB_RESET_WAIT_AFTER_ON:-5}"
RESET_LOCATION="${CAM2_USB_RESET_LOCATION:-}"
RESET_PORT="${CAM2_USB_RESET_PORT:-}"
RESET_AFTER_SHORT_FAILURES="${CAM2_USB_RESET_AFTER_SHORT_FAILURES:-3}"
SHORT_FAILURE_SECONDS="${CAM2_USB_SHORT_FAILURE_SECONDS:-5}"

CACHED_RESET_LOCATION=""
CACHED_RESET_PORT=""
LAST_RESET_TS=0
MISSING_SINCE=""
LAST_MISSING_LOG=-1
LAST_TARGET_LOG=""
SHORT_FAILURES=0

is_true() {
  case "$1" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

cache_reset_target() {
  dev="$1"

  if [ -n "${RESET_LOCATION}" ] && [ -n "${RESET_PORT}" ]; then
    CACHED_RESET_LOCATION="${RESET_LOCATION}"
    CACHED_RESET_PORT="${RESET_PORT}"
  else
    real_dev="$(readlink -f "${dev}" 2>/dev/null || true)"
    [ -n "${real_dev}" ] || return 1

    video_node="$(basename "${real_dev}")"
    sys_path="$(readlink -f "/sys/class/video4linux/${video_node}/device" 2>/dev/null || true)"
    [ -n "${sys_path}" ] || return 1

    usb_path=""
    cur="${sys_path}"
    while [ "${cur}" != "/" ]; do
      base="$(basename "${cur}")"
      case "${base}" in
        *:*)
          ;;
        [0-9]*-[0-9]*)
          usb_path="${base}"
          break
          ;;
      esac
      cur="$(dirname "${cur}")"
    done

    [ -n "${usb_path}" ] || return 1

    case "${usb_path}" in
      *.*)
        CACHED_RESET_LOCATION="${usb_path%.*}"
        CACHED_RESET_PORT="${usb_path##*.}"
        ;;
      *)
        CACHED_RESET_LOCATION="${usb_path%%-*}-0:1.0"
        CACHED_RESET_PORT="${usb_path##*-}"
        ;;
    esac
  fi

  target="${CACHED_RESET_LOCATION}:${CACHED_RESET_PORT}"
  if [ "${LAST_TARGET_LOG}" != "${target}" ]; then
    echo "cam2 hard reset target armed location=${CACHED_RESET_LOCATION} port=${CACHED_RESET_PORT}"
    LAST_TARGET_LOG="${target}"
  fi

  return 0
}

hard_reset_usb() {
  if ! is_true "${HARD_RESET}"; then
    return 1
  fi

  if ! command -v uhubctl >/dev/null 2>&1; then
    echo "cam2 hard reset skipped: uhubctl missing in container"
    return 1
  fi

  if [ -z "${CACHED_RESET_LOCATION}" ] || [ -z "${CACHED_RESET_PORT}" ]; then
    echo "cam2 hard reset skipped: target unknown"
    return 1
  fi

  echo "cam2 hard reset start location=${CACHED_RESET_LOCATION} port=${CACHED_RESET_PORT} off=${RESET_OFF_SECONDS}s"
  if ! uhubctl -l "${CACHED_RESET_LOCATION}" -p "${CACHED_RESET_PORT}" -a off; then
    echo "cam2 hard reset failed while powering off"
    return 1
  fi

  sleep "${RESET_OFF_SECONDS}"

  if ! uhubctl -l "${CACHED_RESET_LOCATION}" -p "${CACHED_RESET_PORT}" -a on; then
    echo "cam2 hard reset failed while powering on"
    return 1
  fi

  echo "cam2 hard reset done, waiting ${RESET_WAIT_AFTER_ON}s for re-enumeration"
  sleep "${RESET_WAIT_AFTER_ON}"
  return 0
}

resolve_device() {
  if [ -e "${DEVICE}" ]; then
    echo "${DEVICE}"
    return 0
  fi
  for p in \
    /dev/v4l/by-id/usb-rockchip_UVC_*-video-index0 \
    /dev/v4l/by-id/*rockchip*UVC*index0
  do
    if [ -e "$p" ]; then
      echo "$p"
      return 0
    fi
  done
  echo ""
  return 0
}

run_stream() {
  dev="$1"
  ffmpeg -hide_banner -loglevel info \
    -fflags +genpts -use_wallclock_as_timestamps 1 \
    -f v4l2 -input_format mjpeg -framerate "${FPS}" -video_size "${RES}" \
    -i "${dev}" \
    -vf "scale=in_range=pc:out_range=tv,format=yuv420p,fps=${FPS}" \
    -an \
    -c:v libx264 -preset "${PRESET}" -tune "${TUNE}" -crf "${CRF}" \
    -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

echo "cam2 publisher start device=${DEVICE} mode=mjpeg->h264 res=${RES} fps=${FPS} crf=${CRF} gop=${GOP}"

while true; do
  ACTIVE_DEVICE="$(resolve_device)"
  if [ -z "${ACTIVE_DEVICE}" ]; then
    now="$(date +%s)"
    if [ -z "${MISSING_SINCE}" ]; then
      MISSING_SINCE="${now}"
      LAST_MISSING_LOG=-1
    fi

    missing_for=$((now - MISSING_SINCE))
    since_reset=$((now - LAST_RESET_TS))

    if [ "${missing_for}" -ne "${LAST_MISSING_LOG}" ]; then
      echo "cam2 device missing: wanted=${DEVICE} missing_for=${missing_for}s waiting..."
      LAST_MISSING_LOG="${missing_for}"
    fi

    if is_true "${HARD_RESET}" && [ "${missing_for}" -ge "${RESET_AFTER_MISSING}" ] && [ "${since_reset}" -ge "${RESET_COOLDOWN}" ]; then
      if hard_reset_usb; then
        LAST_RESET_TS="$(date +%s)"
        MISSING_SINCE=""
        LAST_MISSING_LOG=-1
        continue
      fi
      LAST_RESET_TS="${now}"
    fi

    sleep 1
    continue
  fi

  MISSING_SINCE=""
  LAST_MISSING_LOG=-1

  if [ "${ACTIVE_DEVICE}" != "${DEVICE}" ]; then
    echo "cam2 device fallback selected: ${ACTIVE_DEVICE} (wanted ${DEVICE})"
  fi

  cache_reset_target "${ACTIVE_DEVICE}" || true

  stream_started="$(date +%s)"
  sleep 0.4
  run_stream "${ACTIVE_DEVICE}" || true
  stream_ended="$(date +%s)"
  stream_runtime=$((stream_ended - stream_started))

  if [ "${stream_runtime}" -lt "${SHORT_FAILURE_SECONDS}" ]; then
    SHORT_FAILURES=$((SHORT_FAILURES + 1))
    echo "cam2 short stream failure runtime=${stream_runtime}s count=${SHORT_FAILURES}"
  else
    SHORT_FAILURES=0
  fi

  if is_true "${HARD_RESET}" && [ "${SHORT_FAILURES}" -ge "${RESET_AFTER_SHORT_FAILURES}" ]; then
    now="$(date +%s)"
    since_reset=$((now - LAST_RESET_TS))
    if [ "${since_reset}" -ge "${RESET_COOLDOWN}" ]; then
      if hard_reset_usb; then
        LAST_RESET_TS="$(date +%s)"
        SHORT_FAILURES=0
        MISSING_SINCE=""
        LAST_MISSING_LOG=-1
        continue
      fi
      LAST_RESET_TS="${now}"
    fi
  fi

  echo "cam2 ffmpeg restarted in 1s"
  sleep 1
done
