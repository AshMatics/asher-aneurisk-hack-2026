# Possible directions (not prescriptive)

Teams choose their own direction. These are examples to spark ideas, not tracks. Most of them map naturally onto one of the [three customers](personas.md).

| Direction | Natural customer |
| --- | --- |
| Split and evaluation harness | Regulated developer |
| Multi-axis heterogeneity report | Regulated developer, hospital committee |
| Effective-sample-size estimator | Regulated developer |
| Acquisition-parameter audit | Hospital committee |
| Federated cohort audit | Data network |
| Calibration under shift | Hospital committee |
| Regulatory memo | Regulated developer |
| Provenance and CDM extension | Data network |
| VLM corpus audit, report-generation reliability | Off the main AAA track; welcome if your team has the data and the appetite |

## In more detail

- **Split and evaluation harness:** generate patient-, site-, scanner-, and time-based splits from one dataset and report clustered-bootstrap CIs, patient-level metrics, and finding-level metrics side by side.
- **Multi-axis heterogeneity report:** a one-page audit of label prior, embedding, metadata, and conditional shift across partitions, readable by a clinician.
- **Effective-sample-size estimator:** estimate intracluster correlation in embedding space and report what a dataset can realistically support.
- **Acquisition-parameter audit:** relate model performance to slice thickness, kernel, and scanner, using DICOM headers.
- **VLM corpus audit:** duplication, temporal fingerprinting, concept coverage, and embedding-cloud coverage of a target clinical corpus.
- **Report-generation reliability:** hallucination and prompt-induced bias in a CXR or CT report model, stratified by site or acquisition.
- **Calibration under shift:** show a claim-level conformal guarantee holding at one site and failing at another, and propose a detector.
- **Federated cohort audit:** test whether heterogeneity measures predict FedAvg vs FedProx vs FedPer outcomes.
- **Provenance and CDM extension:** represent audit results and AI findings in OMOP MI-CDM.
- **Regulatory memo:** what a data characterization section and post-market shift-monitoring plan should contain.

## What strong submissions tend to have in common

- They find something unflattering and report it honestly.
- They explain results so a non-ML reader can act on them.
- They can be reproduced by someone else quickly.
- The work would genuinely inform the authors of the model or dataset being audited.

A well-supported "no problem found," or an honest account of where a metric fails, is a useful result. A dramatic failure is not required.

## A checklist for what to report

Not every project needs every item, but a reader should be able to find each one or see why it doesn't apply.

- **Claim and target:** the intended task and population, the prediction unit (scan, patient, lesion), the evaluation unit, and the exact quantity estimated.
- **Data structure:** patient, study and site counts; how many scans per patient; how reliable the patient IDs are; missing data; access limits.
- **Methods:** split rules, weights, encoder, distance or kernel, tuning, the unit you resampled, and how you handled multiple comparisons.
- **Results:** effect sizes with uncertainty, what the model actually did, and your positive and negative controls (see [measures.md](measures.md)).
- **Limits:** axes you could not check, thin subgroups, confounded factors, missing external labels.
- **Reproducibility:** code, versioned configuration, a data manifest or download steps, and what can legally be shared.

More on each point in [technical-reference.md](technical-reference.md).
