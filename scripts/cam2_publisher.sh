#!/bin/sh
set -eu

DEVICE="${CAM2_DEVICE:-/dev/v4l/by-id/usb-rockchip_UVC_2020-video-index0}"
MODE="${CAM2_MODE:-auto}"
THREAD_QUEUE="${CAM2_THREAD_QUEUE:-256}"
RTSP_URL="${CAM2_RTSP_URL:-rtsp://mediamtx:8554/cam2}"

H264_RES="${CAM2_H264_RES:-1920x1080}"
H264_FPS="${CAM2_H264_FPS:-30}"

MJPEG_RES="${CAM2_MJPEG_RES:-1024x768}"
MJPEG_FPS="${CAM2_MJPEG_FPS:-15}"
GOP="${CAM2_GOP:-25}"
ANALYZE="${CAM2_ANALYZE_DURATION:-5M}"
PROBE="${CAM2_PROBE_SIZE:-5M}"
MJPEG_CRF="${CAM2_MJPEG_CRF:-24}"

run_h264() {
  dev="$1"
  ffmpeg -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay -use_wallclock_as_timestamps 1 \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format h264 -framerate "${H264_FPS}" -video_size "${H264_RES}" \
    -i "${dev}" \
    -an -c:v copy \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

run_mjpeg() {
  dev="$1"
  ffmpeg -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay -use_wallclock_as_timestamps 1 \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format mjpeg -framerate "${MJPEG_FPS}" -video_size "${MJPEG_RES}" \
    -analyzeduration "${ANALYZE}" -probesize "${PROBE}" \
    -i "${dev}" \
    -an \
    -c:v libx264 -preset ultrafast -crf "${MJPEG_CRF}" -tune zerolatency \
    -bf 0 -pix_fmt yuv420p \
    -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 \
    -flush_packets 1 -max_delay 0 -muxdelay 0.0 -muxpreload 0.0 \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

resolve_device() {
  if [ -e "${DEVICE}" ]; then
    echo "${DEVICE}"
    return 0
  fi

  for p in \
    /dev/v4l/by-id/*rockchip*UVC*index0 \
    /dev/v4l/by-id/*rockchip*UVC*index1 \
    /dev/v4l/by-id/*UVC*index0 \
    /dev/v4l/by-id/*UVC*index1 \
    /dev/video2 \
    /dev/video3 \
    /dev/video4 \
    /dev/video5
  do
    if [ -e "$p" ]; then
      echo "$p"
      return 0
    fi
  done

  echo ""
  return 0
}

echo "cam2 publisher start device=${DEVICE} mode=${MODE}"

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

  if [ "${MODE}" = "h264" ]; then
    run_h264 "${ACTIVE_DEVICE}" || true
  elif [ "${MODE}" = "mjpeg" ]; then
    run_mjpeg "${ACTIVE_DEVICE}" || true
  else
    run_h264 "${ACTIVE_DEVICE}" || run_mjpeg "${ACTIVE_DEVICE}" || true
  fi

  echo "cam2 ffmpeg restarted in 1s"
  sleep 1
done
