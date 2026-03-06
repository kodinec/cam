import argparse, json, time, re, sys
import serial

OK = re.compile(r'^(ok|error:.*)$', re.I)

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
    end=time.time()+wait
    while time.time()<end:
        ln = s.readline().decode(errors="ignore").strip()
        if not ln:
            continue
        out.append(ln)
        if OK.match(ln):
            break
    # печатаем кратко, чтоб видеть что происходит
    # print(cmd, "->", out[-3:])
    return out

def status(s):
    s.write(b"?\r\n")
    time.sleep(0.15)
    return s.read_all().decode(errors="ignore")

def parse_mpos_xa(st):
    # <Idle|MPos:X,Y,Z,A|...>
    m = re.search(r'MPos:([-\d\.]+),([-\d\.]+),([-\d\.]+),([-\d\.]+)', st)
    if not m:
        return None
    x=float(m.group(1)); y=float(m.group(2)); z=float(m.group(3)); a=float(m.group(4))
    return x,y,z,a

def soft_reset(s):
    s.write(b"\x18")
    time.sleep(1.0)
    s.reset_input_buffer()

def init_lens(s):
    send(s, "G90", 1.0)       # absolute
    send(s, "M120 P1", 1.0)   # LED on (как в SDK)
    send(s, "M114 P1", 1.5)   # iris open (если поддерживается)
    # если не поддерживается — будет error, это ок

def rel_steps(s, axis, steps, feed=50, step_size=1.0):
    # relative move
    send(s, "G91", 1.0)
    sign = 1 if steps >= 0 else -1
    for _ in range(abs(int(steps))):
        cmd = f"G1 {axis}{sign*step_size:.3f} F{feed}"
        send(s, cmd, 1.0)
        time.sleep(0.03)
    send(s, "G90", 1.0)

def set_abs(s, x=None, y=None, a=None, feed=200):
    parts=[]
    if x is not None: parts.append(f"X{x:.3f}")
    if y is not None: parts.append(f"Y{y:.3f}")
    if a is not None: parts.append(f"A{a:.3f}")
    if not parts:
        return
    send(s, "G90", 1.0)
    send(s, "G1 " + " ".join(parts) + f" F{feed}", 2.0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out", default="zoom25_focusmap.json")

    ap.add_argument("--tele_steps", type=int, default=500,
                    help="сколько 1-шаговых шагов X сделать к TELE от wide (подбирается)")
    ap.add_argument("--tele_dir", choices=["+","-"], default="+",
                    help="в какую сторону X едет к TELE (если перепутано — поменяй)")

    ap.add_argument("--wide_backoff", type=int, default=10,
                    help="отъехать от упора на N шагов после wide поиска")
    ap.add_argument("--tele_backoff", type=int, default=10,
                    help="отъехать от упора на N шагов после tele поиска")

    ap.add_argument("--feed", type=float, default=80.0)
    args = ap.parse_args()

    with open_ser(args.port, args.baud) as s:
        print("== reset/init ==")
        soft_reset(s)
        init_lens(s)

        # 1) WIDE: аккуратно уехать в wide до упора “примерно”
        # Здесь мы не умеем детектить упор программно (нет датчиков),
        # поэтому делаем “приехать в wide” большим числом шагов, затем backoff.
        print("== go WIDE (coarse) ==")
        # едем в wide в противоположную сторону tele_dir
        wide_dir = "-" if args.tele_dir == "+" else "+"
        steps = args.tele_steps
        rel_steps(s, "X", steps if wide_dir=="+" else -steps, feed=args.feed, step_size=1.0)
        # backoff (отъехать от упора)
        rel_steps(s, "X", -args.wide_backoff if wide_dir=="+" else args.wide_backoff, feed=args.feed, step_size=1.0)

        # ставим X=0 как wide
        send(s, "G92 X0", 1.0)
        st = status(s)
        print("STATUS after WIDE+G92:", st.strip().splitlines()[0] if st else st)
        base = parse_mpos_xa(st)
        if not base:
            print("Cannot parse status MPos")
            sys.exit(1)

        # 2) TELE: едем в tele на tele_steps
        print("== go TELE (coarse) ==")
        rel_steps(s, "X", steps if args.tele_dir=="+" else -steps, feed=args.feed, step_size=1.0)
        rel_steps(s, "X", -args.tele_backoff if args.tele_dir=="+" else args.tele_backoff, feed=args.feed, step_size=1.0)

        st2 = status(s)
        x2 = parse_mpos_xa(st2)
        if not x2:
            print("Cannot parse TELE status")
            sys.exit(1)
        tele_x = x2[0]
        if tele_x == 0:
            print("TELE X is 0 — range not moved. Check tele_dir/steps.")
            sys.exit(1)

        print(f"== RANGE: wide=0  tele={tele_x:.3f} ==")
        step = tele_x / 25.0
        print(f"== ZOOM STEP = {step:.6f} per 1/25 ==")

        # Вернёмся на wide
        set_abs(s, x=0.0, feed=150)

        # 3) Калибровка фокуса по 25 зумам: ты руками выставляешь фокус,
        # а скрипт сохраняет Y (текущий focus) в JSON.
        print("\n== Focus calibration ==")
        print("Инструкция:")
        print("  - Для каждой позиции i=0..25 скрипт ставит X.")
        print("  - Ты подстраиваешь фокус (Y) любым способом (GUI или отдельной командой).")
        print("  - Когда картинка резкая: нажми Enter -> скрипт прочитает текущий Y и сохранит.")
        print("  - Если нужно пропустить: введи 'skip' и Enter.")
        print("  - Если выйти: 'q' и Enter.\n")

        focusmap = {
            "meta": {
                "port": args.port,
                "baud": args.baud,
                "tele_x": tele_x,
                "zoom_step": step,
                "tele_dir": args.tele_dir,
                "tele_steps": args.tele_steps,
                "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            "points": []
        }

        for i in range(26):
            x = step * i
            set_abs(s, x=x, feed=150)
            time.sleep(0.2)
            st = status(s)
            pos = parse_mpos_xa(st) or (None,None,None,None)
            cur_y = pos[1]

            print(f"[{i:02d}/25] Zoom -> X={x:.3f}  (current Y={cur_y})")
            ans = input("Focus now, then press Enter (or 'skip'/'q'): ").strip().lower()
            if ans == "q":
                break
            if ans == "skip":
                focusmap["points"].append({"i": i, "x": x, "y": None})
                continue

            st = status(s)
            pos = parse_mpos_xa(st)
            if not pos:
                print("  ! cannot read status, saving y=None")
                focusmap["points"].append({"i": i, "x": x, "y": None})
                continue
            y = pos[1]
            focusmap["points"].append({"i": i, "x": x, "y": y})
            print(f"  saved: i={i} x={x:.3f} y={y:.3f}")

        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(focusmap, f, ensure_ascii=False, indent=2)
        print(f"\nSaved: {args.out}")
        print("Next: use this map to auto-apply focus when changing zoom.")

if __name__ == "__main__":
    main()
