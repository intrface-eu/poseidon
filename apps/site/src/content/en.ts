/**
 * English copy for every page.
 *
 * Two kinds of string live here:
 *
 * - `claims`: every sentence that states a fact. Each id must have an entry in
 *   `claims.json` naming its sources; `tests/claims.test.ts` fails the build
 *   otherwise. Citations are added by the renderer from the register, never
 *   typed into the text.
 * - everything else: headings, labels, actions and framing. These must carry
 *   no figures; a number in a non-claim string fails the test, because a
 *   number is a fact and facts need a source.
 *
 * Inline markup: `*italic*`, `**bold**`, `[text](href)`. A Croatian version
 * is a second module with the same shape (`Copy`).
 */

export const en = {
  locale: 'en',
  htmlLang: 'en',
  ogLocale: 'en_GB',

  meta: {
    siteName: 'Poseidon Trident',
    home: {
      title: 'Poseidon Trident: an open listening unit for shellfish farms',
      description:
        'Wild seabream strip farmed mussels off their ropes. Poseidon Trident is an open-source listening unit that will record when they feed. We are looking for farms, scientists and funding.',
    },
    press: {
      title: 'Press kit · Poseidon Trident',
      description:
        'Boilerplate text, a fact sheet, answers to common questions, images and contact for journalists writing about Poseidon Trident.',
    },
    sources: {
      title: 'Sources · Poseidon Trident',
      description: 'Every external fact on the Poseidon Trident pages, with its source and the date we last opened it.',
    },
    evidence: {
      title: 'In the repository · Poseidon Trident',
      description:
        'Where each piece of Poseidon Trident software and design lives in the public repository, so you can read it and run it.',
    },
    notFound: {
      title: 'Page not found · Poseidon Trident',
      description: 'This address does not lead to a Poseidon Trident page. The project page, the press kit and the sources are linked from here.',
    },
    ogImageAlt:
      'Poseidon Trident: a design render of the solar surface unit on its pole at a mussel farm, above and below the waterline, with the headline about seabream.',
  },

  nav: {
    label: 'Main',
    home: 'Poseidon Trident home',
    problem: 'Problem',
    how: 'How it works',
    plan: 'Plan',
    press: 'Press',
    partner: 'Partner with us',
    skip: 'Skip to content',
    byline: 'by',
  },

  actions: {
    partner: 'Partner with us',
    readPlan: 'Read the plan',
    repo: 'Code and designs on GitHub',
    writeAbout: 'Email us about this',
    copy: 'Copy',
    copied: 'Copied',
    copyFailed: 'Select the text to copy it',
    download: 'Download',
    allSources: 'All sources, with the date each was checked',
    explode: 'Take it apart',
    assemble: 'Put it back together',
    dragHint: 'Drag to turn it.',
    backHome: 'Back to the project page',
    newTab: 'opens in a new tab',
  },

  claims: {
    /* Hero */
    'hero-headline': 'Wild seabream are stripping the Adriatic’s mussel farms.',
    'hero-lead':
      'Poseidon Trident is an open-source listening unit for shellfish farms. It will record when the fish come to feed, so farmers and scientists have numbers before anyone tries to stop them.',
    'hero-want': 'We are looking for farms, scientists and funding to put the first units in the water in Lim bay, Istria.',
    'hero-caption':
      'Design model of the surface unit on its pole at a mussel longline, with the listening head below the waterline. Not yet built.',

    /* The problem */
    'problem-heading': 'Seabream eat the mussels off the ropes',
    'fig-ropes-title': 'Two in three new ropes, gone in a month',
    'problem-who':
      'Gilthead seabream (*Sparus aurata*, orada in Croatian) eat farmed mussels straight off the ropes.',
    'problem-ropes':
      'A year-long study of six of Croatia’s most productive mussel farms found that, on average, two of every three new mussel ropes were destroyed within their first month in the sea, with the worst damage in summer and autumn.',
    'problem-young': 'On one eastern Adriatic farm, seabream took 54% of young mussels in a month.',
    'problem-night':
      'In April 2023, seabream ate about 3.5 tonnes of mussels from one Mali Ston bay farm in a single night.',
    'problem-value': 'In 2008 and 2009, losses in Croatia’s main shellfish region were valued at about €1 million.',
    'fig-ropes':
      'On average, 66% of new mussel ropes on six Croatian farms were destroyed within their first month in the sea. Each mark is one rope in a hundred.',
    'problem-france': 'In a survey of French Mediterranean farmers, 93% reported heavy losses they blamed on fish.',
    'problem-spezia': 'A mussel cooperative near La Spezia, Italy, lost 95% of its 2024 production.',
    'problem-common':
      'Wild seabream have become more common in the Adriatic, helped by escapes from fish farms and warmer water.',
    'problem-fidelity': 'In a French lagoon, tagged large seabream came back to the same farm year after year.',
    'fig-output':
      'Croatian mussel output, in tonnes. Researchers name seabream as one of the causes of the fall. The 2025 figure is provisional.',
    'problem-small': 'Most Croatian shellfish comes from small, family-run farms.',
    'problem-2025':
      'In 2025 the country farmed 821 tonnes of mussels and 78 tonnes of oysters, sold for about €3.8 million, on provisional figures.',
    'problem-compensation':
      'Since January 2026 the state compensates mussel farmers for seabream damage, but only damage that is documented and reported, and only where the farmer shows that every lawful means of keeping the fish away was used.',
    'lim-geo': 'Lim bay (Limski kanal) in Istria is a narrow inlet, 32 m deep at most and about 650 m wide.',
    'lim-farming':
      'Mussels and oysters are farmed in its inner part, and it is one of the few places where the native flat oyster survived.',
    'lim-reserve':
      'It has been a special marine reserve since 1980, and fishing is banned there, so the seabream cannot be fished out.',
    'lim-last-farmer':
      'In 2022, the last shellfish farmer on the channel said seabream sometimes take whole mussel lines.',
    'lim-no-figure': 'We have no measured loss figure for Lim bay. Getting one is part of the work.',
    'fix-nets':
      'Nets and protective bags keep fish off, but they foul fast, slow the water that feeds the mussels, stunt growth and get in the way at harvest.',
    'fix-nets-heavy': 'In Mali Ston bay, farmers report nets too heavy to lift after a month.',
    'fix-nets-cost': 'Handling and cleaning barriers is often the largest production cost.',
    'fix-fishing':
      'Fishing out the seabream is banned in protected water such as Lim bay. Elsewhere it is costly and labour-intensive, and a targeted attempt in Mali Ston bay failed.',
    'fix-sound-lim':
      'In 2019, six commercial acoustic deterrents at two Lim bay mussel farms kept the fish off for about two weeks. Once the sea passed 22 °C, the protected lines were eaten as before, and the researchers judged the devices ineffective.',
    'fix-sound-elsewhere':
      'In France, seabream got used to an acoustic deterrent; in Italy, ultrasound trials failed for the same reason. No published study shows an acoustic deterrent working on a bivalve farm.',
    'missing-data': 'What is missing is data: when, where and how often seabream feed on a given farm.',
    'missing-why':
      'Without it, a farmer cannot tell whether a fix works, a researcher cannot design a fair test, and a claim for compensation rests on what the farmer saw.',

    /* How it works */
    'how-listen': 'A passive listening unit hangs on the lines. It makes no sound and changes nothing in the water.',
    'how-measure':
      'It records sound and video through a whole season. Each sound is matched to what the camera saw and logged by time, place and water temperature, then checked by a marine biologist.',
    'how-test':
      'Only if the data justify it, and only as a separate study with scientists, permits and control lines. The plan below says how.',
    'how-eagle-rays':
      'Listening can work. Researchers have heard eagle rays crushing shells above background noise at up to 100 m, and could tell the prey apart by sound.',
    'how-no-recording':
      'We found no published recording of seabream feeding on a shellfish farm. Making one is our first job.',
    'how-value':
      'Monitoring is useful on its own. A farmer who knows when the fish arrive can time seeding, harvest and net checks around them.',
    'unit-parts': 'The unit has two parts joined by a cable.',
    'unit-surface':
      'The **surface unit** sits above the water on a pole or a float: a flat tray with two solar panels on top and a sealed box underneath holding the battery, a small computer, storage and a mobile-data radio. Nothing in it goes under water.',
    'unit-head':
      'The **listening head** hangs below, beside the shellfish lines: a sealed aluminium tube, 112 mm across and 300 mm long, holding a hydrophone (an underwater microphone) and a small camera behind a clear dome.',
    'unit-flow':
      'The computer flags sounds that stand out from the background, keeps a clip around each one and sends a short summary to shore over the mobile network. A person then reviews the clip, watches the video and records what happened: feeding, something else, or unclear.',
    'unit-sensors':
      'Small solar sensor boards on the farm report water temperature and battery state over a low-power radio link.',
    'unit-listens-only': 'The unit only listens. It has no loudspeaker.',
    'head-caption': 'Design model of the listening head, 112 mm across and 300 mm long. Not yet built.',
    'part-dome': 'Clear dome at the front, with the camera looking out through it.',
    'part-hydrophone': 'Hydrophone on a non-metal bracket inside the head.',
    'part-tube': 'Sealed aluminium tube with flanges and end caps.',
    'part-cable': 'Cable entry and strain relief for the line to the surface unit.',
    'part-clamp': 'Clamp that holds the head on a farm line, with pins a diver can pull.',

    /* Where it stands */
    'today-detector': 'A detector that reads recorded audio and flags loud events.',
    'today-hub': 'A local database and hub that keep every event linked to its recording.',
    'today-review':
      'A web app where a person reviews each event, its waveform and any video, and records what they saw.',
    'today-telemetry': 'Telemetry that carries sensor readings over LoRa radio and MQTT.',
    'today-firmware': 'Firmware for the small sensor boards, tested on a computer.',
    'today-scheduler': 'Scheduler code for a later, approved sound trial, which keeps sound output switched off.',
    'today-hardware':
      '3D designs of the surface unit, in pole and float versions, and of the listening head.',
    'today-research':
      'Desk research on underwater acoustics, marine hardware and EU product rules, with more than a hundred cited sources.',
    'today-limits':
      'So far the software has run only on computer-generated recordings. The detector flags loudness; it cannot yet tell a seabream from a boat. No unit has been built or put in water, and every physical test, from leaks and pressure to power and heat, is still to do.',
    'next-access': 'Agree access with Lim bay farms and obtain the permissions a listening unit needs in the reserve.',
    'next-build': 'Build two units and record the first season of feeding, with video.',
    'next-answer':
      'Answer the first question: can feeding be heard and told apart from boats, ropes and snapping shrimp?',
    'stage-1-body':
      'Farm access and permissions, a recording plan agreed with a marine biologist, two units built and bench-tested, and the first recordings from Lim bay farms with video of what the fish do.',
    'stage-1-end': 'Can feeding be heard and told apart from boats, ropes and shrimp?',
    'stage-2-body':
      'Five units on two or three farms, in Lim bay and elsewhere in Istria, through a full predation season, with a detector tested against what the cameras saw and physical tests of the hardware.',
    'stage-2-end':
      'A record of when and where seabream feed, and a decision on whether monitoring is a product farms want.',
    'stage-3-body':
      'This is where deterrence comes in, as the research question we want funded: can any response, sound or otherwise, reduce feeding on the lines for more than a few days? Studies of fish and seals report that animals get used to deterrent sounds, and young seabream stopped reacting to low-frequency noise within about two hours. So the test runs with a fish-behaviour lab, its own permits and untreated control lines.',
    'stage-3-end': 'It may show that nothing works for long. That is a result too.',
    'stage-1-months': 'About 6 to 9 months',
    'stage-2-months': 'About 9 to 12 months',
    'stage-3-months': 'About 12 to 18 months',
    'stage-1-cost': '€49,000 to €83,000',
    'stage-2-cost': '€100,000 to €155,000',
    'stage-3-cost': '€85,000 to €164,000',
    'budget-total': 'Stages 1 and 2 together, the monitoring work: €149,000 to €238,000.',
    'budget-unit': 'Parts for one prototype unit: about €3,000 to €4,200.',
    'budget-basis':
      'Every figure is our estimate, built from published supplier prices and planning rates we set ourselves. None is a quote, and all exclude VAT.',

    /* The ask */
    'ask-lead':
      'Poseidon Trident needs farms, scientists, engineers and money. Each line below says what you get and what we ask of you.',
    'ask-farms-get':
      'The first units on your lines at no cost to you, and a season’s record of when and where seabream feed on your stock.',
    'ask-farms-need':
      'Written access for listening only, one or two lines where a unit can hang, boat access on service days, and your own records of losses. Lim bay first; Mali Ston bay, the Novigrad sea and the Italian and Slovenian coasts one stage later.',
    'ask-biology-get':
      'A new field dataset of seabream on working farms with synchronised sound and video, co-authorship, and a named, budgeted role in the grants we write together.',
    'ask-biology-need':
      'A scientist who knows gilthead seabream behaviour to design the recording study and label feeding on video.',
    'ask-acoustics-get':
      'Long recordings from a sheltered bay at shellfish farms, and an open-source recording and review system you can reuse.',
    'ask-acoustics-need':
      'Advice on the hydrophone, its placement and its calibration, and a review of how we tell feeding sounds from boats, ropes and snapping shrimp.',
    'ask-engineers-get': 'Paid contract work on open hardware, credited in the repository.',
    'ask-engineers-need':
      'Electronics: a review of power, charging and protection, and firmware moved onto real boards. Marine: seals, cable entry, corrosion, mounts, and pressure and leak testing.',
    'ask-permits-get': 'Paid advisory work and a clear brief.',
    'ask-permits-need':
      'The permissions a listening unit needs in Lim bay, a special marine reserve, and who issues each one, from nature protection to maritime rules and camera data.',
    'ask-making-get':
      'An open design ready for a small batch, and first right to build and sell units under the open hardware licence.',
    'ask-making-need': 'A design-for-manufacture review and quotes for a batch of five to ten units.',
    'ask-grants-get':
      'A partner that brings a working software stack, open hardware designs, a pilot site and a written research base, and does the engineering and much of the writing.',
    'ask-grants-need':
      'To apply with us where a call needs a farm, a scientific body or partners from several countries: the fisheries fund, Horizon Europe and Interreg.',
    'ask-investors-get':
      'An early position in a company working on a measured problem in European shellfish farming, with open designs and a partner network around them. Terms to be agreed.',
    'ask-investors-need':
      'Money for the months grants do not cover, introductions to farms, labs and buyers, and patience with a timeline set by fish seasons.',
    'ask-public-get':
      'Public money turned into open code, open hardware designs, open data where farms agree, and published results, negative ones included.',
    'ask-public-need': 'Funding for stage 1, estimated at €49,000 to €83,000, and for the pilot season after it.',

    /* Team, company, open source */
    'team-company':
      'Poseidon Trident is a project of INTRFACE j.d.o.o., a small engineering company in Vrsar, Istria, a few kilometres from Lim bay.',
    'team-alex':
      'Alex Bašić, founder and director, designed and built the software and the hardware designs, and maintains the project.',
    'team-grow': 'Scientific and engineering partners will join as the project moves into the water.',
    'company-registration':
      'INTRFACE j.d.o.o., registered with the Commercial Court in Pazin, MBS 130172611, OIB 34363240459.',
    'open-licences':
      'Everything is public: code under the GNU Affero General Public License 3.0 or later, hardware designs under the CERN Open Hardware Licence, strongly reciprocal, version 2, and documentation under Creative Commons Attribution 4.0.',
    'open-why':
      'Any farm, lab or company can study the design, build it, improve it and share the changes. Research on a public problem should stay public.',
    'open-contribute':
      'To take part, open an issue before a large change, sign off each commit, and send the change as a pull request. The contributing guide lists the setup and the checks.',

    /* Press */
    'press-50':
      'Poseidon Trident is an open-source listening unit for shellfish farms, built by INTRFACE j.d.o.o. in Vrsar, Croatia. It is designed to record when wild gilthead seabream feed on farmed mussels and oysters, starting in Lim bay, Istria. The software works on test data; the hardware is designed but not yet built.',
    'press-150a':
      'Poseidon Trident is an open-source listening unit for shellfish farms, built by INTRFACE j.d.o.o., an engineering company in Vrsar, Istria. Wild gilthead seabream (orada) strip farmed mussels from their ropes; on Croatian farms, two-thirds of newly seeded ropes have been lost within a month. Nets foul and slow growth; fishing is banned in protected water such as Lim bay; underwater sound deterrents tried there worked for about two weeks.',
    'press-150b':
      'Poseidon Trident starts by measuring the problem. In the design, a solar surface unit on a pole or float carries a sealed head with a hydrophone and a camera beside the shellfish lines. It records sound and video, flags events for a person to review, and makes no sound itself. The software stack runs end to end on test data; the hardware exists as 3D designs. The next step is the first field recordings with farms and marine scientists. Code, hardware designs and documentation are open source.',
    'qa-stop':
      'No, and it is not meant to yet. It listens and records. Earlier attempts to scare seabream off with sound, including a 2019 trial in Lim bay, worked for a couple of weeks and then failed. We want to understand the problem before offering a fix.',
    'qa-nets':
      'Many farms already use nets and protective bags. They foul, slow the mussels’ growth and get in the way at harvest. Listening tells a farmer when and where the fish come, which helps with any method, nets included.',
    'qa-recognise':
      'Not yet. Today the software flags loud events and a person reviews the video to say what happened. Telling seabream apart from boats, ropes and shrimp needs real recordings from the farms, which is the first job of the next stage.',
    'qa-tested':
      'No. The software has been tested on computer-generated recordings. The hardware exists as 3D designs and has not been built. The first units go in the water once farms and permits are in place.',
    'qa-safe':
      'The unit makes no sound. It sits in the water like any other piece of farm gear, and it will only go in with the permissions the reserve requires. Any future test of sound would need a separate permit, a specialist lab and control lines, and we will not do it otherwise.',
    'qa-open':
      'Seabream predation is a shared problem across the Mediterranean, and the farms that suffer it are small. Open designs let any farm, lab or company build, check and improve the unit, and public money should produce public results.',
    'qa-cost':
      'We estimate the parts for one prototype at about €3,000 to €4,200. A production price depends on volume and on what the pilot season shows, so we do not have one yet.',
    'qa-need':
      'Farms willing to host a unit, a marine biology partner, and funding for the first stage, which we estimate at €49,000 to €83,000.',
    'fact-site': 'Lim bay (Limski kanal), Istria, Croatia: mussel and oyster farms in a special marine reserve.',
    'fact-problem': 'Gilthead seabream (*Sparus aurata*, orada) feeding on farmed mussels and oysters.',
    'fact-what':
      'A passive listening unit: a solar surface unit on a pole or float, with a sealed underwater head holding a hydrophone and a camera.',
    'fact-status':
      'Software works end to end on computer-generated test recordings. Hardware designed in 3D, not built. No field recordings yet. No sound output.',
    'fact-next': 'First field recordings on Lim bay farms, with a marine biology partner.',
  },

  /**
   * Figure data. Numbers are allowed here only because every figure names the
   * claim that sources it; the test checks that link.
   */
  figures: {
    ropes: { claim: 'fig-ropes', total: 100, lost: 66, lostLabel: '66 destroyed', keptLabel: '34 left' },
    output: {
      claim: 'fig-output',
      unit: 'tonnes',
      rows: [
        { label: '2008', value: 3000, text: '3,000' },
        { label: 'End of the 2010s', value: 920, text: 'about 920' },
        { label: '2025, provisional', value: 821, text: '821' },
      ],
    },
    stages: {
      claim: 'stage-1-months',
      axisMax: 18,
      ticks: [0, 6, 12, 18],
      rows: [
        { min: 6, max: 9 },
        { min: 9, max: 12 },
        { min: 12, max: 18 },
      ],
    },
  },

  home: {
    hero: {
      stageLabel: 'The unit at a mussel farm',
      posterAlt:
        'Design model: a solar tray on a pole above the water among the longline buoys, and below the waterline the mussel ropes, a few seabream and the listening head on its line.',
    },
    problem: {
      whoLoses: 'Who loses',
      limHeading: 'Lim bay, where we start',
      fixesHeading: 'Why today’s fixes fall short',
      fixNets: 'Nets and bags',
      fixFishing: 'Fishing them out',
      fixSound: 'Sound devices',
      ropesLost: 'destroyed',
      ropesKept: 'left',
      outputTitle: 'Croatian mussel output',
    },
    how: {
      heading: 'Listen first, measure, then test responses',
      steps: [
        { title: 'Listen', claim: 'how-listen' },
        { title: 'Measure', claim: 'how-measure' },
        { title: 'Test responses', claim: 'how-test' },
      ],
      unitHeading: 'The unit',
      headHeading: 'Inside the listening head',
      headStageLabel: 'Listening head, 3D design model',
      headPosterAlt:
        'Design model of the listening head: an aluminium tube with a clear dome at one end, a clamp for the farm line on its side and a cable leaving the other end.',
    },
    plan: {
      heading: 'Where the project stands',
      todayHeading: 'Works today',
      nextHeading: 'Comes next',
      stagesHeading: 'The plan, in three stages',
      stageLabel: 'Stage',
      stages: [
        { title: 'First recordings and a prototype build', claimPrefix: 'stage-1' },
        { title: 'One pilot season', claimPrefix: 'stage-2' },
        { title: 'Behaviour trials, only if justified', claimPrefix: 'stage-3' },
      ],
      duration: 'Duration',
      cost: 'Estimate',
      endsWith: 'Ends with',
      monthsAxis: 'months',
    },
    ask: {
      heading: 'Partner with us',
      getLabel: 'You get',
      needLabel: 'We need',
      subjectPrefix: 'Poseidon Trident',
      cards: [
        { id: 'farms', title: 'Shellfish farms', subject: 'Hosting a unit on our farm' },
        { id: 'biology', title: 'Marine biologists and fish-behaviour scientists', subject: 'Marine biology partner' },
        { id: 'acoustics', title: 'Bioacoustics and underwater acoustics labs', subject: 'Acoustics lab partner' },
        { id: 'engineers', title: 'Electronics and marine engineers', subject: 'Engineering work' },
        { id: 'permits', title: 'Permitting advisors', subject: 'Permitting advice' },
        { id: 'making', title: 'Manufacturing partners', subject: 'Manufacturing partner' },
        { id: 'grants', title: 'Grant co-applicants', subject: 'Applying for a grant together' },
        { id: 'investors', title: 'Angel and impact investors', subject: 'Investing' },
        { id: 'public', title: 'Public funders', subject: 'Public funding' },
      ],
      fullList: 'The full partner list, funding routes and the costed budget are in the repository',
    },
    team: {
      heading: 'Who is behind it',
      companyLink: 'INTRFACE, the company',
    },
    open: {
      heading: 'Open from code to hardware',
      repoLink: 'The repository',
      contributeLink: 'The contributing guide',
      licencesLink: 'Licences and ownership notice',
    },
    sources: {
      heading: 'Sources for this page',
    },
    contact: {
      heading: 'Write to us',
      lead: 'Farms, scientists, engineers, funders and journalists: every message reaches the founder directly.',
      role: 'founder and director',
      addressLabel: 'Company',
      linksLabel: 'More',
    },
  },

  press: {
    heading: 'Press kit',
    lead: 'For interviews, images and data, write to Alex Bašić.',
    shortHeading: 'Short description',
    longHeading: 'Longer description',
    factsHeading: 'Fact sheet',
    facts: {
      project: 'Project',
      company: 'Company',
      address: 'Address',
      registration: 'Registration',
      director: 'Director and maintainer',
      site: 'First site',
      problem: 'Problem',
      what: 'What it is',
      status: 'Status',
      next: 'Next step',
      licences: 'Licences',
      repository: 'Repository',
      website: 'Website',
      contact: 'Contact',
    },
    companyType: 'simple limited liability company',
    licenceLine: 'Code: {code}. Hardware: {hardware}. Documentation: {docs}.',
    qaHeading: 'Questions journalists ask',
    questions: [
      { q: 'Does it stop the fish?', claim: 'qa-stop' },
      { q: 'Why listen, rather than just put up nets?', claim: 'qa-nets' },
      { q: 'Can it recognise a seabream by sound?', claim: 'qa-recognise' },
      { q: 'Has it been tested in the sea?', claim: 'qa-tested' },
      { q: 'Is it safe for the reserve and for other animals?', claim: 'qa-safe' },
      { q: 'Why open source?', claim: 'qa-open' },
      { q: 'What will a unit cost?', claim: 'qa-cost' },
      { q: 'What do you need now?', claim: 'qa-need' },
    ],
    imagesHeading: 'Images',
    imagesLead:
      'Renders are design models, not photographs, and are captioned that way. Photographs of farms follow once units are built, and only with the farm’s and the photographer’s permission.',
    assets: {
      hero: 'The unit on its pole at a mussel farm, above and below the water',
      farm: 'The farm: longlines, buoys and mussel ropes',
      unit: 'The surface unit with its two solar panels',
      'head-exploded': 'The listening head taken apart',
      'logo-light': 'Logo, for light backgrounds',
      'logo-dark': 'Logo, for dark backgrounds',
    },
    comingSoon: 'Coming with the next render set',
    /** `{licence}` is filled from site.ts. */
    credit: 'Render: INTRFACE, {licence}',
    contactHeading: 'Press contact',
  },

  notFound: {
    heading: 'This page is not here',
    lead: 'The address may be mistyped, or the page has moved. These are the pages we have:',
    links: {
      home: 'The project: what it is and what we need',
      press: 'Press kit',
      sources: 'Sources',
      evidence: 'What is in the repository',
    },
  },

  sourcesPage: {
    heading: 'Sources',
    lead: 'Every external fact on these pages, with the source it comes from and the date we last opened it. Where we read only an abstract or a third-party summary, the entry says so.',
    groups: {
      S: 'The problem, the site and prior work',
      P: 'Prices used in the budget',
      F: 'Funding routes',
    },
    id: 'ID',
    source: 'Source',
    link: 'Link',
    accessed: 'Checked',
  },

  evidencePage: {
    heading: 'What is in the repository',
    lead: 'Each statement on the project page about the software and the designs points to the part of the public repository behind it. Read the code, run the checks, or open an issue.',
    linksLabel: 'In the repository',
  },

  footer: {
    project: 'A project of',
    licences: 'Code AGPL-3.0-or-later · Hardware CERN-OHL-S-2.0 · Text CC-BY-4.0',
    press: 'Press kit',
    sources: 'Sources',
    evidence: 'Evidence',
    github: 'GitHub',
  },
};

export type Copy = typeof en;
export type ClaimId = keyof Copy['claims'];
