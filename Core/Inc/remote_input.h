#ifndef REMOTE_INPUT_H
#define REMOTE_INPUT_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

#define REMOTE_INPUT_CHANNEL_COUNT  4U
#define REMOTE_INPUT_D0_BIT         0x01U
#define REMOTE_INPUT_D1_BIT         0x02U
#define REMOTE_INPUT_D2_BIT         0x04U
#define REMOTE_INPUT_D3_BIT         0x08U

/* Configure RC_D0..RC_D3 as EXTI-backed debounced GPIO inputs. */
void RemoteInput_Init(void);
/* Poll and debounce the 4-bit RC input state. */
void RemoteInput_Poll(uint32_t now_ms);
/* Return the latest direct pin sample. */
uint8_t RemoteInput_GetRawBits(void);
/* Return the debounced 4-bit state. */
uint8_t RemoteInput_GetStableBits(void);
/* Return and clear debounced change flags. */
uint8_t RemoteInput_ConsumeChangedBits(void);
/* Return and clear debounced press event flags. */
uint8_t RemoteInput_ConsumePressedBits(void);
/* Return the raw EXTI edge count for one channel. */
uint32_t RemoteInput_GetEdgeCount(uint8_t channel);

/* Watch variables for debugger inspection. */
extern volatile uint8_t remote_input_watch_raw_bits;
extern volatile uint8_t remote_input_watch_stable_bits;
extern volatile uint8_t remote_input_watch_changed_bits;
extern volatile uint8_t remote_input_watch_pressed_bits;
extern volatile uint32_t remote_input_watch_edge_count[REMOTE_INPUT_CHANNEL_COUNT];

#ifdef __cplusplus
}
#endif

#endif /* REMOTE_INPUT_H */
