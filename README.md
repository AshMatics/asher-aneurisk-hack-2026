# IID Is a Lie: Build the Open-Source Audit Toolkit for Medical AI Training Data

Sponsor problem for the 2026 Nucleate hackathon, presented by **Asher Informatics PBC** and **Aneurisk Inc.**

> Status: under construction. Data, starter kit and harness land before the event. Watch this repo.

## The problem in one paragraph

Nearly every medical AI model assumes its training and test data are independent and identically distributed (IID). Usually that gets justified with "we shuffled it." In practice, many scans come from the same patient, hospitals use different scanners and protocols, and readers measure the same finding differently. Left unmeasured, these problems produce impressive accuracy that fails quietly on the patients, sites and subgroups that matter most. Tools like Cleanlab catch label errors and duplicates. Nothing open and practical answers the bigger questions: can this dataset support the claims made about it, how much real evidence is in a pile of correlated scans, and does the training data resemble the patients a model will serve?

## The weekend

**The hook.** One abdominal aortic aneurysm (AAA) model, three scores: random split, patient-level split, hospital-level split. Which number would the paper report?

**The hunt.** You get six virtual hospitals built from real abdominal CT. Each hides at least one planted problem. One is clean. Find them, name what kind of problem each is, and explain it so a vascular surgeon would act on it. Three more hospitals arrive Sunday morning with no answers attached. See [docs/hunt-rules.md](docs/hunt-rules.md).

**The customers.** Pick one and build for them. They are in the room all weekend. See [docs/personas.md](docs/personas.md).

| Customer | Their question |
| --- | --- |
| Regulated developer | "Characterize my test and external validation cohorts for my regulatory and clinical team." |
| Hospital AI committee | "Will this AAA model work on our patients, and what should we watch after go-live?" |
| Data network | "I have six hospitals and can't move their data. Can I audit them anyway?" |

**The form is yours.** A library, a report generator, an agent that interrogates a dataset, a visualization, a deployment-match tool, or something we haven't thought of.

## The data (preview)

Abdominal CT drawn from public datasets, resampled into virtual hospitals with heterogeneity we defined in advance.

- **Fast lane (default):** per-case tables, image embeddings, baseline model predictions. Under five minutes from download to first result.
- **Deep lane (opt-in):** full CT volumes (NIfTI), a small DICOM sample with real headers, and an imaging 101 notebook. Some problems are only visible in the pixels.

Schema: [docs/data-card.md](docs/data-card.md).

## Compute

Organizers are arranging per-team GPU cloud credits and per-participant LLM inference and search API credits. Details will be posted here once confirmed.

## Repo layout

```
docs/       problem background, personas, hunt rules, data card, measures reference
harness/    federated audit harness: run your audit inside each hospital, return only summaries
starter/    starter notebooks (coming)
data/       download instructions (data itself is hosted elsewhere)
```

## Background reading

- [docs/background.md](docs/background.md): what IID really assumes, effective sample size, a heterogeneity framework, prior work and gaps
- [docs/measures.md](docs/measures.md): published non-IID measures, what each sees and misses

## Ownership

Anything promising that comes out of the weekend, whether a research direction, a paper or a commercial idea, is yours to pursue. The work stays open, and nobody gets exclusive rights to it, sponsors included.
