# Measuring non-IIDness: a reference

A starting map of published and standard measures, what each one can see, and what it misses. The gaps are where your toolkit can contribute. For the theory behind them, see [background.md](background.md).

## Start from the question, not the score

A useful audit asks several questions and answers each one separately. One universal "IID score" hides which assumption broke.

| Question | Useful methods |
| --- | --- |
| Do training and test sets share patients or related observations? | Patient and study identifiers, duplicate and near-duplicate checks, patient-grouped splitting |
| Do known attributes differ across sites? | Distribution plots, standardized differences, categorical proportion comparisons, KS or chi-square tests |
| Do image representations differ? | Maximum mean discrepancy (MMD), Wasserstein distance, held-out classifiers trained to tell source from target |
| Are the differences distinguishable from sampling noise? | Permutation tests, multiple-testing control, uncertainty estimates |
| Do the differences affect the model? | Patient-, site- and time-held-out evaluation; subgroup performance and calibration |

Patient-aware splitting addresses leakage. Two-sample tests and domain classifiers address distributional differences. They are complementary checks, not substitutes for each other.

Failing to detect a difference does not establish IID. The test may lack power, or it may look at a representation that misses the difference that matters.

## Published methods

| Method | Sees | Blind to |
| --- | --- | --- |
| [EMD over labels (Zhao et al. 2018)](https://arxiv.org/abs/1806.00582) | Label prior skew | Anything about the images; clustering |
| [Hellinger distance (2025 assessment)](https://arxiv.org/html/2503.17070v2) | Label prior skew | Same as EMD |
| [Heterogeneity Index (AAAI 2021)](https://cdn.aaai.org/ojs/17291/17291-13-20785-1-2-20210518.pdf) | One scalar of overall difference | Which axis moved |
| Multi-modal divergence (labels, features, outputs) | Prior, covariate, partly concept shift | Clustering within a client |
| [Non-IID degree estimation](https://pmc.ncbi.nlm.nih.gov/articles/PMC12290147/) | Criteria for judging estimators (variability, separability, compute time) | n/a |
| [Client2Vec (ICCV 2025)](https://openaccess.thecvf.com/content/ICCV2025/papers/Guo_Client2Vec_Improving_Federated_Learning_by_Distribution_Shifts_Aware_Client_Indexing_ICCV_2025_paper.pdf) | Ranks clients by how far they shifted | Why they differ |
| [Distance-aware non-IID FL for segmentation (PMLR 2024)](https://proceedings.mlr.press/v250/alekseenko24a.html) | Imaging-specific distances | Concept shift |

A shared gap: almost all of these treat each client as an internally IID bag. Clustering within a client (repeat patients, intracluster correlation, effective sample size) goes unmeasured.

## Measure families

**f-divergences (KL, JS, Hellinger, total variation).** Fine on discrete labels. Poor in embedding space: different scanners produce nearly disjoint supports, so KL blows up and JS saturates at log 2, which leaves no dose-response. A practical stand-in is a classifier two-sample test: total variation is tied to the best classifier's accuracy at telling two samples apart. Report AUC.

**Wasserstein (optimal transport).** Not information-theoretic, but geometry-aware and does not saturate. Strongest on clinically meaningful one-dimensional quantities: W1 over maximum aortic diameter is in millimeters, which a surgeon and a regulator can both read. In embedding space it inherits whatever the distance metric emphasizes, often scanner directions, and has poor sample complexity in high dimensions. Sliced or Sinkhorn variants help.

**Maximum mean discrepancy (MMD).** Unbiased estimator, permutation test, tolerable in high dimensions. Kernel choice matters.

**Mutual information with site as a variable.** Treat the hospital S as a random variable. The chain rule splits what the data tells you about the hospital into parts:

```
I(S; X, Y) = I(S; X) + I(S; Y | X)
```

- `I(S; X)`: covariate or acquisition shift. Can you tell the hospital from the image?
- `I(S; Y | X)`: concept shift. Does the hospital still predict the label once you have seen the image? Different labeling conventions live here.
- `I(S; Y)`: label prior shift, which EMD and Hellinger approximate.

Estimate with calibrated, held-out classifiers. Variational MI bounds cap out near log n, and `I(S; Y | X)` is only as good as your model of `P(Y | X)`.

## Clustering and effective sample size

For clustered data, the design-effect approximation (worked example in [background.md](background.md), section 2):

```
n_eff = n / (1 + (k - 1) * rho)
```

with `k` the cluster size and `rho` the intracluster correlation. Confidence interval width scales with `1 / sqrt(n_eff)`, not `1 / sqrt(n)`.

## Always report a null

A distance with no reference is not a finding. Compare against the same measure computed between random halves of a single hospital at the same sample size. Small samples look more different by chance.

- **Negative control:** random partitions of one reference hospital, as above, to show ordinary finite-sample variation.
- **Positive control:** plant a change yourself, such as a prevalence shift, and check that your measure sees it. A synthetic change will not reproduce every real one, so say so.
- **Resample the right unit:** if a patient has several scans, permute or bootstrap patients, not rows. Row-wise permutation assumes independence the data may not have.
- **Sample size:** compare at matched patient counts and show how the distance moves with sample size, rather than one unqualified number.
- **Many comparisons:** decide your main comparisons in advance, report exploratory screening separately, and control the error rate where you run tests.
- **Clinical relevance:** a p-value alone does not show harm. Tie a difference to model errors or clinical endpoints. A detected shift does not by itself mean the model got worse, and failing to detect one does not mean the data are IID.
