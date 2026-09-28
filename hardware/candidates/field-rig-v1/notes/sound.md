# field-rig-v1: sound chain (hydrophone, recorder, sensitivity check)

Checked 2026-09-28. Row ids refer to `sound.csv`. All figures are delivered to Vrsar with 25% Croatian VAT. Rates: ECB reference of 25 Sep 2026, EUR/USD 1.1403, EUR/GBP 0.86045; AliExpress still shows HRK, converted at 7.5345.

## Import rules used for non-EU prices

- Since 1 July 2026 the EU charges a flat €3 customs duty per item on parcels worth up to €150. It applies per tariff line, not per parcel, and whether or not the seller uses IOSS. It runs until 1 July 2028. Commission guidance: https://taxation-customs.ec.europa.eu/news/guidance-and-legal-text-temporary-flat-fee-low-value-imports-which-will-apply-until-1-july-2028-2026-06-08_en ; Croatian customs page: https://carina.gov.hr/carinski-postupak-u-postanskom-prometu-3519/3519
- A separate EU handling fee of about €2 per parcel is planned from 1 November 2026. Its amount and start date were still under negotiation in the sources found (https://www.vatcalc.com/eu/eu-mulls-customs-admin-tax-on-non-eu-sellers/). None of the prices below include it.
- Import VAT is 25% at any value. Above €150 the normal duty rate applies. For microphones (CN 8518 10) I assumed 2.5%. I did not verify that rate in TARIC, and I did not check whether the 2025 EU-US deal has cut duty on US goods.
- Carrier clearance fees: Hrvatska pošta charges €2.46 for an H7 declaration (up to €150) and €4.91 for H6 (€150 to €1,000) (https://www.posta.hr/carinski-postupak-0/239). For couriers I assumed €10 to €20.
- EU sellers (Veldshop NL, Aditech ES, Ambient DE, Thomann, LABmaker DE, Kiwi NL) mean no customs. I re-based their prices to 25% VAT. A company buyer with a VAT number pays the same 25% through reverse charge.

## Hydrophone

**Budget pick: Aquarian H2dM, 9 m, from Veldshop NL (SND-01), €277.** Nominal −172 dB re 1 V/µPa, ±4 dB from 20 Hz to 4 kHz. It runs on plug-in power, and Open Acoustic Devices says it plugs straight into the AudioMoth Dev jack, so one hydrophone works in both layouts. It ships the same day from EU stock, so there is no customs step. Downsides: no calibration sheet. Sensitivity falls above 4 kHz (about −210 to −220 dB at 100 kHz) and the maker publishes no figure for 30 kHz. The H2d-XLR (SND-02, €283) is the phantom-power version for an XLR interface.

**Safe pick: Aquarian S1i, 10 m (SND-06), about €548.** It is Aquarian's flattest wideband model. Its response comes from US Navy calibration of three sensors, so it is a typical curve, not a per-unit one. On plug-in power it is about 7 dB less sensitive than the S1e (around −187 dB) and noisier. That sits just outside the −165 to −180 target, so it has to be checked against the site's background noise. With a phantom-powered recorder, the S1e (SND-07, about €565) sits at about −180 dB. Lead time is 6 to 7 weeks.

The closest fit to the spec is the Cetacean Research C57 (SND-10): −165 dB, 16 Hz to 44 kHz ±3 dB, self-noise 46 dB, 15 to 50 m cable, and calibration on request. No price is published. I entered €1,400 as a placeholder; ask NAUTA (Italy) for a quote before choosing between it and the S1.

Rejected:
- ASF-2 MKII (SND-08, the €460 unit in ask.md): stops at 20 kHz and publishes no sensitivity.
- ASF-1 MKII: €1,883, and at −192 dB it is too quiet for the target.
- Natako kit: its band starts at 1 kHz.
- Chinese seismic parts (YH-25-11A at about €333, SeisTech YS-3000 at about €1,245): passive, about −200 dB, need a preamp, and the upper band is unpublished or ends at 30 kHz.
- JrF, the Gladys kit and bare PZT tubes: cheap (€91 to €118), but the sensitivity is unknown until we measure it.

AliExpress lists no real hydrophone with a published sensitivity.

## Recorder

| Layout | Budget pick | Safe pick |
|---|---|---|
| O1 all underwater | HydroMoth (SND-19, ~€206): built-in sensor, case tested to 30 m | AudioMoth Dev (SND-21, ~€109) + external hydrophone |
| O2 cable to surface | AudioMoth Dev (SND-21, ~€109) | Tascam DR-05XP (SND-24, €111) |

- **HydroMoth** is the cheapest complete unit, but it misses the spec. Its MEMS sensor has no calibration, is directional, and loses signal above 20 kHz. Per-unit offsets are possible: Böttner et al. 2026 got ±1 to 3 dB against a SoundTrap at 48 kHz. On 3 AA cells it probably falls short of 7 days at 96 kHz. Use it as a spare or a second listening point, not as the main sensor.
- **AudioMoth Dev**: 96 kHz, 16-bit, with a 3.5 mm plug-in-power jack, a battery input taking 3.7 to 6 V, a real-time clock, and exFAT cards (no size limit). Estimated draw is 0.06 to 0.1 W. That estimate comes from AudioMoth tests: 161 h at 48 kHz and at least 91 h at 96 kHz on 3 AA alkaline. So one 18650 cell (about 11 Wh) or two covers 7 days. It is the only candidate small enough in power for the sealed pipe. Risk: users report plug-in-power hydrophones sound noisier on it at low levels than hydrophones with a separately powered preamp.
- **Tascam DR-05XP**: a finished commercial recorder with plug-in power, 96 kHz, cards up to 512 GB, USB power, and a new file every 2 GB with no gap. It draws about 0.45 W (estimated from DR-05X battery life), which is about 76 Wh a week. That is fine in the O2 dry box. Many USB power banks switch off at this low current. I did not confirm mono or 16-bit modes on the XP.
- Not picked:
  - Zoom H1essential (€99): records 32-bit float only, which is about 232 GB a week at 96 kHz mono.
  - Pi Zero 2 W with a UMC202HD: about 1.5 to 2 W, or 250 to 340 Wh a week. Botland also has the Zero 2 W on backorder until about April 2027.
  - Pi 4: about 3 W.
  - HiFiBerry DAC2 ADC Pro: out of stock.
  - UMC22 and cheap "96 kHz" USB cards: capture only at 48 kHz.
  - UCA202: line input only.
  - Teensy 4.1 with the audio board (€57, about 0.3 to 0.5 W): workable, but running it at 96 kHz and writing the logging firmware is our own work.

Storage: one 256 GB SanDisk High Endurance card per rig (SND-34, about €56) holds 7 days at 96 kHz, 16-bit mono (about 116 GB) with room to spare. At 24-bit the week takes about 174 GB.

## Cost per rig (sound chain only; housing, batteries, cable glands and mounts are other groups)

| Layout | Budget | Safe |
|---|---|---|
| O1 all underwater | AudioMoth Dev €109 + H2dM €277 + card €56 = **€442** (HydroMoth alone + card = €262, but it misses the spec) | AudioMoth Dev €109 + S1i €548 + card €56 = **€713** |
| O2 cable to surface | AudioMoth Dev €109 + H2dM 9 m €277 + card €56 = **€442** | DR-05XP €111 + S1i €548 + card €56 = **€715** |

Shared, bought once: a sound calibrator plus a printed coupler, about €150 (SND-35). One spare hydrophone adds €277 (budget) or €548 (safe). Two budget rigs with a spare and the calibrator come to about €1,310. Two safe rigs with the same come to about €2,130.

Earlier estimate (ask.md): €460 hydrophone + €200 to €250 interface = €660 to €710. The safe picks match that. The budget picks save about €270 per rig.

## Checking sensitivity without a lab

1. **In-air coupler check (cheap, one frequency).** A 94/114 dB sound calibrator at 1 kHz costs about €130 generic (SND-35) or €300 to €700 for a certified class 2 unit (SND-36). Pair it with a resin-printed coupler that seals the hydrophone into the 1-inch cavity. Aquarian sells one for the S1 and gives the STL away (SND-37). A 94 dB tone in air equals 120 dB re 1 µPa. The recorded level then gives the end-to-end sensitivity of hydrophone, cable and recorder gain at that one frequency, to about ±1 dB. Aquarian reports about 0.5 dB loss at 1 kHz versus 250 Hz. Böttner et al. 2026 used this method on HydroMoths and landed within 1 to 3 dB of a factory-calibrated SoundTrap (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0352463). It says nothing about the response at 10 to 30 kHz.
2. **Side-by-side at sea against one calibrated unit.** Hang the rig hydrophones within 0.5 m of a calibrated reference at the same depth. Record boat passes, snapping shrimp, or a sweep from a small underwater speaker. Take the ratio of the spectra in 1/3-octave bands from 100 Hz to 30 kHz. This is the comparison method of IEC 60565-1. The reference's own uncertainty dominates. In the field, expect a few dB below 10 kHz and worse above, where spacing causes interference. A borrowed SoundTrap (factory calibration at 250 Hz, SND-38) or a C57 with a paid calibration can serve as the reference. Each lab-calibrated unit then anchors all the cheap ones.
3. A full lab calibration of one unit has no published fee; ask.md budgets €1,500 to €3,000.

## Risks

- **Fake or loose specs.** Chinese hydrophone listings give no sensitivity at all, or seismic figures in V/bar with no upper band. "96 kHz" USB cards usually mean playback only. Aquarian's own tolerance is ±3 to 4 dB with no per-unit sheet. The DR-05XP, AudioMoth and H1essential power figures are my estimates from battery-life reports, not measurements.
- **No calibration.** None of the affordable hydrophones ships with a per-unit sheet; Cetacean Research calibrates for a fee. Without method 1 at least, levels are relative only. The recorder gain setting must be recorded and frozen per deployment, or the calibration is lost.
- **Noise floor.** Plug-in-power hydrophones (H2dM, S1i) and the AudioMoth input are noisier than a preamp with its own supply. Near 30 kHz, where the H2d and A5 roll off, sea noise may sit close to the recorder's self-noise. Before buying spares, make one bench and one sea recording to compare the system noise with ambient noise at the farm.
- **Supply.** The HydroMoth is out of stock at LABmaker; GroupGets has 81. The Pi Zero 2 W is on backorder at Botland. The S1 takes 6 to 7 weeks and the C57 up to 8.
- **Import costs not verified.** The 2.5% duty rate, the treatment of US-origin goods, courier fees, the November 2026 handling fee, and shipping costs for Veldshop, GroupGets and Aquarian are all estimates.
