#ifndef COMM_TRANSPORT_H
#define COMM_TRANSPORT_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

#define COMM_RX_RING_SIZE  256U
#define COMM_TX_BUFFER_SIZE 128U

typedef enum
{
  COMM_TRANSPORT_LINK_NONE = 0U,
  COMM_TRANSPORT_LINK_USB = 1U,
  COMM_TRANSPORT_LINK_UART = 2U
} CommTransportLink_t;

/* Reset the shared communication receive ring and counters. */
void CommTransport_Init(void);
/* Refresh debugger-visible transport state. */
void CommTransport_Poll(uint32_t now_ms);
/* Copy USB CDC bytes into the shared receive ring. */
uint16_t CommTransport_WriteFromUsb(const uint8_t *data, uint16_t len);
/* Read bytes from the shared receive ring for a future parser. */
uint16_t CommTransport_Read(uint8_t *data, uint16_t max_len);
/* Send one small protocol response on the active transport. */
uint16_t CommTransport_Send(const uint8_t *data, uint16_t len);
/* Clear the receive ring and pending overflow state. */
void CommTransport_ClearRx(void);
/* Return the current number of buffered bytes. */
uint16_t CommTransport_GetRxUsed(void);
/* Return and clear the pending overflow flag. */
uint8_t CommTransport_ConsumeOverflow(void);
/* Return and clear the active-link change flag. */
uint8_t CommTransport_ConsumeLinkChanged(void);
/* Return the currently selected transport link. */
CommTransportLink_t CommTransport_GetActiveLink(void);

/* Static RX ring is exposed for debugger inspection. */
extern uint8_t comm_transport_rx_ring[COMM_RX_RING_SIZE];

extern volatile uint16_t comm_transport_watch_rx_write_index;
extern volatile uint16_t comm_transport_watch_rx_read_index;
extern volatile uint16_t comm_transport_watch_rx_used;
extern volatile uint16_t comm_transport_watch_rx_max_used;
extern volatile uint8_t comm_transport_watch_rx_overflow_pending;
extern volatile uint32_t comm_transport_watch_usb_packet_count;
extern volatile uint32_t comm_transport_watch_rx_total_bytes;
extern volatile uint32_t comm_transport_watch_rx_dropped_bytes;
extern volatile uint32_t comm_transport_watch_rx_overflow_count;
extern volatile uint8_t comm_transport_watch_active_link;
extern volatile uint8_t comm_transport_watch_link_changed;
extern volatile uint8_t comm_transport_watch_uart_dma_started;
extern volatile uint8_t comm_transport_watch_tx_state;
extern volatile uint32_t comm_transport_watch_uart_byte_count;
extern volatile uint32_t comm_transport_watch_link_switch_count;
extern volatile uint32_t comm_transport_watch_tx_packet_count;
extern volatile uint32_t comm_transport_watch_tx_busy_drop_count;
extern volatile uint32_t comm_transport_watch_tx_error_count;

#ifdef __cplusplus
}
#endif

#endif /* COMM_TRANSPORT_H */
