# kurokesu-app

Clean single-camera runtime for:

- `Kurokesu C3 4K`
- `L085 / L085D lens`
- serial PTZ controller

What it does:

- publishes Camera 1 to MediaMTX (`FFmpeg -> RTSP -> WebRTC`)
- serves a root-style UI focused on one camera
- runs map-based zoom from `camzoom.py` logic
- uses the first `8` steps from `focusmap.json`
- keeps `limitXY` safety metadata and rejects flagged selected points by default

Video defaults are tuned for a local-box setup:

- default path in this repo is Intel `h264_vaapi` when `/dev/dri` is available
- `h264_vaapi` defaults to `quality` mode, so `QP` drives quality and `BITRATE/BUFSIZE` are ignored there
- automatic fallback to `libx264` stays enabled if VAAPI init fails

If the host has Intel iGPU exposed as `/dev/dri/renderD128`, you can switch the encoder to hardware:

```dotenv
CAM1_ENCODER=h264_vaapi
CAM1_VAAPI_FALLBACK=true
CAM1_VAAPI_DEVICE=/dev/dri/renderD128
CAM1_VAAPI_DRIVER=iHD
CAM1_VAAPI_RC_MODE=quality
CAM1_VAAPI_QP=18
```

This moves H.264 encoding off CPU. Intel hardware is not used automatically just because the host CPU is Intel.
`cam1-publisher` now builds its own image with `ffmpeg + libva + Intel VAAPI drivers`, which is required for the container to use `/dev/dri`.
If `iHD` does not work on an older Intel GPU, try `CAM1_VAAPI_DRIVER=i965`.

## Why 8 steps

This project intentionally follows the `camzoom.py` model:

- source map: `focusmap.json`
- active runtime steps: first `8` points (`CAM_MAP_STEPS=8`)

The checked-in 25-point source map contains flagged endstop points later in the table.
This runtime keeps the source map intact but only activates the safe 8-step window unless you explicitly change it.
The runtime map file is intentionally lean: `coordSpace`, `xPreload`, and `points[]` with `zoomX`, `focusY`, and optional `limitXY`.
The loader still accepts the older array-based schema as a compatibility fallback.

## Run

```bash
cd /Users/codinec/cam/kurokesu-app
cp -n .env.example .env
# edit .env if paths/ports/auth differ
docker compose up -d --build
```

UI:

- `http://<host>:8787`

## Main env vars

- `.env` is the main runtime config file for this project
- `PTZ_SERIAL`
- `PTZ_SERIAL_FALLBACK`
- `PTZ_BAUD`
- `CAM1_DEVICE`
- `CAM_MAP_STEPS` default `8`
- `CAM_STRICT_MAP_LIMITS` default `true`
- `APP_USER`
- `APP_PASS`

For the controller, prefer a stable `/dev/serial/by-id/...` path when available.

## Typical first edit

Most installations only need to verify these lines in `.env`:

```dotenv
CAM1_DEVICE=/dev/v4l/by-id/usb-Kurokesu_C3_4K_00001-video-index0
PTZ_SERIAL=/dev/ttyACM0
PTZ_SERIAL_FALLBACK=/dev/serial/by-id/
WEBRTC_ADDITIONAL_HOSTS=10.10.45.39
```

If you want to force Intel VAAPI by default, keep:

```dotenv
CAM1_MODE=mjpeg
CAM1_ENCODER=h264_vaapi
CAM1_VAAPI_DRIVER=iHD
CAM1_VAAPI_RC_MODE=quality
```

If `iHD` does not initialize on your host, switch to:

```dotenv
CAM1_VAAPI_DRIVER=i965
```

If you want a fixed-rate VAAPI stream instead of QP-driven quality, switch to:

```dotenv
CAM1_ENCODER=h264_vaapi
CAM1_VAAPI_RC_MODE=bitrate
CAM1_BITRATE=20M
CAM1_BUFSIZE=40M
```

In `quality` mode, only `CAM1_VAAPI_QP` is used.
In `bitrate` mode, `CAM1_BITRATE` and `CAM1_BUFSIZE` are used.
`libx264` still uses `CAM1_CRF` plus `CAM1_BITRATE` / `CAM1_BUFSIZE`.

If you want to stay on the CPU path, keep:

```dotenv
CAM1_MODE=mjpeg
CAM1_ENCODER=libx264
```

If you want to validate Intel offload inside the same container image, run:

```bash
docker compose exec cam1-publisher vainfo --display drm --device /dev/dri/renderD128
```

## Runtime behavior

The home flow is:

1. `RESET`
2. `UNLOCK ($X)`
3. `LIMIT LED ON`
4. `IRIS OPEN`
5. `HOME ZOOM ($HX)`
6. `HOME FOCUS ($HY)`
7. `BACKOFF`
8. `GOTO START`
9. `AUTO RELEASE LIMITS`
10. `G92 X0 Y0`

After homing, the UI sends map-index moves:

- preload X if configured
- move X to the selected zoom point
- move Y to the paired focus point

## Checks

```bash
docker compose ps
docker compose logs --tail 120 mediamtx cam1-publisher web
```
