#include "current_protect.h"

#include "main.h"
#include "adc.h"
#include "app_config.h"
#include "white_pwm.h"

extern ADC_HandleTypeDef hadc1;

/* Debug watch values expose the latest protection state. */
volatile uint16_t current_protect_watch_adc_raw;
volatile uint32_t current_protect_watch_current_ma;
volatile uint8_t current_protect_watch_fault;
volatile uint32_t current_protect_watch_trip_count;

static uint16_t current_protect_adc_raw;
static uint32_t current_protect_current_ma;
static uint32_t current_protect_filtered_adc_q4;
static uint32_t current_protect_last_sample_ms;
static uint32_t current_protect_trip_count;
static uint8_t current_protect_fault;
static uint8_t current_protect_filter_seeded;

static void CurrentProtect_ConfigAdcChannel(void);
static uint8_t CurrentProtect_ReadAdc(uint16_t *raw);
static void CurrentProtect_UpdateFilter(uint16_t raw);
static uint32_t CurrentProtect_AdcToCurrentMa(uint16_t raw);
static void CurrentProtect_UpdateFault(void);
static void CurrentProtect_UpdateWatch(void);

void CurrentProtect_Init(void)
{
  /* Start with no fault latched and a clean filter state. */
  current_protect_adc_raw = 0U;
  current_protect_current_ma = 0U;
  current_protect_filtered_adc_q4 = 0U;
  current_protect_last_sample_ms = 0U;
  current_protect_trip_count = 0U;
  current_protect_fault = 0U;
  current_protect_filter_seeded = 0U;

  CurrentProtect_ConfigAdcChannel();
  (void)HAL_ADCEx_Calibration_Start(&hadc1);
  CurrentProtect_UpdateWatch();
}

void CurrentProtect_Poll(uint32_t now_ms)
{
  uint16_t raw;

  /* Keep white outputs forced off for the entire active fault window. */
  if (current_protect_fault != 0U)
  {
    WhitePwm_Off();
  }

  if ((now_ms - current_protect_last_sample_ms) < APP_CURRENT_PROTECT_SAMPLE_MS)
  {
    return;
  }
  current_protect_last_sample_ms = now_ms;

  if (CurrentProtect_ReadAdc(&raw) == 0U)
  {
    CurrentProtect_UpdateWatch();
    return;
  }

  current_protect_adc_raw = raw;
  CurrentProtect_UpdateFilter(raw);
  current_protect_current_ma = CurrentProtect_AdcToCurrentMa((uint16_t)(current_protect_filtered_adc_q4 >> 4U));
  CurrentProtect_UpdateFault();
  CurrentProtect_UpdateWatch();
}

uint8_t CurrentProtect_IsFaultActive(void)
{
  return current_protect_fault;
}

uint16_t CurrentProtect_GetAdcRaw(void)
{
  return current_protect_adc_raw;
}

uint32_t CurrentProtect_GetCurrentMa(void)
{
  return current_protect_current_ma;
}

static void CurrentProtect_ConfigAdcChannel(void)
{
  /* Reapply the expected PB0/ADC1_IN8 channel in case generated code changes. */
  ADC_ChannelConfTypeDef sConfig = {0};

  sConfig.Channel = ADC_CHANNEL_8;
  sConfig.Rank = ADC_REGULAR_RANK_1;
  sConfig.SamplingTime = ADC_SAMPLETIME_55CYCLES_5;
  (void)HAL_ADC_ConfigChannel(&hadc1, &sConfig);
}

static uint8_t CurrentProtect_ReadAdc(uint16_t *raw)
{
  /* Single software-triggered conversion; no DMA is used for protection ADC. */
  if (HAL_ADC_Start(&hadc1) != HAL_OK)
  {
    return 0U;
  }

  if (HAL_ADC_PollForConversion(&hadc1, APP_CURRENT_ADC_TIMEOUT_MS) != HAL_OK)
  {
    (void)HAL_ADC_Stop(&hadc1);
    return 0U;
  }

  *raw = (uint16_t)HAL_ADC_GetValue(&hadc1);
  (void)HAL_ADC_Stop(&hadc1);
  return 1U;
}

static void CurrentProtect_UpdateFilter(uint16_t raw)
{
  int32_t delta;

  /* First sample seeds the IIR filter to avoid a slow startup ramp. */
  if (current_protect_filter_seeded == 0U)
  {
    current_protect_filtered_adc_q4 = (uint32_t)raw << 4U;
    current_protect_filter_seeded = 1U;
    return;
  }

  delta = ((int32_t)raw << 4U) - (int32_t)current_protect_filtered_adc_q4;
  current_protect_filtered_adc_q4 = (uint32_t)((int32_t)current_protect_filtered_adc_q4 +
                                              (delta / (int32_t)(1U << APP_CURRENT_FILTER_SHIFT)));
}

static uint32_t CurrentProtect_AdcToCurrentMa(uint16_t raw)
{
  /* I_mA = ADC * Vref_mV * 1e6 / (ADCmax * gain * shunt_uohm). */
  uint64_t numerator = (uint64_t)raw * APP_CURRENT_ADC_VREF_MV * 1000000ULL;
  uint64_t denominator = (uint64_t)APP_CURRENT_ADC_MAX_COUNTS *
                         APP_CURRENT_SENSE_GAIN *
                         APP_CURRENT_SENSE_SHUNT_UOHM;

  if (denominator == 0ULL)
  {
    return 0U;
  }

  return (uint32_t)((numerator + (denominator / 2ULL)) / denominator);
}

static void CurrentProtect_UpdateFault(void)
{
  /* Hysteresis prevents chatter around the current limit. */
  if (current_protect_fault == 0U)
  {
    if (current_protect_current_ma >= APP_CURRENT_PROTECT_TRIP_MA)
    {
      current_protect_fault = 1U;
      current_protect_trip_count++;
      WhitePwm_Off();
    }
  }
  else
  {
    WhitePwm_Off();
    if (current_protect_current_ma <= APP_CURRENT_PROTECT_RELEASE_MA)
    {
      current_protect_fault = 0U;
    }
  }
}

static void CurrentProtect_UpdateWatch(void)
{
  current_protect_watch_adc_raw = current_protect_adc_raw;
  current_protect_watch_current_ma = current_protect_current_ma;
  current_protect_watch_fault = current_protect_fault;
  current_protect_watch_trip_count = current_protect_trip_count;
}
