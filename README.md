# 🌸 Petal & Co — D2C Beauty & Wellness Data Pipeline

**Schema Works Demo Project 2**

Petal & Co is a mock D2C beauty and wellness brand built as a Schema Works portfolio demo. This repo contains a fully working data pipeline — from synthetic data generation through to a live Looker Studio dashboard — built on the same stack used for real client engagements.

> **Live dashboard:** [View on Looker Studio](https://datastudio.google.com/s/noNS3VpwPDo)
> **Demo Project 1 — Ember & Co (apparel):** [github.com/siddarthreddy-k/ember-co-demo](https://github.com/siddarthreddy-k/ember-co-demo)

---

## The Data Story

Four interconnected stories are baked into the mock data mathematically:

### 1. Subscription vs One-Time LTV
Subscription customers generate **3-4x more revenue** over 12 months than one-time buyers. The dashboard surfaces this by cohort and channel — showing exactly which acquisition channels drive high-value subscribers vs low-value one-time purchasers.

| Customer Type | Avg Orders / Year | Return Rate | 12-Month LTV |
|---|---|---|---|
| Subscription | 8-12 | ~5% | £350-450 |
| One-time | 1-2 | ~18% | £65-90 |

### 2. Channel Subscriber Rate — The Hidden CAC Story
Not all CAC is equal. Meta acquires customers cheaply on a per-click basis — but only 25% of them subscribe. Email and organic acquire mostly subscribers (65-70%). The real cost of acquiring a subscriber from Meta is 3x higher than it appears.

| Channel | Subscriber Rate | Subscriber CAC |
|---|---|---|
| Meta | 25% | High |
| Google | 45% | Medium |
| TikTok | 20% | Highest |
| Organic | 65% | Low |
| Email | 70% | Lowest |

### 3. GDPR-Compliant PII Handling
Customer emails and first names are hashed using **SHA-256 at the dbt staging layer**. Raw PII never reaches the mart layer or Looker Studio dashboard. Compliant with **GDPR Article 25 — Privacy by Design**.

```sql
-- stg_customers.sql
SHA2(LOWER(TRIM(EMAIL)), 256)       AS EMAIL_HASH,
SHA2(LOWER(TRIM(FIRST_NAME)), 256)  AS FIRST_NAME_HASH
```

### 4. Churn Prediction — ML Model
Monthly subscribers churn at **31%** vs **6%** for quarterly subscribers. A machine learning model (XGBoost, AUC 0.933) scores all 1,911 subscribers with churn probabilities, risk bands, and per-subscriber SHAP explanations — surfaced in Pages 5 and 6 of the Looker Studio dashboard.

| Plan type | Churn rate | Key driver |
|---|---|---|
| Monthly | 31% | Plan structure + acquisition timing |
| Quarterly | 6% | Lower churn cohort, longer commitment |

---

## Stack

```
Python → Snowflake → dbt → Looker Studio
```

| Layer | Tool | Detail |
|---|---|---|
| Data generation | Python 3.11 | Synthetic mock data with story baked in mathematically |
| Data warehouse | Snowflake | GCP Iowa, X-Small warehouse |
| Transformation | dbt Core | Kimball star schema — staging → dims → facts → marts |
| ML model | Python · scikit-learn · XGBoost · SHAP | Churn prediction — scores written back to Snowflake ML schema |
| Visualisation | Looker Studio | Connected via Snowflake community connector |

---

## Data Model

### Source tables (RAW schema)
| Table | Rows | Description |
|---|---|---|
| `customers` | ~4,600 | One row per customer — includes hashed PII fields |
| `subscriptions` | ~1,900 | One row per subscription with plan type and churn date |
| `orders` | ~11,000 | One row per order — subscription and one-time orders |
| `ad_spend` | 1,098 | Daily spend by channel — meta, google, tiktok |
| `fulfilment` | ~11,000 | One row per order — shipping and return dates |

### Staging models (STAGING schema)
| Model | Description |
|---|---|
| `stg_customers` | Clean + cast + SHA-256 hash on email and first_name |
| `stg_subscriptions` | Clean + cast + lifetime days + churn flag |
| `stg_orders` | Clean + cast + joins to stg_customers for channel and customer_type |
| `stg_ad_spend` | Clean + cast + CTR, CPM, CPC calculations |

### Dimensional layer (MARTS schema)
| Model | Description |
|---|---|
| `dim_customers` | Customer attributes — hashed PII, channel, region, subscriber flag |
| `dim_subscriptions` | Subscription attributes — plan, lifetime, churn status |
| `dim_products` | Static product category reference — AOV, division |
| `dim_dates` | Full 2024 date spine — week, month, quarter labels |

### Fact layer (MARTS schema)
| Model | Description |
|---|---|
| `fct_orders` | One row per order — revenue measures, joins to all dims at query time |
| `fct_subscriptions` | One row per subscription — lifetime revenue, MRR estimate, churn |
| `fct_ad_spend` | One row per channel per day — spend, impressions, clicks, efficiency metrics |

### Mart layer (MARTS schema — pre-aggregated for Looker Studio)
| Model | Description |
|---|---|
| `mart_subscription_ltv` | LTV at 30/90/180/365 days by cohort, channel, and customer type |
| `mart_revenue` | Weekly gross vs net revenue by channel and customer type |
| `mart_cac` | Monthly CAC by channel + subscriber rate + subscriber CAC |

### ML layer (ML schema — churn model outputs)
| Table | Rows | Description |
|---|---|---|
| `ML_CHURN_RISK_SCORES` | 1,911 | Per-subscriber churn probability (XGBoost), risk band (1/2/3), top SHAP driver |
| `ML_CHURN_SUMMARY` | 1 | C-suite scorecard — MRR-weighted overall risk band, high/medium/low counts (active only) |
| `ML_CHURN_SHAP_IMPORTANCE` | 13 | Feature importance via SHAP TreeExplainer — mean \|SHAP\| per feature with readable labels |
| `ML_CHURN_INSIGHTS` | 11 | Dynamic key-value store — pre-computed insight values for Looker Studio scorecards |

> All ML tables use `TRUNCATE + INSERT` on each model run — `SCORED_AT` timestamp indicates when the model last ran.

---

## Churn Prediction Model

Full model details and decisions are documented in [`docs/churn_model_decisions.md`](docs/churn_model_decisions.md).

### Model summary
- **Source:** `PETAL_CO_DW.MARTS.FACT_SUBSCRIPTIONS` (1,911 rows)
- **Target:** `IS_CHURNED` (boolean, pre-defined in dbt mart)
- **Features:** 13 (after removing 14 columns for leakage or collinearity)
- **Best model:** XGBoost — Test AUC 0.933, CV AUC 0.925 ± 0.017
- **Script:** `models/ml_models/churn_prediction_model.py`
- **Outputs:** `pipeline/data/ml_output/` (PNG charts + CSV risk scores)

### Leakage discovery
Three rounds of data leakage were identified and removed before the model produced a trustworthy result (AUC dropped from 1.000 to 0.927):

| Round | Features removed | Reason |
|---|---|---|
| 1 | `CANCELLATION_DATE`, `IS_ACTIVE`, `STATUS` | Post-churn status fields — only populated after cancellation |
| 2 | `LIFETIME_DAYS`, `ORDERS_PER_MONTH`, `REVENUE_PER_DAY` | `LIFETIME_DAYS = cancellation_date − start_date` for churned subscribers |
| 3 | `ESTIMATED_MRR` | dbt sets to 0 when `IS_ACTIVE = False` — direct churn proxy |

### Key findings (SHAP)
- `cohort_month` is the strongest predictor — subscribers acquired in Q1/Q2 churn at nearly double the rate of Q3/Q4 cohorts
- `order_interval_days` is second — monthly subscribers churn 5× more than quarterly (31% vs 6%)
- Return features (`return_rate`, `return_ratio`, `total_returns`) have near-zero SHAP values — **returns do not predict churn**

### Running the model
```bash
pip install scikit-learn xgboost shap snowflake-connector-python python-dotenv matplotlib seaborn
python models/ml_models/churn_prediction_model.py
```

---

## Dashboard Pages

### Page 1 — Revenue Overview
- Gross vs net revenue by channel and week
- Return rate by channel (subscription vs one-time)
- Subscription revenue as % of total revenue over time
- Product category revenue breakdown

### Page 2 — CAC & Subscriber Rate
- CAC by channel — month on month trend
- Subscriber rate by channel — % of new customers who subscribe
- Subscriber CAC — true cost of acquiring a subscriber per channel
- Total spend by channel

### Page 3 — Subscription LTV Cohorts
- LTV at 30, 90, 180, 365 days by cohort month
- Subscription vs one-time side by side
- Channel comparison — which channels drive highest LTV subscribers
- Churn rate by plan type (monthly vs quarterly)

### Page 4 — Subscription Tracking
- MRR trend over time
- Active vs churned subscribers by cohort
- Churn rate by plan type and product category

### Page 5 — Churn Risk Intelligence *(ML)*
Connected to `ML_CHURN_RISK_SCORES` and `ML_CHURN_SUMMARY`
- Overall risk band gauge (MRR-weighted — 1.610 Medium as of last run)
- Scorecards: active subscribers, high/medium risk counts, MRR at stake
- Donut chart: risk band distribution (Low / Medium / High)
- Bar charts: churn rate by plan type and product category
- Table: top 10 highest-risk active subscribers with churn probability, risk band, and top driver

### Page 6 — What Drives Churn *(ML + SHAP)*
Connected to `ML_CHURN_SHAP_IMPORTANCE`, `ML_CHURN_INSIGHTS`, `ML_CHURN_RISK_SCORES`
- Scorecards: plan churn multiplier (5.2×), highest-risk cohort (Q1), returns SHAP rank (13th of 13)
- SHAP bar chart: mean |SHAP| per feature — acquisition month and order interval dominate
- Key findings table: dynamic insights from `ML_CHURN_INSIGHTS` — fully updates on model re-run
- Cohort churn bar chart: churn rate by acquisition quarter

---

## Project Structure

```
petal-co-demo/
├── pipeline/
│   ├── generate_mock_data.py          # Synthetic data generator
│   ├── load_to_snowflake.py           # Snowflake ingestion script
│   ├── .env.example                   # Environment variable template
│   └── data/
│       └── ml_output/                 # ML model outputs (gitignored)
│           ├── churn_eda_distributions.png
│           ├── churn_baseline_evaluation.png
│           ├── churn_feature_importance.png
│           ├── churn_rf_feature_importance.png
│           ├── churn_model_comparison.png
│           ├── churn_shap_summary.png
│           ├── churn_shap_bar.png
│           ├── churn_risk_scores.csv
│           └── churn_risk_scores_v2.csv
├── models/
│   ├── staging/
│   │   ├── stg_customers.sql
│   │   ├── stg_subscriptions.sql
│   │   ├── stg_orders.sql
│   │   └── stg_ad_spend.sql
│   ├── marts/
│   │   ├── facts/
│   │   │   ├── fct_orders.sql
│   │   │   ├── fct_subscriptions.sql
│   │   │   └── fct_ad_spend.sql
│   │   ├── dimensions/
│   │   │   ├── dim_customers.sql
│   │   │   ├── dim_subscriptions.sql
│   │   │   ├── dim_products.sql
│   │   │   └── dim_dates.sql
│   │   └── aggregates/
│   │       ├── mart_subscription_ltv.sql
│   │       ├── mart_revenue.sql
│   │       └── mart_cac.sql
│   └── ml_models/
│       └── churn_prediction_model.py  # Day 1 + Day 2 — full ML pipeline
├── docs/
│   └── churn_model_decisions.md       # Feature engineering + model decisions log
├── macros/
│   └── generate_schema_name.sql
├── dbt_project.yml
├── packages.yml
├── profiles.yml
└── README.md
```

---

## Setup

### Prerequisites
- Python 3.9+
- Snowflake account
- dbt Core (`pip install dbt-snowflake`)

### 1. Clone the repo
```bash
git clone https://github.com/siddarthreddy-k/petal-co-demo.git
cd petal-co-demo
```

### 2. Set up environment variables
```bash
cp pipeline/.env.example pipeline/.env
```

Fill in your Snowflake credentials in `.env`:
```
SNOWFLAKE_ACCOUNT=your_account
SNOWFLAKE_USER=your_user
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_WAREHOUSE=your_warehouse
```

### 3. Generate mock data
```bash
cd pipeline
pip install -r requirements.txt
python generate_mock_data.py
```

### 4. Load to Snowflake
```bash
python load_to_snowflake.py
```

### 5. Run dbt models
```bash
cd ../petal_co
dbt deps
dbt run
dbt test
```

### 6. Run the churn prediction model *(optional)*
```bash
pip install scikit-learn xgboost shap snowflake-connector-python python-dotenv matplotlib seaborn
python models/ml_models/churn_prediction_model.py
```

This will:
- Connect to Snowflake and load `FACT_SUBSCRIPTIONS`
- Train Logistic Regression, Random Forest, and XGBoost models
- Run SHAP explainability on Random Forest
- Write results to 4 tables in `PETAL_CO_DW.ML`
- Save 9 output files to `pipeline/data/ml_output/`

---

## GDPR Notes

This pipeline implements **Privacy by Design** (GDPR Article 25):

- `EMAIL` and `FIRST_NAME` are hashed using SHA-256 in `stg_customers.sql`
- Hashed fields (`EMAIL_HASH`, `FIRST_NAME_HASH`) flow through to `dim_customers`
- Raw PII fields are never referenced in any mart model or dashboard
- The Snowflake `RAW` schema containing raw PII should be access-controlled in production — only the dbt service account needs read access
- All downstream consumers (BI tools, data analysts) query only the `MARTS` and `ML` schemas
- The ML model operates on aggregate subscription metrics only — no PII fields are used as features

---

## Model Decisions

Full documentation of feature engineering choices, leakage discovery, model selection, and SHAP findings is in [`docs/churn_model_decisions.md`](docs/churn_model_decisions.md).

| Model | Test AUC | CV AUC | Notes |
|---|---|---|---|
| Logistic Regression | 0.927 | 0.914 ± 0.014 | Interpretable baseline |
| Random Forest | 0.926 | 0.907 ± 0.012 | Used for SHAP analysis |
| **XGBoost** | **0.933** | **0.925 ± 0.017** | **Production model** |

---

## About Schema Works

Schema Works builds data infrastructure for D2C and e-commerce brands — Shopify pipelines, Snowflake warehouses, dbt transformation layers, CAC dashboards, and ML-powered churn prediction.

**Free 30-minute Data Audit:** [calendly.com/siddarth-reddy-schemaworks/schema-works-free-30-min-data-audit](https://calendly.com/siddarth-reddy-schemaworks/schema-works-free-30-min-data-audit)

**LinkedIn:** [linkedin.com/in/siddarth-schemaworks](https://linkedin.com/in/siddarth-schemaworks)