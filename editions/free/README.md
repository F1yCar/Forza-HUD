# Forza HUD Free

Forza HUD Free 是一个开箱即用的实时遥测面板，适合日常驾驶、直播与录制场景。

你将获得两个页面：

- `index.html`：主驾驶 HUD（本地查看）
- `obs.html`：OBS 透明叠加层（直播/录制通用）

---

## 功能范围（Free 版）

包含：

- 实时速度、档位、转速、圈数、名次
- 油门/刹车输入可视化
- 轮胎温度与磨损显示
- 基础策略与进站提示
- OBS 透明叠加层

不包含：

- 回放分析（Replay）
- 调校实验室（Setup）
- 智能赛后复盘（Debrief）

---

## 1) 安装要求

- Python 3.10 或更高版本
- Forza Motorsport / Forza Horizon（需开启 UDP 遥测输出）

安装依赖：

```bash
pip install -r requirements.txt
```

---

## 2) 启动服务

默认启动：

```bash
python monitor_server.py
```

自定义端口示例：

```bash
python monitor_server.py --port 8000 --udp-port 5555 --host 0.0.0.0
```

参数说明：

- `--port`：网页访问端口（默认 `8000`）
- `--udp-port`：接收游戏遥测的 UDP 端口（默认 `5555`）
- `--host`：网页监听地址（默认 `0.0.0.0`）

也支持环境变量：

- `FORZA_WEB_PORT`
- `FORZA_UDP_PORT`
- `FORZA_WEB_HOST`

---

## 3) 游戏内设置（Data Out）

在游戏中将遥测输出配置为：

- 地址：`127.0.0.1`
- 端口：与你启动参数中的 `--udp-port` 一致（默认 `5555`）

---

## 4) 打开页面

服务启动后：

- 主 HUD：`http://127.0.0.1:<port>/`
- OBS 叠加层：`http://127.0.0.1:<port>/obs`
- 健康检查：`http://127.0.0.1:<port>/health`

如果你在局域网中使用平板/副屏，也可访问：

- `http://你的局域网IP:<port>/`

---

## 5) 在 OBS 中使用（直播与录制）

1. 在 OBS 添加 **浏览器源**。
2. URL 填写：`http://127.0.0.1:<port>/obs`
3. 保持默认透明背景即可叠加到游戏画面。
4. 可用于：
   - 直播推流时的实时信息叠加
   - 本地录制（回看素材）时的信息叠加

---

## 6) 常见问题

### Q1：页面有，但数据不动？

请检查：

- 游戏是否开启 Data Out
- Data Out 端口是否与 `--udp-port` 一致
- 本地防火墙是否拦截了 UDP 端口

### Q2：如何确认服务真的启动了？

访问：`/health`

若返回 `{"ok": true, ...}`，表示服务正常运行。

### Q3：为什么没有 Replay / Setup / Debrief 页面？

这是 Free 版设计范围。该仓库仅提供实时 HUD + OBS 叠加功能。

---

祝你刷圈顺利，直播与录制都顺畅。🏁
