# field-rig-v1: prior art for cheap underwater recorders and pipe housings

Target: `hardware/candidates/field-rig-v1/README.md` (hydrophone at 2 to 10 m on Lim bay mussel lines, 7 days per battery swap, 96 kHz / 16-bit mono, 256 GB card, housing to pass a 3 bar test, at most €1,500 per rig).

All links were opened or searched on **2026-09-28**. Each claim carries a source tag; the source list sits under each table.

Evidence marks:

- **S**: stated in the source I read (full text, PDF or project page).
- **I**: my inference or arithmetic, not stated by the source.
- **U**: unverified. It came from a search-engine summary because the page itself blocked fetching (ScienceDirect, FACETS, WILDLABS returned 403). Treat as a lead, not a fact.

## Recommendation in brief

- **O1 (all underwater):** copy the OpenCTD housing idea (PVC pressure pipe, one end solvent-welded and potted, the other closed by a plumbing fitting that seals on an O-ring), scaled to EU PVC-U PN16 pipe. Put in it the AudioMoth recorder (the board inside the HydroMoth, in its Dev form) and a D-cell pack, and put a cabled Aquarian H2d hydrophone outside the housing, its cable potted through the bottom cap. Do not rely on a stock HydroMoth: its contact microphone is directional and weak above 40 kHz, and at 96 kHz three AA cells last about 4 days, not 7.
- **O2 (cable to a surface box):** copy the layout of the Greek NEMO toolkit (factory-sealed hydrophone on its own cable, recorder in a weatherproof case above water), with the H2d in place of their piezo disk. There is no pressure housing at all in O2; the same AudioMoth Dev recorder and D-cell pack sit in an IP67 box on the float.
- Both layouts then share one recorder, one hydrophone, one firmware and one data format; only the housing differs. Details and reasons are in the last section.

---

## P1. FishCam (Mouy et al., HardwareX 2020)

| Field | Detail |
|---|---|
| Link | https://pmc.ncbi.nlm.nih.gov/articles/PMC9041213/ ; repo https://github.com/xaviermouy/FishCam |
| Records | Video and stills (Pi Camera v2, 1600×1200 at 10 fps in the field). No audio; an internal 3 kHz buzzer marks time for nearby hydrophones, heard 3 m away [FC1, S]. |
| Housing | Option 1: homemade Schedule 40 PVC pipe, 4" internal diameter, built after Bergshoeff et al. 2017 "but with a longer tube", about US$100. Option 2: Blue Robotics 4" enclosure, US$233, five penetrator holes in the end cap. Both have a plexiglass front window at one end. O-rings cleaned and greased with silicone before each deployment. No potting described [FC1, S]. The exact PVC fittings (cleanout, plug) are not given in the article text I read or in the repo README [FC1, FC2, S]. |
| Rated / tested depth | PVC housing "pressure tested to water depths of at least 30 m (50 psi)"; Blue Robotics rated 100 m [FC1, S]. Test method for the PVC unit not described beyond that; the repo says to pressure test the closed housing with a pump [FC2, S]. |
| Deployment achieved | 10 deployments, Vancouver Island, Jan to Dec 2019, 8 to 12 m deep, 8 to 14 days each; 80 to 212 h of video per deployment. Units were still running at recovery; the 200 GB card was the limit, not the battery [FC1, S]. |
| Power | 28 NiMH D cells (10 Ah, 1.2 V) as 7 parallel stacks of 4, 70 Ah total, through a Pololu 5 V buck-boost; WittyPi Mini schedules on/off [FC1, S]. Newer repo adds a reed-switch power-saving mode (WiFi, Bluetooth, HDMI off, CPU throttle) claimed to give 40 to 60 % longer runs [FC2, S]. |
| Cost | Under US$500 total; batteries US$149 are the largest item [FC1, S]. |
| Licence | Hardware CC BY-SA (article); repo GPL-3.0 [FC1, FC2, S]. |
| Field lessons | L1: one unit with too little ballast was dragged away and found 180 days later 50 km off on a beach, window scratched opaque. L2: a small amount of water got into the homemade PVC housing; fixed by extra epoxy around the front window seal; authors call the Blue Robotics housing "less prone to failure". L3: WittyPi Mini clock runs only 17 h on its supercapacitor, so off-periods and pre-deployment sync must stay under 17 h (a coin cell fixes it). L4: the Pi OS froze, so it was set to reboot every 4 h. L5: USB drives rejected for power draw and vibration damage [FC1, S]. No fouling or condensation reported [FC1, S]. |

Sources: [FC1] PMC full text, checked 2026-09-28. [FC2] GitHub README, checked 2026-09-28.

## P2. Bergshoeff et al. 2017, "How to build a low-cost underwater camera housing" (FACETS)

| Field | Detail |
|---|---|
| Link | https://www.facetsjournal.com/doi/10.1139/facets-2016-0048 (page returned 403 to my fetch; figshare build video https://figshare.com/articles/media/Video_1_-_Demonstration_of_construction_steps_for_an_underwater_camera_housing/4042932) |
| Records | Consumer video camera (13 h full-HD per deployment) [BG1, U]. |
| Housing | 4" (10.16 cm) Schedule 40 PVC, 0.6 cm wall; 3M 5200 marine adhesive sealant with 5 to 7 day cure; authors advise against O-ring grease, relying on a clean O-ring and compression [BG1, U]. Window and closure fittings not verified. |
| Rated / tested depth | "up to 100 m" [BG1, U]. |
| Deployment achieved | Not verified. |
| Power | Camera's own battery [BG1, U]. |
| Cost | Whole camera system under US$425 [BG1, U]. |
| Licence | Not verified. |
| Field lessons | Not verified. This is the housing FishCam copied (P1), which is the verified part. |

Sources: [BG1] search-engine summaries of the FACETS page, checked 2026-09-28 (page itself blocked).

## P3. OpenCTD (Oceanography for Everyone; Thaler et al., Oceanography 2024)

| Field | Detail |
|---|---|
| Link | https://tos.org/oceanography/article/the-openctd-a-low-cost-open-source-ctd-for-collecting-baseline-oceanographic-data-in-coastal-waters ; build guide https://oceanographyforeveryone.com/wp-content/uploads/2024/01/OpenCTD_ConstructionOperation.pdf ; repo https://github.com/OceanographyforEveryone/OpenCTD |
| Records | Conductivity, temperature (3 × DS18B20), pressure (MS5803 14-bar), logged to SD with an RTC [OC2, S]. |
| Housing | One 12" piece of 2" Schedule 40 PVC. Bottom end: sensors pass through and are potted in Loctite Hysol E-120HP (5-minute epoxy for the pressure sensor); notches or holes in the pipe wall protect the sensors. Top end: an Oatey plumber's test cap whose O-ring seats on the inner pipe wall ("take care not to damage the inner surface where the test cap O-ring will seat"). Mounting by hose clamp and polypro loop [OC2, S]. No window, no gland; everything that leaves the housing is potted. |
| Rated / tested depth | 140 m; the test cap was "pressure tested both in the field and in a barometric chamber to 140 m" [OC1, S]. The 140 m also matches the MS5803 sensor rating [OC2, S]. |
| Deployment achieved | Casts and short moorings (hand cast, rod and reel, anchor line) [OC1, S]. Not a long-duration logger. |
| Power | 3.7 V LiPo, internal switch or external magnetic switch [OC1, S]. |
| Cost | About US$370 (under US$300 with cheaper parts) plus US$40 to 90 consumables [OC1, S]. Housing alone about US$8 versus US$117 for a Blue Robotics tube [OC4, S]. |
| Licence | Firmware and schematics MIT; build guide CC BY-NC 4.0; article CC BY 4.0 [OC1, OC2, S]. |
| Field lessons | L6: Hysol E-60HP and other high-viscosity epoxies gave "consistent failures"; use E-120HP or EA-90FL [OC2, S]. L7: potting voids let seawater reach the pressure sensor; the Hackaday log reports roughly 15 % of units failing after a few casts [OC3, U]. The Oceanography article reports no leaks and no failure rate [OC1, S]. |

Sources: [OC1] tos.org article, checked 2026-09-28. [OC2] construction PDF (89 pages), checked 2026-09-28. [OC3] https://hackaday.io/project/187637-ocean-sensing-for-everyone-the-openctd via search summary, checked 2026-09-28. [OC4] https://www.southernfriedscience.com/the-openctd-open-source-oceanography-for-everyone/ via search summary, checked 2026-09-28.

## P4. HydroMoth (Open Acoustic Devices; Lamont et al. 2022; Böttner et al. 2026)

| Field | Detail |
|---|---|
| Link | Paper https://zslpublications.onlinelibrary.wiley.com/doi/10.1002/rse2.249 (read via https://repository.essex.ac.uk/32014/ PDF); case https://www.openacousticdevices.info/product-page/hydromoth-underwater-case ; board https://www.openacousticdevices.info/audiomoth ; SPL study https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0352463 |
| Records | Sound, 8 to 384 kHz sample rate, 16-bit WAV to microSD, onboard RTC [HM3, S]. The "hydrophone" is the board's analog MEMS microphone pressed against the case wall: OAD removed the acoustic vent and filled the cone with hot-melt glue, which "effectively created a contact type hydrophone" [HM1, S]. |
| Housing | 2022 prototype: modified AudioMoth IPX7 case, vent replaced by hot-melt glue [HM1, S]. Current product: injection-moulded polycarbonate case, clasp and compression O-ring; spare seal and clasp sold as wear parts; £39.99 [HM2, S]. The case does not fit boards with the 3.5 mm socket, so there is no external hydrophone option inside it [HM2, S]. |
| Rated / tested depth | Prototype: no leaks at 30 m for 9 days and at 20 m for 2 months (personal communication in the paper) [HM1, S]. Product: "30 to 60 m", "tested to a depth of 30 m for 2 months" [HM2, S]. Test method not published. |
| Deployment achieved | Paper: 10 days continuous per set of cells (sample rate not stated in that sentence), 48 h reef deployments at 2 to 3 m in Moorea [HM1, S]. Böttner 2026: pool plus a 7 m field test in the Moluccas [HM4, S]. |
| Power | 3 × AA [HM2, HM3, S]. Kitzes Lab bench test of AudioMoth (same board) on alkaline AA: 161 h at 48 kHz, 91 h at 96 kHz [HM5, S]. So a stock HydroMoth at 96 kHz lasts about 4 days on alkaline AA, short of the 7-day target (I). |
| Cost | Under US$140 in 2022: AudioMoth US$79, case US$40, SD US$19, cells US$1 [HM1, S]. |
| Licence | AudioMoth hardware and firmware are open source (OAD GitHub) [HM3, S]; the paper is CC BY [HM1, S]. Modified case and low-gain firmware were "available upon request" in 2022 [HM1, S]. |
| Field lessons | L8: stock AudioMoth gain clipped underwater; custom low-gain firmware needed [HM1, S]. L9: signal-to-noise well below a SoundTrap; frequency response close to SoundTrap below 15 kHz, extra "self-noise or resonance" at 15 to 25 kHz, missed marine mammal sounds above 40 kHz [HM1, S]. L10: strongly directional (microphone in one corner, asymmetric case); two back-to-back units disagreed on whether dolphins were present [HM1, S]. L11: uncalibrated; Böttner 2026 shows a single-point offset per unit brings SPL within about 1 to 3 dB of a SoundTrap ST600, but only for 100 to 1000 Hz [HM4, S]. L12: users report floods when cases are opened often; clean and grease the O-ring each time; the sealed air pocket and lack of a vent make implosion a concern from about 50 m [HM6, U]. |

Sources: [HM1] Lamont et al. 2022 PDF, read in full, checked 2026-09-28. [HM2] OAD case product page, checked 2026-09-28. [HM3] OAD AudioMoth page, checked 2026-09-28. [HM4] Böttner et al. 2026, https://pmc.ncbi.nlm.nih.gov/articles/PMC13293400/, checked 2026-09-28. [HM5] https://github.com/kitzeslab/ARU_battery_longevity/blob/main/report.md Table 6, checked 2026-09-28. [HM6] WILDLABS threads https://wildlabs.net/discussion/drop-deployed-hydromoth and https://wildlabs.net/en/discussion/your-hydromoth-experience via search summary (pages blocked), checked 2026-09-28.

Extra facts for our use: the AudioMoth Dev board takes a 3.7 to 6 V battery on a JST-PH socket and has a 3.5 mm jack for external electret microphones; its own case has a D-cell holder and an M16 cable gland [HM3, S]. The AudioMoth build has exFAT and 64-bit LBA switched on in its FatFs config (`FF_FS_EXFAT 1`, `FF_LBA64 1`) [HM7, S], so SDXC cards of 256 GB should mount (I; to prove on the bench). Firmware 1.12.0 (May 2026) "improved energy consumption of large SD cards" [HM8, S]. OAD's co-founder reportedly suggests an Aquarian H2D plugged into an AudioMoth Dev for longer or deeper work [HM6, U].

[HM7] https://github.com/OpenAcousticDevices/AudioMoth-Project/blob/master/fatfs/inc/ffconf.h lines 218 and 246, checked 2026-09-28. [HM8] https://github.com/OpenAcousticDevices/AudioMoth-Firmware-Basic/releases, checked 2026-09-28.

## P5. Raspberry Pi recorder in a PVC tube (Caldas-Morgan et al., PLOS ONE 2015)

| Field | Detail |
|---|---|
| Link | https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0130297 (full text https://pmc.ncbi.nlm.nih.gov/articles/PMC4468060/) |
| Records | Sound, 16-bit, USB audio codec, 8 to 48 kHz; custom hydrophone (polyurethane-sealed PZT-5 cylinder, −198 dB re 1 V/µPa, flat to 30 kHz ±2 dB) with a 48 dB two-stage preamp; self-noise 84 dB re 1 µPa RMS [CM1, S]. |
| Housing | Cylindrical PVC enclosure 50 cm long, 114.30 mm diameter, 9.52 mm wall (SDR 12, I), closed at both ends; hydrophone and a stainless guard cage on the outer top surface; switched on and off by a Hall-effect latch and a magnet from outside, so no switch penetration [CM1, S]. |
| Rated / tested depth | Pressure chamber to 10 bar gauge (about 99.5 m) with no mechanical failure or leak [CM1, S]. |
| Deployment achieved | Field use at 11 m (port of Santos), about 20 m (humpback whales) and 7 m (dolphins) [CM1, S]. Bench endurance: 61 h continuous at 48 kHz on one pack [CM1, S]. |
| Power | 5 × D alkaline in series (8 V); average 1.12 W while recording 48 kHz and resampling; 68.29 Wh delivered by one pack; five packs fit the tube for an estimated 13.7 days continuous [CM1, S]. |
| Cost | Described as low-cost; no total given in the text I read [CM1, S]. |
| Licence | Article CC BY [CM1, S]; no hardware licence stated. |
| Field lessons | L13: a Raspberry Pi burns about 1.1 W to record 48 kHz, roughly ten times an AudioMoth (I, from CM1 and HM5); L14: no onboard clock on that Pi; DS3231 RTC added [CM1, S]. |

Sources: [CM1] PMC full text, checked 2026-09-28.

## P6. FORTH UL1 low-cost recorder (Papadakis et al., UACE 2017)

| Field | Detail |
|---|---|
| Link | https://www.uaconferences.org/docs/2017_papers/641_UACE2017.pdf |
| Records | Sound; Raspberry Pi 3 with a Cirrus Logic 24-bit, 192 kHz sound card; Aquarian H2c hydrophone (−180 dB re 1 V/µPa, 10 Hz to 100 kHz, 80 m) plus a 35 dB in-house preamp; Witty Pi schedules power and gives a ±2 ppm RTC [UL1, S]. |
| Housing | "Custom made shell which can withstand pressure up to 25 bars"; material and closure not described [UL1, S]. |
| Rated / tested depth | Whole system held 7 bar in a lab chamber for one week without leaking; deployed at 30, 50 and 70 m from a float off Heraklion [UL1, S]. |
| Deployment achieved | Short pilot runs (about 10 min recordings per depth) [UL1, S]. |
| Power | Batteries in the shell; Witty Pi cuts power between recordings [UL1, S]. |
| Cost | Under €800 [UL1, S]. |
| Licence | Not stated. |
| Field lessons | L15: the H2c needed an extra preamp for low ambient noise work; with it the unit recorded below sea state 0 at low frequencies [UL1, S]. |

Sources: [UL1] conference PDF, checked 2026-09-28.

## P7. Shallow-water recorder v2, Raspberry Pi 5 (Bagočius et al., MethodsX 2026)

| Field | Detail |
|---|---|
| Link | https://pmc.ncbi.nlm.nih.gov/articles/PMC13544172/ (doi 10.1016/j.mex.2026.104112) |
| Records | Sound, 44.1 kHz in the test (board does 44.1 to 192 kHz, 24-bit), HiFiBerry DAC+ ADC Pro; Aquarian H2dM (−172 dB re 1 V/µPa); chain sensitivity −192 dB at 1 kHz; self-noise 37 dB re 1 µPa²/Hz at 1 kHz [BA1, S]. |
| Housing | Blue Robotics 6" enclosure (152.4 mm ID, 298 mm long), flat acrylic end caps, double O-rings, pressure vent; hydrophone mounted on the acrylic end cap with a 3D-printed coupling and epoxy potting [BA1, S]. |
| Rated / tested depth | Enclosure rated 65 m; field test at 1.5 m in Klaipėda harbour [BA1, S]. |
| Deployment achieved | Bench endurance 180 h (7.5 days) continuous; up to 30 days with a power-saving schedule averaging 0.69 W [BA1, S]. |
| Power | 2 × 3.2 V 60 Ah LiFePO4 cells [BA1, S]. |
| Cost | €1,339 excluding VAT and shipping; the Blue Robotics tube alone is €546 [BA1, S]. |
| Licence | Article CC BY [BA1, S]. |
| Field lessons | L16: RTC drift of 4 s per 24 h in energy-saving mode [BA1, S]. |

Sources: [BA1] PMC full text, checked 2026-09-28.

## P8. NEMO low-cost passive acoustic toolkit (Galanos et al., Sensors 2025)

| Field | Detail |
|---|---|
| Link | https://doi.org/10.3390/s25237306 (full text https://pmc.ncbi.nlm.nih.gov/articles/PMC12694390/) |
| Records | Sound via a DIY hydrophone on a 10 m audio cable into a handheld recorder above water [NE1, S]. |
| Housing | 35 mm piezo disk glued to a 4 mm plexiglass disk that closes a PVC threaded nipple; brass pipe fitting on the back as cable exit; Sikaflex-291i on the PVC-to-plexiglass joint, PTFE tape and liquid PTFE on the thread, sealant and heatshrink at the cable exit [NE1, S]. For the long run at Villa the "handheld recorders were placed in a weatherproof case secured outside the seawater" with the hydrophone fixed at 6 m [NE1, S]. |
| Rated / tested depth | Used at 3 to 7 m; no pressure test reported [NE1, S]. |
| Deployment achieved | 34.3 h continuous at Villa; the others were 3 h sessions, including one 200 m from aquaculture net pens [NE1, S]. |
| Power | Handheld recorder's own cells [NE1, S]. |
| Cost | About €20 hydrophone plus €30 recorder [NE1, S]. |
| Licence | Article CC BY [NE1, S]. |
| Field lessons | L17: piezo-disk resonance at about 3 kHz saturated spectrograms, and response below 200 Hz was poor; low fish sounds under 1 kHz were missed except when fish were very close [NE1, S]. L18: an air pocket in the head plus the brass fitting made the hydrophone hang nearly horizontal on its cable [NE1, S]. The layout (cabled hydrophone, recorder in a dry case) is what O2 needs; the sensor is not (I). |

Sources: [NE1] PMC full text, checked 2026-09-28.

## P9. OCTOPUS camera trap (Humbert, Onthank, Williams, HardwareX 2023)

| Field | Detail |
|---|---|
| Link | https://pmc.ncbi.nlm.nih.gov/articles/PMC9860435/ ; files on Zenodo (linked from the article) |
| Records | Motion-triggered stills, far-red and UV strobes, Raspberry Pi 3B+ [OT1, S]. |
| Housing | 3 ft of 3" Schedule 80 PVC with a solvent-welded cap; two tees and 6" stubs form three ports; each port closes with a PVC union whose sleeve is removed and replaced by a plexiglass plate (camera and loading ports) or glass plate (strobe port), sealed by the union's O-ring; a Blue Robotics switch threaded into the loading-port plate lets it switch on at depth; desiccant packs inside [OT1, S]. |
| Rated / tested depth | Claimed 370 psi, "in excess of 800 ft"; no pressure test is described [OT1, S]. I read the 370 psi as the pipe's pressure rating, not a test (I). |
| Deployment achieved | 16 deployments, 785 h total, about 72 h each, Puget Sound octopus dens [OT1, S]. |
| Power | Three NiMH packs (chosen over lithium as safer when wet), low-voltage cutoff at 11 V [OT1, S]. |
| Cost | US$900 to 1,000 [OT1, S]. |
| Licence | CC BY-SA 4.0 for design files [OT1, S]. |
| Field lessons | L19: grease O-rings lightly and check the O-ring sits against the plate with no bubbles or dirt; desiccant against window fogging; bolt snaps worked, lift bags suggested for heavier units [OT1, S]. |

Sources: [OT1] PMC full text, checked 2026-09-28.

## P10. PipeCam (Fred Fourie, Hackaday.io, 2017 onward)

| Field | Detail |
|---|---|
| Link | https://hackaday.io/project/21222-pipecam-low-cost-autonomous-underwater-camera ; https://www.raspberrypi.com/news/pipecam-low-cost-underwater-camera/ |
| Records | Time-lapse stills, Pi 3 then Pi Zero with RTC [PC1, S]. |
| Housing | 110 mm PVC waste pipe; 110 mm three-piece PVC union as the opening end; 10 mm Perspex window in a heavy-duty PVC fitting [PC1, PC2, S]. |
| Rated / tested depth | Tested to 4 bar with a one-way valve in a test window and a tyre compressor; used at 0.3 to 5 m in a harbour [PC1, S]. |
| Deployment achieved | 3 days, about 4 days, and 3+ weeks depending on interval [PC1, S]. |
| Power | Lead-acid, then DIY 18650 packs [PC1, S]. |
| Cost | About €60 for a Pi Zero build [PC1, S]. |
| Licence | Not stated on the page [PC1, S]. |
| Field lessons | L20: a rushed new housing "catastrophically failed within minutes of deployment"; L21: after 3 weeks algae on the window was "pretty dramatic"; L22: SD card sleep current varied from µA to about 1 mA; L23: poor ballast let the camera move and spoiled a time-lapse; the author keeps the PVC tube as "the simplest and most reliable housing" [PC1, S]. |

Sources: [PC1] Hackaday.io project page, checked 2026-09-28. [PC2] Raspberry Pi blog via search summary, checked 2026-09-28.

## P11. LoBSTAS (Hackaday.io, 2018)

| Field | Detail |
|---|---|
| Link | https://hackaday.io/project/160192-lobstas-underwater-camera-sensor |
| Records | Stills from a Pi Zero W on a lobster trap, for hypoxia work [LB1, S]. |
| Housing | 2" Schedule 40 PVC, 6 to 9" long; acrylic window solvent-cemented into a 2" coupling; the other end closed by an expansion plug; no O-ring (the builder had no tools to cut grooves) [LB1, S]. |
| Rated / tested depth | Leak test only: dropped on a rope at "various depths" overnight with dry tissue inside; no rating [LB1, S]. |
| Deployment achieved | Not stated [LB1, S]. |
| Power | Anker 5,200 mAh USB power bank [LB1, S]. |
| Cost | About US$100 [LB1, S]. |
| Licence | Not stated on the page [LB1, S]. |
| Field lessons | Cutting the round window was the slowest step [LB1, S]. |

Sources: [LB1] Hackaday.io page, checked 2026-09-28.

## P12. Cave Pearl data loggers (Beddows and Mallon, Sensors 2018, and blog)

| Field | Detail |
|---|---|
| Link | https://pmc.ncbi.nlm.nih.gov/articles/PMC5856100/ ; https://thecavepearlproject.org/2023/05/24/a-diy-pressure-chamber-to-test-housings/ |
| Records | Flow, drip, temperature, pressure (Arduino loggers) [CP1, S]. |
| Housing | 2" Schedule 40 PVC; Formufit table-leg end caps pulled by three nylon 1/4-20 bolts onto an EPDM 332 O-ring, seats wet-sanded to 800 grit; sensors potted in Loctite E-30CL with 8 to 10 mm of epoxy over any part not rated for pressure [CP1, S]. |
| Rated / tested depth | Pipe rated over 150 psi working and over 225 psi collapse; deployed 2 to 24 m; "up to 30 m for >3 years without water ingress" [CP1, S]. Flat caps with sensor wells bowed below 20 m, so direct-connect units are kept above 10 m [CP3, U]. DIY test chamber: clear 4.5"×10" water-filter housing, gauge, bicycle pump, about US$70, usable to about 80 to 90 psi; pressure raised 5 psi per day; failures often came 4 h or more after a step [CP2, S]. |
| Deployment achieved | 430 months over 78 submerged deployments; average 5 months, longest 16 months [CP1, S]. |
| Power | 3 × AA; about 0.1 to 0.25 mA sleep [CP1, S]. |
| Cost | Under US$50 per logger before sensors [CP1, S]. |
| Licence | Article CC BY 4.0; code open source on GitHub [CP1, S]. |
| Field lessons | L24: early power failures came from epoxy breaking down and seawater shorting boards; fixed by changing epoxy [CP1, S]. L25: vapour creeps in at solvent welds on long runs; two 10 g silica packs for stays over a year [CP1, S]. L26: nylon bolts swell about 2 mm in seawater; pre-soak a week [CP1, S]. L27: 316 stainless washers corroded badly after six months [CP1, S]. L28: a slow leak can let water in and compress the trapped air, and the housing then bursts on the way up ("effectively turning the device into a bomb") [CP3, U]. L29: potted ICs can still fail under pressure; rim threads on potted caps split before tubes collapsed [CP2, S]. |

Sources: [CP1] PMC full text, checked 2026-09-28. [CP2] Cave Pearl chamber post, checked 2026-09-28. [CP3] https://thecavepearlproject.org/category/diy-underwater-housings/ via search summary, checked 2026-09-28.

## P13. DEACs camera traps, Lighthouse Reef, Belize (Bilodeau et al., PLOS ONE 2022)

| Field | Detail |
|---|---|
| Link | https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0263377 (full text https://pmc.ncbi.nlm.nih.gov/articles/PMC8809566/) |
| Records | Cuddeback terrestrial camera trap, 20 MP stills every 15 min, daylight only [DE1, S]. |
| Housing | Not pipe. Plastic electrical junction boxes: Saipwell DS-AT-1217-1 (thin walls) and Polycase ML-47F (3.5 to 4.0 mm polycarbonate, stainless screws, silicone gasket); a 2" hole in the lid covered by a 3" disk of 1/8" acrylic epoxied on with MarineWeld; lid seam and window reinforced with marine silicone; about US$30 per housing [DE1, S]. |
| Rated / tested depth | Field only. Thin box flooded past 4 m and leaked shallower; the thick box reached 7 m with "minimal leakage" over months; a revised box reached 40 m in early tests [DE1, S]. |
| Deployment achieved | 28 cameras, 21 reef sites, March 2018 to March 2019; longest continuous run over 5 months [DE1, S]. |
| Power | 8 × lithium AA; still "OK" at 5 months [DE1, S]. |
| Cost | US$125 per unit with housing [DE1, S]. |
| Licence | Article CC BY 4.0; code on GitHub [DE1, S]. |
| Field lessons | L30: wall flex under pressure broke the epoxied window seal; L31: fouling was the biggest problem, images degraded in as little as a month (median about 2 months usable); antifouling paint was "only a minor deterrent"; L32: 32 GB card limit of the camera [DE1, S]. |

Sources: [DE1] PMC full text, checked 2026-09-28.

## P14. CoralCam (Greene et al., HardwareX 2019)

| Field | Detail |
|---|---|
| Link | https://pmc.ncbi.nlm.nih.gov/articles/PMC9041191/ ; files https://osf.io/dum2h |
| Records | Twice-daily stills or 30 s videos from a cheap action camera driven by an Arduino Pro Mini and DS3231 RTC [CC1, S]. |
| Housing | Not pipe. Stock GoPro Hero 4 housing with an extended back door; housing wrapped in electrical tape against fouling; tempered-glass lens protector [CC1, S]. |
| Rated / tested depth | Up to 45 m (the housing's rating) [CC1, S]. |
| Deployment achieved | 2 weeks, then 30 days, Kāneʻohe Bay, Hawaii; no water ingress [CC1, S]. |
| Power | Camera battery plus a 500 mAh LiPo for the controller; the Pro Mini's green LED must be removed for runs over 20 days [CC1, S]. |
| Cost | Under US$80 [CC1, S]. |
| Licence | Hardware CC BY-SA; article CC BY-NC-ND [CC1, S]. |
| Field lessons | L33: fouling started to spoil images after about 25 days; most growth sat on the tape and came off with it [CC1, S]. |

Sources: [CC1] PMC full text, checked 2026-09-28.

## P15 to P18. Other builds checked, lower relevance

| Project | Link | Housing | Depth, run, power, cost, licence | Why lower relevance |
|---|---|---|---|---|
| P15 PlasPi (Purser et al., HardwareX 2020) | https://pmc.ncbi.nlm.nih.gov/articles/PMC9041251/ | Polycarbonate cylinder with machined POM end caps, two greased O-rings each, acrylic port windows, silica gel bag [PP1, S] | Tested at 20 bar; used to 200 m; up to 4 days on a cold-water coral reef at about 90 m; 2 × Li-SO2 D cells; under €200; CERN OHL v1.2 [PP1, S] | Needs lathe work, not plumbing parts |
| P16 KOSMOS (Sensors 2021) | https://pmc.ncbi.nlm.nih.gov/articles/PMC8619907/ | Blue Robotics 4" acrylic tube, aluminium cap, 5 mm acrylic window, double O-ring flanges [KO1, S] | Day-long drop camera; LiPo 3S 2200 mAh; about €1,360; CC BY-SA [KO1, S] | Commercial tube, short runs |
| P17 iFO infrared fish observation (Hermann et al., HardwareX 2020) | https://pmc.ncbi.nlm.nih.gov/articles/PMC9041171/ | Blue Robotics 3" acrylic tubes, M10 penetrators with cable sealed in marine epoxy [IF1, S] | 100 m rating; PoE over an underwater cable to a surface unit with an LTE router and swappable disk, weeks of storage; about €530 per camera plus two lamps; CC BY article [IF1, S] | Only cabled-camera reference found; useful if the O2 rig ever carries a camera |
| P18 Okinawa reef stereo camera (Ishikawa et al., arXiv 2605.10449, 2026) | https://arxiv.org/abs/2605.10449 | "Underwater housing constructed from PVC parts" around a Raspberry Pi 4 and two cameras 40 cm apart; no further detail [OK1, S] | About 2 m on a shallow reef, 20 days hourly daytime video, Anker power bank, sleep scheduling board, about US$1,000 [OK1, S] | Housing not documented |

Sources: [PP1], [KO1], [IF1] PMC full texts; [OK1] arXiv PDF; all checked 2026-09-28.

---

## The reef project built from pipe

I did not find one project that is certainly the one the user saw. The candidates that match "reef" plus "cheap housing", with the detail that tells them apart:

- **DEACs, Belize (P13).** Coral reef, 28 cameras, a year of deployments, PLOS ONE 2022. Housings were plastic junction boxes, not pipe.
- **CoralCam, Hawaii (P14).** Coral reef, HardwareX 2019. Housing was a GoPro case.
- **Okinawa stereo camera (P18).** Coral reef, PVC housing, arXiv May 2026. Housing barely described.
- **OCTOPUS (P9).** Schedule 80 PVC pipe with union ports, HardwareX 2023, the most "plumbing" look of all. It watched octopus dens in Puget Sound, not a reef; the name may be what stuck.
- **PipeCam (P10).** 110 mm PVC waste pipe, Hackaday and the Raspberry Pi blog. Kelp forest and harbour, not a reef.
- **HydroMoth on reefs (P4).** Lamont's team recorded reefs in Moorea and Indonesia with HydroMoths, but in the small polycarbonate case, not pipe.

If the user remembers a cable to the surface, it is more likely iFO (P17); if a hydrophone rather than a camera, HydroMoth (P4).

## Builds and papers on fish feeding or shell crushing

- **Ajemian et al. 2021, JEMBE** (https://www.sciencedirect.com/science/article/abs/pii/S0022098120305037): whitespotted eagle rays crushing 434 molluscs in a tank. First fracture over 160 dB re 1 µPa, fracture events under 0.1 s, peak 3.1 to 5.0 kHz by prey; field playback suggests audible over ambient noise out to 100 m in coastal lagoons [SC1, U, abstract and press text only]. Recorder model not verified. A 2026 follow-up applies signal processing and machine learning to classify the events (https://www.sciencedirect.com/science/article/pii/S1574954126002013) [SC2, U].
- **Šegvić-Bubić et al. 2011, Aquaculture 319** (doi 10.1016/j.aquaculture.2011.07.031): two years of fish counts at a Croatian Adriatic mussel farm; gilthead seabream was among the most abundant species in summer and autumn; rope losses measured after thinning. Visual census, no acoustics [SC3, S, abstract].
- **Colla et al. 2018, J Fish Biol** (doi 10.1111/jfb.13589): passive acoustic monitoring of brown meagre calls inside a northern Adriatic mussel farm; more calls in the farm than on sand outside; high June to August [SC4, S, abstract]. Recorder not checked.
- **Domingos et al. 2026, Research Square preprint** (doi 10.21203/rs.3.rs-9393605/v1): seabream feeding behaviour classified from hydrophone audio in 200 L recirculating tanks, analysed in the 50 to 1000 Hz band; the search summary says an Aquarian H2dM through a USB audio adapter to a laptop [SC5, S for the study, U for the gear].
- No published build records seabream crushing mussels on a farm (from these searches). That gap is what this rig tests (I).

Sources: [SC1] FAU and ScienceDaily press pages and the ScienceDirect abstract via search, checked 2026-09-28. [SC2] ScienceDirect listing via search, checked 2026-09-28. [SC3], [SC4] Europe PMC abstracts, checked 2026-09-28. [SC5] preprint PDF, checked 2026-09-28.

Note for the band: the ray fractures peak at 3 to 5 kHz [SC1, U]; the target band of 50 Hz to 30 kHz at 96 kHz covers it with room above (I).

---

## Cross-cutting lessons for our rig

| Code | Lesson | From |
|---|---|---|
| X1 | Leaks start at glued windows and seams, not in the pipe wall. FishCam leaked at its epoxied window; DEACs windows let go when walls flexed. O1 needs no window, so keep it that way (I). | FC1, DE1 |
| X2 | Every hole in a flat cap weakens it; flat caps bow. Use one small penetration, pot it deep (8 to 10 mm over parts), and keep the cap moulded and pressure-rated. | CP1, CP3 |
| X3 | A slow leak compresses the trapped air and can burst the housing on recovery. Open the housing pointing away from people if it comes up heavy or with water inside (I, based on CP3). | CP3 |
| X4 | Test in steps and hold: failures arrived hours after each pressure step. Put indicator desiccant inside so slow leaks show. | CP2 |
| X5 | Desiccant in every housing; vapour creeps through solvent welds on long runs. | CP1, OT1, PP1 |
| X6 | Fouling: one week is short, but windows fouled in 3 weeks (PipeCam) and a month (DEACs, CoralCam). Tape-wrap the housing and strip it at each swap (CoralCam). | PC1, DE1, CC1 |
| X7 | Ballast and a fixed attitude matter: a FishCam was lost to currents; PipeCam moved and spoiled a series; the NEMO head hung sideways. | FC1, PC1, NE1 |
| X8 | Clocks: WittyPi Mini lost time after 17 h without power; the Pi 5 drifted 4 s per day; DS3231 is quoted at about 1 min per year. Log drift against a GPS-timed tone or clap at deploy and at recovery. | FC1, BA1, CP1 |
| X9 | Cards: SD cards differ widely in sleep current and write energy; test each model; large cards may cost more energy per write. | PC1, CP1, HM8 |
| X10 | Batteries: NiMH sags below the AudioMoth's working voltage at 70 to 80 % of rated capacity [U]; alkaline drawn to 0.8 V leaks [S]. Use fresh alkaline or lithium primaries and measure a full 7-day bench run first. | HM6, CP1 |
| X11 | Piezo disks resonate near 3 kHz and miss sound below 200 Hz. Use a cylindrical hydrophone (Aquarian H2d or a PZT cylinder). | NE1, CM1 |
| X12 | Contact microphones through a case wall are directional and uncalibrated. Keep the element outside the housing, as commercial units do. | HM1 |

## Housing arithmetic (all I)

External pressure buckles a long tube before it bursts. For a thin tube, critical pressure ≈ 2E / (1 − ν²) × 1/(SDR − 1)³, with SDR = outside diameter / wall. With PVC-U E ≈ 3,000 MPa short term and ν ≈ 0.38:

- SDR 26 (PN10 PVC-U, e.g. d110 × 4.2 mm): about 4.5 bar short term, less over days as PVC creeps, less again if the pipe is out of round. Too close to the 3 bar test. Do not use.
- SDR 17 (PN16, e.g. d75 × 4.5 mm, d90 × 5.4 mm, d110 × 6.6 mm): about 17 bar short term; several times the 3 bar test even after creep and ovality. Use this or thicker.
- Caldas-Morgan's tube (114.3 × 9.52 mm, SDR 12) passed 10 bar; FishCam's 4" Schedule 40 (SDR about 19) passed 50 psi. Both sit on the safe side of this rule.

End caps: use moulded solvent-weld PVC-U pressure caps rated PN16, not thin drainage caps.

---

## Recommendation

### What to copy

- **R1. Recorder: the AudioMoth platform (the board inside the HydroMoth), in its Dev form, with an Aquarian H2d hydrophone.** Reasons: it has the lowest power of any recorder found (Kitzes: 91 h at 96 kHz on 3 × AA alkaline, so about 0.1 W; I), so a 7-day run needs roughly 17 Wh, which 3 × D alkaline covers with about three times margin (I). The firmware records 96 kHz 16-bit WAV with an RTC and already runs underwater in the HydroMoth, tested by Lamont 2022 and Böttner 2026. The build has exFAT on, so a 256 GB card should work (to prove). The H2dX is −165 and the H2dM −172 dB re 1 V/µPa, both inside the README's target of −165 to −180, omnidirectional in the horizontal, rated below 80 m, sold with 3 to 15 m cable. The H2dM needs 2 V plug-in power at 0.7 mA; whether the AudioMoth Dev jack supplies that cleanly must be checked on the bench (Q1). The Raspberry Pi route (P5, P6, P7) works and gives 24-bit, but it draws 0.7 to 1.1 W or more, needs 10 times the battery, and brings OS freezes and card corruption (FishCam rebooted every 4 h). Keep it as the fallback if the AudioMoth analog front end proves too noisy for crushing sounds (Q2).
- **R2. O1 housing: the OpenCTD pattern, in EU PN16 pipe.** One piece of pipe, one solvent-welded cap, one serviceable closure that seals on an O-ring, and everything that leaves the housing potted, with no window. OpenCTD's closure was tested in a chamber and in the field to 140 m; FishCam's Schedule 40 tube passed 30 m; Caldas-Morgan's thick tube passed 10 bar with a hydrophone recorder inside. That is enough prior art for a 10 m design with a 3 bar test.
- **R3. O2 layout: the NEMO toolkit pattern (P8) with a better sensor.** Hydrophone hangs on its own cable; recorder sits dry above water. The only wet part is the H2d, which Aquarian already seals and rates to 80 m, so O2 needs no pressure test beyond checking the cable.
- **R4. Keep one stock HydroMoth per rig as a cheap second recorder** at 48 kHz (161 h on alkaline AA per Kitzes, close to 7 days; lithium AA should clear it, to prove). It gives a backup record and a check on the main chain, and its results compare directly with the published HydroMoth work (P4) (I).

### O1 housing recipe to start from (all dimensions I, to confirm against real parts)

1. Tube: PVC-U pressure pipe to EN 1452, PN16 (SDR 17), d75 × 4.5 mm (inside about 66 mm), about 350 mm long. It fits an AudioMoth-size board (58 × 48 mm) and 3 × D cells (34 mm) in series stacked along the axis. Step up to d90 PN16 if the parts do not fit.
2. Bottom: PN16 solvent-weld end cap. Drill one hole for an M16 nylon cable gland (the size OAD's Dev case uses); pass the H2d cable, tighten, then fill the cap's inside well with 8 to 10 mm of marine potting epoxy over the gland body and cable (OpenCTD used Hysol E-120HP; avoid high-viscosity E-60HP). Leave the H2d element outside, hanging 20 to 30 cm below the cap in a small guard cage or perforated PVC sleeve, strain-relieved to the housing so the cable never carries the element's weight into the gland.
3. Top: a PVC-U pressure union (EPDM O-ring) solvent-welded to the tube, closed by a solid PVC blank in place of the union's pipe end, as OCTOPUS did with its plexiglass plates. This opens by hand on a boat, reseals on the same O-ring every week, and needs no tools. Second choice: a plumber's expanding test plug, as OpenCTD used, if unions of this size are hard to buy.
4. Inside: a 3D-printed or PVC sled holding board and cells, a magnet-operated reed switch so the unit can start or stop without opening (HydroMoth and Caldas-Morgan both do this), two indicator silica gel packs, and a tag with contact details.
5. Outside: shackle point through a stainless or Dyneema strap around the tube, not through a drilled hole; backup line; electrical tape wrap to strip at each swap; enough weight that the housing hangs still.
6. Test: build a chamber from a larger PN16 pipe section with caps, or a clear water-filter housing if the d75 tube fits (Cave Pearl's approach, about US$70, good to about 80 psi). Hold 3 bar for 24 h with indicator desiccant inside, raising in steps; then a 7-day powered bench run at 96 kHz before the first dive.

### O2 recipe to start from (I)

1. H2dM or H2dX on a 15 m cable (standard length), hanging 2 to 10 m below the float on a weighted line, with the cable tied loosely along that line so waves pull the rope, not the cable.
2. Recorder, 3 × D pack and desiccant in an IP67 polycarbonate box on the float or raft, cable in through a gland with a drip loop, box shaded and vented against heat and condensation.
3. Same firmware, card and clock routine as O1.

### Risks and open questions

| Code | Item |
|---|---|
| Q1 | Does the AudioMoth Dev 3.5 mm jack power an H2dM (2 V, 0.7 mA plug-in power) with low enough noise? One bench test with a tone in a bucket answers it. If not, use a small external preamp or the H2dX with a 9 V phantom supply. |
| Q2 | Is the AudioMoth front end quiet enough at 30 kHz? The H2d's sensitivity falls toward −210 to −220 dB at 100 kHz; no curve is published for 30 kHz. Compare one bench recording against the HydroMoth and, if we can borrow one, a SoundTrap. |
| Q3 | 256 GB card on AudioMoth: exFAT is compiled in, but OAD may still list tested cards. Prove with a 7-day run. |
| R1 | Flow noise and cable strum in O2 on a moving float. Mitigate with a weight below the hydrophone and slack cable. |
| R2 | Seal wear on the weekly-opened union. Buy spare O-rings; inspect and grease at each swap (HydroMoth users report floods from frequent opening). |
| R3 | Fouling on the hydrophone over repeated weeks. Clean at each swap; do not paint the element. |
| R4 | Theft or boat strikes on the O2 surface box, and on O1 lines. Contact label, low profile, farm owner informed. |

### Rough parts cost per O1 rig (I, prices from the sources above, not quotes)

H2d about US$229; AudioMoth 1.2 was US$79 in 2022 (Dev price not checked); PVC pipe, cap, union, gland and epoxy well under €100; 3 × D cells and a 256 GB card under €60; HydroMoth backup under US$140. That lands far below €1,500 per rig and leaves the rest of the €5,000 for spares, a pressure chamber and the optional camera (FishCam, P1, in a d110 PN16 tube, is the camera to copy).
