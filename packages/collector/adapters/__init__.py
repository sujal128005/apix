"""Source adapters, one module per source family.

Each implements the contract in ``collector.adapter``. The families differ in
what they are permitted to do, not merely in how they parse:

    akasa         Tier 3. A permitted crawl of the airline's availability
                  endpoint. The first adapter here that collects a real fare.
    amadeus       Tier 1. A licensed API under developer terms.
    tariff_sheet  Tier 2. Route-wise tariffs airlines must publish under
                  Rule 135(2) of the Aircraft Rules 1937 and DGCA Air Transport
                  Circular 02 of 2010.
    ota           Tier 4. Disallowed by robots.txt. Built, never executed.
"""

from __future__ import annotations

from collector.adapters.akasa import AkasaAdapter
from collector.adapters.amadeus import AmadeusAdapter
from collector.adapters.ota import OtaAdapter, OtaParserNotValidatedError
from collector.adapters.tariff_sheet import TariffSheetAdapter

__all__ = [
    "AkasaAdapter",
    "AmadeusAdapter",
    "OtaAdapter",
    "OtaParserNotValidatedError",
    "TariffSheetAdapter",
]
