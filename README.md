# 🌸 Petal & Co — D2C Beauty & Wellness Data Pipeline

**Schema Works Demo Project 2**

Petal & Co is a mock D2C beauty and wellness brand built as a Schema Works portfolio demo. This repo contains a fully working data pipeline — from synthetic data generation through to a live Looker Studio dashboard — built on the same stack used for real client engagements.

> **Live dashboard:** [View on Looker Studio](#) *(add link)*
> **Demo Project 1 — Ember & Co (apparel):** [github.com/siddarthreddy-k/ember-co-demo](https://github.com/siddarthreddy-k/ember-co-demo)

---

## The Data Story

Three interconnected stories are baked into the mock data mathematically:

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

---

## Project Structure

```
petal-co-demo/
├── pipeline/
│   ├── generate_mock_data.py      # Synthetic data generator
│   ├── load_to_snowflake.py       # Snowflake ingestion script
│   ├── .env.example               # Environment variable template
│   └── data/                      # Generated CSVs (gitignored)
├── petal_co/
│   ├── models/
│   │   ├── staging/
│   │   │   ├── stg_customers.sql
│   │   │   ├── stg_subscriptions.sql
│   │   │   ├── stg_orders.sql
│   │   │   └── stg_ad_spend.sql
│   │   └── marts/
│   │       ├── dim_customers.sql
│   │       ├── dim_subscriptions.sql
│   │       ├── dim_products.sql
│   │       ├── dim_dates.sql
│   │       ├── fct_orders.sql
│   │       ├── fct_subscriptions.sql
│   │       ├── fct_ad_spend.sql
│   │       ├── mart_subscription_ltv.sql
│   │       ├── mart_revenue.sql
│   │       └── mart_cac.sql
│   ├── macros/
│   │   └── generate_schema_name.sql
│   ├── dbt_project.yml
│   └── packages.yml
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

---

## GDPR Notes

This pipeline implements **Privacy by Design** (GDPR Article 25):

- `EMAIL` and `FIRST_NAME` are hashed using SHA-256 in `stg_customers.sql`
- Hashed fields (`EMAIL_HASH`, `FIRST_NAME_HASH`) flow through to `dim_customers`
- Raw PII fields are never referenced in any mart model or dashboard
- The Snowflake `RAW` schema containing raw PII should be access-controlled in production — only the dbt service account needs read access
- All downstream consumers (BI tools, data analysts) query only the MARTS schema

---

## About Schema Works

Schema Works builds data infrastructure for D2C and e-commerce brands — Shopify pipelines, Snowflake warehouses, dbt transformation layers, and CAC dashboards.

**Free 30-minute Data Audit:** [calendly.com/siddarth-reddy-schemaworks/schema-works-free-30-min-data-audit](https://calendly.com/siddarth-reddy-schemaworks/schema-works-free-30-min-data-audit)

**LinkedIn:** [linkedin.com/in/siddarth-schemaworks](https://linkedin.com/in/siddarth-schemaworks)