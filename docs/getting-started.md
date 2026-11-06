# Getting started: where everything is

One page. Read it first.

## 1. The problem

Everything about the problem lives in this repo:

| Read | For |
| --- | --- |
| [README](../README.md) | The problem in one paragraph and how the weekend runs |
| [personas.md](personas.md) | The three customers. Pick one. |
| [hunt-rules.md](hunt-rules.md) | The flaw hunt: what is released when, and how to post a find |
| [data-card.md](data-card.md) | Every file and column you will receive |
| [background.md](background.md), [measures.md](measures.md), [directions.md](directions.md) | Background reading and possible directions |

## 2. The data

The data is not in this repo. It sits in one cloud storage folder (Azure Blob). **The read-only link is given out at kickoff.** Do not post it publicly.

| When | Folder | What |
| --- | --- | --- |
| Friday evening | `practice/practice.zip` | Practice hospital tables and embeddings, plus answer keys for two hospitals |
| Friday evening | `practice/images/` | CT volumes and aorta masks for the same cases, one zip per hospital (large; optional) |
| Saturday evening | `practice/keys.zip` | Answer keys for the remaining practice hospitals, with reference measures |
| Sunday morning | `sunday/sunday.zip`, `sunday/images/` | The Sunday test hospitals. No answer keys. |

Each folder appears at its time. The same link works all weekend.

## 3. How to download

**Tables (a few MB): start here.** The tables and embeddings are enough for most analyses, and they open on any laptop.

- **Browser:** insert the file path into the link, right before the `?`. For example, `.../students/practice/practice.zip?se=...` downloads the practice tables.
- **Command line** (all files, including images): install [AzCopy](https://learn.microsoft.com/azure/storage/common/storage-use-azcopy-v10), then run

  ```bash
  azcopy copy "<link>" ./data --recursive
  ```

  Put the link in quotes. To skip the images, add `--exclude-path "practice/images"`.
- **Python:**

  ```python
  from azure.storage.blob import ContainerClient   # pip install azure-storage-blob
  c = ContainerClient.from_container_url("<link>")
  for b in c.list_blobs():
      print(b.name, b.size)
  ```

Unzip into `data/` in your clone of this repo. Git ignores that folder, so the data cannot be committed by accident.

**Images (large):** pull them to a cloud machine rather than your laptop.

## 4. Compute

Each team gets cloud GPU credits, and each participant gets LLM and search API credits. Details are handed out at kickoff.

## 5. Rules that matter for the data

- Use the data for this event only. Do not redistribute it.
- Do not try to match cases back to the public source datasets. The hunt is about finding flaws from the data you were given.
- For the data network customer, row-level data must not leave a hospital. That includes sending rows to an external LLM API. See [the harness](../harness/README.md).
- Sources and licenses are listed in `CREDITS.md` inside each download.

## 6. Questions

Ask in the event channel, or find the sponsors in person. The customers are available all weekend.
