# field-rig-v1: power, compute, storage, clock, camera

Checked 2026-09-28. Prices are delivered to Vrsar with 25% Croatian VAT, as a private (B2C) buyer. Row IDs refer to `power.csv`. My slice excludes the hydrophone, audio interface, housings, cable and connectors.

## How delivered prices were built

- **EU sellers that show Croatian VAT** (Kiwi Electronics, UUGear): listed price plus about 1 EUR per unit of shared shipping (one Kiwi order costs 8.11 EUR, or 21.88 EUR once it holds a battery).
- **EU sellers that show German VAT** (LiTime, Power Queen, reichelt, geizhals offers): listed / 1.19 × 1.25, plus shipping. Large sellers charge destination VAT through OSS.
- **Non-EU, consignment up to 150 EUR:** (price + shipping) × 1.25, plus the 3 EUR flat duty per tariff line, plus 2.46 EUR Croatian Post handling when the seller has no IOSS number (couriers charge more; I used about 10 EUR).
- **Non-EU, over 150 EUR:** normal duty (not checked per HS code; cameras and computers assumed 0%), VAT, and a broker fee of about 15 EUR.
- USD at 0.86 EUR (the rate eBay.de used on the day). Not a bank rate.
- INTRFACE j.d.o.o. with a VAT ID can buy from EU sellers under reverse charge; the VAT is then deductible. I did not price that case.

### EU rules found

- F1. Since 1 July 2026 the EU charges a flat **3 EUR customs duty per item** on consignments up to 150 EUR, counted per tariff classification, not per quantity (5 T-shirts = 3 EUR; a T-shirt and a watch = 6 EUR). It runs until 1 July 2028, then normal duty applies. It covers all distance sales up to 150 EUR, IOSS or not. Legal act: Council Regulation (EU) 2026/382. [EC guidance, 2026-06-08](https://taxation-customs.ec.europa.eu/news/guidance-and-legal-text-temporary-flat-fee-low-value-imports-which-will-apply-until-1-july-2028-2026-06-08_en)
- F2. VAT is due on every import from outside the EU, on goods plus shipping. Croatian Post charges 2.46 EUR to lodge the declaration for non-IOSS parcels up to 150 EUR, and 4.98 to 8.30 EUR if the parcel goes to customs inspection. IOSS parcels carry no Post fee. [posta.hr, customs procedure](https://www.posta.hr/carinski-postupak-0/239)
- F3. Product identifiers become mandatory on 1 November 2026, and a separate "Union handling fee" is still being drafted. Neither is priced here.
- F4. **Batteries:** the UPU bans standalone lithium batteries (UN3480, which includes LiFePO4) in international mail. Only batteries inside equipment go by post, through 32 of 192 postal operators, at most 2 batteries or 4 cells per parcel. UN3480 air freight needs a dangerous-goods declaration and at most 30% charge. In practice, LiFePO4 and Li-ion packs from China reach Croatia only from EU warehouses (by road) or by sea freight. Buy them from EU stock. [IATA-UPU mail safety guidelines](https://www.iata.org/contentassets/15ee3a255dc447b886d9a7e91fa65dbe/mail-safety-requirements.pdf), [IATA lithium battery guidance 2026](https://www.iata.org/contentassets/05e6d8742b0047259bf3a700bc9d42b9/lithium-battery-guidance-document.pdf)

## Energy for 7 days (168 h)

Storage first: 96,000 samples/s × 2 bytes × 86,400 s = 16.6 GB/day, 116 GB/week. A 256 GB card holds 15 days.

**(a) HydroMoth-class recorder.** The AudioMoth configuration app models recording at 96 kHz as **13.5 mA** (`recordCurrent: 13.5` in [constants.js](https://github.com/OpenAcousticDevices/AudioMoth-Configuration-App/blob/master/constants.js); 10.5 mA at 48 kHz). HydroMoth runs the same firmware.
13.5 mA × 168 h = 2,268 mAh, or 10.2 Wh at 4.5 V. With 30% margin for card-to-card variation: 2,950 mAh.
- 3 × AA lithium (Energizer L91, about 3,000 to 3,500 mAh at this drain): 1.3 to 1.5× margin. Tight but workable.
- 3 × D alkaline (over 12 Ah at 13.5 mA): about 5× margin.
- Cross-check: in the Kitzes lab test, AudioMoths on alkaline AAs at 96 kHz filled a 64 GB card at 91 h before the batteries ran out ([report](https://github.com/kitzeslab/ARU_battery_longevity/blob/main/report.md)).

**(b) Raspberry Pi Zero 2 W + USB audio interface.** Measured board draw at 5 V: 120 mA stock, 75 mA tuned (HDMI off, Wi-Fi off) ([CNX Software](https://www.cnx-software.com/2021/12/09/raspberry-pi-zero-2-w-power-consumption/)); 100 mA idle ([Jeff Geerling](https://www.jeffgeerling.com/blog/2021/disabling-cores-reduce-pi-zero-2-ws-power-consumption-half/)). The USB interface adds 0.25 to 0.5 W (my assumption; the audio group should measure its unit). Total 1.0 to 1.5 W; design value 1.25 W.

| Load at 5 V | At battery (buck 88%) × 168 h | With 20% reserve | 12.8 V LiFePO4 |
|---|---|---|---|
| 1.0 W | 191 Wh | 229 Wh | 18 Ah |
| 1.25 W | 239 Wh | 286 Wh | 22 Ah |
| 1.5 W | 286 Wh | 344 Wh | 27 Ah |

The 20% reserve covers the BMS cutoff, cold and ageing. A 12.8 V 50 Ah pack (640 Wh) covers the worst case with the camera added.

**(c) Raspberry Pi 4.** Idle is 575 mA at 5 V, 2.85 W ([RasPi.TV](https://raspi.tv/2019/how-much-power-does-the-pi4b-use-power-measurements)); the official figure is 600 mA. Add the USB interface: 3.0 to 3.35 W.
3.0 to 3.35 W / 0.88 × 168 h = 573 to 640 Wh; 687 to 768 Wh with reserve. That needs 54 to 60 Ah at 12.8 V, so a 100 Ah pack (about 10 kg). It does not fit an underwater pipe.

**Camera pod** (Pi Zero 2 W + Camera Module 3, switched off at night): 1.3 W (my estimate) × 13 daylight h × 7 = 118 Wh at 5 V, 134 Wh at the battery, 161 Wh with reserve.
Stills at 3 MB every 10 s come to about 14 GB/day, 98 GB/week.

## Picks per slot

| Slot | Budget pick | Safe pick | Why |
|---|---|---|---|
| O1 recorder | HydroMoth (CMP-01) | HydroMoth (CMP-01) | The only ready-made recorder at this price. The EU seller (CMP-02) was sold out. Note: it records through its own MEMS mic, not a calibrated hydrophone. |
| O1 battery | 3 × AA L91 per week (PWR-12) in the stock holder | 3 × D alkaline (PWR-13, PWR-14) in the pipe housing | The D cells are cheaper per week and give 5× margin instead of 1.4×. |
| O2 recorder | Pi Zero 2 W (CMP-03) | Pi 4 1 GB (CMP-04) | The Zero draws about a third of the Pi 4's power. It is out of stock EU-wide (reichelt: 6 March 2027), and the Pi 4 1 GB is due at Kiwi on 1 October. Radxa ZERO 3W (CMP-06) is in stock but untested for audio. |
| O2 battery | 2 × LiTime 50 Ah (PWR-01), one in use, one charging | 2 × Power Queen 100 Ah (PWR-04) | 50 Ah covers the Zero plus the camera with 30% spare. The Pi 4 needs 100 Ah. Both brands sell from German warehouses with 5-year warranties. |
| O1 Pi variant battery | 4S5P Samsung 50E pack from Nkon (PWR-08, PWR-09), 353 Wh | same | Fits a 4-inch tube; 12 V LiFePO4 blocks do not. Genuine cells from a known dealer. Needs spot welding. |
| Storage | SanDisk Extreme 256 GB (CMP-07), 46 EUR | SanDisk High Endurance 256 GB (CMP-08), 56 EUR | OAD recommends Extreme cards for AudioMoth. High Endurance is rated for continuous writes on a Pi. Samsung PRO Endurance costs 127 EUR after 2026 NAND prices rose. Buy two per rig so the boat swaps the card. |
| Clock | HydroMoth internal RTC set from an NTP-synced laptop; Pi: Adafruit DS3231 (CMP-10) set by NTP over a phone hotspot on deck | DS3231 plus Adafruit GPS PA1616D with PPS (CMP-13) on the O2 float | DS3231 holds ±2 ppm (about 1.2 s/week). GPS on the float keeps the Pi clock disciplined all week. A GPS cannot work underwater, so O1 relies on setting and logging drift at recovery. |
| 12 V to 5 V | UBEC 5 V 3 A (PWR-19) | Pololu D36V28F5 (PWR-18) | Pololu publishes quiescent and sleep current. Both need a bench recording to check switching noise in the 20 to 48 kHz band. |
| Charger | LiTime 14.6 V 10 A (PWR-15) | 2 × Victron Blue Smart IP65s 12/5 (PWR-16) | Same price; Victron has a documented LiFePO4 profile and can charge two packs at once. |
| Camera (one rig) | Camera Module 3 standard (CAM-01) on its own Pi Zero in a flat-window pod, powered by cable from the O2 float battery, Witty Pi (CMP-15) switches it off at night | Blue Robotics Low-Light USB camera (CAM-04, 0.01 lux, onboard H.264) in the same pod | Put the camera on the O2 rig: the float battery feeds it and there is no second battery to swap. |

The camera options that fail the 7-day target:
- **NoIR (CAM-02):** sea water absorbs near-IR within tens of centimetres.
- **Used GoPro HERO9 (CAM-05, 169 EUR):** Labs firmware adds scheduled capture and power-off time-lapse, and it sets the clock from a QR code. But one battery gives about 400 photos, and the dive case blocks external power.
- **SJCAM SJ4000 Air (CAM-06):** 900 mAh battery; its car mode loops over old files.
- **Chinese fishing cameras with a monitor (CAM-08):** internal battery lasts hours.
- **Barlus IP camera (CAM-07, 359 EUR):** comes sealed, with lights, rated to 50 m. It needs Ethernet and so the Pi 4, and its power draw is not published. It is the fallback only if the pod housing fails.

**Starting and syncing the camera:**
- Pi camera: `rpicam-still --timelapse` from a systemd timer; Witty Pi powers the pod on at dawn and off at dusk.
- Clock: the pod Pi gets time from the recorder by NTP (O2) or from its own DS3231.
- Sync check for every camera: tap the housing with a metal tool in view of the lens at deployment and again at recovery. The tap shows in both audio and video, giving two points to measure drift.
- GoPro: use the Labs precision-time QR code before each deployment.

## Cost per rig (my slice only)

| Layout | Budget | Safe | Contents |
|---|---|---|---|
| O1, HydroMoth | 326 EUR (D cells) / 341 EUR (AA L91) | 326 EUR | recorder, 2 cards, 8 weeks of cells, holder |
| O1, Pi Zero variant | 393 EUR | 393 EUR | Pi Zero, two 4S5P packs with BMS, Pololu, DS3231, 2 cards; plus 20 EUR 4S charger (shared); audio codec not included |
| O2, float | 450 EUR | 698 EUR | computer, two batteries, converter, RTC, 2 cards; safe adds GPS and uses Pi 4 and 100 Ah |
| Camera add-on, one rig (O2) | 144 EUR | 307 EUR | pod Pi, camera, card, converter, Witty Pi |
| Camera add-on on an O1 rig | 283 EUR | | adds two 4S3P packs (212 Wh) because O1 has no shared battery |

Shared tools: **335 EUR budget** (Pinecil, basic meter, ferrule and lug crimpers, heat shrink, heat gun, DL24 load, USB meter, LiTime charger), **526 EUR safe** (48 W station, True RMS meter, PA-09 crimper, two Victron chargers, the rest as budget).

Two-rig totals for this slice:
- Two O2 rigs, budget, with camera: **1,378 EUR**.
- One O1 HydroMoth plus one O2 with camera, budget: **1,254 EUR**.
- Two O2 rigs, safe: **2,229 EUR**.

All of these leave room under the 5,000 EUR cap for hydrophones, interfaces and housings. The per-rig figures sit well under the 1,500 EUR target.

## Risks

- R1. **Pi supply.** Zero 2 W is out of stock at every EU shop checked. reichelt gives 6 March 2027, or 22 December 2026 for the header version. Pi 4 and 5 prices rose three times in 2025 and 2026 because of DRAM costs. Zero and Pi 3 prices did not rise; Raspberry Pi holds several years of their LPDDR2 memory ([Raspberry Pi news](https://www.raspberrypi.com/news/more-memory-driven-price-rises/)). Order boards now, or plan on the Pi 4 1 GB.
- R2. **Fake capacity.**
  - Will Prowse measured 245 Ah from a "314 Ah" budget kit.
  - EU-stock Hakadi 32700 cells tested at 65 to 80% of rating.
  - Buy brand packs from EU warehouses with a 30-day return window. Discharge-test every pack with the DL24 (TLS-11) before its first deployment: 50 Ah at 5 A takes about 10 h.
- R3. **Sale prices.** LiTime shows 62% and 49% auto-discounts; Power Queen shows flash sales. Prices may rise before ordering.
- R4. **Fake SD cards.** Buy from authorised retailers only, and run `f3write`/`f3read` over the full card on every new card.
- R5. **HydroMoth current varies by card.** The 13.5 mA figure comes from the config app's model, not a measurement. Measure one unit with the chosen 256 GB card on the bench before trusting the AA option.
- R6. **Converter noise.** Switch-mode converters, including the Pololu in light-load mode (above 20 kHz), can land inside the 20 to 48 kHz band. Record from a hydrophone in a bucket with the rig powered as deployed.
- R7. **Battery shipping.** Lithium packs listed from China without EU stock may arrive late or not at all (F4). The Barlus camera and fishing cameras hold batteries inside the equipment, so they go by courier, not post.
- R8. **Camera Module 3 RFI** can disturb GPS L1 ([Raspberry Pi docs](https://www.raspberrypi.com/documentation/accessories/camera.html)). Keep the camera pod away from the float GPS.
- R9. **Charging in cold weather.** LiTime Basic packs have no low-temperature charge cutoff. Water at 12 to 26 °C is fine; do not charge them outdoors below 0 °C.
- R10. **Estimates.** Rows marked `estimate` (AliExpress parts, AA and D cells, SJCAM, heat gun, fishing cameras) had no readable price page. Quote before ordering.
- R11. **Draw not measured.** The USB audio interface draw and the camera pod draw are my assumptions. Measure both with the USB meter (TLS-12) and redo the battery table.

## Sources

- AudioMoth energy model: https://github.com/OpenAcousticDevices/AudioMoth-Configuration-App/blob/master/constants.js
- AudioMoth batteries and cards: https://www.openacousticdevices.info/batteries, https://www.openacousticdevices.info/sd-card-guide
- Battery longevity tests: https://github.com/kitzeslab/ARU_battery_longevity/blob/main/report.md
- Pi Zero 2 W power: https://www.cnx-software.com/2021/12/09/raspberry-pi-zero-2-w-power-consumption/
- Pi 4 power: https://raspi.tv/2019/how-much-power-does-the-pi4b-use-power-measurements
- EU flat duty: https://taxation-customs.ec.europa.eu/news/guidance-and-legal-text-temporary-flat-fee-low-value-imports-which-will-apply-until-1-july-2028-2026-06-08_en
- Croatian Post customs fees: https://www.posta.hr/carinski-postupak-0/239
- Lithium in mail: https://www.iata.org/contentassets/15ee3a255dc447b886d9a7e91fa65dbe/mail-safety-requirements.pdf
- Raspberry Pi price rises: https://www.raspberrypi.com/news/more-memory-driven-price-rises/
- LiFePO4 test results: https://egbatt.com/yixiang-12v-314ah-battery-review-will-prowse-tests-budget-lifepo4/, https://endless-sphere.com/sphere/threads/32700-lifepo4-cells-in-eu.126385/
- GoPro Labs long time-lapse and time sync: https://gopro.github.io/labs/control/longtimelapse/, https://gopro.github.io/labs/control/precisiontime/
- Always-on power banks: https://voltaicsystems.com/always-on-batteries/
- Part pages: see the `url` column in power.csv.
