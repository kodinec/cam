import argparse, time
import serial

def read_lines(ser, timeout=1.2):
    end = time.time() + timeout
    out = []
    while time.time() < end:
        line = ser.readline().decode(errors="ignore").strip()
        if not line:
            continue
        out.append(line)
        low = line.lower()
        if low == "ok" or low.startswith("error:"):
            break
    return out

def send(ser, cmd, wait=1.2):
    ser.write((cmd.strip() + "\r\n").encode())
    ser.flush()
    return read_lines(ser, wait)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="e.g. /dev/cu.usbmodem14101")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--feed", type=float, default=200.0)
    ap.add_argument("--x_per_step", type=float, default=10.0, help="physical X units per logical zoom step")
    ap.add_argument("--set", type=int, help="set zoom 0..25")
    ap.add_argument("--delta", type=int, help="delta zoom +/-")
    ap.add_argument("--get", action="store_true", help="print status '?' only")
    ap.add_argument("--zoom_max", type=int, default=25)
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.25)
    try:
        # wake
        ser.write(b"\r\n\r\n")
        time.sleep(0.2)
        ser.reset_input_buffer()

        if args.get:
            print("\n".join(send(ser, "?", 1.0)))
            return

        if args.set is None and args.delta is None:
            raise SystemExit("use --set N or --delta +/-N (or --get)")

        z = args.set if args.set is not None else args.delta
        if args.set is None:
            # no persistent state: interpret delta as direct step for quick test
            # use small deltas like --delta 1 / --delta -1
            target = z * args.x_per_step
        else:
            z = max(0, min(args.zoom_max, z))
            target = z * args.x_per_step

        print("G90 ->", send(ser, "G90", 1.0))
        cmd = f"G1 X{target:.3f} F{args.feed:.1f}"  # X axis = Zoom1 (главный зум)
        print(cmd, "->", send(ser, cmd, 1.5))
        print("status ->", send(ser, "?", 1.0))

    finally:
        ser.close()

if __name__ == "__main__":
    main()
