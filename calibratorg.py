import argparse
import json
import re
import time

import serial


OK_RE = re.compile(r"^(ok|error:.*|alarm:.*)$", re.IGNORECASE)
MPOS_RE = re.compile(
    r"MPos:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)",
    re.IGNORECASE,
)
WPOS_RE = re.compile(
    r"WPos:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)",
    re.IGNORECASE,
)
WCO_RE = re.compile(
    r"WCO:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)",
    re.IGNORECASE,
)
PN_RE = re.compile(r"Pn:([A-Z]+)", re.IGNORECASE)

# Safe default: use post-homing/backoff position as calibration start.
# You can override with --start-x/--start-y if needed.
DEFAULT_START_X = None
DEFAULT_START_Y = None


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
    # Prefer direct WPos field if present.
    m = WPOS_RE.search(status_line)
    if m:
        return tuple(float(m.group(i)) for i in range(1, 5))

    # Fallback: derive WPos from MPos and WCO (WPos = MPos - WCO).
    mpos = parse_mpos(status_line)
    wco = parse_wco(status_line)
    if mpos and wco:
        return tuple(mpos[i] - wco[i] for i in range(4))
    return None


def parse_state(status_line: str) -> str | None:
    if not status_line.startswith("<") or "|" not in status_line:
        return None
    return status_line[1:].split("|", 1)[0]


def parse_limits(status_line: str) -> set[str]:
    m = PN_RE.search(status_line)
    if not m:
        return set()
    return set(m.group(1).upper())


def sync_soft_wco_from_status(state: dict, status_line: str) -> None:
    wco = parse_wco(status_line)
    if wco is not None:
        state["soft_wco"] = wco


def get_wpos_with_fallback(state: dict, status_line: str) -> tuple[float, float, float, float] | None:
    wpos = parse_wpos(status_line)
    if wpos is not None:
        return wpos

    mpos = parse_mpos(status_line)
    if mpos is None:
        return None

    soft_wco = state.get("soft_wco")
    if soft_wco is None:
        # If WCO is unavailable, assume current coordinates are already work coords.
        return mpos
    return tuple(mpos[i] - soft_wco[i] for i in range(4))


def wait_for_idle(ser: serial.Serial, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = read_status(ser)
        state = parse_state(last)
        if state == "Idle":
            return last
        if state and state.startswith("Alarm"):
            raise RuntimeError(f"Controller alarm state: {last}")
        time.sleep(0.06)
    raise TimeoutError(f"Timeout waiting for Idle. Last status: {last}")


def move_abs(
    ser: serial.Serial,
    x: float | None = None,
    y: float | None = None,
    feed: float = 200.0,
    idle_timeout: float = 20.0,
) -> None:
    parts = []
    if x is not None:
        parts.append(f"X{x:.3f}")
    if y is not None:
        parts.append(f"Y{y:.3f}")
    if not parts:
        return

    send_command(ser, "G90", 1.0)
    send_command(ser, "G1 " + " ".join(parts) + f" F{feed:.1f}", 4.0)
    wait_for_idle(ser, timeout=idle_timeout)


def move_rel(
    ser: serial.Serial,
    axis: str,
    delta: float,
    feed: float,
    idle_timeout: float = 10.0,
) -> None:
    send_command(ser, "G91", 1.0)
    send_command(ser, f"G1 {axis}{delta:.3f} F{feed:.1f}", 4.0)
    send_command(ser, "G90", 1.0)
    wait_for_idle(ser, timeout=idle_timeout)


def release_axis_limit(
    ser: serial.Serial,
    axis: str,
    step: float,
    max_steps: int,
    feed: float,
) -> bool:
    axis = axis.upper()
    st = read_status(ser)
    if axis not in parse_limits(st):
        return True

    print(f"Axis {axis} limit is active, trying to release...")
    for direction in (1.0, -1.0):
        for _ in range(max_steps):
            move_rel(ser, axis, direction * abs(step), feed, idle_timeout=10.0)
            st = read_status(ser)
            if axis not in parse_limits(st):
                print(f"Axis {axis} released.")
                return True
    return False


def auto_release_limits(ser: serial.Serial, args: argparse.Namespace) -> None:
    st = read_status(ser)
    limits = parse_limits(st)
    if not limits:
        return

    print(f"Active limits detected after move: {''.join(sorted(limits))}")
    ok_x = True
    ok_y = True
    if "X" in limits:
        ok_x = release_axis_limit(
            ser,
            axis="X",
            step=args.release_step_x,
            max_steps=args.release_max_steps,
            feed=args.release_feed,
        )
    if "Y" in limits:
        ok_y = release_axis_limit(
            ser,
            axis="Y",
            step=args.release_step_y,
            max_steps=args.release_max_steps,
            feed=args.release_feed,
        )

    st = read_status(ser)
    limits = parse_limits(st)
    if not ok_y or "Y" in limits:
        raise RuntimeError(
            "Could not release Y limit automatically. "
            "Tune --backoff-x/--backoff-y or --start-x/--start-y."
        )
    if not ok_x or "X" in limits:
        print("WARNING: X limit is still active after auto-release.")


def run_start_flow(ser: serial.Serial, args: argparse.Namespace, state: dict) -> None:
    print("\n=== START FLOW ===")
    print("1) RESET")
    if args.reset_ctrlx:
        ser.write(b"\x18")
        time.sleep(1.0)
        ser.reset_input_buffer()
    else:
        print("   skipped (--reset_ctrlx is off)")

    print("2) UNLOCK ($X)")
    send_command(ser, "$X", 2.0)
    send_command(ser, "G90", 1.0)

    print("3) LIMIT SENSOR LED (M120 P1)")
    if args.limit_led:
        send_command(ser, "M120 P1", 1.5)
    else:
        print("   skipped (--no-limit-led)")

    print("4) IRIS OPEN (M114 P1)")
    if args.iris_open:
        send_command(ser, "M114 P1", 1.5)
    else:
        print("   skipped (--no-iris-open)")

    print("5) HOMING ZOOM ($HX)")
    send_command(ser, "$HX", 3.0)
    wait_for_idle(ser, timeout=args.home_timeout)

    if args.home_focus:
        print("6) HOMING FOCUS ($HY)")
        send_command(ser, "$HY", 3.0)
        wait_for_idle(ser, timeout=args.home_timeout)
    else:
        print("6) HOMING FOCUS skipped (--no-home-focus)")

    print("7) BACKOFF")
    if abs(args.backoff_x) > 1e-9 or abs(args.backoff_y) > 1e-9:
        send_command(ser, "G91", 1.0)
        cmd_parts = ["G1"]
        if abs(args.backoff_x) > 1e-9:
            cmd_parts.append(f"X{args.backoff_x:.3f}")
        if abs(args.backoff_y) > 1e-9:
            cmd_parts.append(f"Y{args.backoff_y:.3f}")
        cmd_parts.append(f"F{args.backoff_feed:.1f}")
        send_command(ser, " ".join(cmd_parts), 3.0)
        send_command(ser, "G90", 1.0)
        wait_for_idle(ser, timeout=10.0)
    else:
        print("   skipped (backoff = 0,0)")

    if args.start_x is None and args.start_y is None:
        print("8) GOTO START skipped (using post-backoff position)")
    else:
        sx = "current" if args.start_x is None else f"{args.start_x:.3f}"
        sy = "current" if args.start_y is None else f"{args.start_y:.3f}"
        print(f"8) GOTO START X={sx} Y={sy}")
        move_abs(
            ser,
            x=args.start_x,
            y=args.start_y,
            feed=args.goto_feed,
            idle_timeout=20.0,
        )

    if args.auto_release_limits:
        print("8b) AUTO RELEASE LIMITS")
        auto_release_limits(ser, args)

    print("9) SET X0 Y0 (G92 X0 Y0)")
    send_command(ser, "G92 X0 Y0", 1.0)

    print("Done. Calibration origin is now X0 Y0.")
    st = read_status(ser)
    sync_soft_wco_from_status(state, st)
    mpos = parse_mpos(st)
    if mpos is not None:
        state["soft_wco"] = mpos
    print(st)
    lim = parse_limits(st)
    if "Y" in lim:
        msg = (
            "Start flow ended with active Y limit (Pn:Y). "
            "Increase --backoff-y or adjust --start-y."
        )
        if args.strict_limits:
            raise RuntimeError(msg)
        print(f"WARNING: {msg}")
    elif "X" in lim:
        print("WARNING: Start flow ended on X limit (Pn:X). This is acceptable for wide endpoint.")


def build_zoom_table(tele_x: float, count: int) -> tuple[list[float], float]:
    if count < 2:
        raise ValueError("--points must be >= 2")
    step = tele_x / float(count - 1)
    table = [round(step * i, 6) for i in range(count)]
    return table, step


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def print_progress(data: dict) -> None:
    focus = data["focusY"]
    filled = sum(v is not None for v in focus)
    total = len(focus)
    print(f"Focus saved: {filled}/{total}")


def parse_index(cmd: str) -> int:
    parts = cmd.split()
    if len(parts) != 2:
        raise ValueError("index required")
    return int(parts[1])


def print_help(max_index: int) -> None:
    print("\nCommands:")
    print("  home          run full start flow")
    print("  zero          set current position as calibration zero (G92 X0 Y0)")
    print("  h             go to calibration origin (X0 Y0)")
    print("  s             read status")
    print("  a / d         zoom -/+ manual step")
    print("  j / l         focus -/+ manual step")
    print(f"  g i           goto point i (X + saved Y if exists)")
    print(f"  gx i          goto only zoom X for index i")
    print("  idx           show nearest index for current position")
    print(f"  w i           save current WPos X/Y into point i (0..{max_index})")
    print(f"  m i           same as 'w i' (compat)")
    print(f"  wy i          save only current WPos Y into point i")
    print("  run           guided pass (inside: j/l/a/d/s/unlimit, Enter=save)")
    print("  check         validate map (duplicates/jumps/missing)")
    print("  resetmap      restore zoomX from tele-x and clear all focusY")
    print("  unlimit       auto move away from active X/Y limits")
    print("  list          print table with current X/Y values")
    print("  save          save JSON")
    print("  q             quit\n")


def print_table(data: dict) -> None:
    print("idx\tX\t\tY\tL")
    for i, x in enumerate(data["zoomX"]):
        y = data["focusY"][i]
        ys = "-" if y is None else f"{y:.3f}"
        limits = ""
        if "limitXY" in data and i < len(data["limitXY"]):
            limits = data["limitXY"][i] or ""
        print(f"{i:02d}\t{x:.3f}\t{ys}\t{limits}")


def map_warnings(
    zoom_x: list[float],
    focus_y: list[float | None],
    focus_jump_warn: float,
) -> list[str]:
    warnings: list[str] = []
    if len(zoom_x) != len(focus_y):
        warnings.append("zoomX/focusY length mismatch")
        return warnings

    for i in range(1, len(zoom_x)):
        dx = zoom_x[i] - zoom_x[i - 1]
        if abs(dx) < 1e-9:
            warnings.append(f"duplicate zoomX at indexes {i-1}/{i}: {zoom_x[i]:.3f}")
        elif dx < 0:
            warnings.append(
                f"non-monotonic zoomX at indexes {i-1}/{i}: {zoom_x[i-1]:.3f} -> {zoom_x[i]:.3f}"
            )

    filled = sum(y is not None for y in focus_y)
    if filled < len(focus_y):
        warnings.append(f"focusY has missing points: {filled}/{len(focus_y)} filled")

    for i in range(1, len(focus_y)):
        y0 = focus_y[i - 1]
        y1 = focus_y[i]
        if y0 is None or y1 is None:
            continue
        dy = y1 - y0
        if abs(dy) > focus_jump_warn:
            warnings.append(
                f"large focus jump {i-1}->{i}: {y0:.3f} -> {y1:.3f} (dy={dy:.3f})"
            )
    return warnings


def print_map_check(data: dict, focus_jump_warn: float) -> None:
    warnings = map_warnings(data["zoomX"], data["focusY"], focus_jump_warn)
    if "limitXY" in data and isinstance(data["limitXY"], list):
        active = [(i, v) for i, v in enumerate(data["limitXY"]) if isinstance(v, str) and v]
        if active:
            warnings.append(f"points saved on limits: {', '.join(f'{i}:{v}' for i, v in active)}")
    if not warnings:
        print("Map check: OK")
        return
    print("Map check warnings:")
    for w in warnings:
        print("  -", w)


def maybe_autosave(args: argparse.Namespace, data: dict) -> None:
    if args.autosave_each:
        save_json(args.out, data)
        print(f"Autosaved: {args.out}")


def save_point_xy(data: dict, i: int, x: float, y: float, lim: set[str]) -> None:
    data["zoomX"][i] = round(x, 3)
    data["focusY"][i] = round(y, 3)
    data["limitXY"][i] = "".join(sorted(lim)) if lim else ""


def goto_zoom_index(ser: serial.Serial, target_x: float, args: argparse.Namespace) -> None:
    # Approach final X from one direction to reduce backlash effect.
    # Default preload comes from official L085D backlash values (~0.02).
    if args.x_preload > 0:
        pre_x = target_x - abs(args.x_preload)
        move_abs(ser, x=pre_x, feed=args.goto_feed, idle_timeout=20.0)
    move_abs(ser, x=target_x, feed=args.goto_feed, idle_timeout=20.0)


def goto_focus_index(ser: serial.Serial, target_y: float, args: argparse.Namespace) -> None:
    if args.y_preload > 0:
        pre_y = target_y - abs(args.y_preload)
        move_abs(ser, y=pre_y, feed=args.goto_feed, idle_timeout=20.0)
    move_abs(ser, y=target_y, feed=args.goto_feed, idle_timeout=20.0)


def nearest_index_by_x(target_x: float, zoom_x: list[float]) -> tuple[int, float]:
    best_i = 0
    best_d = abs(zoom_x[0] - target_x)
    for i in range(1, len(zoom_x)):
        d = abs(zoom_x[i] - target_x)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i, best_d


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Kurokesu C3 4K + L085/L085D calibration tool (25 zoom/focus points)"
    )
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out", default="zoom25_focusmap.json")

    ap.add_argument(
        "--tele-x",
        type=float,
        required=True,
        help="TELE position in calibration coordinates (after start flow + G92)",
    )
    ap.add_argument(
        "--points",
        type=int,
        default=25,
        help="number of calibration points (default: 25, indexes 0..24)",
    )

    # Start flow options
    ap.add_argument("--reset_ctrlx", action="store_true", help="send Ctrl-X at start")
    ap.add_argument(
        "--no-limit-led",
        action="store_true",
        help="skip M120 P1 in start flow",
    )
    ap.add_argument(
        "--no-iris-open",
        action="store_true",
        help="skip M114 P1 in start flow",
    )
    ap.add_argument(
        "--no-home-focus",
        action="store_true",
        help="run only $HX (skip $HY)",
    )
    ap.add_argument("--home-timeout", type=float, default=25.0)

    ap.add_argument("--backoff-x", type=float, default=1.0)
    ap.add_argument("--backoff-y", type=float, default=0.5)
    ap.add_argument("--backoff-feed", type=float, default=120.0)

    ap.add_argument(
        "--start-x",
        type=float,
        default=DEFAULT_START_X,
        help="optional absolute X start after backoff; default: keep current",
    )
    ap.add_argument(
        "--start-y",
        type=float,
        default=DEFAULT_START_Y,
        help="optional absolute Y start after backoff; default: keep current",
    )
    ap.add_argument("--goto-feed", type=float, default=200.0)
    ap.add_argument(
        "--x-preload",
        type=float,
        default=0.02,
        help="preload before final X approach to reduce backlash",
    )
    ap.add_argument(
        "--y-preload",
        type=float,
        default=0.02,
        help="preload before final Y approach to reduce backlash",
    )

    # Manual controls
    ap.add_argument("--dz", type=float, default=0.25, help="manual zoom delta")
    ap.add_argument("--df", type=float, default=0.15, help="manual focus delta")
    ap.add_argument("--feed-zoom", type=float, default=120.0)
    ap.add_argument("--feed-focus", type=float, default=120.0)
    ap.add_argument(
        "--focus-jump-warn",
        type=float,
        default=1.0,
        help="warn threshold for |focusY[i]-focusY[i-1]|",
    )
    ap.add_argument(
        "--allow-edit-zoomx",
        action="store_true",
        help="silence legacy warning for command 'm i' (which now behaves like 'w i')",
    )
    ap.add_argument("--autosave-each", dest="autosave_each", action="store_true", default=True)
    ap.add_argument("--no-autosave-each", dest="autosave_each", action="store_false")
    ap.add_argument("--auto-release-limits", dest="auto_release_limits", action="store_true", default=True)
    ap.add_argument("--no-auto-release-limits", dest="auto_release_limits", action="store_false")
    ap.add_argument("--release-step-x", type=float, default=0.2)
    ap.add_argument("--release-step-y", type=float, default=0.2)
    ap.add_argument("--release-max-steps", type=int, default=40)
    ap.add_argument("--release-feed", type=float, default=80.0)
    ap.add_argument(
        "--strict-limits",
        dest="strict_limits",
        action="store_true",
        default=True,
        help="refuse save/home when Pn:X/Y is active (default: ON)",
    )
    ap.add_argument(
        "--no-strict-limits",
        dest="strict_limits",
        action="store_false",
        help="allow save/home when Pn:X/Y is active (not recommended)",
    )
    ap.add_argument(
        "--allow-zero-on-limit",
        action="store_true",
        help="allow command 'zero' even when Pn:X/Y active (not recommended)",
    )

    args = ap.parse_args()
    args.limit_led = not args.no_limit_led
    args.iris_open = not args.no_iris_open
    args.home_focus = not args.no_home_focus

    zoom_x, zoom_step = build_zoom_table(args.tele_x, args.points)
    base_zoom_x = list(zoom_x)
    focus_y = [None] * args.points
    limit_xy = [""] * args.points

    data = {
        "meta": {
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "points": args.points,
            "tele_x": args.tele_x,
            "zoom_step": zoom_step,
            "coord_space": "wpos",
            "start_machine_xy": {"x": args.start_x, "y": args.start_y},
            "backoff_xy": {"x": args.backoff_x, "y": args.backoff_y},
            "x_preload": args.x_preload,
            "notes": (
                "Flow: RESET -> UNLOCK -> IRIS OPEN -> HOMING ZOOM -> BACKOFF -> "
                "GOTO START -> SET X0 Y0"
            ),
            "official_sdk_refs": [
                "SCE2-SDK/02_console_demo/L086.py",
                "SCE2-SDK/03_lens_tester_gui/main.py",
                "SCE2-SDK/03_lens_tester_gui/lenses/L085.json",
            ],
        },
        "zoomX": zoom_x,
        "focusY": focus_y,
        "limitXY": limit_xy,
    }

    max_index = args.points - 1

    with open_serial(args.port, args.baud) as ser:
        state = {"soft_wco": None}
        print_help(max_index)
        print_progress(data)
        print(
            f"x_preload={args.x_preload:.3f} y_preload={args.y_preload:.3f} "
            f"autosave_each={args.autosave_each}"
        )
        print_map_check(data, args.focus_jump_warn)

        homed = False
        while True:
            cmd = input("> ").strip().lower()
            if not cmd:
                continue
            if cmd == "st":
                cmd = "s"

            if cmd == "q":
                break

            if cmd == "home":
                try:
                    run_start_flow(ser, args, state)
                    homed = True
                except Exception as exc:
                    homed = False
                    print(f"HOME FAILED: {exc}")
                continue

            if cmd == "zero":
                if not homed:
                    print("Run 'home' first.")
                    continue
                st = read_status(ser)
                lim = parse_limits(st)
                if ("X" in lim or "Y" in lim) and not args.allow_zero_on_limit:
                    print(
                        "Cannot set zero while Pn:X/Y is active. "
                        "Use 'unlimit' or move off endstop first."
                    )
                    continue
                send_command(ser, "G92 X0 Y0", 1.0)
                print("Current position set as X0 Y0.")
                st = read_status(ser)
                sync_soft_wco_from_status(state, st)
                mpos = parse_mpos(st)
                if mpos is not None:
                    state["soft_wco"] = mpos
                print(st)
                continue

            if cmd == "h":
                if not homed:
                    print("Run 'home' first.")
                    continue
                move_abs(ser, x=0.0, y=0.0, feed=args.goto_feed, idle_timeout=20.0)
                st = read_status(ser)
                sync_soft_wco_from_status(state, st)
                print("At calibration origin:", st)
                continue

            if cmd == "s":
                st = read_status(ser)
                sync_soft_wco_from_status(state, st)
                print(st)
                mpos = parse_mpos(st)
                wpos = get_wpos_with_fallback(state, st)
                if wpos:
                    print(f"WPos X={wpos[0]:.3f} Y={wpos[1]:.3f}")
                if mpos:
                    print(f"MPos X={mpos[0]:.3f} Y={mpos[1]:.3f}")
                lim = parse_limits(st)
                if lim:
                    print(f"LIMIT ACTIVE: {''.join(sorted(lim))}")
                continue

            if cmd == "unlimit":
                if not homed:
                    print("Run 'home' first.")
                    continue
                try:
                    auto_release_limits(ser, args)
                    st = read_status(ser)
                    sync_soft_wco_from_status(state, st)
                    print("Limit release done:", st)
                except Exception as exc:
                    print(f"UNLIMIT FAILED: {exc}")
                continue

            if cmd == "a":
                move_rel(ser, "X", -args.dz, args.feed_zoom)
                continue
            if cmd == "d":
                move_rel(ser, "X", +args.dz, args.feed_zoom)
                continue
            if cmd == "j":
                move_rel(ser, "Y", -args.df, args.feed_focus)
                continue
            if cmd == "l":
                move_rel(ser, "Y", +args.df, args.feed_focus)
                continue

            if cmd.startswith("g "):
                if not homed:
                    print("Run 'home' first.")
                    continue
                try:
                    i = parse_index(cmd)
                    if i < 0 or i > max_index:
                        raise ValueError("index out of range")
                except ValueError:
                    print(f"Use: g 0..{max_index}")
                    continue
                goto_zoom_index(ser, data["zoomX"][i], args)
                y = data["focusY"][i]
                if y is not None:
                    goto_focus_index(ser, y, args)
                    print(f"Goto point {i}: X={data['zoomX'][i]:.3f} Y={y:.3f}")
                else:
                    print(f"Goto zoom {i}: X={data['zoomX'][i]:.3f} (Y not saved)")
                st = read_status(ser)
                sync_soft_wco_from_status(state, st)
                print(st)
                lim = parse_limits(st)
                if lim:
                    print(
                        f"WARNING: active limit Pn:{''.join(sorted(lim))}. "
                        "Use 'unlimit', then refocus and save."
                    )
                continue

            if cmd.startswith("gx "):
                if not homed:
                    print("Run 'home' first.")
                    continue
                try:
                    i = parse_index(cmd)
                    if i < 0 or i > max_index:
                        raise ValueError("index out of range")
                except ValueError:
                    print(f"Use: gx 0..{max_index}")
                    continue
                goto_zoom_index(ser, data["zoomX"][i], args)
                print(f"Goto zoom-only {i}: X={data['zoomX'][i]:.3f}")
                st = read_status(ser)
                sync_soft_wco_from_status(state, st)
                print(st)
                continue

            if cmd == "idx":
                st = read_status(ser)
                sync_soft_wco_from_status(state, st)
                pos = get_wpos_with_fallback(state, st)
                if not pos:
                    print("Cannot determine current index: no position in status")
                    continue
                i, dx = nearest_index_by_x(pos[0], data["zoomX"])
                y_saved = data["focusY"][i]
                y_saved_text = "-" if y_saved is None else f"{y_saved:.3f}"
                print(
                    f"Current WPos X={pos[0]:.3f} Y={pos[1]:.3f} -> nearest idx={i} "
                    f"(targetX={data['zoomX'][i]:.3f}, dX={dx:.3f}, savedY={y_saved_text})"
                )
                continue

            if cmd.startswith("w "):
                if not homed:
                    print("Run 'home' first.")
                    continue
                try:
                    i = parse_index(cmd)
                    if i < 0 or i > max_index:
                        raise ValueError("index out of range")
                except ValueError:
                    print(f"Use: w 0..{max_index}")
                    continue
                st = read_status(ser)
                sync_soft_wco_from_status(state, st)
                pos = get_wpos_with_fallback(state, st)
                if not pos:
                    print("Cannot parse WPos from status.")
                    continue
                lim = parse_limits(st)
                if "Y" in lim and args.strict_limits:
                    print("Y limit is active (Pn:Y). Move away from endstop and retry. Not saved.")
                    continue
                save_point_xy(data, i, x=pos[0], y=pos[1], lim=lim)
                print(
                    f"Saved point[{i}] -> X={data['zoomX'][i]:.3f}, "
                    f"Y={data['focusY'][i]:.3f}"
                )
                if lim:
                    print(f"WARNING: point saved with active limit Pn:{''.join(sorted(lim))}")
                print_progress(data)
                maybe_autosave(args, data)
                continue

            if cmd.startswith("wy "):
                if not homed:
                    print("Run 'home' first.")
                    continue
                try:
                    i = parse_index(cmd)
                    if i < 0 or i > max_index:
                        raise ValueError("index out of range")
                except ValueError:
                    print(f"Use: wy 0..{max_index}")
                    continue
                st = read_status(ser)
                sync_soft_wco_from_status(state, st)
                pos = get_wpos_with_fallback(state, st)
                if not pos:
                    print("Cannot parse WPos from status.")
                    continue
                lim = parse_limits(st)
                if "Y" in lim and args.strict_limits:
                    print("Y limit is active (Pn:Y). Move away from endstop and retry. Not saved.")
                    continue
                data["focusY"][i] = round(pos[1], 3)
                data["limitXY"][i] = "".join(sorted(lim)) if lim else ""
                print(f"Saved focusY[{i}] = {data['focusY'][i]:.3f}")
                if lim:
                    print(f"WARNING: point saved with active limit Pn:{''.join(sorted(lim))}")
                print_progress(data)
                maybe_autosave(args, data)
                continue

            if cmd.startswith("m "):
                if not homed:
                    print("Run 'home' first.")
                    continue
                try:
                    i = parse_index(cmd)
                    if i < 0 or i > max_index:
                        raise ValueError("index out of range")
                except ValueError:
                    print(f"Use: m 0..{max_index}")
                    continue
                st = read_status(ser)
                sync_soft_wco_from_status(state, st)
                pos = get_wpos_with_fallback(state, st)
                if not pos:
                    print("Cannot parse WPos from status.")
                    continue
                lim = parse_limits(st)
                if "Y" in lim and args.strict_limits:
                    print(
                        "Y limit is active. Refusing to save while focus is on endstop. "
                        "Move away and retry."
                    )
                    continue
                if not args.allow_edit_zoomx:
                    print("Legacy note: 'm i' now behaves like 'w i'. Use --allow-edit-zoomx to silence.")
                save_point_xy(data, i, x=pos[0], y=pos[1], lim=lim)
                print(
                    f"Saved point[{i}] -> X={data['zoomX'][i]:.3f}, "
                    f"Y={data['focusY'][i]:.3f}"
                )
                if lim:
                    print(f"WARNING: point saved with active limit Pn:{''.join(sorted(lim))}")
                print_progress(data)
                maybe_autosave(args, data)
                continue

            if cmd == "run":
                if not homed:
                    print("Run 'home' first.")
                    continue
                print(
                    "Guided mode: Enter=save, skip=next, q=stop, "
                    "j/l=focus, a/d=zoom, s=status, unlimit"
                )
                stop_run = False
                for i in range(args.points):
                    goto_zoom_index(ser, data["zoomX"][i], args)
                    st = read_status(ser)
                    sync_soft_wco_from_status(state, st)
                    pos = get_wpos_with_fallback(state, st)
                    cur_x = None if not pos else pos[0]
                    cur_y = None if not pos else pos[1]
                    print(f"[{i:02d}] targetX={data['zoomX'][i]:.3f} currentX={cur_x} currentY={cur_y}")
                    while True:
                        ans = input("focus now -> Enter/skip/q/j/l/a/d/s/unlimit: ").strip().lower()
                        if ans in ("", "save"):
                            st = read_status(ser)
                            sync_soft_wco_from_status(state, st)
                            pos = get_wpos_with_fallback(state, st)
                            if not pos:
                                print("Cannot parse WPos, skipped.")
                                break
                            lim = parse_limits(st)
                            if "Y" in lim and args.strict_limits:
                                print("Pn:Y active at this point. Not saved; move away from limit and retry.")
                                continue
                            save_point_xy(data, i, x=pos[0], y=pos[1], lim=lim)
                            print(
                                f"Saved point[{i}] -> X={data['zoomX'][i]:.3f}, "
                                f"Y={data['focusY'][i]:.3f}"
                            )
                            if lim:
                                print(f"WARNING: point saved with active limit Pn:{''.join(sorted(lim))}")
                            print_progress(data)
                            maybe_autosave(args, data)
                            break
                        if ans == "skip":
                            print(f"Skipped point[{i}].")
                            break
                        if ans == "q":
                            stop_run = True
                            break
                        if ans == "j":
                            move_rel(ser, "Y", -args.df, args.feed_focus)
                        elif ans == "l":
                            move_rel(ser, "Y", +args.df, args.feed_focus)
                        elif ans == "a":
                            move_rel(ser, "X", -args.dz, args.feed_zoom)
                        elif ans == "d":
                            move_rel(ser, "X", +args.dz, args.feed_zoom)
                        elif ans in ("s", "st"):
                            st = read_status(ser)
                            sync_soft_wco_from_status(state, st)
                            pos = get_wpos_with_fallback(state, st)
                            print(st)
                            if pos:
                                print(f"WPos X={pos[0]:.3f} Y={pos[1]:.3f}")
                            lim = parse_limits(st)
                            if lim:
                                print(f"LIMIT ACTIVE: {''.join(sorted(lim))}")
                            continue
                        elif ans == "unlimit":
                            try:
                                auto_release_limits(ser, args)
                            except Exception as exc:
                                print(f"UNLIMIT FAILED: {exc}")
                            continue
                        else:
                            print("Use Enter/save, skip, q, j/l, a/d, s, unlimit.")
                            continue

                        st = read_status(ser)
                        sync_soft_wco_from_status(state, st)
                        pos = get_wpos_with_fallback(state, st)
                        lim = parse_limits(st)
                        if pos:
                            print(f"Now WPos X={pos[0]:.3f} Y={pos[1]:.3f}")
                        if lim:
                            print(f"LIMIT ACTIVE: {''.join(sorted(lim))}")
                    if stop_run:
                        print("Guided mode stopped.")
                        break
                print_progress(data)
                print_map_check(data, args.focus_jump_warn)
                continue

            if cmd == "check":
                print_map_check(data, args.focus_jump_warn)
                continue

            if cmd == "resetmap":
                data["zoomX"] = list(base_zoom_x)
                data["focusY"] = [None] * args.points
                data["limitXY"] = [""] * args.points
                print("Map reset: zoomX restored from tele-x, focusY cleared.")
                print_progress(data)
                maybe_autosave(args, data)
                continue

            if cmd == "list":
                print_table(data)
                continue

            if cmd == "save":
                save_json(args.out, data)
                print(f"Saved: {args.out}")
                continue

            print_help(max_index)

    save_json(args.out, data)
    print(f"Autosaved: {args.out}")


if __name__ == "__main__":
    main()
