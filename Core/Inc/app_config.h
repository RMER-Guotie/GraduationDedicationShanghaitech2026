#ifndef APP_CONFIG_H
#define APP_CONFIG_H

/* Central application switches for board-level validation. */
#define APP_RC_ACTIVE_HIGH          1U
#define APP_RC_PULL_MODE            GPIO_PULLDOWN
#define APP_RC_DEBOUNCE_MS          5U
#define APP_TEST_RC_STATUS_ENABLE   1U

#define APP_WHITE_PWM_MAX_LEVEL      1000U
#define APP_WHITE_PWM_STEP_MS        2U
#define APP_WHITE_PWM_STEP           5U
#define APP_WHITE_PWM_TIM1_PSC       0U
#define APP_WHITE_PWM_TIM1_ARR       3599U
#define APP_TEST_WHITE_PWM_ENABLE    1U

#endif /* APP_CONFIG_H */
