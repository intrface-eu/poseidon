# Poseidon

Poseidon is an open-source listening unit for shellfish farms, now in development: it will hang beside the mussel and oyster lines, record when wild seabream come to feed, and give farmers and scientists the numbers they need before anyone tries to stop the fish.

## The problem

Gilthead seabream (*Sparus aurata*, orada in Croatian) eat farmed mussels straight off the ropes. A year-long study of six of Croatia's most productive mussel farms found that, on average, 66% of mussel ropes were destroyed within their first month in the sea, with the worst damage in summer and autumn [S1]. On one eastern Adriatic farm, seabream took 54% of young mussels in a month [S3]. In 2008 and 2009, losses in Croatia's main shellfish region were valued at about €1 million [S2]. In April 2023, seabream ate about 3.5 tonnes of mussels from one Mali Ston bay farm in a single night [S4].

Croatia is not alone. In a survey of French Mediterranean farmers, 93% reported heavy losses they blamed on fish [S2]. A mussel cooperative near La Spezia, Italy, lost 95% of its 2024 production [S5]. Wild seabream have become more common in the Adriatic, helped by escapes from fish farms and warmer water [S1][S2][S6]. In a French lagoon, tagged large seabream came back to the same farm year after year [S7].

Croatian mussel output fell from 3,000 tonnes in 2008 to about 920 tonnes by the end of the 2010s, and researchers name seabream as one of the causes [S1]. In 2025 the country farmed 821 tonnes of mussels and 78 tonnes of oysters, sold for about €3.8 million, on provisional figures [S8]. Most of it comes from small, family-run farms [S1]. Since January 2026 the state compensates mussel farmers for seabream damage, but only damage that is documented and reported, and only where the farmer shows that every lawful means of keeping the fish away was used [S9].

Lim bay (Limski kanal) in Istria is a narrow inlet, 32 m deep at most and about 650 m wide [S10]. Mussels and oysters are farmed in its inner part [S11], and it is one of the few places where the native flat oyster survived [S12]. It has been a special marine reserve since 1980 [S11][S13], and fishing is banned there, so the seabream cannot be fished out [S1]. Farming in the bay has shrunk: a 2022 report described the last shellfish farmer on the channel, who says seabream sometimes take whole mussel lines [S14]. We have no measured loss figure for Lim bay; getting one is part of the work.

The tools farmers have today fall short:

- **Nets and protective bags** keep fish off, but they foul fast, slow the water that feeds the mussels, stunt growth and get in the way at harvest [S1]. In Mali Ston bay, farmers report nets too heavy to lift after a month [S15]. Handling and cleaning barriers is often the largest production cost [S2].
- **Fishing out the seabream** is banned in protected water such as Lim bay [S1]. Elsewhere it is costly and labour-intensive [S2], and a targeted-fishing attempt in Mali Ston bay failed [S15].
- **Underwater sound devices** have not lasted. In 2019, six commercial acoustic deterrents at two Lim bay mussel farms kept the fish off for about two weeks; once the sea passed 22 °C, the protected lines were eaten as before, and the researchers judged the devices ineffective [S1]. In France, seabream got used to an acoustic deterrent [S2][S16]; in Italy, ultrasound trials failed for the same reason [S5]. No published study shows an acoustic deterrent working on a bivalve farm [S2].

What is missing is data: when, where and how often seabream feed on a given farm. Without it, a farmer cannot tell whether a fix works, a researcher cannot design a fair test, and a claim for compensation rests on what the farmer saw.

## Our approach

Listen first, measure, then test responses.

1. **Listen.** Put a passive listening unit on the lines. It makes no sound and changes nothing in the water.
2. **Measure.** Record sound and video through a whole season, match what the hydrophone hears to what the camera sees, and build a record of feeding by time, place and water temperature, checked by a marine biologist.
3. **Test responses, if the data justify it.** Only then, with scientists, permits and control lines, test whether any response reduces feeding for more than a few days. Past trials show that fish get used to sound; we will not build a deterrent on hope.

Listening can work. Researchers have heard eagle rays crushing shells above background noise at up to 100 m, and could tell the prey apart by sound [S17]. We found no published recording of seabream feeding on a shellfish farm; making one is our first job.

Monitoring is useful on its own. A farmer who knows when the fish arrive can time seeding, harvest and net checks around them.

## How the unit works

This is the design. The next section says what runs today.

The unit has two parts joined by a cable.

A **surface unit** sits above the water on a pole or a float: a flat tray with two solar panels on top and a sealed box underneath holding the battery, a small computer, storage and a mobile-data radio. Nothing in it goes under water.

A **listening head** hangs below, beside the shellfish lines: a sealed aluminium tube, 112 mm across and 300 mm long, holding a hydrophone (an underwater microphone) and a small camera behind a clear dome.

The head records sound and video. The computer flags sounds that stand out from the background, keeps a clip around each one, and sends a short summary to shore over the mobile network. A person then reviews the clip, watches the video and records what actually happened: feeding, something else, or unclear. Small solar sensor boards on the farm report water temperature and battery state over a low-power radio link.

The unit only listens. It has no loudspeaker.

## What works today

The software works end to end on test data:

- a detector that reads recorded audio and flags loud events;
- a local database and hub that keep every event linked to its recording;
- a web app where a person reviews each event, its waveform and any video, and records what they saw;
- telemetry that carries sensor readings over LoRa radio and MQTT;
- firmware for the small sensor boards, tested on a computer but not yet run on real boards;
- a scheduler that keeps any sound output switched off.

All of this has run only on computer-generated recordings. The detector flags loudness; it cannot yet tell a seabream from a boat. That needs real recordings from the farms, and we have none yet.

The hardware exists as 3D designs built from suppliers' published drawings: the surface unit in pole and float versions, and the listening head. None has been built or put in water, and every physical test, from leaks and pressure to power and heat, is still to do.

We have also done the desk research: underwater acoustics, marine hardware and EU product rules, with more than a hundred cited sources. Its main finding on sound: studies of fish and seals report that animals get used to deterrent sounds [S2][S19], and young seabream stopped reacting to low-frequency noise within about two hours [S18]. We therefore do not plan to build sound output until field data and specialists say it is worth testing.

## What comes next

**Stage 1: first recordings and prototype build.** About 6 to 9 months. Agree access with Lim bay farms, obtain the permissions a listening unit needs in the reserve, build two units, and record the first season's feeding with video. Ends with an answer: can feeding be heard and told apart from boats, ropes and shrimp?

**Stage 2: pilot season.** About 9 to 12 months. Five units on two or three farms, in Lim bay and elsewhere in Istria, through a full predation season, a detector tested against what the cameras saw, and physical tests of the hardware. Ends with a record of when and where seabream feed, and a decision on whether monitoring is a product farms want.

**Stage 3: behaviour trials, only if justified.** About 12 to 18 months. With a fish-behaviour lab and the right permits, a controlled test of whether any response reduces feeding over time, with untreated control lines. It may show that nothing works for long. That is a result too.

## The ask

We are looking for:

- **Farms** in Lim bay and across the Adriatic willing to host a unit and share their loss records.
- **A marine biology or fish-behaviour partner** to design the study and label what the fish do.
- **An underwater acoustics lab** to advise on and calibrate the hydrophones.
- **Engineers**, electronics and marine, for paid review and build work.
- **A permitting advisor** who knows Croatian nature and maritime rules.
- **A manufacturing partner** for small batches.
- **Grant co-applicants** for fisheries-fund, Horizon Europe and Interreg calls.
- **Investors and funders**: stage 1 is estimated at €49,000 to €83,000; stages 1 and 2 together at €149,000 to €238,000. The materials for the first field recordings, two simple recording rigs with spares and test gear, come to about €3,400; the rest of stage 1 is mostly people, boat days and permits.

The full list, with what each partner gets and a costed budget, is on the [What we need](ask) page.

## Team and company

Poseidon is a project of INTRFACE j.d.o.o., a small engineering company in Vrsar, Istria, a few kilometres from Lim bay. The company is led by Alex Basic, director and maintainer, who designed and built the software stack and the hardware designs. The project will add scientific and engineering partners as it moves into the water.

INTRFACE j.d.o.o., Dalmatinska 34, 52450 Vrsar, Croatia. OIB 34363240459. Registered with the Commercial Court in Pazin, MBS 130172611.

## Open source

Everything is public at [github.com/intrface-eu/poseidon](https://github.com/intrface-eu/poseidon):

- code under the GNU Affero General Public License, version 3 or later;
- hardware designs under the CERN Open Hardware Licence, strongly reciprocal, version 2;
- documentation under Creative Commons Attribution 4.0.

Any farm, lab or company can study the design, build it, improve it and share the changes. Research on a public problem should stay public.

## Contact

Alex Basic, director
INTRFACE j.d.o.o., Vrsar, Croatia
[basic@intrface.eu](mailto:basic@intrface.eu)
[poseidon.intrface.eu](https://poseidon.intrface.eu)

Sources are listed on the [Sources](sources) page.
