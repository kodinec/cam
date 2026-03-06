import argparse

import usb.core


CT_BITS = {
    0: "Scanning Mode",
    1: "Auto-Exposure Mode",
    2: "Auto-Exposure Priority",
    3: "Exposure Time Absolute",
    4: "Exposure Time Relative",
    5: "Focus Absolute",
    6: "Focus Relative",
    7: "Iris Absolute",
    8: "Iris Relative",
    9: "Zoom Absolute",
    10: "Zoom Relative",
    11: "PanTilt Absolute",
    12: "PanTilt Relative",
    13: "Roll Absolute",
    14: "Roll Relative",
    16: "Focus Auto",
    17: "Privacy",
    18: "Focus Simple",
    19: "Window",
    20: "Region of Interest",
}


def parse_vc_descriptors(extra: bytes) -> dict:
    i = 0
    out = {"camera_terminal": None, "processing_unit": None, "extension_units": []}

    while i + 2 <= len(extra):
        bl = extra[i]
        if bl <= 0 or i + bl > len(extra):
            break
        chunk = extra[i : i + bl]
        i += bl

        if len(chunk) < 3:
            continue
        b_desc_type = chunk[1]
        b_subtype = chunk[2]
        if b_desc_type != 0x24:  # CS_INTERFACE
            continue

        # Input Terminal (camera terminal)
        if b_subtype == 0x02 and len(chunk) >= 15:
            term_id = chunk[3]
            term_type = int.from_bytes(chunk[4:6], "little")
            b_control_size = chunk[14]
            bm = chunk[15 : 15 + b_control_size]
            out["camera_terminal"] = {
                "id": term_id,
                "type": term_type,
                "control_size": b_control_size,
                "controls_raw_hex": bm.hex(),
                "controls_int": int.from_bytes(bm, "little") if bm else 0,
            }
            continue

        # Processing Unit
        if b_subtype == 0x05 and len(chunk) >= 8:
            unit_id = chunk[3]
            source_id = chunk[4]
            control_size = chunk[7]
            bm = chunk[8 : 8 + control_size]
            out["processing_unit"] = {
                "id": unit_id,
                "source_id": source_id,
                "control_size": control_size,
                "controls_raw_hex": bm.hex(),
                "controls_int": int.from_bytes(bm, "little") if bm else 0,
            }
            continue

        # Extension Unit
        if b_subtype == 0x06 and len(chunk) >= 24:
            unit_id = chunk[3]
            guid = chunk[4:20]
            n_controls = chunk[20]
            n_pins = chunk[21]
            if len(chunk) < 23 + n_pins:
                continue
            control_size = chunk[22 + n_pins]
            bm_start = 23 + n_pins
            bm = chunk[bm_start : bm_start + control_size]
            out["extension_units"].append(
                {
                    "id": unit_id,
                    "guid": guid.hex(),
                    "num_controls": n_controls,
                    "num_pins": n_pins,
                    "control_size": control_size,
                    "controls_raw_hex": bm.hex(),
                    "controls_int": int.from_bytes(bm, "little") if bm else 0,
                }
            )

    return out


def decode_ct_controls(mask: int) -> list[str]:
    enabled = []
    for bit, name in CT_BITS.items():
        if mask & (1 << bit):
            enabled.append(name)
    return enabled


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe UVC zoom capability from USB descriptors")
    ap.add_argument("--vid", default="2207", help="Vendor ID hex, default 2207")
    ap.add_argument("--pid", default="1005", help="Product ID hex, default 1005")
    args = ap.parse_args()

    vid = int(args.vid, 16)
    pid = int(args.pid, 16)

    dev = usb.core.find(idVendor=vid, idProduct=pid)
    if dev is None:
        print(f"Device {vid:04x}:{pid:04x} not found")
        return

    cfg = dev.get_active_configuration()
    vc_if = None
    vc_extra = b""
    for intf in cfg:
        if intf.bInterfaceClass == 0x0E and intf.bInterfaceSubClass == 0x01:
            vc_if = intf.bInterfaceNumber
            vc_extra = bytes(getattr(intf, "extra_descriptors", b""))
            break

    if vc_if is None:
        print("No UVC VideoControl interface found")
        return

    print(f"UVC VC interface: {vc_if}")
    parsed = parse_vc_descriptors(vc_extra)

    ct = parsed["camera_terminal"]
    if ct is None:
        print("Camera Terminal descriptor not found")
    else:
        mask = int(ct["controls_int"])
        print("\nCamera Terminal:")
        print(f"  id={ct['id']} type=0x{ct['type']:04x}")
        print(f"  bmControls={ct['controls_raw_hex']} (0x{mask:08x})")
        enabled = decode_ct_controls(mask)
        print("  enabled controls:", ", ".join(enabled) if enabled else "(none)")
        print(f"  zoom_absolute_supported={bool(mask & (1 << 9))}")
        print(f"  zoom_relative_supported={bool(mask & (1 << 10))}")

    pu = parsed["processing_unit"]
    if pu is not None:
        print("\nProcessing Unit:")
        print(f"  id={pu['id']} source={pu['source_id']}")
        print(f"  bmControls={pu['controls_raw_hex']} (0x{pu['controls_int']:08x})")

    if parsed["extension_units"]:
        print("\nExtension Units:")
        for xu in parsed["extension_units"]:
            print(
                f"  id={xu['id']} guid={xu['guid']} "
                f"num_controls={xu['num_controls']} bmControls={xu['controls_raw_hex']}"
            )
    else:
        print("\nExtension Units: none")

    print("\nConclusion:")
    if ct and not (ct["controls_int"] & (1 << 9)):
        print("  Standard UVC optical zoom is NOT exposed via Camera Terminal controls.")
        print("  If zoom exists, it is likely vendor-specific (Extension Unit / proprietary protocol).")
    else:
        print("  Standard UVC zoom appears available.")


if __name__ == "__main__":
    main()
