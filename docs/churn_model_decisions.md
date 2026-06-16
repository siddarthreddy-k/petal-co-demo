# Petal & Co — Churn Prediction Model Decisions

**Schema Works | CTO Skills Gap: Data & AI**

| Item | Detail |
|---|---|
| Version | v1.0 — Day 1 + Day 2 |
| Date | 13 June 2026 |
| Author | Siddarth Reddy, Schema Works |
| Data source | `PETAL_CO_DW.MARTS.FACT_SUBSCRIPTIONS` (Snowflake) |
| Rows | 1,911 subscribers |
| Target variable | `IS_CHURNED` (boolean — pre-defined in dbt mart) |
| Final feature set | 13 features (after leakage removal) |
| Models trained | Logistic Regression, Random Forest, XGBoost |
| Best model AUC | XGBoost — 0.933 test, 0.925 CV (5-fold) |
| Output | `churn_risk_scores_v2.csv` — 1,911 rows scored with risk band and top churn driver |

---

## 1. Overview

This document records every modelling decision made during the Petal & Co churn prediction build — from data source selection and feature engineering to model choice and result interpretation. It is intended as a reference for client conversations, future model iterations, and Schema Works portfolio documentation.

---

## 2. Data Source & Target Variable

### 2.1 Source Table

The model draws from `FACT_SUBSCRIPTIONS`, the subscription fact table built by the Petal & Co dbt pipeline. This is a mart-layer table — one row per subscriber — containing lifetime order metrics, plan information, and status flags derived from the RAW and STAGING layers.

### 2.2 Target Variable — IS_CHURNED

`IS_CHURNED` is a boolean field defined in the dbt mart (`fact_subscriptions.sql`) as the logical inverse of `IS_ACTIVE`. A subscriber is marked as churned when their `STATUS` field transitions to `Cancelled` in the source data. No additional label engineering was required.

> **Class Balance:** 1,493 active (78.1%) vs 418 churned (21.9%). With a 22% minority class this is a mild imbalance — manageable without SMOTE or other resampling. All models used `class_weight='balanced'` (or `scale_pos_weight` for XGBoost) to account for this automatically.

| Status | Count | % of total |
|---|---|---|
| Active (IS_CHURNED = False) | 1,493 | 78.1% |
| Churned (IS_CHURNED = True) | 418 | 21.9% |

---

## 3. Exploratory Data Analysis

### 3.1 Churn by Plan Type

Monthly subscribers churn at **31%** vs **6%** for quarterly subscribers — a 5× difference. This is the single most important business finding from the EDA and is confirmed by all three models as a top predictive signal.

| Plan type | Total | Churned | Churn rate |
|---|---|---|---|
| Monthly | 1,216 | 375 | 31% |
| Quarterly | 695 | 43 | 6% |

### 3.2 Churn by Product Category

Supplements has the highest churn rate at 25%, followed by skincare at 22%. Wellness bundle has the lowest at 20%. The spread is relatively narrow — product category is a weaker predictor than plan type, confirmed by its low SHAP value in the final model.

| Category | Total | Churned | Churn rate |
|---|---|---|---|
| Supplements | 581 | 146 | 25% |
| Skincare | 646 | 141 | 22% |
| Wellness bundle | 276 | 55 | 20% |
| Haircare | 408 | 76 | 19% |

### 3.3 Key Distribution Observations

- **Total orders:** Churned subscribers cluster heavily at 1–4 orders; active subscribers show a flatter, longer-tailed distribution extending to 12+. Engagement frequency is a strong separator.
- **Net revenue:** Churned subscribers concentrate below £200; active subscribers spread to £800+. Higher total spend correlates with retention.
- **Return rate:** Nearly identical distributions for active and churned subscribers. Returns do not predict churn in this dataset — confirmed by near-zero SHAP values for all return-related features.
- **Order interval days:** All churned subscribers are on 30-day intervals (monthly plan); all 90-day are quarterly. This confirms that `order_interval_days` and `plan_type_enc` carry the same signal.

---

## 4. Feature Engineering & Leakage Removal

### 4.1 Leakage Discovery — Three Iterations

The first model run produced **AUC = 1.000** with zero errors on all 5 cross-validation folds. A perfect score on real-world data is almost always a sign of data leakage — where the model is reading the answer from a feature rather than learning to predict it. Three rounds of leakage were identified and removed.

---

#### Iteration 1 — Post-churn status fields

> **Leakage identified:** `CANCELLATION_DATE`, `IS_ACTIVE`, `STATUS` — these fields are only populated or set after the churn event has already occurred. Including them lets the model read the outcome directly.

- `CANCELLATION_DATE`: NULL for all active subscribers, populated for all churned. Perfect separator.
- `IS_ACTIVE`: Boolean inverse of `IS_CHURNED` — literally the same information in a different column.
- `STATUS`: String encoding of the churn state (`Active` vs `Cancelled`).

**Action:** Dropped all three before modelling.

---

#### Iteration 2 — Lifetime-derived features

> **Leakage identified:** `LIFETIME_DAYS`, `ORDERS_PER_MONTH`, `REVENUE_PER_DAY` — `lifetime_days` is calculated in the dbt model as `CANCELLATION_DATE - START_DATE` for churned subscribers. This means the variable encodes the churn event through its own denominator. Any feature derived by dividing by `lifetime_days` inherits this leakage.

- `LIFETIME_DAYS`: For churned subscribers, this equals the exact number of days they were active before cancelling. For active subscribers, it equals days since sign-up. The distributions are non-overlapping — churned cluster at 0–400 days, active spread across 500–900 days.
- `ORDERS_PER_MONTH`: Engineered as `total_orders / (lifetime_days / 30)`. Inherits `lifetime_days` leakage directly.
- `REVENUE_PER_DAY`: Engineered as `total_net_revenue / lifetime_days`. Same inheritance.

**Action:** Dropped all three. AUC remained at 1.000 after this round — a third leakage source was present.

---

#### Iteration 3 — ESTIMATED_MRR

> **Leakage identified:** `ESTIMATED_MRR` is defined in the dbt mart as: `CASE WHEN IS_ACTIVE AND ORDER_INTERVAL_DAYS > 0 THEN revenue / lifetime_days * 30 ELSE 0 END`. The `ELSE 0` branch means every churned subscriber has `ESTIMATED_MRR = 0` by construction. The model learned: `estimated_mrr = 0` → churned.

- `ESTIMATED_MRR` had a logistic regression coefficient of **-8** in the second run — an order of magnitude larger than all other features. This extreme dominance is the signature of a leaking variable.

**Action:** Dropped `ESTIMATED_MRR`. AUC dropped to **0.927** — the first real, trustworthy result.

---

## 5. Final Feature Set — 13 Features

After removing all leaking columns, the following 13 features were used for modelling. Each feature is available at prediction time for any subscriber — there is no post-event information included.

### 5.1 Kept Features

| Feature | Source | Rationale for inclusion |
|---|---|---|
| `plan_type_enc` | Encoded | Monthly vs quarterly — strongest controllable churn lever. Monthly churns 5× more than quarterly. |
| `product_cat_enc` | Encoded | Supplements has highest churn (25%), wellness bundle lowest (20%). Small but real signal. |
| `order_interval_days` | Raw | Carries plan type signal at a continuous level. 30-day = monthly, 90-day = quarterly. |
| `cohort_month` | Engineered | Month of acquisition. Strongest predictor in all three models — captures seasonal acquisition quality. |
| `cohort_quarter` | Engineered | Quarter-level version of `cohort_month`. Reinforces seasonality signal. |
| `avg_order_value` | Raw (dbt) | Higher AOV subscribers tend to be more committed. Retention signal. |
| `total_net_revenue` | Raw (dbt) | Total value delivered over subscription lifetime. Second-strongest Gini feature. High-revenue = lower churn. |
| `total_discounts` | Raw (dbt) | Absolute discount volume. Price-sensitivity proxy — heavy discounting may signal weaker commitment. |
| `discount_rate` | Engineered | Discounts / net revenue. Normalises discount by subscriber size. Engineered to avoid scale confounding. |
| `total_orders` | Raw (dbt) | Order count — engagement frequency. Churned subscribers cluster at 1–4 orders. |
| `total_returns` | Raw (dbt) | Absolute return count. Low SHAP but included to allow the model to surface any edge-case pattern. |
| `return_rate` | Raw (dbt) | dbt-computed return rate. Confirmed near-zero SHAP — returns do not drive churn. |
| `return_ratio` | Engineered | Returns / total orders. Distinct from `return_rate` which may be revenue-weighted. Both retained for completeness. |

### 5.2 Dropped Features — Full Rationale

| Feature | Reason dropped | Explanation |
|---|---|---|
| `CANCELLATION_DATE` | Post-churn leakage | Only populated after cancellation. NULL = active, populated = churned. |
| `IS_ACTIVE` | Post-churn leakage | Boolean inverse of `IS_CHURNED`. Identical information in a different column. |
| `STATUS` | Post-churn leakage | String encoding of churn state: `Active` vs `Cancelled`. |
| `LIFETIME_DAYS` | Post-churn leakage | `= CANCELLATION_DATE - START_DATE` for churned subscribers. Encodes the churn event directly. |
| `ESTIMATED_MRR` | Post-churn leakage | dbt model sets to 0 when `IS_ACTIVE = False`. Every churned subscriber has MRR = 0 by construction. |
| `ORDERS_PER_MONTH` | Derived leakage | `= total_orders / (lifetime_days / 30)`. Inherits `lifetime_days` leakage. |
| `REVENUE_PER_DAY` | Derived leakage | `= total_net_revenue / lifetime_days`. Inherits `lifetime_days` leakage. |
| `TOTAL_GROSS_REVENUE` | Collinearity | Highly correlated with `total_net_revenue`. Removed for parsimony. |
| `TOTAL_ADJUSTED_REVENUE` | Collinearity | Highly correlated with `total_net_revenue`. Removed for parsimony. |
| `FIRST_ORDER_DATE` | Redundant | Captured by `cohort_month` / `cohort_quarter` at the right grain. |
| `LAST_ORDER_DATE` | Post-event | Post-event timestamp — not available at prediction time for churned subscribers. |
| `START_DATE` | Redundant | Identical information to `START_COHORT` at a finer grain. Cohort is preferred. |
| `SUBSCRIPTION_ID` | ID column | Primary key — no predictive value. |
| `CUSTOMER_ID` | ID column | Primary key — no predictive value. |

---

## 6. Model Results

### 6.1 Baseline — Logistic Regression

Logistic regression was trained first as an interpretable baseline. All features were standardised using `StandardScaler`. Class imbalance was handled via `class_weight='balanced'`. 5-fold stratified cross-validation was used throughout given the small dataset size (1,911 rows).

| Metric | Value | Notes |
|---|---|---|
| Test AUC-ROC | 0.927 | Single 80/20 stratified split |
| CV AUC (5-fold) | 0.914 ± 0.014 | More reliable estimate on small dataset |
| Precision (churned) | 0.84 | 84% of predicted churners are true churners |
| Recall (churned) | 0.83 | 83% of true churners correctly identified |
| Accuracy | 0.93 | Overall — inflated by class imbalance |

**Top retention signals (negative coefficients — reduce churn probability):**

- `cohort_month` (−3.58): Strongest signal — later acquisition months significantly reduce churn
- `total_orders` (−2.89): More orders = lower churn — engagement is the key retention driver
- `plan_type_enc` (−1.68): Quarterly plan strongly reduces churn vs monthly
- `order_interval_days` (−1.68): Longer intervals between orders = lower churn

### 6.2 Random Forest

Random Forest was trained with 300 trees, max depth 8, min samples per leaf 10, and `class_weight='balanced'`. No feature scaling required. Gini importance was used for feature ranking.

| Metric | Value | vs Logistic Regression |
|---|---|---|
| Test AUC-ROC | 0.926 | −0.001 vs baseline |
| CV AUC (5-fold) | 0.907 ± 0.012 | −0.007 vs baseline |
| Precision (churned) | 0.76 | −0.08 vs baseline |
| Recall (churned) | 0.77 | −0.06 vs baseline |

> Random Forest does not improve on logistic regression. This tells us the relationships in this dataset are largely linear — there is little non-linear complexity for a tree ensemble to exploit. The logistic regression baseline is genuinely competitive.

### 6.3 XGBoost

XGBoost was trained with 300 estimators, max depth 4, learning rate 0.05, subsample 0.8, colsample_bytree 0.8. Class imbalance handled via `scale_pos_weight = n_negative / n_positive`.

| Metric | Value | vs Logistic Regression |
|---|---|---|
| Test AUC-ROC | 0.933 | +0.006 vs baseline |
| CV AUC (5-fold) | 0.925 ± 0.017 | +0.011 vs baseline |
| Precision (churned) | 0.84 | Equal to baseline |
| Recall (churned) | 0.81 | −0.02 vs baseline |

### 6.4 Model Comparison Summary

| Model | Test AUC | CV AUC | CV Std | Recommended |
|---|---|---|---|---|
| Logistic Regression | 0.927 | 0.914 | ±0.014 | Baseline |
| Random Forest | 0.926 | 0.907 | ±0.012 | No — underperforms |
| **XGBoost** | **0.933** | **0.925** | **±0.017** | **Yes — production model** |

XGBoost is selected as the production model — it achieves the highest CV AUC (0.925) and shows the smallest gap between test AUC and CV AUC, indicating good generalisation. The logistic regression remains useful for explainability and client presentations due to its interpretable coefficients.

---

## 7. SHAP Explainability

SHAP (SHapley Additive exPlanations) values were computed using `TreeExplainer` on the Random Forest model. SHAP values measure the contribution of each feature to each individual prediction — positive SHAP = pushes toward churn, negative SHAP = pushes toward retention.

### 7.1 Feature Ranking by Mean |SHAP|

| Rank | Feature | Mean \|SHAP\| | Interpretation |
|---|---|---|---|
| 1 | `cohort_month` | 0.095 | Acquisition month is the strongest predictor. Q1/Q2 cohorts churn significantly more than Q3/Q4. |
| 2 | `order_interval_days` | 0.091 | Monthly (30-day) subscribers have far higher churn risk than quarterly (90-day). |
| 3 | `cohort_quarter` | 0.086 | Reinforces `cohort_month` — seasonal acquisition quality is the dominant theme. |
| 4 | `plan_type_enc` | 0.083 | Monthly plan = higher churn. Consistent with EDA finding of 31% vs 6% churn rate. |
| 5 | `total_net_revenue` | 0.056 | Higher total spend = lower churn. Value delivered is a retention signal. |
| 6 | `total_orders` | 0.050 | More orders = lower churn. Engagement frequency is protective. |
| 7–13 | Discount + return features | < 0.020 | Weak signals. Returns consistently near zero — returns do not predict churn. |

### 7.2 Key SHAP Findings

1. **Acquisition timing dominates:** `cohort_month` and `cohort_quarter` together account for the largest share of predictive power. This is an acquisition quality signal — certain months bring in subscribers who are fundamentally less likely to stay, independent of what they buy.

2. **Plan structure is the controllable lever:** `order_interval_days` and `plan_type_enc` are second only to cohort timing. Moving subscribers from monthly to quarterly plans is the single highest-impact intervention available to the business.

3. **Returns do not drive churn:** `return_rate`, `return_ratio`, and `total_returns` all have near-zero SHAP values. This finding frees the business from treating the returns process as a retention risk — budget and attention can be redirected accordingly.

---

## 8. Churn Risk Score Output

The final output (`churn_risk_scores_v2.csv`) scores all 1,911 subscribers using the Random Forest model. Each row includes a churn probability, risk band, and top churn driver identified via SHAP.

| Risk band | Probability range |
|---|---|
| Low | 0.00 – 0.33 |
| Medium | 0.33 – 0.66 |
| High | 0.66 – 1.00 |

**Output columns:** `subscription_id`, `customer_id`, `plan_type`, `product_category_key`, `lifetime_days`, `is_churned`, `estimated_mrr`, `churn_probability`, `risk_band`, `top_churn_driver`

### Snowflake ML Tables (`PETAL_CO_DW.ML`)

| Table | Rows | Purpose |
|---|---|---|
| `ML_CHURN_RISK_SCORES` | 1,911 | Per-subscriber churn probability, risk band, top driver |
| `ML_CHURN_SUMMARY` | 1 | C-suite scorecard — MRR-weighted overall risk band |
| `ML_CHURN_SHAP_IMPORTANCE` | 13 | Feature importance with readable labels for Looker Studio |
| `ML_CHURN_INSIGHTS` | 11 | Dynamic key-value store for dashboard scorecards |

---

## 9. Version Log

| Ver. | Date | Author | Changes |
|---|---|---|---|
| v0.1 | 13 Jun 2026 | Siddarth Reddy | First successful run. AUC = 1.000. Leakage identified — `lifetime_days`, `orders_per_month`, `revenue_per_day` included in feature set. |
| v0.2 | 13 Jun 2026 | Siddarth Reddy | Removed `lifetime_days`, `orders_per_month`, `revenue_per_day`. AUC remained 1.000 — `estimated_mrr` identified as second leakage source (dbt `ELSE 0` branch). |
| v0.3 | 13 Jun 2026 | Siddarth Reddy | Removed `estimated_mrr`. AUC = 0.927. First real result. Logistic regression baseline confirmed. |
| v1.0 | 13 Jun 2026 | Siddarth Reddy | Day 2 complete. Random Forest (AUC 0.926), XGBoost (AUC 0.933), SHAP analysis on RF. Final output: `churn_risk_scores_v2.csv` with `top_churn_driver` per subscriber. 4 Snowflake ML tables written. |

---

## 10. Next Steps & Limitations

### 10.1 Model Limitations

- **Dataset size:** 1,911 rows is sufficient for a logistic regression baseline but limits the complexity of tree-based models. A larger dataset would likely improve Random Forest and XGBoost performance relative to logistic regression.
- **Mock data:** Petal & Co is a Schema Works demo brand built on synthetic data. Real-world subscription data will have messier distributions, missing values, and edge cases not present here.
- **No temporal validation:** The train/test split was random. A time-based split (train on earlier cohorts, test on later) would better simulate production conditions.
- **Feature coverage:** Acquisition channel, campaign source, and payment failure data were not available in `FACT_SUBSCRIPTIONS`. These would likely be strong predictors in a real subscription dataset.

### 10.2 Recommended Next Steps

- Deploy XGBoost as the production scoring model — highest CV AUC, best generalisation.
- Run SHAP on XGBoost directly (currently computed on Random Forest) — XGBoost SHAP values are faster and equally reliable.
- Build a time-based validation split to stress-test model robustness across cohorts.
- Add acquisition channel as a feature — the `cohort_month` signal likely proxies for channel mix, and directly including channel would improve both accuracy and interpretability.
- Package the risk score output as a Looker Studio dashboard layer — high-risk subscribers surfaced with their top churn driver and estimated MRR at stake. *(Pages 5 and 6 of the Petal & Co dashboard are now live.)*

---

*Schema Works Pvt. Ltd. | schemaworks.io | Built on Petal & Co demo data — not real client data*