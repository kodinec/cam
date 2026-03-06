import time, re, argparse
import serial

OK = re.compile(r'^(ok|error:.*)$', re.I)

START_X = -20.0
START_Y =  3.1

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
    return s.read_all().decode(errors="ignore").strip()

ap=argparse.ArgumentParser()
ap.add_argument("--port", required=True)
ap.add_argument("--baud", type=int, default=115200)
ap.add_argument("--feed", type=float, default=200.0)
args=ap.parse_args()

with serial.Serial(args.port, args.baud, timeout=0.25) as s:
    s.write(b"\r\n\r\n"); time.sleep(0.2); s.reset_input_buffer()

    # init
    print("G90 ->", send(s, "G90", 1.0))
    print("M120 P1 ->", send(s, "M120 P1", 1.0))
    print("M114 P1 ->", send(s, "M114 P1", 1.5))  # iris open

    # go start
    cmd = f"G1 X{START_X:.3f} Y{START_Y:.3f} F{args.feed:.1f}"
    print(cmd, "->", send(s, cmd, 3.0))

    print("STATUS:", status(s))
