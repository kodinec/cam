#!/usr/bin/env python3
import argparse, time, re, sys, json
import serial

OK = re.compile(r'^(ok|error:.*)$', re.I)

# твой требуемый "zoom 1" эталон:
ZOOM1_X = -86.723
ZOOM1_Y = -1.000

def open_ser(port, baud):
    s = serial.Serial(port, baud, timeout=0.3)
    # wake
    s.write(b"\r\n\r\n")
    time.sleep(0.25)
    s.reset_input_buffer()
    return s

def rd_all(s, sleep=0.15):
    time.sleep(sleep)
    return s.read_all().decode(errors="ignore").strip()

def send(s, cmd, wait=2.0, flush=False):
    cmd = cmd.strip()
    if not cmd:
        return []
    if flush:
        s.reset_input_buffer()
    s.write((cmd + "\r\n").encode())
    s.flush()
    out = []
    end = time.time() + wait
    while time.time() < end:
        ln = s.readline().decode(errors="ignore").strip()
        if not ln:
            continue
        out.append(ln)
        if OK.match(ln):
            break
    return out

def status_raw(s):
    s.write(b"?\r\n")
    s.flush()
    time.sleep(0.12)
    raw = s.read_all().decode(errors="ignore")
    # берём последнюю строку вида <...>
    lines = [x.strip() for x in raw.splitlines() if x.strip().startswith("<") and x.strip().endswith(">")]
    return lines[-1] if lines else raw.strip()

def parse_status(st):
    # <Idle|MPos:x,y,z,a|Bf:..|F:..|Pn:XY...|...>
    ret = {"state": None, "pn": "", "mpos": None}
    if not st.startswith("<"):
        return ret
    body = st.strip("<>").split("|")
    ret["state"] = body[0]
    for p in body[1:]:
        if p.startswith("Pn:"):
            ret["pn"] = p.split(":",1)[1]
        if p.startswith("MPos:"):
            vals = p.split(":",1)[1].split(",")
            if len(vals) >= 2:
                ret["mpos"] = (float(vals[0]), float(vals[1]))
    return ret

def soft_reset(s):
    # Ctrl-X
    s.write(b"\x18")
    s.flush()
    time.sleep(1.0)
    s.reset_input_buffer()
    # wake
    s.write(b"\r\n\r\n")
    s.flush()
    time.sleep(0.25)
    s.reset_input_buffer()

def unlock_if_alarm(s):
    st = status_raw(s)
    ps = parse_status(st)
    if ps["state"] and "Alarm" in ps["state"]:
        # unlock
        send(s, "$X", 1.0, flush=True)
        time.sleep(0.2)
    return status_raw(s)

def jog_rel(s, axis, delta, feed):
    send(s, "G91", 1.0)
    send(s, f"G0 {axis}{delta:.3f} F{feed:.1f}", 2.0)
    send(s, "G90", 1.0)

def unlimit_axis(s, axis, step=0.5, feed=80.0, max_steps=200):
    """
    Убрать флаг лимита для axis, двигаясь маленькими шагами в обе стороны при необходимости.
    """
    for direction in (+1, -1):
        for _ in range(max_steps):
            st = status_raw(s)
            ps = parse_status(st)
            pn = ps.get("pn","")
            hit = (axis.upper() in pn)
            if not hit:
                return True, st
            # шаг
            jog_rel(s, axis.upper(), direction*step, feed)
            # если снова в Alarm — unlock
            unlock_if_alarm(s)
        # если не вышли — пробуем другую сторону
    return False, status_raw(s)

def iris_open(s):
    # твоя прошивка принимает M114 P1
    return send(s, "M114 P1", 1.5, flush=True)

def iris_close(s):
    return send(s, "M114 P0", 1.5, flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    with open_ser(args.port, args.baud) as s:
        if args.reset:
            soft_reset(s)

        # базовая инициализация
        send(s, "G90", 1.0)
        send(s, "M120 P1", 1.0)  # LED (не критично)

        # выходим из Alarm если есть
        st = unlock_if_alarm(s)

        print("READY:", st)
        print("Commands:")
        print("  s                : status")
        print("  iris / irisoff   : open/close iris (M114 P1/P0)")
        print("  unlim            : снять лимиты X/Y (если Pn:XY)")
        print("  jog x+ / x-      : jog X")
        print("  jog y+ / y-      : jog Y")
        print("  set_zoom1        : сделать текущую точку zoom1 (G92 X-86.723 Y-1.0)")
        print("  goto_zoom1       : перейти в zoom1 (после set_zoom1 это G0 X0 Y0)")
        print("  q                : quit")

        while True:
            cmd = input("> ").strip().lower()
            if cmd == "q":
                break
            if cmd == "s":
                print(status_raw(s)); continue
            if cmd == "iris":
                print("iris:", iris_open(s)); continue
            if cmd == "irisoff":
                print("irisoff:", iris_close(s)); continue
            if cmd == "unlim":
                unlock_if_alarm(s)
                okx, stx = unlimit_axis(s, "X", step=0.5, feed=80)
                oky, sty = unlimit_axis(s, "Y", step=0.5, feed=80)
                print("unlim X:", okx, stx)
                print("unlim Y:", oky, sty)
                continue
            if cmd == "jog x+":
                jog_rel(s, "X", +0.5, 120); print(status_raw(s)); continue
            if cmd == "jog x-":
                jog_rel(s, "X", -0.5, 120); print(status_raw(s)); continue
            if cmd == "jog y+":
                jog_rel(s, "Y", +0.2, 120); print(status_raw(s)); continue
            if cmd == "jog y-":
                jog_rel(s, "Y", -0.2, 120); print(status_raw(s)); continue
            if cmd == "set_zoom1":
                # ВАЖНО: перед G92 убедись что НЕ Alarm
                unlock_if_alarm(s)
                out = send(s, f"G92 X{ZOOM1_X:.3f} Y{ZOOM1_Y:.3f}", 1.0, flush=True)
                print("G92:", out)
                print("STATUS:", status_raw(s))
                continue
            if cmd == "goto_zoom1":
                # после set_zoom1: zoom1 == (X0,Y0) в текущей системе
                unlock_if_alarm(s)
                out = send(s, "G90", 1.0)
                out2 = send(s, "G0 X0 Y0 F200", 4.0)
                print("G0:", out, out2)
                print("STATUS:", status_raw(s))
                continue

            print("unknown command")

if __name__ == "__main__":
    main()
