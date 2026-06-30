#include "app_controller.h"

#include "comm_transport.h"
#include "current_protect.h"
#include "remote_input.h"
#include "white_pwm.h"
#include "ws2812_bsr_dma.h"

volatile uint32_t app_controller_watch_loop_count;
volatile uint8_t app_controller_watch_fault_active;
volatile uint8_t app_controller_watch_rc_stable_bits;

static uint8_t app_controller_fault_was_active;

static void AppController_HandleFault(void);
static void AppController_HandleNormal(uint32_t now_ms);
static void AppController_UpdateWatch(void);

void AppController_Init(void)
{
  /* Keep generated main.c thin and initialize app modules in dependency order. */
  WS2812_BSR_Init();
  RemoteInput_Init();
  WhitePwm_Init();
  CurrentProtect_Init();
  CommTransport_Init();

  app_controller_watch_loop_count = 0U;
  app_controller_fault_was_active = 0U;
  AppController_UpdateWatch();
}

void AppController_Poll(uint32_t now_ms)
{
  /* Cooperative scheduler, normally called about every 1 ms. */
  app_controller_watch_loop_count++;

  CommTransport_Poll(now_ms);
  RemoteInput_Poll(now_ms);
  CurrentProtect_Poll(now_ms);
  WhitePwm_Poll(now_ms);

  if (CurrentProtect_IsFaultActive() != 0U)
  {
    AppController_HandleFault();
  }
  else
  {
    AppController_HandleNormal(now_ms);
  }

  AppController_UpdateWatch();
}

static void AppController_HandleFault(void)
{
  if (app_controller_fault_was_active == 0U)
  {
    WS2812_BSR_ForceBlack();
    app_controller_fault_was_active = 1U;
  }

  /* During fault, keep retransmitting a black WS2812 frame whenever idle. */
  WS2812_BSR_Poll();
  if (WS2812_BSR_IsBusy() == 0U)
  {
    WS2812_BSR_Clear();
    WS2812_BSR_Show();
  }
}

static void AppController_HandleNormal(uint32_t now_ms)
{
  app_controller_fault_was_active = 0U;

  /* Normal validation mode: animate the WS2812 lanes. */
  WS2812_BSR_TestPatternStep(now_ms);
}

static void AppController_UpdateWatch(void)
{
  app_controller_watch_fault_active = CurrentProtect_IsFaultActive();
  app_controller_watch_rc_stable_bits = RemoteInput_GetStableBits();
}
