# Getting started: running SlicePoint at your hospital

SlicePoint checks whether an imaging AI model fits your patients and scanners before
you turn it on. It compares a sample of your scans with a reference (the data the model
was checked on) and gives a **GO**, **BORDERLINE** or **NO-GO** verdict, five health
checks and a report you can print. This page is for a hospital without IT support to
run servers or containers: you need Python on one computer and nothing else.

## What data you need

One folder per site, holding curated parquet files that share a `case_id` column:

| File | Required | What is in it |
|---|---|---|
| `features.parquet` | yes | One row per scan: `patient_id`, `age_band`, `sex`, `scanner_vendor`, `contrast_phase`, slice thickness, `kvp`, aorta brightness, organ volumes |
| `predictions.parquet` | yes | The AI's outputs: `pred_aaa` (empty means "no answer"), `pred_max_diameter_mm`, `pred_aorta_dice` |
| `labels.parquet` | no | Your labels: `aaa`, `max_aortic_diameter_mm`, `aaa_size_class`. Without it, the label and accuracy checks are reported as *not evaluated* |
| `embeddings.parquet` | no | `case_id` plus `emb_0` to `emb_2047` (Merlin CT encoder). Without it, the repeat-scan check is *not evaluated* |

`slicepoint schema FeatureRow` (and `LabelRow`, `PredictionRow`) prints the exact columns
and allowed values. The practice data in `data/practice/` shows the layout.

**Be aware:** today these files are prepared by hand. SlicePoint cannot yet read raw DICOM,
a PACS export or report text; those readers are planned but not built (ADR 0001 §2).

You also need a **reference**: the same kind of folder for the population the model was
validated on, or a reference profile someone saved for you with
`slicepoint reference build`. A check is only as good as its reference, so ask the vendor
for one.

## Install

Python 3.10 or newer. Until SlicePoint is published, install it from a copy of this
repository:

```bash
python -m venv slicepoint-env
source slicepoint-env/bin/activate          # Windows: slicepoint-env\Scripts\activate
pip install -e slicepoint/schemas -e slicepoint/core
slicepoint --help
```

For the notebook, also `pip install jupyterlab`.

## Option 1: the command line

```bash
# once: save a reference profile from the reference data
slicepoint reference build --data data/practice/hospital_a --site-id hospital_a --out refs/hospital_a

# each assessment
slicepoint assess --data data/practice/hospital_b --site-id hospital_b --site-name "Hospital B" \
    --reference-profile refs/hospital_a \
    --out out/hospital_b_result.json --html out/hospital_b_report.html

# or build the reference on the fly from its data folder (--reference-site-id is then required)
slicepoint assess --data data/practice/hospital_b --site-id hospital_b \
    --reference-dir data/practice/hospital_a --reference-site-id hospital_a \
    --out out/hospital_b_result.json --html out/hospital_b_report.html
```

`--site-id` is a short lowercase name you choose for your site; it is recorded in the
result. `--site-name` is the name printed on the report (without it, the site id is shown
made readable: `hospital_b` becomes "Hospital B"). The reference site's id is never
guessed: give it with `--site-id` when you build a reference profile, or with
`--reference-site-id` when you point `assess` at a reference data folder. Add `--json` to
get a machine-readable summary instead of text.

The exit code tells you how it went:

| Code | Meaning |
|---|---|
| 0 | Ran, and the verdict is GO |
| 3 | Ran fine, and the verdict is BORDERLINE or NO-GO: a person should read the report |
| 1 | Something is wrong with the input; the one-line message names the file or column |
| 2 | Internal error in SlicePoint; rerun with `--debug` and send us the output |

## Option 2: the notebook

Open `slicepoint/notebooks/slicepoint_quickstart.ipynb` in Jupyter. Edit the settings in
Step 2 (your data folder, site id and optional display name, the reference and its site
id, and the output folder) and choose *Run All*. The notebook shows the verdict, the check table and the full
report, and saves the same `result.json` and `report.html` as the command line. Both call
the same library code.

## How to read the report

Open `report.html` in any browser. To get a PDF, print it and choose *Save as PDF*; the
first page is the summary.

1. **Verdict.** NO-GO: at least one check found a problem. BORDERLINE: something needs a
   closer look, or a check could not run. GO: every check passed on this sample.
2. **Health checks.** Five cards: different people, scan settings, patients, labels and AI
   accuracy. Each shows its status in words (Problem, Watch, OK, Not evaluated), how many
   scans it used (*n*) and the *effective n* after discounting repeat scans of the same
   person, which sub-factors failed, and a "What this means" line. "Show the numbers"
   opens the detail.
3. **AI performance.** Sensitivity (aneurysms caught) and specificity (normals called
   normal), counting a missing AI answer as wrong, and again leaving those scans out. The
   ranges are 95% intervals: a wide range means the sample is too small to be sure.
   Diameter agreement and outline quality (Dice) follow.
4. **Results by group.** The same numbers per scanner, contrast phase, slice thickness,
   sex and age group. Groups too small to judge say "Too few".
5. **Cases to review.** Scans to open first: missed aneurysms, no answers, size errors and
   false alarms.
6. **Methods and limits** and **Provenance** record how the result was made, from which
   data and thresholds, and which steps were skipped.

The 0 to 100 scores from the proof-of-concept are hidden, and left out of `result.json`:
their formulas have not been validated. Results come from a test sample, not a full trial. This report supports a
decision and is not medical advice.

## Option 3: the interactive viewer

`slicepoint-viewer.html` is one file that opens a `result.json` in your browser. It has
the same content as the report, and you can open each check's evidence and sort and
filter the cases to review. Build it once with `pnpm build` in `slicepoint/viewer` (see
its README), or ask whoever set SlicePoint up for a copy. Then:

1. Double-click `slicepoint-viewer.html`. It works offline, with no server and no
   installation.
2. Click **Open result.json**, or drag the file onto the page.

The viewer reads the file inside the browser and makes no network requests. Its security
policy blocks them, so nothing you open is sent anywhere. It accepts only results written
against the contract version it was built for. Any other file gets a message naming the
problem. The draft 0 to 100 scores stay hidden unless `result.json` was written with
`--show-provisional-scores`. Even then you have to switch them on, and they are labelled
as unratified. For printing or a PDF, use `report.html`.

## Privacy

SlicePoint runs entirely on your computer. It does not upload, send or phone home
anything. The HTML report contains no scripts and loads nothing from the internet (its
built-in security policy blocks it), so it is safe to open offline. The report and
`result.json` list case ids, person groupings, demographics bands and measurements for
the sample, so store and share them as you would other de-identified study data.

## Ask your AI assistant

SlicePoint's command line is designed so that an AI assistant (Copilot, Claude, and so
on) can run it for you. `slicepoint --help` and `slicepoint assess --help` describe every
option, the JSON output and the exit codes. Example requests:

- "Run SlicePoint on `D:\ai-check\our_scans` with site id `st_marys`, against the reference
  profile in `D:\ai-check\vendor_reference`, and save the report to `D:\ai-check\out`.
  Tell me the verdict and which checks failed."
- "Use `slicepoint assess --json` on `data/our_site` (site id `our_site`) against the
  reference folder `data/vendor_ref`. Summarise the verdict, list any check that was not
  evaluated and why, and explain the failing sub-factors in plain English."
- "SlicePoint stopped with an error about `features.parquet`. Read the message, check the
  columns in that file against `slicepoint schema FeatureRow`, and tell me what to fix."
- "Validate `out/our_site_result.json` with `slicepoint validate` and tell me if it is a
  complete result."

Ask the assistant to run the commands on your computer; there is no need to paste patient
data into a chat.
