# Getting started: where everything is

One page, yo.  Read me first!!

## 1. The problem

Everything about the problem statement and why/how pose it lives in this repo:

| Read | For |
| --- | --- |
| [README](../README.md) | The problem in one paragraph and how the weekend runs |
| [personas.md](personas.md) | The three customers. Pick one. |
| [hunt-rules.md](hunt-rules.md) | The flaw hunt: what is released when, and how to post a find |
| [data-card.md](data-card.md) | Every file and column you will receive |
| [background.md](background.md), [measures.md](measures.md), [directions.md](directions.md) | Background reading and possible directions |

## 2. The data

The data are not in this repo. They sit in a cloud storage folder (an Asher Informatics Azure Blob). **The read-only link is given out at kickoff.** Do not post it publicly please. It is segregated from our dev and prod resources, but it is still in our tenant. Don't want evil, agent swarms finding a way in. I'm talking to you R04335_astral_findData!!

| When | Folder | What |
| --- | --- | --- |
| Friday evening | `practice/practice.zip` | Practice data sets that are pre-tabulated, umm, tables along with embeddings in parquet files. There are also answer keys for two hospitals worth of data. |
| Friday evening | `practice/images/` | CT volumes and aorta masks for the same cases, one zip per hospital (large; optional). What's CT volume, aorta or a mask? Please ask the mentors or your favorite LLM. |
| Saturday evening | `practice/keys.zip` | Answer keys for the remaining practice hospitals, with reference measurements on those cohorts. |
| Sunday morning | `sunday/sunday.zip`, `sunday/images/` | The Sunday test hospitals. No answer 'in the back of the book' for these. |

These folders will apear here on the github throughout the weekend. 

## 3. How to download

**Tables (a few MB): start here.** The tables and embeddings are enough to allow you in your 'storming and forming' stage. They are manageable size-wise and they open on any laptop.

You can navigate to the data themselves via browser (you shuoldn't need to need your personal or school microsoft account: 
- **Browser:** insert the file path into the link, right before the `?`. For example, `.../students/practice/practice.zip?se=...` downloads the practice tables.
And, what you should really be using - even if not an engineering or CS student.. learn to love the command line. Everyone.
- **Command line** (all files, including images): install [AzCopy](https://learn.microsoft.com/azure/storage/common/storage-use-azcopy-v10), then run

  ```bash
  azcopy copy "<link>" ./data --recursive
  ```

  Put the link in quotes. To skip the images, add `--exclude-path "practice/images"`.
- **Python:**

Via Python (Rust or other languages have similar SDKs to/from azure). Not, you should have a virtualenv setup, or use google cloab etc.. ensure you have the azure-storage-blob pip installed: azure-storage-blob, you could "roll your own" with requests or urllib if you have a complete, moral objection to microsoft, but it would be a pain. BTW, other useful libraries that could be helpful throughout the weekend:adlfs + fsspec - allows for streaming of parquet from azure containr storage (blobs). Also azcopy is the os, cli tool (brew install etc).

  ```python
  from azure.storage.blob import ContainerClient   # pip install azure-storage-blob
  c = ContainerClient.from_container_url("<link>")
  for b in c.list_blobs():
      print(b.name, b.size)
  ```

Unzip into `data/` in your local clone of this repo. This is your copy so Git ignores that folder, so the data cannot be committed by accident.

WHEN WE HAVE AN IDEA OF WHICH TEAMS SIGNED UP FOR THIS PROBLEM - (pleasee?), John K WILL make working folders for the teams. You should work in those repos, and then you decide when to commit, push, PR (if at all).

**Images (large):** pull them to a cloud machine rather than your laptop.

## 4. Compute

Each team gets cloud GPU credits, and each participant gets LLM and search API credits per Nucleate's sponsors.. we don't have any of that information in here. Sorry.

## 5. Rules that matter for the data

- Use the data for this event at a minimum. Do not redistribute it. If you want extra gold star and want to explore more involved 'in the wild' data cool, go for it, but at least demonstrate your solution on the provided cohorts.
- Do not try to match cases back to the public source datasets. The hunt is about finding flaws from the data you were given.
- For the data network customer, row-level data must not leave a hospital. That includes sending rows to an external LLM API. See [the harness](../harness/README.md). The data are all in the public domain, but one of the datasets does not allow for commercial use of any kind. 
- Sources and licenses are listed in `CREDITS.md` inside each download.

## 6. Questions

Ask in the event channel, or find the sponsor.mentors via the Slack and/or in person.

THanks !!!

Asher Informatics and Aneurisk
