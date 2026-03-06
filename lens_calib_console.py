import argparse, json, time, re
import serial

OK = re.compile(r'^(ok|error:.*)$', re.I)

# Твой желаемый "физический старт" (как ты написал)
HOME_ABS_X = -29.0
HOME_ABS_Y = -2.0


def open_ser(port, baud):
    s = serial.Serial(port, baud, timeout=0.2)
    s.write(b"\r\n\r\n")
    time.sleep(0.25)
    s.reset_input_buffer()
    return s

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
    s.write(b"?\r\n")
    time.sleep(0.12)
    raw = s.read_all().decode(errors="ignore")
    lines=[x.strip() for x in raw.splitlines() if x.strip().startswith("<")]
    return lines[-1] if lines else raw.strip()

def parse_mpos(st):
    m = re.search(r'MPos:([-\d\.]+),([-\d\.]+),([-\d\.]+),([-\d\.]+)', st)
    if not m:
        return None
    return tuple(float(m.group(i)) for i in range(1,5))  # X,Y,Z,A

def move_rel(s, axis, delta, feed):
    send(s, "G91", 1.0)
    send(s, f"G1 {axis}{delta:.3f} F{feed:.1f}", 3.0)
    send(s, "G90", 1.0)

def move_abs(s, x=None, y=None, feed=200):
    parts=[]
    if x is not None: parts.append(f"X{x:.3f}")
    if y is not None: parts.append(f"Y{y:.3f}")
    if not parts:
        return
    send(s, "G90", 1.0)
    send(s, "G1 " + " ".join(parts) + f" F{feed:.1f}", 5.0)

def slam_to_stop(s, axis, big, backoff, feed, direction):
    """
    direction: '-' or '+'
    """
    sign = -1.0 if direction == "-" else 1.0
    send(s, "G91", 1.0)
    # slam
    send(s, f"G1 {axis}{sign*big:.3f} F{feed:.1f}", 10.0)
    # backoff
    send(s, f"G1 {axis}{-sign*backoff:.3f} F{feed:.1f}", 5.0)
    send(s, "G90", 1.0)

def do_home_and_goto_start(s, args):
    """
    1) ВЫГОНЯЕМ В УПОРЫ (нули координат)
    2) ЕДЕМ В X=-32 Y=1.2
    3) ОБЪЯВЛЯЕМ ЭТУ ТОЧКУ НУЛЁМ КАЛИБРОВКИ (G92 X0 Y0)
    """
    # init / iris
    send(s, "G90", 1.0)
    send(s, "M120 P1", 1.0)
    if args.iris_open:
        send(s, "M114 P1", 1.5)

    if args.reset_ctrlx:
        s.write(b"\x18")  # Ctrl-X
        time.sleep(1.0)
        s.reset_input_buffer()

    # 1) slam-to-stop X (WIDE)
    slam_to_stop(s, "X", args.x_stop_big, args.x_stop_backoff, args.x_stop_feed, args.x_stop_dir)

    # 2) slam-to-stop Y (FOCUS) - чтобы "всё в нули"
    slam_to_stop(s, "Y", args.y_stop_big, args.y_stop_backoff, args.y_stop_feed, args.y_stop_dir)

    # 3) текущую точку объявляем X0 Y0
    send(s, "G92 X0 Y0", 1.0)

    # 4) едем в твой "старт": X= Y=1.2 (в текущей системе)
    # Сейчас X0Y0 - это упоры. Мы переезжаем в желаемый старт.
    move_abs(s, x=HOME_ABS_X, y=HOME_ABS_Y, feed=args.goto_feed)

    # 5) эту точку объявляем НУЛЕМ КАЛИБРОВКИ
    send(s, "G92 X0 Y0", 1.0)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)

    ap.add_argument("--tele_x", type=float, required=True, help="TELE X in calibration coords (after home+goto_start). Example: 16.298")
    ap.add_argument("--out", default="zoom25_focusmap.json")

    # manual steps
    ap.add_argument("--dz", type=float, default=0.5, help="manual zoom step (X)")
    ap.add_argument("--df", type=float, default=0.2, help="manual focus step (Y)")
    ap.add_argument("--feed_zoom", type=float, default=120.0)
    ap.add_argument("--feed_focus", type=float, default=120.0)

    # start / homing behavior
    ap.add_argument("--reset_ctrlx", action="store_true", help="send Ctrl-X reset before homing")
    ap.add_argument("--iris_open", action="store_true", help="send M114 P1 at start")

    # X stop (wide)
    ap.add_argument("--x_stop_dir", choices=["-","+"], default="-")
    ap.add_argument("--x_stop_big", type=float, default=90.0)
    ap.add_argument("--x_stop_backoff", type=float, default=2.0)
    ap.add_argument("--x_stop_feed", type=float, default=100.0)

    # Y stop (focus)
    ap.add_argument("--y_stop_dir", choices=["-","+"], default="-")
    ap.add_argument("--y_stop_big", type=float, default=60.0)
    ap.add_argument("--y_stop_backoff", type=float, default=1.0)
    ap.add_argument("--y_stop_feed", type=float, default=80.0)

    # goto start feed
    ap.add_argument("--goto_feed", type=float, default=200.0)

    args=ap.parse_args()

    zoom_step = args.tele_x / 25.0
    zoomX = [zoom_step*i for i in range(26)]

    data = {
        "meta": {
            "calib_start_abs": {"X": HOME_ABS_X, "Y": HOME_ABS_Y},
            "tele_x": args.tele_x,
            "zoom_step": zoom_step,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "notes": "Start: homing to X/Y stops => G92 X0Y0 => goto abs(-32,1.2) => G92 X0Y0 (calibration zero)."
        },
        "zoomX": zoomX,
        "focusY": [None]*26
    }

    with open_ser(args.port, args.baud) as s:
        print("\nCommands:")
        print("  home    : homing (X/Y to stops) -> zero -> goto start(-32,1.2) -> zero (start calib)")
        print("  h       : goto start (X0 Y0) in calib coords")
        print("  a/d     : zoom -/+ manual (X)")
        print("  j/l     : focus -/+ manual (Y)")
        print("  g i     : go to zoom index i (0..25) (uses X table)")
        print("  w i     : save focusY[i] = current Y")
        print("  s       : status")
        print("  save    : save JSON")
        print("  q       : quit\n")

        homed=False

        while True:
            cmd=input("> ").strip()

            if cmd=="q":
                break

            if cmd=="s":
                st=status(s)
                print(st)
                pos=parse_mpos(st)
                if pos:
                    print(f"X={pos[0]:.3f} Y={pos[1]:.3f}")
                continue

            if cmd=="home":
                print("HOMING -> ZERO -> GOTO START -> ZERO ...")
                do_home_and_goto_start(s, args)
                homed=True
                print("DONE. Calibration start is now X0 Y0.")
                print(status(s))
                continue

            if cmd=="h":
                if not homed:
                    print("Run 'home' first.")
                    continue
                move_abs(s, x=0.0, y=0.0, feed=args.goto_feed)
                print("at start:", status(s))
                continue

            if cmd=="a":
                move_rel(s, "X", -args.dz, args.feed_zoom); continue
            if cmd=="d":
                move_rel(s, "X", +args.dz, args.feed_zoom); continue
            if cmd=="j":
                move_rel(s, "Y", -args.df, args.feed_focus); continue
            if cmd=="l":
                move_rel(s, "Y", +args.df, args.feed_focus); continue

            if cmd.startswith("g "):
                if not homed:
                    print("Run 'home' first.")
                    continue
                i=int(cmd.split()[1])
                if i<0 or i>25:
                    print("index 0..25"); continue
                move_abs(s, x=zoomX[i], feed=args.goto_feed)
                print(f"goto zoom {i} (X={zoomX[i]:.3f})")
                print(status(s))
                continue

            if cmd.startswith("w "):
                if not homed:
                    print("Run 'home' first.")
                    continue
                i=int(cmd.split()[1])
                if i<0 or i>25:
                    print("index 0..25"); continue
                st=status(s)
                pos=parse_mpos(st)
                if pos:
                    data["focusY"][i]=pos[1]
                    print(f"saved focusY[{i}] = {pos[1]:.3f}")
                else:
                    print("cannot read position")
                continue

            if cmd=="save":
                with open(args.out,"w",encoding="utf-8") as f:
                    json.dump(data,f,ensure_ascii=False,indent=2)
                print("saved",args.out)
                continue

            print("unknown. use: home h a d j l g i w i s save q")

    with open(args.out,"w",encoding="utf-8") as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
    print("saved", args.out)

if __name__=="__main__":
    main()