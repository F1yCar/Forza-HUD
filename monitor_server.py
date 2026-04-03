import socket
import struct
import asyncio
import json
import os
import math
import csv
import glob
import re
import bisect
import datetime
import psutil
import shutil
import time
import statistics
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse
from threading import Thread
import uvicorn

app = FastAPI()

UDP_PORT = 5555

BASTLAP_DIR = "bastlap"
TEMP_DIR = os.path.join(BASTLAP_DIR, "temp_lap")
STRATEGY_FILE = os.path.join(BASTLAP_DIR, "strategies.json")
LAP_RECORDS_FILE = os.path.join(BASTLAP_DIR, "lap_records.log")

SETUPS_DIR = "setups"
SETUPS_SAVES_DIR = os.path.join(SETUPS_DIR, "saves")
SETUPS_TEMP_DIR = os.path.join(SETUPS_DIR, "temp")
BOUNDS_FILE = os.path.join(SETUPS_DIR, "cars_bounds.json")

for d in [BASTLAP_DIR, TEMP_DIR, SETUPS_DIR, SETUPS_SAVES_DIR, SETUPS_TEMP_DIR]:
    if not os.path.exists(d): os.makedirs(d)

state = {
    "last_packet": {
        "IsRaceOn": 0, "IsRec": False, "AutoSave": False,
        "Car": "等待遥测数据...", "Track": "等待连接...",
        "Delta": "--", "Lap": 0, "CurrentLap": "--:--.---", "BestLap": "--:--.---",
        "HistBestLap": "--:--.---", "OptimalLap": "--:--.---",
        "GhostLap": None, "Mode": "FM", "Gear": "N", "Speed": 0, "RPM": 0, "MaxRPM": 1,
        "Fuel": 100.0, "RemLaps": 99, "Accel": 0, "Brake": 0, "Pit": False,
        "ShiftNow": False, "FrontSlip": False, "RearSlip": False,
        "Temps": {"fl": 0, "fr": 0, "rl": 0, "rr": 0},
        "Wears": {"fl": 0, "fr": 0, "rl": 0, "rr": 0},
        "Position": 0,
        "Debrief": None
    }, 
    "historical_best": "--:--.---", 
    "optimal_lap": "--:--.---", 
    "ghost_lap": None,
    "active_strategy": None,
    "pending_debrief": None
}
config = {"is_recording": False, "auto_save_best": False, "is_dyno": False}

fh5_db, fm_db, track_db, strategies_db, bounds_db = {}, {}, {}, {}, {}
ref_dists, ref_times = [], []

def load_dbs():
    global fh5_db, fm_db, track_db, strategies_db, bounds_db
    try:
        if os.path.exists('fh5_cars.json'):
            with open('fh5_cars.json', 'r', encoding='utf-8') as f: fh5_db = json.load(f)
        if os.path.exists('fm_cars.json'):
            with open('fm_cars.json', 'r', encoding='utf-8') as f: fm_db = json.load(f)
        if os.path.exists('Track_Name.json'):
            with open('Track_Name.json', 'r', encoding='utf-8') as f: track_db = json.load(f)
        if os.path.exists(STRATEGY_FILE):
            with open(STRATEGY_FILE, 'r', encoding='utf-8') as f: strategies_db = json.load(f)
        if os.path.exists(BOUNDS_FILE):
            with open(BOUNDS_FILE, 'r', encoding='utf-8') as f: bounds_db = json.load(f)
    except: pass

def save_strategies():
    try:
        with open(STRATEGY_FILE, 'w', encoding='utf-8') as f:
            json.dump(strategies_db, f, ensure_ascii=False, indent=4)
    except: pass

def format_lap_time(seconds):
    if math.isnan(seconds) or seconds <= 0: return "--:--.---"
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:06.3f}".replace(":", "-")

def safe_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip()

def calculate_optimal_lap(safe_track, safe_car):
    car_dir = os.path.join(BASTLAP_DIR, safe_filename(safe_track), safe_filename(safe_car))
    hist_dir = os.path.join(car_dir, "historical_legacy")
    files = []
    if os.path.exists(car_dir): files.extend(glob.glob(os.path.join(car_dir, "*.csv")))
    if os.path.exists(hist_dir): files.extend(glob.glob(os.path.join(hist_dir, "*.csv")))
    valid_files = [f for f in files if "_TEMP_" not in f and "RACE_" not in f and os.path.isfile(f)]
    if not valid_files: return "--:--.---"
        
    total_dist = 0
    for f in valid_files:
        try:
            with open(f, 'r', encoding='utf-8') as file:
                reader = list(csv.DictReader(file))
                if len(reader) > 100:
                    dist = float(reader[-1].get('DistanceTraveled', 0)) - float(reader[0].get('DistanceTraveled', 0))
                    if dist > total_dist: total_dist = dist
        except: pass
            
    if total_dist <= 0: return "--:--.---"
    s1_target, s2_target = total_dist / 3.0, total_dist * 2.0 / 3.0
    min_s1, min_s2, min_s3 = float('inf'), float('inf'), float('inf')
    
    for file in valid_files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                t0, t1, t2, t3, first_dist = None, None, None, None, None
                for row in reader:
                    d = float(row.get('DistanceTraveled', 0))
                    t = float(row.get('CurrentLapTime', 0))
                    if first_dist is None: first_dist = d; t0 = t
                    rel_d = d - first_dist
                    if t1 is None and rel_d >= s1_target: t1 = t
                    if t2 is None and rel_d >= s2_target: t2 = t
                    if rel_d >= total_dist * 0.95: t3 = t 
                if t0 is not None and t1 is not None and (t1 - t0) > 0: min_s1 = min(min_s1, t1 - t0)
                if t1 is not None and t2 is not None and (t2 - t1) > 0: min_s2 = min(min_s2, t2 - t1)
                if t2 is not None and t3 is not None and (t3 - t2) > 0: min_s3 = min(min_s3, t3 - t2)
        except: pass
        
    if min_s1 != float('inf') and min_s2 != float('inf') and min_s3 != float('inf'):
        return format_lap_time(min_s1 + min_s2 + min_s3).replace("-", ":")
    return "--:--.---"

def analyze_race_data(data_rows):
    if not data_rows or len(data_rows) < 500: return None
    report = []
    
    start_fuel = float(data_rows[0].get('Fuel', 100))
    end_fuel = float(data_rows[-1].get('Fuel', 0))
    if end_fuel > 4.0:
        report.append({
            "id": "fuel", "level": "warning", "title": "燃油死重过载",
            "phys": f"冲线时剩余油量 {end_fuel:.1f}%。你背着多余的死重跑完了全场，拖累了整体的推重比和弯道动态。",
            "setup": f"建议下场比赛将初始载油量严格削减至 {max(1.0, start_fuel - end_fuel + 2.0):.1f}% 左右。",
            "driver": "如果不需要在赛道上执行 Lift and Coast (升档滑行) 来节省油量，你可以全程保持最激进的引擎输出。"
        })
    else:
        report.append({
            "id": "fuel", "level": "perfect", "title": "燃油载量精准",
            "phys": f"冲线剩余油量仅 {end_fuel:.1f}%，完美卡在枯竭临界点，车身重量优势最大化。",
            "setup": "请将当前的载油量设定设为该赛道的基准标准。",
            "driver": "燃油管理极佳，继续保持当前的油门节奏。"
        })
        
    lockups, wheelspins = 0, 0
    max_front_temp, max_rear_temp = 0, 0
    for r in data_rows:
        brk, acc = float(r.get('Brake', 0)), float(r.get('Accel', 0))
        slip_fl, slip_fr = float(r.get('TireCombinedSlip_FL', 0)), float(r.get('TireCombinedSlip_FR', 0))
        slip_rl, slip_rr = float(r.get('TireCombinedSlip_RL', 0)), float(r.get('TireCombinedSlip_RR', 0))
        if brk > 127 and (slip_fl > 1.25 or slip_fr > 1.25): lockups += 1
        if acc > 127 and (slip_rl > 1.5 or slip_rr > 1.5): wheelspins += 1
        max_front_temp = max(max_front_temp, float(r.get('TireTemp_FL', 0)), float(r.get('TireTemp_FR', 0)))
        max_rear_temp = max(max_rear_temp, float(r.get('TireTemp_RL', 0)), float(r.get('TireTemp_RR', 0)))
        
    if lockups > 40 or wheelspins > 40:
        report.append({
            "id": "grip", "level": "danger", "title": "机械抓地力流失",
            "phys": f"侦测到 {lockups} 帧前轮重刹抱死，{wheelspins} 帧后轮动力打滑。轮胎表面已被严重撕裂并过热流失抓地力。",
            "setup": "【前轮抱死】降级刹车压力 3% 或将刹车平衡后推 1%。【后轮打滑】调高差速器加速锁止(Diff Acc) 2%。",
            "driver": "循迹刹车(Trail Braking)末段需更柔和地释放踏板；出弯时方向盘未完全回正前，克制全油门的冲动。"
        })
    else:
        report.append({
            "id": "grip", "level": "perfect", "title": "踏板控制极净",
            "phys": f"全场仅有微量滑移帧 (锁死:{lockups}, 打滑:{wheelspins})，轮胎的机械抓地力被死死咬在极限边缘。",
            "setup": "当前的差速器和刹车平衡完美契合你的驾驶肌肉记忆，无需进行任何妥协性修改。",
            "driver": "展现出了极高水平的踏板颗粒度控制，允许你在高速弯进行更激进的试探。"
        })
        
    lap_times = []
    current_lap = -1
    for r in data_rows:
        l_num = int(r.get('LapNumber', 0))
        l_time = float(r.get('LastLapTime', 0))
        if l_num != current_lap:
            if current_lap != -1 and l_time > 0: lap_times.append(l_time)
            current_lap = l_num
            
    if len(lap_times) > 2:
        flying_laps = lap_times[1:] 
        if len(flying_laps) > 1:
            std_dev = statistics.stdev(flying_laps)
            if std_dev > 1.5:
                report.append({
                    "id": "consistency", "level": "warning", "title": "圈速一致性游离",
                    "phys": f"飞驰圈标准差高达 {std_dev:.2f} 秒。底盘动态可能过于神经质，导致你每个弯角的信心不一。",
                    "setup": "尝试软化前后防倾杆 1.0，或增加前束角(Toe-Out)，换取一个略微迟钝但宽容度极高的入弯动态。",
                    "driver": "不要在每一圈去试探不同的刹车点，先找到一个保守但能稳定重复的赛道参考物。"
                })
            else:
                report.append({
                    "id": "consistency", "level": "perfect", "title": "节拍器级一致性",
                    "phys": f"飞驰圈标准差仅为 {std_dev:.2f} 秒。车辆动态极度可控，人车合一。",
                    "setup": "底盘几何处于高保真状态，可以尝试微降后下压力榨取更多直道极速。",
                    "driver": "你已经完全摸透了这套物理，请继续保持你的肌肉记忆。"
                })
    return report

def process_race_debrief_thread(safe_track, safe_car, data_rows):
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"RACE_{safe_track}_{safe_car}_{timestamp}.csv"
    track_dir = os.path.join(BASTLAP_DIR, safe_filename(safe_track))
    car_dir = os.path.join(track_dir, safe_filename(safe_car))
    if not os.path.exists(car_dir): os.makedirs(car_dir)
    filepath = os.path.join(car_dir, filename)
    try:
        keys = list(data_rows[0].keys())
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(data_rows)
        with open(LAP_RECORDS_FILE, 'a', encoding='utf-8') as log_f:
            log_f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] RACE COMPLETED: {safe_track} | CAR: {safe_car} | LAPS: {len(set([r.get('LapNumber') for r in data_rows]))}\n")
    except: pass
    
    report = analyze_race_data(data_rows)
    if report: state["pending_debrief"] = report

def save_lap_data_thread(safe_track, safe_car, lap_time_sec, lap_data, temp_file_path=None):
    track_dir = os.path.join(BASTLAP_DIR, safe_filename(safe_track))
    car_dir = os.path.join(track_dir, safe_filename(safe_car))
    hist_dir = os.path.join(car_dir, "historical_legacy")
    for d in [track_dir, car_dir, hist_dir]:
        if not os.path.exists(d): os.makedirs(d)

    old_last_pattern = os.path.join(car_dir, f"{safe_track}_{safe_car}_*_LastBastLap.csv")
    for f in glob.glob(old_last_pattern):
        try:
            base = os.path.basename(f).replace("_LastBastLap.csv", "_Legacy.csv")
            shutil.move(f, os.path.join(hist_dir, base))
        except: pass

    curr_best_pattern = os.path.join(car_dir, f"{safe_track}_{safe_car}_*.csv")
    for f in glob.glob(curr_best_pattern):
        if os.path.isfile(f) and "_LastBastLap" not in f and "_TEMP_" not in f and "RACE_" not in f:
            new_path = f.replace(".csv", "_LastBastLap.csv")
            try: os.rename(f, new_path)
            except: pass

    formatted_time = format_lap_time(lap_time_sec).replace(":", "-")
    filename = f"{safe_track}_{safe_car}_{formatted_time}.csv"
    filepath = os.path.join(car_dir, filename)

    try:
        if temp_file_path and os.path.exists(temp_file_path):
            shutil.move(temp_file_path, filepath) 
        elif lap_data:
            keys = list(lap_data[0].keys())
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(lap_data)
        load_historical_reference(safe_track, safe_car)
        state["optimal_lap"] = calculate_optimal_lap(safe_track, safe_car)
    except Exception as e: pass

def load_historical_reference(safe_track, safe_car):
    global ref_dists, ref_times
    best_time, best_file = float('inf'), None
    car_dir = os.path.join(BASTLAP_DIR, safe_filename(safe_track), safe_filename(safe_car))
    
    for file_path in glob.glob(os.path.join(car_dir, "*.csv")):
        if "LastBastLap" in file_path or "_TEMP_" in file_path or "RACE_" in file_path or not os.path.isfile(file_path): continue
        try:
            filename = os.path.basename(file_path)
            time_str = filename.replace('.csv', '').rsplit('_', 1)[-1]
            time_val = float(time_str.split('-')[0]) * 60 + float(time_str.split('-')[1]) if '-' in time_str else float(time_str)
            if time_val < best_time: best_time, best_file = time_val, file_path
        except: pass

    ref_dists.clear(); ref_times.clear()
    if best_file:
        try:
            with open(best_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                first_dist = None
                for row in reader:
                    d, t = float(row.get('DistanceTraveled', 0)), float(row.get('CurrentLapTime', 0))
                    if first_dist is None: first_dist = d
                    ref_dists.append(d - first_dist)
                    ref_times.append(t)
        except: pass
    return best_time if best_time != float('inf') else 0.0

def save_ghost_lap_thread(safe_track, safe_car, lap_time_sec, lap_data):
    formatted_time = format_lap_time(lap_time_sec).replace(":", "-")
    filepath = os.path.join(TEMP_DIR, f"_TEMP_{safe_track}_{safe_car}_{formatted_time}.csv")
    try:
        keys = list(lap_data[0].keys())
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(lap_data)
        state["ghost_lap"] = {"track": safe_track, "car": safe_car, "time": format_lap_time(lap_time_sec), "full_path": filepath, "lap_time_sec": lap_time_sec}
    except: pass

def run_startup_cleanup():
    old_hist = os.path.join(BASTLAP_DIR, "historical_legacy")
    dirs_to_scan = [BASTLAP_DIR]
    if os.path.exists(old_hist): dirs_to_scan.append(old_hist)
    
    for d in dirs_to_scan:
        for f in os.listdir(d):
            if not f.endswith(".csv") or "_TEMP_" in f or "RACE_" in f: continue
            filepath = os.path.join(d, f)
            if not os.path.isfile(filepath): continue
            clean_name = f.replace(".csv", "").replace("_LastBastLap", "").replace("_Legacy", "")
            parts = clean_name.rsplit('_', 2)
            if len(parts) == 3:
                track_dir = os.path.join(BASTLAP_DIR, safe_filename(parts[0]))
                car_dir = os.path.join(track_dir, safe_filename(parts[1]))
                hist_dir = os.path.join(car_dir, "historical_legacy")
                target_dir = hist_dir if "Legacy" in f or "historical_legacy" in d else car_dir
                for md in [track_dir, car_dir, hist_dir]:
                    if not os.path.exists(md): os.makedirs(md)
                try: shutil.move(filepath, os.path.join(target_dir, f))
                except: pass
                
    if os.path.exists(old_hist) and not os.listdir(old_hist):
        try: os.rmdir(old_hist)
        except: pass

    for track_name in os.listdir(BASTLAP_DIR):
        track_path = os.path.join(BASTLAP_DIR, track_name)
        if not os.path.isdir(track_path) or track_name in ["temp_lap", "historical_legacy"]: continue
        for car_name in os.listdir(track_path):
            car_path = os.path.join(track_path, car_name)
            if not os.path.isdir(car_path) or car_name == "historical_legacy": continue
            hist_dir = os.path.join(car_path, "historical_legacy")
            if not os.path.exists(hist_dir): os.makedirs(hist_dir)

            groups = {}
            for filepath in glob.glob(os.path.join(car_path, "*.csv")):
                filename = os.path.basename(filepath)
                if "_TEMP_" in filename or "RACE_" in filename: continue
                clean_name = filename.replace(".csv", "").replace("_LastBastLap", "").replace("_Legacy", "")
                parts = clean_name.rsplit('_', 2)
                if len(parts) != 3: continue
                time_str = parts[2]
                try:
                    time_val = float(time_str.split('-')[0]) * 60 + float(time_str.split('-')[1]) if '-' in time_str else float(time_str)
                except: continue
                prefix = f"{parts[0]}_{parts[1]}"
                if prefix not in groups: groups[prefix] = []
                groups[prefix].append({'path': filepath, 'time': time_val, 'time_str': time_str, 'filename': filename})
                
            for prefix, files_list in groups.items():
                if not files_list: continue
                files_list.sort(key=lambda x: x['time'])
                best = files_list[0]
                target_best = os.path.join(car_path, f"{prefix}_{best['time_str']}.csv")
                if best['path'] != target_best:
                    try: os.rename(best['path'], target_best)
                    except: pass
                if len(files_list) > 1:
                    second = files_list[1]
                    target_second = os.path.join(car_path, f"{prefix}_{second['time_str']}_LastBastLap.csv")
                    if second['path'] != target_second:
                        try: os.rename(second['path'], target_second)
                        except: pass
                for i in range(2, len(files_list)):
                    f = files_list[i]
                    target_legacy = os.path.join(hist_dir, f"{prefix}_{f['time_str']}_Legacy.csv")
                    try: shutil.move(f['path'], target_legacy)
                    except: pass

DATA_MAP = [
    (0, 'i', "IsRaceOn"), (4, 'I', "TimestampMS"),
    (8, 'f', "EngineMaxRpm"), (12, 'f', "EngineIdleRpm"), (16, 'f', "CurrentEngineRpm"),
    (20, 'f', "Accel_X"), (24, 'f', "Accel_Y"), (28, 'f', "Accel_Z"),
    (32, 'f', "Velocity_X"), (36, 'f', "Velocity_Y"), (40, 'f', "Velocity_Z"),
    (44, 'f', "AngularVel_X"), (48, 'f', "AngularVel_Y"), (52, 'f', "AngularVel_Z"),
    (56, 'f', "Yaw"), (60, 'f', "Pitch"), (64, 'f', "Roll"),
    (68, 'f', "SuspTravel_FL"), (72, 'f', "SuspTravel_FR"), (76, 'f', "SuspTravel_RL"), (80, 'f', "SuspTravel_RR"),
    (84, 'f', "TireSlipRatio_FL"), (88, 'f', "TireSlipRatio_FR"), (92, 'f', "TireSlipRatio_RL"), (96, 'f', "TireSlipRatio_RR"),
    (100, 'f', "WheelRotationSpeed_FL"), (104, 'f', "WheelRotationSpeed_FR"), (108, 'f', "WheelRotationSpeed_RL"), (112, 'f', "WheelRotationSpeed_RR"),
    (116, 'f', "WheelOnRumble_FL"), (120, 'f', "WheelOnRumble_FR"), (124, 'f', "WheelOnRumble_RL"), (128, 'f', "WheelOnRumble_RR"),
    (132, 'f', "WheelInPuddle_FL"), (136, 'f', "WheelInPuddle_FR"), (140, 'f', "WheelInPuddle_RL"), (144, 'f', "WheelInPuddle_RR"),
    (148, 'f', "SurfaceRumble_FL"), (152, 'f', "SurfaceRumble_FR"), (156, 'f', "SurfaceRumble_RL"), (160, 'f', "SurfaceRumble_RR"),
    (164, 'f', "TireSlipAngle_FL"), (168, 'f', "TireSlipAngle_FR"), (172, 'f', "TireSlipAngle_RL"), (176, 'f', "TireSlipAngle_RR"),
    (180, 'f', "TireCombinedSlip_FL"), (184, 'f', "TireCombinedSlip_FR"), (188, 'f', "TireCombinedSlip_RL"), (192, 'f', "TireCombinedSlip_RR"),
    (196, 'f', "SuspTravelMeters_FL"), (200, 'f', "SuspTravelMeters_FR"), (204, 'f', "SuspTravelMeters_RL"), (208, 'f', "SuspTravelMeters_RR"),
    (212, 'i', "CarOrdinal"), (216, 'i', "CarClass"), (220, 'i', "CarPerformanceIndex"), (224, 'i', "DrivetrainType"), (228, 'i', "NumCylinders"),
    (232, 'f', "Position_X"), (236, 'f', "Position_Y"), (240, 'f', "Position_Z"), 
    (244, 'f', "Speed"), (248, 'f', "Power"), (252, 'f', "Torque"),
    (256, 'f', "TireTemp_FL"), (260, 'f', "TireTemp_FR"), (264, 'f', "TireTemp_RL"), (268, 'f', "TireTemp_RR"),
    (272, 'f', "Boost"), (276, 'f', "Fuel"), (280, 'f', "DistanceTraveled"), (284, 'f', "BestLapTime"), (288, 'f', "LastLapTime"), 
    (292, 'f', "CurrentLapTime"), (296, 'f', "CurrentRaceTime"), (300, 'H', "LapNumber"), (302, 'B', "RacePosition"),
    (303, 'B', "Accel"), (304, 'B', "Brake"), (305, 'B', "Clutch"), (306, 'B', "Handbrake"), (307, 'B', "Gear"), (308, 'b', "Steer"),
    (309, 'B', "NormalizedDrivingLine"), (310, 'B', "NormalizedAIBrake"),
    (311, 'f', "TireWear_FL"), (315, 'f', "TireWear_FR"), (319, 'f', "TireWear_RL"), (323, 'f', "TireWear_RR"),
    (327, 'i', "TrackOrdinal")
]

def optimize_cpu_affinity():
    try:
        p = psutil.Process(os.getpid())
        cores = [os.cpu_count()-1] if os.cpu_count() < 12 else [os.cpu_count()-2, os.cpu_count()-1]
        p.cpu_affinity(cores)
    except: pass

def get_local_ip():
    """动态抓取真实的局域网 IP，方便移动端访问"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 尝试连接公网 IP 来确定默认的本地路由网卡
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def print_startup_banner():
    """终端自检与向导管线"""
    local_ip = get_local_ip()
    vpn_note = " (如果使用了 VPN 导致该 IP 无法访问，请尝试 `ipconfig` 查找真实的无线网卡 IPv4 地址)" if local_ip != "127.0.0.1" else ""
    
    banner = f"""
\033[1;36m=======================================================================\033[0m
\033[1;32m      🏎️   APEX TELEMETRY ENGINE IS ONLINE (v3.1)   🏎️      \033[0m
\033[1;36m=======================================================================\033[0m

\033[1;33m[📡 数据接收引擎]\033[0m
  - UDP 监听端口 : \033[1;32m{UDP_PORT}\033[0m
  - \033[1m【必须设置】\033[0m 请在游戏中将「数据输出 (Data Out)」设为 \033[1;32m127.0.0.1:{UDP_PORT}\033[0m

\033[1;33m[📱 移动端控制台 (供平板 / 手机在同一 WiFi 下访问)]\033[0m
  - 🏁 实时驾驶舱 : \033[1;34mhttp://{local_ip}:8000/\033[0m {vpn_note}
  - 🔧 调校车间   : \033[1;34mhttp://{local_ip}:8000/setup\033[0m
  - 📊 数据复盘舱 : \033[1;34mhttp://{local_ip}:8000/replay\033[0m

\033[1;33m[📺 桌面级转播信号 (供 OBS 捕获)]\033[0m
  - 📺 HUD 悬浮窗 : \033[1;34mhttp://127.0.0.1:8000/obs\033[0m
  - \033[1m【设置规格】\033[0m 在 OBS 浏览器源中，将宽度设为 \033[1m1920\033[0m，高度设为 \033[1m1080\033[0m。

\033[1;31m[⚠️ 系统安全锁]\033[0m
  1. 此终端窗口是整个系统的运算中枢，\033[1m绝对不能关闭\033[0m，可以最小化。
  2. 所有的遥测数据和策略档案都会自动保存在本目录的 `bastlap/` 文件夹中。
\033[1;36m=======================================================================\033[0m
"""
    print(banner)

def udp_listener():
    global ref_dists, ref_times
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    load_dbs()
    run_startup_cleanup()

    current_lap_buffer = []
    race_session_buffer = [] 
    last_lap_num = 0
    current_track_car = (None, None)
    lap_start_dist, local_hist_best_sec = 0.0, 0.0
    recent_f, recent_w = [], []
    lap_start_fuel, lap_start_wear = 100.0, 0.0
    last_fuel, last_max_w = 100.0, 0.0

    while True:
        try:
            raw, _ = sock.recvfrom(1024)
            if len(raw) < 311: continue
            
            is_race_on = struct.unpack('<I', raw[0:4])[0]
            
            if is_race_on == 0:
                if state.get("last_packet"): state["last_packet"]["IsRaceOn"] = 0
                current_lap_buffer.clear()
                continue

            packet = {}
            for offset, fmt, name in DATA_MAP:
                size = struct.calcsize('<' + fmt)
                if len(raw) >= offset + size:
                    val = struct.unpack('<' + fmt, raw[offset:offset+size])[0]
                    packet[name] = round(val, 5) if fmt == 'f' else val

            lap_num = packet.get("LapNumber", 0) + 1
            car_id, track_id = packet.get("CarOrdinal", 0), packet.get("TrackOrdinal", 0)
            car_name = fm_db.get(str(car_id), f"Car_{car_id}") if len(raw) == 331 else fh5_db.get(str(car_id), f"Car_{car_id}")
            track_name = track_db.get(str(track_id), f"Track_{track_id}") if len(raw) == 331 else "FH5_FreeRoam"
            
            fuel = round(packet.get("Fuel", 0) * 100, 1)
            wears = {k: round(packet.get(f"TireWear_{k.upper()}", 0)*100, 1) for k in ['fl', 'fr', 'rl', 'rr']}
            max_w = max(wears.values())
            acc, brk = packet.get("Accel", 0)/2.55, packet.get("Brake", 0)/2.55
            front_slip = (packet.get("TireCombinedSlip_FL",0) > 1.2 or packet.get("TireCombinedSlip_FR",0) > 1.2) and brk > 15
            rear_slip = (packet.get("TireCombinedSlip_RL",0) > 1.5 or packet.get("TireCombinedSlip_RR",0) > 1.5) and acc > 30

            if (track_name, car_name) != current_track_car:
                current_track_car = (track_name, car_name)
                local_hist_best_sec = load_historical_reference(track_name, car_name)
                state["historical_best"] = format_lap_time(local_hist_best_sec).replace("-", ":")
                state["optimal_lap"] = calculate_optimal_lap(track_name, car_name)
                current_lap_buffer.clear()
                race_session_buffer.clear()
                recent_f.clear(); recent_w.clear()
                lap_start_fuel = fuel; lap_start_wear = max_w

            if fuel > last_fuel + 2.0 or max_w < last_max_w - 5.0:
                recent_f.clear(); recent_w.clear()
                lap_start_fuel = fuel; lap_start_wear = max_w

            if lap_num != last_lap_num:
                if lap_num == 1 and last_lap_num > 1:
                    race_session_buffer.clear()

                strat = state.get("active_strategy")
                if strat and strat.get("mode") == "race" and strat.get("total_laps"):
                    target_laps = int(strat["total_laps"])
                    if last_lap_num == target_laps and lap_num > target_laps:
                        if len(race_session_buffer) > 1000:
                            Thread(target=process_race_debrief_thread, args=(track_name, car_name, race_session_buffer.copy())).start()
                            race_session_buffer.clear()
                            state["active_strategy"] = None

                if last_lap_num > 0 and len(current_lap_buffer) > 0:
                    lap_time = packet.get("LastLapTime", 0)
                    if lap_time > 0 and (local_hist_best_sec == 0 or lap_time < local_hist_best_sec):
                        if config["is_recording"] and config["auto_save_best"]:
                            Thread(target=save_lap_data_thread, args=(track_name, car_name, lap_time, current_lap_buffer.copy())).start()
                        else:
                            Thread(target=save_ghost_lap_thread, args=(track_name, car_name, lap_time, current_lap_buffer.copy())).start()
                        
                        local_hist_best_sec = lap_time
                        state["historical_best"] = format_lap_time(lap_time).replace("-", ":")
                    
                    f_used, w_used = lap_start_fuel - fuel, max_w - lap_start_wear
                    if 0.1 < f_used < 50.0:
                        recent_f.append(f_used)
                        if len(recent_f) > 3: recent_f.pop(0)
                    if 0.0 < w_used < 100.0:
                        recent_w.append(w_used)
                        if len(recent_w) > 3: recent_w.pop(0)

                current_lap_buffer.clear(); last_lap_num = lap_num
                lap_start_dist, lap_start_fuel, lap_start_wear = packet.get("DistanceTraveled", 0), fuel, max_w

            current_lap_buffer.append(packet)
            
            strat = state.get("active_strategy")
            if (strat and strat.get("mode") == "race") or config["is_recording"]:
                race_session_buffer.append(packet)
                
            last_fuel, last_max_w = fuel, max_w

            delta_str = "--"
            if len(ref_dists) > 0 and packet.get("CurrentLapTime", 0) > 0:
                curr_dist = packet.get("DistanceTraveled", 0) - lap_start_dist
                idx = bisect.bisect_left(ref_dists, curr_dist)
                if 0 < idx < len(ref_times):
                    d_sec = packet.get("CurrentLapTime", 0) - ref_times[idx]
                    delta_str = f"{'+' if d_sec > 0 else ''}{d_sec:.3f}"

            rem_laps = 99.0
            if len(recent_f) > 0:
                avg_f = sum(recent_f) / len(recent_f)
                if avg_f > 0: rem_laps = min(rem_laps, fuel / avg_f)
            if len(recent_w) > 0:
                avg_w = sum(recent_w) / len(recent_w)
                if avg_w > 0: rem_laps = min(rem_laps, (80.0 - max_w) / avg_w)

            state["last_packet"] = {
                "IsRaceOn": 1, "Gear": 'R' if packet.get("Gear")==0 else ('N' if packet.get("Gear")==11 else str(packet.get("Gear"))),
                "Speed": int(packet.get("Speed", 0) * 3.6), "RPM": int(packet.get("CurrentEngineRpm", 0)), "MaxRPM": int(packet.get("EngineMaxRpm", 1)),
                "Accel": int(acc), "Brake": int(brk), "Fuel": fuel, "Car": car_name, "Track": track_name, "CarID": car_id, "TrackID": track_id,
                "Temps": {k: round((packet.get(f"TireTemp_{k.upper()}", 32)-32)*5/9) for k in ['fl', 'fr', 'rl', 'rr']},
                "Wears": wears, "Lap": lap_num, "CurrentLap": format_lap_time(packet.get("CurrentLapTime", 0)).replace("-", ":"),
                "BestLap": format_lap_time(packet.get("BestLapTime", 0)).replace("-", ":"), "HistBestLap": state["historical_best"], "OptimalLap": state.get("optimal_lap", "--:--.---"),
                "Delta": delta_str, "RemLaps": max(0.0, round(rem_laps, 1)), "Pit": fuel < 3.0 or max_w > 75, 
                "GhostLap": state.get("ghost_lap"), "FrontSlip": front_slip, "RearSlip": rear_slip, "Mode": "FM" if len(raw)==331 else "FH5",
                "IsRec": config["is_recording"], "AutoSave": config["auto_save_best"], "Position": packet.get("RacePosition", 0),
                "Debrief": state.get("pending_debrief")
            }
        except: pass

@app.post("/api/dyno")
async def toggle_dyno(req: Request):
    data = await req.json()
    config["is_dyno"] = data.get("state", False)
    return {"success": True, "is_dyno": config["is_dyno"]}

def dyno_simulator_thread():
    """内部测功机 (Showcase Mode)：每 30 秒循环展示三种进站预警状态"""
    import time, math
    
    while True:
        time.sleep(0.04) # 锁定 25Hz
        if not config.get("is_dyno"):
            continue
            
        # 强行注入一个 2 停战术来激活黄灯预警逻辑
        if not state.get("active_strategy") or state["active_strategy"].get("mode") != "dyno_test":
            state["active_strategy"] = {
                "mode": "dyno_test",
                "total_laps": 5,
                "stops": 1,
                "stints": [{"tire": "软胎 (Soft)", "laps": 2}, {"tire": "中性胎 (Medium)", "laps": 3}]
            }
        
        t = time.time()
        cycle = t % 30.0 # 30秒一个循环剧本
        
        # 模拟基础视觉动态 (转速/车速/踏板)
        gear = int(1 + (t % 5) / 1)
        rpm = 5000 + int(math.sin(t * 5) * 3000)
        speed = 100 + int(math.sin(t * 2) * 150)
        if speed < 0: speed = 0
        accel = 100 if math.sin(t) > 0 else 0
        brake = 100 if math.sin(t) <= 0 else 0
        
        # 核心剧本编排
        lap = 1
        wear = 20.0
        fuel = 80.0
        curr_lap_time = 0.0
        
        if cycle < 10:
            # [0-10秒] 第 1 圈末尾段：触发 PIT WINDOW OPEN (橙色预警)
            lap = 1
            curr_lap_time = 75.0 # BestLap 设为 100 秒，75 秒即达到 75% 进度，超过 70% 阈值亮窗
        elif cycle < 20:
            # [10-20秒] 第 2 圈 (策略进站圈)：触发 BOX BOX (黄色爆闪)
            lap = 2
            curr_lap_time = 10.0
        else:
            # [20-30秒] 第 3 圈：无视策略，轮胎磨损超标，触发 PIT NOW (红色绝境)
            lap = 3
            wear = 85.0 # > 80% 触发红警
            fuel = 2.0  # < 3.0% 触发红警
            curr_lap_time = 15.0

        state["last_packet"].update({
            "IsRaceOn": 1, "Mode": "DYNO", "Gear": str(max(1, gear)),
            "Speed": int(speed), "RPM": int(rpm), "MaxRPM": 9000,
            "Accel": accel, "Brake": brake, "Fuel": fuel,
            "Car": "Dyno Showcase GT3", "Track": "Test Track",
            "Temps": {"fl": 90, "fr": 90, "rl": 95, "rr": 95},
            "Wears": {"fl": wear, "fr": wear, "rl": wear+2, "rr": wear+2},
            "Lap": lap, 
            "CurrentLap": f"01:{int(curr_lap_time):02d}.000", 
            "BestLap": "01:40.000", # 基准圈 100 秒
            "HistBestLap": "01:40.000",
            "Position": 1, "RemLaps": 10,
            "Pit": wear > 80 or fuel < 3.0
        })

@app.get("/api/strategy/{track}")
async def get_strat(track: str): return {"strategies": strategies_db.get(track, [])}

@app.post("/api/strategy/{track}")
async def set_strat(track: str, req: Request):
    data = await req.json()
    if track not in strategies_db: strategies_db[track] = []
    strategies_db[track].append(data); save_strategies(); return {"success": True}

@app.delete("/api/strategy/{track}/{index}")
async def delete_strat(track: str, index: int):
    if track in strategies_db and 0 <= index < len(strategies_db[track]):
        strategies_db[track].pop(index); save_strategies(); return {"success": True}
    return {"success": False}

@app.get("/api/bounds/{car}")
async def get_bounds(car: str): return bounds_db.get(car, {})
@app.post("/api/bounds/{car}")
async def save_bounds(car: str, req: Request):
    bounds_db[car] = await req.json()
    try:
        with open(BOUNDS_FILE, 'w', encoding='utf-8') as f: json.dump(bounds_db, f, ensure_ascii=False, indent=4)
    except: pass
    return {"success": True}

@app.get("/api/setups/list")
async def list_setups():
    saves = [os.path.basename(f) for f in glob.glob(os.path.join(SETUPS_SAVES_DIR, "*.json"))]
    temps = [os.path.basename(f) for f in glob.glob(os.path.join(SETUPS_TEMP_DIR, "*.json"))]
    saves.sort(key=lambda x: os.path.getmtime(os.path.join(SETUPS_SAVES_DIR, x)), reverse=True)
    temps.sort(key=lambda x: os.path.getmtime(os.path.join(SETUPS_TEMP_DIR, x)), reverse=True)
    return {"saves": saves, "temp": temps}

@app.get("/api/setups/load")
async def load_setup(file: str, type: str):
    path = os.path.join(SETUPS_SAVES_DIR if type == "saves" else SETUPS_TEMP_DIR, safe_filename(file))
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}
    return {}

@app.get("/api/setups/check_temp")
async def check_temp_setups():
    now = time.time()
    expired = [{"name": os.path.basename(f), "path": f, "age_days": round((now - os.path.getmtime(f))/86400, 1)} for f in glob.glob(os.path.join(SETUPS_TEMP_DIR, "*.json")) if os.path.isfile(f) and (now - os.path.getmtime(f) > 259200)]
    return {"expired": expired}

@app.post("/api/setups/clean_temp")
async def clean_temp_setups(req: Request):
    data = await req.json()
    deleted = 0
    for f_info in data.get("files", []):
        path = f_info.get("path")
        if path and os.path.exists(path) and SETUPS_TEMP_DIR in path:
            try: os.remove(path); deleted += 1
            except: pass
    return {"success": True, "deleted": deleted}

@app.post("/api/setups/save")
async def save_setup(req: Request):
    data = await req.json()
    filepath = os.path.join(SETUPS_SAVES_DIR if data.get("save_type") == "saves" else SETUPS_TEMP_DIR, f"{safe_filename(data.get('setup_name', f'setup_{int(time.time())}'))}.json")
    try:
        with open(filepath, 'w', encoding='utf-8') as f: json.dump(data.get("setup_data", {}), f, ensure_ascii=False, indent=4)
        return {"success": True, "path": filepath}
    except Exception as e: return {"success": False, "error": str(e)}

@app.get("/")
async def index(): return FileResponse('index.html')
@app.get("/replay")
async def replay_page(): return FileResponse('replay.html')
@app.get("/obs")
async def obs_page(): return FileResponse('obs.html')
@app.get("/setup")
async def setup_page(): return FileResponse('setup.html')

@app.get("/api/laps")
async def get_files():
    files_info = []
    for root, _, files in os.walk(BASTLAP_DIR):
        if "temp_lap" in root or "temp lap" in root: continue
        for f in files:
            if f.endswith(".csv"):
                path = os.path.join(root, f)
                files_info.append({"name": os.path.relpath(path, BASTLAP_DIR).replace("\\", "/"), "mtime": os.path.getmtime(path)})
    files_info.sort(key=lambda x: x['mtime'], reverse=True)
    return {"files": [x['name'] for x in files_info]}

@app.delete("/api/laps")
async def delete_lap_file(req: Request):
    data = await req.json()
    filepath = data.get("path")
    if filepath:
        full_path = os.path.join(BASTLAP_DIR, filepath)
        if os.path.exists(full_path) and BASTLAP_DIR in full_path:
            try:
                os.remove(full_path)
                return {"success": True}
            except: pass
    return {"success": False}

@app.get("/data/{path:path}")
async def get_data(path: str):
    full_path = os.path.join(BASTLAP_DIR, path)
    return FileResponse(full_path) if os.path.exists(full_path) else {"error": "Not found"}

@app.get("/{filename:path}")
async def get_static_assets(filename: str):
    if filename.endswith((".png", ".jpg", ".gif", ".jpeg")) and os.path.exists(filename): return FileResponse(filename)
    return {"error": "Not found"}

@app.websocket("/ws")
async def ws_handler(ws: WebSocket):
    await ws.accept()
    async def send():
        while True:
            if state.get("last_packet"): await ws.send_json(state["last_packet"])
            await asyncio.sleep(0.04)
    async def recv():
        while True:
            try:
                data = await ws.receive_json()
                cmd = data.get("cmd")
                if cmd == "toggle_rec": 
                    config["is_recording"] = data.get("val", False)
                    state["last_packet"]["IsRec"] = config["is_recording"]
                elif cmd == "toggle_save": 
                    config["auto_save_best"] = data.get("val", False)
                    state["last_packet"]["AutoSave"] = config["auto_save_best"]
                elif cmd == "resolve_ghost":
                    ghost = state.get("ghost_lap")
                    if ghost:
                        if data.get("val"): save_lap_data_thread(ghost["track"], ghost["car"], ghost["lap_time_sec"], None, ghost["full_path"])
                        elif os.path.exists(ghost["full_path"]): os.remove(ghost["full_path"])
                        state["ghost_lap"] = None
                elif cmd == "update_mapping":
                    p = data["payload"]; m_id = str(p["id"])
                    if p["type"] == "car":
                        db = fm_db if p["game"] == "FM" else fh5_db
                        db[m_id] = p["name"]
                        with open(f"{p['game'].lower()}_cars.json", 'w', encoding='utf-8') as f: json.dump(db, f, ensure_ascii=False, indent=4)
                    else:
                        track_db[m_id] = p["name"]
                        with open('Track_Name.json', 'w', encoding='utf-8') as f: json.dump(track_db, f, ensure_ascii=False, indent=4)
                elif cmd == "set_active_strategy":
                    state["active_strategy"] = data.get("val")
                elif cmd == "clear_debrief":
                    state["pending_debrief"] = None
            except WebSocketDisconnect: break
            except Exception: pass
    await asyncio.gather(send(), recv())

if __name__ == "__main__":
    optimize_cpu_affinity()
    print_startup_banner()
    Thread(target=udp_listener, daemon=True).start()
    Thread(target=dyno_simulator_thread, daemon=True).start() # <--- 启动测功机后台挂起
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")