import argparse
import re
import shlex
import subprocess
from dataclasses import dataclass


CTRL_LINE_RE = re.compile(r"^\s*([a-z0-9_]+)\s+0x[0-9a-f]+ \(([^)]+)\)\s*:\s*(.*)$", re.I)
KV_RE = re.compile(r"([a-z_]+)=([^\s]+)", re.I)


@dataclass
class Control:
    name: str
    ctype: str
    raw: str
    min: int | None = None
    max: int | None = None
    step: int | None = None
    default: int | None = None
    value: int | None = None


def run_cmd(args: list[str], check: bool = True) -> str:
    p = subprocess.run(args, capture_output=True, text=True)
    if check and p.returncode != 0:
        cmd = " ".join(shlex.quote(x) for x in args)
        raise RuntimeError(f"Command failed ({p.returncode}): {cmd}\n{p.stderr.strip()}")
    return p.stdout


def parse_int(v: str) -> int | None:
    try:
        return int(v, 10)
    except Exception:
        return None


def parse_controls(txt: str) -> dict[str, Control]:
    out: dict[str, Control] = {}
    for line in txt.splitlines():
        m = CTRL_LINE_RE.match(line)
        if not m:
            continue
        name, ctype, rest = m.group(1), m.group(2), m.group(3)
        c = Control(name=name, ctype=ctype, raw=line.strip())
        for k, v in KV_RE.findall(rest):
            iv = parse_int(v)
            if k == "min":
                c.min = iv
            elif k == "max":
                c.max = iv
            elif k == "step":
                c.step = iv
            elif k == "default":
                c.default = iv
            elif k == "value":
                c.value = iv
        out[name] = c
    return out


def list_controls(dev: str) -> dict[str, Control]:
    txt = run_cmd(["v4l2-ctl", "-d", dev, "--list-ctrls-menus"])
    return parse_controls(txt)


def get_control(dev: str, name: str) -> int | None:
    txt = run_cmd(["v4l2-ctl", "-d", dev, "-C", name], check=False).strip()
    m = re.search(r":\s*(-?\d+)\s*$", txt)
    if not m:
        return None
    return int(m.group(1))


def set_control(dev: str, name: str, value: int) -> bool:
    cmd = f"{name}={value}"
    p = subprocess.run(["v4l2-ctl", "-d", dev, "--set-ctrl", cmd], capture_output=True, text=True)
    return p.returncode == 0


def pick_zoom_control(ctrls: dict[str, Control]) -> str | None:
    for key in ("zoom_absolute", "zoom_relative", "zoom_continuous"):
        if key in ctrls:
            return key
    return None


def clamp(v: int, lo: int | None, hi: int | None) -> int:
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


def print_summary(dev: str, ctrls: dict[str, Control], zoom_name: str | None) -> None:
    print(f"Device: {dev}")
    if zoom_name is None:
        print("Zoom control not found (zoom_absolute/zoom_relative/zoom_continuous).")
    else:
        z = ctrls.get(zoom_name)
        print(f"Zoom control: {zoom_name}")
        if z:
            print(f"  type={z.ctype} min={z.min} max={z.max} step={z.step} default={z.default} value={z.value}")
        cur = get_control(dev, zoom_name)
        if cur is not None:
            print(f"  current={cur}")

    print("\nCommands:")
    print("  +            zoom in")
    print("  -            zoom out")
    print("  g            read current zoom")
    print("  set N        set absolute zoom value N (if supported)")
    print("  list         print all controls with zoom/focus/pan/tilt")
    print("  q            quit")


def do_zoom_step(dev: str, ctrl: Control, direction: int, user_step: int) -> None:
    if ctrl.name == "zoom_absolute":
        cur = get_control(dev, ctrl.name)
        if cur is None:
            cur = ctrl.value if ctrl.value is not None else (ctrl.default or 0)
        base_step = ctrl.step if ctrl.step and ctrl.step > 0 else 1
        step = user_step if user_step > 0 else base_step
        target = clamp(cur + direction * step, ctrl.min, ctrl.max)
        ok = set_control(dev, ctrl.name, target)
        if not ok:
            print("set failed")
            return
        after = get_control(dev, ctrl.name)
        print(f"{ctrl.name}: {cur} -> {after if after is not None else target}")
        return

    if ctrl.name in ("zoom_relative", "zoom_continuous"):
        # Usually ±1 pulses for relative/continuous controls.
        pulse = 1 if direction > 0 else -1
        ok = set_control(dev, ctrl.name, pulse)
        if not ok:
            print("set failed")
            return
        print(f"{ctrl.name}: pulse {pulse}")
        return

    print("unsupported zoom control type")


def main() -> None:
    ap = argparse.ArgumentParser(description="Linux V4L2 zoom console for H50 UVC camera")
    ap.add_argument("--dev", default="/dev/video2", help="video node (e.g. /dev/video2)")
    ap.add_argument("--step", type=int, default=1, help="step for zoom_absolute")
    args = ap.parse_args()

    ctrls = list_controls(args.dev)
    zoom_name = pick_zoom_control(ctrls)
    print_summary(args.dev, ctrls, zoom_name)

    if zoom_name is None:
        return

    zoom_ctrl = ctrls[zoom_name]

    while True:
        cmd = input("> ").strip()
        if cmd == "q":
            return
        if cmd == "+":
            do_zoom_step(args.dev, zoom_ctrl, +1, args.step)
            continue
        if cmd == "-":
            do_zoom_step(args.dev, zoom_ctrl, -1, args.step)
            continue
        if cmd == "g":
            cur = get_control(args.dev, zoom_ctrl.name)
            if cur is None:
                print("cannot read current zoom")
            else:
                print(f"{zoom_ctrl.name}={cur}")
            continue
        if cmd.startswith("set "):
            if zoom_ctrl.name != "zoom_absolute":
                print(f"'set N' works only with zoom_absolute (current: {zoom_ctrl.name})")
                continue
            parts = cmd.split()
            if len(parts) != 2:
                print("usage: set N")
                continue
            try:
                val = int(parts[1])
            except ValueError:
                print("N must be integer")
                continue
            val = clamp(val, zoom_ctrl.min, zoom_ctrl.max)
            ok = set_control(args.dev, zoom_ctrl.name, val)
            if not ok:
                print("set failed")
                continue
            after = get_control(args.dev, zoom_ctrl.name)
            print(f"{zoom_ctrl.name}={after if after is not None else val}")
            continue
        if cmd == "list":
            for name, c in ctrls.items():
                if any(k in name for k in ("zoom", "focus", "pan", "tilt")):
                    print(c.raw)
            continue
        print("unknown command")


if __name__ == "__main__":
    main()
