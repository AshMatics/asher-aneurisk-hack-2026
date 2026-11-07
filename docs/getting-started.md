# Getting started: where everything is

One page, yo.  Read me first!!

## 1. The problem

Everything about the problem statement and why/how we pose it lives in this repo. The [repo README](../README.md) has the problem in one paragraph; the [documentation guide](README.md) lists every document, what to read first, and reading paths by background and by customer.

## 2. The data

The data are not in this repo. They sit in a cloud storage folder (an Asher Informatics Azure Blob). **The read-only link is given out at kickoff.** Do not post it publicly please. It is segregated from our dev and prod resources, but it is still in our tenant. Don't want evil, agent swarms finding a way in. I'm talking to you R04335_astral_findData!!

| When | Folder | What |
| --- | --- | --- |
| Friday evening | `practice/practice.zip` | Practice data sets that are pre-tabulated, umm, tables along with embeddings in parquet files. There are also answer keys for two hospitals worth of data. |
| Friday evening | `practice/images/` | CT volumes and aorta masks for the same cases, one zip per hospital (large; optional). What's CT volume, aorta or a mask? Please ask the mentors or your favorite LLM. |
| Saturday evening | `practice/keys.zip` | Answer keys for the remaining practice hospitals, with reference measurements on those cohorts. |
| Sunday morning | `sunday/sunday.zip`, `sunday/images/` | The Sunday test hospitals. No answer 'in the back of the book' for these. |

These folders appear in the storage folder as each part is released, not in this GitHub repo.

## 3. How to download

**Tables (a few MB): start here.** The tables and embeddings are enough to let you get started Friday night during your 'storming and forming' stage. They are manageable size-wise and they open on any laptop.

You can navigate to the data themselves via browser (you shouldn't need your personal or school Microsoft account):
- **Browser:** insert the file path into the link, right before the `?`. For example, `.../students/practice/practice.zip?se=...` downloads the practice tables.
And, what you should really be using - even if not an engineering or CS student.. learn to love the command line. Everyone.
- **Command line** (all files, including images): install [AzCopy](https://learn.microsoft.com/azure/storage/common/storage-use-azcopy-v10), then run

  ```bash
  azcopy copy "<link>" ./data --recursive
  ```

  Put the link in quotes. To skip the images, add `--exclude-path "practice/images"`.
- **Python:**

  First set up a Python environment (3.10 or newer) from the repo root, or use Google Colab:

  ```bash
  python -m venv .venv
  source .venv/bin/activate        # Windows: .venv\Scripts\activate
  pip install -r requirements.txt
  ```

  That installs everything the harness and starter code need, plus `azure-storage-blob` for downloading. Rust and other languages have similar Azure SDKs. You could roll your own with `requests` if you have a moral objection to Microsoft, but it would be a pain. `adlfs` and `fsspec` (also installed) let you stream parquet straight from the blob without downloading first.

  ```python
  from azure.storage.blob import ContainerClient   # pip install azure-storage-blob
  c = ContainerClient.from_container_url("<link>")
  for b in c.list_blobs():
      print(b.name, round(b.size / 1e6, 1), "MB")

  # download the practice tables (a few MB)
  with open("practice.zip", "wb") as f:
      f.write(c.download_blob("practice/practice.zip").readall())

  # image zips are GBs: stream to disk instead of holding them in memory
  with open("hospital_a.zip", "wb") as f:
      c.download_blob("practice/images/hospital_a.zip").readinto(f)
  ```

Unzip into `data/` in your local clone of this repo. This is your copy so Git ignores that folder, so the data cannot be committed by accident.

WHEN WE HAVE AN IDEA OF WHICH TEAMS SIGNED UP FOR THIS PROBLEM - (please?), John K WILL make working folders for the teams. You should work in those repos, and then you decide when to commit, push, PR (if at all).

**Images (large):** pull them to a cloud machine rather than your laptop.

## 4. Compute

Each team gets cloud GPU credits, and each participant gets LLM and search API credits per Nucleate's sponsors.. we don't have any of that information in here. Sorry.

## 5. Rules that matter for the data

- Use the data for this event at a minimum. Do not redistribute it. If you want extra gold star and want to explore more involved 'in the wild' data cool, go for it, but at least demonstrate your solution on the provided cohorts.
- Do not try to match cases back to the public source datasets. The hunt is about finding flaws from the data you were given.
- For the data network customer, row-level data must not leave a hospital. That includes sending rows to an external LLM API. See [the harness](../harness/README.md). The data are all in the public domain, but one of the datasets does not allow for commercial use of any kind. 
- Sources and licenses are listed in `CREDITS.md` inside each download.

## 6. Questions

Ask in the event channel, or find the sponsor mentors via the Slack and/or in person.

Thanks!!!

Asher Informatics and Aneurisk
