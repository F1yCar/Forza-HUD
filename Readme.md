# 🏎️ Forza Dashboard - F1y/Car

专为极限竞速系列打造的实时遥测仪表与数据分析套件，针对平板/移动设备的触控交互进行深度优化

## ✨ 核心架构 (Core Architectures)

* **实时仪表 (`index.html`)**：触控优先的遥测信息屏。提供零延迟的踏板行程、抓地力监控、轮胎热工况阵列，以及赛段进站策略的动态统筹。
* **数据回放(`replay.html`)**：多维遥测分析矩阵。采用「距离轴绝对对齐算法 (Absolute GPS Mapping)」，消除时间轴误差，实现跨圈速、跨调校的弯角比对。
* **调校实验室 (`setup.html`)**：逆向调教工程操作间。挂载目标遥测数据后，系统将自动提取遥测数据并生成雷达图，引导底盘刚性与空气动力学参数向理论最优值收敛。
* **转播推流页面 (`obs.html`)**：专业级被动视觉输出源。透明背景，GPU 硬件加速的流体动画，专为直播打造，可直接作为浏览器源 (Browser Source) 丢入 OBS。

## ⚙️ 环境依赖与部署 (Installation)

1. 环境要求：**Python 3.9+**。
2. 安装核心依赖库：
    ```bash
    pip install fastapi uvicorn psutil
    ```
3. 启动遥测中枢引擎：
    ```bash
    python monitor_server.py
    ```
    *启动后，终端将自动嗅探局域网物理 IP，并打印供 iPad/移动设备访问的直连地址。*

## 🎮 游戏端输出设置 (Game Configuration)

请在您的极限竞速中进行以下网络重定向：
1. 进入游戏的 **设置 (Settings) -> 界面与游戏性 (HUD / Gameplay)**。
2. 开启 **数据输出 (Data Out / UDP Telemetry)**。
3. 将目标 IP (Target IP) 设置为：`127.0.0.1`。
4. 将目标端口 (Target Port) 设置为：`5555`。

## 📱 触控优先 (Touch-First)

本系统的核心交互逻辑基于平板设备 (iPadOS / iOS) 打造：
* **暗房视界 (Darkroom Optics)**：极高对比度的字体排印，确保在极限竞速的高压环境下余光也能清晰读数。
* **原生级交互 (Zero-Friction)**：抛弃了传统网页生硬的点击反馈，引入底层物理反馈，消除误触与系统键盘的视觉干扰。
* **物理封卷 (Smart Storage)**：所有的 CSV 遥测切片与 JSON 调校策略，均由 Python 后台自动管理并归档至 `bastlap/` 与 `setups/` 本地物理目录。

## ⚠️ 红色警报 (Important Notes)
* **算力中枢不可断电**：Python 终端是整个系统的神经网络引擎，若意外关闭，所有 UI 面板将失去数据流并进入系统待机状态。
* **物理隔离**：Web 控制台直接暴露在局域网内，请勿在无防火墙的公网环境中部署此套件。

---
*Built for the pursuit of the perfect lap.*