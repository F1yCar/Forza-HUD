import json
import os

def parse_car_list(file_name):
    car_db = {}
    if not os.path.exists(file_name):
        print(f"找不到文件: {file_name}")
        return car_db

    # 依次尝试常用的编码格式
    encodings = ['utf-8', 'utf-16', 'utf-8-sig', 'gbk']
    content = None
    
    for enc in encodings:
        try:
            with open(file_name, 'r', encoding=enc) as f:
                content = f.readlines()
            print(f"成功使用 {enc} 读取 {file_name}")
            break
        except Exception:
            continue

    if not content:
        print(f"无法读取 {file_name}，请检查文件编码。")
        return car_db

    for line in content:
        # 使用制表符分割
        parts = [p.strip() for p in line.split('\t') if p.strip()]
        if len(parts) >= 2:
            # 逻辑：通常第一项是名称，最后一项或包含数字的一项是 ID
            car_name = parts[0]
            # 寻找最后一位是否为纯数字 ID
            car_id = parts[-1]
            if car_id.isdigit():
                car_db[car_id] = car_name
                
    return car_db

if __name__ == "__main__":
    print("正在构建车辆数据库...")
    
    fh5_raw = parse_car_list('FH5CARS.json')
    fm_raw = parse_car_list('FMCARS.json')
    
    # 写入独立的 JSON 供程序识别
    with open('fh5_cars.json', 'w', encoding='utf-8') as f:
        json.dump(fh5_raw, f, ensure_ascii=False, indent=2)
        
    with open('fm_cars.json', 'w', encoding='utf-8') as f:
        json.dump(fm_raw, f, ensure_ascii=False, indent=2)
        
    print(f"\n构建完成！")
    print(f"地平线 5 (FH5): 识别到 {len(fh5_raw)} 辆车")
    print(f"极限竞速 (FM): 识别到 {len(fm_raw)} 辆车")