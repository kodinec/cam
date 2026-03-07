#!/bin/sh
set -eu

DEVICE="${CAM2_DEVICE:-/dev/v4l/by-id/usb-rockchip_UVC_2020-video-index0}"
DEVICE_FALLBACK="${CAM2_DEVICE_FALLBACK:-/dev/video2}"
RES="${CAM2_RES:-1024x768}"
FPS="${CAM2_FPS:-15}"
GOP="${CAM2_GOP:-15}"
THREAD_QUEUE="${CAM2_THREAD_QUEUE:-64}"
PRESET="${CAM2_X264_PRESET:-ultrafast}"
CRF="${CAM2_CRF:-24}"
BITRATE="${CAM2_BITRATE:-4M}"
BUFSIZE="${CAM2_BUFSIZE:-512k}"
ANALYZE="${CAM2_ANALYZE_DURATION:-5M}"
PROBE="${CAM2_PROBE_SIZE:-5M}"
RTSP_URL="${CAM2_RTSP_URL:-rtsp://mediamtx:8554/cam2}"

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
    -analyzeduration "${ANALYZE}" -probesize "${PROBE}" \
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

echo "cam2 publisher start device=${DEVICE} res=${RES} fps=${FPS}"
while true; do
  resolved_device="$(resolve_device || true)"
  if [ -z "${resolved_device}" ]; then
    echo "cam2 device missing: preferred=${DEVICE} fallback=${DEVICE_FALLBACK}. waiting..."
    sleep 1
    continue
  fi

  run_once "${resolved_device}" || true
  echo "cam2 ffmpeg restarted in 1s"
  sleep 1
done
