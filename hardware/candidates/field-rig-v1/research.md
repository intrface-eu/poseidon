# field-rig-v1: research and picks

Checked 2026-09-28. Prices are delivered to Vrsar, Croatia, with 25% VAT, EU import duty and shipping, from published listings unless a row in `acquisition.csv` says `estimate`. None is a quote. The full reports, with every source, are in `notes/`.

## What others built

We looked at 18 open or published low-cost underwater builds ([notes/prior-art.md](notes/prior-art.md)). The ones we borrow from:

| Build | What we take |
|---|---|
| OpenCTD (Oceanography for Everyone) | PVC pressure pipe housing, one potted penetration in a moulded cap, pressure-chamber tested |
| OCTOPUS camera trap (HardwareX 2023) | A PVC union as the hand-opened end |
| NEMO toolkit (Sensors 2025) | Hydrophone on its own cable, recorder in a dry box above water |
| HydroMoth and AudioMoth (Open Acoustic Devices) | A recorder that draws about 0.1 W, so primary cells last a week |
| FishCam (HardwareX 2020), PipeCam (Hackaday) | Pi camera in pipe; leaks at glued windows, drift and fouling lessons |

The reef project the team remembered was not identified for certain; the closest matches are listed in the notes. No published build has recorded seabream feeding on mussels at a farm. That is what this rig tests.

Lessons we apply: no window on the recording housing; one penetration, potted deep; desiccant and a humidity card in every housing; raise the test pressure in steps and hold; ballast so the rig hangs the same way; log clock drift at deployment and recovery; the hydrophone outside the housing, never a contact microphone through the wall.

## The build

**Rig A, all underwater.** An AudioMoth Dev board and three D cells inside 63 mm PVC-U pressure pipe, about 300 mm long. A solvent-welded cap closes the bottom; a Georg Fischer PVC-U union with an EPDM O-ring closes the top and opens by hand for the weekly swap. The Aquarian H2dM hydrophone hangs outside in a guard; its cable enters through one ROVMAKER M10 penetrator, potted in epoxy.

**Rig B, cable to the float, with the camera.** A second H2dM hangs on a rope with a sinker. Its cable plugs into an SP13 connector on a Peli 1120 case on the float, which holds a second AudioMoth Dev and D cells. The camera is a Camera Module 3 on a Pi 4 in a 75 mm pipe housing with a 10 mm acrylic window under a union nut. A Witty Pi switches it off at night. It is powered by cable from a 12 V 50 Ah LiFePO4 pack on the float; a second pack charges ashore.

Spares: a third H2dM and AudioMoth Dev, and a HydroMoth to hang beside one rig as a 48 kHz backup.

Why these picks:
- The AudioMoth Dev records 96 kHz from an external hydrophone at about 0.1 W. Three D cells last several weeks on paper. A Raspberry Pi recorder draws 1 to 3 W and needs 10 to 30 times the battery. The Pi Zero 2 W is also out of stock in the EU until 2027.
- The H2dM is the cheapest hydrophone with a published sensitivity (-172 dB re 1 V/µPa, ±4 dB up to 4 kHz) and plug-in power, and it is in stock in the EU at €277. The €460 hydrophone we priced on the site before stops at 20 kHz and publishes no sensitivity. The Chinese listings publish neither sensitivity nor upper frequency.
- The stock HydroMoth records through its case wall, which is directional and weak above 20 kHz, so it is the backup, not the main recorder.
- The pipe housing costs about €100 per rig. The same housing from Blue Robotics costs €440 to €550. From Chinese copies of those parts, only the penetrator is worth buying, and it comes with no pressure rating.

## Cost

| Part | Delivered |
|---|---|
| Two rigs, camera, spares, batteries for 6 weeks, mounting | €2,676 |
| Pressure test set and sound calibrator | €435 |
| Tools | €233 |
| Cable from float to camera housing (estimate) | €20 |
| **Total** | **€3,363** |

That leaves about €1,640 of the €5,000 target. Two uses for it:
- a Cetacean Research C57 hydrophone (about €1,400, needs a quote from NAUTA in Italy), the only one that meets the whole spec, to serve as the local reference;
- a price rise or the planned €2 per-parcel handling fee from 1 November 2026, which is not in the prices.

A calibrated reference recorder (SoundTrap, about €4,800) is not in the total; we plan to borrow one from a lab partner.

## Import rules used

Since 1 July 2026, parcels from outside the EU worth up to €150 pay a flat €3 duty per type of item, until 1 July 2028 ([European Commission guidance](https://taxation-customs.ec.europa.eu/news/guidance-and-legal-text-temporary-flat-fee-low-value-imports-which-will-apply-until-1-july-2028-2026-06-08_en)). Croatian VAT of 25% applies to every import; Croatian Post adds €2.46 per parcel when the seller has not prepaid VAT. Loose lithium cells and packs cannot go by international post, so all batteries come from EU warehouses.

## Pressure and depth

Pressure ratings on pipe are for pressure from inside; a housing fails from outside by buckling. By the thin-tube estimate in the notes, 63 mm PN10 pipe (3.0 mm wall) buckles at about 9 bar short term, less as PVC creeps over days. 63 mm PN16 pipe (4.7 mm wall) comes out near 37 bar. Buy PN16 if a Croatian or EU pool-supply shop stocks it; PN10 is the fallback for the 10 m design depth. Use moulded pressure caps, not drainage caps.

Test every housing before it goes in the sea: fill the 30 L pot with water, raise the pressure in steps to 2 bar on the gauge (20 m of water, twice the design depth), and hold for 24 hours with a humidity card inside. A 3 bar safety valve stops an over-test. Open a housing that comes back heavy pointing away from people; compressed air inside can push the end out.

## Risks

| Code | Risk | What we do |
|---|---|---|
| R1 | Cheap LiFePO4 packs ship below their rated capacity | Test each pack's capacity on arrival with the DL24 tester, inside the return window |
| R2 | The AudioMoth Dev jack may not power the H2dM cleanly (2 V at 0.7 mA) or may be noisy near 30 kHz | Bench recording before building housings |
| R3 | Power draw with a 256 GB card at 96 kHz is modelled, not measured | 7-day bench run on D cells |
| R4 | The 5 V converter can put noise into the recording band | Bench recording with the rig powered as deployed |
| R5 | Chinese penetrators, connectors and epoxy have no verified rating and may be counterfeit | The pressure test is the acceptance check; genuine epoxy if the test fails |
| R6 | The SP13 connector seals only when mated and above water | Mount it on the float box, never under water |
| R7 | 304 steel and nickel-plated parts corrode in sea water | 316 stainless hardware only |
| R8 | 52 of 138 rows are estimates or unpublished prices, and the search allowance ran out before Alibaba bulk prices were checked | Ask for quotes on the estimated rows before ordering |

## Before ordering

1. Ask NAUTA for a C57 quote, and pool-supply shops for 63 mm PN16 pipe and caps.
2. Order one H2dM, one AudioMoth Dev and one card first; run R2 to R4 on the bench.
3. Build one rig A housing and pressure-test it.
4. Order the rest once those pass.
