# Pixel Light 中文交接手册

本文件用于实际交接和快速上手。系统整体技术方案、RAM 论证、协议演进和历史决策放在 `SYSTEM_ARCHITECTURE.md`；协作规则放在 `CODEX_RULES.md`。

## 当前工程位置

- 正确工程目录：`C:\Users\RMER_guotie\Desktop\graduation\pixel`
- 不要使用旧目录：`C:\Users\RMER_guotie\Desktop\graduation\bsrr_test`
- CubeMX 工程：`pixel_light.ioc`
- Keil 工程：`MDK-ARM\PIXEL_LIGHT.uvprojx`
- 主协议文档：`COMM_PROTOCOL.md`
- 上位机目录：`host_tool`

当前本地仓库在 `main` 分支。若需要推送，先检查 `git status --short --branch`，避免把本地测试文件或大 `.pixelbin` 文件带入提交。

## 文件结构

下位机应用层核心文件：

- `Core/Inc/app_config.h`：常用功能开关、板号、通信、白光、检流参数。
- `Core/Src/app_controller.c`：应用层调度入口，主循环中调用。
- `Core/Src/ws2812_bsr_dma.c`：TIM4 + DMA + GPIOA BSRR 驱动 WS2812。
- `Core/Src/white_pwm.c`：TIM1 CH1/CH2 白光 PWM。
- `Core/Src/remote_input.c`：RC 四路输入，EXTI + debounce。
- `Core/Src/current_protect.c`：ADC 检流和过流锁死逻辑，目前宏关闭。
- `Core/Src/comm_transport.c`：USB CDC / UART 字节传输层和 RX ring。
- `Core/Src/comm_protocol.c`：USB/UART 自定义协议、拼包、commit、状态返回。
- `USB_DEVICE\App\usbd_cdc_if.c`：USB CDC 接收回调入口。

上位机核心文件：

- `host_tool/pixel_host/protocol.py`：上位机协议打包/解包参数，当前实际协议以这里为准。
- `host_tool/pixel_host/device.py`：单板 HELLO、STATUS、发帧、ALL_BLACK。
- `host_tool/pixel_host/gui.py`：调试 GUI，自动连接、多板通道测试、文件播放。
- `host_tool/pixel_host/video_generator.py`：视频/GIF 转 `.pixelbin`。
- `host_tool/pixel_host/display_mapping.py`：32x48 逻辑画面到四块板的坐标映射。
- `host_tool/tools/autoplay.py`：Windows 自启播放状态机。
- `host_tool/autoplay.ps1`：自启播放脚本。
- `host_tool/install_autostart.ps1`：安装 Windows 当前用户启动项。
- `host_tool/setup_host_env.ps1`：自动创建 Python 虚拟环境并安装依赖。

重要文档：

- `SYSTEM_ARCHITECTURE.md`：系统架构、模块说明、RAM、协议设计、历史测试记录。
- `CODEX_HANDOFF.md`：本交接手册。
- `CODEX_RULES.md`：协作和修改规则。
- `COMM_PROTOCOL.md`：下位机通信协议说明。若它和代码冲突，先以 `host_tool/pixel_host/protocol.py` 与 `Core/Src/comm_protocol.c` 为准，再同步文档。
- `host_tool/README.md`：上位机安装和常用命令。

## 环境安装

### 下位机

- 使用 Keil MDK 打开 `MDK-ARM\PIXEL_LIGHT.uvprojx`。
- 使用 STM32CubeMX 打开 `pixel_light.ioc`。修改 `.ioc` 后需要重新生成代码，再检查 USER CODE 区是否保留。
- 当前工程目标 MCU 为 STM32F103C8 系列。

### 上位机

第一次在 Windows 电脑上部署：

```powershell
cd host_tool
powershell -ExecutionPolicy Bypass -File .\setup_host_env.ps1
.\.venv\Scripts\activate
```

依赖在 `host_tool/requirements.txt` 中，主要包括：

- `pyserial`：USB CDC / 串口通信。
- `PySide6`：GUI。
- `opencv-python`：视频输入。
- `Pillow`：GIF 输入。

## 下位机常用操作

### 修改板号

每块板烧录前修改：

```c
#define APP_ROLE_ID  10U
```

位置：`Core/Inc/app_config.h`

有效范围目前按 `1..20` 使用。上位机多板自动连接时按 `role_id` 升序映射，最小四块板对应输出 slot1..4。

### 常用功能开关

位置：`Core/Inc/app_config.h`

```c
#define APP_ENABLE_REMOTE_INPUT      1U
#define APP_WS2812_ACTIVE_LANES      8U
#define APP_ENABLE_CURRENT_MONITOR   0U
#define APP_ENABLE_CURRENT_PROTECT   0U
#define APP_ENABLE_CAN               0U
#define APP_USB_ONLY_BRINGUP         0U
```

当前状态：

- RC 输入已打开。
- WS2812 8 路输出已打开。
- 检流监测和过流保护当前关闭，因为 ADC 接入和阈值还没有完成实机验证。
- CAN 当前关闭，不参与 USB IRQ 或工程功能。
- USB-only bring-up 模式关闭，正常运行完整应用。

### 白光 PWM 参数

位置：`Core/Inc/app_config.h`

```c
#define APP_WHITE_PWM_MAX_LEVEL  1000U
#define APP_WHITE_PWM_STEP_MS    2U
#define APP_WHITE_PWM_STEP       5U
#define APP_WHITE_PWM_TIM1_ARR   3599U
```

当前白光通道：

- WW：TIM1 CH1 / PA8
- CW：TIM1 CH2 / PA9
- 目标 PWM 频率约 20 kHz。
- 上位机协议中 WW/CW 是全局板级参数，随 `FRAME_COMMIT` 生效。

### WS2812 输出

- 单板物理输出：8 路，每路 48 个小板，每小板 2 颗串接 WS2812B。
- 协议逻辑输出：每板 `8 x 48` RGB 逻辑像素。
- 固件展开：每个逻辑像素复制到同一小板上的 2 颗物理 WS2812。
- BSRR 输出引脚：PA0..PA7 对应 CH1..CH8。
- 主工程中当前启用 8 路。

## 上位机常用操作

所有命令默认在 `host_tool` 目录运行。

### 扫描设备

```powershell
python -m tools.scan_devices
```

### 查看单板状态

```powershell
python -m tools.status COM15
```

关注字段：

- `role_id`：板号。
- `rc_bits`：RC 四路稳定状态。
- `rc_events`：RC 四路按下事件，STATUS 返回后清除。
- `rx_used`、`error_count`：通信压力/溢出线索。
- `commit_count`：成功 commit 次数。

### 单板发纯色

```powershell
python -m tools.send_solid COM15 --rgb 255 0 0 --ww 0 --cw 0
```

### 打开调试 GUI

```powershell
python -m tools.gui
```

GUI 当前用途：

- 自动扫描并连接多块板。
- 按 `role_id` 升序映射到 slot。
- 单通道 RGB 测试，通道 1..32 从左到右递增。
- 文件播放 `.pixelbin`。
- 白光 WW/CW 全局控制。
- RC / Mode 四键调试：`Mode 1`、`Mode 2`、`Black`、`Pause`。

GUI 四键调试逻辑：

- GUI 会轮询已连接下位机的 `STATUS_RSP.rc_event_bits`。
- 任意下位机上报 bit0/bit1/bit2/bit3 时，GUI 对应按钮高亮并触发同一动作。
- 在 GUI 中手动点击未高亮按钮，也等价于触发该动作。
- 再次点击当前已高亮动作无效，避免重复重启播放。
- `Mode 1` 循环播放 `host_tool\autoplay\mode1.pixelbin`。
- `Mode 2` 循环播放 `host_tool\autoplay\mode2.pixelbin`。
- `Black` 循环播放 `host_tool\autoplay\black.pixelbin`。
- `Pause` 停止继续提交 RGB 帧，保持当前输出。
- GUI 内部对每块板使用串口 `io_lock`，避免播放发帧和 STATUS 轮询同时抢同一个 CDC 响应。

当前仓库本地已生成三个占位 demo 文件：

```text
host_tool\autoplay\mode1.pixelbin
host_tool\autoplay\mode2.pixelbin
host_tool\autoplay\black.pixelbin
```

这些 `.pixelbin` 文件被 `.gitignore` 忽略，只用于本地联调，不进入 git 提交。

### 生成测试灯效文件

```powershell
python -m tools.generate_test_file --output test.pixelbin --pattern breath --frames 240 --fps 60
```

### 视频/GIF 转灯效

```powershell
python -m tools.generator_gui
```

生成器输入：

- MP4/AVI/MOV/MKV/WMV 等视频。
- GIF。

生成器输出：

- `.pixelbin` 播放文件。
- 可选预览 MP4。

当前坐标映射：

```text
x = 0..31，从左到右
y = 0..47，源视频/逻辑画面从上到下
slot = x / 8 + 1
lane = x % 8
pixel = 47 - y
```

原因：实际灯条每个 CH 从下往上串接，所以 host 在每条 lane 内做 `y` 翻转。

### Windows 自启播放

固定灯效文件放在：

```text
host_tool\autoplay\mode1.pixelbin
host_tool\autoplay\mode2.pixelbin
host_tool\autoplay\black.pixelbin
```

手动运行：

```powershell
cd host_tool
powershell -ExecutionPolicy Bypass -File .\autoplay.ps1
```

安装开机自启：

```powershell
cd host_tool
powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1
```

卸载开机自启：

```powershell
cd host_tool
powershell -ExecutionPolicy Bypass -File .\uninstall_autostart.ps1
```

自启逻辑：

- 开机打开控制台。
- 反复扫描 USB CDC 设备并 HELLO。
- 默认等待 4 块控制器全部连接。
- 等待期间轮询已连接板的 `STATUS_RSP.rc_event_bits`。
- 如果任意 RC 指令出现，立刻进入对应模式，不再等待缺失板。
- bit0 对应 `mode1.pixelbin`。
- bit1 对应 `mode2.pixelbin`。
- bit2 对应 `black.pixelbin`，即播放预存全黑视频。
- bit3 对应暂停，暂停时停止继续提交 RGB 帧，保持当前输出。
- 再次单击当前动作无效；单击其他动作立即切换。
- 播放期间继续轮询 RC，按键切换模式。
- 单板异常只打印 log 并跳过，不阻塞其他板。

## 当前测试进度

### 已验证

- Keil 工程曾在当前功能集下编译通过，最近一次用户反馈大小：
  `Code=25704 RO-data=360 RW-data=780 ZI-data=19684`，0 errors。
- USB CDC 枚举问题最终确认曾由硬件连锡导致；硬件修复后 USB 可正常通信。
- BSRR 驱动 WS2812 已能正常输出，前期验证过旧板前 4 路，新板恢复 8 路后可继续测试。
- 白光 PWM 通道基本功能已验证可输出。
- 上位机 CLI 可 HELLO、STATUS、SOLID、ALL_BLACK、发帧。
- GUI 自动识别多设备已验证可用。
- GUI 四键调试已基本可用：下位机 RC 事件可映射到 GUI 高亮和模式触发，GUI 手动按钮也可触发对应动作。
- USB Hub 多板通信曾出现 RX overflow，改为 4 chunk 后用户测试暂时解决。
- 48 逻辑像素/通道、4 chunk、约 60 fps 的 host 发送压力测试结果明显优于旧 2 chunk/8 chunk 方案。
- 视频/GIF 生成 `.pixelbin`、预览 MP4 功能已实现并做过语法级检查。
- Windows autoplay 第一版已实现并做过 `py_compile` 与 `--help` 检查。

### 未充分验证

- Windows 开机自启实机流程：从系统登录、设备枚举、等待 4 板、RC 强制切入、循环播放，还需要完整跑一遍。
- RC 接收机实机输出：当前固件会上报 `rc_event_bits` 按下事件，但仍需实机确认四个输入的电平、去抖和按键映射。
- ADC 检流和过流保护：代码存在，但当前宏关闭，实际阈值、接线和保护行为未完成验证。
- 白光通道在最终实负载上的温升、电流、频闪和 PWM 极性仍需确认。
- 4 块板经同一个 USB Hub 长时间 60 fps 播放稳定性还需要长时间测试。
- 上电顺序、USB Hub 识别延迟、Windows COM 号变化对 autoplay 的影响需要实机观察。

## 下一步优先验收

1. 下位机基础输出
   - 8 路 WS2812 是否都按 CH1..CH8 正确输出。
   - 每路上下方向是否与 `pixel = 47 - y` 匹配。
   - WW/CW 白光是否受上位机全局值控制。

2. 多板映射
   - 给 4 块板烧不同 `APP_ROLE_ID`。
   - GUI 自动连接后确认 role_id 升序对应 slot1..4。
   - 通道 1..32 逐列测试，确认物理顺序为从左到右。

3. `.pixelbin` 播放
   - 用 generator 生成简单方向性图案。
   - GUI 文件播放确认画面方向和板间拼接。
   - 用 `tools.autoplay` 播放 `mode1`、`mode2` 和 `black`。

4. RC 自启切换
   - 只接带 RC 的板和部分控制器，按键确认能强制进入对应模式。
   - 接齐 4 板，不按键确认默认进入 mode1。
   - 播放中按 bit0..bit3 确认模式切换。

5. 长时间稳定性
   - 4 板同 Hub 连续播放 30 分钟以上。
   - 观察 host log 中 err/skip 是否增长。
   - 必要时调大 `--chunk-delay-ms` 或降低文件 FPS。

6. 保护功能
   - ADC 接线确认后再打开 `APP_ENABLE_CURRENT_MONITOR`。
   - 校准电流读数。
   - 最后打开 `APP_ENABLE_CURRENT_PROTECT`，验证白光立即归零、WS2812 持续黑帧、只能复位恢复。

## 常调参数

### 下位机 `Core/Inc/app_config.h`

- `APP_ROLE_ID`：板号，1..20。
- `APP_WS2812_ACTIVE_LANES`：启用 WS2812 输出路数，正常新板为 8。
- `APP_ENABLE_REMOTE_INPUT`：RC 输入。
- `APP_ENABLE_CURRENT_MONITOR`：是否采样电流。
- `APP_ENABLE_CURRENT_PROTECT`：是否启用过流锁死保护。
- `APP_CURRENT_PROTECT_TRIP_MA`：过流阈值。
- `APP_COMM_LONG_TIMEOUT_MS`：上位机长时间无包后的黑屏阈值。
- `APP_WHITE_PWM_STEP_MS` / `APP_WHITE_PWM_STEP`：白光平滑速度。

### 上位机协议 `host_tool/pixel_host/protocol.py`

- `LEDS_PER_LANE = 48`
- `LANES = 8`
- `LANES_PER_CHUNK = 2`
- `FRAME_CHUNKS = 4`
- `MAX_PAYLOAD = 640`

这些参数必须和下位机 `comm_protocol.c` 保持一致。

### 自启播放

- `host_tool/autoplay.ps1`
  - `$ModeDir`
  - `$ChunkDelayMs`
  - `$RcPollInterval`
- `host_tool/tools/autoplay.py`
  - `--boards`
  - `--scan-interval`
  - `--rc-poll-interval`
  - `--chunk-delay-ms`
  - `--fps`

### 灯效生成

- 输出 FPS：通常 60。
- 画面裁剪：中心裁剪到 2:3。
- 输出尺寸：32 x 48。
- 亮度、gamma、饱和度：在 generator GUI 中调整。
- WW/CW：当前作为全局固定值写入 `.pixelbin`。

## 常见问题

### USB 设备管理器能看到但无法通信

- 确认不是硬件 D+/D-、上拉、电源或连锡问题。
- 确认 CAN 关闭，避免影响 USB 相关中断路径。
- 用 `python -m tools.scan_devices` 看是否 HELLO。
- 如果 Windows 分配了 COM 口但打开失败，先拔插、更换 USB 口或 Hub。

### 多板经 Hub 播放偶发 timeout / overflow

- 先看下位机调试变量：RX overflow、parser error、dropped bytes。
- 当前 4 chunk 方案是为 Hub burst 问题做的缓解。
- 可以尝试增大 host 的 `--chunk-delay-ms`，例如 0.25 -> 0.5。
- 若仍不稳，降低 `.pixelbin` FPS 或继续做 host 调度优化。

### 画面上下颠倒

- 当前物理灯条每 CH 从下往上串接。
- host 已在 `display_mapping.py` 使用 `pixel = 47 - y`。
- 如果现场接线再变化，优先修改 `host_tool/pixel_host/display_mapping.py`。

### 通道位置不对

- 确认 4 块板 `APP_ROLE_ID`。
- 上位机按 role_id 升序取最小 4 块，映射到 slot1..4。
- slot1 对应 CH1..8，slot2 对应 CH9..16，slot3 对应 CH17..24，slot4 对应 CH25..32。

### 自启播放没有开始

- 检查 `host_tool\autoplay\mode1.pixelbin` 等文件是否存在。
- 手动运行 `powershell -ExecutionPolicy Bypass -File .\autoplay.ps1` 看 log。
- 确认 Python 虚拟环境已安装：`setup_host_env.ps1`。
- 确认下位机 USB 能 HELLO。

### RC 按键偶尔漏触发

- 当前 host 轮询 `STATUS_RSP.rc_event_bits`。
- 如果按键没有响应，先用 `python -m tools.status COMx` 看 `rc_events` 是否出现。
- 若 `rc_bits` 变化但 `rc_events` 不出现，检查 RC 去抖和固件版本。

## 修改原则

- 改 `.ioc` 前必须明确授权，改完由用户重新生成代码并检查。
- Cube 生成文件尽量只改 USER CODE 区。
- 新功能优先放在应用层模块，不把业务逻辑塞进生成代码。
- 不要提交 `.pixelbin`、预览 MP4、`.venv`、Keil 输出目录。
- 大改前先同步 `SYSTEM_ARCHITECTURE.md` 的方案，实际使用说明同步本文件。
