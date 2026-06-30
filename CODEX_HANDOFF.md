# Pixel Controller Firmware Handoff

## Conversation Rules / User Constraints

- Always begin replies with: `guotie你好`.
- Correct active project path is:
  `C:\Users\RMER_guotie\Desktop\graduation\pixel`
- Earlier edits were accidentally made in the wrong folder:
  `C:\Users\RMER_guotie\Desktop\graduation\bsrr_test`
  Treat that folder only as historical reference. Continue all future work in `graduation\pixel`.
- Do not modify Cube-generated code outside `/* USER CODE BEGIN ... */` and `/* USER CODE END ... */` blocks unless the user explicitly allows it.
- Prefer adding new module files for application logic.
- Do not arbitrarily modify `.ioc`; if `.ioc` changes are needed, explain the exact plan first and wait for user confirmation unless the user has explicitly authorized that specific change.
- Do not call the local compiler/build tools unless the user explicitly asks. The user specifically requested this after the white PWM discussion.
- Before each implementation step, summarize the concrete implementation method and let the user correct it.

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
- PB0 is intended by hardware as current sense input `ADC1_IN8`, but at last inspection ADC regular conversion was still generated as internal temperature sensor. Current protection is not implemented yet.

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
- Data size: `8 lanes x 96 LEDs`, RGB888 stored, GRB output.
- Includes test pattern API `WS2812_BSR_TestPatternStep()` for rainbow/breathing visual test.
- Defines `DMA1_Channel4_IRQHandler()` in the driver file to override startup weak handler. No edit was made to `stm32f1xx_it.c`.

Important APIs:

```c
void WS2812_BSR_Init(void);
void WS2812_BSR_Clear(void);
void WS2812_BSR_FillAll(uint8_t r, uint8_t g, uint8_t b);
void WS2812_BSR_FillLane(uint8_t lane, uint8_t r, uint8_t g, uint8_t b);
void WS2812_BSR_SetPixel(uint8_t lane, uint16_t index, uint8_t r, uint8_t g, uint8_t b);
void WS2812_BSR_Show(void);
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

- Runtime reconfigures PB1/PB2/PB10/PB11 as input with pulldown in `RemoteInput_Init()`.
- Does not modify Cube-generated `gpio.c`.
- Active high.
- Polling debounce, default `5 ms`.

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
```

Note: `app_config.h` currently uses `GPIO_PULLDOWN`; ensure any file including it already has HAL GPIO definitions through `main.h` or relevant HAL includes. `remote_input.c` includes `main.h` before `app_config.h`, so it is OK there.

### 4. White PWM Module

Files added:

- `Core/Inc/white_pwm.h`
- `Core/Src/white_pwm.c`

Behavior:

- `TIM1_CH1 = WW` warm white.
- `TIM1_CH2 = CW` cold white.
- Public brightness range: `0..1000`.
- `Set` APIs update targets only.
- `WhitePwm_Poll()` smooths current level toward target.
- Default smoothing: every `2 ms`, step `5 / 1000`, 0 to 100% in about 400 ms.
- Starts PWM on both TIM1 channels in `WhitePwm_Init()` and initially sets both to 0.

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

## Main Integration

`Core/Src/main.c` was modified only inside USER CODE sections:

- Includes:

```c
#include "ws2812_bsr_dma.h"
#include "remote_input.h"
#include "white_pwm.h"
```

- Init section:

```c
WS2812_BSR_Init();
RemoteInput_Init();
WhitePwm_Init();
```

- Main loop USER CODE section:

```c
RemoteInput_Poll(HAL_GetTick());
WhitePwm_Poll(HAL_GetTick());
WS2812_BSR_TestPatternStep(HAL_GetTick());
HAL_Delay(1);
```

## Keil Project Integration

`MDK-ARM\PIXEL_LIGHT.uvprojx` was modified to include:

- `../Core/Src/ws2812_bsr_dma.c`
- `../Core/Src/remote_input.c`
- `../Core/Src/white_pwm.c`

## IOC Changes Made

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

## Last Build Status

A Keil build was run before the user asked not to compile without request.

Result at that time, before white_pwm module was added:

```text
0 Error(s), 7 Warning(s)
Program Size: Code=19860 RO-data=360 RW-data=460 ZI-data=18324
```

The warnings were only missing final newline warnings in newly added files. Those newline issues were later fixed. No build has been run after adding `white_pwm`.

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
4. `.ioc` has TIM1 20 kHz settings, but generated `tim.c` will not update until Cube regeneration.
5. Current WS2812 test pattern still runs continuously in `main.c`; future overcurrent protection should disable this during fault.

## Proposed Next Module: Current Protection

Do not implement until the user confirms details.

Planned design:

- Add `current_protect.h/.c`.
- Intended ADC input: PB0 / ADC1_IN8, but current generated ADC config still uses internal temperature sensor.
- Need user confirmation before `.ioc` ADC change.
- Proposed thresholds:
  - trip at 16 A
  - release at 14 A
- Proposed macros:

```c
#define APP_CURRENT_PROTECT_TRIP_MA       16000U
#define APP_CURRENT_PROTECT_RELEASE_MA    14000U
#define APP_CURRENT_SENSE_SHUNT_UOHM      500U
#define APP_CURRENT_SENSE_GAIN            50U
#define APP_CURRENT_ADC_VREF_MV           3300U
#define APP_CURRENT_ADC_MAX_COUNTS        4095U
```

Electrical estimate:

- Shunt: 0.5 mOhm.
- Gain: 50x.
- Output = 25 mV/A.
- 16 A -> 400 mV -> about 496 ADC counts at 3.3 V / 12-bit.
- 14 A -> 350 mV -> about 434 ADC counts.

Protection behavior to confirm:

- On fault: call `WhitePwm_Off()`.
- On fault: stop or suppress WS2812 output, preferably force GPIO lanes low and disable the test pattern while fault remains active.
- Fault auto-clears only after filtered current is below release threshold.
- Expose debug globals:
  - `current_protect_watch_adc_raw`
  - `current_protect_watch_current_ma`
  - `current_protect_watch_fault`
  - `current_protect_watch_trip_count`

## Suggested Commit Message For Current Source State

```text
add ws2812 bsrr driver, rc input, and white pwm control

- add TIM4/DMA GPIOA BSRR WS2812 test driver
- add RC_D0-D3 input state/debounce module
- add TIM1 CH1/CH2 WW/CW white PWM control with smoothing
- hook modules through main USER CODE sections
- set TIM1 PWM target to 20 kHz in ioc
```