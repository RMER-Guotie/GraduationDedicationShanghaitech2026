# Pixel Controller Firmware Handoff

## Workspace / Codex Launch Note

- For this project, start or reopen Codex with the working directory set to:
  `C:\Users\RMER_guotie\Desktop\graduation\pixel`
- If Codex is launched from `graduation\bsrr_test` while editing `graduation\pixel`, writes to the real project require approval/escalation and the client may not show the usual clickable `+xx -xx` diff card.
- If the diff card disappears after edits, first check that Codex's workspace/cwd is the `pixel` repo root, then continue work there.

## Project Rules

- Important collaboration rules are maintained in `CODEX_RULES.md`.
- Read `CODEX_RULES.md` before making any plan, code change, document change,
  `.ioc` change, build, run, or other high-cost action.
- This handoff file is for architecture, implementation status, hardware mapping,
  RAM/protocol decisions, progress, and known issues.

## Current Repo / Git Notes

- Project is now a git repo at `C:\Users\RMER_guotie\Desktop\graduation\pixel`.
- Initial commit seen previously:
  `d6daa65 first commit of bsrr test of graduation_dedication`
- A previous Keil build was run before the user asked not to compile further. This updated files under:
  `MDK-ARM\PIXEL_LIGHT\`
  including `.axf`, `.hex`, `.o`, `.map`, `.htm`, `.dep`, etc.
- Those build artifacts may appear in `git status` as modified/untracked. They are build outputs, not source edits.

## Hardware / Pin Mapping Confirmed From Correct Project

- MCU/project: STM32F103, Cube HAL project, Keil MDK project file `MDK-ARM\PIXEL_LIGHT.uvprojx`.
- WS2812 lanes use GPIOA:
  - CH1 = PA0
  - CH2 = PA1
  - CH3 = PA2
  - CH4 = PA3
  - CH5 = PA4
  - CH6 = PA5
  - CH7 = PA6
  - CH8 = PA7
- System-level LED array uses at least 4 downstream controller boards.
- Each downstream controller board controls only its own `8 x 96` WS2812B LEDs:
  8 output channels, 48 small boards per channel, 2 WS2812B LEDs per small board.
- The aggregate system is therefore at least `32 x 96` WS2812B LEDs, but this is
  split across multiple controllers. A single STM32 firmware instance must not
  allocate buffers for the whole aggregate array.
- `PA0-PA7` are configured high speed output in `.ioc` / regenerated GPIO code.
- TIM1 PWM pins are reserved for white LEDs:
  - `TIM1_CH1 / PA8 = WW` warm white
  - `TIM1_CH2 / PA9 = CW` cold white
- RC inputs intended mapping:
  - bit0 = RC_D0 = PB11
  - bit1 = RC_D1 = PB10
  - bit2 = RC_D2 = PB2
  - bit3 = RC_D3 = PB1
- `PB2` is BOOT1-related; hardware must not force wrong boot state at reset.
- PB0 is current sense input `ADC1_IN8`; generated `Core/Src/adc.c` now configures ADC1 regular conversion on channel 8.

## Implemented Source Modules

### 1. WS2812 BSRR DMA Test Driver

Files added:

- `Core/Inc/ws2812_bsr_dma.h`
- `Core/Src/ws2812_bsr_dma.c`

Behavior:

- Drives 8 WS2812 lanes on GPIOA `PA0-PA7` using GPIOA `BSRR` writes.
- Uses TIM4 as trigger source, not TIM1.
- DMA mapping used:
  - `TIM4_UP -> DMA1_Channel7`: set all active lanes high at bit start.
  - `TIM4_CH1 -> DMA1_Channel1`: reset lanes carrying 0 bits.
  - `TIM4_CH2 -> DMA1_Channel4`: reset all lanes and trigger transfer complete interrupt.
- Timing constants in driver:
  - timer period = 89 ticks, 72 MHz clock assumed, about 1.25 us bit period.
  - zero compare = 29 ticks, about 0.40 us high.
  - one compare = 58 ticks, about 0.81 us high.
- Per-controller data size: `8 lanes x 96 LEDs`, RGB888 stored in software, GRB transmitted to WS2812B.
- Each lane's 96 LEDs come from `48` small boards with `2` cascaded WS2812B LEDs
  on each small board.
- Current RGB software frame is `ws2812_frame[8][96]`, size `2304 bytes`.
- Current DMA BSRR encoding buffer is `ws2812_zero_reset_buffer[96 * 24]`, size `9216 bytes`.
  It stores one 32-bit GPIOA BSRR reset mask per WS2812 bit. It is not USB data
  and is not an RGB frame.
- `WS2812_BSR_Show()` encodes the current RGB frame, starts three TIM4-paced DMA
  streams, and returns without blocking.
- Busy state covers both active DMA transmission and the WS2812 reset latch
  window. Current latch wait is `1 ms`; current show timeout guard is `20 ms`.
- Includes test pattern API `WS2812_BSR_TestPatternStep()` for rainbow/breathing visual test.
- Includes fault API `WS2812_BSR_ForceBlack()` to abort active DMA, force PA0-PA7 low, and clear the frame buffer.
- Defines `DMA1_Channel4_IRQHandler()` in the driver file to override startup weak handler. No edit was made to `stm32f1xx_it.c`.
- The built-in test pattern is only a validation mode. Formal host control should
  replace it with committed protocol frames.

Important APIs:

```c
void WS2812_BSR_Init(void);
void WS2812_BSR_Clear(void);
void WS2812_BSR_FillAll(uint8_t r, uint8_t g, uint8_t b);
void WS2812_BSR_FillLane(uint8_t lane, uint8_t r, uint8_t g, uint8_t b);
void WS2812_BSR_SetPixel(uint8_t lane, uint16_t index, uint8_t r, uint8_t g, uint8_t b);
void WS2812_BSR_Show(void);
void WS2812_BSR_ForceBlack(void);
void WS2812_BSR_Poll(void);
void WS2812_BSR_Wait(void);
uint8_t WS2812_BSR_IsBusy(void);
void WS2812_BSR_TestPatternStep(uint32_t now_ms);
```

Debug globals include show/complete/error/timeout/start-error counters.

### 2. RC Input Module

Files added:

- `Core/Inc/remote_input.h`
- `Core/Src/remote_input.c`

Behavior:

- Generated `gpio.c` configures PB1/PB2/PB10/PB11 as input with pulldown.
- `RemoteInput_Init()` also reconfigures PB1/PB2/PB10/PB11 as input with pulldown
  at runtime to keep the RC module robust after future CubeMX regeneration.
- Active high.
- Polling debounce, default `5 ms`.
- Current implementation is still polling-based. The planned final RC design is
  EXTI-based and is recorded in the planned RC section below.

APIs:

```c
void RemoteInput_Init(void);
void RemoteInput_Poll(uint32_t now_ms);
uint8_t RemoteInput_GetRawBits(void);
uint8_t RemoteInput_GetStableBits(void);
uint8_t RemoteInput_ConsumeChangedBits(void);
uint32_t RemoteInput_GetEdgeCount(uint8_t channel);
```

Debug globals:

```c
remote_input_watch_raw_bits
remote_input_watch_stable_bits
remote_input_watch_changed_bits
remote_input_watch_edge_count[4]
```

### 3. App Config Header

File added:

- `Core/Inc/app_config.h`

Current intended macros:

```c
#define APP_RC_ACTIVE_HIGH          1U
#define APP_RC_PULL_MODE            GPIO_PULLDOWN
#define APP_RC_DEBOUNCE_MS          5U
#define APP_TEST_RC_STATUS_ENABLE   1U

#define APP_WHITE_PWM_MAX_LEVEL      1000U
#define APP_WHITE_PWM_STEP_MS        2U
#define APP_WHITE_PWM_STEP           5U
#define APP_WHITE_PWM_TIM1_PSC       0U
#define APP_WHITE_PWM_TIM1_ARR       3599U
#define APP_TEST_WHITE_PWM_ENABLE    1U

#define APP_CURRENT_PROTECT_SAMPLE_MS     5U
#define APP_CURRENT_PROTECT_TRIP_MA       16000U
#define APP_CURRENT_PROTECT_RELEASE_MA    14000U
#define APP_CURRENT_SENSE_SHUNT_UOHM      500U
#define APP_CURRENT_SENSE_GAIN            50U
#define APP_CURRENT_ADC_VREF_MV           3300U
#define APP_CURRENT_ADC_MAX_COUNTS        4095U
#define APP_CURRENT_ADC_TIMEOUT_MS        2U
#define APP_CURRENT_FILTER_SHIFT          3U
```

Note: `app_config.h` currently uses `GPIO_PULLDOWN`; ensure any file including it already has HAL GPIO definitions through `main.h` or relevant HAL includes. `remote_input.c` includes `main.h` before `app_config.h`, so it is OK there.

### 4. White PWM Module

Files added:

- `Core/Inc/white_pwm.h`
- `Core/Src/white_pwm.c`

Behavior:

- `TIM1_CH1 = WW` warm white.
- `TIM1_CH2 = CW` cold white.
- Physical pins are `PA8 = WW` and `PA9 = CW`.
- TIM1 target PWM frequency is 20 kHz with `PSC = 0`, `ARR = 3599`, assuming a
  72 MHz TIM1 clock.
- Public brightness range: `0..1000`.
- `Set` APIs update targets only.
- `WhitePwm_Poll()` smooths current level toward target.
- Default smoothing: every `2 ms`, step `5 / 1000`, 0 to 100% in about 400 ms.
- Starts PWM on both TIM1 channels in `WhitePwm_Init()` and initially sets both to 0.
- Compare value conversion is:

```text
CCR = round((ARR + 1) * level / 1000)
```

- `WhitePwm_Off()` is the protection path. It bypasses smoothing and immediately
  sets target, current, and TIM1 compare values to zero.
- In the planned communication architecture, WW/CW values are frame metadata and
  take effect only after a successful `FRAME_COMMIT`.

APIs:

```c
void WhitePwm_Init(void);
void WhitePwm_Poll(uint32_t now_ms);
void WhitePwm_SetWW(uint16_t level);
void WhitePwm_SetCW(uint16_t level);
void WhitePwm_SetBoth(uint16_t ww, uint16_t cw);
uint16_t WhitePwm_GetWW(void);
uint16_t WhitePwm_GetCW(void);
void WhitePwm_Off(void);
```

Debug globals:

```c
white_pwm_watch_ww_target
white_pwm_watch_cw_target
white_pwm_watch_ww_current
white_pwm_watch_cw_current
```

### 5. Current Protection Module

Files added:

- `Core/Inc/current_protect.h`
- `Core/Src/current_protect.c`

Behavior:

- Uses ADC1 regular conversion on `ADC_CHANNEL_8` / PB0.
- Reconfigures ADC channel 8 at module init for robustness, then starts ADC calibration.
- Samples every `5 ms` from the cooperative main-loop scheduler.
- Uses a single software-triggered ADC conversion per sample; no ADC DMA is used.
- Converts ADC counts using a 0.5 mOhm shunt, 50x current sense gain, 3.3 V reference, and 12-bit ADC full scale.
- Current conversion formula:

```text
I_mA = ADC_raw * Vref_mV * 1,000,000 / (4095 * gain * shunt_uohm)
```

- Applies a small IIR filter before comparing thresholds.
- Trips at `16000 mA`, releases at `14000 mA`.
- On fault, calls `WhitePwm_Off()` every poll; `WhitePwm_Off()` now immediately zeros target/current levels and TIM1 compare registers.
- On fault entry, `AppController` calls `WS2812_BSR_ForceBlack()` to abort active WS2812 output and force lanes low.
- While fault remains active, `AppController` suppresses the WS2812 test pattern and retransmits an all-black WS2812 frame whenever the WS2812 driver is idle.
- Fault state auto-clears only after the filtered current estimate is at or below
  the release threshold.

APIs:

```c
void CurrentProtect_Init(void);
void CurrentProtect_Poll(uint32_t now_ms);
uint8_t CurrentProtect_IsFaultActive(void);
uint16_t CurrentProtect_GetAdcRaw(void);
uint32_t CurrentProtect_GetCurrentMa(void);
```

Debug globals:

```c
current_protect_watch_adc_raw
current_protect_watch_current_ma
current_protect_watch_fault
current_protect_watch_trip_count
```

### 6. App Controller Module

Files added:

- `Core/Inc/app_controller.h`
- `Core/Src/app_controller.c`

Behavior:

- Owns application-level initialization and cooperative scheduling.
- Keeps Cube-generated `main.c` thin: `main.c` only calls `AppController_Init()` after peripheral init and `AppController_Poll(HAL_GetTick())` in the loop.
- Poll order is:
  - `CommTransport_Poll(now_ms)`
  - `CommProtocol_Poll(now_ms)`
  - `RemoteInput_Poll(now_ms)`
  - `CurrentProtect_Poll(now_ms)`
  - `WhitePwm_Poll(now_ms)`
  - fault handling or WS2812 test pattern handling
- On fault entry, calls `WS2812_BSR_ForceBlack()`.
- During active fault, retransmits black WS2812 frames whenever idle.
- During normal mode, protocol output owns WS2812 once any valid host protocol
  packet is received. Before host control starts, the built-in WS2812 validation
  pattern can still run.

APIs:

```c
void AppController_Init(void);
void AppController_Poll(uint32_t now_ms);
```

Debug globals:

```c
app_controller_watch_loop_count
app_controller_watch_fault_active
app_controller_watch_rc_stable_bits
```

### 7. Communication Transport Module

Files added:

- `Core/Inc/comm_transport.h`
- `Core/Src/comm_transport.c`

Behavior:

- Implements the shared byte transport for USB CDC and UART.
- Defines a statically allocated shared RX ring:

```c
#define COMM_RX_RING_SIZE  256U
uint8_t comm_transport_rx_ring[COMM_RX_RING_SIZE];
```

- `CDC_Receive_FS()` copies each USB CDC receive callback payload into this ring
  and immediately re-arms USB receive.
- No protocol parsing, frame transaction handling, or lighting output update is
  done in the USB callback.
- UART RX uses USART1 RX DMA1 Channel5 in circular mode and writes directly into
  the same `comm_transport_rx_ring[256]`.
- USART1 baud is overridden at runtime to `APP_COMM_UART_BAUD = 921600`; `.ioc`
  was not changed for this step.
- UART TX does not use DMA. Small responses use blocking `HAL_UART_Transmit()`.
- USB TX responses use one static `COMM_TX_BUFFER_SIZE = 128` buffer and retry
  while CDC is busy; no large TX queue is implemented.
- Active transport is tracked as none / USB / UART. When the active link changes,
  the transport marks a link-change flag so the protocol layer can reset parser
  and frame transaction state.
- If a USB packet does not fit in the ring, the packet is dropped as a whole,
  overflow state is recorded, and future parser logic must resynchronize at the
  next sync word.
- Ring access uses a short critical section because USB receive can write from
  interrupt context while the main loop or future parser reads.
- `CommTransport_Poll()` refreshes UART DMA write position, debug/watch variables,
  and pending USB TX state.

APIs:

```c
void CommTransport_Init(void);
void CommTransport_Poll(uint32_t now_ms);
uint16_t CommTransport_WriteFromUsb(const uint8_t *data, uint16_t len);
uint16_t CommTransport_Read(uint8_t *data, uint16_t max_len);
uint16_t CommTransport_Send(const uint8_t *data, uint16_t len);
void CommTransport_ClearRx(void);
uint16_t CommTransport_GetRxUsed(void);
uint8_t CommTransport_ConsumeOverflow(void);
uint8_t CommTransport_ConsumeLinkChanged(void);
CommTransportLink_t CommTransport_GetActiveLink(void);
```

Debug globals:

```c
comm_transport_rx_ring[256]
comm_transport_watch_rx_write_index
comm_transport_watch_rx_read_index
comm_transport_watch_rx_used
comm_transport_watch_rx_max_used
comm_transport_watch_rx_overflow_pending
comm_transport_watch_usb_packet_count
comm_transport_watch_rx_total_bytes
comm_transport_watch_rx_dropped_bytes
comm_transport_watch_rx_overflow_count
comm_transport_watch_active_link
comm_transport_watch_link_changed
comm_transport_watch_uart_dma_started
comm_transport_watch_tx_state
comm_transport_watch_uart_byte_count
comm_transport_watch_link_switch_count
comm_transport_watch_tx_packet_count
comm_transport_watch_tx_busy_drop_count
comm_transport_watch_tx_error_count
```

### 8. Communication Protocol Module

Files added:

- `Core/Inc/comm_protocol.h`
- `Core/Src/comm_protocol.c`
- `COMM_PROTOCOL.md`

Behavior:

- Implements the first USB/UART parser and frame transaction layer.
- Packet format is:

```text
sync0 sync1 version type seq payload_len flags payload crc16
```

- Sync is `0x5A 0xA5`.
- Version is `APP_COMM_PROTOCOL_VERSION = 1`.
- CRC is CRC16-CCITT-FALSE over `version..payload`.
- Parser state machine is implemented as:

```text
WAIT_SYNC0 -> WAIT_SYNC1 -> READ_HEADER -> READ_PAYLOAD -> READ_CRC0 -> READ_CRC1
```

- Implemented message types:
  - `HELLO_REQ`
  - `HELLO_RSP`
  - `FRAME_BEGIN`
  - `FRAME_RGB_CHUNK`
  - `FRAME_COMMIT`
  - `ALL_BLACK`
  - `STATUS_REQ`
  - `STATUS_RSP`
  - `ERROR_RSP`
- `uid_hash` is derived from the STM32 UID base address and returned in
  `HELLO_RSP`; `role_id` is currently `0xFF` / unknown.
- A statically allocated staging RGB frame stores one uncommitted `8 x 96 x RGB`
  frame, adding `2304 bytes` RAM.
- One full frame uses 16 chunks. Each chunk carries 144 bytes = 48 RGB pixels.
- Chunk mapping is lane-major:
  - chunk 0/1 -> lane 0 pixels 0..47 / 48..95,
  - chunk 2/3 -> lane 1,
  - ...
  - chunk 14/15 -> lane 7.
- `FRAME_BEGIN` records frame ID, chunk count, WW/CW metadata, and optional
  frame CRC32. The current first version stores but does not verify frame CRC32.
- CRC-valid chunks write only into the staging frame and update `received_mask`.
- `FRAME_COMMIT` succeeds only when frame ID matches, all 16 chunks are received,
  no severe transaction error is active, and overcurrent fault is inactive.
- Successful commit copies staging RGB into the WS2812 software frame, applies
  WW/CW target levels, and triggers WS2812 output. If WS2812 DMA is busy, it
  sets `pending_show` and sends the newest committed frame after DMA becomes idle.
- `FRAME_COMMIT` always sends a response using message type `FRAME_COMMIT`.
- `ALL_BLACK` discards any active frame transaction, calls `WhitePwm_Off()`, and
  calls `WS2812_BSR_ForceBlack()`.
- After host control starts, if no valid protocol packet is received for
  `APP_COMM_LONG_TIMEOUT_MS = 10000`, output is forced black.
- Overcurrent protection remains higher priority than protocol output.

APIs:

```c
void CommProtocol_Init(void);
void CommProtocol_Poll(uint32_t now_ms);
void CommProtocol_OutputPoll(uint32_t now_ms);
uint8_t CommProtocol_HasOutputControl(void);
void CommProtocol_Reset(void);
```

Debug globals:

```c
comm_protocol_watch_parser_state
comm_protocol_watch_host_control_active
comm_protocol_watch_pending_show
comm_protocol_watch_last_error
comm_protocol_watch_frame_id
comm_protocol_watch_received_mask
comm_protocol_watch_uid_hash
comm_protocol_watch_packet_count
comm_protocol_watch_crc_error_count
comm_protocol_watch_parser_error_count
comm_protocol_watch_commit_count
comm_protocol_watch_commit_error_count
comm_protocol_watch_timeout_black_count
comm_protocol_watch_last_valid_packet_ms
```

## Planned ADC Current Protection Architecture

This section records the current-protection design constraints. Do not change
thresholds, sampling method, or fault behavior until the user authorizes the
specific implementation step.

- ADC current sense input is PB0 / `ADC1_IN8`.
- Current protection remains a cooperative polling task, not an interrupt or DMA
  pipeline.
- Default sample period is `APP_CURRENT_PROTECT_SAMPLE_MS = 5 ms`.
- ADC conversion remains single-channel, software-triggered, and non-DMA unless
  later bench testing shows polling is insufficient.
- Filtering remains an IIR filter controlled by `APP_CURRENT_FILTER_SHIFT`.
- Default electrical parameters:
  - shunt: `APP_CURRENT_SENSE_SHUNT_UOHM = 500` micro-ohms,
  - current sense gain: `APP_CURRENT_SENSE_GAIN = 50`,
  - ADC reference: `APP_CURRENT_ADC_VREF_MV = 3300`,
  - ADC max count: `APP_CURRENT_ADC_MAX_COUNTS = 4095`.
- Default hysteresis:
  - trip: `APP_CURRENT_PROTECT_TRIP_MA = 16000`,
  - release: `APP_CURRENT_PROTECT_RELEASE_MA = 14000`.
- Fault behavior:
  - white PWM is forced to zero immediately and repeatedly while fault is active,
  - WS2812 output is forced black on fault entry,
  - WS2812 black frames continue to be sent whenever the WS2812 driver is idle,
  - protocol or display frames must not override an active overcurrent fault.
- Hardware threshold accuracy must be validated on the bench because the current
  estimate depends on shunt value, amplifier gain, ADC reference, and layout
  noise.

## Planned RC EXTI Input Architecture

This section records the confirmed RC input direction. Do not implement this
EXTI migration until the user authorizes the specific implementation step.

- RC physical mapping remains:
  - `D0 = PB11`
  - `D1 = PB10`
  - `D2 = PB2`
  - `D3 = PB1`
- The final RC input module should use external interrupts on rising and falling
  edges.
- First implementation should avoid `.ioc` changes unless the user separately
  authorizes them. Runtime GPIO configuration in `RemoteInput_Init()` is
  acceptable.
- Required interrupt lines:
  - `EXTI1` for PB1 / D3,
  - `EXTI2` for PB2 / D2,
  - `EXTI15_10` for PB10 / D1 and PB11 / D0.
- EXTI handlers should be lightweight:
  - sample or mark raw state,
  - update edge counters or pending flags,
  - record timestamp if needed,
  - avoid debounce logic,
  - avoid direct lighting output changes.
- `RemoteInput_Poll(now_ms)` should continue to own debounce and stable-state
  publication.
- Debounce target remains `APP_RC_DEBOUNCE_MS = 5 ms`.
- The module should expose a global/state API containing only the four RC state
  values plus optional debug/watch fields.
- RC state is an input to higher-level control logic only. It must not be mapped
  directly to white PWM or WS2812 pixels unless the user later defines that
  behavior.
- PB2 is BOOT1-related, so hardware must not force an invalid boot level at
  reset.

## Planned USB / UART Communication Architecture

This section records the confirmed communication design and current first
implementation status. Further protocol, buffering, or `.ioc` changes still need
separate authorization.

### Transport Ownership

- USB CDC and UART share one protocol parser, frame transaction state machine,
  and frame commit path.
- Only one transport is active at a time.
- Switching the active transport must clear:
  - the shared RX ring,
  - parser state,
  - the current frame transaction.
- This prevents partial packets from one link from contaminating the next link.
- Current implementation tracks active link and resets parser/transaction on a
  link-change flag.

### USB CDC Layer

- USB CDC is treated as a byte stream. One `CDC_Receive_FS()` callback is not a
  complete protocol packet.
- USB receive stage is implemented. `CDC_Receive_FS()` now only:
  - copy `Buf[0..Len-1]` into the shared application RX ring,
  - immediately re-arm USB receive,
  - avoid protocol parsing,
  - avoid direct lighting output updates.
- Current CDC temporary buffer sizes are:

```c
#define APP_RX_DATA_SIZE  256
#define APP_TX_DATA_SIZE  128
```

- The device sends only small responses such as `HELLO_RSP`, commit result,
  `STATUS_RSP`, and `ERROR_RSP`.
- `FRAME_COMMIT` success or failure must produce a response.
- Per-chunk ACK is not required by default unless a debug stage explicitly needs it.
- `CDC_Transmit_FS()` may return `USBD_BUSY`; TX code must handle this without
  blocking lighting output.
- Current USB TX handling uses one 128-byte static response buffer and drops a
  new response if the previous response is still in flight.
- `CDC_Control_FS()` now keeps a minimal line-coding state for host
  `SET_LINE_CODING` / `GET_LINE_CODING` requests. The default reported line
  coding is 921600 8N1.
- `CDC_Transmit_FS()` now checks for null payloads and an unenumerated USB CDC
  class handle before accessing `TxState`.

### Shared RX Ring

- The first version uses one statically allocated shared RX ring:

```c
#define COMM_RX_RING_SIZE  256U
```

- USB writes received bytes into this ring by software copy.
- UART RX DMA writes directly into this same ring; no separate UART raw DMA
  buffer should be added in the first version.
- The user confirmed this is acceptable because only USB or UART will be active
  at one time.
- The ring is intentionally static so it can be inspected directly during debug.
- If the RX ring overflows, discard the current frame transaction and wait for
  the next sync word to re-synchronize.

Bandwidth estimate:

- Per-controller full RGB frame size: `8 * 96 * 3 = 2304 bytes`.
- The host owns any aggregate `32 x 96` or larger system layout and distributes
  each controller's own `8 x 96` frame by device identity.
- With protocol overhead, estimate about `2500..2600 bytes/frame`.
- At `60 fps`, input is about `150..156 KB/s`; a 256-byte RX ring covers about
  `1.6 ms`.
- At `120 fps`, input is about `300..312 KB/s`; a 256-byte RX ring covers about
  `0.8 ms`.
- Therefore `60 fps` is the guaranteed design target. `120 fps` is only a stress
  estimate and requires the main loop to drain communication data very often.

### UART Layer

- UART uses the same protocol as USB.
- USART1 is currently configured on PB6/PB7.
- First UART baud target: `921600`.
- If bench testing shows low loss/error rate, baud can be increased later.
- UART RX must use DMA.
- Preferred DMA mapping for USART1 RX is DMA1 Channel5, which does not conflict
  with the current WS2812 DMA use of DMA1 Channels 1, 4, and 7.
- UART TX should not use DMA in the first version because USART1 TX commonly
  maps to DMA1 Channel4, which is already used by WS2812 TIM4_CH2.
- At `921600` baud with 8N1 framing, effective throughput is about `92 KB/s`.
  This is not enough for 60 fps full-frame RGB, so UART is a lower-frame-rate
  backup/debug transport unless a higher baud is validated later.
- Current implementation starts USART1 RX DMA1 Channel5 in circular mode from
  `CommTransport_Init()` and overrides baud to `921600` at runtime. `.ioc` was
  not modified for this.

### Protocol And Frame Transaction

- Protocol packets must have explicit boundaries and must not be raw RGB bytes.
- Packet fields are implemented as:
  - sync,
  - version,
  - type,
  - packet sequence,
  - payload length,
  - flags,
  - payload,
  - CRC16.
- Parser state machine implemented:

```text
WAIT_SYNC0 -> WAIT_SYNC1 -> READ_HEADER -> READ_PAYLOAD -> READ_CRC0 -> READ_CRC1 -> DISPATCH
```

- Parser checks:
  - sync,
  - payload length bounds,
  - message type,
  - CRC16,
  - frame ID.
- Errors must not corrupt the active frame. Uncommitted data can only affect the
  back/staging frame.

Confirmed message types:

- `HELLO_REQ`
- `HELLO_RSP`
- `FRAME_BEGIN`
- `FRAME_RGB_CHUNK`
- `FRAME_COMMIT`
- `ALL_BLACK`
- `STATUS_REQ`
- `STATUS_RSP`
- `ERROR_RSP`

Frame transaction rules:

- `FRAME_BEGIN` starts a transaction and records frame ID, chunk count, optional
  frame CRC32, and WW/CW frame metadata. Current implementation stores but does
  not verify frame CRC32.
- WW/CW white levels are stored as frame metadata and take effect only after a
  successful `FRAME_COMMIT`.
- Each RGB chunk is planned as 144 bytes, representing 48 RGB LEDs.
- One full frame has 16 RGB chunks.
- CRC-valid chunks are written to the back/staging frame at their target offset.
- A `received_mask` tracks the 16 chunks.
- `FRAME_COMMIT` is accepted only when frame ID matches, all chunks are received,
  and no severe transaction error is active.
- `COMM_PROTOCOL.md` is the host-facing protocol handoff document.

### Frame Output And Timeout Policy

- `FRAME_COMMIT` swaps active/back frame ownership and schedules WS2812 output.
- If WS2812 DMA is busy at commit time, use the confirmed `pending_show`
  strategy. The latest committed frame is shown after DMA completion.
- The main loop scheduling may be changed later to remove or reduce the fixed
  `HAL_Delay(1)` so communication draining is not delayed.
- Short communication timeout keeps the last committed frame.
- Long communication timeout outputs black. The initial long-time threshold is
  `10 seconds`, configurable by macro later.
- `ALL_BLACK` is a high-priority command.
- Existing overcurrent protection behavior must be preserved.
- Current implementation rejects `FRAME_COMMIT` while overcurrent fault is active.

### Device Identity

- First version identifies the board through `uid_hash`.
- `uid_hash` is derived from STM32 UID and returned in `HELLO_RSP`.
- `role_id` is not implemented in the first version. If a board-number GPIO,
  solder option, DIP switch, or compile-time role is added later, `HELLO_RSP`
  can be extended.
- The host must not rely on COM port order to identify multiple boards.

## Main Integration

`Core/Src/main.c` was modified only inside USER CODE sections:

- Includes:

```c
#include "app_controller.h"
```

- Init section:

```c
AppController_Init();
```

- Main loop USER CODE section:

```c
AppController_Poll(HAL_GetTick());
HAL_Delay(1);
```

## Keil Project Integration

`MDK-ARM\PIXEL_LIGHT.uvprojx` was modified to include:

- `../Core/Src/ws2812_bsr_dma.c`
- `../Core/Src/remote_input.c`
- `../Core/Src/white_pwm.c`
- `../Core/Src/current_protect.c`
- `../Core/Src/app_controller.c`
- `../Core/Src/comm_transport.c`
- `../Core/Src/comm_protocol.c`

## IOC Changes Made

ADC1 current sense input was changed in `pixel_light.ioc` after user approval:

```text
ADC1.Channel-0\#ChannelRegularConversion=ADC_CHANNEL_8
ADC1.SamplingTime-0\#ChannelRegularConversion=ADC_SAMPLETIME_55CYCLES_5
Mcu.PinsNb=33
```

The previous internal temperature sensor virtual input `VP_ADC1_TempSens_Input` was removed. `PB0.Signal=ADCx_IN8` and `SH.ADCx_IN8.0=ADC1_IN8,IN8` remain in the IOC.

Current generated `Core/Src/adc.c` also configures `ADC_CHANNEL_8` with `ADC_SAMPLETIME_55CYCLES_5`.

Only `.ioc` white PWM timing was changed after user approval:

```text
TIM1.Prescaler=0
TIM1.Period=3599
TIM1.IPParameters=Channel-PWM Generation1 CH1,Channel-PWM Generation2 CH2,Prescaler,Period
```

This targets about 20 kHz PWM at 72 MHz TIM1 clock:

```text
72 MHz / (0 + 1) / (3599 + 1) = 20 kHz
```

Important: `tim.c` is still generated code. After this `.ioc` change, the user must regenerate with CubeMX for generated `MX_TIM1_Init()` to actually use ARR 3599. Do not manually edit `tim.c` generated area.

RC input pins were also aligned in `pixel_light.ioc` after user authorization:

```text
PB11 / RC_D0 = GPIO_Input, GPIO_PULLDOWN
PB10 / RC_D1 = GPIO_Input, GPIO_PULLDOWN
PB2  / RC_D2 = GPIO_Input, GPIO_PULLDOWN
PB1  / RC_D3 = GPIO_Input, GPIO_PULLDOWN
```

Generated `Core/Src/gpio.c` is now also aligned to configure these four pins as
input pulldown. `RemoteInput_Init()` still repeats the same configuration at
runtime for robustness.

## Last Build Status

A Keil command-line build was run after user authorization while validating the
first USB/UART protocol implementation and CDC buffer shrink.

Current result:

```text
0 Error(s), 0 Warning(s)
Program Size: Code=26732 RO-data=376 RW-data=728 ZI-data=19592
Total RW Size: 20320 bytes
RW_IRAM1: 0x4f60 / 0x5000
RAM remaining: 160 bytes
```

The build passes, but RAM margin is extremely small. The current design keeps
both `ws2812_frame[2304]` and `comm_protocol_staging_frame[2304]` as approved.
If later features add more global/static RAM, revisit heap/stack sizing, USB
descriptor buffer size, or the frame-staging strategy.

## Known Checks / Potential Issues For Next Agent

1. Do not use or modify `graduation\bsrr_test`; it was the earlier wrong target.
2. Do not run local compiler unless user explicitly asks.
3. If checking source consistency without compiling:
   - Verify `app_config.h` still contains white PWM macros.
   - Verify `white_pwm.c` contains:
     ```c
     #define WHITE_PWM_WW_TIM_CHANNEL  TIM_CHANNEL_1
     #define WHITE_PWM_CW_TIM_CHANNEL  TIM_CHANNEL_2
     ```
   - Verify `.ioc` TIM1 fields are on separate lines, not concatenated.
4. `.ioc` has TIM1 20 kHz settings and current `Core/Src/tim.c` already shows `htim1.Init.Period = 3599`.
5. Current protection is implemented, but hardware thresholds should still be validated on the bench because the calculation assumes 0.5 mOhm shunt, 50x gain, and 3.3 V ADC reference.
6. WS2812 fault handling now uses `WS2812_BSR_ForceBlack()` on fault entry, then retransmits an all-black frame whenever idle.
7. USB/UART protocol code now compiles in Keil with 0 errors and 0 warnings, but
   it still needs bench/host-side communication testing.
8. UART RX DMA writes directly into the shared 256-byte RX ring. This relies on
   the confirmed hardware usage that only USB or UART is active at one time.
9. The first protocol implementation stores `frame_crc32` from `FRAME_BEGIN` but
   does not verify it yet; packet-level CRC16 is implemented.

## Suggested Commit Message For Current Source State

```text
add ws2812 bsrr driver, rc input, white pwm, and current protection

- add TIM4/DMA GPIOA BSRR WS2812 test driver
- add RC_D0-D3 input state/debounce module
- add TIM1 CH1/CH2 WW/CW white PWM control with smoothing
- add ADC1_IN8 current protection with filtered 16A trip / 14A release
- add app controller scheduler for application-level polling and fault handling
- hook modules through main USER CODE sections
- set TIM1 PWM target to 20 kHz in ioc
```
