# kurokesu-app

Clean single-camera runtime for:

- `Kurokesu C3 4K`
- `L085 / L085D lens`
- serial PTZ controller

What it does:

- publishes Camera 1 to MediaMTX (`FFmpeg -> RTSP -> WebRTC`)
- serves a root-style UI focused on one camera
- runs map-based zoom from `camzoom.py` logic
- uses the first `8` steps from `zoom25_focusmap.json`
- keeps `limitXY` safety metadata and rejects flagged selected points by default

## Why 8 steps

This project intentionally follows the `camzoom.py` model:

- source map: `zoom25_focusmap.json`
- active runtime steps: first `8` points (`CAM_MAP_STEPS=8`)

The checked-in 25-point source map contains flagged endstop points later in the table.
This runtime keeps the source map intact but only activates the safe 8-step window unless you explicitly change it.

## Run

```bash
cd /Users/codinec/cam/kurokesu-app
docker compose up -d --build
```

UI:

- `http://<host>:8787`

## Main env vars

- `PTZ_SERIAL`
- `PTZ_BAUD`
- `CAM1_DEVICE`
- `CAM_MAP_STEPS` default `8`
- `CAM_STRICT_MAP_LIMITS` default `true`
- `APP_USER`
- `APP_PASS`

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
