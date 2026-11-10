# SlicePoint (from the IID Is a Lie hackathon)

The 2026 Nucleate Pittsburgh hackathon is over. This repo is now the home of **SlicePoint**, the runner-up project, which is being rebuilt here as open source. SlicePoint checks whether an imaging AI model fits a hospital's patients and scanners before go-live, and returns a GO / BORDERLINE / NO-GO verdict with the evidence behind it.

**To start, go to [slicepoint/README.md](slicepoint/README.md).** It has the quick start (install, run one assessment, open the report), the package map, and how to run the service with the live web UI. The practice data goes in `data/practice/` (see [data/README.md](data/README.md)).

The original hackathon brief is kept below for context.

---

# The hackathon brief: IID Is a Lie

Sponsor problem for the 2026 Nucleate Pittsburgh hackathon, presented by **Asher Informatics PBC** and **Aneurisk Inc.**

> [docs/README.md](docs/README.md) is the guide to the hackathon documents. For the data, go to [docs/getting-started.md](docs/getting-started.md).

## The problem

Nearly every medical AI model assumes its training and test data are independent and identically distributed (IID). Usually that gets justified with "we shuffled it." In practice, many scans come from the same patient, hospitals use different scanners and protocols, and readers measure the same finding differently. Left unmeasured and unmitigated, these problems produce impressive accuracy on test data sets but cause an AI system to perform very differently on data in a particular clinic. And often the performance is worse in sites and patient subgroups that can lead to further marginalization or biased care. Tools like Cleanlab catch label errors and duplicates in data cohorts. But there are few, if any, integrated tools that help answer the bigger questions: can this dataset support the claims made about it, how and in what ways does a training cohort violate the IID assumption, and does the training data resemble the patients a model will serve?

## The weekend

**Where's 'waldo' features .** You are given five practice hospitals built from real abdominal CT studies, assembled to look like data seen 'in the wild'. Most of them hide at least one flaw that would affect an AI model trained or tested on them. At least one is clean (or as close to our best assumptions about training data as we could make it). Find these flaws with your solution, name what kind of problem each is, and be able to explain these flaws such that a user (like a vascular surgeon) would understand its importance when using an AI trained, or tested, with those data. You get two more hospitals Sunday morning. See [docs/hunt-rules.md](docs/hunt-rules.md).

**The customers.** Pick one customer type and orient your solution to their persona needs. These customer types will be available to interact with throughout the weekend during scheduled office hours or ad hoc. Our notifications may be off at 3AM though. See [docs/personas.md](docs/personas.md).

| Customer | Their question |
| --- | --- |
| Regulated developer | "Characterize my test and external validation cohorts for my regulatory and clinical team." |
| Hospital AI committee | "Will this AAA model work on our patients, and what should we watch after go-live?" |
| Data network | "I have six hospitals and can't move their data. Can I audit them anyway?" |

**You decide the form and function of the solution.** It could be purely an SDK/library, a report generator, an agent that interrogates a dataset, a visualization, a deployment-match tool, or a holographic projector.

## The data (preview)

Abdominal CT drawn from public datasets, resampled into virtual hospitals with heterogeneity and structure we established for this exercise.

- **Fast lane (default):** per-case tables, image embeddings, baseline model predictions. Under five minutes from download to first result.
- **Deep lane (opt-in):** CT volumes and aorta masks (NIfTI) for the same cases. The images let you check, in the pixels, what the tables suggest.

Schema: [docs/data-card.md](docs/data-card.md).

## Compute

Each team gets cloud GPU credits, and each participant gets LLM inference and search API credits. Details at kickoff and see the Slack channel.

## Repo layout

```
slicepoint/ SlicePoint: schemas, core library + CLI, API, viewer, segmentation worker
docs/       hackathon documentation; start at docs/README.md
harness/    federated audit harness: run your audit inside each hospital, return only summaries
starter/    starter notes
data/       download instructions (data itself is hosted elsewhere)
```

## Background reading

Start with [docs/background.md](docs/background.md), then [docs/measures.md](docs/measures.md) and [docs/directions.md](docs/directions.md). The full list, with what each document is for, is in [docs/README.md](docs/README.md).

## Ownership

Anything promising that comes out of the weekend, whether a research direction, a paper or a commercial idea, is yours to pursue. The work stays open, and nobody gets exclusive rights to it, sponsors included.

## License

Code and documentation in this repo are under the [MIT License](LICENSE). The hackathon data is not in this repo and keeps its source licenses, listed in `CREDITS.md` inside each download.
