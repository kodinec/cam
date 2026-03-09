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
    echo "cam2 device missing: wanted=${DEVICE}. waiting..."
    sleep 1
    continue
  fi
  if [ "${ACTIVE_DEVICE}" != "${DEVICE}" ]; then
    echo "cam2 device fallback selected: ${ACTIVE_DEVICE} (wanted ${DEVICE})"
  fi

  sleep 0.4
  run_stream "${ACTIVE_DEVICE}" || true
  echo "cam2 ffmpeg restarted in 1s"
  sleep 1
done
