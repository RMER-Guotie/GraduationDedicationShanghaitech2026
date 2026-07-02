#include "comm_transport.h"

#include "main.h"
#include "app_config.h"
#include "usart.h"
#include "usbd_cdc_if.h"

/* Shared byte-stream transport for USB CDC and USART1 DMA RX. */
#define COMM_UART_RX_DMA_CHANNEL       DMA1_Channel5

extern USBD_HandleTypeDef hUsbDeviceFS;

typedef enum
{
  COMM_TX_IDLE = 0U,
  COMM_TX_USB_PENDING = 1U,
  COMM_TX_USB_IN_FLIGHT = 2U
} CommTransportTxState_t;

uint8_t comm_transport_rx_ring[COMM_RX_RING_SIZE];

/* Watch variables are intentionally global for live debugger inspection. */
volatile uint16_t comm_transport_watch_rx_write_index;
volatile uint16_t comm_transport_watch_rx_read_index;
volatile uint16_t comm_transport_watch_rx_used;
volatile uint16_t comm_transport_watch_rx_max_used;
volatile uint8_t comm_transport_watch_rx_overflow_pending;
volatile uint32_t comm_transport_watch_usb_packet_count;
volatile uint32_t comm_transport_watch_rx_total_bytes;
volatile uint32_t comm_transport_watch_rx_dropped_bytes;
volatile uint32_t comm_transport_watch_rx_overflow_count;
volatile uint8_t comm_transport_watch_active_link;
volatile uint8_t comm_transport_watch_link_changed;
volatile uint8_t comm_transport_watch_uart_dma_started;
volatile uint8_t comm_transport_watch_tx_state;
volatile uint32_t comm_transport_watch_uart_byte_count;
volatile uint32_t comm_transport_watch_link_switch_count;
volatile uint32_t comm_transport_watch_tx_packet_count;
volatile uint32_t comm_transport_watch_tx_busy_drop_count;
volatile uint32_t comm_transport_watch_tx_error_count;

static DMA_HandleTypeDef comm_transport_hdma_usart1_rx;
/* RX ring indexes are shared by USB ISR, UART DMA polling, and parser reads. */
static volatile uint16_t comm_transport_rx_write_index;
static volatile uint16_t comm_transport_rx_read_index;
static volatile uint16_t comm_transport_rx_used;
static volatile uint16_t comm_transport_rx_max_used;
static volatile uint8_t comm_transport_rx_overflow_pending;
static volatile uint8_t comm_transport_link_changed;
static volatile uint32_t comm_transport_usb_packet_count;
static volatile uint32_t comm_transport_uart_byte_count;
static volatile uint32_t comm_transport_rx_total_bytes;
static volatile uint32_t comm_transport_rx_dropped_bytes;
static volatile uint32_t comm_transport_rx_overflow_count;
static volatile uint32_t comm_transport_link_switch_count;
static volatile uint8_t comm_transport_uart_dma_started;
static CommTransportLink_t comm_transport_active_link;
static uint16_t comm_transport_uart_dma_last_index;

/* Only one small response can be pending; protocol responses are short. */
static uint8_t comm_transport_tx_buffer[COMM_TX_BUFFER_SIZE];
static uint16_t comm_transport_tx_len;
static CommTransportTxState_t comm_transport_tx_state;
static volatile uint32_t comm_transport_tx_packet_count;
static volatile uint32_t comm_transport_tx_busy_drop_count;
static volatile uint32_t comm_transport_tx_error_count;

static uint32_t CommTransport_EnterCritical(void);
static void CommTransport_ExitCritical(uint32_t primask);
static uint16_t CommTransport_AdvanceIndex(uint16_t index);
static uint16_t CommTransport_Distance(uint16_t from, uint16_t to);
static void CommTransport_ActivateLink(CommTransportLink_t link, uint8_t clear_on_switch);
static void CommTransport_ClearRxInternal(void);
static uint8_t CommTransport_StartUartDma(void);
static void CommTransport_UpdateUartDmaWriteIndex(void);
static uint16_t CommTransport_GetUartDmaWriteIndex(void);
static void CommTransport_RecordOverflow(uint16_t dropped);
static void CommTransport_PollTx(void);
static void CommTransport_UpdateWatch(void);

void CommTransport_Init(void)
{
  uint32_t primask;

  /* Runtime baud override avoids changing the generated USART init code. */
  huart1.Init.BaudRate = APP_COMM_UART_BAUD;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }

  primask = CommTransport_EnterCritical();

  comm_transport_active_link = COMM_TRANSPORT_LINK_NONE;
  comm_transport_link_changed = 0U;
  comm_transport_rx_write_index = 0U;
  comm_transport_rx_read_index = 0U;
  comm_transport_rx_used = 0U;
  comm_transport_rx_max_used = 0U;
  comm_transport_rx_overflow_pending = 0U;
  comm_transport_usb_packet_count = 0U;
  comm_transport_uart_byte_count = 0U;
  comm_transport_rx_total_bytes = 0U;
  comm_transport_rx_dropped_bytes = 0U;
  comm_transport_rx_overflow_count = 0U;
  comm_transport_link_switch_count = 0U;
  comm_transport_uart_dma_started = 0U;
  comm_transport_uart_dma_last_index = 0U;
  comm_transport_tx_len = 0U;
  comm_transport_tx_state = COMM_TX_IDLE;
  comm_transport_tx_packet_count = 0U;
  comm_transport_tx_busy_drop_count = 0U;
  comm_transport_tx_error_count = 0U;
  CommTransport_UpdateWatch();

  CommTransport_ExitCritical(primask);

  (void)CommTransport_StartUartDma();
}

void CommTransport_Poll(uint32_t now_ms)
{
  uint32_t primask;

  (void)now_ms;

  primask = CommTransport_EnterCritical();
  CommTransport_UpdateUartDmaWriteIndex();
  CommTransport_UpdateWatch();
  CommTransport_ExitCritical(primask);

  CommTransport_PollTx();
}

uint16_t CommTransport_WriteFromUsb(const uint8_t *data, uint16_t len)
{
  uint16_t written = 0U;
  uint32_t primask;

  if ((data == 0) || (len == 0U))
  {
    return 0U;
  }

  primask = CommTransport_EnterCritical();

  /* USB callback copies bytes only; parsing stays in the main loop. */
  CommTransport_ActivateLink(COMM_TRANSPORT_LINK_USB, 1U);
  comm_transport_usb_packet_count++;
  comm_transport_rx_total_bytes += len;

  if (len > (uint16_t)(COMM_RX_RING_SIZE - comm_transport_rx_used))
  {
    CommTransport_RecordOverflow(len);
    CommTransport_UpdateWatch();
    CommTransport_ExitCritical(primask);
    return 0U;
  }

  while (written < len)
  {
    comm_transport_rx_ring[comm_transport_rx_write_index] = data[written];
    comm_transport_rx_write_index = CommTransport_AdvanceIndex(comm_transport_rx_write_index);
    written++;
  }

  comm_transport_rx_used = (uint16_t)(comm_transport_rx_used + written);
  if (comm_transport_rx_used > comm_transport_rx_max_used)
  {
    comm_transport_rx_max_used = comm_transport_rx_used;
  }

  CommTransport_UpdateWatch();
  CommTransport_ExitCritical(primask);

  return written;
}

uint16_t CommTransport_Read(uint8_t *data, uint16_t max_len)
{
  uint16_t read_count = 0U;
  uint32_t primask;

  if ((data == 0) || (max_len == 0U))
  {
    return 0U;
  }

  /* UART DMA can advance while the parser drains bytes, so protect indexes. */
  primask = CommTransport_EnterCritical();
  CommTransport_UpdateUartDmaWriteIndex();

  while ((read_count < max_len) && (comm_transport_rx_used > 0U))
  {
    data[read_count] = comm_transport_rx_ring[comm_transport_rx_read_index];
    comm_transport_rx_read_index = CommTransport_AdvanceIndex(comm_transport_rx_read_index);
    comm_transport_rx_used--;
    read_count++;
  }

  CommTransport_UpdateWatch();
  CommTransport_ExitCritical(primask);

  return read_count;
}

uint16_t CommTransport_Send(const uint8_t *data, uint16_t len)
{
  HAL_StatusTypeDef uart_status;
  uint32_t primask;
  uint16_t index;
  CommTransportLink_t active_link;

  if ((data == 0) || (len == 0U) || (len > COMM_TX_BUFFER_SIZE))
  {
    return 0U;
  }

  CommTransport_PollTx();

  primask = CommTransport_EnterCritical();
  active_link = comm_transport_active_link;

  /* Response path follows the currently active link selected by RX traffic. */
  if (active_link == COMM_TRANSPORT_LINK_USB)
  {
    if (comm_transport_tx_state != COMM_TX_IDLE)
    {
      comm_transport_tx_busy_drop_count++;
      CommTransport_UpdateWatch();
      CommTransport_ExitCritical(primask);
      return 0U;
    }

    for (index = 0U; index < len; index++)
    {
      comm_transport_tx_buffer[index] = data[index];
    }

    comm_transport_tx_len = len;
    comm_transport_tx_state = COMM_TX_USB_PENDING;
    CommTransport_UpdateWatch();
    CommTransport_ExitCritical(primask);

    CommTransport_PollTx();
    return len;
  }

  CommTransport_ExitCritical(primask);

  if (active_link == COMM_TRANSPORT_LINK_UART)
  {
    uart_status = HAL_UART_Transmit(&huart1, (uint8_t *)data, len, APP_COMM_UART_TX_TIMEOUT_MS);
    if (uart_status == HAL_OK)
    {
      primask = CommTransport_EnterCritical();
      comm_transport_tx_packet_count++;
      CommTransport_UpdateWatch();
      CommTransport_ExitCritical(primask);
      return len;
    }
  }

  primask = CommTransport_EnterCritical();
  comm_transport_tx_error_count++;
  CommTransport_UpdateWatch();
  CommTransport_ExitCritical(primask);
  return 0U;
}

void CommTransport_ClearRx(void)
{
  uint32_t primask = CommTransport_EnterCritical();

  CommTransport_ClearRxInternal();
  CommTransport_UpdateWatch();

  CommTransport_ExitCritical(primask);
}

uint16_t CommTransport_GetRxUsed(void)
{
  uint16_t used;
  uint32_t primask = CommTransport_EnterCritical();

  CommTransport_UpdateUartDmaWriteIndex();
  used = comm_transport_rx_used;

  CommTransport_ExitCritical(primask);
  return used;
}

uint8_t CommTransport_ConsumeOverflow(void)
{
  uint8_t overflow;
  uint32_t primask = CommTransport_EnterCritical();

  overflow = comm_transport_rx_overflow_pending;
  comm_transport_rx_overflow_pending = 0U;
  CommTransport_UpdateWatch();

  CommTransport_ExitCritical(primask);
  return overflow;
}

uint8_t CommTransport_ConsumeLinkChanged(void)
{
  uint8_t changed;
  uint32_t primask = CommTransport_EnterCritical();

  changed = comm_transport_link_changed;
  comm_transport_link_changed = 0U;
  CommTransport_UpdateWatch();

  CommTransport_ExitCritical(primask);
  return changed;
}

CommTransportLink_t CommTransport_GetActiveLink(void)
{
  CommTransportLink_t link;
  uint32_t primask = CommTransport_EnterCritical();

  link = comm_transport_active_link;

  CommTransport_ExitCritical(primask);
  return link;
}

void DMA1_Channel5_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&comm_transport_hdma_usart1_rx);
}

static uint32_t CommTransport_EnterCritical(void)
{
  uint32_t primask = __get_PRIMASK();
  __disable_irq();
  return primask;
}

static void CommTransport_ExitCritical(uint32_t primask)
{
  if (primask == 0U)
  {
    __enable_irq();
  }
}

static uint16_t CommTransport_AdvanceIndex(uint16_t index)
{
  index++;
  if (index >= COMM_RX_RING_SIZE)
  {
    index = 0U;
  }
  return index;
}

static uint16_t CommTransport_Distance(uint16_t from, uint16_t to)
{
  if (to >= from)
  {
    return (uint16_t)(to - from);
  }

  return (uint16_t)(COMM_RX_RING_SIZE - from + to);
}

static void CommTransport_ActivateLink(CommTransportLink_t link, uint8_t clear_on_switch)
{
  if (comm_transport_active_link == link)
  {
    return;
  }

  /* Switching links invalidates partial packets and frame transactions. */
  if (comm_transport_active_link != COMM_TRANSPORT_LINK_NONE)
  {
    comm_transport_link_switch_count++;
    comm_transport_link_changed = 1U;
    if (clear_on_switch != 0U)
    {
      CommTransport_ClearRxInternal();
    }
  }

  comm_transport_active_link = link;
}

static void CommTransport_ClearRxInternal(void)
{
  if ((comm_transport_active_link == COMM_TRANSPORT_LINK_UART) &&
      (comm_transport_uart_dma_started != 0U))
  {
    comm_transport_rx_write_index = CommTransport_GetUartDmaWriteIndex();
    comm_transport_uart_dma_last_index = comm_transport_rx_write_index;
  }
  else
  {
    comm_transport_rx_write_index = 0U;
  }

  comm_transport_rx_read_index = comm_transport_rx_write_index;
  comm_transport_rx_used = 0U;
  comm_transport_rx_overflow_pending = 0U;
}

static uint8_t CommTransport_StartUartDma(void)
{
  HAL_StatusTypeDef status;

  /* USART1 RX uses DMA1 Channel5 in circular mode into the shared ring. */
  __HAL_RCC_DMA1_CLK_ENABLE();

  comm_transport_hdma_usart1_rx.Instance = COMM_UART_RX_DMA_CHANNEL;
  comm_transport_hdma_usart1_rx.Init.Direction = DMA_PERIPH_TO_MEMORY;
  comm_transport_hdma_usart1_rx.Init.PeriphInc = DMA_PINC_DISABLE;
  comm_transport_hdma_usart1_rx.Init.MemInc = DMA_MINC_ENABLE;
  comm_transport_hdma_usart1_rx.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
  comm_transport_hdma_usart1_rx.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
  comm_transport_hdma_usart1_rx.Init.Mode = DMA_CIRCULAR;
  comm_transport_hdma_usart1_rx.Init.Priority = DMA_PRIORITY_HIGH;

  if (HAL_DMA_Init(&comm_transport_hdma_usart1_rx) != HAL_OK)
  {
    return 0U;
  }

  __HAL_LINKDMA(&huart1, hdmarx, comm_transport_hdma_usart1_rx);

  HAL_NVIC_DisableIRQ(DMA1_Channel5_IRQn);
  HAL_NVIC_ClearPendingIRQ(DMA1_Channel5_IRQn);
  HAL_NVIC_SetPriority(DMA1_Channel5_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(DMA1_Channel5_IRQn);

  status = HAL_UART_Receive_DMA(&huart1, comm_transport_rx_ring, COMM_RX_RING_SIZE);
  if (status != HAL_OK)
  {
    return 0U;
  }

  comm_transport_uart_dma_started = 1U;
  comm_transport_uart_dma_last_index = CommTransport_GetUartDmaWriteIndex();
  return 1U;
}

static void CommTransport_UpdateUartDmaWriteIndex(void)
{
  uint16_t dma_write_index;
  uint16_t delta;
  uint16_t free_space;

  if (comm_transport_uart_dma_started == 0U)
  {
    return;
  }

  /* Convert the DMA remaining count into producer progress in the RX ring. */
  dma_write_index = CommTransport_GetUartDmaWriteIndex();
  delta = CommTransport_Distance(comm_transport_uart_dma_last_index, dma_write_index);

  if (delta == 0U)
  {
    return;
  }

  comm_transport_uart_dma_last_index = dma_write_index;
  comm_transport_uart_byte_count += delta;
  comm_transport_rx_total_bytes += delta;

  if (comm_transport_active_link == COMM_TRANSPORT_LINK_NONE)
  {
    comm_transport_active_link = COMM_TRANSPORT_LINK_UART;
  }
  else if (comm_transport_active_link != COMM_TRANSPORT_LINK_UART)
  {
    comm_transport_link_switch_count++;
    comm_transport_link_changed = 1U;
    comm_transport_active_link = COMM_TRANSPORT_LINK_UART;
    comm_transport_rx_write_index = dma_write_index;
    comm_transport_rx_read_index = dma_write_index;
    comm_transport_rx_used = 0U;
    return;
  }

  free_space = (uint16_t)(COMM_RX_RING_SIZE - comm_transport_rx_used);
  if (delta > free_space)
  {
    CommTransport_RecordOverflow((uint16_t)(comm_transport_rx_used + delta));
    comm_transport_rx_write_index = dma_write_index;
    comm_transport_rx_read_index = dma_write_index;
    comm_transport_rx_used = 0U;
    return;
  }

  comm_transport_rx_write_index = dma_write_index;
  comm_transport_rx_used = (uint16_t)(comm_transport_rx_used + delta);
  if (comm_transport_rx_used > comm_transport_rx_max_used)
  {
    comm_transport_rx_max_used = comm_transport_rx_used;
  }
}

static uint16_t CommTransport_GetUartDmaWriteIndex(void)
{
  uint16_t remaining = (uint16_t)__HAL_DMA_GET_COUNTER(&comm_transport_hdma_usart1_rx);
  uint16_t index = (uint16_t)(COMM_RX_RING_SIZE - remaining);

  if (index >= COMM_RX_RING_SIZE)
  {
    index = 0U;
  }

  return index;
}

static void CommTransport_RecordOverflow(uint16_t dropped)
{
  comm_transport_rx_overflow_pending = 1U;
  comm_transport_rx_overflow_count++;
  comm_transport_rx_dropped_bytes += dropped;
}

static void CommTransport_PollTx(void)
{
  USBD_CDC_HandleTypeDef *hcdc;
  uint32_t primask;
  uint8_t result;

  primask = CommTransport_EnterCritical();

  if (comm_transport_tx_state == COMM_TX_IDLE)
  {
    CommTransport_UpdateWatch();
    CommTransport_ExitCritical(primask);
    return;
  }

  if (comm_transport_active_link != COMM_TRANSPORT_LINK_USB)
  {
    comm_transport_tx_state = COMM_TX_IDLE;
    comm_transport_tx_len = 0U;
    CommTransport_UpdateWatch();
    CommTransport_ExitCritical(primask);
    return;
  }

  hcdc = (USBD_CDC_HandleTypeDef *)hUsbDeviceFS.pClassData;
  if (hcdc == 0)
  {
    CommTransport_UpdateWatch();
    CommTransport_ExitCritical(primask);
    return;
  }

  /* CDC clears TxState after the USB stack has accepted the IN transfer. */
  if ((comm_transport_tx_state == COMM_TX_USB_IN_FLIGHT) && (hcdc->TxState == 0U))
  {
    comm_transport_tx_state = COMM_TX_IDLE;
    comm_transport_tx_len = 0U;
    CommTransport_UpdateWatch();
    CommTransport_ExitCritical(primask);
    return;
  }

  if (comm_transport_tx_state != COMM_TX_USB_PENDING)
  {
    CommTransport_UpdateWatch();
    CommTransport_ExitCritical(primask);
    return;
  }

  if (hcdc->TxState != 0U)
  {
    CommTransport_UpdateWatch();
    CommTransport_ExitCritical(primask);
    return;
  }

  CommTransport_ExitCritical(primask);
  result = CDC_Transmit_FS(comm_transport_tx_buffer, comm_transport_tx_len);

  primask = CommTransport_EnterCritical();
  if (result == USBD_OK)
  {
    comm_transport_tx_state = COMM_TX_USB_IN_FLIGHT;
    comm_transport_tx_packet_count++;
  }
  else if (result != USBD_BUSY)
  {
    comm_transport_tx_state = COMM_TX_IDLE;
    comm_transport_tx_len = 0U;
    comm_transport_tx_error_count++;
  }

  CommTransport_UpdateWatch();
  CommTransport_ExitCritical(primask);
}

static void CommTransport_UpdateWatch(void)
{
  comm_transport_watch_rx_write_index = comm_transport_rx_write_index;
  comm_transport_watch_rx_read_index = comm_transport_rx_read_index;
  comm_transport_watch_rx_used = comm_transport_rx_used;
  comm_transport_watch_rx_max_used = comm_transport_rx_max_used;
  comm_transport_watch_rx_overflow_pending = comm_transport_rx_overflow_pending;
  comm_transport_watch_usb_packet_count = comm_transport_usb_packet_count;
  comm_transport_watch_rx_total_bytes = comm_transport_rx_total_bytes;
  comm_transport_watch_rx_dropped_bytes = comm_transport_rx_dropped_bytes;
  comm_transport_watch_rx_overflow_count = comm_transport_rx_overflow_count;
  comm_transport_watch_active_link = (uint8_t)comm_transport_active_link;
  comm_transport_watch_link_changed = comm_transport_link_changed;
  comm_transport_watch_uart_dma_started = comm_transport_uart_dma_started;
  comm_transport_watch_tx_state = (uint8_t)comm_transport_tx_state;
  comm_transport_watch_uart_byte_count = comm_transport_uart_byte_count;
  comm_transport_watch_link_switch_count = comm_transport_link_switch_count;
  comm_transport_watch_tx_packet_count = comm_transport_tx_packet_count;
  comm_transport_watch_tx_busy_drop_count = comm_transport_tx_busy_drop_count;
  comm_transport_watch_tx_error_count = comm_transport_tx_error_count;
}
