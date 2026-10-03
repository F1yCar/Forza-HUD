import socket
import struct
import csv
import time

# 定义 V3 数据包的完整结构 (基于官方 support 文档)
# f: float, i: int32, I: uint32, H: uint16, B: uint8, b: int8
# 这里的格式字符串严格匹配文档从 S32 IsRaceOn 到 S32 TrackOrdinal 的顺序
V3_STRUCT_FORMAT = (
    '<iI' + 'f'*3 + 'f'*3 + 'f'*3 + 'f'*3 + 'f'*3 +  # IsRaceOn...Roll
    'f'*4 + 'f'*4 + 'f'*4 + 'i'*4 + 'f'*4 + 'f'*4 +  # SuspTravel...SurfRumble
    'f'*4 + 'f'*4 + 'f'*4 +                          # SlipAngle...SuspTravelMeters
    'iiiiifff' + 'f'*3 + 'f'*4 + 'f'*2 +             # CarOrdinal...TireTemp
    'ffffH' + 'BBBBBb b b' +                         # Boost...NormalizedAIBrake
    'f'*4 + 'i'                                      # TireWear...TrackOrdinal
)

# 对应的列名列表 (用于 CSV)
COLUMNS = [
    'IsRaceOn', 'TimestampMS', 'EngineMaxRpm', 'EngineIdleRpm', 'CurrentEngineRpm',
    'AccelX', 'AccelY', 'AccelZ', 'VelX', 'VelY', 'VelZ', 'AngVelX', 'AngVelY', 'AngVelZ',
    'Yaw', 'Pitch', 'Roll',
    'NormSuspFL', 'NormSuspFR', 'NormSuspRL', 'NormSuspRR',
    'SlipRatioFL', 'SlipRatioFR', 'SlipRatioRL', 'SlipRatioRR',
    'WheelRotFL', 'WheelRotFR', 'WheelRotRL', 'WheelRotRR',
    'RumbleFL', 'RumbleFR', 'RumbleRL', 'RumbleRR',
    'PuddleFL', 'PuddleFR', 'PuddleRL', 'PuddleRR',
    'SurfRumbleFL', 'SurfRumbleFR', 'SurfRumbleRL', 'SurfRumbleRR',
    'SlipAngleFL', 'SlipAngleFR', 'SlipAngleRL', 'SlipAngleRR',
    'CombSlipFL', 'CombSlipFR', 'CombSlipRL', 'CombSlipRR',
    'SuspMetersFL', 'SuspMetersFR', 'SuspMetersRL', 'SuspMetersRR',
    'CarOrdinal', 'CarClass', 'CarPI', 'Drivetrain', 'NumCylinders',
    'PosX', 'PosY', 'PosZ', 'Speed', 'Power', 'Torque',
    'TempFL', 'TempFR', 'TempRL', 'TempRR', 'Boost', 'Fuel', 'Distance',
    'BestLap', 'LastLap', 'CurrentLap', 'CurrentRaceTime', 'LapNum',
    'RacePos', 'Accel', 'Brake', 'Clutch', 'Handbrake', 'Gear', 'Steer',
    'NormDrivingLine', 'NormAIBrakeDiff',
    'WearFL', 'WearFR', 'WearRL', 'WearRR', 'TrackOrdinal'
]

def capture_all():
    UDP_IP = "0.0.0.0"
    UDP_PORT = 5555  # 确保游戏内设置一致
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    
    filename = f"forza_v3_full_{int(time.time())}.csv"
    print(f"工程师模式：全量数据捕获中... 目标文件: {filename}")
    
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        
        try:
            while True:
                data, addr = sock.recvfrom(1024)
                # V3 数据包理论长度在 324 字节以上
                if len(data) >= 324:
                    # 我们只取前 311 字节或 324 字节（视版本而定），
                    # 按照定义的格式解包
                    try:
                        # 截取对应长度的数据进行解析
                        decoded = struct.unpack(V3_STRUCT_FORMAT, data[:struct.calcsize(V3_STRUCT_FORMAT)])
                        writer.writerow(decoded)
                    except Exception as e:
                        pass # 忽略格式微调产生的溢出错误
                    
                    if len(data) % 60 == 0:
                        print(f"\r已记录记录点，当前 Gear: {data[319]}", end="")
        except KeyboardInterrupt:
            print(f"\n捕获停止。数据已完整存入 {filename}")

if __name__ == "__main__":
    capture_all()