# O-1 evidence - api.mospi.gov.in

Run at: 2026-09-07T20:54:20.229212+00:00
User-Agent: `APIx-Research/0.1 (+https://github.com/sujal128005/apix; MoSPI SIH 2026 PS 26056)`
TLS rung that completed a handshake: **NONE**
HTTP status from the first endpoint: **no response**

Certificate verification was enabled on every attempt (ADR-016).
No credentials were used.

## Attempts

```json
[
  {
    "url": "https://api.mospi.gov.in/api/cpi/getCpiBaseYear",
    "tls_mode": "STANDARD",
    "authenticated": false,
    "ok": false,
    "error_type": "transport",
    "error": "URLError(SSLError(1, '[SSL: UNSAFE_LEGACY_RENEGOTIATION_DISABLED] unsafe legacy renegotiation disabled (_ssl.c:1010)'))"
  },
  {
    "url": "https://api.mospi.gov.in/api/cpi/getCpiBaseYear",
    "tls_mode": "LEGACY",
    "authenticated": false,
    "ok": false,
    "error_type": "transport",
    "error": "URLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1010)'))"
  }
]
```

## robots.txt

```json
{
  "http_status": null,
  "body": null,
  "error": "URLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain (_ssl.c:1010)'))"
}
```

## Conclusions to record

- Bearer token required? Unknown - no HTTP response was received.
- TLS: no rung completed a handshake; see the script output for options.
- robots.txt: see above. Per ADR-019 it does not govern API access, but the record is kept.
