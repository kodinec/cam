#!/bin/sh
set -eu

DEVICE="${CAM1_DEVICE:-/dev/v4l/by-id/usb-Kurokesu_C3_4K_00001-video-index0}"
MODE="${CAM1_MODE:-mjpeg}"
FPS="${CAM1_FPS:-25}"
RES="${CAM1_RES:-1920x1080}"
THREAD_QUEUE="${CAM1_THREAD_QUEUE:-64}"
ENCODER="${CAM1_ENCODER:-libx264}"
VAAPI_FALLBACK="${CAM1_VAAPI_FALLBACK:-true}"
VAAPI_DRIVER="${CAM1_VAAPI_DRIVER:-}"
VAAPI_RC_MODE="${CAM1_VAAPI_RC_MODE:-bitrate}"
PRESET="${CAM1_X264_PRESET:-superfast}"
TUNE="${CAM1_X264_TUNE:-zerolatency}"
PROFILE="${CAM1_X264_PROFILE:-high}"
CRF="${CAM1_CRF:-13}"
VAAPI_DEVICE="${CAM1_VAAPI_DEVICE:-/dev/dri/renderD128}"
VAAPI_QP="${CAM1_VAAPI_QP:-18}"
GOP="${CAM1_GOP:-15}"
RTSP_URL="${CAM1_RTSP_URL:-rtsp://mediamtx:8554/cam1}"
BITRATE="${CAM1_BITRATE:-10M}"
BUFSIZE="${CAM1_BUFSIZE:-20M}"
RTBUF_SIZE="${CAM1_RTBUF_SIZE:-64M}"
X264_PARAMS="${CAM1_X264_PARAMS:-bframes=0:rc-lookahead=0:sync-lookahead=0:scenecut=0}"

if [ -n "${VAAPI_DRIVER}" ]; then
  export LIBVA_DRIVER_NAME="${VAAPI_DRIVER}"
fi

cpu_video_filter() {
  input_mode="$1"
  case "${input_mode}" in
    mjpeg)
      printf '%s\n' "scale=in_range=pc:out_range=tv,format=yuv420p"
      ;;
    *)
      printf '%s\n' "scale=in_range=tv:out_range=tv,format=yuv420p"
      ;;
  esac
}

vaapi_video_filter() {
  input_mode="$1"
  case "${input_mode}" in
    mjpeg)
      printf '%s\n' "scale=in_range=pc:out_range=tv,format=nv12,hwupload"
      ;;
    *)
      printf '%s\n' "scale=in_range=tv:out_range=tv,format=nv12,hwupload"
      ;;
  esac
}

cpu_encoder_args() {
  input_mode="$1"
  FILTER="$(cpu_video_filter "${input_mode}")"
  args="
    -an
    -vf ${FILTER}
    -c:v libx264 -preset ${PRESET} -crf ${CRF} -tune ${TUNE}
    -profile:v ${PROFILE}
    -bf 0 -pix_fmt yuv420p -color_range tv
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

vaapi_encoder_args() {
  input_mode="$1"
  rc_mode="$2"
  FILTER="$(vaapi_video_filter "${input_mode}")"
  args="
    -an
    -vaapi_device ${VAAPI_DEVICE}
    -vf ${FILTER}
    -c:v h264_vaapi
    -profile:v ${PROFILE}
    -color_range tv
    -bf 0
    -g ${GOP}
  "
  case "${rc_mode}" in
    quality)
      args="${args} -rc_mode CQP -qp ${VAAPI_QP}"
      ;;
    bitrate)
      args="${args} -rc_mode CBR"
      if [ -n "${BITRATE}" ]; then
        args="${args} -b:v ${BITRATE} -maxrate ${BITRATE}"
      fi
      if [ -n "${BUFSIZE}" ]; then
        args="${args} -bufsize ${BUFSIZE}"
      fi
      ;;
    *)
      echo "cam1 invalid CAM1_VAAPI_RC_MODE=${rc_mode}; expected quality or bitrate" >&2
      return 1
      ;;
  esac
  # shellcheck disable=SC2086
  set -- ${args}
  printf '%s\n' "$@"
}

run_mjpeg_cpu() {
  dev="$1"
  ENCODER_ARGS="$(cpu_encoder_args mjpeg)"
  ffmpeg -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay \
    -rtbufsize "${RTBUF_SIZE}" \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format mjpeg -framerate "${FPS}" -video_size "${RES}" \
    -i "${dev}" \
    ${ENCODER_ARGS} \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

run_yuyv_cpu() {
  dev="$1"
  ENCODER_ARGS="$(cpu_encoder_args yuyv)"
  ffmpeg -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay \
    -rtbufsize "${RTBUF_SIZE}" \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format yuyv422 -framerate "${FPS}" -video_size "${RES}" \
    -i "${dev}" \
    ${ENCODER_ARGS} \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

run_mjpeg_vaapi() {
  dev="$1"
  rc_mode="$2"
  ENCODER_ARGS="$(vaapi_encoder_args mjpeg "${rc_mode}")"
  ffmpeg -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay \
    -rtbufsize "${RTBUF_SIZE}" \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format mjpeg -framerate "${FPS}" -video_size "${RES}" \
    -i "${dev}" \
    ${ENCODER_ARGS} \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

run_yuyv_vaapi() {
  dev="$1"
  rc_mode="$2"
  ENCODER_ARGS="$(vaapi_encoder_args yuyv "${rc_mode}")"
  ffmpeg -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay \
    -rtbufsize "${RTBUF_SIZE}" \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format yuyv422 -framerate "${FPS}" -video_size "${RES}" \
    -i "${dev}" \
    ${ENCODER_ARGS} \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

run_mjpeg() {
  dev="$1"
  case "${ENCODER}" in
    h264_vaapi)
      if ! run_mjpeg_vaapi "${dev}" "${VAAPI_RC_MODE}"; then
        if [ "${VAAPI_FALLBACK}" = "true" ] && [ "${VAAPI_RC_MODE}" = "bitrate" ]; then
          echo "cam1 vaapi bitrate mode unsupported, retry with quality qp=${VAAPI_QP}"
          if run_mjpeg_vaapi "${dev}" quality; then
            return 0
          fi
        fi
        if [ "${VAAPI_FALLBACK}" = "true" ]; then
          echo "cam1 vaapi init failed, fallback to libx264"
          run_mjpeg_cpu "${dev}"
        else
          return 1
        fi
      fi
      ;;
    *)
      run_mjpeg_cpu "${dev}"
      ;;
  esac
}

run_yuyv() {
  dev="$1"
  case "${ENCODER}" in
    h264_vaapi)
      if ! run_yuyv_vaapi "${dev}" "${VAAPI_RC_MODE}"; then
        if [ "${VAAPI_FALLBACK}" = "true" ] && [ "${VAAPI_RC_MODE}" = "bitrate" ]; then
          echo "cam1 vaapi bitrate mode unsupported, retry with quality qp=${VAAPI_QP}"
          if run_yuyv_vaapi "${dev}" quality; then
            return 0
          fi
        fi
        if [ "${VAAPI_FALLBACK}" = "true" ]; then
          echo "cam1 vaapi init failed, fallback to libx264"
          run_yuyv_cpu "${dev}"
        else
          return 1
        fi
      fi
      ;;
    *)
      run_yuyv_cpu "${dev}"
      ;;
  esac
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

probe_vaapi() {
  if [ "${ENCODER}" != "h264_vaapi" ]; then
    return 0
  fi
  if ! command -v vainfo >/dev/null 2>&1; then
    return 0
  fi
  if vainfo --display drm --device "${VAAPI_DEVICE}" >/dev/null 2>&1; then
    echo "cam1 vaapi probe ok device=${VAAPI_DEVICE}${VAAPI_DRIVER:+ driver=${VAAPI_DRIVER}}"
    return 0
  fi
  echo "cam1 vaapi probe failed device=${VAAPI_DEVICE}${VAAPI_DRIVER:+ driver=${VAAPI_DRIVER}}; ffmpeg will try and may fallback"
  return 0
}

startup_rate_summary() {
  case "${ENCODER}" in
    h264_vaapi)
      case "${VAAPI_RC_MODE}" in
        quality)
          printf '%s\n' "encoder=${ENCODER} rc_mode=${VAAPI_RC_MODE} qp=${VAAPI_QP}"
          ;;
        bitrate)
          printf '%s\n' "encoder=${ENCODER} rc_mode=${VAAPI_RC_MODE} bitrate=${BITRATE:-unset} bufsize=${BUFSIZE:-unset}"
          ;;
        *)
          printf '%s\n' "encoder=${ENCODER} rc_mode=${VAAPI_RC_MODE}"
          ;;
      esac
      ;;
    *)
      printf '%s\n' "encoder=${ENCODER} crf=${CRF} bitrate=${BITRATE:-crf-only} bufsize=${BUFSIZE:-none}"
      ;;
  esac
}

echo "cam1 publisher start device=${DEVICE} mode=${MODE} $(startup_rate_summary) res=${RES} fps=${FPS} gop=${GOP}"
probe_vaapi

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
    run_mjpeg "${ACTIVE_DEVICE}" || run_yuyv "${ACTIVE_DEVICE}" || true
  fi

  echo "cam1 ffmpeg restarted in 1s"
  sleep 1
done
