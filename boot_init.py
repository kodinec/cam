import time, re, argparse
import serial

OK = re.compile(r'^(ok|error:.*)$', re.I)

def open_ser(port, baud):
    s = serial.Serial(port, baud, timeout=0.25)
    s.write(b"\r\n\r\n"); time.sleep(0.2)
    s.reset_input_buffer()
    return s

def send(s, cmd, wait=2.0):
    s.write((cmd+"\r\n").encode()); s.flush()
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
    s.write(b"?\r\n")
    time.sleep(0.15)
    raw=s.read_all().decode(errors="ignore")
    lines=[x.strip() for x in raw.splitlines() if x.strip().startswith("<")]
    return lines[-1] if lines else raw.strip()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--big", type=float, default=80.0, help="big move to hit WIDE stop")
    ap.add_argument("--backoff", type=float, default=2.0, help="move away from stop")
    ap.add_argument("--feed", type=float, default=80.0)
    ap.add_argument("--wide_dir", choices=["-","+"] , default="-", help="direction to reach WIDE")
    ap.add_argument("--reset", action="store_true", help="send Ctrl-X reset")
    ap.add_argument("--iris", action="store_true", help="send iris open (M114 P1)")
    args=ap.parse_args()

    with open_ser(args.port, args.baud) as s:
        if args.reset:
            s.write(b"\x18"); time.sleep(1.0); s.reset_input_buffer()

        send(s, "G90", 1.0)
        send(s, "M120 P1", 1.0)
        if args.iris:
            send(s, "M114 P1", 1.5)

        # go relative
        send(s, "G91", 1.0)

        # slam to WIDE stop
        sign = -1.0 if args.wide_dir == "-" else 1.0
        send(s, f"G1 X{sign*args.big:.3f} F{args.feed:.1f}", 6.0)

        # backoff (opposite direction)
        send(s, f"G1 X{-sign*args.backoff:.3f} F{args.feed:.1f}", 3.0)

        # set this as X=0 reference
        send(s, "G92 X0", 1.0)

        send(s, "G90", 1.0)

        print("INIT DONE")
        print("STATUS:", status(s))

if __name__=="__main__":
    main()
