# IRZ / ATM21 / Mercury

Production data path:

```text
Mercury -- RS-485 --> ATM21 -- outbound TCP --> modem-sniffer:5009
                                      web --> modem-sniffer:5010
```

ATM21 is the TCP client. OPORA never opens a production TCP or serial
connection to the meter. `modem-sniffer` owns the accepted socket and exposes
only an internal HTTP control API to Flask workers.

After the `AT$IMEI` identification packet, the gateway registers the live
session by IMEI and persists non-secret ATM21 metadata. `ONLINE` means that
this exact session is currently present in the process-local registry. A
gateway restart or socket disconnect therefore makes the device offline.

Mercury V2 commands use `ATM21SessionTransport`, which implements the
`mercury-base` transport contract over the already accepted socket. Per-session
locking permits one outstanding Mercury request. Identification messages and
the observed `B5 BC BD BE BF` heartbeat are not delivered to the Mercury
parser. A response is accepted only after a valid CRC frame for the configured
RS-485 network address has accumulated.

The meaning of `B5 BC BD BE BF` is not documented. Echo/ACK is disabled by
default and can be enabled for a physical compatibility test with
`ATM21_HEARTBEAT_ACK=1`.

## Diagnostic request

For network address `1`, the safe serial/date request produced by
`mercury-base` is:

```text
01 08 00 27 C0
```

`01` is the RS-485 address, `08 00` is the V2 operation/parameter, and
`27 C0` is the valid Modbus-style CRC emitted by the library. A timeout proves
only that no CRC-valid response for address 1 reached OPORA during the wait.
It does not prove the configured meter address, ATM21 transparent framing,
RS-485 baud/parity/stop bits, or protocol version are correct.

## Physical test

1. Configure ATM21 to connect to OPORA TCP port 5009 and confirm its IMEI is
   `ONLINE` on `/irz`.
2. Verify ATM21 RS-485 mode and the meter's baud, parity, stop bits and network
   address locally.
3. Save that network address in the selected ATM21 card.
4. Run “Проверить Mercury”; confirm the journal and sidecar stdout contain the
   exact TX bytes.
5. Observe all RX during the five-second window. Compare once with heartbeat
   ACK disabled and, only if required by device documentation/known behavior,
   with `ATM21_HEARTBEAT_ACK=1`.
