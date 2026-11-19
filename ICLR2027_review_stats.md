# ICLR 2027 – Basic review statistics

Computed from the first snapshot (crawled 2026-11-06, right after the reviews went public), so these numbers predate the rebuttal period. Source: `reviews.csv` and `papers.csv`.

> **Note on scale:** the ratings in this venue are integers **1–4** (not the 1–10 scale of earlier ICLRs); the label text for each value is not present in the crawled data, so thresholds below are on the raw numbers. Std/variance are *population* (ddof=0) within a paper, over its reviews; papers with 1 review have variance 0.

## 1. Overview

| Item | Value |
|---|---|
| Papers in crawl | 42,790 |
| – active submissions | 40,557 |
| – withdrawn | 551 |
| – desk-rejected | 1,682 |
| Papers with ≥1 review | 40,642 |
| Papers with ≥1 review (active submissions, used below) | 40,399 |
| Total reviews | 125,613 |
| Reviews / paper (mean) | 3.09 |

Reviews per paper: 1: 4, 2: 328, 3: 36,421, 4: 3,305, 5: 324, 6: 16, 7: 1

## 2. Review-level scores

| Field | Mean | Std | Median |
|---|---|---|---|
| rating_num | 2.059 | 0.684 | 2 |
| confidence_num | 2.831 | 0.715 | 3 |
| soundness | 1.948 | 0.568 | 2 |
| presentation | 2.263 | 0.647 | 2 |
| informativeness | 1.910 | 0.506 | 2 |

**Rating distribution**

| Rating | #Reviews | % |
|---|---|---|
| 1 | 23,953 | 19.1% |
| 2 | 72,138 | 57.4% |
| 3 | 27,630 | 22.0% |
| 4 | 1,892 | 1.5% |

Correlation of rating with: confidence_num -0.15, soundness 0.50, presentation 0.40, informativeness 0.53

## 2a. Rating counts per review

| Rating | #Reviews (all) | % | #Reviews (active submissions only) | % |
|---|---|---|---|---|
| 1 | 23,953 | 19.1% | 23,574 | 18.9% |
| 2 | 72,138 | 57.4% | 71,793 | 57.5% |
| 3 | 27,630 | 22.0% | 27,607 | 22.1% |
| 4 | 1,892 | 1.5% | 1,892 | 1.5% |
| **Total** | **125,613** | 100% | **124,866** | 100% |

Rating × confidence (number of reviews):

| Rating \ Confidence | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| 1 | 255 | 5,252 | 11,660 | 6,786 |
| 2 | 898 | 22,321 | 38,044 | 10,875 |
| 3 | 728 | 10,604 | 13,024 | 3,274 |
| 4 | 16 | 602 | 833 | 441 |

- Reviews rated 3 or higher: 29,522 (23.5%); rated 2 or lower: 96,091 (76.5%).

## 3. Paper-level scores (active submissions with ≥1 review)

| Metric | Value |
|---|---|
| Mean of paper-mean rating | 2.061 |
| Median of paper-mean | 2.000 |
| Std of paper-mean | 0.449 |
| **Avg within-paper variance** | 0.265 |
| Avg within-paper std | 0.428 |
| Avg range (max−min) | 0.949 |
| Papers with zero disagreement (all reviews equal) | 9,673 (23.9%) |
| …among papers with ≥3 reviews | 9,518 (23.8%) |

**Paper-mean rating buckets**

| Mean in | #Papers | % |
|---|---|---|
| [1, 1.5) | 3,999 | 9.9% |
| [1.5, 2) | 8,188 | 20.3% |
| [2, 2.5) | 21,448 | 53.1% |
| [2.5, 3) | 5,086 | 12.6% |
| [3, 3.5) | 1,640 | 4.1% |
| [3.5, 4] | 38 | 0.1% |

## 4. Threshold counts (per paper, over all its reviews)

| Condition | #Papers | % of reviewed |
|---|---|---|
| all ratings ≥ 3 | 1,056 | 2.6% |
| all ratings ≥ 2 | 22,964 | 56.8% |
| all ratings < 3 (max ≤ 2) | 19,415 | 48.1% |
| all ratings < 2 (all = 1) | 822 | 2.0% |
| all ratings = 2 | 8,036 | 19.9% |
| all ratings = 4 | 3 | 0.0% |
| at least one rating ≥ 3 | 20,984 | 51.9% |
| at least one rating = 4 | 1,791 | 4.4% |
| at least one rating = 1 | 17,435 | 43.2% |
| mean ≥ 3 | 1,678 | 4.2% |
| mean ≥ 2.5 | 6,764 | 16.7% |
| mean < 2 | 12,187 | 30.2% |
| range ≥ 2 (strong disagreement) | 7,189 | 17.8% |
| range = 3 (1 vs 4) | 414 | 1.0% |

Same, restricted to papers with ≥3 reviews (n = 40,067):

| Condition | #Papers | % |
|---|---|---|
| all ratings ≥ 3 | 1,033 | 2.6% |
| all ratings ≥ 2 | 22,757 | 56.8% |
| all ratings < 3 | 19,210 | 47.9% |
| all ratings = 1 | 793 | 2.0% |

## 5. By primary area (≥200 reviewed papers)

| Area | #Papers | Mean rating | Avg var | %all≥3 | %all<3 |
|---|---|---|---|---|---|
| generative models | 2,745 | 2.157 | 0.253 | 3.8% | 40.5% |
| learning theory | 1,297 | 2.129 | 0.339 | 5.3% | 38.7% |
| applications to robotics, autonomy, planning | 2,139 | 2.124 | 0.247 | 2.9% | 43.9% |
| applications to computer vision, audio, language, and other modalities | 5,168 | 2.112 | 0.234 | 2.5% | 46.8% |
| optimization | 1,535 | 2.086 | 0.287 | 3.3% | 45.2% |
| infrastructure, software libraries, hardware, systems, etc. | 665 | 2.078 | 0.283 | 3.5% | 43.8% |
| foundation or frontier models, including LLMs | 6,334 | 2.071 | 0.258 | 2.8% | 48.3% |
| datasets and benchmarks | 2,967 | 2.058 | 0.274 | 2.6% | 47.0% |
| applications to neuroscience & cognitive science | 693 | 2.054 | 0.288 | 1.4% | 45.7% |
| probabilistic methods (Bayesian methods, variational inference, sampling, UQ, etc.) | 847 | 2.046 | 0.304 | 2.6% | 44.4% |
| reinforcement learning | 2,258 | 2.045 | 0.268 | 2.3% | 49.6% |
| unsupervised, self-supervised, semi-supervised, and supervised representation learning | 2,032 | 2.040 | 0.258 | 3.3% | 51.1% |
| alignment, fairness, safety, privacy, and societal considerations | 3,094 | 2.035 | 0.267 | 1.7% | 50.6% |
| learning on graphs and other geometries & topologies | 910 | 2.020 | 0.280 | 2.3% | 50.8% |
| other topics in machine learning (i.e., none of the above) | 1,074 | 2.017 | 0.263 | 2.2% | 52.3% |
| applications to physical sciences (physics, chemistry, biology, etc.) | 1,906 | 2.009 | 0.284 | 1.6% | 50.7% |
| transfer learning, meta learning, and lifelong learning | 1,098 | 1.993 | 0.239 | 1.8% | 55.2% |
| learning on time series and dynamical systems | 1,098 | 1.988 | 0.267 | 1.5% | 54.2% |
| causal reasoning | 318 | 1.977 | 0.292 | 1.9% | 50.3% |
| neurosymbolic & hybrid AI systems (physics-informed, logic & formal reasoning, etc.) | 531 | 1.931 | 0.267 | 1.7% | 57.3% |
| interpretability and explainable AI | 1,690 | 1.924 | 0.286 | 1.7% | 55.2% |

## 6. Papers by mean rating (in steps of 1/3, since most papers have 3 reviews)

Mean is the average rating of a paper's reviews. Papers at or below 2 are grouped together; above that the cut-offs are 2.33 (7/3), 2.67 (8/3), 3.00, and so on.

- **Cumulative**: papers with a mean at or above the cut-off.
- **In band**: papers at or above the cut-off but below the next one (bands do not overlap and add up to the total).

### All active papers with at least 1 review (n = 40,399)

| Condition | Papers (cumulative) | % | Papers (in band) | % |
|---|---|---|---|---|
| mean ≤ 2.00 | 24,225 | 59.96% | 24,225 | 59.96% |
| 2.00 < mean < 2.33 (only possible for papers without exactly 3 reviews) | 799 | 1.98% | 799 | 1.98% |
| mean ≥ 2.33 | 15,375 | 38.06% | 9,240 | 22.87% |
| mean ≥ 2.67 | 6,135 | 15.19% | 4,457 | 11.03% |
| mean ≥ 3.00 | 1,678 | 4.15% | 1,402 | 3.47% |
| mean ≥ 3.33 | 276 | 0.68% | 244 | 0.60% |
| mean ≥ 3.67 | 32 | 0.08% | 29 | 0.07% |
| mean ≥ 4.00 | 3 | 0.01% | 3 | 0.01% |

### Papers with exactly 3 reviews (n = 36,421)

| Condition | Papers (cumulative) | % | Papers (in band) | % |
|---|---|---|---|---|
| mean ≤ 2.00 | 22,072 | 60.60% | 22,072 | 60.60% |
| 2.00 < mean < 2.33 (only possible for papers without exactly 3 reviews) | 0 | 0.00% | 0 | 0.00% |
| mean ≥ 2.33 | 14,349 | 39.40% | 8,557 | 23.49% |
| mean ≥ 2.67 | 5,792 | 15.90% | 4,230 | 11.61% |
| mean ≥ 3.00 | 1,562 | 4.29% | 1,294 | 3.55% |
| mean ≥ 3.33 | 268 | 0.74% | 238 | 0.65% |
| mean ≥ 3.67 | 30 | 0.08% | 28 | 0.08% |
| mean ≥ 4.00 | 2 | 0.01% | 2 | 0.01% |
