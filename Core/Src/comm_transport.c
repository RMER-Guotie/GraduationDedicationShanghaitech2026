#include "comm_transport.h"

#include "main.h"

uint8_t comm_transport_rx_ring[COMM_RX_RING_SIZE];

volatile uint16_t comm_transport_watch_rx_write_index;
volatile uint16_t comm_transport_watch_rx_read_index;
volatile uint16_t comm_transport_watch_rx_used;
volatile uint16_t comm_transport_watch_rx_max_used;
volatile uint8_t comm_transport_watch_rx_overflow_pending;
volatile uint32_t comm_transport_watch_usb_packet_count;
volatile uint32_t comm_transport_watch_rx_total_bytes;
volatile uint32_t comm_transport_watch_rx_dropped_bytes;
volatile uint32_t comm_transport_watch_rx_overflow_count;

static volatile uint16_t comm_transport_rx_write_index;
static volatile uint16_t comm_transport_rx_read_index;
static volatile uint16_t comm_transport_rx_used;
static volatile uint16_t comm_transport_rx_max_used;
static volatile uint8_t comm_transport_rx_overflow_pending;
static volatile uint32_t comm_transport_usb_packet_count;
static volatile uint32_t comm_transport_rx_total_bytes;
static volatile uint32_t comm_transport_rx_dropped_bytes;
static volatile uint32_t comm_transport_rx_overflow_count;

static uint32_t CommTransport_EnterCritical(void);
static void CommTransport_ExitCritical(uint32_t primask);
static uint16_t CommTransport_AdvanceIndex(uint16_t index);
static void CommTransport_UpdateWatch(void);

void CommTransport_Init(void)
{
  uint32_t primask = CommTransport_EnterCritical();

  comm_transport_rx_write_index = 0U;
  comm_transport_rx_read_index = 0U;
  comm_transport_rx_used = 0U;
  comm_transport_rx_max_used = 0U;
  comm_transport_rx_overflow_pending = 0U;
  comm_transport_usb_packet_count = 0U;
  comm_transport_rx_total_bytes = 0U;
  comm_transport_rx_dropped_bytes = 0U;
  comm_transport_rx_overflow_count = 0U;
  CommTransport_UpdateWatch();

  CommTransport_ExitCritical(primask);
}

void CommTransport_Poll(uint32_t now_ms)
{
  uint32_t primask;

  (void)now_ms;
  primask = CommTransport_EnterCritical();
  CommTransport_UpdateWatch();
  CommTransport_ExitCritical(primask);
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

  comm_transport_usb_packet_count++;
  comm_transport_rx_total_bytes += len;

  if (len > (uint16_t)(COMM_RX_RING_SIZE - comm_transport_rx_used))
  {
    comm_transport_rx_overflow_pending = 1U;
    comm_transport_rx_overflow_count++;
    comm_transport_rx_dropped_bytes += len;
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

  primask = CommTransport_EnterCritical();

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

void CommTransport_ClearRx(void)
{
  uint32_t primask = CommTransport_EnterCritical();

  comm_transport_rx_write_index = 0U;
  comm_transport_rx_read_index = 0U;
  comm_transport_rx_used = 0U;
  comm_transport_rx_overflow_pending = 0U;
  CommTransport_UpdateWatch();

  CommTransport_ExitCritical(primask);
}

uint16_t CommTransport_GetRxUsed(void)
{
  uint16_t used;
  uint32_t primask = CommTransport_EnterCritical();

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
}
