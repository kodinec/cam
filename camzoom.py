import argparse
import json
import re
import time

import serial


OK_RE = re.compile(r"^(ok|error:.*|alarm:.*)$", re.IGNORECASE)
MPOS_RE = re.compile(r"MPos:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)", re.IGNORECASE)
WPOS_RE = re.compile(r"WPos:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)", re.IGNORECASE)
WCO_RE = re.compile(r"WCO:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)", re.IGNORECASE)
PN_RE = re.compile(r"Pn:([A-Z]+)", re.IGNORECASE)


def open_serial(port: str, baud: int) -> serial.Serial:
    ser = serial.Serial(port, baud, timeout=0.25)
    ser.write(b"\r\n\r\n")
    time.sleep(0.25)
    ser.reset_input_buffer()
    return ser


def send_command(ser: serial.Serial, cmd: str, wait: float = 2.0) -> list[str]:
    cmd = cmd.strip()
    if not cmd:
        return []
    ser.write((cmd + "\r\n").encode("utf-8"))
    ser.flush()
    out: list[str] = []
    deadline = time.time() + wait
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").strip()
        if not line:
            continue
        out.append(line)
        if OK_RE.match(line):
            break
    return out


def read_status(ser: serial.Serial) -> str:
    ser.write(b"?\r\n")
    time.sleep(0.12)
    raw = ser.read_all().decode(errors="ignore")
    lines = [x.strip() for x in raw.splitlines() if x.strip().startswith("<")]
    return lines[-1] if lines else raw.strip()


def parse_state(status_line: str) -> str | None:
    if not status_line.startswith("<") or "|" not in status_line:
        return None
    return status_line[1:].split("|", 1)[0]


def parse_mpos(status_line: str) -> tuple[float, float, float, float] | None:
    m = MPOS_RE.search(status_line)
    if not m:
        return None
    return tuple(float(m.group(i)) for i in range(1, 5))


def parse_wco(status_line: str) -> tuple[float, float, float, float] | None:
    m = WCO_RE.search(status_line)
    if not m:
        return None
    return tuple(float(m.group(i)) for i in range(1, 5))


def parse_wpos(status_line: str) -> tuple[float, float, float, float] | None:
    m = WPOS_RE.search(status_line)
    if m:
        return tuple(float(m.group(i)) for i in range(1, 5))
    mpos = parse_mpos(status_line)
    wco = parse_wco(status_line)
    if mpos is not None and wco is not None:
        return tuple(mpos[i] - wco[i] for i in range(4))
    return None


def parse_limits(status_line: str) -> set[str]:
    m = PN_RE.search(status_line)
    if not m:
        return set()
    return set(m.group(1).upper())


def sync_soft_wco(runtime: dict, status_line: str) -> None:
    wco = parse_wco(status_line)
    if wco is not None:
        runtime["soft_wco"] = wco


def get_wpos(runtime: dict, status_line: str) -> tuple[float, float, float, float] | None:
    wpos = parse_wpos(status_line)
    if wpos is not None:
        return wpos
    mpos = parse_mpos(status_line)
    if mpos is None:
        return None
    soft_wco = runtime.get("soft_wco")
    if soft_wco is None:
        return mpos
    return tuple(mpos[i] - soft_wco[i] for i in range(4))


def print_status(runtime: dict, st: str) -> None:
    sync_soft_wco(runtime, st)
    print(st)
    wpos = get_wpos(runtime, st)
    mpos = parse_mpos(st)
    if wpos is not None:
        print(f"WPos X={wpos[0]:.3f} Y={wpos[1]:.3f}")
    if mpos is not None:
        print(f"MPos X={mpos[0]:.3f} Y={mpos[1]:.3f}")
    lim = parse_limits(st)
    if lim:
        print(f"LIMIT ACTIVE: {''.join(sorted(lim))}")


def wait_for_idle(ser: serial.Serial, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = read_status(ser)
        state = parse_state(last)
        if state == "Idle":
            return last
        if state and state.startswith("Alarm"):
            raise RuntimeError(f"Controller alarm: {last}")
        time.sleep(0.06)
    raise TimeoutError(f"Timeout waiting Idle. Last status: {last}")


def move_xy(ser: serial.Serial, x: float | None, y: float | None, feed: float, timeout: float = 20.0) -> None:
    parts = []
    if x is not None:
        parts.append(f"X{x:.3f}")
    if y is not None:
        parts.append(f"Y{y:.3f}")
    if not parts:
        return
    send_command(ser, "G90", 1.0)
    send_command(ser, "G1 " + " ".join(parts) + f" F{feed:.1f}", 4.0)
    wait_for_idle(ser, timeout=timeout)


def move_xy_to_mpos(
    ser: serial.Serial,
    target_x: float | None,
    target_y: float | None,
    feed: float,
    timeout: float = 20.0,
) -> None:
    st = read_status(ser)
    pos = parse_mpos(st)
    if pos is None:
        raise RuntimeError(f"Cannot parse MPos: {st}")
    dx = None if target_x is None else target_x - pos[0]
    dy = None if target_y is None else target_y - pos[1]
    if dx is None and dy is None:
        return
    cmd = ["G1"]
    if dx is not None:
        cmd.append(f"X{dx:.3f}")
    if dy is not None:
        cmd.append(f"Y{dy:.3f}")
    cmd.append(f"F{feed:.1f}")
    send_command(ser, "G91", 1.0)
    send_command(ser, " ".join(cmd), 4.0)
    send_command(ser, "G90", 1.0)
    wait_for_idle(ser, timeout=timeout)


def move_rel(ser: serial.Serial, axis: str, delta: float, feed: float, timeout: float = 10.0) -> None:
    send_command(ser, "G91", 1.0)
    send_command(ser, f"G1 {axis}{delta:.3f} F{feed:.1f}", 4.0)
    send_command(ser, "G90", 1.0)
    wait_for_idle(ser, timeout=timeout)


def release_axis_limit(ser: serial.Serial, axis: str, step: float, max_steps: int, feed: float) -> bool:
    axis = axis.upper()
    st = read_status(ser)
    if axis not in parse_limits(st):
        return True
    print(f"Axis {axis} limit is active, trying to release...")
    for direction in (1.0, -1.0):
        for _ in range(max_steps):
            move_rel(ser, axis, direction * abs(step), feed, timeout=10.0)
            st = read_status(ser)
            if axis not in parse_limits(st):
                print(f"Axis {axis} released.")
                return True
    return False


def auto_release_limits(ser: serial.Serial, step_x: float, step_y: float, max_steps: int, feed: float) -> None:
    st = read_status(ser)
    limits = parse_limits(st)
    if not limits:
        return
    print(f"Active limits detected after move: {''.join(sorted(limits))}")
    ok_x = True
    ok_y = True
    if "X" in limits:
        ok_x = release_axis_limit(ser, "X", step_x, max_steps, feed)
    if "Y" in limits:
        ok_y = release_axis_limit(ser, "Y", step_y, max_steps, feed)
    st = read_status(ser)
    limits = parse_limits(st)
    if not ok_y or "Y" in limits:
        raise RuntimeError("Could not release Y limit automatically.")
    if not ok_x or "X" in limits:
        print("WARNING: X limit is still active after auto-release.")


def run_start_flow(ser: serial.Serial, args: argparse.Namespace) -> None:
    print("\n=== START FLOW ===")
    print("1) RESET")
    if args.reset:
        ser.write(b"\x18")
        time.sleep(1.0)
        ser.reset_input_buffer()
    else:
        print("   skipped")

    print("2) UNLOCK ($X)")
    send_command(ser, "$X", 2.0)
    send_command(ser, "G90", 1.0)

    if args.limit_led:
        print("3) LIMIT LED ON (M120 P1)")
        send_command(ser, "M120 P1", 1.5)
    else:
        print("3) LIMIT LED skipped")

    if args.iris_open:
        print("4) IRIS OPEN (M114 P1)")
        send_command(ser, "M114 P1", 1.5)
    else:
        print("4) IRIS OPEN skipped")

    print("5) HOME ZOOM ($HX)")
    send_command(ser, "$HX", 3.0)
    wait_for_idle(ser, timeout=args.home_timeout)

    print("6) HOME FOCUS ($HY)")
    send_command(ser, "$HY", 3.0)
    wait_for_idle(ser, timeout=args.home_timeout)

    print("7) BACKOFF")
    send_command(ser, "G91", 1.0)
    send_command(ser, f"G1 X{args.backoff_x:.3f} Y{args.backoff_y:.3f} F{args.backoff_feed:.1f}", 3.0)
    send_command(ser, "G90", 1.0)
    wait_for_idle(ser, timeout=10.0)

    print(f"8) GOTO START X={args.start_x:.3f} Y={args.start_y:.3f}")
    move_xy(ser, x=args.start_x, y=args.start_y, feed=args.goto_feed, timeout=20.0)

    print("8b) AUTO RELEASE LIMITS")
    auto_release_limits(ser, args.release_step_x, args.release_step_y, args.release_max_steps, args.release_feed)

    print("9) SET X0 Y0 (G92 X0 Y0)")
    send_command(ser, "G92 X0 Y0", 1.0)


def load_steps(path: str, steps: int) -> tuple[list[float], list[float | None], str, float]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    zoom = data.get("zoomX")
    focus = data.get("focusY")
    meta = data.get("meta", {})
    if not isinstance(zoom, list) or not isinstance(focus, list):
        raise ValueError("Map JSON must contain arrays zoomX/focusY")
    if len(zoom) < steps or len(focus) < steps:
        raise ValueError(f"Map has less than {steps} points")
    zoom_out = [float(v) for v in zoom[:steps]]
    focus_out: list[float | None] = []
    for v in focus[:steps]:
        if v is None:
            focus_out.append(None)
        else:
            focus_out.append(float(v))
    coord_space = str(meta.get("coord_space", "wpos")).lower()
    if coord_space not in {"wpos", "mpos"}:
        coord_space = "wpos"
    x_preload = float(meta.get("x_preload", 0.02))
    return zoom_out, focus_out, coord_space, x_preload


def goto_step(
    ser: serial.Serial,
    runtime: dict,
    idx: int,
    zoom: list[float],
    focus: list[float | None],
    map_coords: str,
    x_preload: float,
    feed: float,
) -> None:
    x = zoom[idx]
    y = focus[idx]

    if x_preload > 0:
        pre_x = x - abs(x_preload)
        if map_coords == "mpos":
            move_xy_to_mpos(ser, pre_x, None, feed, timeout=20.0)
            move_xy_to_mpos(ser, x, None, feed, timeout=20.0)
        else:
            move_xy(ser, pre_x, None, feed, timeout=20.0)
            move_xy(ser, x, None, feed, timeout=20.0)
    else:
        if map_coords == "mpos":
            move_xy_to_mpos(ser, x, None, feed, timeout=20.0)
        else:
            move_xy(ser, x, None, feed, timeout=20.0)

    if y is not None:
        if map_coords == "mpos":
            move_xy_to_mpos(ser, None, y, feed, timeout=20.0)
        else:
            move_xy(ser, None, y, feed, timeout=20.0)

    if y is None:
        print(f"Step {idx}: X={x:.3f} (focus unchanged)")
    else:
        print(f"Step {idx}: X={x:.3f} Y={y:.3f}")
    st = read_status(ser)
    print_status(runtime, st)


def main() -> None:
    ap = argparse.ArgumentParser(description="Minimal camera zoom stepper (0..7) with + and - only")
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--map", default="/Users/codinec/cam/zoom25_focusmap.json")
    ap.add_argument("--steps", type=int, default=8, help="use first N steps from map")
    ap.add_argument("--feed", type=float, default=180.0)

    # Start-flow controls
    ap.add_argument("--reset", action="store_true", default=True)
    ap.add_argument("--no-reset", dest="reset", action="store_false")
    ap.add_argument("--iris-open", action="store_true", default=True)
    ap.add_argument("--no-iris-open", dest="iris_open", action="store_false")
    ap.add_argument("--limit-led", action="store_true", default=True)
    ap.add_argument("--no-limit-led", dest="limit_led", action="store_false")
    ap.add_argument("--home-timeout", type=float, default=25.0)
    ap.add_argument("--backoff-x", type=float, default=1.0)
    ap.add_argument("--backoff-y", type=float, default=0.5)
    ap.add_argument("--backoff-feed", type=float, default=120.0)
    ap.add_argument("--start-x", type=float, default=0.0)
    ap.add_argument("--start-y", type=float, default=0.0)
    ap.add_argument("--goto-feed", type=float, default=200.0)
    ap.add_argument("--release-step-x", type=float, default=0.2)
    ap.add_argument("--release-step-y", type=float, default=0.2)
    ap.add_argument("--release-max-steps", type=int, default=40)
    ap.add_argument("--release-feed", type=float, default=80.0)
    args = ap.parse_args()

    if args.steps < 2:
        raise ValueError("--steps must be >= 2")

    zoom, focus, map_coords, map_x_preload = load_steps(args.map, args.steps)
    runtime = {"soft_wco": None}
    current_idx = 0

    with open_serial(args.port, args.baud) as ser:
        run_start_flow(ser, args)

        print("\nGo to step 0...")
        goto_step(
            ser=ser,
            runtime=runtime,
            idx=0,
            zoom=zoom,
            focus=focus,
            map_coords=map_coords,
            x_preload=map_x_preload,
            feed=args.feed,
        )

        print("\nCommands:")
        print("  + | zoom+         one step zoom in")
        print("  - | zoom-         one step zoom out")
        print("  q                 quit\n")

        max_idx = args.steps - 1
        while True:
            cmd = input("> ").strip().lower()
            if cmd in {"q", "quit", "exit"}:
                break
            if cmd in {"+", "zoom+", "z+", "in"}:
                if current_idx >= max_idx:
                    print("Already at max step.")
                    continue
                current_idx += 1
                goto_step(ser, runtime, current_idx, zoom, focus, map_coords, map_x_preload, args.feed)
                continue
            if cmd in {"-", "zoom-", "z-", "out"}:
                if current_idx <= 0:
                    print("Already at min step.")
                    continue
                current_idx -= 1
                goto_step(ser, runtime, current_idx, zoom, focus, map_coords, map_x_preload, args.feed)
                continue
            print("Use only: +, -, q")


if __name__ == "__main__":
    main()
