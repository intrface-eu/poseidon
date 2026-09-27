# Hardware design files

Copyright (C) 2026 INTRFACE j.d.o.o. Original hardware design files (CAD source, exports, BOM and drawings) are licensed under CERN-OHL-S-2.0. They are digital candidates, not manufacturing approval or pressure qualification.

Purchased parts are referenced by part number and source URL. The repository distributes only original, dimension-based fit proxies, not supplier CAD, datasheets or drawings. Run `make fetch-vendor-sources` to retrieve hash-checked supplier evidence into the ignored `hardware/.vendor-cache/`; `make check-vendor-fit` compares the cached STEP envelopes on demand. Offline hardware verification requires neither downloaded supplier files nor this optional check.
