#ifndef APP_CONFIG_H
#define APP_CONFIG_H

/* RC input validation settings. */
#define APP_RC_ACTIVE_HIGH          1U
#define APP_RC_PULL_MODE            GPIO_PULLDOWN
#define APP_RC_DEBOUNCE_MS          5U
#define APP_TEST_RC_STATUS_ENABLE   1U

/* White LED PWM scaling and smoothing settings. */
#define APP_WHITE_PWM_MAX_LEVEL      1000U
#define APP_WHITE_PWM_STEP_MS        2U
#define APP_WHITE_PWM_STEP           5U
#define APP_WHITE_PWM_TIM1_PSC       0U
#define APP_WHITE_PWM_TIM1_ARR       3599U
#define APP_TEST_WHITE_PWM_ENABLE    1U

/* Current protection sampling, conversion, and hysteresis settings. */
#define APP_CURRENT_PROTECT_SAMPLE_MS     5U
#define APP_CURRENT_PROTECT_TRIP_MA       16000U
#define APP_CURRENT_PROTECT_RELEASE_MA    14000U
#define APP_CURRENT_SENSE_SHUNT_UOHM      500U
#define APP_CURRENT_SENSE_GAIN            50U
#define APP_CURRENT_ADC_VREF_MV           3300U
#define APP_CURRENT_ADC_MAX_COUNTS        4095U
#define APP_CURRENT_ADC_TIMEOUT_MS        2U
#define APP_CURRENT_FILTER_SHIFT          3U

#endif /* APP_CONFIG_H */
