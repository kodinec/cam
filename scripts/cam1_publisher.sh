#!/bin/sh
set -eu

DEVICE="${CAM1_DEVICE:-/dev/video0}"
MODE="${CAM1_MODE:-mjpeg}"
FPS="${CAM1_FPS:-30}"
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
  ffmpeg -hide_banner -loglevel warning \
    -fflags +nobuffer+discardcorrupt+genpts -flags low_delay -use_wallclock_as_timestamps 1 \
    -avioflags direct \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format mjpeg -framerate "${FPS}" -video_size "${RES}" \
    -i "${DEVICE}" \
    -an \
    -vf "scale=in_range=pc:out_range=tv,format=yuv420p,settb=AVTB,setpts=N/(${FPS}*TB)" \
    -c:v libx264 -preset "${PRESET}" -crf "${CRF}" -tune zerolatency \
    -bf 0 -pix_fmt yuv420p -b:v "${BITRATE}" -maxrate "${BITRATE}" -bufsize "${BUFSIZE}" \
    -x264-params "${X264_PARAMS}" \
    -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 \
    -fps_mode cfr -r "${FPS}" \
    -flush_packets 1 -max_delay 0 -muxdelay 0.0 -muxpreload 0.0 \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

run_yuyv() {
  ffmpeg -hide_banner -loglevel warning \
    -fflags +nobuffer+discardcorrupt+genpts -flags low_delay -use_wallclock_as_timestamps 1 \
    -avioflags direct \
    -thread_queue_size "${THREAD_QUEUE}" \
    -f v4l2 -input_format yuyv422 -framerate "${FPS}" -video_size "${RES}" \
    -i "${DEVICE}" \
    -an \
    -vf "format=yuv420p,settb=AVTB,setpts=N/(${FPS}*TB)" \
    -c:v libx264 -preset "${PRESET}" -crf "${CRF}" -tune zerolatency \
    -bf 0 -pix_fmt yuv420p -b:v "${BITRATE}" -maxrate "${BITRATE}" -bufsize "${BUFSIZE}" \
    -x264-params "${X264_PARAMS}" \
    -g "${GOP}" -keyint_min "${GOP}" -sc_threshold 0 \
    -fps_mode cfr -r "${FPS}" \
    -flush_packets 1 -max_delay 0 -muxdelay 0.0 -muxpreload 0.0 \
    -f rtsp -rtsp_transport tcp "${RTSP_URL}"
}

echo "cam1 publisher start device=${DEVICE} mode=${MODE} res=${RES} fps=${FPS} gop=${GOP} crf=${CRF}"

while true; do
  if [ ! -e "${DEVICE}" ]; then
    echo "cam1 device missing: ${DEVICE}. waiting..."
    sleep 1
    continue
  fi

  if [ "${MODE}" = "mjpeg" ]; then
    echo "cam1 run: mjpeg"
    run_mjpeg || true
  elif [ "${MODE}" = "yuyv" ]; then
    echo "cam1 run: yuyv"
    run_yuyv || true
  else
    echo "cam1 run: auto(mjpeg->yuyv)"
    run_mjpeg || run_yuyv || true
  fi

  echo "cam1 ffmpeg restarted in 1s"
  sleep 1
done
