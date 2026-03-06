import argparse
import time

import cv2

try:
    from AVFoundation import AVCaptureDevice, AVMediaTypeVideo
except Exception:
    AVCaptureDevice = None
    AVMediaTypeVideo = None


def open_camera(index: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    if cap.isOpened():
        return cap
    cap.release()
    # Fallback backend
    cap = cv2.VideoCapture(index)
    return cap


def list_avfoundation_video_devices() -> list[dict]:
    if AVCaptureDevice is None:
        return []
    devices = []
    try:
        objs = AVCaptureDevice.devicesWithMediaType_(AVMediaTypeVideo)
    except Exception:
        try:
            objs = AVCaptureDevice.devices()
        except Exception:
            objs = []
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
        devices.append({"index": i, "name": name, "unique_id": uid, "model_id": model})
    return devices


def resolve_camera_index(unique_id: str | None, model_id: str | None, fallback_index: int) -> int:
    if not unique_id and not model_id:
        return fallback_index

    devices = list_avfoundation_video_devices()
    if not devices:
        raise RuntimeError(
            "Cannot enumerate AVFoundation video devices. "
            "Grant camera permission to Terminal/iTerm and retry."
        )

    for d in devices:
        uid = d.get("unique_id", "")
        mid = d.get("model_id", "")
        name = d.get("name", "")
        uid_ok = True if not unique_id else (unique_id in uid)
        model_ok = True if not model_id else (model_id in mid or model_id in name)
        if uid_ok and model_ok:
            return int(d["index"])

    raise RuntimeError(
        "Requested camera not found in AVFoundation list. "
        "Use --list-devices to inspect available indexes/IDs."
    )


def scan_cameras(max_index: int) -> None:
    print(f"Scanning camera indexes 0..{max_index - 1}")
    found = 0
    for i in range(max_index):
        cap = open_camera(i)
        if not cap.isOpened():
            print(f"[{i}] not available")
            continue
        ok, frame = cap.read()
        if ok and frame is not None:
            h, w = frame.shape[:2]
            print(f"[{i}] OK {w}x{h}")
            found += 1
        else:
            print(f"[{i}] opened but no frame")
        cap.release()
    if found == 0:
        print("No cameras with valid frames found in this range.")


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def apply_digital_zoom_frame(frame, factor: float):
    if factor <= 1.0:
        return frame
    h, w = frame.shape[:2]
    cw = max(2, int(round(w / factor)))
    ch = max(2, int(round(h / factor)))
    x0 = max(0, (w - cw) // 2)
    y0 = max(0, (h - ch) // 2)
    crop = frame[y0 : y0 + ch, x0 : x0 + cw]
    if crop.size == 0:
        return frame
    return cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)


def configure_camera(cap: cv2.VideoCapture, width: int, height: int, fps: int) -> None:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
    cap.set(cv2.CAP_PROP_FPS, float(fps))


def fourcc_value(name: str) -> int:
    return cv2.VideoWriter_fourcc(*name)


def try_open_profile(
    cam_index: int,
    width: int,
    height: int,
    fps: int,
    codec: str | None,
    warmup_frames: int = 25,
) -> tuple[cv2.VideoCapture | None, tuple[int, int] | None]:
    cap = open_camera(cam_index)
    if not cap.isOpened():
        return None, None

    if codec is not None:
        cap.set(cv2.CAP_PROP_FOURCC, float(fourcc_value(codec)))

    configure_camera(cap, width, height, fps)

    frame_shape: tuple[int, int] | None = None
    for _ in range(warmup_frames):
        ok, frame = cap.read()
        if (not ok) or frame is None or getattr(frame, "size", 0) == 0:
            g = cap.grab()
            if g:
                ok2, frame2 = cap.retrieve()
                if ok2 and frame2 is not None and getattr(frame2, "size", 0) > 0:
                    ok = True
                    frame = frame2
        if ok and frame is not None and frame.size > 0:
            h, w = frame.shape[:2]
            frame_shape = (w, h)
            break
        time.sleep(0.02)

    if frame_shape is None:
        cap.release()
        return None, None

    return cap, frame_shape


def open_camera_with_probe(
    cam_index: int,
    width: int,
    height: int,
    fps: int,
    codec_mode: str,
    auto_probe: bool,
) -> tuple[cv2.VideoCapture, tuple[int, int], str]:
    profiles: list[tuple[int, int, int, str | None]] = []

    requested_codec: str | None
    if codec_mode == "mjpg":
        requested_codec = "MJPG"
    elif codec_mode == "yuy2":
        requested_codec = "YUY2"
    elif codec_mode == "2vuy":
        requested_codec = "2vuy"
    elif codec_mode == "420v":
        requested_codec = "420v"
    else:
        requested_codec = None

    profiles.append((width, height, fps, requested_codec))

    if auto_probe:
        probe_list = [
            (1024, 768, 30, "420v"),
            (640, 480, 30, "2vuy"),
            (1280, 720, 30, "2vuy"),
            (1920, 1080, 30, "2vuy"),
            (3840, 2160, 30, "MJPG"),
            (1920, 1080, 30, "MJPG"),
            (1280, 720, 30, "MJPG"),
            (1920, 1080, 30, None),
            (1280, 720, 30, None),
            (640, 480, 30, None),
            (640, 480, 15, None),
        ]
        for p in probe_list:
            if p not in profiles:
                profiles.append(p)

    for w, h, f, c in profiles:
        cap, shape = try_open_profile(cam_index, w, h, f, c)
        if cap is None or shape is None:
            print(f"Profile failed: {w}x{h}@{f} codec={c or 'ANY'}")
            continue
        label = f"{w}x{h}@{f} codec={c or 'ANY'}"
        return cap, shape, label

    raise RuntimeError(
        "Cannot get frames from this camera in tested profiles. "
        "Try closing Photo Booth/OBS and run with --codec 2vuy."
    )


def select_camera_interactive(max_index: int, width: int, height: int, fps: int) -> int | None:
    window = "Select Camera"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    idx = 0

    while 0 <= idx < max_index:
        cap = open_camera(idx)
        if not cap.isOpened():
            print(f"[{idx}] not available")
            idx += 1
            continue

        configure_camera(cap, width, height, fps)
        print(f"Preview camera index {idx}. Keys: s=select, n=next, p=prev, q=quit")

        step = 1
        while True:
            ok, frame = cap.read()
            if ok and frame is not None:
                text1 = f"CAM INDEX: {idx}"
                text2 = "s select | n next | p prev | q quit"
                cv2.putText(frame, text1, (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)
                cv2.putText(frame, text2, (16, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 220, 0), 2, cv2.LINE_AA)
                cv2.imshow(window, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("s"):
                cap.release()
                cv2.destroyWindow(window)
                return idx
            if key in (ord("n"), ord(" ")):
                step = 1
                break
            if key in (ord("p"),):
                step = -1
                break
            if key == ord("q"):
                cap.release()
                cv2.destroyWindow(window)
                return None

        cap.release()
        idx += step

    cv2.destroyWindow(window)
    return None


def apply_zoom(cap: cv2.VideoCapture, value: float) -> tuple[bool, float]:
    ok = cap.set(cv2.CAP_PROP_ZOOM, float(value))
    time.sleep(0.03)
    actual = cap.get(cv2.CAP_PROP_ZOOM)
    return ok, actual


def main() -> None:
    ap = argparse.ArgumentParser(description="UVC camera viewer with +/- zoom control")
    ap.add_argument("--cam", type=int, default=1, help="camera index (camera #2 is usually index 1)")
    ap.add_argument("--scan", action="store_true", help="scan indexes and exit")
    ap.add_argument("--select", action="store_true", help="interactive camera picker by preview")
    ap.add_argument("--list-devices", action="store_true", help="print AVFoundation video devices and exit")
    ap.add_argument("--unique-id", default=None, help="prefer camera by AVFoundation unique ID")
    ap.add_argument("--model-id", default=None, help="prefer camera by model ID/name substring")
    ap.add_argument("--scan-max", type=int, default=8)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=768)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--codec", choices=["auto", "mjpg", "yuy2", "2vuy", "420v", "any"], default="420v")
    ap.add_argument("--no-auto-probe", dest="auto_probe", action="store_false")
    ap.add_argument("--auto-probe", dest="auto_probe", action="store_true", default=True)
    ap.add_argument("--zoom-step", type=float, default=5.0)
    ap.add_argument("--zoom-min", type=float, default=0.0)
    ap.add_argument("--zoom-max", type=float, default=1000.0)
    ap.add_argument("--zoom-start", type=float, default=None)
    ap.add_argument("--digital-zoom-max", type=float, default=4.0)
    args = ap.parse_args()

    if args.scan:
        scan_cameras(args.scan_max)
        return

    if args.list_devices:
        devices = list_avfoundation_video_devices()
        if not devices:
            print("No AVFoundation video devices found (or permission denied).")
            return
        for d in devices:
            print(
                f"[{d['index']}] name='{d['name']}' "
                f"model_id='{d['model_id']}' unique_id='{d['unique_id']}'"
            )
        return

    cam_index = args.cam
    if args.unique_id or args.model_id:
        cam_index = resolve_camera_index(args.unique_id, args.model_id, args.cam)
        print(f"Resolved camera index from ID filter: {cam_index}")

    if args.select:
        selected = select_camera_interactive(args.scan_max, args.width, args.height, args.fps)
        if selected is None:
            print("No camera selected.")
            return
        cam_index = selected
        print(f"Selected camera index: {cam_index}")

    codec_mode = "any" if args.codec == "any" else args.codec
    cap, frame_shape, profile_label = open_camera_with_probe(
        cam_index=cam_index,
        width=args.width,
        height=args.height,
        fps=args.fps,
        codec_mode=codec_mode,
        auto_probe=args.auto_probe,
    )

    zoom_target = cap.get(cv2.CAP_PROP_ZOOM)
    if zoom_target is None:
        zoom_target = 0.0
    if args.zoom_start is not None:
        zoom_target = args.zoom_start

    zoom_target = clamp(float(zoom_target), args.zoom_min, args.zoom_max)
    set_ok, zoom_actual = apply_zoom(cap, zoom_target)
    hw_zoom_supported = bool(set_ok)
    digital_zoom = 1.0

    print("Controls:")
    print("  + : zoom in")
    print("  - : zoom out")
    print("  q : quit")
    print(f"Video profile: {profile_label} actual_frame={frame_shape[0]}x{frame_shape[1]}")
    print(f"Start zoom target={zoom_target:.2f}, actual={zoom_actual:.2f}, set_ok={set_ok}")
    if not hw_zoom_supported:
        print(
            "Hardware zoom not available on this camera via OpenCV. "
            "Using digital preview zoom fallback."
        )

    window = f"Cam {cam_index} (NVECTECH)"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            continue

        if not hw_zoom_supported:
            frame = apply_digital_zoom_frame(frame, digital_zoom)

        line1 = f"zoom target={zoom_target:.2f} actual={zoom_actual:.2f}"
        if not hw_zoom_supported:
            line1 += f" digital={digital_zoom:.2f}x"
        line2 = f"set_ok={set_ok}  keys: +/- zoom, q quit"
        cv2.putText(frame, line1, (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
        cv2.putText(frame, line2, (16, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 220, 0), 2, cv2.LINE_AA)
        cv2.imshow(window, frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key in (ord("+"), ord("=")):
            zoom_target = clamp(zoom_target + args.zoom_step, args.zoom_min, args.zoom_max)
            if hw_zoom_supported:
                set_ok, zoom_actual = apply_zoom(cap, zoom_target)
                print(f"[+] target={zoom_target:.2f} actual={zoom_actual:.2f} set_ok={set_ok}")
            else:
                digital_zoom = clamp(digital_zoom + (args.zoom_step / 100.0), 1.0, args.digital_zoom_max)
                print(f"[+] digital zoom={digital_zoom:.2f}x (hardware zoom unsupported)")
        elif key == ord("-"):
            zoom_target = clamp(zoom_target - args.zoom_step, args.zoom_min, args.zoom_max)
            if hw_zoom_supported:
                set_ok, zoom_actual = apply_zoom(cap, zoom_target)
                print(f"[-] target={zoom_target:.2f} actual={zoom_actual:.2f} set_ok={set_ok}")
            else:
                digital_zoom = clamp(digital_zoom - (args.zoom_step / 100.0), 1.0, args.digital_zoom_max)
                print(f"[-] digital zoom={digital_zoom:.2f}x (hardware zoom unsupported)")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
