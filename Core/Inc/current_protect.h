#ifndef CURRENT_PROTECT_H
#define CURRENT_PROTECT_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* Configure ADC1 current sampling and reset protection state. */
void CurrentProtect_Init(void);
/* Sample/filter current and update the latched fault state. */
void CurrentProtect_Poll(uint32_t now_ms);
/* Return nonzero while overcurrent protection is active. */
uint8_t CurrentProtect_IsFaultActive(void);
/* Return the latest raw ADC sample. */
uint16_t CurrentProtect_GetAdcRaw(void);
/* Return the filtered current estimate in milliamps. */
uint32_t CurrentProtect_GetCurrentMa(void);

/* Watch variables for debugger inspection. */
extern volatile uint16_t current_protect_watch_adc_raw;
extern volatile uint32_t current_protect_watch_current_ma;
extern volatile uint8_t current_protect_watch_fault;
extern volatile uint32_t current_protect_watch_trip_count;

#ifdef __cplusplus
}
#endif

#endif /* CURRENT_PROTECT_H */
