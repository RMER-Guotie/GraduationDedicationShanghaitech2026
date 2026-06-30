#include "white_pwm.h"

#include "tim.h"
#include "app_config.h"

extern TIM_HandleTypeDef htim1;

#define WHITE_PWM_WW_TIM_CHANNEL  TIM_CHANNEL_1
#define WHITE_PWM_CW_TIM_CHANNEL  TIM_CHANNEL_2

/* Debug watch values mirror the internal target/current levels. */
volatile uint16_t white_pwm_watch_ww_target;
volatile uint16_t white_pwm_watch_cw_target;
volatile uint16_t white_pwm_watch_ww_current;
volatile uint16_t white_pwm_watch_cw_current;

static uint16_t white_pwm_ww_target;
static uint16_t white_pwm_cw_target;
static uint16_t white_pwm_ww_current;
static uint16_t white_pwm_cw_current;
static uint32_t white_pwm_last_step_ms;

static uint16_t WhitePwm_ClampLevel(uint16_t level);
static uint8_t WhitePwm_Approach(uint16_t *current, uint16_t target);
static void WhitePwm_ApplyChannel(uint32_t channel, uint16_t level);
static void WhitePwm_UpdateWatch(void);

void WhitePwm_Init(void)
{
  /* Keep both channels off before enabling TIM1 PWM outputs. */
  white_pwm_ww_target = 0U;
  white_pwm_cw_target = 0U;
  white_pwm_ww_current = 0U;
  white_pwm_cw_current = 0U;
  white_pwm_last_step_ms = 0U;

  WhitePwm_ApplyChannel(WHITE_PWM_WW_TIM_CHANNEL, 0U);
  WhitePwm_ApplyChannel(WHITE_PWM_CW_TIM_CHANNEL, 0U);
  (void)HAL_TIM_PWM_Start(&htim1, WHITE_PWM_WW_TIM_CHANNEL);
  (void)HAL_TIM_PWM_Start(&htim1, WHITE_PWM_CW_TIM_CHANNEL);
  WhitePwm_UpdateWatch();
}

void WhitePwm_Poll(uint32_t now_ms)
{
  uint8_t changed = 0U;

  /* Smoothing is time-sliced so callers can poll from the main loop. */
  if ((now_ms - white_pwm_last_step_ms) < APP_WHITE_PWM_STEP_MS)
  {
    return;
  }

  white_pwm_last_step_ms = now_ms;
  changed |= WhitePwm_Approach(&white_pwm_ww_current, white_pwm_ww_target);
  changed |= WhitePwm_Approach(&white_pwm_cw_current, white_pwm_cw_target);

  if (changed != 0U)
  {
    WhitePwm_ApplyChannel(WHITE_PWM_WW_TIM_CHANNEL, white_pwm_ww_current);
    WhitePwm_ApplyChannel(WHITE_PWM_CW_TIM_CHANNEL, white_pwm_cw_current);
    WhitePwm_UpdateWatch();
  }
}

void WhitePwm_SetWW(uint16_t level)
{
  white_pwm_ww_target = WhitePwm_ClampLevel(level);
  WhitePwm_UpdateWatch();
}

void WhitePwm_SetCW(uint16_t level)
{
  white_pwm_cw_target = WhitePwm_ClampLevel(level);
  WhitePwm_UpdateWatch();
}

void WhitePwm_SetBoth(uint16_t ww, uint16_t cw)
{
  white_pwm_ww_target = WhitePwm_ClampLevel(ww);
  white_pwm_cw_target = WhitePwm_ClampLevel(cw);
  WhitePwm_UpdateWatch();
}

uint16_t WhitePwm_GetWW(void)
{
  return white_pwm_ww_current;
}

uint16_t WhitePwm_GetCW(void)
{
  return white_pwm_cw_current;
}

void WhitePwm_Off(void)
{
  /* Fault shutdown bypasses smoothing and writes 0 duty immediately. */
  white_pwm_ww_target = 0U;
  white_pwm_cw_target = 0U;
  white_pwm_ww_current = 0U;
  white_pwm_cw_current = 0U;
  WhitePwm_ApplyChannel(WHITE_PWM_WW_TIM_CHANNEL, 0U);
  WhitePwm_ApplyChannel(WHITE_PWM_CW_TIM_CHANNEL, 0U);
  WhitePwm_UpdateWatch();
}

static uint16_t WhitePwm_ClampLevel(uint16_t level)
{
  return (level > APP_WHITE_PWM_MAX_LEVEL) ? APP_WHITE_PWM_MAX_LEVEL : level;
}

static uint8_t WhitePwm_Approach(uint16_t *current, uint16_t target)
{
  uint16_t next;

  /* Move one channel by a fixed step without overshooting the target. */
  if (*current == target)
  {
    return 0U;
  }

  if (*current < target)
  {
    next = (uint16_t)(*current + APP_WHITE_PWM_STEP);
    *current = (next > target) ? target : next;
  }
  else
  {
    if ((*current - target) <= APP_WHITE_PWM_STEP)
    {
      *current = target;
    }
    else
    {
      *current = (uint16_t)(*current - APP_WHITE_PWM_STEP);
    }
  }

  return 1U;
}

static void WhitePwm_ApplyChannel(uint32_t channel, uint16_t level)
{
  /* Convert the public 0..1000 level to TIM1 compare counts. */
  uint32_t period_counts = (uint32_t)__HAL_TIM_GET_AUTORELOAD(&htim1) + 1U;
  uint32_t pulse = ((period_counts * (uint32_t)level) + (APP_WHITE_PWM_MAX_LEVEL / 2U)) /
                   APP_WHITE_PWM_MAX_LEVEL;

  if (pulse > 0xFFFFU)
  {
    pulse = 0xFFFFU;
  }

  __HAL_TIM_SET_COMPARE(&htim1, channel, pulse);
}

static void WhitePwm_UpdateWatch(void)
{
  white_pwm_watch_ww_target = white_pwm_ww_target;
  white_pwm_watch_cw_target = white_pwm_cw_target;
  white_pwm_watch_ww_current = white_pwm_ww_current;
  white_pwm_watch_cw_current = white_pwm_cw_current;
}
