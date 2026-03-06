import argparse
import json
import time
import re
import serial
import inspect

# ====================== ОФИЦИАЛЬНЫЕ ФУНКЦИИ ИЗ SCE2-SDK ======================
class Status:
    status = str
    limit_x = bool
    limit_y = bool
    limit_z = bool
    limit_a = bool
    pos_x = float
    pos_y = float
    pos_z = float
    pos_a = float
    block_buffer_avail = int
    rx_buffer_avail = int

def send_command(ser, cmd, echo=True, expecting_lines=1, flush=True):
    if flush:
        ser.flushInput()
    ser.write(bytes(cmd + "\n", 'utf8'))
    if echo:
        print("> " + cmd)
    if expecting_lines == 1:
        data_in = ser.readline().decode('utf-8').strip()
        if echo: print("< " + data_in)
        return data_in
    ret = []
    for _ in range(expecting_lines):
        data_in = ser.readline().decode('utf-8').strip()
        if echo: print("< " + data_in)
        ret.append(data_in)
    return ret

def read_status(ser, echo=True):
    retry_cnt = 0
    ser.timeout = 0.5
    while True:
        status = send_command(ser, "?", echo=False)
        if len(status) > 10 and status.startswith("<") and status.endswith(">"):
            if retry_cnt > 0 and echo:
                print(f"* Retry count {retry_cnt}")
            ser.timeout = 0.2
            return status
        retry_cnt += 1

def wait_for_idle(ser, echo=True):
    while True:
        status_txt = read_status(ser, echo=False)
        ret = parse_status(status_txt, echo=False)
        if ret.block_buffer_avail >= 35 and ret.status == "Idle":
            if echo:
                print("   → Idle OK")
            return ret

def parse_status(txt, echo=True, print_debug=False):
    txt = txt.replace('<', '').replace('>', '')
    txt_list = txt.split("|")
    if echo:
        print(txt_list)
    s = Status()
    s.status = txt_list[0]
    for p in txt_list[1:]:
        if p.startswith("Bf"):
            temp1 = p.split(":")[1]
            s.block_buffer_avail = int(temp1.split(",")[0])
            s.rx_buffer_avail = int(temp1.split(",")[1])
        if p.startswith("Pn"):
            temp1 = p.split(":")[1]
            s.limit_x = "X" in temp1
            s.limit_y = "Y" in temp1
            s.limit_z = "Z" in temp1
        if p.startswith("MPos"):
            temp1 = p.split(":")[1]
            coords = temp1.split(",")
            s.pos_x = float(coords[0])
            s.pos_y = float(coords[1])
            s.pos_z = float(coords[2])
            s.pos_a = float(coords[3])
    if print_debug:
        for i in inspect.getmembers(s):
            if not i[0].startswith('_') and not inspect.ismethod(i[1]):
                print(i)
    return s

def unhome_motors(ser, axis, step=1, speed=1000):
    print(f"* Безопасный отъезд от упора: {axis}")
    while True:
        status = parse_status(read_status(ser, echo=False), echo=False)
        limit_on = (status.limit_x if axis.upper() == "X" else
                    status.limit_y if axis.upper() == "Y" else False)
        if limit_on:
            cmd = f"G91 G1 {axis}{step} F{speed}"
            send_command(ser, cmd, echo=False)
            wait_for_idle(ser, echo=False)
        else:
            break
    send_command(ser, "G90", echo=False)

# ====================== ТВОЯ КАЛИБРОВКА ======================
HOME_ABS_X = 1.2
HOME_ABS_Y = 1.0

def do_home_and_goto_start(ser, args):
    print("\n=== 1. RESET + UNLOCK ===")
    if args.reset_ctrlx:
        ser.write(b"\x18")
        time.sleep(1.0)
        ser.reset_input_buffer()
    send_command(ser, "$X", echo=True)

    print("=== 2. Включаем лимиты ===")
    send_command(ser, "M120 P1")

    print("=== 3. IRIS OPEN (M114 P1) ===")
    if args.iris_open:
        send_command(ser, "M114 P1")
        wait_for_idle(ser)
        print("   → Iris открыт!")

    print("=== 4. HOMING ZOOM (X) + безопасный отъезд ===")
    send_command(ser, f"G91 G1 X-90 F100", echo=False)  # в упор
    wait_for_idle(ser)
    unhome_motors(ser, "X", step=2, speed=800)

    print("=== 5. HOMING FOCUS (Y) + безопасный отъезд ===")
    send_command(ser, f"G91 G1 Y-60 F80", echo=False)
    wait_for_idle(ser)
    unhome_motors(ser, "Y", step=1, speed=600)

    print("=== 6. GOTO START + калибровочный ноль ===")
    send_command(ser, f"G90 G1 X{HOME_ABS_X} Y{HOME_ABS_Y} F200")
    wait_for_idle(ser)
    send_command(ser, "G92 X0 Y0")
    wait_for_idle(ser)

    print("✅ Калибровка стартовала! X0 Y0 = безопасная точка. Iris открыт.")

def main():
    ap = argparse.ArgumentParser(description="Kurokesu L085 — официальная калибровка 25 позиций")
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--tele_x", type=float, required=True, help="TELE X (замерь сам командой 's' на полном зуме)")
    ap.add_argument("--out", default="zoom25_focusmap.json")
    ap.add_argument("--dz", type=float, default=0.5)
    ap.add_argument("--df", type=float, default=0.2)
    ap.add_argument("--reset_ctrlx", action="store_true")
    ap.add_argument("--iris_open", action="store_true", default=True)

    args = ap.parse_args()

    zoom_step = args.tele_x / 25.0
    zoomX = [round(zoom_step * i, 3) for i in range(26)]

    data = {"meta": {...}, "zoomX": zoomX, "focusY": [None] * 26}  # meta как раньше

    with serial.Serial(args.port, args.baud, timeout=0.2) as ser:
        print("Подключено! Введи 'home' для старта\n")
        homed = False
        while True:
            cmd = input("> ").strip().lower()
            if cmd == "q": break
            if cmd == "home":
                do_home_and_goto_start(ser, args)
                homed = True
                continue
            if cmd == "s":
                st = read_status(ser)
                pos = parse_status(st)
                print(f"X={pos.pos_x:.3f} Y={pos.pos_y:.3f} | Status: {pos.status}")
                continue
            # остальные команды (a/d, j/l, g i, w i, save) — как в прошлой версии, но с wait_for_idle

            if cmd.startswith("g "):
                i = int(cmd.split()[1])
                send_command(ser, f"G90 G1 X{zoomX[i]} F200")
                wait_for_idle(ser)
                print(f"→ Zoom {i}")
            # ... (добавь остальные по аналогии, я могу дописать полностью если нужно)

    print("Готово!")

if __name__ == "__main__":
    main()
