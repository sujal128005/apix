# O-1 evidence - api.mospi.gov.in

Run at: 2026-09-07T21:00:17.088781+00:00
User-Agent: `APIx-Research/0.1 (+https://github.com/sujal128005/apix; MoSPI SIH 2026 PS 26056)`
TLS rung that completed a handshake: **LEGACY**
HTTP status from the first endpoint: **200**

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
    "ok": true,
    "http_status": 200,
    "content_type": "application/json; charset=utf-8",
    "body_head": "{\"data\":{\"base_year\":[{\"base_year\":\"2010\"},{\"base_year\":\"2012\"},{\"base_year\":\"2024\"}],\"level\":[{\"level\":\"Group\",\"viz\":\"line,hbar,vbar,map\"},{\"level\":\"Item\",\"viz\":\"line,hbar,vbar,map\"}],\"series\":[{\"series\":\"Current\",\"viz\":\"line\"},{\"series\":\"Back\",\"viz\":\"line\"}]},\"msg\":\"Data fetched successfully\",\"statusCode\":true}"
  },
  {
    "url": "https://api.mospi.gov.in/api/cpi/getCpiFilterByLevelAndBaseYear?base_year=2024&level=Item&series_code=Current",
    "tls_mode": "LEGACY",
    "authenticated": false,
    "ok": true,
    "http_status": 200,
    "content_type": "application/json; charset=utf-8",
    "body_head": "{\"data\":[{\"series\":[{\"series\":\"Current\",\"viz\":\"line\"},{\"series\":\"Back\",\"viz\":\"line\"}],\"year\":[{\"year\":2025,\"series\":\"Current\"},{\"year\":2026,\"series\":\"Current\"}],\"state\":[{\"state_code\":1,\"state_name\":\"All India\"},{\"state_code\":2,\"state_name\":\"Andaman And Nicobar Islands\"},{\"state_code\":3,\"state_name\":\"Andhra Pradesh\"},{\"state_code\":4,\"state_name\":\"Arunachal Pradesh\"},{\"state_code\":5,\"state_name\":\"Assam\"},{\"state_code\":6,\"state_name\":\"Bihar\"},{\"state_code\":7,\"state_name\":\"Chandigarh\"},{\"state_code\":8,\"state_name\":\"Chhattisgarh\"},{\"state_code\":9,\"state_name\":\"Goa\"},{\"state_code\":10,\"state_name\":\""
  }
]
```

## robots.txt

```json
{
  "http_status": 200,
  "body": "<!doctype html><html lang=\"en\"><head><meta charset=\"UTF-8\"><title>Ministry of Statistics and Program Implementation | Government Of India</title><link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/3.24.2/swagger-ui.css\"><link rel=\"icon\" href=\"../public/favicon.ico\" type=\"image/x-icon\"><script defer=\"defer\" src=\"/static/js/main.addddd18.js\"></script><link href=\"/static/css/main.a3a48c73.css\" rel=\"stylesheet\"></head><body><div id=\"root\"></div></body></html>"
}
```

## Conclusions to record

- Bearer token required? No - an unauthenticated request returned 200.
- TLS: `LEGACY` completed a handshake with verification on. Certificate verification was never disabled.
- robots.txt: see above. Per ADR-019 it does not govern API access, but the record is kept.
