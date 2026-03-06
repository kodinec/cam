import serial
import time
import json
import argparse

class Status:
    status=""
    pos_x=0
    pos_y=0
    limit_x=False
    limit_y=False
    block_buffer_avail=0

def send(s,cmd,echo=True):
    s.write((cmd+"\n").encode())
    s.flush()

    while True:
        r=s.readline().decode(errors="ignore").strip()
        if not r:
            continue
        if echo:
            print("<",r)
        if r.startswith("ok") or r.startswith("error"):
            return r

def status(s):
    s.write(b"?\n")
    s.flush()
    time.sleep(0.1)
    txt=s.readline().decode().strip()
    return txt

def parse_status(txt):
    txt=txt.replace("<","").replace(">","")
    parts=txt.split("|")

    s=Status()
    s.status=parts[0]

    for p in parts:

        if p.startswith("MPos"):
            t=p.split(":")[1]
            v=t.split(",")
            s.pos_x=float(v[0])
            s.pos_y=float(v[1])

        if p.startswith("Pn"):
            t=p.split(":")[1]
            s.limit_x="X" in t
            s.limit_y="Y" in t

        if p.startswith("Bf"):
            t=p.split(":")[1]
            s.block_buffer_avail=int(t.split(",")[0])

    return s

def wait_idle(s):
    while True:
        st=parse_status(status(s))
        if st.status=="Idle":
            break
        time.sleep(0.05)

def move_rel(s,axis,val,feed=120):
    send(s,"G91")
    send(s,f"G1 {axis}{val} F{feed}")
    wait_idle(s)
    send(s,"G90")

def home_zoom(s):

    print("Homing zoom to WIDE stop")

    while True:

        st=parse_status(status(s))

        if st.limit_x:
            print("Reached stop")
            break

        move_rel(s,"X",-1)

    print("Backoff")
    move_rel(s,"X",2)

    send(s,"G92 X0")

def open_serial(port,baud):

    s=serial.Serial(port,baud,timeout=0.2)

    s.write(b"\r\n\r\n")
    time.sleep(1)
    s.reset_input_buffer()

    return s

def main():

    ap=argparse.ArgumentParser()
    ap.add_argument("--port",required=True)
    ap.add_argument("--baud",type=int,default=115200)
    ap.add_argument("--tele_x",type=float,required=True)
    ap.add_argument("--out",default="zoom_focus.json")

    args=ap.parse_args()

    s=open_serial(args.port,args.baud)

    print("RESET")
    s.write(b"\x18")
    time.sleep(1)

    send(s,"$X")

    send(s,"G90")
    send(s,"M120 P1")
    send(s,"M114 P1")

    home_zoom(s)

    print("Goto start calibration position")
    send(s,"G1 X-32 Y1.2 F200")
    wait_idle(s)

    send(s,"G92 X0 Y0")

    print("START = X0 Y0")

    step=args.tele_x/25

    data={"focus":[]}

    print("")
    print("Controls:")
    print("a/d zoom")
    print("j/l focus")
    print("w save focus")
    print("s status")
    print("q quit")

    while True:

        cmd=input("> ").strip()

        if cmd=="a":
            move_rel(s,"X",-0.5)

        elif cmd=="d":
            move_rel(s,"X",0.5)

        elif cmd=="j":
            move_rel(s,"Y",-0.2)

        elif cmd=="l":
            move_rel(s,"Y",0.2)

        elif cmd=="s":

            st=parse_status(status(s))
            print("X",st.pos_x,"Y",st.pos_y)

        elif cmd=="w":

            st=parse_status(status(s))
            data["focus"].append(st.pos_y)

            print("saved",st.pos_y)

        elif cmd=="q":

            with open(args.out,"w") as f:
                json.dump(data,f,indent=2)

            print("saved file",args.out)
            break

if __name__=="__main__":
    main()
