# O-8 evidence - what each source's robots.txt actually permits

Checked: 2026-09-13T18:01:53.563014+00:00
User-Agent: `APIx-Research/0.1 (+https://github.com/sujal128005/apix; MoSPI SIH 2026 PS 26056)`

Produced by `scripts/check_source_permissions.py`, which fetches each
domain's robots.txt and evaluates the exact paths an adapter would request,
using the same protego parser and user agent as the compliance gate.

**This replaces an assumption.** Phase 1 checked MakeMyTrip and inferred the
rest. That inference became documentation and was repeated for weeks. A spot
check found SpiceJet's robots.txt largely permissive, so every source is now
checked rather than assumed.

**A permitted host is not the host that serves fares.** robots.txt is
per-origin. Airline booking engines commonly run on a separate host from
the marketing site - Akasa's fares come from `prod-bl.qp.akasaair.com`,
not `www.akasaair.com` - and permission established for one says nothing
about the other. Both are listed below.

**A permitted path is not a known path.** An earlier run of this script
tested invented paths and reported Air India Express as permitting fare
collection, when its robots.txt disallows `/flight-availability` by name.
The invented path was permitted only because it does not exist. Paths below
are taken from each site's own Disallow rules where possible; the rest are
limited to `/` until a real path is confirmed.

**robots.txt is not a licence.** A site that does not disallow a path has not
granted permission to collect from it at volume. Terms of service govern that,
and for an official statistic the bar is affirmative permission, not the
absence of a prohibition. Treat every `allowed` below as *technically not
excluded*, pending legal review.

## Summary

| Source | Tier | robots.txt | Search path permitted | Crawl delay we would use |
|---|---|---|---|---|
| IndiGo | 3 | `UNAVAILABLE` | **no** | 5.0s |
| Air India | 3 | `UNAVAILABLE` | **no** | 5.0s |
| Air India Express | 3 | `OK` | **no** | 5.0s |
| Akasa Air | 3 | `OK` | **no** | 5.0s |
| Akasa Air (booking engine) | 3 | `ABSENT` | yes | 5.0s |
| SpiceJet | 3 | `OK` | **no** | 5.0s |
| MakeMyTrip | 4 | `UNAVAILABLE` | **no** | 5.0s |
| Goibibo | 4 | `OK` | yes | 5.0s |
| Yatra | 4 | `UNAVAILABLE` | **no** | 5.0s |
| EaseMyTrip | 4 | `OK` | **no** | 5.0s |
| Cleartrip | 4 | `OK` | **no** | 5.0s |
| Ixigo | 4 | `OK` | **no** | 5.0s |

## Per-source detail

### IndiGo (`indigo_web`, tier 3)

- `https://www.goindigo.in/robots.txt` &rarr; HTTP None, outcome `UNAVAILABLE`
- sha256: `None`
- snapshot: `None`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | **blocked** | robots.txt unreachable: refusing until it can be read |

### Air India (`airindia_web`, tier 3)

- `https://www.airindia.com/robots.txt` &rarr; HTTP None, outcome `UNAVAILABLE`
- sha256: `None`
- snapshot: `None`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | **blocked** | robots.txt unreachable: refusing until it can be read |

### Air India Express (`aix_web`, tier 3)

- `https://www.airindiaexpress.com/robots.txt` &rarr; HTTP 200, outcome `OK`
- sha256: `05206b5dfa0a662c8800235342601117f0059b939628459796cf040c56e7ca03`
- snapshot: `data\reference\robots-snapshots\aix_web\20260913T180153Z.txt`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | allowed | allowed by robots.txt |
| `/flight-availability` | **blocked** | disallowed by robots.txt for APIx-Research |

<details><summary>robots.txt as fetched</summary>

```
User-agent: * 
Disallow: /rsm-dashboard
Disallow: /retro-claim
Disallow: /loyalty-addon-packs
Disallow: /tcp-terms
Disallow: /tcp-terms-mb
Disallow: /loyalty-benefits-mb
Disallow: /loyalty-program-mb
Disallow: /growtrees
Disallow: /growtrees-certificate
Disallow: /flight-availability
Disallow: /dam
Disallow: /content/dam
Sitemap: https://www.airindiaexpress.com/sitemap.xml


```

</details>

### Akasa Air (`akasa_web`, tier 3)

- `https://www.akasaair.com/robots.txt` &rarr; HTTP 200, outcome `OK`
- sha256: `8679bca50522a4ba74ae634b99bc25ba121838fb61e6649964e3a9ce5a4d68b2`
- snapshot: `data\reference\robots-snapshots\akasa_web\20260913T180153Z.txt`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | allowed | allowed by robots.txt |

<details><summary>robots.txt as fetched</summary>

```
User-Agent: *
Sitemap: https://www.akasaair.com/sitemap.xml
Sitemap: https://www.akasaair.com/book-flight-tickets/sitemap_index.xml
 
```

</details>

### Akasa Air (booking engine) (`akasa_ibe`, tier 3)

- `https://prod-bl.qp.akasaair.com/robots.txt` &rarr; HTTP 404, outcome `ABSENT`
- sha256: `None`
- snapshot: `None`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | allowed | no robots.txt published: no restrictions to apply |
| `/api/ibe/availability/search` | allowed | no robots.txt published: no restrictions to apply |

### SpiceJet (`spicejet_web`, tier 3)

- `https://www.spicejet.com/robots.txt` &rarr; HTTP 200, outcome `OK`
- sha256: `f9bece01c38061a8f92eb25bc23f2827a40befc98af496983c638ac559851b67`
- snapshot: `data\reference\robots-snapshots\spicejet_web\20260913T180153Z.txt`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | allowed | allowed by robots.txt |
| `/api/v1` | **blocked** | disallowed by intent: robots.txt contains a malformed rule for '/api/v1' written as a full URL. A strict parser ignores it; we do not exploit the mistake. |
| `/public/` | **blocked** | disallowed by intent: robots.txt contains a malformed rule for '/public/' written as a full URL. A strict parser ignores it; we do not exploit the mistake. |
| `/externalBooking` | **blocked** | disallowed by intent: robots.txt contains a malformed rule for '/externalBooking' written as a full URL. A strict parser ignores it; we do not exploit the mistake. |

<details><summary>robots.txt as fetched</summary>

```
Disallow: 
User-agent: googlebot-mobile
Disallow: 
User-agent: MSNBot
Disallow: 
User-agent: Slurp
Disallow: 
User-agent: Teoma
Disallow: 
User-agent: Gigabot
Disallow: 
User-agent: Robozilla
Disallow: 
User-agent: Nutch
Disallow: 
User-agent: ia_archiver
Disallow: 
User-agent: baiduspider
Disallow: 
User-agent: yahoo-mmcrawler
Disallow: 
User-agent: yahoo-blogs/v3.9
Disallow: 
User-agent: *
Disallow: 
Disallow: /cgi-bin/
Disallow: https://www.spicejet.com/api/v1
Disallow: https://www.spicejet.com/public/
Disallow: https://www.spicejet.com/externalBooking
Sitemap: https://www.spicejet.com/sitemap.xml

```

</details>

### MakeMyTrip (`makemytrip`, tier 4)

- `https://www.makemytrip.com/robots.txt` &rarr; HTTP None, outcome `UNAVAILABLE`
- sha256: `None`
- snapshot: `None`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | **blocked** | robots.txt unreachable: refusing until it can be read |
| `/air/search` | **blocked** | robots.txt unreachable: refusing until it can be read |

### Goibibo (`goibibo`, tier 4)

- `https://www.goibibo.com/robots.txt` &rarr; HTTP 200, outcome `OK`
- sha256: `788921307bc5658818c741caeb562de22a770fa5f02669cb1f10338410ad4e5c`
- snapshot: `data\reference\robots-snapshots\goibibo\20260913T180153Z.txt`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | allowed | allowed by robots.txt |
| `/air/search` | allowed | allowed by robots.txt |
| `/flights/` | allowed | allowed by robots.txt |
| `/flights/?mode=search` | **blocked** | disallowed by robots.txt for APIx-Research |

<details><summary>robots.txt as fetched</summary>

```
User-agent: google-hoteladsverifier
Disallow:

User-agent: *
Disallow: /hotels/*?pg=*
Disallow: /bus/*?pg=*
Disallow: /flights/*?mode=*
Disallow: /hotels/*?PageSpeed*
Disallow: /flights/*?PageSpeed*
Disallow: /bus/*?PageSpeed*
Disallow: /trains/*?PageSpeed*
Disallow: /destinations/*?PageSpeed*
Disallow: /destinations/*aggregate*
Disallow: /ask/*?PageSpeed*
Disallow: /cars/*?PageSpeed*
Disallow: /routeplanner/*?PageSpeed*
Allow: /hotels/getHotelPolicyDataV2/
Allow: /bus/getsearch/
Disallow: /cheap/flight-tickets/
Disallow: /hotels/*?page=*
Disallow: /accounts/login/
Disallow: /eticket/
Disallow: /bus/eticket/
Disallow: /cab/eticket/
Disallow: /holidays/eticket/
Disallow: /hotels/eticket/
Disallow: /cab/searchticket/
Disallow: /hotels/searchticket/
Disallow: /flight/searchticket/
Disallow: /bus/searchticket/
Disallow: /holidays/searchticket/
Disallow: /travel-guide/pdf/
Disallow: /holidays/holidays-searchresult/
Disallow: /accounts/login/?next=/feedback/
Disallow: /common/sendquery/
Disallow: /common/emailpromo/
Disallow: /common/searchchunk/
Disallow: /searchticket/
Disallow: /tguide2/
Disallow: /hotels/search-product/
Disallow: /hotels/find-hotels-in-*/
Disallow: /hotels/find-sem-hotels-in-*
Disallow: /hotels/detail/
Disallow: /hotelsn/
Disallow: /hotelsm/
Disallow: /flights/new/
Disallow: /multicity-flights/new/
Disallow: /international-flights/new/
Disallow: /bus-new/
Disallow: /hotels/writeHotelReview/
Disallow: /reviews/readReview/*
Disallow: /gostays/search-product/
Disallow: /gostays/find-hotels-in-*/
Disallow: /gostays/detail/
Disallow: /gostays/
Disallow: /seo-renderer/*
Disallow: /api/
Disallow: /flight/customersupport/
Disallow: /bus/customersupport/
Disallow: /paymentcallback/
Disallow: /hotels/hotel-booking/*
Disallow: /https:/www.goibibo.com/reviews/writeReview/*
Disallow: /reviews/writeReview/*
Disallow: /go/fph/*
Disallow: /hotels/managebooking/*
Disallow: /flight/mytravelticket/*
Disallow: /flights/air-*
Disallow: /hotels/searchbooking/
Disallow: /hotels/searchbookingv2/
Disallow: /trains/results?*
Disallow: /trains/app/*
Disallow: /trains/booking
Disallow: /activity/*
Disallow: /trains/*?*
Disallow: /flights/*?*
Disallow: /hotels/*?*
Disallow: /bus/*?*
Disallow: /guest/
Disallow: /god/*
Disallow: /bus/-bus-booking/*
Disallow: /flight-hotels/*
Disallow: /hotels/convfeeinvoice/*
Disallow: /indiaholidaypackages/*
Disallow: /watsnew/*
Disallow: /costacruise/*
Disallow: /accounts/activate/*
Disallow: /weekendsales/*
Disallow: /promo/goibibo-promotional-code/*
Disallow: /dishtvoffer/*
Disallow: /mcpromocode/*
Disallow: /christmas-offer/*
Disallow: /christmas2013/*
Disallow: /vipwelcome/*
Disallow: /mahe-island-flights/*
Disallow: /mob1/*
Disallow: /27coupons/*
Disallow: /flight_hotel-mumbai/*
Disallow: /coupondekho/*
Disallow: /coupondunia/*
Disallow: /biggest_saletest/*
Disallow: /indianholiday/westbengal-orissa/*
Disallow: /royal_orchid/*
Disallow: /facebookoffer/*
Disallow: /couponzguru/*
Disallow: /fern/*
Disallow: /nasscom/*
Disallow: /gociti100/*
Disallow: /indianholiday/*
Disallow: /citibank-10x-offer/*
Disallow: /group-booking/*
Disallow: /indiahoneymoonpackages/*
Disallow: /reschedule-rule/*
Disallow: /holiday-mktg/*
Disallow: /flight/status/*
Disallow: /common/privacy/*
Disallow: /newmobile/*
Disallow: /hotels/*5972658767320989955*
Disallow: /gociti10/*
Disallow: /trains/srp/*
Disallow: /bus/*Airport*
Disallow: /bus/bus_mweb*
Disallow: /bus/*msrtc*
Disallow: /bus/*shrinath*
Disallow: /bus/*shreenath*
Disallow: /trains/dsrp/*
Disallow: /hotels/faq/*
Disallow: /info/user-agreement/
Disallow: /*/?hquery=
Disallow: /hotelsnew/*
Allow: /pagemaker/goCash-widget/*

Disallow: /hotels/hotel-listing/*
Disallow: /hotels/nhotel-booking/*
Disallow: /hotels/hotel-details/*
Disallow:/hotels-international/hotel-listing/*
Disallow:/hotels-international/nhotel-booking/*?
Disallow: /hotels-international/find-hotels-in-*/
Disallow: /hotels-international/find-sem-hotels-in-*
Disallow:/hotels-international/hotel-details/*

Disa
```

</details>

### Yatra (`yatra`, tier 4)

- `https://www.yatra.com/robots.txt` &rarr; HTTP None, outcome `UNAVAILABLE`
- sha256: `None`
- snapshot: `None`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | **blocked** | robots.txt unreachable: refusing until it can be read |

### EaseMyTrip (`easemytrip`, tier 4)

- `https://www.easemytrip.com/robots.txt` &rarr; HTTP 200, outcome `OK`
- sha256: `9c3d331b3f13a99e07e10c6902c1a11a5bf1f0a52c48cef955a8aab47f3a72e3`
- snapshot: `data\reference\robots-snapshots\easemytrip\20260913T180153Z.txt`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | allowed | allowed by robots.txt |

<details><summary>robots.txt as fetched</summary>

```
User-Agent: *
Disallow: /cgi-bin/
Disallow: /admin/
Disallow: /test/
Disallow: /cheap_flights/
Disallow: /cheap-flights/
Disallow: /flight-search/listing*
Disallow: /hotel-new/*
Disallow: /TrainListInfo/
Disallow: /TrainInfo/
Disallow: /trainService/
Disallow: /holiday_packages/
Disallow: /international_airlines/
Disallow: /Packages/
Disallow: /static/
Disallow: /holiday-query/
Disallow: /trains/
Disallow: /*/?e=
Disallow: /*/htl-in-
Disallow: *?appcode=
Disallow: /*?__sta=
Sitemap: https://www.easemytrip.com/sitemap.xml
```

</details>

### Cleartrip (`cleartrip`, tier 4)

- `https://www.cleartrip.com/robots.txt` &rarr; HTTP 200, outcome `OK`
- sha256: `8545b00fbfbbb7148f4ce8e794795da86a7397f80259962e3733bafd0beabc17`
- snapshot: `data\reference\robots-snapshots\cleartrip\20260913T180153Z.txt`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | allowed | allowed by robots.txt |

<details><summary>robots.txt as fetched</summary>

```
User-agent: *
Allow: /

Disallow: /cgi-bin/
Disallow: /forums/35
Disallow: /forums/38
Disallow: /flights/search*
Disallow: /trains/results*
Disallow: /trains/search*
Disallow: /packages/search
Disallow: /packages/results
Disallow: /bus/chart
Disallow: /bus/itinerary/travellers
Disallow: /pay/bus
Disallow: /bus/confirmation
Disallow: /m/flights/search*
Disallow: /m/hotels/results*
Disallow: /m/hotels/search*
Disallow: /m/trains/results*
Disallow: /m/trains/search*
Disallow: /m/flights/international/results
Disallow: /m/flights/international/results
Disallow: /flights/international/search
Disallow: /smallworld/*
Disallow: /hotels/info*
Disallow: /hotels/info/*
Disallow: /alerts*
Disallow: /users/
Disallow: /urltrack/
Disallow: /themes_holidays/
Disallow: /promotions/
Disallow: /promos/
Disallow: /forums/
Disallow: /itinerary/
Disallow: /waytogo/*
Disallow: /hotels/search
Disallow: /hotels/results
Disallow: /sem-flights-lp
Disallow: /sem-flights-offer-lp
Disallow: /signin/
Disallow: /account/
Disallow: /signinstatic/
Disallow: /sem-hotels-lp
Disallow: /html/
Disallow: /domesticair/bookflow/emailId
Disallow: /domesticair/bookflow/TravellerInfo
Disallow: /partners/dashboard
Disallow: /messages/500.shtml
Disallow: /insurance/
Disallow: /m/signin?service=/m/trips
Disallow: /ticket/view
Disallow: /m/signin
Disallow: /register
Disallow: /payment/return/tpsl
Disallow: /reset
Disallow: /local/signin
Disallow: /wl/expedia/trips
Disallow: /internationalair/bookflow/emailId
Disallow: /bookflow/TravellerInfo
Disallow: /hotel/bookflow/MakePayment
Disallow: /api/
Disallow: /hotels/itinerary/*
Disallow: /flights/itinerary/*
Disallow: /trains/itinerary/*
Disallow: /local/itinerary/*
Disallow: /packages/itinerary/*
Disallow: /payment/itinerary/*
Disallow: /*flights-flights.html
Disallow: /flights/results/itinerary/loading*
Disallow: /intake/v2/rum-events
Disallow: /m/hotels/details/
Disallow: /hotel/orchestrator/
Disallow: *?page=
Disallow: *?service
Disallow: *?hotelId=

User-agent: bingbot
Allow: /

Sitemap: https://www.cleartrip.com/sitemap.xml
Sitemap: https://www.cleartrip.com/hotels/seo-sitemap/hotel-sitemap-index.xml
```

</details>

### Ixigo (`ixigo`, tier 4)

- `https://www.ixigo.com/robots.txt` &rarr; HTTP 200, outcome `OK`
- sha256: `da8676fa944bbeae41cc121023aa57540ad920c05e06c3a91b86e8f0ee39d055`
- snapshot: `data\reference\robots-snapshots\ixigo\20260913T180153Z.txt`
- declared crawl-delay: None

| Path | Verdict | Rule applied |
|---|---|---|
| `/` | allowed | allowed by robots.txt |
| `/search/result/flight` | **blocked** | disallowed by robots.txt for APIx-Research |

<details><summary>robots.txt as fetched</summary>

```
# Hi there! Since you are here, we assume you are either a bot or a geek. In either case, drop us an email at [careers@ixigo.com]. We would love to have a conversation with you ;)

User-agent: *

Disallow: /search/result/
Disallow: /flights/search
Disallow: /flights/review
Disallow: /*.pdf$
Disallow: /add-a-place/
Disallow: /ask/
Disallow: /action/content*
Disallow: /api/
Disallow: /cdn-cgi/
Disallow: /checkbox/
Disallow: /crossselldeal
Disallow: /hotels/search/result
Disallow: /html/help/enabling-javascript.ixi
Disallow: /html/home.ixi
Disallow: /important-security-update/FAQ.html
Disallow: /ixi-api/tracker/track
Disallow: /ixigoer/
Disallow: /m/
Disallow: /mytrips/
Disallow: /q/
Disallow: /redirect.ixi
Disallow: /review-edit/
Disallow: /tp/
Disallow: /track/
Disallow: /trains/v1/search/
Disallow: *-lp-*
Disallow: *-ne-*
Disallow: *-fq-*
Disallow: /from-by-road/*
Disallow: /by-air-flight/
Disallow: /airports/
Disallow: /plan/itinerary
Disallow: /hotels/*/details
Disallow: /hotels/*/room-selection
Disallow: /trains/booking/
Disallow: /trains/search-pwa/*
Disallow: /pwa/initialpage*
Disallow: /logs/ui
Disallow: /seo-pages/_next/data/
Disallow: /seo-pages/_next/data/*

User-agent: AdIdxBot
Disallow: /

User-agent: MSNBot
crawl-delay: 10

User-agent: Yandex
Disallow: /

User-agent: Baiduspider
Disallow: /

User-agent: Bingbot
Disallow: /ixi-api/img/


#sitemaps
Sitemap:  https://www.ixigo.com/sitemap/index.xml
```

</details>
