# The three customers

Pick one customer on Friday night and build for that person. Each is played live by a sponsor all weekend: open Q&A Friday, a 10-minute check-in Saturday morning, more on request. They are surrogate customers, not the event judges: use them to test your work before the real judging.

If your customer says "I would never read that," believe them.

---

## 1. The regulated developer

**Who:** a company building FDA-regulated software for abdominal aortic aneurysm (AAA) assessment on CT angiography. Played by Aneurisk.

**Their question:** "Characterize my test and external validation cohorts for my regulatory and clinical team. Are they truly independent of training? Which subgroups are covered, and how much real evidence does each one hold?"

**What they already have:** a trained model, a training set, a held-out test set, an external validation set from other sites, and a lot of anxiety about the data characterization section of a regulatory submission.

**What they care about:**

- Patient and site leakage between training and test
- Subgroup coverage: sex, age band, AAA size class, scanner vendor, contrast phase, slice thickness
- Effective sample size per subgroup and confidence intervals that account for clustering
- How the external cohort differs from training, and whether those differences matter for the claim

**What they would ignore:** a single "non-IID score" with no explanation; a dashboard their clinical lead can't read.

**What good looks like:** something they could paste into a submission and defend in front of a reviewer.

---

## 2. The hospital AI committee

**Who:** the clinical AI governance committee at a health system. Played by Asher Informatics.

**Their question:** "A vendor wants to sell us this AAA model. Will it work on our patients, and what should we watch after go-live?"

**What they already have:** the vendor's summary of its training data, and summary statistics about their own patients and scanners. Not the vendor's raw data.

**What they care about:**

- Do our patients and scanners fall inside what the model was trained on?
- Which subgroups of ours are thin or missing in the training data?
- What should trigger a review after go-live?

**What they would ignore:** anything longer than a page; p-values without a decision attached.

**What good looks like:** go, caution or no-go, with the reasons, on one page a CMIO would read.

---

## 3. The data network

**Who:** a federated network of hospitals that cannot move patient data off site. Played by Asher Informatics.

**Their question:** "I have six hospitals and can't move their data. Can I audit them anyway?"

**What they already have:** compute at each site, and a rule: only summary statistics leave a hospital.

**What they care about:**

- An audit that runs inside each node and returns only summaries
- Finding the same problems a centralized audit would find
- Knowing what was lost by not pooling the data

**The rule, stated plainly:** row-level data never leaves a node. That includes data sent to an external LLM API. If your agent ships rows to a model provider, the data has left the hospital.

**What good looks like:** passes [the harness](../harness/README.md) and still finds the flaws.
