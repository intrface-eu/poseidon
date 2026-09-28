# field-rig-v1: housings, seals, cable entry, mounting, test gear

Checked 2026-09-28. Part rows are `HSG-xx` in `housing.csv`. All prices are delivered to Vrsar with 25% Croatian VAT. Prices marked estimate in the CSV were not visible online.

## Import rules used for the prices

- **€3 duty per item type.** From 1 July 2026 to 1 July 2028, every non-EU parcel worth up to €150 pays a flat €3 customs duty for each distinct tariff heading in it, not per piece (five identical glands = €3; glands plus O-rings = €6). The seller or importer declares it; AliExpress adds it at checkout. Sources: [European Commission, 29 June 2026](https://commission.europa.eu/news-and-media/news/ensuring-fairness-and-safety-eur3-customs-duty-low-value-parcels-2026-06-29_en), [Council final approval, 11 Feb 2026](https://www.consilium.europa.eu/en/press/press-releases/2026/02/11/council-gives-final-green-light-to-new-customs-duty-rules-for-small-parcels/).
- **VAT.** 25% Croatian VAT applies to every import. Parcels up to €150 pay it at checkout through IOSS. Above €150, VAT is charged on goods plus shipping plus duty, and the courier adds a clearance fee.
- **Above €150** (for example a Blue Robotics order), normal duty applies: I used 6% (aluminium articles 7616 / plastics 3926), plus about €15 for DHL clearance.
- **€2 handling fee.** News reports say a €2 handling fee per parcel starts on 1 November 2026. I could not confirm the final legal text, so the prices here leave it out ([vatcalc](https://www.vatcalc.com/eu/eu-mulls-customs-admin-tax-on-non-eu-sellers/)). Budget €2 more per Chinese parcel after that date.
- **Price assumptions.** AliExpress rows = listed price (shown in HRK on the site; divided by 7.5345, VAT assumed included) + €3 duty + €2–15 shipping. Blue Robotics rows = USD × 0.86 × 1.58. The 1.58 factor covers about USD 60 DHL shipping, 6% duty, 25% VAT and the DHL fee on an order of about USD 385. The USD rate of 0.86 is an assumption.
- **German shops.** Their prices include 19% German VAT. I converted them to Croatian 25% VAT, as distance-selling rules require.

## Where to buy pipe in Croatia

- Pevex, Bauhaus HR and Exterim results showed only drain pipe (odvodne/KG, PP or PVC). Drain pipe has no pressure rating. Do not use it.
- PVC-U pressure pipe and fittings (EN 1452 type, PN10/PN16) come from pool-supply shops:
  - AquaPond: sells by the metre, VAT included, ships by Packeta or BRT.
  - Bazeni Radić (Kaštela/Trogir): 3 m sticks, Plimat unions.
  - Boni-shop: threaded plugs.
- Georg Fischer PN16 unions ship from Germany (Alternative Haustechnik, €28.90 flat parcel fee to Croatia).
- Pipelife and Wavin sell only through wholesalers; I found no online retail prices for them.
- I did not check Alibaba bulk PVC fittings, because my search allowance ran out. At two rigs, minimum order quantities of hundreds of pieces make it pointless anyway.

## O1: recorder and battery in one pipe housing

**Build.** A 63 mm PVC-U pipe with a glued cap on the closed end and a glued PVC-U union at the service end. A short pipe stub and a second cap are glued into the union's loose half. To swap the battery, unscrew the union nut and lift out the cap half. The union's EPDM O-ring sits in a machined groove on its sealing face, and external pressure pushes the faces together. That makes the union the best openable end available off the shelf.

**Size.** Inside diameter is 57 mm and body length about 300 mm. That fits a HydroMoth-class board (48 mm wide) and a pack of D cells in a row or 18650 cells. The 75 mm pipe (inside 67.8 mm) is the fallback if the battery pack is wider.

**Cable entry.** The hydrophone cable enters through a 316 stainless M10 penetrator bolt (HSG-20), potted with epoxy (HSG-27) and fitted in the fixed cap. Spot-face the cap flat with a Forstner bit first, because moulded caps are slightly domed. A Blue Robotics WetLink (HSG-18) is the known-rated alternative if a Blue Robotics order is placed anyway.

**Mounting.** A rope bridle around the housing, held by two 316 hose clamps over rubber strips. It hangs from a 316 shackle (pin moused), with a second line and shackle as backup. Fix an engraved contact tag to the bridle.

Buoyancy: the housing displaces about 1.1 L, so it floats or sits near neutral depending on the battery. Hang it below the longline or add weight.

| Part | Row | € |
|---|---|---|
| Pipe d63 PN10, 1 m | HSG-01 | 8.60 |
| 2 solvent-weld caps d63 | HSG-04 | 5.20 |
| GF union d63 PN16, EPDM O-ring | HSG-06 | 36.70 |
| M10 penetrator, 316 | HSG-20 | 9.33 |
| Spare union O-ring | HSG-30 | 6.05 |
| Share of glue + cleaner, epoxy, grease, O-ring kit (½ each) | HSG-11, 27, 28, 29 | 26.47 |
| Share of desiccant and humidity cards (½ each) | HSG-45, 46 | 8.89 |
| 2 shackles, 10 m rope, 2 hose clamps | HSG-35, 36, 37 | 22.40 |
| **Per rig** | | **≈ €124** |

- **Cheaper version:** the Plimat d63 union (HSG-07) instead of GF brings it to **≈ €98**. Its seal material and PN rating are not published, so check with the seller before using it.
- **Blue Robotics comparison** (3" locking series: aluminium 240 mm tube, two flanges, two aluminium caps, WetLink, vent):
  - ≈ €551 delivered.
  - With a cast acrylic tube: ≈ €436.
  - That is 4 to 5 times the PVC housing, for a 1000 m rating the rig does not need.
  - Blue Robotics 2026 prices are much higher than in earlier years (3" aluminium 240 mm tube: USD 264).
- **Chinese copies:**
  - ROVMAKER sells cheap acrylic caps and tubes (HSG-21), but I found no matching flange, so the system is incomplete.
  - The AliExpress "ROV sealed cabin" listings (HSG-22) give no depth rating or dimensions.
  - Of these, only the penetrator is worth buying.

**Camera housing (one rig only).** A 75 mm pipe with a Plimat d75 union at the lens end. A 10 mm cast acrylic disc (HSG-31) takes the place of the union's loose tail piece. The union nut clamps the disc onto the union's own O-ring, which leaves about 85 mm of clear view. At 3 bar the disc stress is about 7 MPa (simply supported, 42 mm radius), well within the range acrylic takes. This layout is untested; pressure-test it before the camera goes in.

Parts: pipe HSG-03 €11.50, union HSG-08 €35.90, cap HSG-05 €6.20, disc HSG-31 €8.87, clamps €5.00. **Adds ≈ €67.** The Blue Robotics route is an acrylic end cap (HSG-17) on a Blue Robotics flange and tube, about €450.

**Threaded clean-out plug (not recommended).** A d63 × 2" female adapter (HSG-09) plus a 2" PN10 plug (HSG-10) costs €18.81. BSP threads do not seal, so this relies on a flat gasket under a moulded shoulder. Use it only for a vent or fill port, not as the battery door.

## O2: cabled hydrophone, dry box on the float

**Build.** A Peli 1120 case (HSG-32, IP67, 184 × 120 × 75 mm inside) strapped to the float or raft. An SP13 2-pin panel connector (HSG-25) in the case wall takes the hydrophone cable, so the cable unplugs dry for service.

The hydrophone hangs on a rope with a 1 kg sinker (HSG-38). The rope carries the load, and the cable is tied to it every 0.5 m with a drip loop at the box. The cable-to-element joint is potted (HSG-27). The hydrophone and its cable are costed in the hydrophone group.

| Part | Row | € |
|---|---|---|
| Peli 1120 case | HSG-32 | 56.95 |
| SP13 2-pin connector pair | HSG-25 | 7.94 |
| Share of epoxy (½) | HSG-27 | 5.85 |
| Share of desiccant and humidity cards (½ each) | HSG-45, 46 | 8.89 |
| 2 shackles, 15 m rope, 2 clamps or straps, 1 kg sinker | HSG-35–38 | 32.40 |
| **Per rig** | | **≈ €112** |

- **Cheaper version:** a Spelsberg TK PC glass-fibre polycarbonate box (HSG-33) brings it to **≈ €80**. It is UV-stable and DNV-approved, but IP66 only, so it must not be submerged. If the battery pack is larger than a few 18650 cells, move up to a Peli 1150 (not priced).
- The AliExpress ABS box (HSG-34) is not advised in full sun.

## Test gear (one set for the project)

The test puts each housing under **external** pressure. Pipe test pumps alone only push water into a pipe, so they test from the inside, which is the wrong direction for a housing.

- **Pressure pot (HSG-40).** VEVOR 30 L steel pressure pot, 315 mm inside diameter × 530 mm deep, 0.55 MPa maximum, built-in relief above 0.5 MPa. It fits both housings.
- **Pressurise with water, not air.** Fill the pot completely with water, then add pressure with the hand hydrostatic test pump (HSG-42) through a 1/4" inlet. A water-full pot stores almost no energy.
- **Gauge and relief valve.** Add a 0–6 bar gauge (HSG-43) and a 3 bar boiler relief valve (HSG-44) on a tee. The valve stops any over-test.
- **Test pressure.** The README's "20 m (3 bar)" means 3 bar absolute, which is 2 bar on a gauge. Hold 2.5 bar gauge (25 m) for 1 hour; the 3 bar relief valve caps the test.
- **Leak check.** Before the test, put a humidity card and tissue in the housing and weigh it. Inspect and reweigh after. Test every housing after every rebuild, and never before the glue has cured for 24 hours.

| Part | Row | € |
|---|---|---|
| VEVOR 30 L pressure pot | HSG-40 | 227.99 |
| Hand test pump 2.5 MPa | HSG-42 | 39.94 |
| 0–6 bar gauge and 1/4" fittings | HSG-43 | 25.00 |
| 3 bar relief valve | HSG-44 | 12.00 |
| **Test set** | | **≈ €305** |

- The VEVOR search page showed the 30 L pot at €179.90 and the product page at €227.99; I used the higher price.
- The 15 L pot (HSG-41, €74.90) brings the set to about €152, but its inside depth is not published and may be too short for a 300 mm housing.
- Desiccant and humidity cards for a season: HSG-45 and HSG-46, €17.76, already split across the rigs above.

## Totals

| Item | Cost |
|---|---|
| Two O1 rigs, one with camera housing | 2 × €124 + €67 + €305 test set = **≈ €620** |
| Two O2 rigs | 2 × €112 + €305 = **≈ €529** |
| Spares (extra caps, one spare union, O-rings) | ≈ €50 |

All of this fits well inside the €1,500 per rig target. The housing group is a small share of the budget.

## Risks

- **R1 Glued joints under cyclic pressure.** Under external pressure a socket joint is mostly squeezed, not pulled apart, so wave and tide cycles at 2–10 m are mild. Failures come from dry spots in the glue: no cleaner, no chamfer, glue that is too old, or testing before cure.
  - Use PVC-U pressure glue (Tangit PVC-U, EN 14814), clean both parts, and chamfer the pipe.
  - Wait 24 h before the pressure test.
  - Retest after every season or any impact.
- **R2 O-ring faces on moulded PVC.** Moulded caps and plugs have parting lines, sink marks and domed ends, so O-rings on them leak.
  - Seal only on surfaces made to take an O-ring: the union's grooved face, a spot-faced flat for a penetrator, or Blue Robotics machined parts.
  - Do not use petroleum grease on EPDM; it swells.
  - Keep a spare O-ring of the same brand and size, because union O-rings differ between makers.
- **R3 Pipe collapse.** Pressure ratings are for internal pressure. A thin-wall estimate puts short-term collapse of 63 mm PN10 (SDR21) pipe at about 7 bar (E ≈ 3 GPa), and PVC creep lowers that over a week.
  - That is 2.3 times the 3 bar test, and the short length and end caps add stiffness.
  - PN16 (SDR13.6, 4.7 mm wall) raises the estimate about 3.7 times. I found no Croatian retail price for 63 mm PN16; ask AquaPond or a German shop.
- **R4 Condensation.** A housing sealed at 25 °C and 60% RH has a dew point near 17 °C. Sea water at 12–20 °C will then fog the camera window and wet the electronics.
  - Close housings in an air-conditioned room.
  - Add 10 g of dried silica gel per litre and a humidity card, and read the card at every swap.
- **R5 UV.** Grey PVC-U, the Peli case (PP) and glass-fibre polycarbonate take sun for a season. Transparent PVC pipe, ABS boxes and white nylon glands do not; use black glands only.
  - Underwater at 2–10 m, UV is minor.
  - The O2 box on the float gets full sun and heat, so shade it or pick a light colour to keep the battery cool.
- **R6 Sea-water corrosion.**
  - Use 316 (A4) hardware only.
  - 304 glands (HSG-24), nickel-plated M12 connectors (HSG-26) and bare aluminium penetrators pit.
  - Blue Robotics anodised aluminium pits where it is scratched.
  - Copper tape next to stainless or aluminium sets up galvanic corrosion.
- **R7 Fouling.** Seven-day deployments barely foul. Skip copper tape (HSG-39) and antifouling paint near the hydrophone. Wipe the housing at each swap, and wrap the hydrophone in a replaceable nylon sock if slime builds up.
- **R8 Dry-mate connectors.** SP13 and M12 connectors are IP68 only when mated, with no depth rating for this use. Keep them above water on the O2 box. The O1 housing uses potted entry only.
- **R9 Unverified parts.**
  - Pressure rating not published: all Chinese penetrators, glands, connectors, the ROV cabin, the Plimat union, and the solvent caps.
  - Material or chemistry unverified: the silicone grease, the "3M DP270" at AliExpress prices (counterfeit risk), and the acrylic disc (cast or extruded not stated).
  - The pressure test is the acceptance check for every one of them.
