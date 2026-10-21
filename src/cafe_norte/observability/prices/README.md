# prices

The versioned price table (D36). `v1.yaml` holds provider prices in USD with the page each came
from; `cost.load_prices` converts them to EUR at the ECB rate the file records.

To change a price: edit the entry, update `verified_on` and `usd_per_eur`, bump `version`.
Exports record the table version they were priced with. Re-verify every price before a release.
