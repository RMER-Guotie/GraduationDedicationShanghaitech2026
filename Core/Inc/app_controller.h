#ifndef APP_CONTROLLER_H
#define APP_CONTROLLER_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* Initialize all application-level modules after CubeMX peripheral setup. */
void AppController_Init(void);
/* Run one cooperative scheduler tick from the main loop. */
void AppController_Poll(uint32_t now_ms);

/* Watch variables for debugger inspection. */
extern volatile uint32_t app_controller_watch_loop_count;
extern volatile uint8_t app_controller_watch_fault_active;
extern volatile uint8_t app_controller_watch_rc_stable_bits;

#ifdef __cplusplus
}
#endif

#endif /* APP_CONTROLLER_H */
