#ifndef WHITE_PWM_H
#define WHITE_PWM_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

void WhitePwm_Init(void);
void WhitePwm_Poll(uint32_t now_ms);
void WhitePwm_SetWW(uint16_t level);
void WhitePwm_SetCW(uint16_t level);
void WhitePwm_SetBoth(uint16_t ww, uint16_t cw);
uint16_t WhitePwm_GetWW(void);
uint16_t WhitePwm_GetCW(void);
void WhitePwm_Off(void);

extern volatile uint16_t white_pwm_watch_ww_target;
extern volatile uint16_t white_pwm_watch_cw_target;
extern volatile uint16_t white_pwm_watch_ww_current;
extern volatile uint16_t white_pwm_watch_cw_current;

#ifdef __cplusplus
}
#endif

#endif /* WHITE_PWM_H */
