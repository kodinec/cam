import time, re, argparse
import serial

OK = re.compile(r'^(ok|error:.*)$', re.I)

def rd_all(s, t=0.25):
    time.sleep(t)
    return s.read_all().decode(errors="ignore").strip()

def send(s, cmd, wait=2.0):
    cmd = cmd.strip()
    if not cmd:
        return []
    s.write((cmd + "\r\n").encode()); s.flush()
    out=[]
    end=time.time()+wait
    while time.time()<end:
        ln=s.readline().decode(errors="ignore").strip()
        if not ln:
            continue
        out.append(ln)
        if OK.match(ln):
            break
    return out

def status(s):
    s.write(b"?\r\n"); s.flush()
    time.sleep(0.15)
    raw = s.read_all().decode(errors="ignore")
    lines=[x.strip() for x in raw.splitlines() if x.strip().startswith("<")]
    return lines[-1] if lines else raw.strip()

ap=argparse.ArgumentParser()
ap.add_argument("--port", required=True)
ap.add_argument("--baud", type=int, default=115200)
ap.add_argument("--reset", action="store_true")
ap.add_argument("--wide_dir", choices=["-","+"], default="-")  # куда ехать в WIDE упор
ap.add_argument("--slam", type=float, default=140.0)          # большой ход до упора
ap.add_argument("--backoff", type=float, default=2.0)         # отъехать от упора
ap.add_argument("--feed", type=float, default=80.0)
args=ap.parse_args()

with serial.Serial(args.port, args.baud, timeout=0.25) as s:
    s.write(b"\r\n\r\n"); s.flush()
    s.reset_input_buffer()

    if args.reset:
        s.write(b"\x18"); s.flush()
        time.sleep(1.0)
        s.reset_input_buffer()
        s.write(b"\r\n\r\n"); s.flush()
        time.sleep(0.25)
        s.reset_input_buffer()

    print("G90 ->", send(s, "G90", 1.0))
    print("M120 P1 ->", send(s, "M120 P1", 1.0))
    print("M114 P1 (iris open) ->", send(s, "M114 P1", 1.5))

    sign = -1.0 if args.wide_dir == "-" else 1.0

    # relative
    print("G91 ->", send(s, "G91", 1.0))

    # slam to stop
    print("SLAM ->", send(s, f"G1 X{sign*args.slam:.3f} F{args.feed:.1f}", 12.0))

    # backoff
    print("BACKOFF ->", send(s, f"G1 X{-sign*args.backoff:.3f} F{args.feed:.1f}", 6.0))

    # set X0 at this safe point
    print("G92 X0 ->", send(s, "G92 X0", 1.0))

    # absolute again
    print("G90 ->", send(s, "G90", 1.0))

    print("STATUS:", status(s))
