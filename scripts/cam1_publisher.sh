#!/bin/sh
set -eu

DEVICE="${CAM1_DEVICE:-/dev/v4l/by-id/usb-Kurokesu_C3_4K_00001-video-index0}"
MODE="${CAM1_MODE:-mjpeg}"
FPS="${CAM1_FPS:-25}"
RES="${CAM1_RES:-1920x1080}"
THREAD_QUEUE="${CAM1_THREAD_QUEUE:-64}"
PRESET="${CAM1_X264_PRESET:-superfast}"
CRF="${CAM1_CRF:-14}"
GOP="${CAM1_GOP:-15}"
RTSP_URL="${CAM1_RTSP_URL:-rtsp://mediamtx:8554/cam1}"
BITRATE="${CAM1_BITRATE:-10M}"
BUFSIZE="${CAM1_BUFSIZE:-512k}"
X264_PARAMS="${CAM1_X264_PARAMS:-bframes=0:rc-lookahead=0:sync-lookahead=0:scenecut=0}"

run_mjpeg() {
  dev="$1"
  ffmpeg -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format mjpeg -framerate "${FPS}" -video_size "${RES}" \
    -i "${dev}" \
    -an \
    -vf "format=yuv420p" \
    -c:v libx264 -preset "${PRESET}" -crf "${CRF}" -tune zerolatency \
    -bf 0 -pix_fmt yuv420p -b:v "${BITRATE}" -maxrate "${BITRATE}" -bufsize "${BUFSIZE}" \
    -x264-params "${X264_PARAMS}" \
    -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

run_yuyv() {
  dev="$1"
  ffmpeg -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format yuyv422 -framerate "${FPS}" -video_size "${RES}" \
    -i "${dev}" \
    -an \
    -vf "format=yuv420p" \
    -c:v libx264 -preset "${PRESET}" -crf "${CRF}" -tune zerolatency \
    -bf 0 -pix_fmt yuv420p -b:v "${BITRATE}" -maxrate "${BITRATE}" -bufsize "${BUFSIZE}" \
    -x264-params "${X264_PARAMS}" \
    -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

echo "cam1 publisher start device=${DEVICE} mode=${MODE} res=${RES} fps=${FPS} gop=${GOP} crf=${CRF}"

resolve_device() {
  if [ -e "${DEVICE}" ]; then
    echo "${DEVICE}"
    return 0
  fi

  for p in \
    /dev/v4l/by-id/usb-Kurokesu_C3_4K_*-video-index0 \
    /dev/v4l/by-id/*Kurokesu*C3*video-index0 \
    /dev/v4l/by-id/*Kurokesu*video-index0
  do
    if [ -e "$p" ]; then
      echo "$p"
      return 0
    fi
  done

  echo ""
  return 0
}

while true; do
  ACTIVE_DEVICE="$(resolve_device)"
  if [ -z "${ACTIVE_DEVICE}" ]; then
    echo "cam1 device missing: wanted=${DEVICE}. waiting..."
    sleep 1
    continue
  fi
  if [ "${ACTIVE_DEVICE}" != "${DEVICE}" ]; then
    echo "cam1 device fallback selected: ${ACTIVE_DEVICE} (wanted ${DEVICE})"
  fi

  # Let kernel settle right after re-enumeration.
  sleep 0.2

  if [ "${MODE}" = "mjpeg" ]; then
    echo "cam1 run: mjpeg"
    run_mjpeg "${ACTIVE_DEVICE}" || true
  elif [ "${MODE}" = "yuyv" ]; then
    echo "cam1 run: yuyv"
    run_yuyv "${ACTIVE_DEVICE}" || true
  else
    echo "cam1 run: auto(mjpeg->yuyv)"
    run_mjpeg "${ACTIVE_DEVICE}" || run_yuyv "${ACTIVE_DEVICE}" || true
  fi

  echo "cam1 ffmpeg restarted in 1s"
  sleep 1
done
