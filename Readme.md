# Forza Dashboard - F1y/Car

面向极限竞速系列的局域网遥测仪表与数据分析工具。Python 接收游戏 UDP 数据，通过 WebSocket 向浏览器推送；支持平板、副屏和 OBS 浏览器源。

## 项目构成

```text
Forza HUD/
├── monitor_server.py       主程序入口：遥测、记录、策略、HTTP 与 WebSocket
├── requirements.txt        主程序运行依赖
├── requirements-dev.txt    测试依赖
├── web/
│   ├── index.html          实时 HUD
│   ├── obs.html            OBS 透明叠加层
│   ├── replay.html         圈速与遥测对比
│   ├── setup.html          调校参数与图表
│   └── assets/             原有图片资源
├── data/
│   ├── fh5_cars.json       FH5 车辆名称映射
│   ├── fm_cars.json        FM 车辆名称映射
│   ├── Track_Name.json     FM 赛道名称映射
│   ├── bastlap/            圈速、整段记录、策略与历史档案
│   └── setups/             调校存档、临时档案与车辆参数边界
├── tests/                  隔离测试，不操作个人历史数据
├── editions/free/          原 Free 版，独立保留，非主程序依赖
├── reference/              原第三方参考项目（本机参考，不入库）
├── tools/
│   ├── Initialization.py   遥测字段查看工具
│   ├── Initialization.html
│   └── legacy/             原「杂物」中的抓包、车辆库转换工具与样本
├── docs/                   协议字段说明与原开发笔记
└── archive/                原始抓包文本（本机归档，不入库）
```

原始 ZIP 保留在项目目录之外。历史 CSV、JSON 和素材仅调整目录，不清理、不转换；`bastlap` 拼写及内部文件名保留，以兼容既有记录。

## 功能与边界

| 功能 | 说明 |
|---|---|
| 实时 HUD | 速度、挡位、转速、踏板、转向、G 值、胎温与打滑提示 |
| FM 圈速与策略 | 最快圈、差值、估算理想圈、续航估计与进站提示 |
| 记录与回放 | 单圈及整段 CSV，曲线和轨迹图，按相对行驶距离对齐比较 |
| 调校工具 | 参数编辑、存取、车辆参数边界、遥测图表与实验性建议 |
| OBS | 透明背景浏览器源，建议 1920 × 1080 |
| 演示模式 | 不连接游戏时展示模拟仪表数据；不是车辆性能测量工具 |

FH5 支持基础遥测及整段录制，不进入 FM 的历史圈速、赛道与策略处理流程。FH5 数据包没有 FM 的轮胎磨损扩展字段，主 HUD 中磨损为占位值，不是实际测量值。

调校目标由速度、横向 G 值的阈值与随机扰动生成，属于实验性展示，并非物理优化求解器。赛后建议同样是规则分析，不应当作保证准确的车辆调校结论。

## 安装与启动

建议 Python 3.10+；整理后的版本使用 Python 3.13 验证。主程序不需要 Node.js、Electron 或 .NET，参考项目的依赖无需安装。

在项目根目录建立独立环境：

```bash
python3 -m venv .venv
```

macOS / Linux：

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python monitor_server.py
```

Windows：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe monitor_server.py
```

网页地址：

- HUD：`http://127.0.0.1:8000/`
- OBS：`http://127.0.0.1:8000/obs`
- 回放：`http://127.0.0.1:8000/replay`
- 调校：`http://127.0.0.1:8000/setup`

平板使用运行服务的电脑的局域网 IP 替换 `127.0.0.1`。程序资源路径以脚本位置为基准，因此也可从其他目录通过绝对路径启动。

请使用 `python monitor_server.py` 入口；单独执行 `uvicorn monitor_server:app` 不会启动 UDP 接收和演示线程。

### 可选环境变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `FORZA_WEB_HOST` | `0.0.0.0` | 网页监听地址；仅本机使用时可设为 `127.0.0.1` |
| `FORZA_WEB_PORT` | `8000` | 网页端口 |
| `FORZA_UDP_PORT` | `5555` | 游戏遥测接收端口 |
| `FORZA_DATA_DIR` | 项目内 `data/` | 数据根目录；建议使用绝对路径 |

macOS / Linux 自定义示例：

```bash
FORZA_WEB_HOST=127.0.0.1 FORZA_WEB_PORT=8002 FORZA_UDP_PORT=5556 .venv/bin/python monitor_server.py
```

Windows PowerShell 示例：

```powershell
$env:FORZA_WEB_PORT = "8002"
$env:FORZA_UDP_PORT = "5556"
.venv\Scripts\python.exe monitor_server.py
```

自定义数据目录不会自动迁移原有记录或名称映射。默认启动不再执行旧版的历史 CSV 重命名/归档流程。

## 游戏设置

1. 在游戏 HUD / Gameplay 设置中打开 Data Out。
2. 游戏与服务在同一台电脑时，目标 IP 为 `127.0.0.1`。
3. 游戏在另一台电脑或主机时，目标 IP 必须是运行 Python 服务的电脑的局域网 IP。
4. 目标端口与 `FORZA_UDP_PORT` 一致，默认 `5555`。
5. 如果游戏提供数据包格式选项，使用包含仪表字段的 Car Dash 格式。
6. 检查防火墙是否允许 UDP 遥测端口和 TCP 网页端口。

主程序、Free 版和抓包工具不要同时使用相同 UDP 端口。

## 历史版本和开发工具

`editions/free/` 保留原 Free 版，不参与主程序运行。该版本仍存在未完成的录制/测功机开关、空名称字典和缺失图片；原依赖清单也未包含 WebSocket 实现。不要将其当作已经完善的发行包，也不要依赖其录制开关保存数据。日常使用优先选择根目录主程序。

`tools/Initialization.py` 是字段查看工具，网页默认端口为 `8001`，UDP 默认端口为 `5555`。应先停止主程序，再运行：

```bash
.venv/bin/python tools/Initialization.py
```

`tools/legacy/` 为原始实验代码，保留原行为，部分脚本从当前工作目录读取或写入文件；数据库构建、抓包脚本可能覆盖同名输出。运行前查看脚本，并在独立工作目录中准备输入副本，不要直接对个人存档操作。

## 验证

安装测试依赖后运行：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

Windows 将 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`。

测试使用临时目录和构造的遥测数据，不写入 `data/` 中的个人记录。自动测试不能替代实际游戏、平板和 OBS 验证。

## 使用注意

- 服务没有用户认证，只适用于可信局域网，不要进行公网端口映射。
- 图片只从 `web/assets/` 提供；遥测文件接口只允许访问数据目录内的 CSV。
- 录制数据主要缓存在内存中；整段录制应先关闭录制开关并等待保存，再停止程序，异常退出仍有丢失未保存记录的风险。
- 页面仍使用在线 Tailwind、Chart.js 和 PapaParse CDN，尚不保证完全离线可用。
- 主 HUD 和调校页断线后可能需要手动刷新；OBS 页面保留原有重连逻辑。
- 不要随意删除 `data/bastlap/temp_lap/`：其中可能包含尚未确认保存的圈速。
- 运行依赖沿用原 Free 版的 FastAPI/Uvicorn 版本并补齐缺失库；本轮未进行全量依赖升级或安全审计。
