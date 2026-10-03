import asyncio
import argparse
import json
import math
import os
import re
import socket
import struct
import time
from threading import Thread

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

app = FastAPI()
UDP_PORT = int(os.getenv("FORZA_UDP_PORT", "5555"))
WEB_PORT = int(os.getenv("FORZA_WEB_PORT", "8000"))
WEB_HOST = os.getenv("FORZA_WEB_HOST", "0.0.0.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STRATEGY_FILE = os.path.join(BASE_DIR, "strategies.json")

fh5_db, fm_db, track_db, strategies_db = {}, {}, {}, {}

state = {
    "last_packet": {
        "IsRaceOn": 0,
        "IsRec": False,
        "IsSessionRec": False,
        "AutoSave": False,
        "Car": "等待遥测数据...",
        "Track": "等待连接...",
        "Mode": "FM",
        "Gear": "N",
        "Speed": 0,
        "RPM": 0,
        "MaxRPM": 1,
        "Fuel": 100.0,
        "Lap": 0,
        "CurrentLap": "--:--.---",
        "BestLap": "--:--.---",
        "HistBestLap": "--:--.---",
        "OptimalLap": "--:--.---",
        "Delta": "--",
        "RemLaps": 99,
        "Accel": 0,
        "Brake": 0,
        "Pit": False,
        "ShiftNow": False,
        "FrontSlip": False,
        "RearSlip": False,
        "SteerInput": 0,
        "GForceLat": 0.0,
        "GForceLong": 0.0,
        "Temps": {"fl": 0, "fr": 0, "rl": 0, "rr": 0},
        "Wears": {"fl": 0, "fr": 0, "rl": 0, "rr": 0},
        "ThrottleCeil": 100,
        "Position": 0,
        "GhostLap": None,
    }
}

config = {
    "is_recording": False,
    "is_session_recording": False,
    "auto_save_best": False,
    "is_dyno": False,
}

DATA_MAP = [
    (0, "i", "IsRaceOn"), (4, "I", "TimestampMS"),
    (8, "f", "EngineMaxRpm"), (12, "f", "EngineIdleRpm"), (16, "f", "CurrentEngineRpm"),
    (20, "f", "Accel_X"), (24, "f", "Accel_Y"), (28, "f", "Accel_Z"),
    (32, "f", "Velocity_X"), (36, "f", "Velocity_Y"), (40, "f", "Velocity_Z"),
    (44, "f", "AngularVel_X"), (48, "f", "AngularVel_Y"), (52, "f", "AngularVel_Z"),
    (56, "f", "Yaw"), (60, "f", "Pitch"), (64, "f", "Roll"),
    (68, "f", "SuspTravel_FL"), (72, "f", "SuspTravel_FR"), (76, "f", "SuspTravel_RL"), (80, "f", "SuspTravel_RR"),
    (84, "f", "TireSlipRatio_FL"), (88, "f", "TireSlipRatio_FR"), (92, "f", "TireSlipRatio_RL"), (96, "f", "TireSlipRatio_RR"),
    (100, "f", "WheelRotationSpeed_FL"), (104, "f", "WheelRotationSpeed_FR"), (108, "f", "WheelRotationSpeed_RL"), (112, "f", "WheelRotationSpeed_RR"),
    (116, "f", "WheelOnRumble_FL"), (120, "f", "WheelOnRumble_FR"), (124, "f", "WheelOnRumble_RL"), (128, "f", "WheelOnRumble_RR"),
    (132, "f", "WheelInPuddle_FL"), (136, "f", "WheelInPuddle_FR"), (140, "f", "WheelInPuddle_RL"), (144, "f", "WheelInPuddle_RR"),
    (148, "f", "SurfaceRumble_FL"), (152, "f", "SurfaceRumble_FR"), (156, "f", "SurfaceRumble_RL"), (160, "f", "SurfaceRumble_RR"),
    (164, "f", "TireSlipAngle_FL"), (168, "f", "TireSlipAngle_FR"), (172, "f", "TireSlipAngle_RL"), (176, "f", "TireSlipAngle_RR"),
    (180, "f", "TireCombinedSlip_FL"), (184, "f", "TireCombinedSlip_FR"), (188, "f", "TireCombinedSlip_RL"), (192, "f", "TireCombinedSlip_RR"),
    (196, "f", "SuspTravelMeters_FL"), (200, "f", "SuspTravelMeters_FR"), (204, "f", "SuspTravelMeters_RL"), (208, "f", "SuspTravelMeters_RR"),
    (212, "i", "CarOrdinal"), (216, "i", "CarClass"), (220, "i", "CarPerformanceIndex"), (224, "i", "DrivetrainType"), (228, "i", "NumCylinders"),
    (232, "f", "Position_X"), (236, "f", "Position_Y"), (240, "f", "Position_Z"),
    (244, "f", "Speed"), (248, "f", "Power"), (252, "f", "Torque"),
    (256, "f", "TireTemp_FL"), (260, "f", "TireTemp_FR"), (264, "f", "TireTemp_RL"), (268, "f", "TireTemp_RR"),
    (272, "f", "Boost"), (276, "f", "Fuel"), (280, "f", "DistanceTraveled"), (284, "f", "BestLapTime"), (288, "f", "LastLapTime"),
    (292, "f", "CurrentLapTime"), (296, "f", "CurrentRaceTime"), (300, "H", "LapNumber"), (302, "B", "RacePosition"),
    (303, "B", "Accel"), (304, "B", "Brake"), (305, "B", "Clutch"), (306, "B", "Handbrake"), (307, "B", "Gear"), (308, "b", "Steer"),
    (309, "B", "NormalizedDrivingLine"), (310, "B", "NormalizedAIBrake"),
    (311, "f", "TireWear_FL"), (315, "f", "TireWear_FR"), (319, "f", "TireWear_RL"), (323, "f", "TireWear_RR"),
    (327, "i", "TrackOrdinal"),
]


def safe_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip()


def get_local_ip():
        try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                return ip
        except Exception:
                return "127.0.0.1"


def print_startup_banner():
        local_ip = get_local_ip()
        banner = f"""
=======================================================================
    FORZA HUD FREE - Telemetry Engine Online
=======================================================================

[数据接收]
    - UDP 监听端口: {UDP_PORT}
    - 请在游戏 Data Out 设置为: 127.0.0.1:{UDP_PORT}

[访问地址]
    - 主 HUD: http://{local_ip}:{WEB_PORT}/
    - OBS Overlay: http://127.0.0.1:{WEB_PORT}/obs

[启动参数]
    - --port      Web 端口 (默认 {WEB_PORT})
    - --udp-port  遥测 UDP 端口 (默认 {UDP_PORT})
    - --host      Web Host (默认 {WEB_HOST})

=======================================================================
"""
        print(banner)


def load_dbs():
    global fh5_db, fm_db, track_db, strategies_db

    def _load_json(filename, default):
        path = os.path.join(BASE_DIR, filename)
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    fh5_db = _load_json("fh5_cars.json", {})
    fm_db = _load_json("fm_cars.json", {})
    track_db = _load_json("Track_Name.json", {})
    strategies_db = _load_json("strategies.json", {})


def save_strategies():
    with open(STRATEGY_FILE, "w", encoding="utf-8") as f:
        json.dump(strategies_db, f, ensure_ascii=False, indent=2)


def format_lap_time(seconds):
    try:
        seconds = float(seconds)
    except Exception:
        return "--:--.---"
    if seconds <= 0 or math.isnan(seconds):
        return "--:--.---"
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:06.3f}"


def get_packet_value(packet, raw, name, default=0):
    dash_offset = 12 if len(raw) == 324 else 0
    for offset, fmt, field_name in DATA_MAP:
        if field_name != name:
            continue
        if dash_offset == 12 and offset >= 232:
            shifted = offset + dash_offset
            size = struct.calcsize("<" + fmt)
            if len(raw) >= shifted + size:
                v = struct.unpack("<" + fmt, raw[shifted:shifted + size])[0]
                return round(v, 5) if fmt == "f" else v
        if name in packet:
            return packet.get(name, default)
        size = struct.calcsize("<" + fmt)
        if len(raw) >= offset + size:
            v = struct.unpack("<" + fmt, raw[offset:offset + size])[0]
            return round(v, 5) if fmt == "f" else v
        return default
    return default


def predict_throttle_ceiling(packet, raw):
    slip_rl = float(get_packet_value(packet, raw, "TireCombinedSlip_RL", 0) or 0)
    slip_rr = float(get_packet_value(packet, raw, "TireCombinedSlip_RR", 0) or 0)
    rear_slip = max(slip_rl, slip_rr)
    speed_kmh = float(get_packet_value(packet, raw, "Speed", 0) or 0) * 3.6

    if speed_kmh < 60:
        target_max = 1.28
    elif speed_kmh < 120:
        target_max = 1.20
    else:
        target_max = 1.10

    if rear_slip <= target_max:
        return 100

    over = (rear_slip - target_max) / max(target_max, 0.01)
    ceil = 90 - min(55, over * 120)
    return int(max(20, min(100, round(ceil))))


def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))

    while True:
        try:
            raw, _ = sock.recvfrom(1024)
            if len(raw) < 232:
                continue

            is_fm = len(raw) >= 331
            is_race_on = struct.unpack("<f", raw[0:4])[0] > 0
            if not is_race_on:
                state["last_packet"]["IsRaceOn"] = 0
                continue

            packet = {}
            for offset, fmt, name in DATA_MAP:
                size = struct.calcsize("<" + fmt)
                if len(raw) >= offset + size:
                    val = struct.unpack("<" + fmt, raw[offset:offset + size])[0]
                    packet[name] = round(val, 5) if fmt == "f" else val

            acc = float(get_packet_value(packet, raw, "Accel", 0)) / 2.55
            brk = float(get_packet_value(packet, raw, "Brake", 0)) / 2.55
            throttle_ceil = predict_throttle_ceiling(packet, raw)
            steer_raw = int(get_packet_value(packet, raw, "Steer", 0) or 0)
            steer_pct = int(max(-100, min(100, round(steer_raw / 1.27))))
            g_lat = round(float(packet.get("Accel_X", 0.0)) / 9.81, 3)
            g_long = round(float(packet.get("Accel_Z", 0.0)) / 9.81, 3)

            if is_fm:
                car_id = packet.get("CarOrdinal", 0)
                track_id = packet.get("TrackOrdinal", 0)
                car_name = fm_db.get(str(car_id), f"Car_{car_id}")
                track_name = track_db.get(str(track_id), f"Track_{track_id}")
                lap = int(packet.get("LapNumber", 0)) + 1
                curr_lap = format_lap_time(packet.get("CurrentLapTime", 0))
                best_lap = format_lap_time(packet.get("BestLapTime", 0))
            else:
                car_id = get_packet_value(packet, raw, "CarOrdinal", 0)
                car_name = fh5_db.get(str(car_id), f"Car_{car_id}")
                track_name = "FH5"
                lap = int(get_packet_value(packet, raw, "LapNumber", 0) or 0) + 1
                curr_lap = format_lap_time(get_packet_value(packet, raw, "CurrentLapTime", 0) or 0)
                best_lap = format_lap_time(get_packet_value(packet, raw, "BestLapTime", 0) or 0)

            speed_mps = float(get_packet_value(packet, raw, "Speed", 0) or 0)
            if speed_mps <= 0:
                vx = float(packet.get("Velocity_X", 0.0))
                vy = float(packet.get("Velocity_Y", 0.0))
                vz = float(packet.get("Velocity_Z", 0.0))
                speed_mps = math.sqrt(vx * vx + vy * vy + vz * vz)

            front_slip = (float(packet.get("TireCombinedSlip_FL", 0)) > 1.2 or float(packet.get("TireCombinedSlip_FR", 0)) > 1.2) and brk > 15
            rear_slip = (float(packet.get("TireCombinedSlip_RL", 0)) > 1.5 or float(packet.get("TireCombinedSlip_RR", 0)) > 1.5) and acc > 30

            fuel_pct = round(float(get_packet_value(packet, raw, "Fuel", 0) or 0) * 100, 1)
            wears = {
                "fl": round(float(get_packet_value(packet, raw, "TireWear_FL", 0) or 0) * 100, 1),
                "fr": round(float(get_packet_value(packet, raw, "TireWear_FR", 0) or 0) * 100, 1),
                "rl": round(float(get_packet_value(packet, raw, "TireWear_RL", 0) or 0) * 100, 1),
                "rr": round(float(get_packet_value(packet, raw, "TireWear_RR", 0) or 0) * 100, 1),
            }

            state["last_packet"] = {
                **state["last_packet"],
                "IsRaceOn": 1,
                "IsRec": config["is_recording"],
                "IsSessionRec": config["is_session_recording"],
                "AutoSave": config["auto_save_best"],
                "Mode": "FM" if is_fm else "FH5",
                "Car": car_name,
                "Track": track_name,
                "Lap": lap,
                "CurrentLap": curr_lap,
                "BestLap": best_lap,
                "HistBestLap": best_lap,
                "OptimalLap": "--:--.---",
                "Delta": "--",
                "Gear": "R" if int(get_packet_value(packet, raw, "Gear", 11)) == 0 else ("N" if int(get_packet_value(packet, raw, "Gear", 11)) == 11 else str(int(get_packet_value(packet, raw, "Gear", 11)))),
                "Speed": int(speed_mps * 3.6),
                "RPM": int(packet.get("CurrentEngineRpm", 0)),
                "MaxRPM": int(packet.get("EngineMaxRpm", 1) or 1),
                "Accel": int(acc),
                "Brake": int(brk),
                "Fuel": fuel_pct,
                "RemLaps": 99,
                "FrontSlip": front_slip,
                "RearSlip": rear_slip,
                "SteerInput": steer_pct,
                "GForceLat": g_lat,
                "GForceLong": g_long,
                "ThrottleCeil": throttle_ceil,
                "Position": int(get_packet_value(packet, raw, "RacePosition", 0) or 0),
                "Temps": {
                    "fl": round((float(get_packet_value(packet, raw, "TireTemp_FL", 32)) - 32) * 5 / 9),
                    "fr": round((float(get_packet_value(packet, raw, "TireTemp_FR", 32)) - 32) * 5 / 9),
                    "rl": round((float(get_packet_value(packet, raw, "TireTemp_RL", 32)) - 32) * 5 / 9),
                    "rr": round((float(get_packet_value(packet, raw, "TireTemp_RR", 32)) - 32) * 5 / 9),
                },
                "Wears": wears,
                "GhostLap": None,
            }
        except Exception:
            pass


@app.get("/")
async def home():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))


@app.get("/obs")
async def obs_page():
    return FileResponse(os.path.join(BASE_DIR, "obs.html"))


@app.get("/health")
async def health_check():
    return {
        "ok": True,
        "web_host": WEB_HOST,
        "web_port": WEB_PORT,
        "udp_port": UDP_PORT,
    }


@app.post("/api/dyno")
async def toggle_dyno(req: Request):
    data = await req.json()
    config["is_dyno"] = bool(data.get("state", False))
    return {"success": True, "is_dyno": config["is_dyno"]}


@app.get("/api/strategy/{track}")
async def get_strategy(track: str):
    return {"strategies": strategies_db.get(track, [])}


@app.post("/api/strategy/{track}")
async def save_strategy(track: str, req: Request):
    payload = await req.json()
    strategies_db.setdefault(track, []).append(payload)
    save_strategies()
    return {"success": True}


@app.delete("/api/strategy/{track}/{index}")
async def delete_strategy(track: str, index: int):
    arr = strategies_db.get(track, [])
    if 0 <= index < len(arr):
        arr.pop(index)
        strategies_db[track] = arr
        save_strategies()
    return {"success": True}


@app.websocket("/ws")
async def ws_handler(ws: WebSocket):
    await ws.accept()

    async def send_loop():
        while True:
            await ws.send_json(state["last_packet"])
            await asyncio.sleep(0.04)

    async def recv_loop():
        while True:
            data = await ws.receive_json()
            cmd = data.get("cmd")
            if cmd == "toggle_rec":
                config["is_recording"] = bool(data.get("val", False))
            elif cmd == "toggle_session_rec":
                config["is_session_recording"] = bool(data.get("val", False))
            elif cmd == "toggle_save":
                config["auto_save_best"] = bool(data.get("val", False))
            elif cmd == "set_active_strategy":
                pass
            elif cmd == "update_mapping":
                payload = data.get("payload", {})
                m_id = str(payload.get("id", "")).strip()
                name = str(payload.get("name", "")).strip()
                m_type = payload.get("type")
                game = payload.get("game", "FM")
                if m_id and name:
                    if m_type == "car":
                        db = fm_db if game == "FM" else fh5_db
                        db[m_id] = name
                        filename = "fm_cars.json" if game == "FM" else "fh5_cars.json"
                        with open(os.path.join(BASE_DIR, filename), "w", encoding="utf-8") as f:
                            json.dump(db, f, ensure_ascii=False, indent=2)
                    elif m_type == "track":
                        track_db[m_id] = name
                        with open(os.path.join(BASE_DIR, "Track_Name.json"), "w", encoding="utf-8") as f:
                            json.dump(track_db, f, ensure_ascii=False, indent=2)

    try:
        await asyncio.gather(send_loop(), recv_loop())
    except WebSocketDisconnect:
        return
    except Exception:
        return


@app.get("/{filename:path}")
async def static_assets(filename: str):
    path = os.path.join(BASE_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path)
    return {"error": "Not found"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Forza HUD Free server")
    parser.add_argument("--port", type=int, default=WEB_PORT, help="Web 服务端口")
    parser.add_argument("--udp-port", type=int, default=UDP_PORT, help="遥测 UDP 端口")
    parser.add_argument("--host", type=str, default=WEB_HOST, help="Web 监听地址")
    args = parser.parse_args()

    UDP_PORT = args.udp_port
    WEB_PORT = args.port
    WEB_HOST = args.host

    load_dbs()
    print_startup_banner()
    Thread(target=udp_listener, daemon=True).start()
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT, log_level="warning")
