import argparse, time, re
import serial

OK_RE = re.compile(r'^(ok|error:.*)$', re.I)

def open_ser(port, baud):
    s = serial.Serial(port, baud, timeout=0.25)
    # wake
    s.write(b"\r\n\r\n")
    time.sleep(0.2)
    s.reset_input_buffer()
    return s

def send(s, cmd, wait=1.5):
    cmd = cmd.strip()
    if not cmd:
        return []
    s.write((cmd + "\r\n").encode())
    s.flush()
    lines = []
    end = time.time() + wait
    while time.time() < end:
        ln = s.readline().decode(errors="ignore").strip()
        if not ln:
            continue
        lines.append(ln)
        if OK_RE.match(ln):
            break
    return lines

def status(s):
    s.write(b"?\r\n")
    time.sleep(0.15)
    data = s.read_all().decode(errors="ignore")
    return data.strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)

    # target pose (как в GUI)
    ap.add_argument("--x", type=float, default=None)  # Zoom (X)
    ap.add_argument("--y", type=float, default=None)  # Focus (Y)
    ap.add_argument("--a", type=float, default=None)  # Iris/Filter axis (A) - осторожно
    ap.add_argument("--f", type=float, default=100.0) # feedrate

    # helpers
    ap.add_argument("--reset", action="store_true", help="soft reset (Ctrl-X)")
    ap.add_argument("--zero", action="store_true", help="set current position as 0 (G92 X0 Y0 Z0 A0)")
    ap.add_argument("--iris-open", action="store_true", help="try open iris using M114 P1 first, else do nothing")
    args = ap.parse_args()

    s = open_ser(args.port, args.baud)

    try:
        if args.reset:
            # GRBL soft reset
            s.write(b"\x18")
            time.sleep(1.0)
            s.reset_input_buffer()

        # Absolute mode
        send(s, "G90", 1.0)

        if args.iris_open:
            # На некоторых прошивках SCE2 это открывает iris “правильно”
            # Если не поддерживается — вернет error, это ок.
            out = send(s, "M114 P1", 1.5)
            print("M114 P1 ->", out)

        if args.zero:
            out = send(s, "G92 X0 Y0 Z0 A0", 1.0)
            print("G92 ->", out)

        # Move to target (one combined move)
        parts = []
        if args.x is not None: parts.append(f"X{args.x:.3f}")
        if args.y is not None: parts.append(f"Y{args.y:.3f}")
        if args.a is not None: parts.append(f"A{args.a:.3f}")

        if parts:
            cmd = "G1 " + " ".join(parts) + f" F{args.f:.1f}"
            out = send(s, cmd, 2.0)
            print(cmd, "->", out)

        print("STATUS:", status(s))

    finally:
        s.close()

if __name__ == "__main__":
    main()
