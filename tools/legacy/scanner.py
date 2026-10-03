import socket
import struct
import asyncio
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from threading import Thread
import uvicorn

app = FastAPI()

UDP_PORT = 5555
state = {"last_packet": {}}

# --- 极简前端探针页面 ---
HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>FM23 V3 协议显微镜</title>
    <style>
        body { background: #050505; color: #0f0; font-family: monospace; padding: 20px; }
        #status { color: #ff0; font-size: 1.2em; border-bottom: 1px dashed #333; padding-bottom: 10px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 8px; margin-top: 20px; }
        .cell { background: #111; padding: 6px 10px; border: 1px solid #333; border-radius: 4px; display: flex; justify-content: space-between; }
        .key { color: #888; }
        .highlight { background: #220; border-color: #aa0; color: #ff0; font-weight: bold; }
        .scan { border-color: #05f; color: #5af; }
    </style>
</head>
<body>
    <div id="status">等待游戏 UDP 数据 (端口 5555)...</div>
    <div id="data" class="grid"></div>
    <script>
        const ws = new WebSocket(`ws://${window.location.host}/ws`);
        const statusDiv = document.getElementById('status');
        const dataDiv = document.getElementById('data');

        ws.onmessage = (e) => {
            const d = JSON.parse(e.data);
            statusDiv.innerText = `数据接收中 | 包长度: ${d["000_PacketLength"]} Bytes | 刷新率: 实时`;
            
            let html = "";
            const keys = Object.keys(d).sort(); 
            keys.forEach(key => {
                if (key === "000_PacketLength") return;
                const isTarget = key.includes("FM23");
                const isScan = key.includes("Scan");
                let cls = isTarget ? 'highlight' : (isScan ? 'scan' : '');
                html += `<div class="cell ${cls}">
                            <span class="key">${key}</span>
                            <span>${d[key]}</span>
                         </div>`;
            });
            dataDiv.innerHTML = html;
        };
    </script>
</body>
</html>
"""

DATA_MAP = [
    (0, 'i', "IsRaceOn"), (16, 'f', "RPM"), (244, 'f', "Speed"), 
    (300, 'H', "Lap"), (307, 'B', "Gear"),
    (84, 'f', "TireSlip_FL"), (88, 'f', "TireSlip_FR"), (92, 'f', "TireSlip_RL"), (96, 'f', "TireSlip_RR"),
    # FM2023 专属 311 强攻区域
    (311, 'f', "FM23_Wear_FL"), (315, 'f', "FM23_Wear_FR"), 
    (319, 'f', "FM23_Wear_RL"), (323, 'f', "FM23_Wear_RR"),
    (327, 'i', "FM23_TrackOrdinal")
]

def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print("UDP 探针监听已启动，等待数据...")

    while True:
        try:
            raw, _ = sock.recvfrom(1024)
            L = len(raw)
            if L < 232: continue 

            packet = {"000_PacketLength": L}

            # 1. 提取已知数据
            for offset, fmt, name in DATA_MAP:
                size = struct.calcsize('<' + fmt)
                if L >= offset + size:
                    try:
                        val = struct.unpack('<' + fmt, raw[offset:offset+size])[0]
                        if fmt == 'f': val = round(val, 6)
                        packet[f"{offset:03d}_{name}"] = val
                    except: pass
            
            # 2. 自动扫描 280 字节之后的所有未知 Float (蓝色高亮)
            for offset in range(280, L - 3, 4):
                if not any(dm[0] == offset for dm in DATA_MAP): # 排除已定义的
                    try:
                        val = struct.unpack('<f', raw[offset:offset+4])[0]
                        if -100000 < val < 100000: # 过滤乱码
                            packet[f"Scan_F32_{offset:03d}"] = round(val, 6)
                    except: pass

            state["last_packet"] = packet
        except Exception as e: 
            pass

@app.get("/")
async def get_index(): return HTMLResponse(HTML_PAGE)

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            if state.get("last_packet"):
                await websocket.send_json(state["last_packet"])
            await asyncio.sleep(0.05)
    except: pass

if __name__ == "__main__":
    # 就是这一行！之前忘记启动接收线程了！
    Thread(target=udp_listener, daemon=True).start() 
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="error")