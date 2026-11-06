# Guide to the documentation

Everything students need for the "IID Is a Lie" problem is in this repo. This page says what each document is for, which ones to read first, and which ones you can save for later.

The data itself is not in the repo. [getting-started.md](getting-started.md) says where it is and how to download it.

## If you read nothing else (about 20 minutes)

1. [The repo README](../README.md): the problem in one paragraph and how the weekend runs.
2. [getting-started.md](getting-started.md): where the data is, when each part is released, how to download it.
3. [personas.md](personas.md): the three customers. Your team picks one on Friday.
4. [hunt-rules.md](hunt-rules.md): the flaw hunt, and how to post a find.
5. [data-card.md](data-card.md): every file and column you will receive.

Then run the starter script ([starter/README.md](../starter/README.md)). It takes under a minute on a laptop and shows the core problem on real numbers.

## Every document

| Document | What it is | Read it when |
| --- | --- | --- |
| [README](../README.md) | The problem, the weekend, the customers, ownership of your work | First |
| [getting-started.md](getting-started.md) | Data location, release schedule, download commands, data rules | First |
| [personas.md](personas.md) | The regulated developer, the hospital AI committee and the data network: what each asks and what good looks like to them | Friday, before picking a direction |
| [hunt-rules.md](hunt-rules.md) | What is released when, how to post a find, how feedback works | Friday |
| [data-card.md](data-card.md) | Columns and types for features, labels, predictions and embeddings; the deep-lane images | When you open the data |
| [measures.md](measures.md) | Which method answers which audit question; published non-IID measures and what they miss; nulls and controls | When you start measuring |
| [directions.md](directions.md) | Example project shapes mapped to the customers, and a checklist for what to report | When choosing a direction, and again before you present |
| [background.md](background.md) | What IID assumes, effective sample size, a heterogeneity framework, text and VLMs, calibration, prior work, Cleanlab | When you want the why (about 30 minutes) |
| [technical-reference.md](technical-reference.md) | The long, careful version of background.md, with the conditions behind each claim and sources | When you need to be precise or cite something |
| [harness/README.md](../harness/README.md) | The federated audit harness: what may leave a hospital and how to run your audit inside it | Required if you build for the data network; useful for everyone |
| [starter/README.md](../starter/README.md) | Loading the tables, the example audit, and `hook.py` | Friday night |
| [data/README.md](../data/README.md) | Where to unzip downloads so git ignores them | When you download |

## Reading paths by background

You do not need to read everything. Pick the path closest to your team's skills, then fill gaps as questions come up.

- **ML or CS:** data-card, starter, measures, then background sections 1 to 3. Use the harness early if you might build for the data network.
- **Statistics or biostatistics:** background sections 1 and 2, then technical-reference on dependence, effective sample size and valid inference. The nulls and controls in measures.md are where you will catch other teams' mistakes.
- **Clinical, policy or design:** personas, hunt-rules, directions (especially the reporting checklist), then background section 6 on prior work. Your job is to decide what is worth measuring and make results readable to a surgeon or a committee, which is half the problem.
- **Imaging:** data-card's deep-lane section, then background section 2 on 3D CT. The images can confirm, or reveal, what the tables only hint at.

## Reading paths by customer

| Customer | Start with | Then |
| --- | --- | --- |
| Regulated developer | personas.md section 1, background section 2 (effective sample size, honest evaluation) | measures.md, the reporting checklist in directions.md |
| Hospital AI committee | personas.md section 2, data-card subgroups | measures.md (question-to-method table), background section 3 |
| Data network | personas.md section 3, harness/README.md | measures.md (what can be computed from summaries), background section 6 on federated learning |

## Over the weekend

| When | What changes | Docs that matter |
| --- | --- | --- |
| Friday evening | Kickoff; practice data and two tutorial answer keys released; pick a customer | getting-started, personas, hunt-rules, data-card |
| Saturday morning | Check-ins with your customer | personas, directions |
| Saturday evening | Remaining practice answer keys released | hunt-rules |
| Sunday morning | Two new hospitals, no answer keys | hunt-rules, measures (nulls and controls) |
| Before you present | | directions.md checklist |

## Questions

Ask in the event channel, or find a sponsor mentor on Slack or in person. If a document is wrong or unclear, tell us, or open an issue on this repo.
