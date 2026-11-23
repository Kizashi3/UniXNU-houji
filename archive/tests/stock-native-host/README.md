# Native stock GMU/HFI host boundary test

Run `python3 tests/stock-native-host/run_native_stock_test.py`. This executes actual Native memory, GEC-NC and secure-CX preparation, the actual C bridge/untouched HGF, and the actual stock Native adapter. Only architectural operations and device/IOKit boundaries are peers. The 29 profiles cover ready/ACK, bad ACKs/timeouts, ownership/cache changes, callback loss, retained references and the no-filesystem terminal exit. It does not prove hardware firmware/HFI success.

The base peer carries the already qualified Native/NC/SCM fixture. Firmware bytes are private: set `HOUJI_GMU_FIRMWARE_HEADER` to the locally generated pinned 78588-byte firmware header when using another workspace. Never commit the firmware image.
