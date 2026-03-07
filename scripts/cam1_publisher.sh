#!/bin/sh
set -eu

DEVICE="${CAM1_DEVICE:-/dev/video0}"
FPS="${CAM1_FPS:-25}"
RES="${CAM1_RES:-1920x1080}"
THREAD_QUEUE="${CAM1_THREAD_QUEUE:-256}"
PRESET="${CAM1_X264_PRESET:-veryfast}"
CRF="${CAM1_CRF:-18}"
GOP="${CAM1_GOP:-25}"
RTSP_URL="${CAM1_RTSP_URL:-rtsp://mediamtx:8554/cam1}"

echo "cam1 publisher start device=${DEVICE} res=${RES} fps=${FPS} gop=${GOP} crf=${CRF}"

while true; do
  if [ ! -e "${DEVICE}" ]; then
    echo "cam1 device missing: ${DEVICE}. waiting..."
    sleep 1
    continue
  fi

  ffmpeg -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay -use_wallclock_as_timestamps 1 \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format mjpeg -framerate "${FPS}" -video_size "${RES}" \
    -i "${DEVICE}" \
    -an \
    -c:v libx264 -preset "${PRESET}" -crf "${CRF}" -tune zerolatency \
    -bf 0 -pix_fmt yuv420p \
    -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 \
    -flush_packets 1 -max_delay 0 -muxdelay 0.0 -muxpreload 0.0 \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}" || true

  echo "cam1 ffmpeg restarted in 1s"
  sleep 1
done

