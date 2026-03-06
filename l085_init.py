import time, serial, re

PORT="/dev/cu.usbmodem6D86487550831"
BAUD=115200
OK=re.compile(r'^(ok|error:.*)$', re.I)

def send(s, cmd, t=1.5):
    s.write((cmd+"\r\n").encode())
    s.flush()
    end=time.time()+t
    out=[]
    while time.time()<end:
        ln=s.readline().decode(errors="ignore").strip()
        if not ln: 
            continue
        out.append(ln)
        if OK.match(ln):
            break
    print(cmd, "=>", out)

with serial.Serial(PORT, BAUD, timeout=0.25) as s:
    # wake
    s.write(b"\r\n\r\n")
    time.sleep(0.2)
    s.reset_input_buffer()

    # controller info (как GUI часто делает)
    send(s, "$I", 2.0)

    # absolute positioning
    send(s, "G90", 1.0)

    # Включить “limit sensor LED” (в SDK часто есть M120 P1)
    send(s, "M120 P1", 1.0)

    # Попытка открыть iris “правильной командой” (как в SDK)
    send(s, "M114 P1", 1.5)

    # На всякий случай — запрос статуса
    s.write(b"?\r\n")
    time.sleep(0.2)
    print("STATUS:", s.read_all().decode(errors="ignore").strip())
