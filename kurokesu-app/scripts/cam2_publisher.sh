#!/bin/sh
set -eu

DEVICE="${CAM2_DEVICE:-/dev/v4l/by-id/usb-rockchip_UVC_2020-video-index0}"
FPS="${CAM2_FPS:-15}"
RES="${CAM2_RES:-1024x768}"
THREAD_QUEUE="${CAM2_THREAD_QUEUE:-64}"
ENCODER="${CAM2_ENCODER:-h264_vaapi}"
VAAPI_FALLBACK="${CAM2_VAAPI_FALLBACK:-true}"
VAAPI_DRIVER="${CAM2_VAAPI_DRIVER:-}"
VAAPI_DEVICE="${CAM2_VAAPI_DEVICE:-/dev/dri/renderD128}"
VAAPI_RC_MODE="${CAM2_VAAPI_RC_MODE:-bitrate}"
VAAPI_QP="${CAM2_VAAPI_QP:-20}"
BITRATE="${CAM2_BITRATE:-4M}"
BUFSIZE="${CAM2_BUFSIZE:-8M}"
PRESET="${CAM2_X264_PRESET:-veryfast}"
TUNE="${CAM2_X264_TUNE:-zerolatency}"
CRF="${CAM2_CRF:-23}"
GOP="${CAM2_GOP:-15}"
RTSP_URL="${CAM2_RTSP_URL:-rtsp://mediamtx:8554/cam2}"
X264_PARAMS="${CAM2_X264_PARAMS:-bframes=0:rc-lookahead=0:sync-lookahead=0:scenecut=0}"

if [ -n "${VAAPI_DRIVER}" ]; then
  export LIBVA_DRIVER_NAME="${VAAPI_DRIVER}"
fi

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

cpu_encoder_args() {
  args="
    -vf scale=in_range=pc:out_range=tv,format=yuv420p,fps=${FPS}
    -an
    -c:v libx264 -preset ${PRESET} -tune ${TUNE} -crf ${CRF}
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

vaapi_encoder_args() {
  rc_mode="$1"
  args="
    -vf scale=in_range=pc:out_range=tv,format=nv12,hwupload,fps=${FPS}
    -an
    -vaapi_device ${VAAPI_DEVICE}
    -c:v h264_vaapi
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
      echo "cam2 invalid CAM2_VAAPI_RC_MODE=${rc_mode}; expected quality or bitrate" >&2
      return 1
      ;;
  esac
  # shellcheck disable=SC2086
  set -- ${args}
  printf '%s\n' "$@"
}

run_cpu() {
  dev="$1"
  ENCODER_ARGS="$(cpu_encoder_args)"
  ffmpeg -hide_banner -loglevel warning \
    -fflags +genpts -use_wallclock_as_timestamps 1 \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format mjpeg -framerate "${FPS}" -video_size "${RES}" \
    -i "${dev}" \
    ${ENCODER_ARGS} \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

run_vaapi() {
  dev="$1"
  rc_mode="$2"
  ENCODER_ARGS="$(vaapi_encoder_args "${rc_mode}")"
  ffmpeg -hide_banner -loglevel warning \
    -fflags +genpts -use_wallclock_as_timestamps 1 \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format mjpeg -framerate "${FPS}" -video_size "${RES}" \
    -i "${dev}" \
    ${ENCODER_ARGS} \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

probe_vaapi() {
  if [ "${ENCODER}" != "h264_vaapi" ]; then
    return 0
  fi
  if ! command -v vainfo >/dev/null 2>&1; then
    return 0
  fi
  if vainfo --display drm --device "${VAAPI_DEVICE}" >/dev/null 2>&1; then
    echo "cam2 vaapi probe ok device=${VAAPI_DEVICE}${VAAPI_DRIVER:+ driver=${VAAPI_DRIVER}}"
    return 0
  fi
  echo "cam2 vaapi probe failed device=${VAAPI_DEVICE}${VAAPI_DRIVER:+ driver=${VAAPI_DRIVER}}; ffmpeg will try and may fallback"
  return 0
}

run_stream() {
  dev="$1"
  case "${ENCODER}" in
    h264_vaapi)
      if ! run_vaapi "${dev}" "${VAAPI_RC_MODE}"; then
        if [ "${VAAPI_FALLBACK}" = "true" ] && [ "${VAAPI_RC_MODE}" = "bitrate" ]; then
          echo "cam2 vaapi bitrate mode unsupported, retry with quality qp=${VAAPI_QP}"
          if run_vaapi "${dev}" quality; then
            return 0
          fi
        fi
        if [ "${VAAPI_FALLBACK}" = "true" ]; then
          echo "cam2 vaapi init failed, fallback to libx264"
          run_cpu "${dev}"
          return 0
        fi
        return 1
      fi
      ;;
    *)
      run_cpu "${dev}"
      ;;
  esac
}

startup_rate_summary() {
  case "${ENCODER}" in
    h264_vaapi)
      case "${VAAPI_RC_MODE}" in
        quality)
          printf '%s\n' "mode=mjpeg->h264 encoder=${ENCODER} rc_mode=${VAAPI_RC_MODE} qp=${VAAPI_QP}"
          ;;
        bitrate)
          printf '%s\n' "mode=mjpeg->h264 encoder=${ENCODER} rc_mode=${VAAPI_RC_MODE} bitrate=${BITRATE:-unset} bufsize=${BUFSIZE:-unset}"
          ;;
        *)
          printf '%s\n' "mode=mjpeg->h264 encoder=${ENCODER} rc_mode=${VAAPI_RC_MODE}"
          ;;
      esac
      ;;
    *)
      printf '%s\n' "mode=mjpeg->h264 encoder=${ENCODER} crf=${CRF} bitrate=${BITRATE:-crf-only} bufsize=${BUFSIZE:-none}"
      ;;
  esac
}

echo "cam2 publisher start device=${DEVICE} $(startup_rate_summary) res=${RES} fps=${FPS} gop=${GOP}"
probe_vaapi

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
