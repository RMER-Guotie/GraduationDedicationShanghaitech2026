#include "ws2812_bsr_dma.h"

#include "main.h"
#include "tim.h"

#define WS2812_BSR_BITS_PER_LED        24U
#define WS2812_BSR_BIT_WORDS           (WS2812_BSR_LEDS_PER_LANE * WS2812_BSR_BITS_PER_LED)
#define WS2812_BSR_RESET_MS            1U
#define WS2812_BSR_SHOW_TIMEOUT_MS     20U
#define WS2812_BSR_TEST_STEP_MS        10U
#define WS2812_BSR_TEST_HUE_STEP       2U
#define WS2812_BSR_TEST_PIXEL_HUE_STEP 3U

#define WS2812_BSR_TIMER_PERIOD        89U
#define WS2812_BSR_ZERO_COMPARE        29U
#define WS2812_BSR_ONE_COMPARE         58U

#define WS2812_BSR_SET(mask)           ((uint32_t)(mask))
#define WS2812_BSR_RESET(mask)         ((uint32_t)(mask) << 16U)
#define WS2812_BSR_ACTIVE_MASK         ((uint16_t)(CH1_Pin | CH2_Pin | CH3_Pin | CH4_Pin | \
                                                   CH5_Pin | CH6_Pin | CH7_Pin | CH8_Pin))

typedef struct
{
  uint8_t r;
  uint8_t g;
  uint8_t b;
} WS2812_BSR_RGB888_t;

extern TIM_HandleTypeDef htim4;

static const uint16_t ws2812_lane_pin_mask[WS2812_BSR_LANES] =
{
  CH1_Pin,
  CH2_Pin,
  CH3_Pin,
  CH4_Pin,
  CH5_Pin,
  CH6_Pin,
  CH7_Pin,
  CH8_Pin
};

static WS2812_BSR_RGB888_t ws2812_frame[WS2812_BSR_LANES][WS2812_BSR_LEDS_PER_LANE];
static uint32_t ws2812_zero_reset_buffer[WS2812_BSR_BIT_WORDS];
static uint32_t ws2812_set_all_word;
static uint32_t ws2812_reset_all_word;

static DMA_HandleTypeDef ws2812_hdma_tim4_up;
static DMA_HandleTypeDef ws2812_hdma_tim4_cc1;
static DMA_HandleTypeDef ws2812_hdma_tim4_cc2;

volatile uint32_t ws2812_bsr_diag_show_count;
volatile uint32_t ws2812_bsr_diag_complete_count;
volatile uint32_t ws2812_bsr_diag_error_count;
volatile uint32_t ws2812_bsr_diag_timeout_count;
volatile uint32_t ws2812_bsr_diag_start_error_count;
volatile uint32_t ws2812_bsr_diag_poll_complete_count;
volatile uint32_t ws2812_show_count_watch;
volatile uint32_t ws2812_complete_count_watch;

static volatile uint8_t ws2812_initialized;
static volatile uint8_t ws2812_busy;
static volatile uint8_t ws2812_dma_done;
static volatile uint32_t ws2812_latch_start_tick;
static uint32_t ws2812_show_start_tick;
static uint32_t ws2812_test_last_show_ms;
static uint8_t ws2812_test_base_hue;
static uint8_t ws2812_test_breath;
static uint8_t ws2812_test_breath_up = 1U;

static void WS2812_BSR_InitGpio(void);
static HAL_StatusTypeDef WS2812_BSR_InitDmaHandle(DMA_HandleTypeDef *hdma, DMA_Channel_TypeDef *channel, uint32_t mem_inc);
static void WS2812_BSR_EncodeByte(uint32_t **zero_dst, const uint8_t lane_byte[WS2812_BSR_LANES]);
static void WS2812_BSR_EncodeFrame(void);
static void WS2812_BSR_StopTimerDma(void);
static void WS2812_BSR_ApplyTiming(void);
static uint8_t WS2812_BSR_ResetTimeElapsed(void);
static uint8_t WS2812_BSR_DmaTransferComplete(DMA_HandleTypeDef *hdma);
static uint8_t WS2812_BSR_DmaTransferError(DMA_HandleTypeDef *hdma);
static void WS2812_BSR_ReleaseDmaHandle(DMA_HandleTypeDef *hdma);
static void WS2812_BSR_DmaCompleteCallback(DMA_HandleTypeDef *hdma);
static void WS2812_BSR_DmaErrorCallback(DMA_HandleTypeDef *hdma);
static void WS2812_BSR_CleanupCompletedDma(void);
static void WS2812_BSR_AbortDma(void);
static void WS2812_BSR_MarkDmaDone(void);
static void WS2812_BSR_DemoColorWheel(uint8_t hue, uint8_t brightness, uint8_t *r, uint8_t *g, uint8_t *b);

void WS2812_BSR_Init(void)
{
  __HAL_RCC_DMA1_CLK_ENABLE();

  ws2812_set_all_word = WS2812_BSR_SET(WS2812_BSR_ACTIVE_MASK);
  ws2812_reset_all_word = WS2812_BSR_RESET(WS2812_BSR_ACTIVE_MASK);

  WS2812_BSR_InitGpio();
  WS2812_BSR_Clear();

  if (WS2812_BSR_InitDmaHandle(&ws2812_hdma_tim4_up, DMA1_Channel7, DMA_MINC_DISABLE) != HAL_OK)
  {
    return;
  }

  if (WS2812_BSR_InitDmaHandle(&ws2812_hdma_tim4_cc1, DMA1_Channel1, DMA_MINC_ENABLE) != HAL_OK)
  {
    return;
  }

  if (WS2812_BSR_InitDmaHandle(&ws2812_hdma_tim4_cc2, DMA1_Channel4, DMA_MINC_DISABLE) != HAL_OK)
  {
    return;
  }

  ws2812_hdma_tim4_cc2.XferCpltCallback = WS2812_BSR_DmaCompleteCallback;
  ws2812_hdma_tim4_cc2.XferErrorCallback = WS2812_BSR_DmaErrorCallback;

  HAL_NVIC_DisableIRQ(DMA1_Channel4_IRQn);
  HAL_NVIC_ClearPendingIRQ(DMA1_Channel4_IRQn);
  HAL_NVIC_SetPriority(DMA1_Channel4_IRQn, 1, 0);
  HAL_NVIC_EnableIRQ(DMA1_Channel4_IRQn);

  WS2812_BSR_StopTimerDma();
  WS2812_BSR_ApplyTiming();
  GPIOA->BSRR = WS2812_BSR_RESET(WS2812_BSR_ACTIVE_MASK);

  ws2812_busy = 0U;
  ws2812_dma_done = 0U;
  ws2812_latch_start_tick = 0U;
  ws2812_show_start_tick = 0U;
  ws2812_initialized = 1U;
}

void WS2812_BSR_Clear(void)
{
  WS2812_BSR_FillAll(0U, 0U, 0U);
}

void WS2812_BSR_FillAll(uint8_t r, uint8_t g, uint8_t b)
{
  uint32_t lane;

  for (lane = 0U; lane < WS2812_BSR_LANES; lane++)
  {
    WS2812_BSR_FillLane((uint8_t)lane, r, g, b);
  }
}

void WS2812_BSR_FillLane(uint8_t lane, uint8_t r, uint8_t g, uint8_t b)
{
  uint32_t index;

  if (lane >= WS2812_BSR_LANES)
  {
    return;
  }

  for (index = 0U; index < WS2812_BSR_LEDS_PER_LANE; index++)
  {
    ws2812_frame[lane][index].r = r;
    ws2812_frame[lane][index].g = g;
    ws2812_frame[lane][index].b = b;
  }
}

void WS2812_BSR_SetPixel(uint8_t lane, uint16_t index, uint8_t r, uint8_t g, uint8_t b)
{
  if ((lane >= WS2812_BSR_LANES) || (index >= WS2812_BSR_LEDS_PER_LANE))
  {
    return;
  }

  ws2812_frame[lane][index].r = r;
  ws2812_frame[lane][index].g = g;
  ws2812_frame[lane][index].b = b;
}
void WS2812_BSR_Show(void)
{
  if ((ws2812_initialized == 0U) || (ws2812_busy != 0U))
  {
    return;
  }

  WS2812_BSR_EncodeFrame();

  ws2812_busy = 1U;
  ws2812_dma_done = 0U;
  ws2812_latch_start_tick = 0U;

  WS2812_BSR_StopTimerDma();
  WS2812_BSR_ApplyTiming();
  GPIOA->BSRR = WS2812_BSR_RESET(WS2812_BSR_ACTIVE_MASK);

  if (HAL_DMA_Start(&ws2812_hdma_tim4_up,
                    (uint32_t)&ws2812_set_all_word,
                    (uint32_t)&GPIOA->BSRR,
                    WS2812_BSR_BIT_WORDS) != HAL_OK)
  {
    ws2812_bsr_diag_start_error_count++;
    WS2812_BSR_AbortDma();
    ws2812_busy = 0U;
    return;
  }

  if (HAL_DMA_Start(&ws2812_hdma_tim4_cc1,
                    (uint32_t)ws2812_zero_reset_buffer,
                    (uint32_t)&GPIOA->BSRR,
                    WS2812_BSR_BIT_WORDS) != HAL_OK)
  {
    ws2812_bsr_diag_start_error_count++;
    WS2812_BSR_AbortDma();
    ws2812_busy = 0U;
    return;
  }

  if (HAL_DMA_Start_IT(&ws2812_hdma_tim4_cc2,
                       (uint32_t)&ws2812_reset_all_word,
                       (uint32_t)&GPIOA->BSRR,
                       WS2812_BSR_BIT_WORDS) != HAL_OK)
  {
    ws2812_bsr_diag_start_error_count++;
    WS2812_BSR_AbortDma();
    ws2812_busy = 0U;
    return;
  }

  ws2812_bsr_diag_show_count++;
  ws2812_show_count_watch = ws2812_bsr_diag_show_count;
  ws2812_show_start_tick = HAL_GetTick();

  __HAL_TIM_SET_COUNTER(&htim4, WS2812_BSR_TIMER_PERIOD);
  __HAL_TIM_CLEAR_FLAG(&htim4, TIM_FLAG_UPDATE | TIM_FLAG_CC1 | TIM_FLAG_CC2);
  __HAL_TIM_ENABLE_DMA(&htim4, TIM_DMA_UPDATE | TIM_DMA_CC1 | TIM_DMA_CC2);
  __HAL_TIM_ENABLE(&htim4);
}

void WS2812_BSR_Poll(void)
{
  if (ws2812_busy == 0U)
  {
    return;
  }

  if (ws2812_dma_done != 0U)
  {
    if (WS2812_BSR_ResetTimeElapsed() != 0U)
    {
      ws2812_busy = 0U;
    }
    return;
  }

  if (WS2812_BSR_DmaTransferError(&ws2812_hdma_tim4_up) != 0U ||
      WS2812_BSR_DmaTransferError(&ws2812_hdma_tim4_cc1) != 0U ||
      WS2812_BSR_DmaTransferError(&ws2812_hdma_tim4_cc2) != 0U)
  {
    ws2812_bsr_diag_error_count++;
    WS2812_BSR_AbortDma();
    WS2812_BSR_MarkDmaDone();
    return;
  }

  if (WS2812_BSR_DmaTransferComplete(&ws2812_hdma_tim4_cc2) != 0U)
  {
    ws2812_bsr_diag_poll_complete_count++;
    ws2812_complete_count_watch = ws2812_bsr_diag_complete_count + ws2812_bsr_diag_poll_complete_count;
    WS2812_BSR_CleanupCompletedDma();
    WS2812_BSR_MarkDmaDone();
    return;
  }

  if ((HAL_GetTick() - ws2812_show_start_tick) > WS2812_BSR_SHOW_TIMEOUT_MS)
  {
    ws2812_bsr_diag_timeout_count++;
    WS2812_BSR_AbortDma();
    WS2812_BSR_MarkDmaDone();
  }
}

void WS2812_BSR_Wait(void)
{
  while (WS2812_BSR_IsBusy() != 0U)
  {
    WS2812_BSR_Poll();
  }
}

uint8_t WS2812_BSR_IsBusy(void)
{
  WS2812_BSR_Poll();
  return ws2812_busy;
}

void WS2812_BSR_TestPatternStep(uint32_t now_ms)
{
  uint8_t brightness;
  uint32_t lane;
  uint32_t index;

  WS2812_BSR_Poll();

  if ((now_ms - ws2812_test_last_show_ms) < WS2812_BSR_TEST_STEP_MS)
  {
    return;
  }

  if (WS2812_BSR_IsBusy() != 0U)
  {
    return;
  }

  ws2812_test_last_show_ms = now_ms;
  brightness = (uint8_t)(6U + (((uint16_t)ws2812_test_breath * 42U) / 255U));

  for (lane = 0U; lane < WS2812_BSR_LANES; lane++)
  {
    for (index = 0U; index < WS2812_BSR_LEDS_PER_LANE; index++)
    {
      uint8_t r;
      uint8_t g;
      uint8_t b;
      uint8_t hue = (uint8_t)(ws2812_test_base_hue +
                              (uint8_t)(lane * 32U) +
                              (uint8_t)(index * WS2812_BSR_TEST_PIXEL_HUE_STEP));

      WS2812_BSR_DemoColorWheel(hue, brightness, &r, &g, &b);
      WS2812_BSR_SetPixel((uint8_t)lane, (uint16_t)index, r, g, b);
    }
  }

  WS2812_BSR_Show();
  ws2812_test_base_hue = (uint8_t)(ws2812_test_base_hue + WS2812_BSR_TEST_HUE_STEP);

  if (ws2812_test_breath_up != 0U)
  {
    if (ws2812_test_breath >= 250U)
    {
      ws2812_test_breath = 255U;
      ws2812_test_breath_up = 0U;
    }
    else
    {
      ws2812_test_breath = (uint8_t)(ws2812_test_breath + 5U);
    }
  }
  else
  {
    if (ws2812_test_breath <= 5U)
    {
      ws2812_test_breath = 0U;
      ws2812_test_breath_up = 1U;
    }
    else
    {
      ws2812_test_breath = (uint8_t)(ws2812_test_breath - 5U);
    }
  }
}

void DMA1_Channel4_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&ws2812_hdma_tim4_cc2);
}
static void WS2812_BSR_InitGpio(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  __HAL_RCC_GPIOA_CLK_ENABLE();

  GPIO_InitStruct.Pin = WS2812_BSR_ACTIVE_MASK;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = 0U;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
}

static HAL_StatusTypeDef WS2812_BSR_InitDmaHandle(DMA_HandleTypeDef *hdma, DMA_Channel_TypeDef *channel, uint32_t mem_inc)
{
  hdma->Instance = channel;
  hdma->Init.Direction = DMA_MEMORY_TO_PERIPH;
  hdma->Init.PeriphInc = DMA_PINC_DISABLE;
  hdma->Init.MemInc = mem_inc;
  hdma->Init.PeriphDataAlignment = DMA_PDATAALIGN_WORD;
  hdma->Init.MemDataAlignment = DMA_MDATAALIGN_WORD;
  hdma->Init.Mode = DMA_NORMAL;
  hdma->Init.Priority = DMA_PRIORITY_VERY_HIGH;
  hdma->XferCpltCallback = 0;
  hdma->XferHalfCpltCallback = 0;
  hdma->XferErrorCallback = 0;
  hdma->XferAbortCallback = 0;

  return HAL_DMA_Init(hdma);
}

static void WS2812_BSR_EncodeByte(uint32_t **zero_dst, const uint8_t lane_byte[WS2812_BSR_LANES])
{
  uint32_t bit;

  for (bit = 0U; bit < 8U; bit++)
  {
    uint8_t bit_mask = (uint8_t)(0x80U >> bit);
    uint16_t one_mask = 0U;
    uint32_t lane;

    for (lane = 0U; lane < WS2812_BSR_LANES; lane++)
    {
      if ((lane_byte[lane] & bit_mask) != 0U)
      {
        one_mask |= ws2812_lane_pin_mask[lane];
      }
    }

    **zero_dst = WS2812_BSR_RESET((uint16_t)(WS2812_BSR_ACTIVE_MASK & (uint16_t)(~one_mask)));
    (*zero_dst)++;
  }
}

static void WS2812_BSR_EncodeFrame(void)
{
  uint32_t pixel;
  uint32_t *zero_dst = ws2812_zero_reset_buffer;

  for (pixel = 0U; pixel < WS2812_BSR_LEDS_PER_LANE; pixel++)
  {
    uint8_t lane_g[WS2812_BSR_LANES];
    uint8_t lane_r[WS2812_BSR_LANES];
    uint8_t lane_b[WS2812_BSR_LANES];
    uint32_t lane;

    for (lane = 0U; lane < WS2812_BSR_LANES; lane++)
    {
      lane_g[lane] = ws2812_frame[lane][pixel].g;
      lane_r[lane] = ws2812_frame[lane][pixel].r;
      lane_b[lane] = ws2812_frame[lane][pixel].b;
    }

    WS2812_BSR_EncodeByte(&zero_dst, lane_g);
    WS2812_BSR_EncodeByte(&zero_dst, lane_r);
    WS2812_BSR_EncodeByte(&zero_dst, lane_b);
  }
}

static void WS2812_BSR_StopTimerDma(void)
{
  __HAL_TIM_DISABLE_DMA(&htim4, TIM_DMA_UPDATE | TIM_DMA_CC1 | TIM_DMA_CC2);
  __HAL_TIM_DISABLE(&htim4);
  __HAL_TIM_CLEAR_FLAG(&htim4, TIM_FLAG_UPDATE | TIM_FLAG_CC1 | TIM_FLAG_CC2);
}

static void WS2812_BSR_ApplyTiming(void)
{
  __HAL_TIM_SET_PRESCALER(&htim4, 0U);
  __HAL_TIM_SET_AUTORELOAD(&htim4, WS2812_BSR_TIMER_PERIOD);
  __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_1, WS2812_BSR_ZERO_COMPARE);
  __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_2, WS2812_BSR_ONE_COMPARE);
  htim4.Instance->EGR = TIM_EGR_UG;
  __HAL_TIM_SET_COUNTER(&htim4, 0U);
  __HAL_TIM_CLEAR_FLAG(&htim4, TIM_FLAG_UPDATE | TIM_FLAG_CC1 | TIM_FLAG_CC2);
}

static uint8_t WS2812_BSR_ResetTimeElapsed(void)
{
  return ((HAL_GetTick() - ws2812_latch_start_tick) >= WS2812_BSR_RESET_MS) ? 1U : 0U;
}

static uint8_t WS2812_BSR_DmaTransferComplete(DMA_HandleTypeDef *hdma)
{
  return (__HAL_DMA_GET_FLAG(hdma, __HAL_DMA_GET_TC_FLAG_INDEX(hdma)) != RESET) ? 1U : 0U;
}

static uint8_t WS2812_BSR_DmaTransferError(DMA_HandleTypeDef *hdma)
{
  return (__HAL_DMA_GET_FLAG(hdma, __HAL_DMA_GET_TE_FLAG_INDEX(hdma)) != RESET) ? 1U : 0U;
}

static void WS2812_BSR_ReleaseDmaHandle(DMA_HandleTypeDef *hdma)
{
  hdma->Instance->CCR &= ~(DMA_IT_TC | DMA_IT_HT | DMA_IT_TE);
  __HAL_DMA_DISABLE(hdma);
  __HAL_DMA_CLEAR_FLAG(hdma, __HAL_DMA_GET_GI_FLAG_INDEX(hdma));
  hdma->ErrorCode = HAL_DMA_ERROR_NONE;
  hdma->State = HAL_DMA_STATE_READY;
  __HAL_UNLOCK(hdma);
}

static void WS2812_BSR_DmaCompleteCallback(DMA_HandleTypeDef *hdma)
{
  if (hdma != &ws2812_hdma_tim4_cc2)
  {
    return;
  }

  WS2812_BSR_CleanupCompletedDma();
  ws2812_bsr_diag_complete_count++;
  ws2812_complete_count_watch = ws2812_bsr_diag_complete_count + ws2812_bsr_diag_poll_complete_count;
  WS2812_BSR_MarkDmaDone();
}

static void WS2812_BSR_DmaErrorCallback(DMA_HandleTypeDef *hdma)
{
  (void)hdma;
  ws2812_bsr_diag_error_count++;
  WS2812_BSR_AbortDma();
  WS2812_BSR_MarkDmaDone();
}

static void WS2812_BSR_CleanupCompletedDma(void)
{
  WS2812_BSR_StopTimerDma();

  WS2812_BSR_ReleaseDmaHandle(&ws2812_hdma_tim4_up);
  WS2812_BSR_ReleaseDmaHandle(&ws2812_hdma_tim4_cc1);
  WS2812_BSR_ReleaseDmaHandle(&ws2812_hdma_tim4_cc2);
}

static void WS2812_BSR_AbortDma(void)
{
  WS2812_BSR_StopTimerDma();
  WS2812_BSR_ReleaseDmaHandle(&ws2812_hdma_tim4_up);
  WS2812_BSR_ReleaseDmaHandle(&ws2812_hdma_tim4_cc1);
  WS2812_BSR_ReleaseDmaHandle(&ws2812_hdma_tim4_cc2);
  GPIOA->BSRR = WS2812_BSR_RESET(WS2812_BSR_ACTIVE_MASK);
}

static void WS2812_BSR_MarkDmaDone(void)
{
  GPIOA->BSRR = WS2812_BSR_RESET(WS2812_BSR_ACTIVE_MASK);
  ws2812_latch_start_tick = HAL_GetTick();
  ws2812_dma_done = 1U;
}
static void WS2812_BSR_DemoColorWheel(uint8_t hue, uint8_t brightness, uint8_t *r, uint8_t *g, uint8_t *b)
{
  uint16_t red = 0U;
  uint16_t green = 0U;
  uint16_t blue = 0U;

  if (hue < 85U)
  {
    red = (uint16_t)(255U - ((uint16_t)hue * 3U));
    green = (uint16_t)hue * 3U;
  }
  else if (hue < 170U)
  {
    uint8_t pos = (uint8_t)(hue - 85U);

    green = (uint16_t)(255U - ((uint16_t)pos * 3U));
    blue = (uint16_t)pos * 3U;
  }
  else
  {
    uint8_t pos = (uint8_t)(hue - 170U);

    blue = (uint16_t)(255U - ((uint16_t)pos * 3U));
    red = (uint16_t)pos * 3U;
  }

  *r = (uint8_t)((red * brightness) / 255U);
  *g = (uint8_t)((green * brightness) / 255U);
  *b = (uint8_t)((blue * brightness) / 255U);
}
