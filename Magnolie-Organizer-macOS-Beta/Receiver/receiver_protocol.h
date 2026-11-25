/* Magnolie's private UxPlay host contract. GPL-3.0-or-later; Refs #721. */
#ifndef MAGNOLIE_RECEIVER_PROTOCOL_H
#define MAGNOLIE_RECEIVER_PROTOCOL_H

#ifdef __cplusplus
extern "C" {
#endif

/* Before GStreamer/threads: stdout becomes bounded JSONL, normal logs go to
 * stderr. stdin must be an owned pipe; EOF stops this process, never a peer. */
int magnolie_receiver_initialize(void);
void magnolie_receiver_ready(void);
void magnolie_receiver_pin(const char *code);
void magnolie_receiver_connection_opened(void);
void magnolie_receiver_connection_closed(void);
void magnolie_receiver_media(int video, const void *stream);
void magnolie_receiver_stream_ended(int video, const void *stream);
void magnolie_receiver_error(const char *code);

#ifdef __cplusplus
}
#endif
#endif
