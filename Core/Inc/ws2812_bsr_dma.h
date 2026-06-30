#ifndef WS2812_BSR_DMA_H
#define WS2812_BSR_DMA_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

#define WS2812_BSR_LANES          8U
#define WS2812_BSR_LEDS_PER_LANE  96U

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
