import time, re, argparse
import serial

OK = re.compile(r'^(ok|error:.*)$', re.I)

START_X = -20.000
START_Y = -0.900

def open_ser(port, baud):
    s = serial.Serial(port, baud, timeout=0.25)
    s.write(b"\r\n\r\n"); time.sleep(0.2)
    s.reset_input_buffer()
    return s

def send(s, cmd, wait=2.0):
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
    s.write(b"?\r\n")
    time.sleep(0.15)
    return s.read_all().decode(errors="ignore").strip()

ap=argparse.ArgumentParser()
ap.add_argument("--port", required=True)
ap.add_argument("--baud", type=int, default=115200)
args=ap.parse_args()

with open_ser(args.port, args.baud) as s:
    send(s, "G90", 1.0)
    send(s, "M120 P1", 1.0)
    send(s, "M114 P1", 1.5) # iris open
    send(s, f"G1 X{START_X:.3f} Y{START_Y:.3f} F200", 3.0)
    print(status(s))
