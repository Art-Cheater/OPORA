#ifndef CONFIG_H
#define CONFIG_H

/*
 * IPP TCP v2.1 CLEAN STABLE
 * Test board: ipp-001
 *
 * IMPORTANT:
 * This is the pilot secret requested for the current test board.
 * Rotate it after stable commissioning.
 */
#define DEVICE_ID_LITERAL      "ipp-001"
#define DEVICE_SECRET_LITERAL  "Artwer"

#define TCP_HOST_LITERAL       "tcp.zheleznogame.ru"
#define TCP_PORT_LITERAL       "5000"

#define GPRS_APN_LITERAL       "internet"
#define GPRS_USER_LITERAL      "gdata"
#define GPRS_PASS_LITERAL      "gdata"

/* Production token_urlsafe(32) nonce is ~43 chars. */
#define NONCE_MAX              64

/*
 * Realtime policy:
 * - STATE immediately after auth
 * - STATE immediately after SET / SETALL
 * - STATE immediately after U2/U3 change
 * - full heartbeat snapshot every 2 seconds
 *
 * 500 ms flooded BGS2T with SISW traffic and could delay control commands.
 */
#define STATE_PERIOD_MS        2000U
#define INPUT_DEBOUNCE_MS      5U

#define AUTH_DIAG_TIMEOUT_MS   30000U
#define READ_POLL_MS           20U
#define SISR_WAIT_MAX_MS       500U

#define SISW_READY_TIMEOUT_MS  650U
#define SISW_READY_RETRIES     8U
#define SISW_RETRY_DELAY_MS    60U
#define SISW_FINISH_TIMEOUT_MS 650U

#endif
