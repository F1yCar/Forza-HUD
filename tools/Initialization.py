import socket
import struct
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from threading import Thread
from pathlib import Path
import uvicorn

app = FastAPI()

UDP_PORT = 5555
state = {"last_packet": {}}

# Forza 官方数据结构映射表：(偏移量, 数据类型, 字段名称)
# 类型代码: 'i'=整数, 'I'=无符号整数, 'f'=浮点数, 'B'=无符号单字节, 'b'=有符号单字节, 'H'=无符号双字节
DATA_MAP = [
    (0, 'i', "IsRaceOn"), (4, 'I', "TimestampMS"),
    (8, 'f', "EngineMaxRpm"), (12, 'f', "EngineIdleRpm"), (16, 'f', "CurrentEngineRpm"),
    (20, 'f', "Accel_X"), (24, 'f', "Accel_Y"), (28, 'f', "Accel_Z"),
    (32, 'f', "Velocity_X"), (36, 'f', "Velocity_Y"), (40, 'f', "Velocity_Z"),
    (44, 'f', "AngularVel_X"), (48, 'f', "AngularVel_Y"), (52, 'f', "AngularVel_Z"),
    (56, 'f', "Yaw"), (60, 'f', "Pitch"), (64, 'f', "Roll"),
    (68, 'f', "SuspTravel_FL"), (72, 'f', "SuspTravel_FR"), (76, 'f', "SuspTravel_RL"), (80, 'f', "SuspTravel_RR"),
    (84, 'f', "TireSlipRatio_FL"), (88, 'f', "TireSlipRatio_FR"), (92, 'f', "TireSlipRatio_RL"), (96, 'f', "TireSlipRatio_RR"),
    (100, 'f', "WheelRotSpeed_FL"), (104, 'f', "WheelRotSpeed_FR"), (108, 'f', "WheelRotSpeed_RL"), (112, 'f', "WheelRotSpeed_RR"),
    (116, 'i', "WheelOnRumble_FL"), (120, 'i', "WheelOnRumble_FR"), (124, 'i', "WheelOnRumble_RL"), (128, 'i', "WheelOnRumble_RR"),
    (132, 'f', "PuddleDepth_FL"), (136, 'f', "PuddleDepth_FR"), (140, 'f', "PuddleDepth_RL"), (144, 'f', "PuddleDepth_RR"),
    (148, 'f', "SurfaceRumble_FL"), (152, 'f', "SurfaceRumble_FR"), (156, 'f', "SurfaceRumble_RL"), (160, 'f', "SurfaceRumble_RR"),
    (164, 'f', "TireSlipAngle_FL"), (168, 'f', "TireSlipAngle_FR"), (172, 'f', "TireSlipAngle_RL"), (176, 'f', "TireSlipAngle_RR"),
    (180, 'f', "TireCombinedSlip_FL"), (184, 'f', "TireCombinedSlip_FR"), (188, 'f', "TireCombinedSlip_RL"), (192, 'f', "TireCombinedSlip_RR"),
    (196, 'f', "SuspTravelMeters_FL"), (200, 'f', "SuspTravelMeters_FR"), (204, 'f', "SuspTravelMeters_RL"), (208, 'f', "SuspTravelMeters_RR"),
    (212, 'i', "CarOrdinal"), (216, 'i', "CarClass"), (220, 'i', "CarPerformanceIndex"), (224, 'i', "DrivetrainType"), (228, 'i', "NumCylinders"),
    (232, 'f', "Position_X"), (236, 'f', "Position_Y"), (240, 'f', "Position_Z"),
    (244, 'f', "Speed_mps"), (248, 'f', "Power_Watts"), (252, 'f', "Torque_Nm"),
    (256, 'f', "TireTemp_FL"), (260, 'f', "TireTemp_FR"), (264, 'f', "TireTemp_RL"), (268, 'f', "TireTemp_RR"),
    (272, 'f', "Boost"), (276, 'f', "Fuel"), (280, 'f', "DistanceTraveled"),
    (284, 'f', "BestLapTime"), (288, 'f', "LastLapTime"), (292, 'f', "CurrentLapTime"), (296, 'f', "CurrentRaceTime"),
    (300, 'H', "LapNumber"), (302, 'B', "RacePosition"),
    (303, 'B', "Accel_Input"), (304, 'B', "Brake_Input"), (305, 'B', "Clutch_Input"), (306, 'B', "HandBrake_Input"),
    (307, 'B', "Gear"), (308, 'b', "Steer_Input"), (309, 'b', "NormDrivingLine"), (310, 'b', "NormAIBrakeDiff")
]

def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"全量数据采集器已启动...")

    while True:
        try:
            raw, _ = sock.recvfrom(1024)
            L = len(raw)
            if L < 232: continue

            packet = {"000_PacketLength": L}

            # 遍历官方字典，自动提取所有存在的数据
            for offset, fmt, name in DATA_MAP:
                size = struct.calcsize('<' + fmt)
                if L >= offset + size:
                    val = struct.unpack('<' + fmt, raw[offset:offset+size])[0]
                    if fmt == 'f': val = round(val, 3) # 浮点数保留三位小数防抖
                    packet[f"{offset:03d}_{name}"] = val
            
            # 如果是 FM 的 331 字节长包，将剩下的未知数据原样列出
            if L > 311:
                for i in range(311, L):
                    packet[f"{i:03d}_RawByte"] = raw[i]

            state["last_packet"] = packet
        except Exception as e:
            pass

@app.get("/")
async def get_index(): return FileResponse(Path(__file__).resolve().with_name('Initialization.html'))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            if state["last_packet"]:
                await websocket.send_json(state["last_packet"])
            await asyncio.sleep(0.05)
    except: pass

if __name__ == "__main__":
    Thread(target=udp_listener, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="error")