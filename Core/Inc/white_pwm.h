#ifndef WHITE_PWM_H
#define WHITE_PWM_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* Start TIM1 CH1/CH2 PWM outputs at 0 duty. */
void WhitePwm_Init(void);
/* Smooth current duty levels toward their targets. */
void WhitePwm_Poll(uint32_t now_ms);
/* Set warm-white target level, range 0..APP_WHITE_PWM_MAX_LEVEL. */
void WhitePwm_SetWW(uint16_t level);
/* Set cold-white target level, range 0..APP_WHITE_PWM_MAX_LEVEL. */
void WhitePwm_SetCW(uint16_t level);
/* Set both white target levels at the same time. */
void WhitePwm_SetBoth(uint16_t ww, uint16_t cw);
/* Return the current smoothed warm-white level. */
uint16_t WhitePwm_GetWW(void);
/* Return the current smoothed cold-white level. */
uint16_t WhitePwm_GetCW(void);
/* Immediately force both white PWM channels to 0 duty. */
void WhitePwm_Off(void);

/* Watch variables for debugger inspection. */
extern volatile uint16_t white_pwm_watch_ww_target;
extern volatile uint16_t white_pwm_watch_cw_target;
extern volatile uint16_t white_pwm_watch_ww_current;
extern volatile uint16_t white_pwm_watch_cw_current;

#ifdef __cplusplus
}
#endif

#endif /* WHITE_PWM_H */
