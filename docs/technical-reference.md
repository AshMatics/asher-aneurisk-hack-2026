# Dependence, Heterogeneity, and Distribution Shift in Medical AI

Technical reference from the sponsors (Asher Informatics PBC and Aneurisk Inc.), updated November 2, 2026.

This is the long, careful companion to [background.md](background.md). Read background.md first. Come here when you need the conditions behind a claim, or a source to cite. The examples are general (chest CT, text, VLMs); the hackathon data is abdominal CT for aortic aneurysm.

This reference describes statistical foundations and practical methods for assessing dependence, heterogeneity, and distribution shift in medical AI datasets. It covers imaging, clinical text, and multimodal applications, with explicit distinctions between established methods, proposed applications, and the limits of inference.

The organizing question is: **What evidence supports transporting a model's measured performance from the available data to the intended patients, institutions, times, and tasks?** The proposed contribution is an open, reusable audit workflow that connects existing statistical and data-quality tools to that question, rather than claiming to invent the individual methods.

## How to use this reference

- **Foundations:** Start with sampling units, dependence, heterogeneity, and the target estimand before choosing a metric.
- **Methods:** Use the method-selection sections to distinguish descriptive comparisons, formal tests, uncertainty estimation, and model evaluation.
- **Worked example:** Treat the CT calculation as a deliberately specified scalar random-effects example, not a universal neural-network sample-size formula.
- **Multimodal extensions:** Use the text, pairing, and calibration sections to extend the same reasoning to VLM applications.
- **Evidence status:** “Established” describes a method's statistical role, not proof that it will be useful for every dataset; “proposed” marks suggested audit designs that require validation.

Sources are linked beside the relevant discussion. Numerical calculations explicitly labeled as hypothetical are derived examples, not empirical findings.

## Scope and terminology

Three different problems should not be collapsed into “non-IID”: related observations can create dependence; groups can have different distributions; and the evaluation population can differ from the intended deployment population. Medical-imaging guidance identifies both hierarchical leakage and cross-source generalization as evaluation concerns ([Rouzrokh et al., data-bias review](https://pmc.ncbi.nlm.nih.gov/articles/PMC9533091/)).

A heterogeneous dataset is not automatically defective, and a representative dataset need not be homogeneous. The audit should ask whether the data structure and evaluation design support a specified use, rather than reward maximum similarity between all groups ([Rouzrokh et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC9533091/)).

Throughout, let:

- **$X$:** The defined input, possibly a complete CT volume, image-text pair, or clinical encounter.
- **$Y$:** The defined target, reference annotation, outcome, or adjudicated claim correctness.
- **$G$:** A grouping or domain variable, such as patient, site, scanner, reader, or era.
- **$P$, $Q$:** Explicit source and target sampling distributions, not an unspecified “real-world distribution.”
- **Estimand:** The particular quantity being estimated, such as mean patient-level report error, lesion sensitivity, or performance at a specified false-positive rate.

## Sampling units come before IID

### Two distinct assumptions

For observations $Z_1,\ldots,Z_n$, independence means their joint law factorizes, while identical distribution means their marginal laws are the same. IID combines both, but neither follows from the other; these assumptions belong to the definition of the observations and sampling process, not to an image file format ([Shalev-Shwartz and Ben-David, statistical-learning foundations](https://www.cambridge.org/core/books/understanding-machine-learning/3059695661405D25673058E43C8BE2A6/listing)).

```math
P(Z_1,\ldots,Z_n)=\prod_{i=1}^{n}P(Z_i),
\qquad Z_i\sim P\ \text{for every }i.
```

Proposed unit declarations for an audit:

| Analysis | Sampling/evaluation unit to declare | Internal structure to preserve |
|---|---|---|
| CT report generation | Study or patient, depending on intended use | Voxels, regions, findings, report claims |
| Longitudinal CT analysis | Patient trajectory or explicitly defined follow-up event | Serial scans and repeated findings |
| Lesion detection | Lesion for sensitivity, scan/patient for false positives and uncertainty | Multiple lesions within a patient |
| Clinical-text analysis | Patient, encounter, document, or document family | Repeated notes, templates, copied passages |
| VLM evaluation | Patient-linked image-text case | Multiple views, reports, prompts, generated claims |

Dependence among voxels or slices within one CT does not itself contradict an IID model of whole patient-level volumes. The practical leakage risk arises when related data from the same patient are divided across development and evaluation sets intended to represent new patients ([Rouzrokh et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC9533091/)).

### Mixtures are not automatically non-IID

Consider this specified sampling model: for each new observation, independently draw a site $G_i$ with fixed probabilities $w_g$, then draw $Z_i$ from that site's distribution $P_g$. By construction, the observations are IID from the mixture

```math
P_{\mathrm{mix}}=\sum_g w_gP_g,
```

even though the site-conditional distributions differ. If observations are instead collected in site-specific blocks, the conditional sampling design is different; the analyst must say which design is being modeled.

The concern for deployment is whether its mixture weights, component distributions, and task match those used for evaluation. Cross-source and temporal evaluation investigate how performance transfers beyond an internal split ([generalizability review](https://pmc.ncbi.nlm.nih.gov/articles/PMC9885377/)).

Likewise, lesion-bearing and lesion-free regions may be components of one joint distribution over volumes and findings. Their coexistence is not, by itself, evidence against IID sampling of volumes; clinical-task definition and sampling design determine the relevant question.

## What dependence and heterogeneity do to estimation

### Likelihood and Bayes' theorem

A likelihood is the joint probability model for the observed data as a function of its parameters. Independent, non-identically distributed observations can still have a valid product likelihood, including when distributions depend on observed covariates; a shared parameter does not require identical unconditional distributions ([Varin, Reid, and Firth, composite-likelihood review](https://utstat.toronto.edu/reid/research/varin_reid_firth.pdf)).

```math
L(\theta;D)=p_\theta(D),
\qquad
L(\theta;D\mid z_1,\ldots,z_n)
=\prod_i p_\theta(x_i\mid z_i)
```

where the second expression assumes conditional independence under the specified model.

Multiplying correctly specified marginal densities while ignoring dependence can be a useful working-independence composite likelihood, but consistency requires identification and an appropriate asymptotic regime, such as increasing independent clusters or suitable weak-dependence assumptions. Correct marginals alone do not guarantee consistency under arbitrary dependence, and ordinary inverse-Hessian uncertainty generally needs an appropriate sandwich/Godambe adjustment ([Varin, Reid, and Firth](https://utstat.toronto.edu/reid/research/varin_reid_firth.pdf)).

Bayes' theorem remains

```math
p(\theta\mid D)\propto p_\theta(D)\,p(\theta).
```

Using a working-independence product as if it were the genuine joint likelihood can produce misleading posterior uncertainty; composite-likelihood Bayesian methods require additional calibration or adjustment. This is a modeling issue, not a failure of Bayes' theorem ([adjusted composite likelihood for Bayesian inference](https://ar5iv.labs.arxiv.org/html/2104.01920)).

Dependence and distribution differences can affect both uncertainty and the usefulness of an estimate. Their relative importance depends on the estimand, sampling design, strength of dependence, model specification, and deployment target.

### Neural networks: approximation, optimization, generalization

These are separate questions: whether a network can represent a function, whether a training procedure can find suitable parameters, and whether the resulting predictor performs well on new observations. Expressive power alone is not a guarantee of optimization success or generalization ([Shalev-Shwartz and Ben-David, chapters on learning theory, SGD, and neural networks](https://www.cambridge.org/core/books/understanding-machine-learning/3059695661405D25673058E43C8BE2A6/listing)).

For a fixed dataset, define

```math
\widehat R_n(\theta)=\frac{1}{n}\sum_{i=1}^{n}
\ell(f_\theta(x_i),y_i).
```

Uniformly sampling an index $I$ from this fixed dataset gives the following conditional expectation, provided the derivatives exist:

```math
\mathbb E_I[\nabla_\theta\ell(f_\theta(x_I),y_I)\mid D,\theta]
=\nabla_\theta\widehat R_n(\theta).
```

This identity follows from averaging the finite sum; it does not require that the original cases were independently collected. It also does not establish convergence of the optimizer.

Nonconvex SGD convergence results require assumptions on the objective, gradient estimates, and step sizes, and typically concern stationary points rather than arbitrary global minima. Constant learning rates can leave residual variation, and neither IID nor non-IID collection determines whether training loss reaches zero ([Jin et al., nonconvex optimization](https://arxiv.org/html/1902.04811v2)).

IID sampling supports classical generalization analysis, but uniform convergence also requires control of the hypothesis/loss class; IID alone is insufficient for arbitrary function classes. Uniform convergence is one route to generalization guarantees, not the sole framework for analyzing modern learning systems ([Shalev-Shwartz and Ben-David, uniform convergence and complexity](https://www.cambridge.org/core/books/understanding-machine-learning/3059695661405D25673058E43C8BE2A6/listing)).

For source $P$ and target $Q$, define

```math
R_P(\theta)=\mathbb E_P[\ell(f_\theta(X),Y)],
\qquad
R_Q(\theta)=\mathbb E_Q[\ell(f_\theta(X),Y)].
```

The audit should investigate the discrepancy relevant to the intended loss and target. A detected input shift does not necessarily mean performance deteriorated, while a training-loss plateau does not establish transportability ([Dombrowski, medical-image drift review](https://arxiv.org/html/2409.17800v2)).

## Worked CT example: what effective sample size actually means

### A deliberately specified scalar model

This is a hypothetical calculation for estimating a scalar mean. It is not an empirical estimate of CT feature correlation, training-data sufficiency, or AUC uncertainty.

Assume 500 independent patients, 100 measurements per patient, and

```math
U_{ij}=\mu+b_i+\varepsilon_{ij},
```

where $b_i$ are independent patient effects, residuals are independent of patient effects and one another, and the variance components are $\tau^2$ and $\sigma^2$. Within each patient, this construction gives equal pairwise correlation

```math
\rho=\frac{\tau^2}{\tau^2+\sigma^2}.
```

The equal-cluster design effect $1+(k-1)\rho$ is the familiar clustered-mean calculation; design effects and effective sample sizes are properties of an estimator and design, not universal properties of a dataset ([CONSORT cluster-trial guidance](https://www.bmj.com/content/345/bmj.e5661), [PracTools, design effects](https://stat.ethz.ch/CRAN/web/packages/PracTools/vignettes/Design-effects.html)).

For $M=500$, $k=100$, and $N=Mk=50{,}000$, direct variance calculation gives

```math
\operatorname{Var}(\bar U)
=\frac{\tau^2}{M}+\frac{\sigma^2}{Mk}
=\frac{\tau^2+\sigma^2}{N}\{1+(k-1)\rho\}.
```

Relative to independent measurements of the same marginal variance,

```math
N_{\mathrm{eff}}=\frac{50{,}000}{1+99\rho}.
```

Calculated sensitivity analysis under these stated assumptions:

| Assumed $\rho$ | Design effect | Effective size for this mean | Standard-error multiplier versus the independent-measurement calculation |
|---:|---:|---:|---:|
| 0 | 1.00 | 50,000 | 1.00 |
| 0.01 | 1.99 | 25,125.6 | 1.41 |
| 0.10 | 10.90 | 4,587.2 | 3.30 |
| 0.50 | 50.50 | 990.1 | 7.11 |
| 0.90 | 90.10 | 554.9 | 9.49 |
| 1.00 | 100.00 | 500.0 | 10.00 |

For this model, the effective size lies between 500 and 50,000 when $\rho\in[0,1]$. The number of independent patients and the information contributed by repeated measurements are distinct quantities; both matter to the precision of the specified estimator.

### What this does not justify

- **A universal training sample count:** Repeated patches may provide useful local information without adding independent patients; the calculation does not convert patches into a universal number of training cases.
- **An image-similarity substitution:** Correlation of pixels or selected embedding coordinates is not automatically the correlation of prediction errors, losses, or influence-function contributions relevant to a performance estimate.
- **An AUC correction factor:** Multiplying an AUC confidence-interval width by this table's multiplier is not justified without a suitable variance argument for that AUC estimator.
- **A nodule shortcut:** Dividing all nodules by all patients, including patients with no nodules, does not satisfy an equal-positive-cluster assumption; variable cluster sizes require a design-specific treatment.

Unequal cluster sizes and the quantity being estimated affect design-effect calculations, so a single average-cluster-size correction can be inadequate ([CONSORT guidance](https://www.bmj.com/content/345/bmj.e5661), [PracTools](https://stat.ethz.ch/CRAN/web/packages/PracTools/vignettes/Design-effects.html)).

### Weighting changes the question

For $k_i$ observations in patient $i$, compare these two proposed loss summaries:

```math
\widehat R_{\mathrm{observation}}
=\frac{1}{\sum_i k_i}\sum_i\sum_j\ell_{ij},
\qquad
\widehat R_{\mathrm{patient}}
=\frac{1}{M}\sum_i\left(\frac{1}{k_i}\sum_j\ell_{ij}\right).
```

The first weights patients in proportion to their observation counts; the second gives each patient equal weight. They can differ without either being a numerical error: the intended estimand determines the appropriate choice.

Lesion-centered sampling or loss weighting is a task-design choice, not proof that uniform sampling violates IID. In the proposed audit, report the sampling weights and evaluate the final system at the intended clinical unit and operating point.

## Dependence-aware evaluation

### Leakage, uncertainty, and transport are different checks

- **Leakage prevention:** Keep all relevant observations from a patient together when the claim concerns new-patient performance; check identity linkage across datasets as well as within a dataset ([Rouzrokh et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC9533091/)).
- **Dependence-aware uncertainty:** For repeated observations per patient, resample patients with replacement and retain their associated observations when computing a cluster-bootstrap performance interval ([clustered-AUC bootstrap methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC10728486/)).
- **Transport evaluation:** Use held-out sites, eras, or acquisition settings when those match the generalization question, rather than treating a patient split as evidence for every deployment setting ([generalizability review](https://pmc.ncbi.nlm.nih.gov/articles/PMC9885377/)).

A bootstrap interval for a fixed model evaluated on held-out patients describes test-sample variation under its resampling assumptions; it is not automatically an interval incorporating model retraining, hyperparameter selection, or uncertainty about new hospitals. Proposed reporting should state which of those sources of variation are included.

With few hospitals, broad claims about a population of hospitals remain weak even when there are many patients. Resampling patients within observed hospitals does not create evidence about unobserved hospital variation; a proposed multi-site analysis should report site-specific results and qualify its target of inference.

### A three-splits evaluation design

The following is a proposed demonstration, not a predicted performance ranking:

| Evaluation design | Question addressed | Main caveat |
|---|---|---|
| Patch-random split | How well does the model perform when related patient data can occur in both partitions? | Deliberately unsuitable as the sole test of new-patient generalization |
| Patient-disjoint split | How well does it perform for new patients from the represented source setting? | Does not establish performance at unseen hospitals or future eras |
| Site/time holdout | How well does it perform in specified held-out domains? | Domain difficulty, prevalence, sample size, and case mix may differ |

A site-holdout result can be higher or lower than an internal test result, depending on case mix, acquisition, sample size, and task difficulty. The most informative evaluation design is the one that matches the intended generalization claim.

Proposed controls: hold architecture and preprocessing fixed where feasible; perform development and threshold selection without the final test data; document training-size differences; repeat appropriate splits; and use a separate common patient-disjoint test when the aim is to compare training strategies fairly. If the test populations differ, interpret score differences as a combination of training and test-design effects, not a clean causal estimate of leakage alone.

For detection, proposed reporting should include lesion sensitivity at defined false positives per scan, handling of unmatched detections, lesion matching rules, and patient-aware intervals. For report generation, use finding/claim-level error and clinically consequential omissions or additions rather than treating a single classification AUC as the whole task.

## Heterogeneity and shift: an explicit taxonomy

Use “feature-distribution difference” for an observed difference in $P(X)$ unless the assumptions needed for a specific shift model have been established. Covariate shift, label shift, and changes in conditional relationships impose different constraints and can occur in combinations ([Dombrowski](https://arxiv.org/html/2409.17800v2)).

| Description | Observed or assumed difference | What not to conclude automatically |
|---|---|---|
| Feature-distribution difference | $P(X)\ne Q(X)$ | That labels or clinical performance changed |
| Strict covariate shift | $P(X)\ne Q(X)$, with $P(Y\mid X)=Q(Y\mid X)$ | That the conditional-invariance assumption follows from an unlabeled test |
| Label-prevalence difference | $P(Y)\ne Q(Y)$ | That pure label shift holds |
| Strict label shift | $P(Y)\ne Q(Y)$, with $P(X\mid Y)=Q(X\mid Y)$ | That prevalence reweighting alone will fix arbitrary domain differences |
| Conditional relationship change | $P(Y\mid X)\ne Q(Y\mid X)$ | That reader behavior is the cause |
| Acquisition/metadata difference | Scanner, protocol, era, or population composition differs | That its effect is separable from correlated site factors |
| Dependence/quantity structure | Different counts per patient/site, serial repeats, related documents | That there is one scalar effective size for all analyses |

Co-occurrence among findings deserves explicit assessment in multi-finding CT tasks. Proposed checks include per-finding prevalence, pairwise co-occurrence, conditional performance when associated findings are absent, and errors on unusual combinations; label-derived analyses should report annotation uncertainty.

## Methods menu: established tools and proposed uses

### Distribution comparisons

The tools below are established statistical or data-analysis methods; their proposed combination into a clinical audit still requires validation. Imaging reviews describe metadata tests, MMD, and domain classifiers, while emphasizing dependence on sample size, representations, and the shift being simulated or observed ([Dombrowski](https://arxiv.org/html/2409.17800v2)).

| Method | What it can assess | Important limitation / proposed safeguard |
|---|---|---|
| Counts, proportions, missingness, distribution plots | Known composition differences | Make units, denominators, and missing categories explicit |
| Standardized differences / risk differences | Magnitude of differences in measured attributes | Do not turn a conventional threshold into a universal clinical safety rule |
| KS or Wasserstein comparisons of continuous attributes | Distributional differences beyond a mean | Report scale, effect magnitude, sample size, and cluster-aware uncertainty |
| Chi-square or appropriate exact tests | Categorical composition differences | Sparse cells and dependence require attention |
| Hellinger / Jensen-Shannon / total variation | Differences in label or category probabilities | Estimate uncertainty; rare categories and smoothing affect results |
| KL divergence | Directional probability discrepancy | Zero estimated probabilities can dominate; report smoothing and direction |
| Wasserstein over categories | Transport cost when a meaningful ground metric exists | Nominal labels have no intrinsic numeric distance; do not assign arbitrary category ranks |
| MMD | Multivariate two-sample discrepancy through a kernel | Encoder, scaling, kernel/bandwidth, power, and resampling determine practical sensitivity |
| Source-versus-target classifier | Whether represented samples are distinguishable | Use held-out patients, avoid identifier leakage, and evaluate imbalance-aware baselines |
| Gaussian Fréchet-style feature distance | Difference in feature means/covariances under a Gaussian summary | Not a full distribution comparison or generic certificate of clinical similarity |

For a characteristic kernel, population MMD is zero if and only if the two distributions on the tested space are equal. In finite samples this becomes an estimation/testing problem, and an encoder can discard distinctions that remain important in the original images ([Gretton et al., kernel two-sample test](https://www.jmlr.org/papers/volume13/gretton12a/gretton12a.pdf)).

### Valid inference and interpretation

- **Resampling unit:** Ordinary row-wise permutation assumes an exchangeability structure that correlated patches may not have; proposed tests should permute independent patient-level units or use a justified dependence-aware alternative.
- **Sample-size sensitivity:** Repeat comparisons at matched patient counts and across subsamples, reporting a sensitivity curve rather than one unqualified distance.
- **Multiple comparisons:** Specify confirmatory comparisons in advance, report exploratory screening separately, and control error rates where hypothesis tests are used.
- **Negative controls:** Compare compatible random partitions of the same reference population to characterize ordinary finite-sample variation.
- **Positive controls:** Introduce documented changes such as a prevalence shift or plausible reconstruction perturbation, without claiming that synthetic changes reproduce every clinical shift.
- **Clinical relevance:** Relate discrepancy to model errors and clinical endpoints on an independent evaluation set; do not declare harm from a p-value alone.

The distinction between statistical significance and useful effect magnitude is especially important in large datasets, and nonsignificance does not demonstrate absence of an effect ([medical-imaging methodology review](https://pmc.ncbi.nlm.nih.gov/articles/PMC9005663/)). Medical-image drift research also explicitly warns that drift and performance deterioration are not interchangeable ([Dombrowski](https://arxiv.org/html/2409.17800v2)).

### Attribution and conditional shift are harder

A classifier that distinguishes hospitals establishes separability in the chosen representation, not that scanner hardware caused it. Patient mix, protocol, disease severity, annotation, and unmeasured factors can be confounded, so causal decomposition requires additional design or assumptions ([Dombrowski](https://arxiv.org/html/2409.17800v2)).

Proposed approaches, from descriptive to more demanding:

- **Stratified comparison:** Compare sites within measured protocol or demographic strata, reporting overlap and sparse cells.
- **Adjustment or reweighting:** Compare measured covariate-adjusted summaries, stating positivity/support and model assumptions.
- **Variance-component models:** Explore scanner, patient, reader, and site contributions where sufficient independent variation exists.
- **Matched or repeated acquisitions:** Use available repeated scans or standardized acquisitions to reduce some confounding, with residual limitations stated.
- **Reader-standardization studies:** Have readers from different settings evaluate shared cases using an explicit annotation protocol.

Different outputs of separate site-trained models do not establish $P(Y\mid X)$ changed; they can reflect estimation error or different input support. Without labels, a general test of a change in that conditional relationship is not available from the input distribution alone; conditional-shift assessment therefore requires explicit identification assumptions and suitable reference data.

## Text and embedding distributions

### Probability models remain well-defined

For a fixed vocabulary and fixed-length token sequence, the chain rule defines a joint probability model,

```math
p_\theta(t_1,\ldots,t_T)
=\prod_{s=1}^{T}p_\theta(t_s\mid t_{<s}).
```

This factorization does not assume tokens are independent. Variable-length generation additionally requires a specified treatment of length/end-of-sequence; defining a sampling process is different from having a universally representative “distribution of English.”

For a deterministic token embedding $E$ and token probabilities $p_v$, the pushforward law is explicitly

```math
P_H=\sum_{v\in V}p_v\,\delta_{E(v)}.
```

Thus embedding-space probability is not intrinsically undefined: it is an induced distribution. For contextual embeddings, the induced law also depends on the sampled contexts, token positions, model, layer, and extraction rule.

No Gaussian, Bernoulli, or heavy-tail family automatically carries through an arbitrary learned mapping. Under a finite vocabulary and fixed finite token vectors, the static embedding distribution has finite support and finite moments; heavy-tailed rank-frequency behavior does not imply infinite-variance embedding coordinates.

### Geometry is informative but not a semantic oracle

Removing a common mean and selected dominant directions improved particular static word representations on the tasks tested in “All-but-the-Top.” That result does not establish that the top principal components of every medical sentence encoder or VLM are frequency-only nuisance ([Mu, Bhat, and Viswanath](https://arxiv.org/abs/1702.01417)).

Proposed safeguards: compare encoder/layer choices; inspect associations with frequency, length, site, and clinical concepts; validate preprocessing against the downstream audit purpose; and do not remove principal components merely because they explain substantial variance. Do not assume a universal intrinsic dimension or that meaning resides only in low-variance directions.

### Corpus audit approaches

These are proposed applications of descriptive, duplicate-detection, and distribution-comparison methods:

| Audit component | Suggested evidence | What it does not establish |
|---|---|---|
| Provenance and corpus composition | Sources, dates, languages, specialties, document types, exclusions, sampling weights | That disclosed sources equal the complete pretraining corpus |
| Duplication | Exact matching, near-duplicate text matching, document-family linkage | That every similar template is leakage or unnecessary redundancy |
| Patient/document dependence | Patient/encounter linkage, copied-note families, document versions | One universal token-level effective sample size |
| Clinical concept coverage | Validated concept extraction with negation, temporality, and uncertainty handling | Clinical knowledge or competency from term frequency alone |
| Representation comparison | Frozen-encoder MMD, domain classification, neighborhood diagnostics | Semantic completeness or factual correctness |
| Temporal analysis | Reliable timestamps, guideline-era labels where available | Exact training cutoff inferred solely from model phrasing |
| Target-use evaluation | Adjudicated claims, task success, subgroup error, abstention | Safety outside the measured setting |

Document length and chunking should be explicit in the proposed audit: uniformly sampling chunks weights long documents differently from uniformly sampling documents. Compare both only when each answers a stated question.

If pretraining data are undisclosed, label any disclosed-source analysis as partial and any proxy corpus as a proxy. Output resemblance, memorized phrases, or membership-inference signals do not reconstruct the full training distribution and must not be presented as proof of it.

## Joint image-text and VLM audits

### Matching marginals does not establish matching pairs

This constructed example makes the issue precise. Let binary image feature $X$ and text feature $T$ each have marginal probability $1/2$.

In source data, assign probability $1/2$ to each pair $(0,0)$ and $(1,1)$; in target data, assign probability $1/2$ to each pair $(0,1)$ and $(1,0)$. The image and text marginals match exactly, but the pairing relationship reverses.

Therefore, separate image and text comparisons can miss an important joint change. Proposed VLM audits should assess alignment in addition to each modality's marginal distribution.

### Feasible proposed approaches

- **Pair integrity:** Check study/report identity, acquisition/report times, amendments, laterality, and reference-image linkage where metadata permit.
- **Joint representations:** Compare concatenated or interaction-aware paired embeddings with a frozen, documented representation.
- **Alignment controls:** Compare genuine pairs with within-patient, within-site, or within-finding shuffled pairs, each testing a different alternative.
- **Retrieval diagnostics:** Measure image-to-report and report-to-image retrieval with patient-disjoint candidate pools; control templates and source cues.
- **Finding co-occurrence:** Compare common and unusual combinations using reliable reference labels.
- **Context conflict:** Hold an image fixed while varying clinical text, distinguishing appropriate use of context from ungrounded changes in image findings.
- **Behavior under shift:** Relate pairing or feature discrepancy to false assertions, omissions, grounding/localization error, and selective performance.

These designs are complementary probes, not a certificate that a VLM “uses vision correctly.” Synthetic swaps and conflicting histories can create unrealistic cases, and a report may legitimately contain prior-study or clinical information not visible in a single current image.

## Calibration, semantic uncertainty, and conformal methods

### Define the event before calibrating

For a binary correctness event $C$ and reported score $S$, population calibration can be expressed as

```math
\mathbb E[C\mid S]=S.
```

Possible events include correct next-token prediction, correctness of an answer option, correctness of one finding claim, or acceptability of a whole report. These are different targets; empirical evidence of calibration on one task/format does not establish calibration on a new task ([Kadavath et al.](https://arxiv.org/abs/2207.05221)).

Softmax and decoding do not make calibration mathematically impossible. For a proposed medical-VLM evaluation, fix the model version, prompt/context policy, decoding procedure, claim extraction, reference standard, and population before estimating reliability, proper scoring rules, or selective risk.

Semantic entropy measures variation across sampled meanings and was developed to detect confabulations; it is not itself a calibrated probability that an answer is true. Consistently wrong answers can have low semantic entropy ([Farquhar et al.](https://www.nature.com/articles/s41586-024-07421-0)).

Calibration should be measured for the specific model, task, and population of interest. Comparisons across base and post-trained models should use a common evaluation protocol rather than assume a universal direction of change.

### Exchangeability and the unit of coverage

Standard split conformal prediction provides finite-sample marginal coverage under the required exchangeability of calibration and test observations/scores, with a properly separated model-fitting procedure. Its usual guarantee is not pointwise correctness for every case or automatic coverage within every subgroup ([Angelopoulos and Bates](https://dl.acm.org/doi/10.1561/2200000101), [conformal guarantees tutorial](https://www.auai.org/uai2024/public/tutorial_slides/UAI2024_Tutorial_3_ConformalPred.pdf)).

```math
\Pr\{Y_{\mathrm{new}}\in C_\alpha(X_{\mathrm{new}})\}
\ge 1-\alpha.
```

Exchangeability is invariance of the joint law under permutation; it is weaker than IID but not synonymous with arbitrary dependence. Moving from one site to another can invalidate the assumptions behind the original guarantee, without ensuring that observed coverage will necessarily worsen ([design-based conformal prediction](https://arxiv.org/html/2303.01422v2)).

Conformal language modeling calibrates sampling/rejection procedures and establishes guarantees for acceptable candidate sets and selected components in its specified setting; the paper includes radiology report generation. Those guarantees should not be paraphrased as “every report is correct with probability 90%” ([Quach et al.](https://arxiv.org/abs/2306.10193)).

Proposed extension: evaluate patient-level and subgroup coverage, set size, claim retention, and clinical error under a documented site/time shift. Multiple claims from the same patient must not simply be treated as independent calibration cases; the chosen unit and any cluster-aware conformal method need explicit justification.

## Cleanlab: capabilities and complementary methods

This assessment concerns documented open-source Datalab capabilities, not an exhaustive audit of every commercial Cleanlab service. The relevant question is how its outputs fit into a dependence- and deployment-aware workflow, not whether Cleanlab “solves IID.”

### Documented capabilities

- **Ordering-based non-IID check:** Datalab compares index-gap behavior for feature neighbors and random pairs, with an overall statistical-test p-value; it explicitly advises preserving order for this check ([Datalab issue guide](https://docs.cleanlab.ai/stable/cleanlab/datalab/guide/issue_type_description.html)).
- **Checks without class predictions:** Near-duplicate and feature-based outlier checks can use feature vectors or a neighbor graph without requiring class predictions ([Datalab issue guide](https://docs.cleanlab.ai/stable/cleanlab/datalab/guide/issue_type_description.html)).
- **Underperforming groups:** The detector uses predicted probabilities with features, a graph, or supplied `cluster_ids`; its documented performance proxy uses self-confidence for given labels, supporting analysis of either discovered clusters or supplied groupings ([Datalab issue guide](https://docs.cleanlab.ai/stable/cleanlab/datalab/guide/issue_type_description.html)).
- **Reporting:** Datalab exposes example-level results and dataset summaries for inspecting detected issues ([Datalab issue guide](https://docs.cleanlab.ai/stable/cleanlab/datalab/guide/issue_type_description.html)).

A non-significant ordering-test p-value after shuffling is not proof of IID and is not guaranteed on every shuffle. It addresses evidence against the tested ordering null, not a universal property of the underlying cohort ([Datalab issue guide](https://docs.cleanlab.ai/stable/cleanlab/datalab/guide/issue_type_description.html)).

### Complementary audit components

Proposed contributions to evaluate against existing tools:

- **Hierarchy-aware evaluation:** Patient/encounter/study grouping, leakage checks, bootstrap uncertainty, and explicit estimands.
- **Named-domain comparison:** Matched-size site/scanner/time comparisons with effect sizes and appropriate inference.
- **Behavior linkage:** Relating detected differences to clinical model errors, rather than declaring every unusual example defective.
- **Joint multimodal structure:** Pair integrity, image-text co-occurrence, and grounded report evaluation.
- **Evidence packaging:** A reproducible manifest recording data/model/encoder versions, assumptions, missing information, and limits of inference.

These are integration and domain-methodology opportunities, not claims that no other open-source project contains related components. Cleanlab should be one baseline or reusable component, and a project should document exactly what it adds beyond the baselines it actually evaluates.

## Federated learning and imaging-CDM connections

In the proposed FL extension, clients are explicit partitions for label, feature, metadata, and outcome comparisons. Treat partition-generation settings, such as a Dirichlet parameter, as design inputs rather than measured degrees of clinically relevant heterogeneity; test whether measured discrepancies predict held-out behavior of the actual FL methods compared.

Do not assume FedProx or FedPer must win for a given scalar distance. Proposed comparisons should hold the task, client sampling, compute, tuning process, and target population as consistent as possible, reporting personalization and global-model results separately when they answer different questions.

OHDSI's Medical Imaging Working Group aims to link imaging and algorithmically generated measurements with OMOP clinical data and describes a proposed imaging extension. This supports a provenance/infrastructure connection, not a claim that a particular audit schema is already adopted ([OHDSI ImageWG](https://ohdsi.github.io/ImageWG/)).

Proposed integration: version audit manifests alongside cohort definitions and model-derived findings, retaining source links, analysis units, transformations, and model identifiers. Verify the actual extension and vocabulary versions before implementing mappings; do not declare a cohort “IID enough” merely because it has a CDM representation.

## A practical research agenda, without prescribing team tasks

The following are optional project shapes. Each can be useful without training a new foundation model or building a complete product.

| Proposed contribution | Minimum credible demonstration | Principal limit to acknowledge |
|---|---|---|
| Dependence-aware evaluation harness | Reproduce patient grouping and compare appropriate uncertainty estimates | Does not infer all hidden dependencies from images |
| Multi-axis cohort report | Document metadata, labels, representation discrepancy, and sample-size sensitivity | Describes differences; does not identify causes automatically |
| Controlled benchmark | Combine a known simulated mechanism with at least one real-data evaluation | Simulations need not represent real clinical shifts |
| Text-corpus comparison | Compare accessible corpora with document/patient linkage and sensitivity to encoder/chunking | Cannot audit undisclosed training data directly |
| VLM pairing audit | Show a joint discrepancy missed by marginal checks, then evaluate behavior | An alignment metric is not clinical correctness |
| Claim-level calibration study | Use adjudicated claims, patient-disjoint calibration/test sets, and group results | Prompt, scorer, and population dependence remain |
| Audit manifest / provenance layer | Reproduce a result from versioned data/model/analysis metadata | A readable report is not regulatory validation |

Suggested evidence package:

- **Claim and target:** Intended task, population, prediction unit, evaluation unit, and estimand.
- **Data structure:** Patient/study/site counts, observation-count distributions, identity-linkage limitations, missingness, and access constraints.
- **Methods:** Split rules, weights, encoders, kernels/distances, tuning, inference unit, and multiple-testing choices.
- **Results:** Effect sizes, uncertainty, relevant model behavior, and positive/negative controls.
- **Limits:** Unsupported axes, sparse groups, confounding, inaccessible corpora, and absence of external labels.
- **Reproducibility:** Code, versioned configuration, data manifest or retrieval instructions, and a description of what can legally be shared.

The value of a result depends on whether the evidence supports its stated claim, rather than whether it uncovers a dramatic failure. A well-powered null finding or a documented limitation of a proposed metric can be a useful research outcome.

## Synthesis

The methodological objective is not to prove IID in the abstract. It is to make the data-generating assumptions, dependence, population differences, and model-evaluation claims explicit enough to test, qualify, and reproduce.

A useful audit connects three layers: the structure of the available evidence, measurable differences between relevant populations, and the consequences for a defined clinical task. Its conclusions should state what was assessed, which assumptions were required, and where additional data or validation remain necessary.
