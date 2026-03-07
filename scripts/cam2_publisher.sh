#!/bin/sh
set -eu

DEVICE="${CAM2_DEVICE:-/dev/v4l/by-id/usb-rockchip_UVC_2020-video-index0}"
MODE="${CAM2_MODE:-mjpeg}"
THREAD_QUEUE="${CAM2_THREAD_QUEUE:-64}"
RTSP_URL="${CAM2_RTSP_URL:-rtsp://mediamtx:8554/cam2}"

H264_RES="${CAM2_H264_RES:-1920x1080}"
H264_FPS="${CAM2_H264_FPS:-30}"

MJPEG_RES="${CAM2_MJPEG_RES:-1024x768}"
MJPEG_FPS="${CAM2_MJPEG_FPS:-15}"
GOP="${CAM2_GOP:-15}"
ANALYZE="${CAM2_ANALYZE_DURATION:-5M}"
PROBE="${CAM2_PROBE_SIZE:-5M}"
MJPEG_CRF="${CAM2_MJPEG_CRF:-24}"
MJPEG_BITRATE="${CAM2_MJPEG_BITRATE:-4M}"
MJPEG_BUFSIZE="${CAM2_MJPEG_BUFSIZE:-512k}"
MJPEG_X264_PARAMS="${CAM2_MJPEG_X264_PARAMS:-bframes=0:rc-lookahead=0:sync-lookahead=0:scenecut=0}"

run_h264() {
  dev="$1"
  ffmpeg -hide_banner -loglevel warning \
    -fflags +nobuffer+discardcorrupt+genpts -flags low_delay -use_wallclock_as_timestamps 1 \
    -avioflags direct \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format h264 -framerate "${H264_FPS}" -video_size "${H264_RES}" \
    -i "${dev}" \
    -an -c:v copy -fps_mode passthrough -vsync passthrough \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

run_mjpeg() {
  dev="$1"
  ffmpeg -hide_banner -loglevel warning \
    -fflags +nobuffer+discardcorrupt+genpts -flags low_delay -use_wallclock_as_timestamps 1 \
    -avioflags direct \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format mjpeg -framerate "${MJPEG_FPS}" -video_size "${MJPEG_RES}" \
    -analyzeduration "${ANALYZE}" -probesize "${PROBE}" \
    -i "${dev}" \
    -an \
    -c:v libx264 -preset ultrafast -crf "${MJPEG_CRF}" -tune zerolatency \
    -bf 0 -pix_fmt yuv420p -b:v "${MJPEG_BITRATE}" -maxrate "${MJPEG_BITRATE}" -bufsize "${MJPEG_BUFSIZE}" \
    -x264-params "${MJPEG_X264_PARAMS}" \
    -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 \
    -fps_mode passthrough -vsync passthrough \
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
    /dev/v4l/by-id/*UVC*index0 \
    /dev/video2 \
    /dev/video4 \
    /dev/video6
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

  # Give USB camera a moment after reconnect before opening stream.
  sleep 0.4

  if [ "${MODE}" = "h264" ]; then
    echo "cam2 run: h264"
    run_h264 "${ACTIVE_DEVICE}" || true
  elif [ "${MODE}" = "mjpeg" ]; then
    echo "cam2 run: mjpeg"
    run_mjpeg "${ACTIVE_DEVICE}" || true
  else
    echo "cam2 run: auto(mjpeg->h264)"
    run_mjpeg "${ACTIVE_DEVICE}" || run_h264 "${ACTIVE_DEVICE}" || true
  fi

  echo "cam2 ffmpeg restarted in 1s"
  sleep 1
done
