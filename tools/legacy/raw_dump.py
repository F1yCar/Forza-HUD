import socket
import datetime

# 配置
UDP_PORT = 5555
SAVE_FILE = "forza_raw_dump.txt"

def start_raw_dump():
    # 创建 UDP 句柄
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    
    print(f"--- 原始数据抓取模式 ---")
    print(f"监听端口: {UDP_PORT}")
    print(f"数据将保存至: {SAVE_FILE}")
    print(f"请在游戏中起步、换挡（1-2-3），然后按 Ctrl+C 停止抓取...")
    print(f"------------------------")

    with open(SAVE_FILE, "w") as f:
        f.write(f"Record Start: {datetime.datetime.now()}\n")
        f.write("Format: [Timestamp] | [Packet Length] | [Hex Data]\n")
        f.write("-" * 50 + "\n")
        
        count = 0
        try:
            while True:
                data, addr = sock.recvfrom(1024)
                timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                packet_len = len(data)
                
                # 将原始字节转为十六进制字符串
                hex_data = data.hex(' ')
                
                # 写入文件
                f.write(f"[{timestamp}] | L={packet_len} | {hex_data}\n")
                
                count += 1
                if count % 60 == 0:
                    print(f"已记录 {count} 帧数据...")
                    
        except KeyboardInterrupt:
            print(f"\n抓取停止。共记录 {count} 帧。")
            f.write(f"\nRecord End: {datetime.datetime.now()}\n")

if __name__ == "__main__":
    start_raw_dump()