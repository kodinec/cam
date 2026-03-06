import time, re, argparse
import serial

OK = re.compile(r'^(ok|error:.*)$', re.I)

START_X = -20.0
START_Y =  3.1

def open_ser(port, baud):
    s = serial.Serial(port, baud, timeout=0.25)
    s.write(b"\r\n\r\n")
    time.sleep(0.2)
    s.reset_input_buffer()
    return s

def send(s, cmd, wait=1.8):
    cmd = cmd.strip()
    if not cmd:
        return []
    s.write((cmd + "\r\n").encode())
    s.flush()
    out=[]
    end = time.time() + wait
    while time.time() < end:
        ln = s.readline().decode(errors="ignore").strip()
        if not ln:
            continue
        out.append(ln)
        if OK.match(ln):
            break
    return out

def status(s):
    s.write(b"?\r\n")
    time.sleep(0.15)
    return s.read_all().decode(errors="ignore").strip()

def soft_reset(s):
    s.write(b"\x18")
    time.sleep(1.0)
    s.reset_input_buffer()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--feed", type=float, default=200.0)
    ap.add_argument("--no-reset", action="store_true", help="do not send Ctrl-X reset")
    ap.add_argument("--no-iris", action="store_true", help="skip iris open")
    ap.add_argument("--no-zero", action="store_true", help="skip G92 X0 Y0 at start")
    args = ap.parse_args()

    with open_ser(args.port, args.baud) as s:
        if not args.no_reset:
            print("RESET -> Ctrl-X")
            soft_reset(s)

        print("G90 ->", send(s, "G90", 1.0))

        # Как у SDK/GUI: включают LED и открывают iris
        print("M120 P1 ->", send(s, "M120 P1", 1.0))

        if not args.no_iris:
            print("M114 P1 (iris open) ->", send(s, "M114 P1", 1.5))

        # Стартовая позиция, которую ты дал
        cmd = f"G1 X{START_X:.3f} Y{START_Y:.3f} F{args.feed:.1f}"
        print(cmd, "->", send(s, cmd, 3.0))

        # Зафиксировать "это старт": сделать её (0,0)
        if not args.no_zero:
            print("G92 X0 Y0 ->", send(s, "G92 X0 Y0", 1.0))

        print("STATUS:", status(s))

if __name__ == "__main__":
    main()
