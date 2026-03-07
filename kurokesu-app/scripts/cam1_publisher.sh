#!/bin/sh
set -eu

DEVICE="${CAM1_DEVICE:-/dev/v4l/by-id/usb-Kurokesu_C3_4K_00001-video-index0}"
MODE="${CAM1_MODE:-auto}"
FPS="${CAM1_FPS:-25}"
RES="${CAM1_RES:-1920x1080}"
THREAD_QUEUE="${CAM1_THREAD_QUEUE:-64}"
PRESET="${CAM1_X264_PRESET:-veryfast}"
TUNE="${CAM1_X264_TUNE:-zerolatency}"
PROFILE="${CAM1_X264_PROFILE:-high}"
CRF="${CAM1_CRF:-12}"
GOP="${CAM1_GOP:-15}"
RTSP_URL="${CAM1_RTSP_URL:-rtsp://mediamtx:8554/cam1}"
BITRATE="${CAM1_BITRATE:-25M}"
BUFSIZE="${CAM1_BUFSIZE:-50M}"
RTBUF_SIZE="${CAM1_RTBUF_SIZE:-128M}"
X264_PARAMS="${CAM1_X264_PARAMS:-bframes=0:scenecut=0}"

encoder_args() {
  args="
    -an
    -vf format=yuv420p
    -c:v libx264 -preset ${PRESET} -crf ${CRF} -tune ${TUNE}
    -profile:v ${PROFILE}
    -bf 0 -pix_fmt yuv420p
    -x264-params ${X264_PARAMS}
    -g ${GOP} -keyint_min ${GOP} -sc_threshold 0
  "
  if [ -n "${BITRATE}" ]; then
    args="${args} -b:v ${BITRATE} -maxrate ${BITRATE}"
  fi
  if [ -n "${BUFSIZE}" ]; then
    args="${args} -bufsize ${BUFSIZE}"
  fi
  # shellcheck disable=SC2086
  set -- ${args}
  printf '%s\n' "$@"
}

run_mjpeg() {
  dev="$1"
  ENCODER_ARGS="$(encoder_args)"
  ffmpeg -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay \
    -rtbufsize "${RTBUF_SIZE}" \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format mjpeg -framerate "${FPS}" -video_size "${RES}" \
    -i "${dev}" \
    ${ENCODER_ARGS} \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

run_yuyv() {
  dev="$1"
  ENCODER_ARGS="$(encoder_args)"
  ffmpeg -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay \
    -rtbufsize "${RTBUF_SIZE}" \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format yuyv422 -framerate "${FPS}" -video_size "${RES}" \
    -i "${dev}" \
    ${ENCODER_ARGS} \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

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

echo "cam1 publisher start device=${DEVICE} mode=${MODE} res=${RES} fps=${FPS} gop=${GOP} crf=${CRF} bitrate=${BITRATE:-crf-only} bufsize=${BUFSIZE:-none} preset=${PRESET} profile=${PROFILE}"

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

  sleep 0.2

  if [ "${MODE}" = "mjpeg" ]; then
    run_mjpeg "${ACTIVE_DEVICE}" || true
  elif [ "${MODE}" = "yuyv" ]; then
    run_yuyv "${ACTIVE_DEVICE}" || true
  else
    run_yuyv "${ACTIVE_DEVICE}" || run_mjpeg "${ACTIVE_DEVICE}" || true
  fi

  echo "cam1 ffmpeg restarted in 1s"
  sleep 1
done
