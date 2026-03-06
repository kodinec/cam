import argparse
import json
import os
import time


def build_linear_zoom(tele_x: float, points: int) -> list[float]:
    if points < 2:
        return [0.0]
    step = tele_x / float(points - 1)
    return [round(step * i, 6) for i in range(points)]


def init_data(path: str, points: int, tele_x: float | None) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "zoomX" in data and "focusY" in data:
            data = normalize_data(data, points)
            return data

    zoom_x = build_linear_zoom(tele_x if tele_x is not None else 0.0, points)
    focus_y = [None] * points
    return {
        "meta": {
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "points": points,
            "tele_x": 0.0 if tele_x is None else float(tele_x),
            "zoom_step": 0.0 if points < 2 else (0.0 if tele_x is None else float(tele_x) / float(points - 1)),
            "coord_space": "wpos",
            "notes": "Manual map builder. Fill idx/x/y manually.",
        },
        "zoomX": zoom_x,
        "focusY": focus_y,
        "limitXY": [""] * points,
    }


def normalize_data(data: dict, points: int) -> dict:
    zoom_raw = data.get("zoomX", [])
    focus_raw = data.get("focusY", [])
    lim_raw = data.get("limitXY", [])

    zoom: list[float] = []
    focus: list[float | None] = []
    lim: list[str] = []

    for i in range(points):
        if i < len(zoom_raw):
            try:
                zoom.append(float(zoom_raw[i]))
            except (TypeError, ValueError):
                zoom.append(0.0)
        else:
            zoom.append(0.0)

        if i < len(focus_raw):
            v = focus_raw[i]
            if v is None:
                focus.append(None)
            else:
                try:
                    focus.append(float(v))
                except (TypeError, ValueError):
                    focus.append(None)
        else:
            focus.append(None)

        if i < len(lim_raw) and isinstance(lim_raw[i], str):
            lim.append(lim_raw[i].strip().upper())
        else:
            lim.append("")

    meta = data.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}
    meta["points"] = points

    return {"meta": meta, "zoomX": zoom, "focusY": focus, "limitXY": lim}


def save_data(path: str, data: dict) -> None:
    data["meta"]["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def map_warnings(zoom_x: list[float], focus_y: list[float | None]) -> list[str]:
    warnings: list[str] = []
    if len(zoom_x) != len(focus_y):
        warnings.append("zoomX/focusY length mismatch")
        return warnings

    for i in range(1, len(zoom_x)):
        dx = zoom_x[i] - zoom_x[i - 1]
        if abs(dx) < 1e-9:
            warnings.append(f"duplicate zoomX at {i-1}/{i}: {zoom_x[i]:.3f}")
        elif dx < 0:
            warnings.append(f"non-monotonic zoomX at {i-1}/{i}: {zoom_x[i-1]:.3f}->{zoom_x[i]:.3f}")

    filled = sum(v is not None for v in focus_y)
    if filled < len(focus_y):
        warnings.append(f"focusY filled: {filled}/{len(focus_y)}")

    for i in range(1, len(focus_y)):
        y0 = focus_y[i - 1]
        y1 = focus_y[i]
        if y0 is None or y1 is None:
            continue
        dy = y1 - y0
        if abs(dy) > 1.0:
            warnings.append(f"large focus jump {i-1}->{i}: {y0:.3f}->{y1:.3f} (dy={dy:.3f})")
    return warnings


def print_help(max_index: int) -> None:
    print("\nCommands:")
    print(f"  set i x y      set point i (0..{max_index})")
    print(f"  x i v          set zoomX[i]")
    print(f"  y i v          set focusY[i]")
    print(f"  clr i          clear focusY[i]")
    print("  bulk           paste lines: i x y (empty line to finish)")
    print("  tele v         rebuild linear zoomX from tele value")
    print("  list           print table")
    print("  check          validate map")
    print("  save           save JSON")
    print("  q              quit\n")


def print_table(data: dict) -> None:
    print("idx\tX\t\tY")
    for i, x in enumerate(data["zoomX"]):
        y = data["focusY"][i]
        ys = "-" if y is None else f"{y:.3f}"
        print(f"{i:02d}\t{x:.3f}\t{ys}")


def parse_int(token: str) -> int:
    return int(token)


def parse_float(token: str) -> float:
    return float(token)


def apply_set(data: dict, idx: int, x: float, y: float) -> None:
    data["zoomX"][idx] = round(float(x), 3)
    data["focusY"][idx] = round(float(y), 3)
    data["limitXY"][idx] = ""


def main() -> None:
    ap = argparse.ArgumentParser(description="Minimal manual builder for zoom/focus map JSON")
    ap.add_argument("--out", default="/Users/codinec/cam/zoom25_focusmap.json")
    ap.add_argument("--points", type=int, default=25)
    ap.add_argument("--tele-x", type=float, default=None, help="initial linear zoom end value")
    ap.add_argument("--autosave", action="store_true", default=True)
    ap.add_argument("--no-autosave", dest="autosave", action="store_false")
    args = ap.parse_args()

    if args.points < 2:
        raise ValueError("--points must be >= 2")

    data = init_data(args.out, args.points, args.tele_x)
    max_index = args.points - 1

    print(f"Map file: {args.out}")
    print(f"Points: {args.points} (0..{max_index})")
    print_help(max_index)
    print_table(data)

    while True:
        cmd = input("> ").strip()
        if not cmd:
            continue
        low = cmd.lower()
        parts = cmd.split()

        if low in {"q", "quit", "exit"}:
            break

        if low == "help":
            print_help(max_index)
            continue

        if low == "list":
            print_table(data)
            continue

        if low == "check":
            warns = map_warnings(data["zoomX"], data["focusY"])
            if not warns:
                print("Map check: OK")
            else:
                print("Map check warnings:")
                for w in warns:
                    print("  -", w)
            continue

        if low == "save":
            save_data(args.out, data)
            print(f"Saved: {args.out}")
            continue

        if low == "bulk":
            print("Paste lines: i x y  (empty line to finish)")
            changed = 0
            while True:
                line = input("bulk> ").strip()
                if not line:
                    break
                cols = line.split()
                if len(cols) != 3:
                    print("  skip: need exactly 3 values")
                    continue
                try:
                    i = parse_int(cols[0])
                    x = parse_float(cols[1])
                    y = parse_float(cols[2])
                except ValueError:
                    print("  skip: parse error")
                    continue
                if i < 0 or i > max_index:
                    print(f"  skip: index out of range 0..{max_index}")
                    continue
                apply_set(data, i, x, y)
                changed += 1
            print(f"Bulk updated: {changed} points")
            if args.autosave and changed > 0:
                save_data(args.out, data)
                print(f"Autosaved: {args.out}")
            continue

        if parts and parts[0].lower() == "tele" and len(parts) == 2:
            try:
                tele = parse_float(parts[1])
            except ValueError:
                print("Use: tele <value>")
                continue
            data["zoomX"] = build_linear_zoom(tele, args.points)
            data["meta"]["tele_x"] = tele
            data["meta"]["zoom_step"] = tele / float(args.points - 1)
            print(f"zoomX rebuilt from tele={tele:.3f}")
            if args.autosave:
                save_data(args.out, data)
                print(f"Autosaved: {args.out}")
            continue

        if parts and parts[0].lower() == "set" and len(parts) == 4:
            try:
                i = parse_int(parts[1])
                x = parse_float(parts[2])
                y = parse_float(parts[3])
            except ValueError:
                print("Use: set <idx> <x> <y>")
                continue
            if i < 0 or i > max_index:
                print(f"Index range: 0..{max_index}")
                continue
            apply_set(data, i, x, y)
            print(f"set[{i}] X={x:.3f} Y={y:.3f}")
            if args.autosave:
                save_data(args.out, data)
                print(f"Autosaved: {args.out}")
            continue

        if parts and parts[0].lower() == "x" and len(parts) == 3:
            try:
                i = parse_int(parts[1])
                x = parse_float(parts[2])
            except ValueError:
                print("Use: x <idx> <value>")
                continue
            if i < 0 or i > max_index:
                print(f"Index range: 0..{max_index}")
                continue
            data["zoomX"][i] = round(x, 3)
            print(f"zoomX[{i}]={x:.3f}")
            if args.autosave:
                save_data(args.out, data)
                print(f"Autosaved: {args.out}")
            continue

        if parts and parts[0].lower() == "y" and len(parts) == 3:
            try:
                i = parse_int(parts[1])
                y = parse_float(parts[2])
            except ValueError:
                print("Use: y <idx> <value>")
                continue
            if i < 0 or i > max_index:
                print(f"Index range: 0..{max_index}")
                continue
            data["focusY"][i] = round(y, 3)
            data["limitXY"][i] = ""
            print(f"focusY[{i}]={y:.3f}")
            if args.autosave:
                save_data(args.out, data)
                print(f"Autosaved: {args.out}")
            continue

        if parts and parts[0].lower() == "clr" and len(parts) == 2:
            try:
                i = parse_int(parts[1])
            except ValueError:
                print("Use: clr <idx>")
                continue
            if i < 0 or i > max_index:
                print(f"Index range: 0..{max_index}")
                continue
            data["focusY"][i] = None
            data["limitXY"][i] = ""
            print(f"focusY[{i}] cleared")
            if args.autosave:
                save_data(args.out, data)
                print(f"Autosaved: {args.out}")
            continue

        print_help(max_index)

    save_data(args.out, data)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
