# new-app

Minimal clean baseline for two USB cameras:
- `cam1` and `cam2` publishers (FFmpeg -> RTSP)
- MediaMTX (RTSP ingest + WebRTC playback)
- small Go web UI (`:8787`)

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

## Quick checks

```bash
docker compose ps
docker compose logs --tail 120 cam1-publisher cam2-publisher mediamtx web
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/
```

## Notes

- Publishers use primary `by-id` path and fallback `/dev/videoN`.
- If Camera 2 repeatedly switches between `idProduct=0000` and `idProduct=1005`,
  this is USB/firmware instability (outside app logic). In that state software can
  only retry; stream will flap until the device stabilizes.
