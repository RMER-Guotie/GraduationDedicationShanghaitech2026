#ifndef WS2812_BSR_DMA_H
#define WS2812_BSR_DMA_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

#define WS2812_BSR_LANES          8U
#define WS2812_BSR_LEDS_PER_LANE  96U

/* Configure GPIOA lanes, TIM4 timing, DMA channels, and IRQ. */
void WS2812_BSR_Init(void);
/* Clear the software frame buffer to black. */
void WS2812_BSR_Clear(void);
/* Fill every lane and pixel with one RGB color. */
void WS2812_BSR_FillAll(uint8_t r, uint8_t g, uint8_t b);
/* Fill one lane with one RGB color. */
void WS2812_BSR_FillLane(uint8_t lane, uint8_t r, uint8_t g, uint8_t b);
/* Set one RGB pixel in the software frame buffer. */
void WS2812_BSR_SetPixel(uint8_t lane, uint16_t index, uint8_t r, uint8_t g, uint8_t b);
/* Start a nonblocking TIM4/DMA WS2812 transfer. */
void WS2812_BSR_Show(void);
/* Abort any transfer, force GPIO lanes low, and clear the frame buffer. */
void WS2812_BSR_ForceBlack(void);
/* Advance DMA completion, error, timeout, and reset-latch handling. */
void WS2812_BSR_Poll(void);
/* Block until the current WS2812 transfer and reset latch finish. */
void WS2812_BSR_Wait(void);
/* Return nonzero while a WS2812 transfer or reset latch is active. */
uint8_t WS2812_BSR_IsBusy(void);
/* Generate the built-in rainbow/breathing validation pattern. */
void WS2812_BSR_TestPatternStep(uint32_t now_ms);

/* Diagnostic counters for debugger inspection. */
extern volatile uint32_t ws2812_bsr_diag_show_count;
extern volatile uint32_t ws2812_bsr_diag_complete_count;
extern volatile uint32_t ws2812_bsr_diag_error_count;
extern volatile uint32_t ws2812_bsr_diag_timeout_count;
extern volatile uint32_t ws2812_bsr_diag_start_error_count;
extern volatile uint32_t ws2812_bsr_diag_poll_complete_count;
extern volatile uint32_t ws2812_show_count_watch;
extern volatile uint32_t ws2812_complete_count_watch;

#ifdef __cplusplus
}
#endif

#endif /* WS2812_BSR_DMA_H */
