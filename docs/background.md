# Background: what IID really assumes, and why it matters for medical AI

Technical background notes from the sponsors. The worked example in section 2 uses chest CT for illustration; the hackathon data is abdominal CT, and the same arithmetic applies.

This page is the short version. For the careful statistical treatment, with the conditions each claim depends on and sources for each, see [technical-reference.md](technical-reference.md).

## 1. Technical background: what "IID" really assumes

### Two assumptions, not one

Given samples X_1, ..., X_n:

- **Independent:** the joint distribution factorizes. Knowing one sample tells you nothing about another.

```math
P(X_1, \ldots, X_n) = \prod_{i=1}^{n} P(X_i)
```

- **Identically distributed:** every X_i is drawn from the same distribution P.

These are logically separate. Examples:

| Case | Example |
|---|---|
| Identical, not independent | Many patches or slices from one patient's CT |
| Independent, not identical | One study each from a fixed set of scanners, analyzed scanner by scanner |
| Neither | Typical multi-site clinical data with repeat patients and scanner drift |

**A mixture is not automatically non-IID.** If each new case is drawn by first picking a site at random with fixed probabilities and then drawing a case from that site, the cases are IID from the mixture, even though the sites differ. What matters is how the data were actually collected (random draws or site-by-site blocks), and whether the deployment mix of sites, scanners and patients matches the one you evaluated on.

### What happens to MLE

The likelihood is usually written as a product:

```math
L(\theta) = \prod_{i=1}^{n} p(x_i \mid \theta)
```

The product form requires the observations to be independent, or independent once you condition on covariates or random effects you have modeled. A shared theta does not require every case to have the same distribution: in a regression, each case's distribution depends on its covariates and the product is still valid. The trouble starts when differences between sources are not modeled.

**Independence violated.** The point estimate can stay consistent if the marginal model is right (quasi-likelihood and composite-likelihood theory), but only in a suitable regime, such as a growing number of independent patients; correct marginals alone do not guarantee it under arbitrary dependence. The usual failure is that the variance is underestimated because correlated observations are counted as independent. Confidence intervals are too narrow and p-values are too small. Standard fixes treat the patient as the unit: cluster-robust (Liang-Zeger) sandwich standard errors, GEE, mixed-effects models, or a patient-level bootstrap. All need enough clusters; with only a handful of hospitals, site-clustered standard errors are not trustworthy.

**Identical distribution violated.** If the differences are captured by modeled covariates, this is just regression and is fine. If the shift is unmodeled, MLE converges to the best fit for the training mixture, weighted by however the sample happened to draw from each source. That bias does not shrink as n grows.

### What happens to Bayes

Bayes' theorem itself never breaks. The likelihood plugged into it does.

- **Independence violated:** the posterior concentrates too quickly. One repeated signal looks like overwhelming evidence, and credible intervals shrink unjustifiably. The natural fix is a hierarchical model (patient-level and site-level random effects), which makes observations conditionally independent given the latent structure.
- **Identical distribution violated and unmodeled:** under standard regularity conditions, the posterior concentrates on the parameter that minimizes KL divergence from the true mixture to the model class. That parameter describes the training mix of sites. It need not match any one site or the deployment population, and a reasonable prior will not fix that.

### Which violation is worse?

| | Independence violated | Identical distribution violated |
|---|---|---|
| Symptom | Mainly overconfidence; point estimates can survive, under conditions | Biased estimates of the wrong target |
| Detectability | Easier (repeat patients, temporal and spatial correlation) | Harder; you must hypothesize the axes of shift |
| Fixes | GEE, mixed models, hierarchical Bayes, cluster bootstrap | Covariate modeling, importance weighting, domain adaptation; all need extra knowledge or data |
| Does more data help? | More independent patients help; more scans per patient help little | Not by itself |

**Summary:** independence violations lie about your precision. Identical-distribution violations lie about what you learned. These are tendencies, not rules: which one matters more depends on the quantity being estimated, the sampling design and the deployment target.

### What this means for neural networks and SGD

A neural network is a flexible parametric estimator fit by minimizing empirical risk:

```math
\hat{R}_n(\theta) = \frac{1}{n} \sum_{i=1}^{n} \ell\big(f_\theta(x_i), y_i\big)
```

Two kinds of convergence get conflated:

1. **Optimization convergence.** SGD finds a low-loss region of the empirical risk on the fixed training set. This works whether or not the data are IID with respect to the world. Correlated mini-batches (for example, all patches from one patient) add gradient variance, and data read site by site without shuffling bias each step toward the current block. Shuffling and patient-aware batching address both. Whether training loss goes down depends on the optimizer and the objective, not on whether the data are IID.
2. **Statistical convergence.** The classical guarantee that empirical risk approaches population risk uniformly needs IID samples and a model class of limited capacity. It is a statement about the population you sampled from, and it covers deployment only if deployment draws from that same population.

- With independence violated, the row-average empirical risk is still unbiased, but for an observation-weighted target in which patients with more scans count more. If the claim is per patient, average within each patient first. Either way, the gap between training and population risk closes more slowly because the effective sample size is smaller.
- With unmodeled identical-distribution violations, training targets the training risk, and the best model for the training data need not be the best for deployment:

```math
\arg\min_\theta R_{\text{train}}(\theta) \quad \text{need not equal} \quad \arg\min_\theta R_{\text{deploy}}(\theta)
```

No stopping criterion or learning-rate schedule reveals this, and training curves and an internal validation split look the same either way. An audit of what the training data represent, or a test on data from the deployment setting, can show it.

---

## 2. Worked example: effective sample size in 3D chest CT

Modern chest CT work rarely uses slice-by-slice 2D classifiers. Typical approaches are 3D U-Nets (often nnU-Net), 3D or 2.5D detectors, self-supervised 3D backbones, and CT vision-language models. The clustering problem doesn't go away; the correlated unit just changes from slices to patches, findings, and serial scans.

### Setup

- 500 patients, one chest CT each (roughly 512 x 512 x 300 voxels)
- Training on 96 x 96 x 96 patches, about 100 patches per volume
- **50,000 training patches from 500 patients**
- 800 annotated nodules, long-tailed: most patients have 0 or 1, a few have 5 or more

The naive view is "50,000 patches and 800 positives: a solid dataset."

### The design effect

For clustered data, the classic design-effect approximation is:

```math
n_{\text{eff}} = \frac{n}{1 + (k - 1)\rho}
```

where n is the total number of observations, k is the cluster size, and rho is the intracluster correlation. This is for a mean, with equal cluster sizes and one common rho.

**Patient-level generalization.** Patches from one volume share anatomy, scanner, protocol, contrast timing, and body habitus. For claims about new patients you have 500 independent units, not 50,000. For a simple mean with 100 patches per patient, n_eff = 50,000 / (1 + 99 rho), which runs from 50,000 at rho = 0 down to 500 at rho = 1: about 4,600 at rho = 0.1 and about 990 at rho = 0.5. Adding patches never reduces the part of the uncertainty that comes from differences between patients. The same logic applies one level up: a claim about new hospitals rests on the handful of hospitals you have, however many patients each contributes.

**Nodule-level task: where the formula stops working.** It is tempting to plug in an average of 1.6 nodules per patient and get a tidy n_eff for the 800 nodules. Don't. The formula assumes clusters of equal size, and here most patients have 0 or 1 nodules while a few have 5 or more. With uneven clusters, use a patient-clustered bootstrap or a model built for the design instead of an average-cluster-size correction.

Design effects and n_eff are properties of a specific estimator under a specific design, not of a dataset. The same data can have a different n_eff for a mean, a sensitivity and an AUC.

**Historical 2D comparison.** In the older framing of 100 patients x 200 slices with rho = 0.9:

```math
n_{\text{eff}} = \frac{20{,}000}{1 + 199 \times 0.9} \approx 111
```

That's a 180x shrinkage. For a simple mean, confidence-interval width scales with one over the square root of n_eff, so naive intervals would be about 13x too narrow. That multiplier does not carry over to AUC or other metrics without a variance argument for that specific estimator; for those, use a patient-clustered bootstrap.

### Gradient signal

With uniform patch sampling, most patches contain no nodule. Standard practice (hard-negative mining, balanced or lesion-centered sampling, focal loss) reweights training toward what the clinical task needs. That is a task-design choice, not evidence that the data violate IID. Report the sampling weights you used, and evaluate the final system at the clinical unit and operating point you claim.

### The three-splits demonstration

| Split | What leaks | What the model can exploit | Illustrative AUC |
|---|---|---|---|
| A. Patch-level random | Same patients in train and test | Patient identity and anatomy | ~0.94 to 0.97 |
| B. Patient-level | Nothing patient-level | Within-site anatomical patterns | ~0.82 to 0.88 |
| C. Site-level | Nothing site-level | Only what generalizes across sites | ~0.70 to 0.80 |

These AUC ranges are illustrative, not measured, and the ordering is not guaranteed: a site holdout can score higher or lower than an internal test, depending on case mix, acquisition, sample size and task difficulty. Each split answers a different question (A: related data allowed in both sets; B: new patients from the same sites; C: unseen sites). The right split is the one that matches the claim. A common failure is reporting something closer to Split A while claiming what only Split C can support.

### What an honest evaluation reports

1. Naive metric with naive CI (conventional, but misleading)
2. Same metric with a **patient-clustered bootstrap** CI (resample patients, keep all their data together)
3. Patient-level metric (one aggregated prediction per patient)
4. Finding-level sensitivity (each lesion counted once)
5. Performance stratified by site and acquisition parameters

### 3D-specific heterogeneity axes

Slice thickness (1 mm vs 5 mm), reconstruction kernel (soft vs sharp), reconstruction algorithm (filtered back projection vs iterative), contrast timing, and dose all change the image. They correlate with institution and era. Most are in DICOM headers, though contrast phase often has to be inferred from the series description or from HU in the aorta. In the hackathon data, the available ones are columns in `features.parquet` (see the [data card](data-card.md)); reconstruction kernel and algorithm are not provided. That makes them easy, concrete audit targets.

### Multiple findings per scan

A real chest CT can contain nodules, emphysema, atelectasis, effusion, and incidental findings at once. These co-occur non-independently. Good audit questions: does the model separate co-occurring findings or entangle them? Does a CT report generator hallucinate findings that often co-occur in training but aren't present?

---

## 3. A heterogeneity framework: axes worth measuring

A single scalar "non-IID score" hides more than it shows. Useful audits report several axes separately:

| Axis | What differs | Example measures |
|---|---|---|
| Label prior | P(Y) across partitions | Hellinger, total variation, KL (smoothed; direction matters). Wasserstein only where labels have an order or distance, such as size class or diameter in mm |
| Covariate / feature | P(X) in a pretrained encoder's embedding space (here, the provided Merlin CT embeddings) | MMD, Fréchet distance (compares means and covariances only), classifier two-sample tests |
| Metadata | Scanner, protocol, demographics, era | Chi-square, Wasserstein, standardized differences |
| Conditional / concept | P(Y given X): same finding labeled differently across sites or readers | Cross-site label models, inter-reader agreement, disagreement on matched cases |
| Quantity / clustering | Cases per patient, studies per site | Intracluster correlation, design effect, n_eff |

Partitions worth comparing: random vs patient vs site vs scanner vs time vs demographic group.

The strongest version of this connects the heterogeneity measures to downstream behavior: do they predict which splits lose performance, or which federated algorithm (FedAvg, FedProx, FedPer) wins? Federated learning makes the problem visible because clients are explicit, but centralized training has the same heterogeneity hidden under the shuffle.

---

## 4. The text and VLM angle

### Why text is harder

Imaging at least has the defensible fiction of "one patient, one study." Text has no clean sampling unit. It could be a token, a document, or a context window, and none of them is independent. Token frequencies follow Zipf's law, vocabulary keeps growing with corpus size (Heaps' law), and most sentences appear only once. There is no well-defined "distribution of English" that a corpus samples from.

Autoregressive training sidesteps this by estimating conditional distributions, the next token given its context. That is effectively a regression indexed by context. Still:

- **Independence** is violated everywhere: overlapping windows, near-duplicate documents, topic clusters. The effective sample size is far below the token count.
- **Identical distribution** becomes partly philosophical: the corpus is the distribution by construction. The real gap is between the corpus and the queries users actually send.
- **Held-out perplexity** is a within-corpus test. It says little about out-of-distribution deployment.

### Embedding geometry

- Many trained embedding spaces are **anisotropic**: vectors crowd into a narrow cone ([Gao et al. 2019](https://arxiv.org/abs/1907.12009); [Ethayarajh 2019](https://arxiv.org/abs/1909.00512)). For static word vectors, the top principal directions track word frequency more than meaning ([Mu, Bhat and Viswanath 2018, "All-but-the-Top"](https://arxiv.org/abs/1702.01417)).
- This doesn't come from linear algebra alone. Training puts frequency-related variance in the top directions (gradient-count asymmetry, softmax pressure on rare tokens), and PCA faithfully surfaces whatever dominates variance.
- Meaning lives in local neighborhoods and many mid-spectrum directions, often superposed ([monosemanticity / sparse autoencoder work](https://transformer-circuits.pub/2023/monosemantic-features/index.html)). That's why removing top components or whitening often improves semantic similarity.
- **Parallel to imaging:** in imaging, the top variance directions are often scanner and site effects; in text, they're often frequency effects. In both cases nuisance variance can swamp what you care about.
- **Caution:** these results come from specific models and tasks. Do not assume the top components of every medical encoder are nuisance. Check what they track (frequency, length, site, clinical concepts) before removing them, and never remove a direction just because it explains a lot of variance.

### What can actually be measured about a corpus

- Composition: token and term frequency vs general text; medical concept coverage (UMLS / SNOMED); document type and length; language and domain mix
- Structure: duplicate and near-duplicate rates (MinHash-LSH or embedding-based); topic clusters; temporal distribution (drug names, guidelines, and terminology can date a corpus)
- Geometry: effective rank, intrinsic dimension, coverage (does the target deployment corpus fall inside the training cloud?), MMD or Wasserstein between clouds
- Pairing (for VLMs): are image-text pairs from the same clinical event, era, and institution, or has one modality drifted relative to the other?

These are descriptive statements about a specific corpus, not population inference about language.

### Candidate models and data

- VLMs: MedGemma, MAIRA-2, CheXagent, RadFM, LLaVA-Med, BiomedCLIP; CT-focused models such as CT2Rep, CT-CLIP, and M3D
- Other domains: pathology (CONCH, PathChat, Prov-GigaPath), dermatology, ophthalmology (RETFound derivatives), ambient documentation
- Data: CheXpert Plus, MIMIC-CXR and MIMIC-IV (PhysioNet credentialing required), RSNA challenge sets, TCIA multi-site collections, LIDC-IDRI, NLST-derived cohorts, PubMed

---

## 5. Calibration, conformal prediction, and exchangeability

### A common misconception

Attention heads don't each produce logits that collapse at the output. Within every layer, head outputs are concatenated and projected back into the residual stream. At the end, one unembedding matrix produces a single logit vector per position, and softmax gives a full next-token distribution. Choosing a token doesn't destroy that distribution, though later tokens depend on the choice.

### Where calibration is actually hard

1. **Token probability is not claim probability.** One meaning has many phrasings, and sequence probability depends on length and wording. [Semantic entropy (Farquhar et al., Nature 2024)](https://www.nature.com/articles/s41586-024-07421-0) clusters sampled answers by meaning and measures uncertainty over meanings.
2. **Post-training can change calibration.** [Larger base models are well calibrated on multiple-choice and true/false questions in the right format (Kadavath et al.)](https://arxiv.org/abs/2207.05221). In the GPT-4 Technical Report, expected calibration error on an MMLU subset was 0.007 for the pre-trained model and 0.074 after post-training, which included RLHF ([OpenAI 2023, Figure 8](https://arxiv.org/abs/2303.08774)). Neither result is a general law: measure calibration for your model, task and population rather than assuming a direction.
3. **Free text has no fixed outcome space.** You have to decide what is being calibrated: the report, the sentence, or the finding.
4. **Stated confidence is a separate signal.** Hedge words like "possible" or "cannot exclude" are generated text and may not match internal uncertainty.

### Methods with guarantees

- [Conformal language modeling (Quach et al.)](https://arxiv.org/abs/2306.10193) calibrates a sampling-and-rejection procedure so the output set contains an acceptable answer with high probability; it was evaluated on radiology report generation.
- [Conformal factuality (Mohri and Hashimoto)](https://raw.githubusercontent.com/mlresearch/v235/main/assets/mohri24a/mohri24a.pdf) splits outputs into sub-claims and filters low-confidence claims to meet a target correctness level.

### The link back to the hackathon

Conformal guarantees require **exchangeability** between calibration and deployment data, a relaxed form of IID. A claim-level calibration done at Site A can lose its guarantee at Site B because of scanner or population differences. Moving sites breaks the assumption behind the guarantee; it does not prove coverage will get worse, so measure it. The guarantee is also marginal coverage on average, not correctness for every case or every subgroup, and several claims from one patient are not independent calibration cases. Calibration is only as honest as the exchangeability assumption behind the calibration set, which is exactly the gap the audit toolkit is meant to address.

---

## 6. Prior work and where the gaps are

### Evidence the problem is real

- **Hidden stratification:** strong overall performance can hide clinically important subgroup failures ([Oakden-Rayner et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC7665161/)).
- **Shortcut learning:** models use artifacts, markers, and site cues ([risk of shortcutting in medical imaging](https://pmc.ncbi.nlm.nih.gov/articles/PMC11589829/); [detecting shortcuts in chest X-rays](https://arxiv.org/pdf/2211.04279)).
- **Scanner domain shift** ([experimental study](https://arxiv.org/abs/2409.04368)).
- **Underdiagnosis bias** in chest X-ray AI ([Seyyed-Kalantari et al., Nature Medicine](https://www.nature.com/articles/s41591-021-01595-0)), including in foundation models ([demographic bias in VLMs](https://pmc.ncbi.nlm.nih.gov/articles/PMC11939055/)).
- **Unsupervised shift detection** for imaging at deployment ([automatic dataset shift identification](https://arxiv.org/html/2411.07940v3)).

### Measuring non-IID in federated learning

- Quantifying non-IIDness is acknowledged as under-studied ([survey](https://arxiv.org/html/2411.12377v2)), and existing approaches are siloed without a unified benchmark ([heterogeneity benchmark](https://arxiv.org/html/2410.07286v2)).
- Existing measures: EMD over labels ([Zhao et al. 2018](https://arxiv.org/abs/1806.00582)), Hellinger distance ([assessment study](https://arxiv.org/html/2503.17070v2)), heterogeneity indices ([AAAI 2021](https://cdn.aaai.org/ojs/17291/17291-13-20785-1-2-20210518.pdf)), multi-modal divergence frameworks, non-IID degree estimation ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12290147/)), Client2Vec ([ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/papers/Guo_Client2Vec_Improving_Federated_Learning_by_Distribution_Shifts_Aware_Client_Indexing_ICCV_2025_paper.pdf)), and medical segmentation-specific assessment ([PMLR 2024](https://proceedings.mlr.press/v250/alekseenko24a.html)).
- Common weakness: collapsing several axes into one scalar, or measuring only label skew.
- What each of these measures sees and misses: [measures.md](measures.md).

### Cleanlab: what it covers and what it doesn't

**What it does well** ([GitHub](https://github.com/cleanlab/cleanlab), [docs](https://docs.cleanlab.ai/stable/index.html)):

- Label-error detection (confident learning) across classification, multi-label, segmentation, and detection
- Outliers and near-duplicates
- Underperforming groups: clusters in feature space where a model does poorly, a useful partial check for hidden stratification. It also accepts your own `cluster_ids`, so you can pass sites or scanners as the groups
- Annotator quality and active learning

**Its non-IID test is ordering-based.** It builds a k-NN graph on features, then compares index gaps between feature neighbors and random pairs with a permutation test ([Cleanlab blog](https://cleanlab.ai/blog/learn/non-iid-detection/); [Cummings, Snorrason and Mueller 2023](https://arxiv.org/abs/2305.15696)). The documentation says not to shuffle first, because shuffling destroys the signal the test relies on; it also notes that shuffling doesn't fix the underlying problem ([issue type guide](https://docs.cleanlab.ai/stable/cleanlab/datalab/guide/issue_type_description.html)).

**Gaps relative to this problem:**

1. No two-sample comparison across known partitions (site A vs B, scanner X vs Y)
2. No effective sample size, intracluster correlation, clustered bootstrap, or patient-level split tooling
3. No decomposition of heterogeneity by named axes; it finds clusters but doesn't explain them
4. No conditional-shift measurement (same finding labeled differently across sites)
5. No pretraining-vs-deployment corpus audit for VLMs or LLMs
6. No audit of multimodal pairing
7. No regulator- or committee-ready report format
8. No behavioral evaluation of models under shift

These are gaps in Cleanlab's documented open-source Datalab, not claims that no other tool covers them. Also, a non-significant ordering test after shuffling is not proof of IID. Whatever you build, say what it adds beyond the baselines you actually ran.

**Recommended positioning:** treat Cleanlab as a first step. Run it for label errors and duplicates, then build what comes after shuffling.

### Imaging data infrastructure: OMOP MI-CDM

- The OHDSI Medical Imaging extension adds tables and vocabularies to OMOP CDM v5.4 for DICOM-based studies ([Park et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC11031512/); [JAMIA 2025](https://pubmed.ncbi.nlm.nih.gov/40680297/); [Working Group](https://ohdsi.github.io/ImageWG/); [DICOM2OMOP](https://github.com/paulnagy/DICOM2OMOP)).
- Open questions that touch this problem: representing AI findings with provenance (model version, confidence, uncertainty), handling AI-vs-reader disagreement, and storing audit metadata alongside cohorts so studies can say whether a cohort is homogeneous enough to support a claim.

---

## References

Problem evidence

- Oakden-Rayner et al., Hidden stratification: https://pmc.ncbi.nlm.nih.gov/articles/PMC7665161/
- Risk of shortcutting in medical imaging: https://pmc.ncbi.nlm.nih.gov/articles/PMC11589829/
- Detecting shortcuts in chest X-rays: https://arxiv.org/pdf/2211.04279
- Scanner domain shift study: https://arxiv.org/abs/2409.04368
- Seyyed-Kalantari et al., Underdiagnosis bias: https://www.nature.com/articles/s41591-021-01595-0
- Demographic bias of VLM foundation models: https://pmc.ncbi.nlm.nih.gov/articles/PMC11939055/
- Automatic dataset shift identification: https://arxiv.org/html/2411.07940v3

Non-IID measurement and federated learning

- Non-IID data in FL survey: https://arxiv.org/html/2411.12377v2
- Benchmarking data heterogeneity evaluation: https://arxiv.org/html/2410.07286v2
- Zhao et al., FL with non-IID data (2018): https://arxiv.org/abs/1806.00582
- Thorough assessment of non-IID impact: https://arxiv.org/html/2503.17070v2
- Curse or Redemption (AAAI 2021): https://cdn.aaai.org/ojs/17291/17291-13-20785-1-2-20210518.pdf
- Non-IID degree estimation: https://pmc.ncbi.nlm.nih.gov/articles/PMC12290147/
- Client2Vec (ICCV 2025): https://openaccess.thecvf.com/content/ICCV2025/papers/Guo_Client2Vec_Improving_Federated_Learning_by_Distribution_Shifts_Aware_Client_Indexing_ICCV_2025_paper.pdf
- Distance-aware non-IID FL for medical segmentation: https://proceedings.mlr.press/v250/alekseenko24a.html

Cleanlab

- Repository: https://github.com/cleanlab/cleanlab
- Documentation: https://docs.cleanlab.ai/stable/index.html
- Non-IID detection blog: https://cleanlab.ai/blog/learn/non-iid-detection/
- Cummings, Snorrason and Mueller (2023): https://arxiv.org/abs/2305.15696
- Issue type guide: https://docs.cleanlab.ai/stable/cleanlab/datalab/guide/issue_type_description.html

Embeddings and LLM uncertainty

- Mu, Bhat and Viswanath, All-but-the-Top (ICLR 2018): https://arxiv.org/abs/1702.01417
- Gao et al., Representation degeneration: https://arxiv.org/abs/1907.12009
- Ethayarajh, Contextual representations: https://arxiv.org/abs/1909.00512
- Towards Monosemanticity: https://transformer-circuits.pub/2023/monosemantic-features/index.html
- Farquhar et al., Semantic entropy: https://www.nature.com/articles/s41586-024-07421-0
- Kadavath et al., Language Models (Mostly) Know What They Know: https://arxiv.org/abs/2207.05221
- OpenAI, GPT-4 Technical Report (2023), Figure 8: https://arxiv.org/abs/2303.08774
- Quach et al., Conformal language modeling: https://arxiv.org/abs/2306.10193
- Mohri and Hashimoto, Conformal factuality: https://raw.githubusercontent.com/mlresearch/v235/main/assets/mohri24a/mohri24a.pdf

Imaging informatics

- Park et al., MI-CDM extension: https://pmc.ncbi.nlm.nih.gov/articles/PMC11031512/
- Breaking data silos (JAMIA 2025): https://pubmed.ncbi.nlm.nih.gov/40680297/
- OHDSI Medical Imaging Working Group: https://ohdsi.github.io/ImageWG/
- DICOM2OMOP: https://github.com/paulnagy/DICOM2OMOP
