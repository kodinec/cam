import os
import re
import sys
import time

import serial


OK_RE = re.compile(r"^(ok|error:.*|alarm:.*)$", re.IGNORECASE)
PN_RE = re.compile(r"Pn:([A-Z]+)", re.IGNORECASE)


def env_str(key: str, default: str) -> str:
    v = os.getenv(key, "").strip()
    return v if v else default


def env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key, "").strip().lower()
    if v == "":
        return default
    return v in ("1", "true", "yes", "on")


def env_int(key: str, default: int) -> int:
    v = os.getenv(key, "").strip()
    if v == "":
        return default
    return int(v)


def env_float(key: str, default: float) -> float:
    v = os.getenv(key, "").strip()
    if v == "":
        return default
    return float(v)


def parse_limits(status_line: str) -> set[str]:
    m = PN_RE.search(status_line)
    if not m:
        return set()
    return set(m.group(1).upper())


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
        time.sleep(0.07)
    raise TimeoutError(f"Timeout waiting Idle. Last status: {last}")


def move_rel(ser: serial.Serial, axis: str, delta: float, feed: float, timeout: float = 10.0) -> None:
    send_command(ser, "G91", 1.0)
    send_command(ser, f"G1 {axis}{delta:.3f} F{feed:.1f}", 4.0)
    send_command(ser, "G90", 1.0)
    wait_for_idle(ser, timeout=timeout)


def move_abs(ser: serial.Serial, x: float, y: float, feed: float, timeout: float = 20.0) -> None:
    send_command(ser, "G90", 1.0)
    send_command(ser, f"G1 X{x:.3f} Y{y:.3f} F{feed:.1f}", 4.0)
    wait_for_idle(ser, timeout=timeout)


def release_axis_limit(ser: serial.Serial, axis: str, step: float, max_steps: int, feed: float) -> bool:
    st = read_status(ser)
    if axis not in parse_limits(st):
        return True
    print(f"axis {axis} limit active, releasing...")
    for direction in (1.0, -1.0):
        for _ in range(max_steps):
            move_rel(ser, axis, direction * abs(step), feed, timeout=10.0)
            st = read_status(ser)
            if axis not in parse_limits(st):
                print(f"axis {axis} released")
                return True
    return False


def auto_release_limits(ser: serial.Serial, step_x: float, step_y: float, max_steps: int, feed: float) -> None:
    st = read_status(ser)
    lim = parse_limits(st)
    if not lim:
        return
    print(f"active limits: {''.join(sorted(lim))}")
    ok_x = True
    ok_y = True
    if "X" in lim:
        ok_x = release_axis_limit(ser, "X", step_x, max_steps, feed)
    if "Y" in lim:
        ok_y = release_axis_limit(ser, "Y", step_y, max_steps, feed)
    st = read_status(ser)
    lim = parse_limits(st)
    if not ok_y or "Y" in lim:
        raise RuntimeError("could not release Y limit")
    if not ok_x or "X" in lim:
        print("warning: X limit still active")


def run_start_flow(ser: serial.Serial) -> None:
    reset = env_bool("PTZ_RESET", True)
    limit_led = env_bool("PTZ_LIMIT_LED", True)
    iris_open = env_bool("PTZ_IRIS_OPEN", True)

    home_timeout = env_float("PTZ_HOME_TIMEOUT", 25.0)
    backoff_x = env_float("PTZ_BACKOFF_X", 1.0)
    backoff_y = env_float("PTZ_BACKOFF_Y", 0.5)
    backoff_feed = env_float("PTZ_BACKOFF_FEED", 120.0)
    start_x = env_float("PTZ_START_X", 0.0)
    start_y = env_float("PTZ_START_Y", 0.0)
    goto_feed = env_float("PTZ_GOTO_FEED", 200.0)
    rel_step_x = env_float("PTZ_RELEASE_STEP_X", 0.2)
    rel_step_y = env_float("PTZ_RELEASE_STEP_Y", 0.2)
    rel_steps = env_int("PTZ_RELEASE_MAX_STEPS", 40)
    rel_feed = env_float("PTZ_RELEASE_FEED", 80.0)

    print("1) RESET")
    if reset:
        ser.write(b"\x18")
        time.sleep(1.0)
        ser.reset_input_buffer()
    else:
        print("   skipped")

    print("2) UNLOCK ($X)")
    send_command(ser, "$X", 2.0)
    send_command(ser, "G90", 1.0)

    if limit_led:
        print("3) LIMIT LED ON (M120 P1)")
        send_command(ser, "M120 P1", 1.5)
    else:
        print("3) LIMIT LED skipped")

    if iris_open:
        print("4) IRIS OPEN (M114 P1)")
        send_command(ser, "M114 P1", 1.5)
    else:
        print("4) IRIS OPEN skipped")

    print("5) HOME ZOOM ($HX)")
    send_command(ser, "$HX", 3.0)
    wait_for_idle(ser, timeout=home_timeout)

    print("6) HOME FOCUS ($HY)")
    send_command(ser, "$HY", 3.0)
    wait_for_idle(ser, timeout=home_timeout)

    print("7) BACKOFF")
    send_command(ser, "G91", 1.0)
    send_command(ser, f"G1 X{backoff_x:.3f} Y{backoff_y:.3f} F{backoff_feed:.1f}", 3.0)
    send_command(ser, "G90", 1.0)
    wait_for_idle(ser, timeout=10.0)

    print(f"8) GOTO START X={start_x:.3f} Y={start_y:.3f}")
    move_abs(ser, start_x, start_y, goto_feed, timeout=20.0)

    print("8b) AUTO RELEASE LIMITS")
    auto_release_limits(ser, rel_step_x, rel_step_y, rel_steps, rel_feed)

    print("9) SET X0 Y0 (G92 X0 Y0)")
    send_command(ser, "G92 X0 Y0", 1.0)


def resolve_serial_path() -> str:
    primary = env_str("PTZ_SERIAL", "/dev/ttyACM0")
    fallback = env_str("PTZ_SERIAL_FALLBACK", "")
    if os.path.exists(primary):
        return primary
    if fallback and os.path.exists(fallback):
        return fallback
    return primary


def run_once() -> None:
    baud = env_int("PTZ_BAUD", 115200)
    port = resolve_serial_path()
    print(f"ptz-init serial={port} baud={baud}")
    with serial.Serial(port, baud, timeout=0.25) as ser:
        ser.write(b"\r\n\r\n")
        time.sleep(0.25)
        ser.reset_input_buffer()
        run_start_flow(ser)
        st = read_status(ser)
        print(f"ptz-init done status={st}")


def main() -> int:
    max_tries = env_int("PTZ_INIT_MAX_TRIES", 0)
    retry_sec = env_float("PTZ_INIT_RETRY_SEC", 2.0)
    attempt = 0

    while True:
        attempt += 1
        try:
            run_once()
            return 0
        except Exception as e:
            print(f"ptz-init failed attempt={attempt}: {e}", file=sys.stderr)
            if max_tries > 0 and attempt >= max_tries:
                return 1
            time.sleep(retry_sec)


if __name__ == "__main__":
    raise SystemExit(main())
