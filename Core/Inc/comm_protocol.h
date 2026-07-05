#ifndef COMM_PROTOCOL_H
#define COMM_PROTOCOL_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

#define COMM_PROTOCOL_SYNC0             0x5AU
#define COMM_PROTOCOL_SYNC1             0xA5U
#define COMM_PROTOCOL_HEADER_SIZE       7U
#define COMM_PROTOCOL_CRC_SIZE          2U
#define COMM_PROTOCOL_MAX_PAYLOAD       640U
#define COMM_PROTOCOL_FRAME_CHUNKS      2U
#define COMM_PROTOCOL_LANES_PER_CHUNK   4U
#define COMM_PROTOCOL_CHUNK_RGB_BYTES   576U
#define COMM_PROTOCOL_LEDS_PER_CHUNK    192U
#define COMM_PROTOCOL_LOGICAL_LEDS_PER_LANE  48U

typedef enum
{
  COMM_MSG_HELLO_REQ = 0x01U,
  COMM_MSG_HELLO_RSP = 0x81U,
  COMM_MSG_FRAME_BEGIN = 0x10U,
  COMM_MSG_FRAME_RGB_CHUNK = 0x11U,
  COMM_MSG_FRAME_COMMIT = 0x12U,
  COMM_MSG_ALL_BLACK = 0x13U,
  COMM_MSG_STATUS_REQ = 0x20U,
  COMM_MSG_STATUS_RSP = 0xA0U,
  COMM_MSG_ERROR_RSP = 0xE0U
} CommProtocolMsgType_t;

typedef enum
{
  COMM_PROTO_OK = 0U,
  COMM_PROTO_ERR_BAD_VERSION = 1U,
  COMM_PROTO_ERR_BAD_LENGTH = 2U,
  COMM_PROTO_ERR_BAD_CRC = 3U,
  COMM_PROTO_ERR_BAD_TYPE = 4U,
  COMM_PROTO_ERR_BAD_STATE = 5U,
  COMM_PROTO_ERR_BAD_FRAME_ID = 6U,
  COMM_PROTO_ERR_BAD_CHUNK = 7U,
  COMM_PROTO_ERR_INCOMPLETE_FRAME = 8U,
  COMM_PROTO_ERR_FAULT_ACTIVE = 9U,
  COMM_PROTO_ERR_RX_OVERFLOW = 10U
} CommProtocolStatus_t;

void CommProtocol_Init(void);
void CommProtocol_Poll(uint32_t now_ms);
void CommProtocol_OutputPoll(uint32_t now_ms);
uint8_t CommProtocol_HasOutputControl(void);
void CommProtocol_Reset(void);

extern volatile uint8_t comm_protocol_watch_parser_state;
extern volatile uint8_t comm_protocol_watch_host_control_active;
extern volatile uint8_t comm_protocol_watch_pending_show;
extern volatile uint8_t comm_protocol_watch_last_error;
extern volatile uint16_t comm_protocol_watch_frame_id;
extern volatile uint16_t comm_protocol_watch_received_mask;
extern volatile uint32_t comm_protocol_watch_uid_hash;
extern volatile uint32_t comm_protocol_watch_packet_count;
extern volatile uint32_t comm_protocol_watch_crc_error_count;
extern volatile uint32_t comm_protocol_watch_parser_error_count;
extern volatile uint32_t comm_protocol_watch_commit_count;
extern volatile uint32_t comm_protocol_watch_commit_error_count;
extern volatile uint32_t comm_protocol_watch_timeout_black_count;
extern volatile uint32_t comm_protocol_watch_last_valid_packet_ms;
extern volatile uint32_t comm_protocol_watch_frame_begin_ms;
extern volatile uint32_t comm_protocol_watch_last_chunk_ms;
extern volatile uint32_t comm_protocol_watch_commit_rx_ms;
extern volatile uint32_t comm_protocol_watch_apply_start_ms;
extern volatile uint32_t comm_protocol_watch_apply_done_ms;
extern volatile uint32_t comm_protocol_watch_show_request_ms;
extern volatile uint32_t comm_protocol_watch_show_start_ms;
extern volatile uint32_t comm_protocol_watch_commit_rsp_ms;
extern volatile uint32_t comm_protocol_watch_frame_rx_span_ms;
extern volatile uint32_t comm_protocol_watch_commit_to_rsp_ms;

#ifdef __cplusplus
}
#endif

#endif /* COMM_PROTOCOL_H */
