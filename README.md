# IID Is a Lie: Build the Open-Source Audit Toolkit for Medical AI Training Data

Sponsor problem for the 2026 Nucleate hackathon, presented by **Asher Informatics PBC** and **Aneurisk Inc.**

> Start with [docs/getting-started.md](docs/getting-started.md): where the documents and data are, and how to download.

## The problem in one paragraph

Nearly every medical AI model assumes its training and test data are independent and identically distributed (IID). Usually that gets justified with "we shuffled it." In practice, many scans come from the same patient, hospitals use different scanners and protocols, and readers measure the same finding differently. Left unmeasured and mitigated, these problems produce impressive accuracy on test data sets but cause an AI system to perform very differently on data in a particular clinic. And often the performance is worse in sites and patient subgroups that can lead to further marginalization or biased care. Tools like Cleanlab catch label errors and duplicates in data cohorts. But there are few, if any, integrated tools that help answer the bigger questions: can this dataset support the claims made about it, how and in what ways does a training cohort violate the IID assumption, and does the training data resemble the patients a model will serve?

## The weekend

**The hunt.** You are given five practice hospitals built from real abdominal CT studies, assembled to look like data seen 'in the wild'. Most of them hide at least one flaw that would affect an AI model trained or tested on them. At least one is clean (or as close to our best assumptions about training data as we could make it). Find these flaws with your solution, name what kind of problem each is, and be able to explain these flaws such that a user (like a vascular surgeon) would understand its importance when using an AI trained, or tested, with those data. You get two more hospitals Sunday morning. See [docs/hunt-rules.md](docs/hunt-rules.md).

**The customers.** Pick one customer type and orient your solution to their persona needs. These customer types will be available to interact with throughout the weekend. See [docs/personas.md](docs/personas.md).

| Customer | Their question |
| --- | --- |
| Regulated developer | "Characterize my test and external validation cohorts for my regulatory and clinical team." |
| Hospital AI committee | "Will this AAA model work on our patients, and what should we watch after go-live?" |
| Data network | "I have six hospitals and can't move their data. Can I audit them anyway?" |

**You decide the form and function of the solution.** It could be purely an SDK/library, a report generator, an agent that interrogates a dataset, a visualization, a deployment-match tool, or a holographic projector.

## The data (preview)

Abdominal CT drawn from public datasets, resampled into virtual hospitals with heterogeneity and structure we established for this exercise.

- **Fast lane (default):** per-case tables, image embeddings, baseline model predictions. Under five minutes from download to first result.
- **Deep lane (opt-in):** CT volumes and aorta masks (NIfTI) for the same cases. Some problems are only visible in the pixels.

Schema: [docs/data-card.md](docs/data-card.md).

## Compute

Each team gets cloud GPU credits, and each participant gets LLM inference and search API credits. Details at kickoff.

## Repo layout

```
docs/       problem background, personas, hunt rules, data card, measures reference
harness/    federated audit harness: run your audit inside each hospital, return only summaries
starter/    starter notes
data/       download instructions (data itself is hosted elsewhere)
```

## Background reading

- [docs/background.md](docs/background.md): what IID really assumes, effective sample size, a heterogeneity framework, prior work and gaps
- [docs/measures.md](docs/measures.md): which method answers which audit question, and what published non-IID measures see and miss
- [docs/directions.md](docs/directions.md): possible directions, mapped to the three customers

## Ownership

Anything promising that comes out of the weekend, whether a research direction, a paper or a commercial idea, is yours to pursue. The work stays open, and nobody gets exclusive rights to it, sponsors included.
