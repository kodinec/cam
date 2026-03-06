import argparse
import json
import os
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


def sync_soft_wco_from_status(runtime: dict, status_line: str) -> None:
    wco = parse_wco(status_line)
    if wco is not None:
        runtime["soft_wco"] = wco


def get_wpos_with_fallback(runtime: dict, status_line: str) -> tuple[float, float, float, float] | None:
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


def get_pos_for_map(runtime: dict, status_line: str, map_coords: str) -> tuple[float, float, float, float] | None:
    if map_coords == "mpos":
        return parse_mpos(status_line)
    return get_wpos_with_fallback(runtime, status_line)


def print_live_status(runtime: dict, status_line: str, *, show_raw: bool = True) -> tuple[float, float] | None:
    sync_soft_wco_from_status(runtime, status_line)
    mpos = parse_mpos(status_line)
    wpos = get_wpos_with_fallback(runtime, status_line)
    if show_raw:
        print(status_line)
    if wpos is not None:
        print(f"WPos X={wpos[0]:.3f} Y={wpos[1]:.3f}")
    if mpos is not None:
        print(f"MPos X={mpos[0]:.3f} Y={mpos[1]:.3f}")
    lim = parse_limits(status_line)
    if lim:
        print(f"LIMIT ACTIVE: {''.join(sorted(lim))}")
    if wpos is not None:
        return (wpos[0], wpos[1])
    if mpos is not None:
        return (mpos[0], mpos[1])
    return None


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


def load_map(path: str) -> tuple[list[float], list[float | None], list[str], dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "zoomX" not in data or "focusY" not in data:
        raise ValueError("Map JSON must contain zoomX and focusY")

    zoom_x = data["zoomX"]
    focus_y = data["focusY"]
    if not isinstance(zoom_x, list) or not isinstance(focus_y, list):
        raise ValueError("zoomX/focusY must be arrays")
    if len(zoom_x) == 0 or len(zoom_x) != len(focus_y):
        raise ValueError("zoomX/focusY length mismatch or empty")

    clean_zoom: list[float] = []
    clean_focus: list[float | None] = []
    clean_limits: list[str] = []

    for i, x in enumerate(zoom_x):
        try:
            clean_zoom.append(float(x))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"zoomX[{i}] is not numeric: {x}") from exc

    for i, y in enumerate(focus_y):
        if y is None:
            clean_focus.append(None)
            continue
        try:
            clean_focus.append(float(y))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"focusY[{i}] is not numeric/null: {y}") from exc

    raw_limits = data.get("limitXY")
    if isinstance(raw_limits, list) and len(raw_limits) == len(clean_zoom):
        for i, v in enumerate(raw_limits):
            if v is None:
                clean_limits.append("")
                continue
            if not isinstance(v, str):
                raise ValueError(f"limitXY[{i}] must be string/null")
            clean_limits.append(v.strip().upper())
    else:
        clean_limits = [""] * len(clean_zoom)

    meta = data.get("meta", {})
    return clean_zoom, clean_focus, clean_limits, meta


def save_map(
    path: str,
    zoom_x: list[float],
    focus_y: list[float | None],
    limit_xy: list[str],
    meta: dict,
) -> None:
    payload = {
        "meta": dict(meta),
        "zoomX": [round(float(x), 3) for x in zoom_x],
        "focusY": [None if y is None else round(float(y), 3) for y in focus_y],
        "limitXY": [str(v).upper() if isinstance(v, str) else "" for v in limit_xy],
    }
    payload["meta"]["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def nearest_index(zoom_x: list[float], current_x: float) -> int:
    best_i = 0
    best_d = abs(zoom_x[0] - current_x)
    for i in range(1, len(zoom_x)):
        d = abs(zoom_x[i] - current_x)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def map_warnings(zoom_x: list[float], focus_y: list[float | None], limit_xy: list[str]) -> list[str]:
    warnings: list[str] = []
    if len(zoom_x) != len(focus_y):
        warnings.append("zoomX/focusY length mismatch")
        return warnings

    for i in range(1, len(zoom_x)):
        if abs(zoom_x[i] - zoom_x[i - 1]) < 1e-9:
            warnings.append(f"duplicate zoomX at indexes {i-1}/{i}: {zoom_x[i]:.3f}")

    for i in range(1, len(focus_y)):
        y0 = focus_y[i - 1]
        y1 = focus_y[i]
        if y0 is None or y1 is None:
            continue
        if abs(y1 - y0) > 1.0:
            warnings.append(
                f"large focus jump at {i-1}->{i}: {y0:.3f} -> {y1:.3f} (dy={y1-y0:.3f})"
            )
    bad_limits = [(i, v) for i, v in enumerate(limit_xy) if v]
    if bad_limits:
        warnings.append(
            "points saved with active limits: "
            + ", ".join(f"{i}:{v}" for i, v in bad_limits)
        )
    return warnings


def load_state(path: str) -> dict | None:
    if not path:
        return None
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def save_state(
    path: str,
    map_path: str,
    map_coords: str,
    current_idx: int,
    focus_offset: float,
    apply_focus: bool,
) -> None:
    if not path:
        return
    state = {
        "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "map": map_path,
        "map_coords": map_coords,
        "index": current_idx,
        "focus_offset": round(float(focus_offset), 6),
        "apply_focus": bool(apply_focus),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def to_optional_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def interpolate_missing_focus(focus_y: list[float | None]) -> tuple[list[float | None], int]:
    out = list(focus_y)
    n = len(out)
    filled = 0
    for i, y in enumerate(out):
        if y is not None:
            continue
        left = i - 1
        while left >= 0 and out[left] is None:
            left -= 1
        right = i + 1
        while right < n and out[right] is None:
            right += 1

        if left >= 0 and right < n and out[left] is not None and out[right] is not None:
            t = (i - left) / float(right - left)
            out[i] = float(out[left]) + (float(out[right]) - float(out[left])) * t
            filled += 1
        elif left >= 0 and out[left] is not None:
            out[i] = float(out[left])
            filled += 1
        elif right < n and out[right] is not None:
            out[i] = float(out[right])
            filled += 1
    return out, filled


def move_xy(
    ser: serial.Serial,
    x: float | None,
    y: float | None,
    feed: float,
    timeout: float = 20.0,
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
    if not pos:
        raise RuntimeError(f"Cannot parse MPos before move. Status: {st}")

    dx = None if target_x is None else target_x - pos[0]
    dy = None if target_y is None else target_y - pos[1]
    if dx is None and dy is None:
        return

    cmd_parts = ["G1"]
    if dx is not None:
        cmd_parts.append(f"X{dx:.3f}")
    if dy is not None:
        cmd_parts.append(f"Y{dy:.3f}")
    cmd_parts.append(f"F{feed:.1f}")

    send_command(ser, "G91", 1.0)
    send_command(ser, " ".join(cmd_parts), 4.0)
    send_command(ser, "G90", 1.0)
    wait_for_idle(ser, timeout=timeout)


def move_rel(
    ser: serial.Serial,
    axis: str,
    delta: float,
    feed: float,
    timeout: float = 10.0,
) -> None:
    send_command(ser, "G91", 1.0)
    send_command(ser, f"G1 {axis}{delta:.3f} F{feed:.1f}", 4.0)
    send_command(ser, "G90", 1.0)
    wait_for_idle(ser, timeout=timeout)


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
            move_rel(ser, axis, direction * abs(step), feed, timeout=10.0)
            st = read_status(ser)
            if axis not in parse_limits(st):
                print(f"Axis {axis} released.")
                return True
    return False


def auto_release_limits(
    ser: serial.Serial,
    step_x: float,
    step_y: float,
    max_steps: int,
    feed: float,
) -> None:
    st = read_status(ser)
    limits = parse_limits(st)
    if not limits:
        return

    print(f"Active limits detected after move: {''.join(sorted(limits))}")
    ok_x = True
    ok_y = True
    if "X" in limits:
        ok_x = release_axis_limit(ser, axis="X", step=step_x, max_steps=max_steps, feed=feed)
    if "Y" in limits:
        ok_y = release_axis_limit(ser, axis="Y", step=step_y, max_steps=max_steps, feed=feed)

    st = read_status(ser)
    limits = parse_limits(st)
    if not ok_y or "Y" in limits:
        raise RuntimeError(
            "Could not release Y limit automatically. "
            "Tune --backoff-x/--backoff-y or --start-x/--start-y."
        )
    if not ok_x or "X" in limits:
        print("WARNING: X limit is still active after auto-release.")


def approach_x_mpos(
    ser: serial.Serial,
    target_x: float,
    feed: float,
    x_preload: float,
    x_min: float | None,
    timeout: float = 20.0,
) -> None:
    if x_preload <= 0:
        move_xy_to_mpos(ser, target_x=target_x, target_y=None, feed=feed, timeout=timeout)
        return

    pre_x = target_x - abs(x_preload)
    if x_min is not None and pre_x < x_min:
        pre_x = x_min

    move_xy_to_mpos(ser, target_x=pre_x, target_y=None, feed=feed, timeout=timeout)
    move_xy_to_mpos(ser, target_x=target_x, target_y=None, feed=feed, timeout=timeout)


def approach_x_wpos(
    ser: serial.Serial,
    target_x: float,
    feed: float,
    x_preload: float,
    x_min: float | None,
    timeout: float = 20.0,
) -> None:
    if x_preload <= 0:
        move_xy(ser, x=target_x, y=None, feed=feed, timeout=timeout)
        return

    pre_x = target_x - abs(x_preload)
    if x_min is not None and pre_x < x_min:
        pre_x = x_min

    move_xy(ser, x=pre_x, y=None, feed=feed, timeout=timeout)
    move_xy(ser, x=target_x, y=None, feed=feed, timeout=timeout)


def run_start_flow(
    ser: serial.Serial,
    reset_first: bool,
    do_iris_open: bool,
    do_limit_led: bool,
    do_home_focus: bool,
    home_timeout: float,
    backoff_x: float,
    backoff_y: float,
    backoff_feed: float,
    start_x: float | None,
    start_y: float | None,
    goto_feed: float,
    auto_release_after_start: bool,
    release_step_x: float,
    release_step_y: float,
    release_max_steps: int,
    release_feed: float,
    strict_limits: bool,
) -> None:
    print("\n=== START FLOW ===")
    print("1) RESET")
    if reset_first:
        ser.write(b"\x18")
        time.sleep(1.0)
        ser.reset_input_buffer()
    else:
        print("   skipped")

    print("2) UNLOCK ($X)")
    send_command(ser, "$X", 2.0)
    send_command(ser, "G90", 1.0)

    if do_limit_led:
        print("3) LIMIT LED ON (M120 P1)")
        send_command(ser, "M120 P1", 1.5)
    else:
        print("3) LIMIT LED skipped")

    if do_iris_open:
        print("4) IRIS OPEN (M114 P1)")
        send_command(ser, "M114 P1", 1.5)
    else:
        print("4) IRIS OPEN skipped")

    print("5) HOME ZOOM ($HX)")
    send_command(ser, "$HX", 3.0)
    wait_for_idle(ser, timeout=home_timeout)

    if do_home_focus:
        print("6) HOME FOCUS ($HY)")
        send_command(ser, "$HY", 3.0)
        wait_for_idle(ser, timeout=home_timeout)
    else:
        print("6) HOME FOCUS skipped")

    print("7) BACKOFF")
    if abs(backoff_x) > 1e-9 or abs(backoff_y) > 1e-9:
        send_command(ser, "G91", 1.0)
        cmd = ["G1"]
        if abs(backoff_x) > 1e-9:
            cmd.append(f"X{backoff_x:.3f}")
        if abs(backoff_y) > 1e-9:
            cmd.append(f"Y{backoff_y:.3f}")
        cmd.append(f"F{backoff_feed:.1f}")
        send_command(ser, " ".join(cmd), 3.0)
        send_command(ser, "G90", 1.0)
        wait_for_idle(ser, timeout=10.0)
    else:
        print("   skipped")

    if start_x is None and start_y is None:
        print("8) GOTO START skipped (using post-backoff position)")
    else:
        sx = "current" if start_x is None else f"{start_x:.3f}"
        sy = "current" if start_y is None else f"{start_y:.3f}"
        print(f"8) GOTO START X={sx} Y={sy}")
        move_xy(ser, x=start_x, y=start_y, feed=goto_feed, timeout=20.0)

    if auto_release_after_start:
        print("8b) AUTO RELEASE LIMITS")
        auto_release_limits(
            ser,
            step_x=release_step_x,
            step_y=release_step_y,
            max_steps=release_max_steps,
            feed=release_feed,
        )

    print("9) SET X0 Y0 (G92 X0 Y0)")
    send_command(ser, "G92 X0 Y0", 1.0)
    st = read_status(ser)
    print(st)
    lim = parse_limits(st)
    if "Y" in lim:
        msg = (
            "Start flow ended with active Y limit (Pn:Y). "
            "Increase --backoff-y or adjust --start-y."
        )
        if strict_limits:
            raise RuntimeError(msg)
        print(f"WARNING: {msg}")
    elif "X" in lim:
        print("WARNING: Start flow ended on X limit (Pn:X). This is acceptable for wide endpoint.")


def goto_index(
    ser: serial.Serial,
    runtime: dict,
    idx: int,
    zoom_x: list[float],
    focus_y: list[float | None],
    limit_xy: list[str],
    apply_focus: bool,
    feed: float,
    map_coords: str,
    sequential_focus: bool,
    focus_settle_s: float,
    focus_offset: float,
    x_preload: float,
    x_min: float | None,
) -> None:
    x = zoom_x[idx]
    y_raw = focus_y[idx] if apply_focus else None
    lim_tag = ""
    if 0 <= idx < len(limit_xy):
        lim_tag = limit_xy[idx]
    if y_raw is not None and lim_tag:
        print(
            f"WARNING: idx={idx} in map was saved on limit Pn:{lim_tag}; "
            "focus move skipped for safety."
        )
        y_raw = None
    y = None if y_raw is None else y_raw + focus_offset

    if map_coords == "mpos":
        if sequential_focus and y is not None:
            approach_x_mpos(ser, target_x=x, feed=feed, x_preload=x_preload, x_min=x_min, timeout=20.0)
            if focus_settle_s > 0:
                time.sleep(focus_settle_s)
            move_xy_to_mpos(ser, target_x=None, target_y=y, feed=feed, timeout=20.0)
        elif sequential_focus and y is None:
            approach_x_mpos(ser, target_x=x, feed=feed, x_preload=x_preload, x_min=x_min, timeout=20.0)
        else:
            move_xy_to_mpos(ser, target_x=x, target_y=y, feed=feed, timeout=20.0)
    else:
        if sequential_focus and y is not None:
            approach_x_wpos(ser, target_x=x, feed=feed, x_preload=x_preload, x_min=x_min, timeout=20.0)
            if focus_settle_s > 0:
                time.sleep(focus_settle_s)
            move_xy(ser, x=None, y=y, feed=feed, timeout=20.0)
        elif sequential_focus and y is None:
            approach_x_wpos(ser, target_x=x, feed=feed, x_preload=x_preload, x_min=x_min, timeout=20.0)
        else:
            move_xy(ser, x=x, y=y, feed=feed, timeout=20.0)

    if y is None:
        print(f"Moved -> idx={idx} X={x:.3f} (focus unchanged)")
    else:
        if abs(focus_offset) > 1e-9:
            print(
                f"Moved -> idx={idx} X={x:.3f} Y={y:.3f} "
                f"(base={y_raw:.3f}, offset={focus_offset:+.3f})"
            )
        else:
            print(f"Moved -> idx={idx} X={x:.3f} Y={y:.3f}")
    st = read_status(ser)
    print_live_status(runtime, st, show_raw=True)
    lim = parse_limits(st)
    if lim:
        print(
            f"WARNING: limit active Pn:{''.join(sorted(lim))}. "
            "This point is unstable; reduce focus (fo-) or recalibrate."
        )


def print_help(max_index: int) -> None:
    print("\nCommands:")
    print("  + | zoom+         one step zoom in")
    print("  - | zoom-         one step zoom out")
    print("  set i             goto zoom index i")
    print("  a / d             manual zoom -/+ jog")
    print("  j / l             manual focus -/+ jog")
    print("  w i               save current X/Y into map index i")
    print("  w                 save current X/Y into current index")
    print("  wy i              save current Y into map index i")
    print("  idx               show current index")
    print("  list              print all calibration points")
    print("  save              save map JSON now")
    print("  s                 status")
    print("  unlimit           auto-release active X/Y limits")
    print("  home              run full start flow and set X0 Y0")
    print("  focus on|off      toggle applying focusY with zoom moves")
    print("  fo+ / fo-         focus offset +/- 0.05")
    print("  fo N              set focus offset value, e.g. 'fo -0.20'")
    print("  fo                show current focus offset")
    print("  state             show runtime state file and current values")
    print("  q                 quit")
    print(f"Index range: 0..{max_index}\n")


def print_list(zoom_x: list[float], focus_y: list[float | None], limit_xy: list[str]) -> None:
    print("idx\tX\t\tY\tL")
    for i, x in enumerate(zoom_x):
        y = focus_y[i]
        y_text = "-" if y is None else f"{y:.3f}"
        lim = ""
        if i < len(limit_xy):
            lim = limit_xy[i] or ""
        print(f"{i:02d}\t{x:.3f}\t{y_text}\t{lim}")


def parse_set_command(cmd: str) -> int:
    parts = cmd.split()
    if len(parts) != 2:
        raise ValueError("usage: set <index>")
    return int(parts[1])


def parse_index_command(cmd: str, keyword: str) -> int:
    parts = cmd.split()
    if len(parts) != 2 or parts[0] != keyword:
        raise ValueError(f"usage: {keyword} <index>")
    return int(parts[1])


def main() -> None:
    ap = argparse.ArgumentParser(
        description="PTZ console for Kurokesu L085 calibration map (zoom +/- by index)"
    )
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--map", default="/Users/codinec/cam/zoom25_focusmap.json")
    ap.add_argument(
        "--map-coords",
        choices=["auto", "mpos", "wpos"],
        default="auto",
        help="coordinate space in map file (auto uses meta.coord_space if present)",
    )
    ap.add_argument("--feed", type=float, default=180.0)
    ap.add_argument("--jog-feed", type=float, default=120.0)
    ap.add_argument("--dz", type=float, default=0.25, help="manual zoom jog step")
    ap.add_argument("--df", type=float, default=0.15, help="manual focus jog step")
    ap.add_argument("--x-preload", type=float, default=None)
    ap.add_argument("--focus-offset", type=float, default=None)
    ap.add_argument("--focus-offset-step", type=float, default=0.05)
    ap.add_argument("--focus-settle-ms", type=int, default=120)
    ap.add_argument(
        "--no-sequential-focus",
        action="store_true",
        help="move X/Y together in one move (default is zoom then focus)",
    )
    ap.add_argument(
        "--no-interpolate-focus",
        action="store_true",
        help="keep null focus points as-is",
    )
    ap.add_argument("--start-index", type=int, default=None)
    ap.add_argument("--state", default="/Users/codinec/cam/ptz_state.json")
    ap.add_argument("--no-state", action="store_true", help="disable load/save runtime PTZ state")
    ap.add_argument("--autosave-map", dest="autosave_map", action="store_true", default=True)
    ap.add_argument("--no-autosave-map", dest="autosave_map", action="store_false")
    ap.add_argument("--no-reset", action="store_true", help="skip reset on connect")
    ap.add_argument(
        "--no-apply-focus",
        action="store_true",
        help="when moving zoom index, do not move focus Y",
    )

    # Start-flow options (for command 'home' and startup)
    ap.add_argument("--autohome", dest="autohome", action="store_true", default=True)
    ap.add_argument("--no-autohome", dest="autohome", action="store_false")
    ap.add_argument("--no-iris-open", action="store_true")
    ap.add_argument("--no-limit-led", action="store_true")
    ap.add_argument("--no-home-focus", action="store_true")
    ap.add_argument("--home-timeout", type=float, default=25.0)
    ap.add_argument("--backoff-x", type=float, default=1.0)
    ap.add_argument("--backoff-y", type=float, default=0.5)
    ap.add_argument("--backoff-feed", type=float, default=120.0)
    ap.add_argument("--start-x", type=float, default=None)
    ap.add_argument("--start-y", type=float, default=None)
    ap.add_argument("--goto-feed", type=float, default=200.0)
    ap.add_argument(
        "--auto-release-limits",
        dest="auto_release_limits",
        action="store_true",
        default=True,
    )
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
        help="strict limit checks (default: ON)",
    )
    ap.add_argument(
        "--no-strict-limits",
        dest="strict_limits",
        action="store_false",
        help="allow operation/save with active limits (not recommended)",
    )
    args = ap.parse_args()

    zoom_x, focus_y, limit_xy, meta = load_map(args.map)
    max_index = len(zoom_x) - 1

    if args.map_coords == "auto":
        map_coords = str(meta.get("coord_space", "mpos")).lower()
        if map_coords not in {"mpos", "wpos"}:
            map_coords = "mpos"
    else:
        map_coords = args.map_coords

    state_enabled = not args.no_state
    state_path = args.state if state_enabled else ""
    state_data = load_state(state_path) if state_enabled else None
    restored_index: int | None = None

    apply_focus = not args.no_apply_focus
    sequential_focus = not args.no_sequential_focus
    focus_settle_s = max(0.0, args.focus_settle_ms / 1000.0)
    focus_offset = 0.0 if args.focus_offset is None else args.focus_offset
    do_reset = not args.no_reset
    do_iris_open = not args.no_iris_open
    do_limit_led = not args.no_limit_led
    do_home_focus = not args.no_home_focus
    x_min = min(zoom_x) if zoom_x else None
    if args.x_preload is not None:
        x_preload = args.x_preload
    else:
        x_preload = float(meta.get("x_preload", 0.02))

    interp_filled = 0
    if not args.no_interpolate_focus:
        focus_y, interp_filled = interpolate_missing_focus(focus_y)

    if state_data and str(state_data.get("map", "")) == args.map:
        if args.start_index is None:
            raw_idx = state_data.get("index")
            if isinstance(raw_idx, int) and 0 <= raw_idx <= max_index:
                restored_index = raw_idx
        if args.focus_offset is None:
            restored_offset = to_optional_float(state_data.get("focus_offset"))
            if restored_offset is not None:
                focus_offset = restored_offset
        if not args.no_apply_focus and isinstance(state_data.get("apply_focus"), bool):
            apply_focus = bool(state_data["apply_focus"])

    start_x = args.start_x
    start_y = args.start_y
    if start_x is None or start_y is None:
        start_xy = meta.get("start_machine_xy", {})
        if not isinstance(start_xy, dict):
            start_xy = {}
        if start_x is None:
            start_x = to_optional_float(start_xy.get("x"))
        if start_y is None:
            start_y = to_optional_float(start_xy.get("y"))

    runtime = {"soft_wco": None}

    with open_serial(args.port, args.baud) as ser:
        if args.autohome:
            try:
                run_start_flow(
                    ser=ser,
                    reset_first=do_reset,
                    do_iris_open=do_iris_open,
                    do_limit_led=do_limit_led,
                    do_home_focus=do_home_focus,
                    home_timeout=args.home_timeout,
                    backoff_x=args.backoff_x,
                    backoff_y=args.backoff_y,
                    backoff_feed=args.backoff_feed,
                    start_x=start_x,
                    start_y=start_y,
                    goto_feed=args.goto_feed,
                    auto_release_after_start=args.auto_release_limits,
                    release_step_x=args.release_step_x,
                    release_step_y=args.release_step_y,
                    release_max_steps=args.release_max_steps,
                    release_feed=args.release_feed,
                    strict_limits=args.strict_limits,
                )
            except Exception as exc:
                raise RuntimeError(f"Autohome failed: {exc}") from exc
        else:
            if do_reset:
                ser.write(b"\x18")
                time.sleep(1.0)
                ser.reset_input_buffer()
            send_command(ser, "$X", 2.0)
            send_command(ser, "G90", 1.0)

        status_line = read_status(ser)
        sync_soft_wco_from_status(runtime, status_line)
        pos_for_map = get_pos_for_map(runtime, status_line, map_coords)

        if args.start_index is not None:
            if args.start_index < 0 or args.start_index > max_index:
                raise ValueError(f"--start-index must be 0..{max_index}")
            current_idx = args.start_index
        elif restored_index is not None:
            current_idx = restored_index
        elif pos_for_map:
            current_idx = nearest_index(zoom_x, pos_for_map[0])
        else:
            current_idx = 0

        print(f"Loaded map: {args.map}")
        print(f"Points: {len(zoom_x)} (index 0..{max_index})")
        print(f"Current index: {current_idx}")
        print(f"Apply focus: {apply_focus}")
        print(f"Sequential focus: {sequential_focus} (settle {args.focus_settle_ms} ms)")
        print(f"X preload: {x_preload:.3f}")
        print(f"Focus offset: {focus_offset:+.3f}")
        print(f"Map coords: {map_coords}")
        bad_limit_count = sum(1 for v in limit_xy if v)
        if bad_limit_count:
            print(f"Map limit flags: {bad_limit_count}/{len(limit_xy)} points were saved on endstop limits")
        if interp_filled > 0:
            print(f"Interpolated missing focus points: {interp_filled}")
        if state_enabled:
            print(f"State file: {state_path}")
            if restored_index is not None:
                print(f"State restored: index={restored_index}")
        print(f"Jog: dz={args.dz:.3f} df={args.df:.3f} jog_feed={args.jog_feed:.1f}")
        print(f"Map autosave: {args.autosave_map}")
        warnings = map_warnings(zoom_x, focus_y, limit_xy)
        if warnings:
            print("Map warnings:")
            for w in warnings:
                print("  -", w)
        print_help(max_index)

        def persist_state() -> None:
            if not state_enabled:
                return
            try:
                save_state(
                    path=state_path,
                    map_path=args.map,
                    map_coords=map_coords,
                    current_idx=current_idx,
                    focus_offset=focus_offset,
                    apply_focus=apply_focus,
                )
            except Exception as exc:
                print(f"WARNING: cannot save state: {exc}")

        def persist_map(*, reason: str = "") -> None:
            try:
                save_map(args.map, zoom_x, focus_y, limit_xy, meta)
                if reason:
                    print(f"Map saved ({reason}): {args.map}")
                else:
                    print(f"Map saved: {args.map}")
            except Exception as exc:
                print(f"WARNING: cannot save map: {exc}")

        def maybe_persist_map(*, reason: str = "") -> None:
            if args.autosave_map:
                persist_map(reason=reason)

        def show_status_and_sync_index(*, sync_index: bool = True) -> None:
            nonlocal current_idx
            st = read_status(ser)
            print_live_status(runtime, st, show_raw=True)
            if not sync_index:
                return
            pos_now = get_pos_for_map(runtime, st, map_coords)
            if pos_now is None:
                return
            nearest = nearest_index(zoom_x, pos_now[0])
            if nearest != current_idx:
                current_idx = nearest
                print(f"Nearest index -> {current_idx}")
                persist_state()

        persist_state()
        show_status_and_sync_index(sync_index=True)

        while True:
            cmd = input("> ").strip().lower()
            if not cmd:
                continue

            if cmd in {"q", "quit", "exit"}:
                break

            if cmd in {"+", "zoom+", "z+", "in"}:
                if current_idx >= max_index:
                    print("Already at max zoom index.")
                    continue
                current_idx += 1
                goto_index(
                    ser,
                    runtime,
                    current_idx,
                    zoom_x,
                    focus_y,
                    limit_xy,
                    apply_focus,
                    args.feed,
                    map_coords,
                    sequential_focus,
                    focus_settle_s,
                    focus_offset,
                    x_preload,
                    x_min,
                )
                persist_state()
                continue

            if cmd in {"-", "zoom-", "z-", "out"}:
                if current_idx <= 0:
                    print("Already at min zoom index.")
                    continue
                current_idx -= 1
                goto_index(
                    ser,
                    runtime,
                    current_idx,
                    zoom_x,
                    focus_y,
                    limit_xy,
                    apply_focus,
                    args.feed,
                    map_coords,
                    sequential_focus,
                    focus_settle_s,
                    focus_offset,
                    x_preload,
                    x_min,
                )
                persist_state()
                continue

            if cmd.startswith("set "):
                try:
                    idx = parse_set_command(cmd)
                except ValueError:
                    print(f"Use: set 0..{max_index}")
                    continue
                if idx < 0 or idx > max_index:
                    print(f"Use: set 0..{max_index}")
                    continue
                current_idx = idx
                goto_index(
                    ser,
                    runtime,
                    current_idx,
                    zoom_x,
                    focus_y,
                    limit_xy,
                    apply_focus,
                    args.feed,
                    map_coords,
                    sequential_focus,
                    focus_settle_s,
                    focus_offset,
                    x_preload,
                    x_min,
                )
                persist_state()
                continue

            if cmd == "a":
                move_rel(ser, "X", -abs(args.dz), args.jog_feed, timeout=10.0)
                show_status_and_sync_index(sync_index=True)
                continue

            if cmd == "d":
                move_rel(ser, "X", +abs(args.dz), args.jog_feed, timeout=10.0)
                show_status_and_sync_index(sync_index=True)
                continue

            if cmd == "j":
                move_rel(ser, "Y", -abs(args.df), args.jog_feed, timeout=10.0)
                show_status_and_sync_index(sync_index=False)
                continue

            if cmd == "l":
                move_rel(ser, "Y", +abs(args.df), args.jog_feed, timeout=10.0)
                show_status_and_sync_index(sync_index=False)
                continue

            if cmd == "unlimit":
                try:
                    auto_release_limits(
                        ser,
                        step_x=args.release_step_x,
                        step_y=args.release_step_y,
                        max_steps=args.release_max_steps,
                        feed=args.release_feed,
                    )
                    show_status_and_sync_index(sync_index=True)
                except Exception as exc:
                    print(f"UNLIMIT FAILED: {exc}")
                continue

            if cmd == "save":
                persist_map(reason="manual")
                continue

            if cmd == "w":
                cmd = f"w {current_idx}"

            if cmd.startswith("w "):
                try:
                    idx = parse_index_command(cmd, "w")
                except ValueError:
                    print(f"Use: w 0..{max_index}")
                    continue
                if idx < 0 or idx > max_index:
                    print(f"Use: w 0..{max_index}")
                    continue
                st = read_status(ser)
                sync_soft_wco_from_status(runtime, st)
                pos = get_pos_for_map(runtime, st, map_coords)
                if pos is None:
                    print("Cannot parse current position from status.")
                    continue
                lim = parse_limits(st)
                if "Y" in lim and args.strict_limits:
                    print("Y limit is active (Pn:Y). Not saved.")
                    print_live_status(runtime, st, show_raw=True)
                    continue
                zoom_x[idx] = round(pos[0], 3)
                focus_y[idx] = round(pos[1], 3)
                limit_xy[idx] = "".join(sorted(lim)) if lim else ""
                print(f"Saved point[{idx}] -> X={zoom_x[idx]:.3f} Y={focus_y[idx]:.3f}")
                if lim:
                    print(f"WARNING: point saved with active limit Pn:{''.join(sorted(lim))}")
                current_idx = idx
                maybe_persist_map(reason=f"w {idx}")
                persist_state()
                continue

            if cmd.startswith("wy "):
                try:
                    idx = parse_index_command(cmd, "wy")
                except ValueError:
                    print(f"Use: wy 0..{max_index}")
                    continue
                if idx < 0 or idx > max_index:
                    print(f"Use: wy 0..{max_index}")
                    continue
                st = read_status(ser)
                sync_soft_wco_from_status(runtime, st)
                pos = get_pos_for_map(runtime, st, map_coords)
                if pos is None:
                    print("Cannot parse current position from status.")
                    continue
                lim = parse_limits(st)
                if "Y" in lim and args.strict_limits:
                    print("Y limit is active (Pn:Y). Not saved.")
                    print_live_status(runtime, st, show_raw=True)
                    continue
                focus_y[idx] = round(pos[1], 3)
                limit_xy[idx] = "".join(sorted(lim)) if lim else ""
                print(f"Saved focusY[{idx}] -> {focus_y[idx]:.3f}")
                if lim:
                    print(f"WARNING: point saved with active limit Pn:{''.join(sorted(lim))}")
                maybe_persist_map(reason=f"wy {idx}")
                persist_state()
                continue

            if cmd == "idx":
                print(
                    f"index={current_idx} x={zoom_x[current_idx]:.3f} "
                    f"focus={'-' if focus_y[current_idx] is None else f'{focus_y[current_idx]:.3f}'}"
                )
                continue

            if cmd == "list":
                print_list(zoom_x, focus_y, limit_xy)
                continue

            if cmd in {"s", "status"}:
                show_status_and_sync_index(sync_index=True)
                continue

            if cmd == "home":
                try:
                    run_start_flow(
                        ser=ser,
                        reset_first=do_reset,
                        do_iris_open=do_iris_open,
                        do_limit_led=do_limit_led,
                        do_home_focus=do_home_focus,
                        home_timeout=args.home_timeout,
                        backoff_x=args.backoff_x,
                        backoff_y=args.backoff_y,
                        backoff_feed=args.backoff_feed,
                        start_x=start_x,
                        start_y=start_y,
                        goto_feed=args.goto_feed,
                        auto_release_after_start=args.auto_release_limits,
                        release_step_x=args.release_step_x,
                        release_step_y=args.release_step_y,
                        release_max_steps=args.release_max_steps,
                        release_feed=args.release_feed,
                        strict_limits=args.strict_limits,
                    )
                    current_idx = 0
                    print("Index reset to 0 after home flow.")
                    show_status_and_sync_index(sync_index=False)
                    persist_state()
                except Exception as exc:
                    print(f"HOME FAILED: {exc}")
                continue

            if cmd == "focus on":
                apply_focus = True
                print("Apply focus: ON")
                persist_state()
                continue

            if cmd == "focus off":
                apply_focus = False
                print("Apply focus: OFF")
                persist_state()
                continue

            if cmd == "fo+":
                focus_offset += args.focus_offset_step
                print(f"Focus offset: {focus_offset:+.3f}")
                persist_state()
                continue

            if cmd == "fo-":
                focus_offset -= args.focus_offset_step
                print(f"Focus offset: {focus_offset:+.3f}")
                persist_state()
                continue

            if cmd == "fo":
                print(f"Focus offset: {focus_offset:+.3f}")
                continue

            if cmd.startswith("fo "):
                parts = cmd.split()
                if len(parts) != 2:
                    print("Use: fo <value>, fo+, fo-")
                    continue
                try:
                    focus_offset = float(parts[1])
                except ValueError:
                    print("Use: fo <value>, e.g. fo -0.20")
                    continue
                print(f"Focus offset: {focus_offset:+.3f}")
                persist_state()
                continue

            if cmd == "state":
                print(
                    f"state={'on' if state_enabled else 'off'} "
                    f"path={state_path if state_enabled else '-'}"
                )
                print(
                    f"index={current_idx} focus_offset={focus_offset:+.3f} "
                    f"apply_focus={apply_focus}"
                )
                continue

            print_help(max_index)


if __name__ == "__main__":
    main()
