#include "remote_input.h"

#include "main.h"
#include "app_config.h"

#define REMOTE_INPUT_VALID_MASK  0x0FU

/* Physical RC input map: bit0..bit3 are PB11, PB10, PB2, PB1. */
typedef struct
{
  GPIO_TypeDef *port;
  uint16_t pin;
  uint8_t bit;
} RemoteInput_PinMap_t;

static const RemoteInput_PinMap_t remote_input_pin_map[REMOTE_INPUT_CHANNEL_COUNT] =
{
  {RC_D0_GPIO_Port, RC_D0_Pin, REMOTE_INPUT_D0_BIT},
  {RC_D1_GPIO_Port, RC_D1_Pin, REMOTE_INPUT_D1_BIT},
  {RC_D2_GPIO_Port, RC_D2_Pin, REMOTE_INPUT_D2_BIT},
  {RC_D3_GPIO_Port, RC_D3_Pin, REMOTE_INPUT_D3_BIT}
};

volatile uint8_t remote_input_watch_raw_bits;
volatile uint8_t remote_input_watch_stable_bits;
volatile uint8_t remote_input_watch_changed_bits;
volatile uint32_t remote_input_watch_edge_count[REMOTE_INPUT_CHANNEL_COUNT];

static volatile uint8_t remote_input_raw_bits;
static uint8_t remote_input_candidate_bits;
static uint8_t remote_input_stable_bits;
static uint8_t remote_input_changed_bits;
static uint32_t remote_input_candidate_since_ms;
static volatile uint32_t remote_input_edge_count[REMOTE_INPUT_CHANNEL_COUNT];

static uint8_t RemoteInput_SamplePins(void);
static void RemoteInput_HandleExti(uint16_t gpio_pin);
static void RemoteInput_UpdateWatch(void);

void RemoteInput_Init(void)
{
  /* Runtime EXTI setup keeps RC input behavior robust after CubeMX regeneration. */
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  uint32_t channel;

  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_AFIO_CLK_ENABLE();

  GPIO_InitStruct.Pin = RC_D0_Pin | RC_D1_Pin | RC_D2_Pin | RC_D3_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING_FALLING;
  GPIO_InitStruct.Pull = APP_RC_PULL_MODE;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  HAL_NVIC_ClearPendingIRQ(EXTI1_IRQn);
  HAL_NVIC_ClearPendingIRQ(EXTI2_IRQn);
  HAL_NVIC_ClearPendingIRQ(EXTI15_10_IRQn);
  HAL_NVIC_SetPriority(EXTI1_IRQn, 3, 0);
  HAL_NVIC_SetPriority(EXTI2_IRQn, 3, 0);
  HAL_NVIC_SetPriority(EXTI15_10_IRQn, 3, 0);
  HAL_NVIC_EnableIRQ(EXTI1_IRQn);
  HAL_NVIC_EnableIRQ(EXTI2_IRQn);
  HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);

  remote_input_raw_bits = RemoteInput_SamplePins();
  remote_input_candidate_bits = remote_input_raw_bits;
  remote_input_stable_bits = remote_input_raw_bits;
  remote_input_changed_bits = 0U;
  remote_input_candidate_since_ms = HAL_GetTick();

  for (channel = 0U; channel < REMOTE_INPUT_CHANNEL_COUNT; channel++)
  {
    remote_input_edge_count[channel] = 0U;
  }

  RemoteInput_UpdateWatch();
}

void RemoteInput_Poll(uint32_t now_ms)
{
  uint8_t raw_bits;
  uint8_t changed_bits;

  /* Debounce the latest EXTI-updated raw state before publishing it. */
  raw_bits = remote_input_raw_bits;

  if (raw_bits != remote_input_candidate_bits)
  {
    remote_input_candidate_bits = raw_bits;
    remote_input_candidate_since_ms = now_ms;
    RemoteInput_UpdateWatch();
    return;
  }

  if (raw_bits == remote_input_stable_bits)
  {
    RemoteInput_UpdateWatch();
    return;
  }

  if ((now_ms - remote_input_candidate_since_ms) < APP_RC_DEBOUNCE_MS)
  {
    RemoteInput_UpdateWatch();
    return;
  }

  changed_bits = (uint8_t)((remote_input_stable_bits ^ raw_bits) & REMOTE_INPUT_VALID_MASK);
  remote_input_stable_bits = raw_bits;
  remote_input_changed_bits = (uint8_t)((remote_input_changed_bits | changed_bits) & REMOTE_INPUT_VALID_MASK);

  RemoteInput_UpdateWatch();
}

uint8_t RemoteInput_GetRawBits(void)
{
  return remote_input_raw_bits;
}

uint8_t RemoteInput_GetStableBits(void)
{
  return remote_input_stable_bits;
}

uint8_t RemoteInput_ConsumeChangedBits(void)
{
  /* Change flags are edge-like events consumed by higher-level logic. */
  uint8_t changed_bits = remote_input_changed_bits;

  remote_input_changed_bits = 0U;
  RemoteInput_UpdateWatch();

  return changed_bits;
}

uint32_t RemoteInput_GetEdgeCount(uint8_t channel)
{
  if (channel >= REMOTE_INPUT_CHANNEL_COUNT)
  {
    return 0U;
  }

  return remote_input_edge_count[channel];
}

static uint8_t RemoteInput_SamplePins(void)
{
  /* Convert GPIO pin states into the active-high logical bit mask. */
  uint8_t bits = 0U;
  uint32_t channel;

  for (channel = 0U; channel < REMOTE_INPUT_CHANNEL_COUNT; channel++)
  {
    GPIO_PinState pin_state = HAL_GPIO_ReadPin(remote_input_pin_map[channel].port,
                                               remote_input_pin_map[channel].pin);
#if (APP_RC_ACTIVE_HIGH != 0U)
    if (pin_state == GPIO_PIN_SET)
#else
    if (pin_state == GPIO_PIN_RESET)
#endif
    {
      bits = (uint8_t)(bits | remote_input_pin_map[channel].bit);
    }
  }

  return (uint8_t)(bits & REMOTE_INPUT_VALID_MASK);
}

static void RemoteInput_HandleExti(uint16_t gpio_pin)
{
  uint8_t previous_bits;
  uint8_t raw_bits;
  uint8_t changed_bits;
  uint32_t channel;

  if ((gpio_pin & (RC_D0_Pin | RC_D1_Pin | RC_D2_Pin | RC_D3_Pin)) == 0U)
  {
    return;
  }

  previous_bits = remote_input_raw_bits;
  raw_bits = RemoteInput_SamplePins();
  changed_bits = (uint8_t)((previous_bits ^ raw_bits) & REMOTE_INPUT_VALID_MASK);
  remote_input_raw_bits = raw_bits;

  for (channel = 0U; channel < REMOTE_INPUT_CHANNEL_COUNT; channel++)
  {
    if ((changed_bits & (uint8_t)(1U << channel)) != 0U)
    {
      remote_input_edge_count[channel]++;
    }
  }
}

void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
  RemoteInput_HandleExti(GPIO_Pin);
}

static void RemoteInput_UpdateWatch(void)
{
  uint32_t channel;

  remote_input_watch_raw_bits = remote_input_raw_bits;
  remote_input_watch_stable_bits = remote_input_stable_bits;
  remote_input_watch_changed_bits = remote_input_changed_bits;

  for (channel = 0U; channel < REMOTE_INPUT_CHANNEL_COUNT; channel++)
  {
    remote_input_watch_edge_count[channel] = remote_input_edge_count[channel];
  }
}
