#!/usr/bin/env python3
import json
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

import serial
from serial import SerialException


OK_RE = re.compile(r"^(ok|error:.*|alarm:.*)$", re.IGNORECASE)
MPOS_RE = re.compile(r"MPos:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)", re.IGNORECASE)
WPOS_RE = re.compile(r"WPos:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)", re.IGNORECASE)
WCO_RE = re.compile(r"WCO:([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)", re.IGNORECASE)
PN_RE = re.compile(r"Pn:([A-Z]+)", re.IGNORECASE)


def env_str(key: str, default: str) -> str:
    value = os.getenv(key, "").strip()
    return value or default


def env_int(key: str, default: int) -> int:
    value = os.getenv(key, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(key: str, default: float) -> float:
    value = os.getenv(key, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key, "").strip()
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def parse4(regex: re.Pattern[str], line: str) -> tuple[float, float, float, float] | None:
    match = regex.search(line)
    if not match:
        return None
    return tuple(float(match.group(i)) for i in range(1, 5))


def parse_state(status_line: str) -> str | None:
    if not status_line.startswith("<") or "|" not in status_line:
        return None
    return status_line[1:].split("|", 1)[0]


def parse_mpos(status_line: str) -> tuple[float, float, float, float] | None:
    return parse4(MPOS_RE, status_line)


def parse_wco(status_line: str) -> tuple[float, float, float, float] | None:
    return parse4(WCO_RE, status_line)


def parse_wpos(status_line: str) -> tuple[float, float, float, float] | None:
    direct = parse4(WPOS_RE, status_line)
    if direct is not None:
        return direct
    mpos = parse_mpos(status_line)
    wco = parse_wco(status_line)
    if mpos is None or wco is None:
        return None
    return tuple(mpos[i] - wco[i] for i in range(4))


def parse_limits(status_line: str) -> set[str]:
    match = PN_RE.search(status_line)
    if not match:
        return set()
    return set(match.group(1).upper())


def first_fatal_line(lines: list[str]) -> str | None:
    for line in lines:
        lc = line.lower()
        if lc.startswith("error") or lc.startswith("alarm"):
            return line
    return None


@dataclass
class ZoomMap:
    path: str
    coord_space: str
    x_preload: float
    zoom_x: list[float]
    focus_y: list[float | None]
    limit_xy: list[str]
    source_points: int
    source_flagged_indices: list[int]
    selected_flagged: list[int]

    @property
    def max_index(self) -> int:
        return len(self.zoom_x) - 1

    def state(self, current_index: int, homed: bool, focus_fine_step: float) -> dict[str, Any]:
        return {
            "enabled": True,
            "path": self.path,
            "coordSpace": self.coord_space,
            "xPreload": self.x_preload,
            "points": len(self.zoom_x),
            "sourcePoints": self.source_points,
            "maxIndex": self.max_index,
            "currentIndex": current_index,
            "homed": homed,
            "focusFineStep": focus_fine_step,
            "sourceFlaggedIndices": list(self.source_flagged_indices),
            "selectedFlagged": list(self.selected_flagged),
        }


def load_zoom_map(path: str, steps: int, strict: bool) -> ZoomMap:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    zoom = data.get("zoomX")
    focus = data.get("focusY")
    limit_xy = data.get("limitXY", [])
    meta = data.get("meta", {})

    if not isinstance(zoom, list) or not zoom:
        raise ValueError(f"map {path} has empty zoomX")
    if not isinstance(focus, list):
        raise ValueError(f"map {path} has invalid focusY")
    if len(focus) != len(zoom):
        raise ValueError(f"map {path} has zoomX/focusY length mismatch")

    use_n = len(zoom)
    if steps > 0:
        if steps > len(zoom):
            raise ValueError(f"map {path} has {len(zoom)} zoom points, but CAM_MAP_STEPS={steps}")
        use_n = steps

    coord_space = str(meta.get("coord_space", "wpos")).strip().lower()
    if coord_space not in {"wpos", "mpos"}:
        raise ValueError(f"map {path} has unsupported coord_space={coord_space!r}")

    x_preload = float(meta.get("x_preload", 0.02))
    zoom_x = [float(value) for value in zoom[:use_n]]
    focus_y: list[float | None] = [None if value is None else float(value) for value in focus[:use_n]]

    selected_flagged: list[int] = []
    source_flagged_indices: list[int] = []
    selected_limits: list[str] = []
    for index in range(len(zoom)):
        flag = ""
        if index < len(limit_xy):
            flag = str(limit_xy[index]).strip().upper()
        if flag:
            source_flagged_indices.append(index)
        if index < use_n:
            selected_limits.append(flag)
            if flag:
                selected_flagged.append(index)

    if strict and selected_flagged:
        joined = ",".join(str(value) for value in selected_flagged)
        raise ValueError(f"selected map points are flagged with limitXY: {joined}")

    return ZoomMap(
        path=path,
        coord_space=coord_space,
        x_preload=x_preload,
        zoom_x=zoom_x,
        focus_y=focus_y,
        limit_xy=selected_limits,
        source_points=len(zoom),
        source_flagged_indices=source_flagged_indices,
        selected_flagged=selected_flagged,
    )


class PTZController:
    def __init__(self) -> None:
        self.listen = env_str("PTZ_API_LISTEN", "0.0.0.0:8081")
        self.serial_path = env_str("PTZ_SERIAL", "/dev/ttyACM0")
        self.serial_fallback = env_str("PTZ_SERIAL_FALLBACK", "/dev/serial/by-id/")
        self.serial_baud = env_int("PTZ_BAUD", 115200)
        self.map_feed = env_float("CAM_MAP_FEED", 180.0)
        self.focus_fine_step = env_float("CAM_FOCUS_FINE_STEP", 0.05)
        self.reset = env_bool("CAM_RESET", True)
        self.limit_led = env_bool("CAM_LIMIT_LED", True)
        self.iris_open = env_bool("CAM_IRIS_OPEN", True)
        self.home_focus = env_bool("CAM_HOME_FOCUS", True)
        self.home_timeout = env_float("CAM_HOME_TIMEOUT", 25.0)
        self.backoff_x = env_float("CAM_BACKOFF_X", 1.0)
        self.backoff_y = env_float("CAM_BACKOFF_Y", 0.5)
        self.backoff_feed = env_float("CAM_BACKOFF_FEED", 120.0)
        self.start_x = env_float("CAM_START_X", 0.0)
        self.start_y = env_float("CAM_START_Y", 0.0)
        self.goto_feed = env_float("CAM_GOTO_FEED", 200.0)
        self.auto_release = env_bool("CAM_AUTO_RELEASE", True)
        self.release_step_x = env_float("CAM_RELEASE_STEP_X", 0.2)
        self.release_step_y = env_float("CAM_RELEASE_STEP_Y", 0.2)
        self.release_max_steps = env_int("CAM_RELEASE_MAX_STEPS", 40)
        self.release_feed = env_float("CAM_RELEASE_FEED", 80.0)

        map_path = env_str("CAM_MAP_PATH", "/app/zoom25_focusmap.json")
        map_steps = env_int("CAM_MAP_STEPS", 8)
        strict_limits = env_bool("CAM_STRICT_MAP_LIMITS", True)
        self.zoom_map = load_zoom_map(map_path, map_steps, strict_limits)

        self.lock = threading.RLock()
        self.port: serial.Serial | None = None
        self.port_path = ""
        self.current_index = 0
        self.homed = False
        self.soft_wco: tuple[float, float, float, float] | None = None
        self.last_status_line = ""
        self.last_status_lines: list[str] = []

    def map_state(self) -> dict[str, Any]:
        return self.zoom_map.state(self.current_index, self.homed, self.focus_fine_step)

    def _resolve_serial_path(self) -> str:
        primary = self.serial_path.strip()
        fallback = self.serial_fallback.strip()
        if primary and os.path.exists(primary):
            return primary
        if fallback and fallback != primary and fallback != "/dev/serial/by-id/" and os.path.exists(fallback):
            return fallback
        if fallback == "/dev/serial/by-id/" and os.path.isdir(fallback):
            for name in sorted(os.listdir(fallback)):
                candidate = os.path.join(fallback, name)
                if os.path.exists(candidate):
                    return candidate
        return primary

    def _close_port(self) -> None:
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None

    def _ensure_port(self) -> serial.Serial:
        if self.port is not None and self.port.is_open:
            return self.port
        path = self._resolve_serial_path()
        if not path:
            raise RuntimeError("serial path is empty")
        try:
            self.port = serial.Serial(path, self.serial_baud, timeout=0.25)
            self.port_path = path
            self.port.write(b"\r\n\r\n")
            time.sleep(0.25)
            self.port.reset_input_buffer()
            return self.port
        except SerialException as exc:
            self._close_port()
            raise RuntimeError(f"open serial {path}: {exc}") from exc

    def _remember_status(self, status_line: str) -> None:
        self.last_status_line = status_line
        self.last_status_lines = [status_line]
        wco = parse_wco(status_line)
        if wco is not None:
            self.soft_wco = wco

    def _readline(self) -> str:
        port = self._ensure_port()
        try:
            line = port.readline().decode(errors="ignore").strip()
            return line
        except SerialException as exc:
            self._close_port()
            raise RuntimeError(str(exc)) from exc

    def _send_command(self, cmd: str, wait: float) -> list[str]:
        cmd = cmd.strip()
        if not cmd:
            raise ValueError("empty command")
        port = self._ensure_port()
        try:
            port.write((cmd + "\r\n").encode("utf-8"))
            port.flush()
        except SerialException as exc:
            self._close_port()
            raise RuntimeError(f"write {cmd!r} failed: {exc}") from exc

        out: list[str] = []
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            line = self._readline()
            if not line:
                continue
            out.append(line)
            if OK_RE.match(line):
                break

        fatal = first_fatal_line(out)
        if fatal is not None:
            raise RuntimeError(fatal)
        return out

    def _read_status(self) -> tuple[str, list[str]]:
        port = self._ensure_port()
        try:
            port.write(b"?\r\n")
            port.flush()
        except SerialException as exc:
            self._close_port()
            raise RuntimeError(f"write '?' failed: {exc}") from exc

        time.sleep(0.12)
        try:
            raw = port.read_all().decode(errors="ignore")
        except SerialException as exc:
            self._close_port()
            raise RuntimeError(str(exc)) from exc

        all_lines = [line.strip() for line in raw.splitlines() if line.strip()]
        fatal = first_fatal_line(all_lines)
        if fatal is not None:
            raise RuntimeError(fatal)

        status_lines = [line for line in all_lines if line.startswith("<")]
        if not status_lines:
            raise TimeoutError('wait status for "?": timeout')

        status_line = status_lines[-1]
        self._remember_status(status_line)
        self.last_status_lines = list(status_lines)
        return status_line, status_lines

    def _get_wpos(self, status_line: str) -> tuple[float, float, float, float] | None:
        wpos = parse_wpos(status_line)
        if wpos is not None:
            return wpos
        mpos = parse_mpos(status_line)
        if mpos is None or self.soft_wco is None:
            return None
        return tuple(mpos[i] - self.soft_wco[i] for i in range(4))

    def _wait_for_idle(self, timeout: float) -> tuple[str, list[str]]:
        deadline = time.monotonic() + timeout
        last_status = ""
        last_lines: list[str] = []
        while time.monotonic() < deadline:
            try:
                status_line, status_lines = self._read_status()
                last_status = status_line
                last_lines = status_lines
            except TimeoutError:
                time.sleep(0.06)
                continue
            state = parse_state(last_status)
            if state == "Idle":
                return last_status, last_lines
            if state and state.startswith("Alarm"):
                raise RuntimeError(f"Controller alarm: {last_status}")
            time.sleep(0.06)
        raise TimeoutError(f"timeout waiting for idle: {last_status}")

    def _move_abs_wpos(self, x: float | None, y: float | None, feed: float, timeout: float) -> tuple[list[str], list[str], str]:
        parts: list[str] = []
        if x is not None:
            parts.append(f"X{x:.3f}")
        if y is not None:
            parts.append(f"Y{y:.3f}")
        if not parts:
            return [], [], ""

        reply: list[str] = []
        reply.extend(self._send_command("G90", 1.0))
        reply.extend(self._send_command("G1 " + " ".join(parts) + f" F{feed:.1f}", 4.0))
        status_line, status_lines = self._wait_for_idle(timeout)
        return reply, status_lines, status_line

    def _move_to_mpos(self, target_x: float | None, target_y: float | None, feed: float, timeout: float) -> tuple[list[str], list[str], str]:
        status_line, _ = self._read_status()
        pos = parse_mpos(status_line)
        if pos is None:
            raise RuntimeError(f"cannot parse MPos from status: {status_line}")

        dx = None if target_x is None else target_x - pos[0]
        dy = None if target_y is None else target_y - pos[1]
        if dx is None and dy is None:
            return [], [status_line], status_line

        parts = ["G1"]
        if dx is not None:
            parts.append(f"X{dx:.3f}")
        if dy is not None:
            parts.append(f"Y{dy:.3f}")
        parts.append(f"F{feed:.1f}")

        reply: list[str] = []
        reply.extend(self._send_command("G91", 1.0))
        reply.extend(self._send_command(" ".join(parts), 4.0))
        reply.extend(self._send_command("G90", 1.0))
        idle_line, idle_lines = self._wait_for_idle(timeout)
        return reply, idle_lines, idle_line

    def _move_rel(self, dx: float | None, dy: float | None, feed: float, timeout: float) -> tuple[list[str], list[str], str]:
        if dx is None and dy is None:
            return [], [], ""
        parts = ["G1"]
        if dx is not None:
            parts.append(f"X{dx:.3f}")
        if dy is not None:
            parts.append(f"Y{dy:.3f}")
        parts.append(f"F{feed:.1f}")

        reply: list[str] = []
        reply.extend(self._send_command("G91", 1.0))
        reply.extend(self._send_command(" ".join(parts), 4.0))
        reply.extend(self._send_command("G90", 1.0))
        idle_line, idle_lines = self._wait_for_idle(timeout)
        return reply, idle_lines, idle_line

    def _release_limit_axis(self, axis: str, step: float, max_steps: int, feed: float) -> bool:
        axis = axis.upper().strip()
        if axis not in {"X", "Y"} or max_steps <= 0 or step == 0:
            return False
        step = abs(step)

        status_line, _ = self._read_status()
        if axis not in parse_limits(status_line):
            return True

        for direction in (1.0, -1.0):
            for _ in range(max_steps):
                dx = direction * step if axis == "X" else None
                dy = direction * step if axis == "Y" else None
                self._move_rel(dx, dy, feed, 10.0)
                status_line, _ = self._read_status()
                if axis not in parse_limits(status_line):
                    return True
        return False

    def _auto_release_limits(self) -> None:
        try:
            status_line, _ = self._read_status()
        except Exception as exc:
            logging.warning("auto-release skipped: initial status unavailable: %s", exc)
            return

        limits = parse_limits(status_line)
        if not limits:
            return

        ok_x = True
        ok_y = True
        if "X" in limits:
            ok_x = self._release_limit_axis("X", self.release_step_x, self.release_max_steps, self.release_feed)
        if "Y" in limits:
            ok_y = self._release_limit_axis("Y", self.release_step_y, self.release_max_steps, self.release_feed)

        status_line, _ = self._read_status()
        limits = parse_limits(status_line)
        if not ok_y or "Y" in limits:
            raise RuntimeError("could not release Y limit automatically")
        if not ok_x or "X" in limits:
            logging.warning("X limit is still active after auto-release")

    def status_response(self) -> tuple[int, dict[str, Any]]:
        with self.lock:
            response: dict[str, Any] = {
                "available": True,
                "mapState": self.map_state(),
            }
            try:
                status_line, status_lines = self._read_status()
            except Exception as exc:
                if self.last_status_line:
                    status_line = self.last_status_line
                    status_lines = list(self.last_status_lines)
                    response["warning"] = str(exc)
                else:
                    response["available"] = False
                    response["error"] = str(exc)
                    response["statusReply"] = ""
                    response["statusLines"] = []
                    return HTTPStatus.OK, response

            response["statusReply"] = status_line
            response["statusLines"] = status_lines
            mpos = parse_mpos(status_line)
            if mpos is not None:
                response["mposX"] = mpos[0]
                response["mposY"] = mpos[1]
            wpos = self._get_wpos(status_line)
            if wpos is not None:
                response["wposX"] = wpos[0]
                response["wposY"] = wpos[1]
            limits = "".join(sorted(parse_limits(status_line)))
            if limits:
                response["limits"] = limits
            return HTTPStatus.OK, response

    def run_start_flow(self) -> dict[str, Any]:
        with self.lock:
            flow = ["=== START FLOW ==="]
            port = self._ensure_port()

            if self.reset:
                flow.append("1) RESET")
                port.write(b"\x18")
                port.flush()
                time.sleep(1.0)
                port.reset_input_buffer()
            else:
                flow.append("1) RESET skipped")

            flow.append("2) UNLOCK ($X)")
            self._send_command("$X", 2.0)
            self._send_command("G90", 1.0)

            if self.limit_led:
                flow.append("3) LIMIT LED ON (M120 P1)")
                self._send_command("M120 P1", 1.5)
            else:
                flow.append("3) LIMIT LED skipped")

            if self.iris_open:
                flow.append("4) IRIS OPEN (M114 P1)")
                self._send_command("M114 P1", 1.5)
            else:
                flow.append("4) IRIS OPEN skipped")

            flow.append("5) HOME ZOOM ($HX)")
            self._send_command("$HX", 3.0)
            self._wait_for_idle(self.home_timeout)

            if self.home_focus:
                flow.append("6) HOME FOCUS ($HY)")
                self._send_command("$HY", 3.0)
                self._wait_for_idle(self.home_timeout)
            else:
                flow.append("6) HOME FOCUS skipped")

            flow.append("7) BACKOFF")
            self._move_rel(self.backoff_x, self.backoff_y, self.backoff_feed, 10.0)

            flow.append(f"8) GOTO START X={self.start_x:.3f} Y={self.start_y:.3f}")
            self._move_abs_wpos(self.start_x, self.start_y, self.goto_feed, 20.0)

            if self.auto_release:
                flow.append("8b) AUTO RELEASE LIMITS")
                self._auto_release_limits()
            else:
                flow.append("8b) AUTO RELEASE LIMITS skipped")

            flow.append("9) SET X0 Y0 (G92 X0 Y0)")
            self._send_command("G92 X0 Y0", 1.0)

            status_line = ""
            status_lines: list[str] = []
            try:
                status_line, status_lines = self._read_status()
            except Exception as exc:
                logging.warning("final status after home unavailable: %s", exc)

            self.current_index = 0
            self.homed = True

            return {
                "ok": True,
                "flow": flow,
                "statusReply": status_line,
                "statusLines": status_lines,
                "mapState": self.map_state(),
            }

    def goto_index(self, idx: int) -> dict[str, Any]:
        with self.lock:
            if not self.homed:
                raise RuntimeError("zoom map is not homed yet. Run /api/home first")
            if idx < 0 or idx > self.zoom_map.max_index:
                raise ValueError(f"index must be in range 0..{self.zoom_map.max_index}")

            flag = self.zoom_map.limit_xy[idx].strip()
            if flag:
                raise RuntimeError(f"map index {idx} is flagged with limitXY={flag}")

            target_x = self.zoom_map.zoom_x[idx]
            target_y = self.zoom_map.focus_y[idx]
            reply_lines: list[str] = []
            status_lines: list[str] = []
            status_reply = ""

            def move(x: float | None, y: float | None) -> None:
                nonlocal reply_lines, status_lines, status_reply
                if self.zoom_map.coord_space == "mpos":
                    reply, lines, status = self._move_to_mpos(x, y, self.map_feed, 20.0)
                else:
                    reply, lines, status = self._move_abs_wpos(x, y, self.map_feed, 20.0)
                reply_lines.extend(reply)
                if lines:
                    status_lines = lines
                    status_reply = status

            if self.zoom_map.x_preload > 0:
                move(target_x - abs(self.zoom_map.x_preload), None)
            move(target_x, None)
            if target_y is not None:
                move(None, target_y)

            if not status_reply:
                try:
                    status_reply, status_lines = self._read_status()
                except Exception:
                    status_reply = ""
                    status_lines = []

            self.current_index = idx
            response: dict[str, Any] = {
                "mapEnabled": True,
                "mapIndex": idx,
                "mapMaxIndex": self.zoom_map.max_index,
                "targetX": target_x,
                "coordSpace": self.zoom_map.coord_space,
                "xPreload": self.zoom_map.x_preload,
                "replyLines": reply_lines,
                "statusReply": status_reply,
                "statusLines": status_lines,
                "mapState": self.map_state(),
            }
            if target_y is not None:
                response["targetY"] = target_y
            return response

    def focus(self, set_value: float | None, delta: int | None) -> dict[str, Any]:
        with self.lock:
            if not self.homed:
                raise RuntimeError("zoom map is not homed yet. Run /api/home first")

            if delta is not None and delta not in {-1, 1}:
                raise ValueError("delta must be -1 or +1")

            if delta is not None:
                dy = float(delta) * self.focus_fine_step
                reply, status_lines, status_reply = self._move_rel(None, dy, self.map_feed, 10.0)
            else:
                assert set_value is not None
                if self.zoom_map.coord_space == "mpos":
                    reply, status_lines, status_reply = self._move_to_mpos(None, set_value, self.map_feed, 20.0)
                else:
                    reply, status_lines, status_reply = self._move_abs_wpos(None, set_value, self.map_feed, 20.0)

            response: dict[str, Any] = {
                "ok": True,
                "coordSpace": self.zoom_map.coord_space,
                "focusStep": self.focus_fine_step,
                "replyLines": reply,
                "statusReply": status_reply,
                "statusLines": status_lines,
                "mapState": self.map_state(),
            }
            if set_value is not None:
                response["targetY"] = set_value
            if delta is not None:
                response["delta"] = delta
            return response


class PTZRequestHandler(BaseHTTPRequestHandler):
    controller: PTZController

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.info("%s - %s", self.address_string(), fmt % args)

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid json: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("json body must be an object")
        return data

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self._write_json(HTTPStatus.OK, {"ok": True})
            return
        if path == "/api/status":
            status, payload = self.controller.status_response()
            self._write_json(status, payload)
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/home":
                result = self.controller.run_start_flow()
                try:
                    step0 = self.controller.goto_index(0)
                except Exception as exc:
                    self._write_json(
                        HTTPStatus.BAD_GATEWAY,
                        {
                            "error": str(exc),
                            "flowResult": result,
                            "afterHomeOK": True,
                            "mapState": self.controller.map_state(),
                        },
                    )
                    return
                result["step0"] = step0
                result["mapState"] = self.controller.map_state()
                self._write_json(HTTPStatus.OK, result)
                return

            body = self._read_json()
            if path == "/api/zoom":
                set_value = body.get("set")
                delta = body.get("delta")
                if (set_value is None) == (delta is None):
                    raise ValueError("provide exactly one of: set or delta")

                state = self.controller.map_state()
                max_index = int(state.get("maxIndex", -1))
                next_index = int(state.get("currentIndex", 0))

                if set_value is not None:
                    if not isinstance(set_value, int):
                        raise ValueError("set must be an integer")
                    if set_value < 0 or set_value > max_index:
                        raise ValueError(f"set must be in range 0..{max_index}")
                    next_index = set_value

                if delta is not None:
                    if not isinstance(delta, int) or delta not in {-1, 1}:
                        raise ValueError("delta must be -1 or +1")
                    next_index = max(0, min(max_index, next_index + delta))

                try:
                    payload = self.controller.goto_index(next_index)
                except ValueError as exc:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc), "mapState": self.controller.map_state()})
                    return
                except RuntimeError as exc:
                    self._write_json(HTTPStatus.CONFLICT, {"error": str(exc), "mapState": self.controller.map_state()})
                    return

                self._write_json(HTTPStatus.OK, payload)
                return

            if path == "/api/focus":
                set_value = body.get("set")
                delta = body.get("delta")
                if (set_value is None) == (delta is None):
                    raise ValueError("provide exactly one of: set or delta")
                if set_value is not None and not isinstance(set_value, (int, float)):
                    raise ValueError("set must be a number")
                if delta is not None and (not isinstance(delta, int) or delta not in {-1, 1}):
                    raise ValueError("delta must be -1 or +1")

                payload = self.controller.focus(None if set_value is None else float(set_value), delta)
                self._write_json(HTTPStatus.OK, payload)
                return

            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            logging.exception("request failed path=%s", path)
            status = HTTPStatus.BAD_GATEWAY
            if path == "/api/focus":
                status = HTTPStatus.BAD_GATEWAY
            if path == "/api/home":
                self._write_json(status, {"error": str(exc)})
                return
            self._write_json(status, {"error": str(exc), "mapState": self.controller.map_state()})


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    controller = PTZController()
    host, port_str = controller.listen.rsplit(":", 1)
    server = ThreadingHTTPServer((host, int(port_str)), PTZRequestHandler)
    PTZRequestHandler.controller = controller
    logging.info(
        "startup listen=%s serial=%s serial_fallback=%s baud=%d map=%s map_steps=%d coord=%s",
        controller.listen,
        controller.serial_path,
        controller.serial_fallback,
        controller.serial_baud,
        controller.zoom_map.path,
        len(controller.zoom_map.zoom_x),
        controller.zoom_map.coord_space,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
