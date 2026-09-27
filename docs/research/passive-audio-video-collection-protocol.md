# Passive audio/video collection protocol

Status: desk proposal, unapproved, 2026-09-07

This protocol prepares a passive feasibility study for candidate shell-crushing and feeding events. It does not authorize site access, recording, installation, equipment purchase, animal exposure, or acoustic transmission. The current software slice uses declared files and synthetic fixtures only. Field collection starts only after the gates below pass.

## Research question

Can passive underwater audio, with synchronized visual and observer evidence where available, distinguish locally observed feeding events from site noise at a useful range and false-alert rate?

A positive result supports further monitoring work. It does not establish species identification from sound alone, localization, predator prevention, stock-loss reduction, or permission to emit sound.

## Evidence boundary

- [Capturing shell-crushing by large mobile predators using passive acoustics technology](https://doi.org/10.1016/j.jembe.2020.151497) reports shell-crushing peaks around 3.1–5.0 kHz for eagle rays. It supports testing passive methods, not assuming the same spectrum for local gilthead seabream or requiring 100 kHz acquisition.
- The official [ARIEL Croatian regional pilot report](https://ariel.adrioninterreg.eu/wp-content/uploads/2020/07/ARIEL_D.T2.4.1_Pilot_Activities_-regional_Report_HRVate.docx) reports a six-device 2019 DDD03L trial at two Lim Bay mussel concessions. Initial protection did not persist: severe predation was reported by mid-July, and the July repeat also failed after about two weeks. That active-output result does not validate a passive detector. The tested 5–500 kHz range and roughly 140 kHz peak are historical device attributes, not receive-band or treatment requirements.
- The [PREDADOR project page](https://www.pole-mer-bretagne-atlantique.com/ressources-biologiques-marines/predador) reports habituation in prior deterrence work. It is a reason to keep active intervention outside this protocol.

## Mandatory gates

| Gate ID | Gate | Approval evidence | Owner | Initial status |
|---|---|---|---|---|
| COL-GATE-001 | Exact farm, coordinates, cultured species, target predator, loss mechanism, and recording zones confirmed | Signed or otherwise traceable site record | Farm/site partner and marine ecologist | Blocked |
| COL-GATE-002 | Farm access and every applicable protected-area, research, recording, installation, navigation, and work-safety permission in force | Written decisions and conditions in the [site and permissions register](site-permissions-evidence-register.md) | Product owner with site partner and current competent authorities | Blocked |
| COL-GATE-003 | Passive-only method and initial hazard controls approved | Reviewed method statement and [hazard register](../safety/initial-hazard-register.md) | Safety owner, marine operations owner, and marine ecologist | Blocked |
| COL-GATE-004 | Data protection and farm-confidentiality rules approved | Lawful basis or consent where needed; access, retention, deletion, and publication rules | Data controller/legal adviser and farm operator | Blocked |
| COL-GATE-005 | Exploratory passive-pilot receive plan approved; final dataset chain freezes only after that pilot measures local signals/noise | For the pilot: conservatively selected borrowed/rented receive gear, justified initial band/sample rate, calibration/provenance plan, safe mount/power/clock/storage method. Before dataset collection: reviewed final settings and uncertainty. | Underwater-acoustics specialist, data lead, and electrical/mechanical engineers | Blocked |
| COL-GATE-006 | Annotation guide, split policy, metrics, sample sufficiency, and numeric decision thresholds frozen before holdout scoring | Dated protocol revision and reviewer approval | Data lead, statistics reviewer, marine ecologist, and product owner | Blocked |

Failure or expiry of any applicable gate stops collection. Nothing in this protocol permits an output-capable projector or an active synchronization sound.

## Study units and identifiers

The primary provenance unit is a continuous recording, not an extracted clip.

- `site_id`: stable code for one approved farm/site; no public coordinates in ordinary manifests unless approved.
- `local_date`: date at the site, with timezone recorded separately.
- `recording_id`: stable ID for one uninterrupted acquisition run.
- `audio_channel_id` and `video_stream_id`: source identities linked to calibration and clock records.
- `segment_id`: derived review window; start/end offsets point back to the immutable recording.
- `event_id`: one candidate or observed event with all annotations and evidence links.
- `deployment_id`: mount geometry, depth, orientation, clock, and environmental context for a recording run.

Every derived clip keeps the source recording checksum, exact offsets, transformation version, and synthetic/field provenance. Synthetic data must never be relabeled as field data.

## Acquisition design to freeze after an authorized exploratory pilot

No final component, sample rate, bandwidth, channel count, or geometry is selected in this draft. After all site permissions and operational-safety gates pass, a bounded exploratory passive pilot may use conservatively selected borrowed or rented receive gear and specialist-approved initial settings to measure local signals and noise. Those settings, data, and limits must be labeled exploratory; they do not select product hardware or set the final dataset protocol.

| Parameter | Required decision | Owner | Current value |
|---|---|---|---|
| Receive bandwidth and sample rate | Cover measured local signal and alias/filter margin without adopting the historical pinger range | Underwater-acoustics specialist and data lead | TBD |
| Hydrophone sensitivity, self-noise, dynamic range, calibration, and uncertainty | Support comparable receive measurements over the declared band | Underwater-acoustics specialist | TBD |
| Channel count and geometry | Start from event detection needs; add synchronized channels only if a justified localization or noise-rejection requirement exists | Acoustics specialist and product owner | TBD |
| Camera field of view, frame rate, low-light method, and visibility threshold | Provide useful ground truth without presenting invisible periods as predator absence | Data lead and marine ecologist | TBD |
| Clock source, offset, drift, and resynchronization | Bound audio/video/observer alignment without acoustic emission | Data lead | TBD |
| Mount distance, depth, orientation, isolation, and retrieval | Limit flow, cable, handling, structure-borne, and farm-operation noise while meeting site safety rules | Marine/mechanical engineer with site partner | TBD |
| Session length, daily coverage, season coverage, and storage | Capture feeding periods and hard negatives across relevant conditions | Statistics reviewer, farm partner, and data lead | TBD |
| Environmental context | Record at least the approved variables needed to interpret detectability and confounding | Marine ecologist and data lead | TBD |

A short authorized pilot recording may be used only to characterize noise and choose these settings. Its data cannot silently become model evaluation data.

## Collection procedure

1. Before each session, verify the approved site/work window, gate status, equipment identity, mount geometry, available storage, clock status, and passive-only configuration.
2. Record a deployment log with personnel roles, local time/timezone, weather, sea state, water conditions available under the approved method, vessel activity, farm operations, visibility, and known noise sources.
3. Start audio and video using the approved non-emitting synchronization method. Record measured clock offset and uncertainty.
4. Maintain an observer log without prompting or attracting animals. Mark observed feeding, suspected feeding, handling, ropes/gear movement, boats, rain, snapping shrimp where identifiable, other species, occlusion, and equipment disturbance.
5. Preserve continuous source files. Candidate extraction must not discard quiet context or hard negatives.
6. Record clipping, dropped samples/frames, queue overflow, device restart, clock correction, camera obstruction, and observer absence as data-quality events.
7. End the session within the approved work window. Verify file closure and checksums before moving equipment or deleting any copy.
8. Quarantine files that lack permission, provenance, integrity, or required metadata. Do not use them for training or publication until the issue is resolved.
9. Copy data only to approved encrypted storage. Apply access and retention rules; do not upload bulk media to MQTT, LoRaWAN, or an unapproved cloud service.
10. Review incidents and near misses before the next session. Any safety, permission, ecological, or privacy concern pauses collection.

## Ground truth and annotation

### Label classes

- `confirmed_feeding`: synchronized visual or direct observer evidence meets the approved feeding definition.
- `probable_feeding`: evidence suggests feeding but misses one approved confirmation element; excluded from primary positive scoring unless the frozen analysis says otherwise.
- `non_feeding_biological`: fish or other fauna present without confirmed feeding.
- `anthropogenic_noise`: boat, handling, machinery, cable, rope, farm work, or other human source.
- `environmental_noise`: rain, waves, flow, sediment, snapping shrimp, or another approved local class.
- `unknown`: source cannot be resolved.
- `unusable`: clipping, corruption, timing failure, missing context, or visibility below the approved limit.

Each annotation stores annotator, timestamp/offset, class, confidence rule, evidence source, visibility, audio quality, disagreement, and adjudication. Annotators must be able to mark uncertainty. Missing video is not a negative label.

At least the frozen sample of primary evaluation events receives independent review by two qualified annotators. The statistics/ecology reviewers set that sample and disagreement threshold before holdout scoring.

## Train, validation, and holdout policy

1. Split at the continuous-recording group, never at neighboring clip windows.
2. No `recording_id` may appear in both model-development data and holdout data.
3. No local calendar day may appear in both model-development data and holdout data. This blocks leakage from repeated ambient conditions and farm operations.
4. If more than one site exists, reserve whole sites for holdout before making a cross-site performance claim. A one-site study must state that it tested one site only.
5. Keep repeated views or overlapping windows from one event in one partition.
6. Group deployments that share a continuous run or inseparable setup artifact in one partition.
7. Freeze and checksum the split manifest before threshold tuning or holdout scoring. Restrict holdout labels from developers until the evaluation is locked where practical.
8. Set train/validation/holdout proportions and minimum event/day/site counts only after the desk/site sampling model. They remain TBD; sparse data must not be hidden by clip multiplication.
9. A new site, sensor chain, annotation rule, or material processing change creates a new evaluation stratum and may require a new holdout.

## Baselines and evaluation

Evaluate simple methods before ML: time-domain amplitude/activity rules, band-energy rules chosen from training data, and other interpretable baselines approved by the acoustics/data reviewers. The current normalized-amplitude candidate detector can test the replay and provenance path; it is not a field detector claim.

Report at minimum:

- event precision and recall with confidence intervals;
- false alerts per recording hour and by hard-negative class;
- detectability or coverage by range where distance ground truth exists;
- performance by day, site, deployment, visibility, environmental condition, and farm activity;
- timing offset/drift and paired-video availability;
- clipped, dropped, malformed, or skipped input;
- compute time, memory, storage, and power when measured on the target platform;
- all exclusions and unusable data;
- error review for false positives and false negatives.

Numeric pass/fail thresholds, test-zone limits, sample sizes, and confidence bounds are TBD and must be frozen by the product owner, statistics reviewer, marine ecologist, and data lead before holdout scoring. The roadmap's example of 90% recall and no more than one false alert/hour is a discussion point, not an approved product threshold.

## Stop, revise, or proceed decision

- `Proceed`: passive events are separable on locked local data at the frozen threshold and collection remains lawful, safe, and operationally useful.
- `Revise`: evidence is promising but placement, modality, labeling, sampling, or hardware needs a bounded new study.
- `Stop acoustic detection`: events are not separable at useful range/conditions, ground truth cannot be collected, or permission/ethics constraints make the method unsuitable. Consider visual or operational monitoring rather than adding output power or model complexity.

The decision and negative findings are retained. Passing this protocol's passive gate does not unlock acoustic transmission; active work follows separate P3/P4 requirements.
