import serial
import time

PORT = "/dev/cu.usbmodem6D86487550831"
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=0.2)

def send(cmd):
    ser.write((cmd + "\r\n").encode())
    time.sleep(0.1)
    while ser.in_waiting:
        print(ser.readline().decode().strip())

print("Reset controller")
ser.write(b"\x18")
time.sleep(1)

send("G90")

print("Open iris")
send("G1 A10 F100")

print("Set focus")
send("G1 Y10 F100")

print("Zoom wide")
send("G1 X0 F100")

print("\nCommands:")
print("  z = zoom in")
print("  x = zoom out")
print("  f = focus +")
print("  d = focus -")
print("  i = iris +")
print("  k = iris -")
print("  q = quit")

zoom = 0
focus = 10
iris = 10

while True:
    key = input("> ")

    if key == "q":
        break

    if key == "z":
        zoom += 2
        send(f"G1 X{zoom} F100")

    if key == "x":
        zoom -= 2
        send(f"G1 X{zoom} F100")

    if key == "f":
        focus += 1
        send(f"G1 Y{focus} F100")

    if key == "d":
        focus -= 1
        send(f"G1 Y{focus} F100")

    if key == "i":
        iris += 1
        send(f"G1 A{iris} F100")

    if key == "k":
        iris -= 1
        send(f"G1 A{iris} F100")

ser.close()
