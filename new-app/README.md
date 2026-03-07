# new-app

Minimal clean baseline for two USB cameras:
- `cam1` and `cam2` publishers (FFmpeg -> RTSP)
- MediaMTX (RTSP ingest + WebRTC playback)
- small Go web UI (`:8787`)
- `ptz-init` startup flow for Camera 1 lens controller

## Run

```bash
cd /home/new-app
cp -n .env.example .env
docker compose up -d --build
```

UI:
- `http://10.10.45.39:8787`

Direct WebRTC pages:
- `http://10.10.45.39:8889/cam1/`
- `http://10.10.45.39:8889/cam2/`

If ports are already busy (old stack is still running), start with overrides:

```bash
MTX_RTSP_PORT=18554 \
MTX_WEBRTC_HTTP_PORT=18889 \
MTX_WEBRTC_ICE_PORT=18189 \
WEB_PORT=18787 \
docker compose up -d --build
```

Then open:
- `http://10.10.45.39:18787`

## Quick checks

```bash
docker compose ps
docker compose logs --tail 120 cam1-publisher cam2-publisher mediamtx web
docker compose logs --tail 120 ptz-init
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/
```

## Notes

- Publishers use primary `by-id` path and fallback `/dev/videoN`.
- Camera 1 stream is gated by `ptz-init` startup sequence:
  `RESET -> $X -> M120 -> M114 -> $HX -> $HY -> BACKOFF -> GOTO START -> AUTO RELEASE LIMITS -> G92`.
- If Camera 2 repeatedly switches between `idProduct=0000` and `idProduct=1005`,
  this is USB/firmware instability (outside app logic). In that state software can
  only retry; stream will flap until the device stabilizes.
