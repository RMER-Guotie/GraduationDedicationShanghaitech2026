#include "comm_protocol.h"

#include <string.h>

#include "main.h"
#include "app_config.h"
#include "comm_transport.h"
#include "current_protect.h"
#include "remote_input.h"
#include "white_pwm.h"
#include "ws2812_bsr_dma.h"

/* Host protocol parser and frame transaction manager. */
#define COMM_PROTOCOL_UID_WORDS             3U
#define COMM_PROTOCOL_UID_BASE_ADDRESS      0x1FFFF7E8UL
#define COMM_PROTOCOL_FRAME_RECEIVED_MASK   0x000FU
#define COMM_PROTOCOL_FRAME_BEGIN_LEN       12U
#define COMM_PROTOCOL_CHUNK_HEADER_LEN      5U
#define COMM_PROTOCOL_CHUNK_PAYLOAD_LEN     (COMM_PROTOCOL_CHUNK_HEADER_LEN + COMM_PROTOCOL_CHUNK_RGB_BYTES)
#define COMM_PROTOCOL_COMMIT_LEN            2U
#define COMM_PROTOCOL_STATUS_FLAG_FAULT      0x0001U
#define COMM_PROTOCOL_STATUS_FLAG_PENDING    0x0002U
#define COMM_PROTOCOL_STATUS_FLAG_HOST       0x0004U
#define COMM_PROTOCOL_STATUS_FLAG_TXN        0x0008U

#if (APP_ROLE_ID < 1U) || (APP_ROLE_ID > 20U)
#error "APP_ROLE_ID must be in the 1..20 physical board ID range"
#endif

typedef enum
{
  /* Parser consumes one byte at a time from the shared transport ring. */
  COMM_PARSE_WAIT_SYNC0 = 0U,
  COMM_PARSE_WAIT_SYNC1 = 1U,
  COMM_PARSE_READ_HEADER = 2U,
  COMM_PARSE_READ_PAYLOAD = 3U,
  COMM_PARSE_READ_CRC0 = 4U,
  COMM_PARSE_READ_CRC1 = 5U
} CommProtocolParserState_t;

typedef struct
{
  /* Active frame metadata is valid between FRAME_BEGIN and FRAME_COMMIT. */
  uint8_t active;
  uint8_t severe_error;
  uint8_t chunk_count;
  uint8_t flags;
  uint16_t frame_id;
  uint16_t received_mask;
  uint16_t ww_level;
  uint16_t cw_level;
  uint32_t frame_crc32;
} CommProtocolFrameTransaction_t;

volatile uint8_t comm_protocol_watch_parser_state;
volatile uint8_t comm_protocol_watch_host_control_active;
volatile uint8_t comm_protocol_watch_pending_show;
volatile uint8_t comm_protocol_watch_last_error;
volatile uint16_t comm_protocol_watch_frame_id;
volatile uint16_t comm_protocol_watch_received_mask;
volatile uint32_t comm_protocol_watch_uid_hash;
volatile uint32_t comm_protocol_watch_packet_count;
volatile uint32_t comm_protocol_watch_crc_error_count;
volatile uint32_t comm_protocol_watch_parser_error_count;
volatile uint32_t comm_protocol_watch_commit_count;
volatile uint32_t comm_protocol_watch_commit_error_count;
volatile uint32_t comm_protocol_watch_timeout_black_count;
volatile uint32_t comm_protocol_watch_last_valid_packet_ms;
/* Timing probes separate host transfer time from firmware commit latency. */
volatile uint32_t comm_protocol_watch_frame_begin_ms;
volatile uint32_t comm_protocol_watch_last_chunk_ms;
volatile uint32_t comm_protocol_watch_commit_rx_ms;
volatile uint32_t comm_protocol_watch_apply_start_ms;
volatile uint32_t comm_protocol_watch_apply_done_ms;
volatile uint32_t comm_protocol_watch_show_request_ms;
volatile uint32_t comm_protocol_watch_show_start_ms;
volatile uint32_t comm_protocol_watch_commit_rsp_ms;
volatile uint32_t comm_protocol_watch_frame_rx_span_ms;
volatile uint32_t comm_protocol_watch_commit_to_rsp_ms;

/* Packet parser scratch buffers; payload is bounded by COMM_PROTOCOL_MAX_PAYLOAD. */
static CommProtocolParserState_t comm_protocol_parser_state;
static uint8_t comm_protocol_header[COMM_PROTOCOL_HEADER_SIZE];
static uint8_t comm_protocol_payload[COMM_PROTOCOL_MAX_PAYLOAD];
static uint8_t comm_protocol_header_index;
static uint16_t comm_protocol_payload_index;
static uint16_t comm_protocol_payload_len;
static uint16_t comm_protocol_rx_crc;
static uint8_t comm_protocol_packet_type;
static uint16_t comm_protocol_packet_seq;

/* Staging frame preserves atomic commit semantics before touching output frame. */
static uint8_t comm_protocol_staging_frame[WS2812_BSR_LANES][COMM_PROTOCOL_LOGICAL_LEDS_PER_LANE][3];
static CommProtocolFrameTransaction_t comm_protocol_transaction;
static uint8_t comm_protocol_host_control_active;
static uint8_t comm_protocol_pending_show;
static uint8_t comm_protocol_timeout_black_sent;
static uint8_t comm_protocol_last_error;
static uint32_t comm_protocol_uid_hash;
static uint32_t comm_protocol_packet_count;
static uint32_t comm_protocol_crc_error_count;
static uint32_t comm_protocol_parser_error_count;
static uint32_t comm_protocol_commit_count;
static uint32_t comm_protocol_commit_error_count;
static uint32_t comm_protocol_timeout_black_count;
static uint32_t comm_protocol_last_valid_packet_ms;

static void CommProtocol_ResetParser(void);
static void CommProtocol_ResetTransaction(void);
static void CommProtocol_ParseByte(uint8_t byte, uint32_t now_ms);
static void CommProtocol_HeaderComplete(uint32_t now_ms);
static void CommProtocol_PacketComplete(uint32_t now_ms);
static void CommProtocol_DispatchPacket(uint32_t now_ms);
static void CommProtocol_HandleFrameBegin(void);
static void CommProtocol_HandleFrameChunk(void);
static void CommProtocol_HandleFrameCommit(void);
static void CommProtocol_HandleAllBlack(void);
static void CommProtocol_ApplyCommittedFrame(void);
static void CommProtocol_RequestShow(void);
static void CommProtocol_ForceBlackOutput(void);
static void CommProtocol_SendHelloResponse(uint16_t seq);
static void CommProtocol_SendStatusResponse(uint16_t seq);
static void CommProtocol_SendCommitResponse(uint16_t seq, uint16_t frame_id, uint8_t status);
static void CommProtocol_SendError(uint16_t seq, uint8_t code, uint16_t detail);
static void CommProtocol_SendPacket(uint8_t type, uint16_t seq, uint8_t flags, const uint8_t *payload, uint16_t payload_len);
static uint16_t CommProtocol_CalcCrc(const uint8_t *data, uint16_t len);
static uint16_t CommProtocol_Crc16Update(uint16_t crc, uint8_t data);
static uint16_t CommProtocol_ReadU16(const uint8_t *data);
static uint32_t CommProtocol_ReadU32(const uint8_t *data);
static void CommProtocol_WriteU16(uint8_t *data, uint16_t value);
static void CommProtocol_WriteU32(uint8_t *data, uint32_t value);
static uint32_t CommProtocol_CalcUidHash(void);
static void CommProtocol_RecordError(uint8_t code);
static void CommProtocol_UpdateWatch(void);

void CommProtocol_Init(void)
{
  comm_protocol_uid_hash = CommProtocol_CalcUidHash();
  comm_protocol_host_control_active = 0U;
  comm_protocol_pending_show = 0U;
  comm_protocol_timeout_black_sent = 0U;
  comm_protocol_last_error = COMM_PROTO_OK;
  comm_protocol_packet_count = 0U;
  comm_protocol_crc_error_count = 0U;
  comm_protocol_parser_error_count = 0U;
  comm_protocol_commit_count = 0U;
  comm_protocol_commit_error_count = 0U;
  comm_protocol_timeout_black_count = 0U;
  comm_protocol_last_valid_packet_ms = 0U;
  memset(comm_protocol_staging_frame, 0, sizeof(comm_protocol_staging_frame));
  CommProtocol_ResetParser();
  CommProtocol_ResetTransaction();
  CommProtocol_UpdateWatch();
}

void CommProtocol_Poll(uint32_t now_ms)
{
  uint8_t byte;

  /* Transport errors invalidate the current packet and uncommitted frame. */
  if (CommTransport_ConsumeLinkChanged() != 0U)
  {
    CommProtocol_ResetParser();
    CommProtocol_ResetTransaction();
  }

  if (CommTransport_ConsumeOverflow() != 0U)
  {
    CommProtocol_ResetParser();
    CommProtocol_ResetTransaction();
    CommProtocol_RecordError(COMM_PROTO_ERR_RX_OVERFLOW);
    CommProtocol_SendError(comm_protocol_packet_seq, COMM_PROTO_ERR_RX_OVERFLOW, 0U);
  }

  while (CommTransport_Read(&byte, 1U) == 1U)
  {
    CommProtocol_ParseByte(byte, now_ms);
  }

  CommProtocol_UpdateWatch();
}

void CommProtocol_OutputPoll(uint32_t now_ms)
{
  if (comm_protocol_host_control_active == 0U)
  {
    return;
  }

  WS2812_BSR_Poll();

  if (CurrentProtect_IsFaultActive() != 0U)
  {
    return;
  }

  /* Long host silence forces a black output after host control has started. */
  if ((comm_protocol_timeout_black_sent == 0U) &&
      ((now_ms - comm_protocol_last_valid_packet_ms) >= APP_COMM_LONG_TIMEOUT_MS))
  {
    CommProtocol_ForceBlackOutput();
    comm_protocol_timeout_black_sent = 1U;
    comm_protocol_timeout_black_count++;
    CommProtocol_UpdateWatch();
    return;
  }

  if ((comm_protocol_pending_show != 0U) && (WS2812_BSR_IsBusy() == 0U))
  {
    comm_protocol_pending_show = 0U;
    comm_protocol_watch_show_start_ms = now_ms;
    WS2812_BSR_Show();
  }

  CommProtocol_UpdateWatch();
}

uint8_t CommProtocol_HasOutputControl(void)
{
  return comm_protocol_host_control_active;
}

void CommProtocol_Reset(void)
{
  CommProtocol_ResetParser();
  CommProtocol_ResetTransaction();
  comm_protocol_host_control_active = 0U;
  comm_protocol_pending_show = 0U;
  comm_protocol_timeout_black_sent = 0U;
  CommProtocol_UpdateWatch();
}

static void CommProtocol_ResetParser(void)
{
  comm_protocol_parser_state = COMM_PARSE_WAIT_SYNC0;
  comm_protocol_header_index = 0U;
  comm_protocol_payload_index = 0U;
  comm_protocol_payload_len = 0U;
  comm_protocol_rx_crc = 0U;
  comm_protocol_packet_type = 0U;
  comm_protocol_packet_seq = 0U;
}

static void CommProtocol_ResetTransaction(void)
{
  comm_protocol_transaction.active = 0U;
  comm_protocol_transaction.severe_error = 0U;
  comm_protocol_transaction.chunk_count = COMM_PROTOCOL_FRAME_CHUNKS;
  comm_protocol_transaction.flags = 0U;
  comm_protocol_transaction.frame_id = 0U;
  comm_protocol_transaction.received_mask = 0U;
  comm_protocol_transaction.ww_level = 0U;
  comm_protocol_transaction.cw_level = 0U;
  comm_protocol_transaction.frame_crc32 = 0U;
}

static void CommProtocol_ParseByte(uint8_t byte, uint32_t now_ms)
{
  /* Byte-stream framing: sync, fixed header, payload, then little-endian CRC. */
  switch (comm_protocol_parser_state)
  {
    case COMM_PARSE_WAIT_SYNC0:
      if (byte == COMM_PROTOCOL_SYNC0)
      {
        comm_protocol_parser_state = COMM_PARSE_WAIT_SYNC1;
      }
      break;

    case COMM_PARSE_WAIT_SYNC1:
      if (byte == COMM_PROTOCOL_SYNC1)
      {
        comm_protocol_header_index = 0U;
        comm_protocol_parser_state = COMM_PARSE_READ_HEADER;
      }
      else if (byte != COMM_PROTOCOL_SYNC0)
      {
        comm_protocol_parser_state = COMM_PARSE_WAIT_SYNC0;
      }
      break;

    case COMM_PARSE_READ_HEADER:
      comm_protocol_header[comm_protocol_header_index] = byte;
      comm_protocol_header_index++;
      if (comm_protocol_header_index >= COMM_PROTOCOL_HEADER_SIZE)
      {
        CommProtocol_HeaderComplete(now_ms);
      }
      break;

    case COMM_PARSE_READ_PAYLOAD:
      comm_protocol_payload[comm_protocol_payload_index] = byte;
      comm_protocol_payload_index++;
      if (comm_protocol_payload_index >= comm_protocol_payload_len)
      {
        comm_protocol_parser_state = COMM_PARSE_READ_CRC0;
      }
      break;

    case COMM_PARSE_READ_CRC0:
      comm_protocol_rx_crc = byte;
      comm_protocol_parser_state = COMM_PARSE_READ_CRC1;
      break;

    case COMM_PARSE_READ_CRC1:
      comm_protocol_rx_crc |= (uint16_t)((uint16_t)byte << 8U);
      CommProtocol_PacketComplete(now_ms);
      break;

    default:
      CommProtocol_ResetParser();
      break;
  }
}

static void CommProtocol_HeaderComplete(uint32_t now_ms)
{
  (void)now_ms;

  /* Header gives type, sequence, payload length, and flags. */
  if (comm_protocol_header[0] != APP_COMM_PROTOCOL_VERSION)
  {
    CommProtocol_RecordError(COMM_PROTO_ERR_BAD_VERSION);
    CommProtocol_SendError(0U, COMM_PROTO_ERR_BAD_VERSION, comm_protocol_header[0]);
    CommProtocol_ResetParser();
    return;
  }

  comm_protocol_packet_type = comm_protocol_header[1];
  comm_protocol_packet_seq = CommProtocol_ReadU16(&comm_protocol_header[2]);
  comm_protocol_payload_len = CommProtocol_ReadU16(&comm_protocol_header[4]);
  comm_protocol_payload_index = 0U;

  if (comm_protocol_payload_len > COMM_PROTOCOL_MAX_PAYLOAD)
  {
    CommProtocol_RecordError(COMM_PROTO_ERR_BAD_LENGTH);
    CommProtocol_SendError(comm_protocol_packet_seq, COMM_PROTO_ERR_BAD_LENGTH, comm_protocol_payload_len);
    CommProtocol_ResetParser();
    return;
  }

  if (comm_protocol_payload_len == 0U)
  {
    comm_protocol_parser_state = COMM_PARSE_READ_CRC0;
  }
  else
  {
    comm_protocol_parser_state = COMM_PARSE_READ_PAYLOAD;
  }
}

static void CommProtocol_PacketComplete(uint32_t now_ms)
{
  uint16_t calc_crc;
  uint16_t index;

  /* CRC covers version..payload, excluding the two sync bytes. */
  calc_crc = CommProtocol_CalcCrc(comm_protocol_header, COMM_PROTOCOL_HEADER_SIZE);
  if (comm_protocol_payload_len > 0U)
  {
    for (index = 0U; index < comm_protocol_payload_len; index++)
    {
      calc_crc = CommProtocol_Crc16Update(calc_crc, comm_protocol_payload[index]);
    }
  }

  if (calc_crc != comm_protocol_rx_crc)
  {
    comm_protocol_crc_error_count++;
    CommProtocol_RecordError(COMM_PROTO_ERR_BAD_CRC);
    CommProtocol_SendError(comm_protocol_packet_seq, COMM_PROTO_ERR_BAD_CRC, comm_protocol_packet_type);
    CommProtocol_ResetParser();
    return;
  }

  comm_protocol_packet_count++;
  comm_protocol_last_valid_packet_ms = now_ms;
  comm_protocol_timeout_black_sent = 0U;
  comm_protocol_host_control_active = 1U;

  /* Track one complete host-controlled frame from BEGIN to COMMIT response. */
  if (comm_protocol_packet_type == COMM_MSG_FRAME_BEGIN)
  {
    comm_protocol_watch_frame_begin_ms = now_ms;
    comm_protocol_watch_last_chunk_ms = 0U;
    comm_protocol_watch_commit_rx_ms = 0U;
    comm_protocol_watch_apply_start_ms = 0U;
    comm_protocol_watch_apply_done_ms = 0U;
    comm_protocol_watch_show_request_ms = 0U;
    comm_protocol_watch_show_start_ms = 0U;
    comm_protocol_watch_commit_rsp_ms = 0U;
    comm_protocol_watch_frame_rx_span_ms = 0U;
    comm_protocol_watch_commit_to_rsp_ms = 0U;
  }
  else if (comm_protocol_packet_type == COMM_MSG_FRAME_RGB_CHUNK)
  {
    comm_protocol_watch_last_chunk_ms = now_ms;
  }
  else if (comm_protocol_packet_type == COMM_MSG_FRAME_COMMIT)
  {
    comm_protocol_watch_commit_rx_ms = now_ms;
    comm_protocol_watch_frame_rx_span_ms = now_ms - comm_protocol_watch_frame_begin_ms;
  }

  CommProtocol_DispatchPacket(now_ms);
  CommProtocol_ResetParser();
}

static void CommProtocol_DispatchPacket(uint32_t now_ms)
{
  (void)now_ms;

  /* Only complete CRC-valid packets reach command dispatch. */
  switch (comm_protocol_packet_type)
  {
    case COMM_MSG_HELLO_REQ:
      CommProtocol_SendHelloResponse(comm_protocol_packet_seq);
      break;

    case COMM_MSG_STATUS_REQ:
      CommProtocol_SendStatusResponse(comm_protocol_packet_seq);
      break;

    case COMM_MSG_FRAME_BEGIN:
      CommProtocol_HandleFrameBegin();
      break;

    case COMM_MSG_FRAME_RGB_CHUNK:
      CommProtocol_HandleFrameChunk();
      break;

    case COMM_MSG_FRAME_COMMIT:
      CommProtocol_HandleFrameCommit();
      break;

    case COMM_MSG_ALL_BLACK:
      CommProtocol_HandleAllBlack();
      break;

    default:
      CommProtocol_RecordError(COMM_PROTO_ERR_BAD_TYPE);
      CommProtocol_SendError(comm_protocol_packet_seq, COMM_PROTO_ERR_BAD_TYPE, comm_protocol_packet_type);
      break;
  }
}

static void CommProtocol_HandleFrameBegin(void)
{
  uint16_t ww_level;
  uint16_t cw_level;

  /* Begin clears staging and records white levels for atomic commit. */
  if (comm_protocol_payload_len != COMM_PROTOCOL_FRAME_BEGIN_LEN)
  {
    CommProtocol_RecordError(COMM_PROTO_ERR_BAD_LENGTH);
    CommProtocol_SendError(comm_protocol_packet_seq, COMM_PROTO_ERR_BAD_LENGTH, comm_protocol_payload_len);
    return;
  }

  ww_level = CommProtocol_ReadU16(&comm_protocol_payload[4]);
  cw_level = CommProtocol_ReadU16(&comm_protocol_payload[6]);

  if ((comm_protocol_payload[2] != COMM_PROTOCOL_FRAME_CHUNKS) ||
      (ww_level > APP_WHITE_PWM_MAX_LEVEL) ||
      (cw_level > APP_WHITE_PWM_MAX_LEVEL))
  {
    CommProtocol_RecordError(COMM_PROTO_ERR_BAD_LENGTH);
    CommProtocol_SendError(comm_protocol_packet_seq, COMM_PROTO_ERR_BAD_LENGTH, comm_protocol_payload[2]);
    return;
  }

  memset(comm_protocol_staging_frame, 0, sizeof(comm_protocol_staging_frame));
  comm_protocol_transaction.active = 1U;
  comm_protocol_transaction.severe_error = 0U;
  comm_protocol_transaction.frame_id = CommProtocol_ReadU16(&comm_protocol_payload[0]);
  comm_protocol_transaction.chunk_count = comm_protocol_payload[2];
  comm_protocol_transaction.flags = comm_protocol_payload[3];
  comm_protocol_transaction.ww_level = ww_level;
  comm_protocol_transaction.cw_level = cw_level;
  comm_protocol_transaction.frame_crc32 = CommProtocol_ReadU32(&comm_protocol_payload[8]);
  comm_protocol_transaction.received_mask = 0U;
}

static void CommProtocol_HandleFrameChunk(void)
{
  uint16_t frame_id;
  uint16_t data_len;
  uint8_t chunk_index;
  uint8_t lane_offset;
  uint8_t lane;
  uint16_t pixel;
  const uint8_t *src;

  /* Each RGB chunk fills two complete logical lanes. */
  if (comm_protocol_payload_len != COMM_PROTOCOL_CHUNK_PAYLOAD_LEN)
  {
    comm_protocol_transaction.severe_error = 1U;
    CommProtocol_RecordError(COMM_PROTO_ERR_BAD_LENGTH);
    CommProtocol_SendError(comm_protocol_packet_seq, COMM_PROTO_ERR_BAD_LENGTH, comm_protocol_payload_len);
    return;
  }

  if (comm_protocol_transaction.active == 0U)
  {
    CommProtocol_RecordError(COMM_PROTO_ERR_BAD_STATE);
    CommProtocol_SendError(comm_protocol_packet_seq, COMM_PROTO_ERR_BAD_STATE, 0U);
    return;
  }

  frame_id = CommProtocol_ReadU16(&comm_protocol_payload[0]);
  chunk_index = comm_protocol_payload[2];
  data_len = CommProtocol_ReadU16(&comm_protocol_payload[3]);

  if (frame_id != comm_protocol_transaction.frame_id)
  {
    CommProtocol_RecordError(COMM_PROTO_ERR_BAD_FRAME_ID);
    CommProtocol_SendError(comm_protocol_packet_seq, COMM_PROTO_ERR_BAD_FRAME_ID, frame_id);
    return;
  }

  if ((chunk_index >= COMM_PROTOCOL_FRAME_CHUNKS) ||
      (data_len != COMM_PROTOCOL_CHUNK_RGB_BYTES))
  {
    comm_protocol_transaction.severe_error = 1U;
    CommProtocol_RecordError(COMM_PROTO_ERR_BAD_CHUNK);
    CommProtocol_SendError(comm_protocol_packet_seq, COMM_PROTO_ERR_BAD_CHUNK, chunk_index);
    return;
  }

  src = &comm_protocol_payload[COMM_PROTOCOL_CHUNK_HEADER_LEN];

  for (lane_offset = 0U; lane_offset < COMM_PROTOCOL_LANES_PER_CHUNK; lane_offset++)
  {
    lane = (uint8_t)((chunk_index * COMM_PROTOCOL_LANES_PER_CHUNK) + lane_offset);

    for (pixel = 0U; pixel < COMM_PROTOCOL_LOGICAL_LEDS_PER_LANE; pixel++)
    {
      uint16_t src_pixel = (uint16_t)(((uint16_t)lane_offset * COMM_PROTOCOL_LOGICAL_LEDS_PER_LANE) + pixel);
      uint16_t src_offset = (uint16_t)(src_pixel * 3U);

      comm_protocol_staging_frame[lane][pixel][0] = src[src_offset];
      comm_protocol_staging_frame[lane][pixel][1] = src[(uint16_t)(src_offset + 1U)];
      comm_protocol_staging_frame[lane][pixel][2] = src[(uint16_t)(src_offset + 2U)];
    }
  }

  comm_protocol_transaction.received_mask |= (uint16_t)(1UL << chunk_index);
}

static void CommProtocol_HandleFrameCommit(void)
{
  uint16_t frame_id;
  uint8_t status = COMM_PROTO_OK;

  /* Commit validates completeness and fault state before applying outputs. */
  if (comm_protocol_payload_len != COMM_PROTOCOL_COMMIT_LEN)
  {
    status = COMM_PROTO_ERR_BAD_LENGTH;
  }
  else if (comm_protocol_transaction.active == 0U)
  {
    status = COMM_PROTO_ERR_BAD_STATE;
  }
  else
  {
    frame_id = CommProtocol_ReadU16(&comm_protocol_payload[0]);

    if (frame_id != comm_protocol_transaction.frame_id)
    {
      status = COMM_PROTO_ERR_BAD_FRAME_ID;
    }
    else if (comm_protocol_transaction.severe_error != 0U)
    {
      status = COMM_PROTO_ERR_BAD_STATE;
    }
    else if (comm_protocol_transaction.received_mask != COMM_PROTOCOL_FRAME_RECEIVED_MASK)
    {
      status = COMM_PROTO_ERR_INCOMPLETE_FRAME;
    }
    else if (CurrentProtect_IsFaultActive() != 0U)
    {
      status = COMM_PROTO_ERR_FAULT_ACTIVE;
    }
  }

  if (status == COMM_PROTO_OK)
  {
    CommProtocol_ApplyCommittedFrame();
    comm_protocol_commit_count++;
    comm_protocol_transaction.active = 0U;
  }
  else
  {
    CommProtocol_RecordError(status);
    comm_protocol_commit_error_count++;
  }

  CommProtocol_SendCommitResponse(comm_protocol_packet_seq,
                                  comm_protocol_transaction.frame_id,
                                  status);
  comm_protocol_watch_commit_rsp_ms = HAL_GetTick();
  comm_protocol_watch_commit_to_rsp_ms = comm_protocol_watch_commit_rsp_ms - comm_protocol_watch_commit_rx_ms;
}

static void CommProtocol_HandleAllBlack(void)
{
  CommProtocol_ResetTransaction();
  CommProtocol_ForceBlackOutput();
  CommProtocol_SendStatusResponse(comm_protocol_packet_seq);
}

static void CommProtocol_ApplyCommittedFrame(void)
{
  uint8_t lane;
  uint16_t pixel;
  uint16_t physical_pixel;

  comm_protocol_watch_apply_start_ms = HAL_GetTick();

  /* Expand 48 logical pixels to 96 physical LEDs as paired same-color pixels. */
  for (lane = 0U; lane < WS2812_BSR_LANES; lane++)
  {
    for (pixel = 0U; pixel < COMM_PROTOCOL_LOGICAL_LEDS_PER_LANE; pixel++)
    {
      physical_pixel = (uint16_t)(pixel * 2U);
      WS2812_BSR_SetPixel(lane,
                          physical_pixel,
                          comm_protocol_staging_frame[lane][pixel][0],
                          comm_protocol_staging_frame[lane][pixel][1],
                          comm_protocol_staging_frame[lane][pixel][2]);
      WS2812_BSR_SetPixel(lane,
                          (uint16_t)(physical_pixel + 1U),
                          comm_protocol_staging_frame[lane][pixel][0],
                          comm_protocol_staging_frame[lane][pixel][1],
                          comm_protocol_staging_frame[lane][pixel][2]);
    }
  }

  WhitePwm_SetBoth(comm_protocol_transaction.ww_level, comm_protocol_transaction.cw_level);
  CommProtocol_RequestShow();
  comm_protocol_watch_apply_done_ms = HAL_GetTick();
}

static void CommProtocol_RequestShow(void)
{
  comm_protocol_watch_show_request_ms = HAL_GetTick();

  if (WS2812_BSR_IsBusy() != 0U)
  {
    comm_protocol_pending_show = 1U;
    return;
  }

  comm_protocol_pending_show = 0U;
  comm_protocol_watch_show_start_ms = HAL_GetTick();
  WS2812_BSR_Show();
}

static void CommProtocol_ForceBlackOutput(void)
{
  comm_protocol_pending_show = 0U;
  WhitePwm_Off();
  WS2812_BSR_ForceBlack();
}

static void CommProtocol_SendHelloResponse(uint16_t seq)
{
  uint8_t payload[18];

  /* HELLO tells the host board identity, geometry, and protocol limits. */
  CommProtocol_WriteU32(&payload[0], comm_protocol_uid_hash);
  payload[4] = (uint8_t)APP_ROLE_ID;
  payload[5] = WS2812_BSR_LANES;
  CommProtocol_WriteU16(&payload[6], COMM_PROTOCOL_LOGICAL_LEDS_PER_LANE);
  CommProtocol_WriteU16(&payload[8], COMM_PROTOCOL_CHUNK_RGB_BYTES);
  payload[10] = COMM_PROTOCOL_FRAME_CHUNKS;
  payload[11] = APP_COMM_PROTOCOL_VERSION;
  CommProtocol_WriteU16(&payload[12], COMM_PROTOCOL_MAX_PAYLOAD);
  CommProtocol_WriteU16(&payload[14], APP_COMM_LONG_TIMEOUT_MS);
  CommProtocol_WriteU16(&payload[16], APP_WHITE_PWM_MAX_LEVEL);

  CommProtocol_SendPacket(COMM_MSG_HELLO_RSP, seq, 0U, payload, sizeof(payload));
}

static void CommProtocol_SendStatusResponse(uint16_t seq)
{
  uint8_t payload[36];
  uint16_t flags = 0U;
  uint16_t offset = 0U;

  /* STATUS is compact enough to fit the 128-byte transport TX buffer. */
  if (CurrentProtect_IsFaultActive() != 0U)
  {
    flags |= COMM_PROTOCOL_STATUS_FLAG_FAULT;
  }
  if (comm_protocol_pending_show != 0U)
  {
    flags |= COMM_PROTOCOL_STATUS_FLAG_PENDING;
  }
  if (comm_protocol_host_control_active != 0U)
  {
    flags |= COMM_PROTOCOL_STATUS_FLAG_HOST;
  }
  if (comm_protocol_transaction.active != 0U)
  {
    flags |= COMM_PROTOCOL_STATUS_FLAG_TXN;
  }

  CommProtocol_WriteU16(&payload[offset], flags);
  offset = (uint16_t)(offset + 2U);
  payload[offset] = (uint8_t)CommTransport_GetActiveLink();
  offset++;
  payload[offset] = RemoteInput_GetStableBits();
  offset++;
  CommProtocol_WriteU16(&payload[offset], CommTransport_GetRxUsed());
  offset = (uint16_t)(offset + 2U);
  CommProtocol_WriteU16(&payload[offset], comm_protocol_transaction.frame_id);
  offset = (uint16_t)(offset + 2U);
  CommProtocol_WriteU16(&payload[offset], comm_protocol_transaction.received_mask);
  offset = (uint16_t)(offset + 2U);
  CommProtocol_WriteU32(&payload[offset], comm_protocol_packet_count);
  offset = (uint16_t)(offset + 4U);
  CommProtocol_WriteU32(&payload[offset], comm_protocol_parser_error_count);
  offset = (uint16_t)(offset + 4U);
  CommProtocol_WriteU32(&payload[offset], CurrentProtect_GetCurrentMa());
  offset = (uint16_t)(offset + 4U);
  CommProtocol_WriteU16(&payload[offset], WhitePwm_GetWW());
  offset = (uint16_t)(offset + 2U);
  CommProtocol_WriteU16(&payload[offset], WhitePwm_GetCW());
  offset = (uint16_t)(offset + 2U);
  CommProtocol_WriteU32(&payload[offset], comm_protocol_uid_hash);
  offset = (uint16_t)(offset + 4U);
  CommProtocol_WriteU32(&payload[offset], comm_protocol_commit_count);
  offset = (uint16_t)(offset + 4U);

  CommProtocol_SendPacket(COMM_MSG_STATUS_RSP, seq, 0U, payload, offset);
}

static void CommProtocol_SendCommitResponse(uint16_t seq, uint16_t frame_id, uint8_t status)
{
  uint8_t payload[5];

  CommProtocol_WriteU16(&payload[0], frame_id);
  payload[2] = status;
  CommProtocol_WriteU16(&payload[3], comm_protocol_transaction.received_mask);

  CommProtocol_SendPacket(COMM_MSG_FRAME_COMMIT, seq, 0U, payload, sizeof(payload));
}

static void CommProtocol_SendError(uint16_t seq, uint8_t code, uint16_t detail)
{
  uint8_t payload[3];

  payload[0] = code;
  CommProtocol_WriteU16(&payload[1], detail);
  CommProtocol_SendPacket(COMM_MSG_ERROR_RSP, seq, 0U, payload, sizeof(payload));
}

static void CommProtocol_SendPacket(uint8_t type, uint16_t seq, uint8_t flags, const uint8_t *payload, uint16_t payload_len)
{
  uint8_t packet[COMM_TX_BUFFER_SIZE];
  uint16_t crc;
  uint16_t offset = 0U;
  uint16_t total_len;
  uint16_t index;

  /* Build one complete framed response packet in a stack-local buffer. */
  total_len = (uint16_t)(2U + COMM_PROTOCOL_HEADER_SIZE + payload_len + COMM_PROTOCOL_CRC_SIZE);
  if ((payload_len > COMM_PROTOCOL_MAX_PAYLOAD) || (total_len > COMM_TX_BUFFER_SIZE))
  {
    return;
  }

  packet[offset++] = COMM_PROTOCOL_SYNC0;
  packet[offset++] = COMM_PROTOCOL_SYNC1;
  packet[offset++] = APP_COMM_PROTOCOL_VERSION;
  packet[offset++] = type;
  CommProtocol_WriteU16(&packet[offset], seq);
  offset = (uint16_t)(offset + 2U);
  CommProtocol_WriteU16(&packet[offset], payload_len);
  offset = (uint16_t)(offset + 2U);
  packet[offset++] = flags;

  for (index = 0U; index < payload_len; index++)
  {
    packet[offset] = payload[index];
    offset++;
  }

  crc = 0xFFFFU;
  for (index = 2U; index < offset; index++)
  {
    crc = CommProtocol_Crc16Update(crc, packet[index]);
  }

  CommProtocol_WriteU16(&packet[offset], crc);
  offset = (uint16_t)(offset + 2U);

  (void)CommTransport_Send(packet, offset);
}

static uint16_t CommProtocol_CalcCrc(const uint8_t *data, uint16_t len)
{
  uint16_t crc = 0xFFFFU;
  uint16_t index;

  for (index = 0U; index < len; index++)
  {
    crc = CommProtocol_Crc16Update(crc, data[index]);
  }

  return crc;
}

static uint16_t CommProtocol_Crc16Update(uint16_t crc, uint8_t data)
{
  uint8_t bit;

  crc ^= (uint16_t)((uint16_t)data << 8U);
  for (bit = 0U; bit < 8U; bit++)
  {
    if ((crc & 0x8000U) != 0U)
    {
      crc = (uint16_t)((crc << 1U) ^ 0x1021U);
    }
    else
    {
      crc = (uint16_t)(crc << 1U);
    }
  }

  return crc;
}

static uint16_t CommProtocol_ReadU16(const uint8_t *data)
{
  return (uint16_t)((uint16_t)data[0] | ((uint16_t)data[1] << 8U));
}

static uint32_t CommProtocol_ReadU32(const uint8_t *data)
{
  return (uint32_t)data[0] |
         ((uint32_t)data[1] << 8U) |
         ((uint32_t)data[2] << 16U) |
         ((uint32_t)data[3] << 24U);
}

static void CommProtocol_WriteU16(uint8_t *data, uint16_t value)
{
  data[0] = (uint8_t)(value & 0xFFU);
  data[1] = (uint8_t)((value >> 8U) & 0xFFU);
}

static void CommProtocol_WriteU32(uint8_t *data, uint32_t value)
{
  data[0] = (uint8_t)(value & 0xFFU);
  data[1] = (uint8_t)((value >> 8U) & 0xFFU);
  data[2] = (uint8_t)((value >> 16U) & 0xFFU);
  data[3] = (uint8_t)((value >> 24U) & 0xFFU);
}

static uint32_t CommProtocol_CalcUidHash(void)
{
  const uint32_t *uid = (const uint32_t *)COMM_PROTOCOL_UID_BASE_ADDRESS;
  uint32_t hash = 2166136261UL;
  uint8_t word_index;

  for (word_index = 0U; word_index < COMM_PROTOCOL_UID_WORDS; word_index++)
  {
    uint32_t value = uid[word_index];
    uint8_t byte_index;

    for (byte_index = 0U; byte_index < 4U; byte_index++)
    {
      hash ^= (uint8_t)(value & 0xFFU);
      hash *= 16777619UL;
      value >>= 8U;
    }
  }

  if (hash == 0U)
  {
    hash = 1U;
  }

  return hash;
}

static void CommProtocol_RecordError(uint8_t code)
{
  comm_protocol_last_error = code;
  comm_protocol_parser_error_count++;
}

static void CommProtocol_UpdateWatch(void)
{
  comm_protocol_watch_parser_state = (uint8_t)comm_protocol_parser_state;
  comm_protocol_watch_host_control_active = comm_protocol_host_control_active;
  comm_protocol_watch_pending_show = comm_protocol_pending_show;
  comm_protocol_watch_last_error = comm_protocol_last_error;
  comm_protocol_watch_frame_id = comm_protocol_transaction.frame_id;
  comm_protocol_watch_received_mask = comm_protocol_transaction.received_mask;
  comm_protocol_watch_uid_hash = comm_protocol_uid_hash;
  comm_protocol_watch_packet_count = comm_protocol_packet_count;
  comm_protocol_watch_crc_error_count = comm_protocol_crc_error_count;
  comm_protocol_watch_parser_error_count = comm_protocol_parser_error_count;
  comm_protocol_watch_commit_count = comm_protocol_commit_count;
  comm_protocol_watch_commit_error_count = comm_protocol_commit_error_count;
  comm_protocol_watch_timeout_black_count = comm_protocol_timeout_black_count;
  comm_protocol_watch_last_valid_packet_ms = comm_protocol_last_valid_packet_ms;
}
