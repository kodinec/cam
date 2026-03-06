import argparse
import json
import time

import cv2

try:
    from AVFoundation import (
        AVAuthorizationStatusAuthorized,
        AVAuthorizationStatusDenied,
        AVAuthorizationStatusNotDetermined,
        AVAuthorizationStatusRestricted,
        AVCaptureDevice,
        AVMediaTypeVideo,
    )
    from CoreMedia import CMFormatDescriptionGetMediaSubType, CMVideoFormatDescriptionGetDimensions
except Exception:
    AVCaptureDevice = None
    AVMediaTypeVideo = None
    AVAuthorizationStatusNotDetermined = 0
    AVAuthorizationStatusRestricted = 1
    AVAuthorizationStatusDenied = 2
    AVAuthorizationStatusAuthorized = 3
    CMFormatDescriptionGetMediaSubType = None
    CMVideoFormatDescriptionGetDimensions = None


def fourcc_value(name: str) -> int:
    return cv2.VideoWriter_fourcc(*name)


def fourcc_to_text(v: float) -> str:
    try:
        i = int(v)
    except Exception:
        return "????"
    chars = []
    for shift in (0, 8, 16, 24):
        c = (i >> shift) & 0xFF
        chars.append(chr(c) if 32 <= c <= 126 else "?")
    return "".join(chars)


def list_avf_devices() -> list[dict]:
    if AVCaptureDevice is None:
        return []
    try:
        objs = AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo)
    except Exception:
        try:
            objs = AVCaptureDevice.devices()
        except Exception:
            objs = []

    out: list[dict] = []
    for i, d in enumerate(objs):
        name = ""
        uid = ""
        model = ""
        try:
            name = str(d.localizedName())
        except Exception:
            pass
        try:
            uid = str(d.uniqueID())
        except Exception:
            pass
        if hasattr(d, "modelID"):
            try:
                model = str(d.modelID())
            except Exception:
                pass
        out.append({"index": i, "name": name, "model_id": model, "unique_id": uid})
    return out


def auth_status_text() -> dict:
    if AVCaptureDevice is None or AVMediaTypeVideo is None:
        return {"value": None, "text": "unavailable"}
    try:
        v = int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeVideo))
    except Exception:
        return {"value": None, "text": "error"}
    mapping = {
        int(AVAuthorizationStatusNotDetermined): "not_determined",
        int(AVAuthorizationStatusRestricted): "restricted",
        int(AVAuthorizationStatusDenied): "denied",
        int(AVAuthorizationStatusAuthorized): "authorized",
    }
    return {"value": v, "text": mapping.get(v, "unknown")}


def _fourcc_be(code: int) -> str:
    chars = []
    for shift in (24, 16, 8, 0):
        c = (int(code) >> shift) & 0xFF
        chars.append(chr(c) if 32 <= c <= 126 else "?")
    return "".join(chars)


def _fmt_fps_range(fmt) -> tuple[float | None, float | None]:
    try:
        ranges = list(fmt.videoSupportedFrameRateRanges())
    except Exception:
        ranges = []
    if not ranges:
        return None, None
    mins: list[float] = []
    maxs: list[float] = []
    for r in ranges:
        try:
            mins.append(float(r.minFrameRate()))
            maxs.append(float(r.maxFrameRate()))
        except Exception:
            continue
    if not mins or not maxs:
        return None, None
    return min(mins), max(maxs)


def camera_formats(devs: list[dict], index: int) -> list[dict]:
    if AVCaptureDevice is None or CMVideoFormatDescriptionGetDimensions is None:
        return []
    if index < 0 or index >= len(devs):
        return []
    try:
        objs = AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo)
    except Exception:
        return []
    if index >= len(objs):
        return []
    d = objs[index]
    out: list[dict] = []
    try:
        fmts = list(d.formats())
    except Exception:
        fmts = []
    for i, fmt in enumerate(fmts):
        try:
            desc = fmt.formatDescription()
            dims = CMVideoFormatDescriptionGetDimensions(desc)
            subtype = int(CMFormatDescriptionGetMediaSubType(desc))
            min_fps, max_fps = _fmt_fps_range(fmt)
            out.append(
                {
                    "index": i,
                    "width": int(getattr(dims, "width", 0)),
                    "height": int(getattr(dims, "height", 0)),
                    "subtype_raw": subtype,
                    "subtype_text": _fourcc_be(subtype),
                    "fps_min": min_fps,
                    "fps_max": max_fps,
                }
            )
        except Exception:
            continue
    return out


def resolve_index(devs: list[dict], cam: int, unique_id: str | None, model_id: str | None) -> int:
    if unique_id or model_id:
        for d in devs:
            uid_ok = True if not unique_id else (unique_id in d.get("unique_id", ""))
            model_ok = True if not model_id else (
                model_id in d.get("model_id", "") or model_id in d.get("name", "")
            )
            if uid_ok and model_ok:
                return int(d["index"])
    return cam


def open_capture(index: int, backend: str) -> cv2.VideoCapture:
    if backend == "avfoundation":
        return cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(index)


def test_profile(
    index: int,
    backend: str,
    width: int,
    height: int,
    fps: int,
    codec: str | None,
    warmup_frames: int,
) -> dict:
    res: dict = {
        "backend": backend,
        "index": index,
        "req": {"width": width, "height": height, "fps": fps, "codec": codec or "ANY"},
    }

    cap = open_capture(index, backend)
    if not cap.isOpened():
        res["open_ok"] = False
        res["reason"] = "open_failed"
        return res
    res["open_ok"] = True

    if codec:
        cap.set(cv2.CAP_PROP_FOURCC, float(fourcc_value(codec)))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
    cap.set(cv2.CAP_PROP_FPS, float(fps))
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1.0)

    ok_count = 0
    first_shape = None
    read_mode = "none"
    for _ in range(max(1, warmup_frames)):
        ok, frame = cap.read()
        mode = "read"
        if (not ok) or frame is None or getattr(frame, "size", 0) == 0:
            g = cap.grab()
            if g:
                ok2, frame2 = cap.retrieve()
                if ok2 and frame2 is not None and getattr(frame2, "size", 0) > 0:
                    ok = True
                    frame = frame2
                    mode = "grab+retrieve"
        if ok and frame is not None and frame.size > 0:
            ok_count += 1
            read_mode = mode
            if first_shape is None:
                h, w = frame.shape[:2]
                first_shape = {"width": int(w), "height": int(h)}
        time.sleep(0.01)

    res["frames_ok"] = ok_count
    res["first_frame"] = first_shape
    res["read_mode"] = read_mode

    got_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    got_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    got_fps = cap.get(cv2.CAP_PROP_FPS)
    got_fourcc = cap.get(cv2.CAP_PROP_FOURCC)
    res["actual"] = {
        "width": got_w,
        "height": got_h,
        "fps": got_fps,
        "fourcc_raw": got_fourcc,
        "fourcc_text": fourcc_to_text(got_fourcc),
    }

    z0 = cap.get(cv2.CAP_PROP_ZOOM)
    set_same = cap.set(cv2.CAP_PROP_ZOOM, z0)
    z1 = cap.get(cv2.CAP_PROP_ZOOM)
    res["zoom"] = {"before": z0, "set_same_ok": bool(set_same), "after": z1}

    cap.release()
    return res


def profile_matrix() -> list[tuple[int, int, int, str | None]]:
    return [
        (640, 480, 30, "2vuy"),
        (1024, 768, 30, "420v"),
        (1280, 720, 30, "2vuy"),
        (1920, 1080, 30, "2vuy"),
        (3840, 2160, 30, "2vuy"),
        (3840, 2160, 30, "MJPG"),
        (1920, 1080, 30, "MJPG"),
        (1280, 720, 30, "MJPG"),
        (1920, 1080, 30, None),
        (1280, 720, 30, None),
        (640, 480, 30, None),
        (640, 480, 15, None),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="Console diagnostics for UVC camera open/frame/zoom capability")
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--unique-id", default=None)
    ap.add_argument("--model-id", default=None)
    ap.add_argument("--backend", choices=["avfoundation", "default", "both"], default="both")
    ap.add_argument("--warmup", type=int, default=25)
    ap.add_argument("--show-formats", action="store_true", help="print AVFoundation format list for target camera")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    auth = auth_status_text()
    print(f"AVFoundation auth: {auth['text']} ({auth['value']})")

    devices = list_avf_devices()
    print("AVFoundation devices:")
    if not devices:
        print("  (none / permission denied)")
    else:
        for d in devices:
            print(
                f"  [{d['index']}] name='{d['name']}' model='{d['model_id']}' uid='{d['unique_id']}'"
            )

    cam_index = resolve_index(devices, args.cam, args.unique_id, args.model_id)
    print(f"\nTarget camera index: {cam_index}")

    formats = camera_formats(devices, cam_index)
    if args.show_formats:
        print("\nTarget camera formats:")
        if not formats:
            print("  (no format list)")
        else:
            for f in formats:
                fps_txt = "?"
                if f["fps_min"] is not None and f["fps_max"] is not None:
                    fps_txt = f"{f['fps_min']:.2f}..{f['fps_max']:.2f}"
                print(
                    "  "
                    f"[{f['index']:02d}] {f['width']}x{f['height']} "
                    f"subtype={f['subtype_text']} ({f['subtype_raw']}) fps={fps_txt}"
                )

    if args.backend == "both":
        backends = ["avfoundation", "default"]
    else:
        backends = [args.backend]

    results: list[dict] = []
    print("\nTesting profiles...")
    for backend in backends:
        for w, h, fps, codec in profile_matrix():
            r = test_profile(
                index=cam_index,
                backend=backend,
                width=w,
                height=h,
                fps=fps,
                codec=codec,
                warmup_frames=args.warmup,
            )
            results.append(r)
            req = r["req"]
            if not r.get("open_ok"):
                print(
                    f"  {backend:12s} {req['width']}x{req['height']}@{req['fps']} {req['codec']}: OPEN_FAIL"
                )
                continue
            frames_ok = int(r.get("frames_ok", 0))
            actual = r.get("actual", {})
            print(
                f"  {backend:12s} {req['width']}x{req['height']}@{req['fps']} {req['codec']}: "
                f"frames_ok={frames_ok} actual={int(actual.get('width', 0))}x{int(actual.get('height', 0))} "
                f"fps={actual.get('fps', 0):.2f} fourcc={actual.get('fourcc_text', '????')} "
                f"mode={r.get('read_mode', 'none')}"
            )

    best = None
    for r in results:
        if not r.get("open_ok"):
            continue
        if int(r.get("frames_ok", 0)) <= 0:
            continue
        best = r
        break

    print("\nSummary:")
    if best is None:
        print("  No working profile found (open+frames).")
    else:
        req = best["req"]
        print(
            "  Best first working profile: "
            f"backend={best['backend']} {req['width']}x{req['height']}@{req['fps']} codec={req['codec']}"
        )
        z = best.get("zoom", {})
        print(
            "  Zoom property: "
            f"before={z.get('before')} set_same_ok={z.get('set_same_ok')} after={z.get('after')}"
        )

    report = {
        "auth": auth,
        "devices": devices,
        "target_index": cam_index,
        "formats": formats,
        "results": results,
        "best": best,
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nSaved report: {args.json_out}")


if __name__ == "__main__":
    main()
