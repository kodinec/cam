#!/bin/sh
set -eu

DEVICE="${CAM1_DEVICE:-/dev/v4l/by-id/usb-Kurokesu_C3_4K_00001-video-index0}"
DEVICE_FALLBACK="${CAM1_DEVICE_FALLBACK:-/dev/video0}"
RES="${CAM1_RES:-1920x1080}"
FPS="${CAM1_FPS:-25}"
GOP="${CAM1_GOP:-15}"
THREAD_QUEUE="${CAM1_THREAD_QUEUE:-64}"
PRESET="${CAM1_X264_PRESET:-superfast}"
CRF="${CAM1_CRF:-14}"
BITRATE="${CAM1_BITRATE:-10M}"
BUFSIZE="${CAM1_BUFSIZE:-512k}"
RTSP_URL="${CAM1_RTSP_URL:-rtsp://mediamtx:8554/cam1}"

resolve_device() {
  if [ -e "${DEVICE}" ]; then
    echo "${DEVICE}"
    return 0
  fi
  if [ -n "${DEVICE_FALLBACK}" ] && [ -e "${DEVICE_FALLBACK}" ]; then
    echo "${DEVICE_FALLBACK}"
    return 0
  fi
  return 1
}

run_once() {
  in_dev="$1"
  ffmpeg -hide_banner -loglevel warning \
    -fflags +genpts+nobuffer+discardcorrupt -flags low_delay \
    -use_wallclock_as_timestamps 1 \
    -thread_queue_size "${THREAD_QUEUE}" \
    -rtbufsize 128M \
    -f v4l2 -input_format mjpeg -framerate "${FPS}" -video_size "${RES}" \
    -i "${in_dev}" \
    -an -vf "format=yuv420p" \
    -c:v libx264 -preset "${PRESET}" -crf "${CRF}" -tune zerolatency \
    -pix_fmt yuv420p \
    -x264-params "bframes=0:rc-lookahead=0:sync-lookahead=0:scenecut=0" \
    -b:v "${BITRATE}" -maxrate "${BITRATE}" -bufsize "${BUFSIZE}" \
    -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 \
    -fps_mode vfr -muxdelay 0.05 -muxpreload 0 -pkt_size 1200 \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

echo "cam1 publisher start device=${DEVICE} res=${RES} fps=${FPS}"
while true; do
  resolved_device="$(resolve_device || true)"
  if [ -z "${resolved_device}" ]; then
    echo "cam1 device missing: preferred=${DEVICE} fallback=${DEVICE_FALLBACK}. waiting..."
    sleep 1
    continue
  fi

  run_once "${resolved_device}" || true
  echo "cam1 ffmpeg restarted in 1s"
  sleep 1
done
