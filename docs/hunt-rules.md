# The spot-the-flaw 'hunt': rules and scoring

## The setup

- **Six dev hospitals**, released Friday night and the data are in folders with similar structure (see [data-card.md](data-card.md)).
- Each hospital hides **one or two planted problems** ("Waldos"). Some are about who the patients are, some about how they were scanned, some about how they were labeled, some about how the data was assembled.
- **At least one hospital is clean.** Saying so, with evidence, is a correct answer.
- **Two tutorial answer keys** are released Friday night so you can calibrate your tool.
- **All dev answer keys** are released Saturday evening, with a full reference panel of standard measures. See what you missed and tune.
- **Three hidden hospitals** arrive Sunday morning. No keys. This is the real test.

## Posting a find

Post finds to the Waldo board (link at kickoff). Each find names:

1. The hospital
2. The **kind** of problem (for example: label prior, acquisition or scanner, labeling convention, population, clustering or duplication, shortcut)
3. Severity, if the hospital has more than one problem or you are comparing hospitals
4. One or two sentences of evidence a clinician could follow

## Scoring

| Criterion | Weight | Judged by |
| --- | --- | --- |
| Usefulness to your chosen customer | 40% | That customer |
| Hunt score: correct finds on dev and hidden hospitals, minus false alarms | 25% | Sealed answer keys |
| Clear to a non-ML reader | 20% | Panel, including a clinician |
| Reusable and open: runs on someone else's data, documented | 15% | Panel |

**False alarms cost points.** Flagging a clean hospital as broken is penalized. There is a small extra prize for the best "this hospital is clean" call.

**Naming the kind of problem matters.** "Hospital 4 is different" earns little. "Hospital 4 measures aneurysms differently, and here is how we know" earns a lot.

## Spirit of the thing

The strongest submissions tend to find something unflattering and report it honestly, explain results so a non-ML reader can act on them, and can be reproduced by someone else quickly.
