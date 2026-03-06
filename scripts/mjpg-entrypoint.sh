#!/bin/sh
set -eu

CAM_DEVICE="${CAM_DEVICE:-/dev/video0}"
CAM_RES="${CAM_RES:-1280x720}"
CAM_FPS="${CAM_FPS:-25}"
CAM_PORT="${CAM_PORT:-8080}"

WWW_DIR=""
for d in /usr/share/mjpg-streamer/www /usr/local/share/mjpg-streamer/www; do
  if [ -d "$d" ]; then
    WWW_DIR="$d"
    break
  fi
done
if [ -z "$WWW_DIR" ]; then
  echo "mjpg-streamer web dir not found" >&2
  exit 1
fi

echo "Starting mjpg-streamer: device=$CAM_DEVICE res=$CAM_RES fps=$CAM_FPS port=$CAM_PORT www=$WWW_DIR"
exec mjpg_streamer \
  -i "input_uvc.so -d $CAM_DEVICE -r $CAM_RES -f $CAM_FPS -y" \
  -o "output_http.so -p $CAM_PORT -w $WWW_DIR"
