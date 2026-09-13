# Source discovery — akasa

Site: https://www.akasaair.com
Session: 2026-09-13T17:57:01.741298+00:00

Recorded by `scripts/discover_source.py` during one human-driven browsing
session. **No fare here is an observation** — nothing was stored, scheduled
or repeated. This is the reconnaissance that decides whether collection is
worth proposing, not collection.

## Where the search landed

`https://www.akasaair.com/flight-search`

<details><summary>Navigation history</summary>

```
https://www.akasaair.com/
https://www.akasaair.com/flight-search
```

</details>

## Candidate fare responses (1)

Responses that plausibly carry fares. An adapter would request one of
these directly rather than driving a browser, if the site permits it.

### 1. `POST https://prod-bl.qp.akasaair.com/api/ibe/availability/search`

- status 200, 30,158 bytes
- content-type: `application/json`

Request payload:

```json
{"criteria":[{"stations":{"originStationCodes":["DEL"],"destinationStationCodes":["BOM"],"searchDestinationMacs":true,"searchOriginMacs":true},"dates":{"beginDate":"2026-09-19T00:00:00"},"filters":{"compressionType":1,"maxConnections":8,"productClasses":["NB","LB","EC","AV"],"fareTypes":["NB","LB","R","V"]}}],"passengers":{"types":[{"type":"ADT","count":1}],"residentCountry":""},"codes":{"currencyCode":"INR","promotionCode":""},"offerCode":null,"numberOfFaresPerJourney":10,"taxesAndFees":1}
```

Response head:

```json
{"data":{"currencyCode":"INR","currentSourceOrganization":null,"faresAvailable":[{"key":"MH5VMX5_UVB_VTFPN1JXSVh_MTAwMX5_Mn4xfk5CT01EWE4wMDIwMDEwflghMA--","value":{"fareAvailabilityKey":"MH5VMX5_UVB_VTFPN1JXSVh_MTAwMX5_Mn4xfk5CT01EWE4wMDIwMDEwflghMA--","fares":[{"classOfService":"U1","classType":null,"fareApplicationType":"Route","passengerFares":[{"discountedFare":5318.0000,"fareAmount":6968.0000,"multiplier":1,"passengerType":"ADT","publishedFare":5318.0000,"revenueFare":5318.0000,"serviceCharges":[{"amount":5318.0000,"code":null,"currencyCode":"INR","detail":null,"foreignAmount":5318.0000,"foreignCurrencyCode":"INR","type":"FarePrice"},{"amount":75.0,"code":"CUTE","currencyCode":"INR","detail":"DXN-BOM","foreignAmount":75.0,"foreignCurrencyCode":"INR","type":"TravelFee"},{"amount":50.0,"code":"RCS","currencyCode":"INR","detail":"DXN-BOM","foreignAmount":50.0,"foreignCurrencyCode":"INR","type":"TravelFee"},{"amount":350.0,"code":"WFE","currencyCode":"INR","detail":"DXN-BOM","foreignAmount":350.0,"foreignCurrencyCode":"INR","type":"TravelFee"},{"amount":236.0,"code":"ASF","currencyCode":"INR","detail":"DXN-BOM","foreignAmount":236.0,"foreignCurrencyCode":"INR","type":"TravelFee"},{"amount":578.0,"code":"UDF","currencyCode":"INR","detail":"DXN-BOM","foreignAmount":578.0,"foreignCurrencyCode":"INR","type":"TravelFee"},{"amount":89.0,"code":"DUDF","currencyCode":"INR","detail":"DXN-BOM","foreignAmount":89.0,"foreignCurrencyCode":"INR","type":"TravelFee"},{"amount":272.0,"code":null,"currencyCode":"INR","detail":"TaxSum","foreignAmount":272.0,"foreignCurrencyCode":"INR","type":"Tax"}]}],"productClass":"EC","ruleNumber":"1001"}],"totals":{"discountedTotal":5318.0000,"fareTotal":6968.0000,"publishedTotal":5318.0000}}},{"key":"MH5SM35_UVB_UjNPN1ZXSVh_MTAwMn5_MTZ_MX5OQk9NREVMMDE2MDAxMH5YITc-","value":{"fareAvailabilityKey":"MH5SM35_UVB_UjNPN1ZXSVh_MTAwMn5_MTZ_MX5OQk9NREVMMDE2MDAxMH5YITc-","fares":[{"classOfService":"R3","classType":null,"fareApplicationType":"Route","passengerFares":[{"discountedFare":6945.0000,"fareAmount":8251.0000,"multiplier":1,"passengerType":"ADT","publishedFare":6945.0000,"revenueFare":6945.0000,"serviceCharges":[{"amount":6945.0000,"code":null,"currencyCode":"INR","detail":null,"foreignAmount":6945.0000,"foreignCurrencyCode":"INR","type":"FarePrice"},{"amount":75.0,"code":"CUTE","currencyCode":"INR","detail":"DEL-BOM","foreignAmount":75.0,"foreignCurrencyCode":"INR","type":"TravelFee"},{"amount":50.0,"code":"RCS","currencyCode":"INR","detail":"DEL-BOM","foreignAmount":50.0,"foreignCurrencyCode":"INR","type":"TravelFee"},{"amount":350.0,"code":"WFE","currencyCode":"INR","detail":"DEL-BOM","foreignAmount":350.0,"foreignCurrencyCode":"INR","type":"TravelFee"},{"amount":236.0,"code":"ASF","currencyCode":"INR","detail":"DEL-BOM","foreignAmount":236.0,"foreignCurrencyCode":"INR","type":"TravelFee"},{"amount":152.0,"code":"UDF","currencyCode":"INR","detail":"DEL-BOM","foreignAmount":152.0,"foreignCurrencyCode":"INR","type":"TravelFee"}
```

## Candidate price selectors (0)

Leaf elements whose text reads as a rupee amount. Useful if fares must be
read from the rendered page rather than an endpoint.

## Before building an adapter

1. Run `scripts/check_source_permissions.py` against the **exact path**
   above. A path permitted in general is not the path this search used.
2. Read the site's terms of service. robots.txt governs crawling; terms
   govern automated access, and they are different questions.
3. For an official statistic, neither is sufficient — the bar is
   affirmative permission. See `docs/DATA-REQUEST.md`.
