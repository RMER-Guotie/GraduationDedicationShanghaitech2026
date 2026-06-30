#ifndef COMM_TRANSPORT_H
#define COMM_TRANSPORT_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

#define COMM_RX_RING_SIZE  256U

/* Reset the shared communication receive ring and counters. */
void CommTransport_Init(void);
/* Refresh debugger-visible transport state. */
void CommTransport_Poll(uint32_t now_ms);
/* Copy USB CDC bytes into the shared receive ring. */
uint16_t CommTransport_WriteFromUsb(const uint8_t *data, uint16_t len);
/* Read bytes from the shared receive ring for a future parser. */
uint16_t CommTransport_Read(uint8_t *data, uint16_t max_len);
/* Clear the receive ring and pending overflow state. */
void CommTransport_ClearRx(void);
/* Return the current number of buffered bytes. */
uint16_t CommTransport_GetRxUsed(void);
/* Return and clear the pending overflow flag. */
uint8_t CommTransport_ConsumeOverflow(void);

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

#ifdef __cplusplus
}
#endif

#endif /* COMM_TRANSPORT_H */
