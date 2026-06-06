"""
Petal & Co — Mock Data Generator
Schema Works Demo Project 2
Generates 12 months of realistic D2C beauty & wellness data

Tables generated:
- customers.csv
- subscriptions.csv
- orders.csv
- ad_spend.csv
- fulfilment.csv

Story baked in:
- Subscription customers: 3-4x LTV vs one-time buyers
- Meta acquires mostly one-time buyers — low LTV despite high spend
- Email and organic acquire mostly subscribers — highest LTV
- GDPR: email and first_name hashed at staging layer (SHA-256)

Run: python generate_mock_data.py
Output: ./data/ folder
"""

import csv
import os
import random
from datetime import datetime, timedelta
from collections import defaultdict

# ── Seed for reproducibility
random.seed(99)

# ── Config
START_DATE = datetime(2024, 1, 1)
END_DATE   = datetime(2024, 12, 31)

CHANNELS      = ["meta", "google", "tiktok", "organic", "email", "referral"]
PAID_CHANNELS = ["meta", "google", "tiktok"]

COUNTRIES      = ["GB", "US", "DE", "FR", "AU", "NL", "CA"]
COUNTRY_WEIGHTS = [0.40, 0.28, 0.10, 0.08, 0.06, 0.05, 0.03]

# Product categories and base AOV (GBP)
PRODUCT_CATEGORIES = ["skincare", "supplements", "haircare", "wellness_bundle"]
CATEGORY_WEIGHTS   = [0.35, 0.30, 0.20, 0.15]

AOV = {
    "skincare":        45,
    "supplements":     35,
    "haircare":        40,
    "wellness_bundle": 75,
}

# Return rates — subscriptions have very low return rates
RETURN_RATES = {
    "subscription": 0.05,
    "one_time":     0.18,
}

# Subscription mix by channel
# Meta drives mostly one-time buyers — low LTV despite high CAC
# Email and organic drive mostly subscribers — highest LTV
SUBSCRIPTION_RATES = {
    "meta":     0.25,   # 25% of Meta customers subscribe
    "google":   0.45,   # 45% of Google customers subscribe
    "tiktok":   0.20,   # 20% of TikTok customers subscribe
    "organic":  0.65,   # 65% of organic customers subscribe
    "email":    0.70,   # 70% of email customers subscribe
    "referral": 0.55,   # 55% of referral customers subscribe
}

# Target CAC in January (GBP)
BASE_CAC = {
    "meta":   72.0,
    "google": 58.0,
    "tiktok": 65.0,
}

# Monthly CAC inflation
CAC_INFLATION = {
    "meta":   0.038,
    "google": 0.008,
    "tiktok": 0.018,
}

# Subscription plan weights
PLAN_WEIGHTS = {
    "monthly":   0.65,
    "quarterly": 0.35,
}

# Churn rates per month (probability of cancelling in any given month)
MONTHLY_CHURN = {
    "monthly":   0.08,   # 8% churn per month
    "quarterly": 0.04,   # 4% churn per quarter
}

# First names pool (fictional)
FIRST_NAMES = [
    "Emma", "Olivia", "Ava", "Isla", "Mia", "Sophie", "Amelia", "Grace",
    "Lily", "Charlotte", "Hannah", "Zoe", "Lucy", "Ella", "Chloe",
    "James", "Oliver", "Harry", "George", "Jack", "Noah", "Liam",
    "William", "Ethan", "Mason", "Logan", "Lucas", "Henry", "Alex", "Sam"
]

OUTPUT_DIR = "./data"


# ── Common Functions

def random_date(start: datetime, end: datetime) -> datetime:
    delta = end - start
    if delta.total_seconds() <= 0:
        return start
    return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def weighted_choice(options, weights):
    r = random.random()
    cumulative = 0
    for opt, w in zip(options, weights):
        cumulative += w
        if r <= cumulative:
            return opt
    return options[-1]


def date_range(start: datetime, end: datetime):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def get_month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def get_month_end(month_dt: datetime) -> datetime:
    return (
        (month_dt.replace(day=28) + timedelta(days=4)).replace(day=1)
        - timedelta(days=1)
    )


# ── 1. Ad Spend (generated first — drives customer counts)

def generate_ad_spend() -> tuple[list[dict], dict]:
    spend_rows    = []
    monthly_spend = defaultdict(lambda: defaultdict(float))

    base_spend = {
        "meta":   280.0,
        "google": 160.0,
        "tiktok": 100.0,
    }

    for day in date_range(START_DATE, END_DATE):
        month_index = day.month - 1
        month_key   = get_month_key(day)

        for channel, base in base_spend.items():
            # Seasonal multiplier
            seasonal = 1.0
            if day.month in (11, 12):
                seasonal = 1.5
            elif day.month in (6, 7):
                seasonal = 1.15

            # Spend drift
            if channel == "meta":
                drift = 1 + (month_index * 0.035)
            elif channel == "tiktok":
                drift = 1 + (month_index * 0.020)
            else:
                drift = 1 + (month_index * 0.005)

            daily_spend = round(
                base * seasonal * drift * random.uniform(0.85, 1.15), 2
            )

            cpm_base    = {"meta": 8.0, "google": 11.0, "tiktok": 4.5}[channel]
            cpm         = cpm_base * (1 + month_index * 0.02)
            impressions = int((daily_spend / cpm) * 1000)
            ctr         = {"meta": 0.018, "google": 0.034, "tiktok": 0.022}[channel]
            ctr_adj     = ctr * (1 - month_index * 0.008)
            clicks      = int(impressions * max(ctr_adj, 0.008))

            spend_rows.append({
                "date":        day.strftime("%Y-%m-%d"),
                "channel":     channel,
                "spend_gbp":   daily_spend,
                "impressions": impressions,
                "clicks":      clicks,
            })

            monthly_spend[month_key][channel] += daily_spend

    return spend_rows, monthly_spend


# ── 2. Customers (derived from ad spend via target CAC)

def generate_customers(monthly_spend: dict) -> list[dict]:
    customers  = []
    customer_id = 1

    for month_key, channel_spend in sorted(monthly_spend.items()):
        month_dt    = datetime.strptime(month_key, "%Y-%m")
        month_index = month_dt.month - 1
        month_end   = min(get_month_end(month_dt), END_DATE - timedelta(days=1))

        # Paid channels — derived from spend / CAC
        for channel in PAID_CHANNELS:
            total_spend = channel_spend.get(channel, 0)
            target_cac  = BASE_CAC[channel] * (
                (1 + CAC_INFLATION[channel]) ** month_index
            )
            n_customers = max(
                1, int(total_spend / target_cac * random.uniform(0.92, 1.08))
            )

            for _ in range(n_customers):
                cust_id      = f"CUST{customer_id:05d}"
                acq_date     = random_date(month_dt, month_end)
                country      = weighted_choice(COUNTRIES, COUNTRY_WEIGHTS)
                is_subscriber = random.random() < SUBSCRIPTION_RATES[channel]
                first_name   = random.choice(FIRST_NAMES)
                email        = f"{first_name.lower()}.{cust_id.lower()}@example.com"

                customers.append({
                    "customer_id":         cust_id,
                    "email":               email,
                    "first_name":          first_name,
                    "acquisition_channel": channel,
                    "acquisition_date":    acq_date.strftime("%Y-%m-%d"),
                    "country":             country,
                    "customer_type":       "subscription" if is_subscriber else "one_time",
                    "email_subscribed":    random.choice([True, True, True, False]),
                })
                customer_id += 1

        # Organic, email, referral — proportional to paid volume
        total_paid = sum(
            1 for c in customers
            if datetime.strptime(c["acquisition_date"], "%Y-%m-%d").strftime("%Y-%m") == month_key
            and c["acquisition_channel"] in PAID_CHANNELS
        )

        organic_n  = max(1, int(total_paid * random.uniform(0.22, 0.32)))
        email_n    = max(1, int(total_paid * random.uniform(0.10, 0.16)))
        referral_n = max(1, int(total_paid * random.uniform(0.04, 0.07)))

        for channel, n in [
            ("organic",  organic_n),
            ("email",    email_n),
            ("referral", referral_n),
        ]:
            for _ in range(n):
                cust_id       = f"CUST{customer_id:05d}"
                acq_date      = random_date(month_dt, month_end)
                country       = weighted_choice(COUNTRIES, COUNTRY_WEIGHTS)
                is_subscriber = random.random() < SUBSCRIPTION_RATES[channel]
                first_name    = random.choice(FIRST_NAMES)
                email         = f"{first_name.lower()}.{cust_id.lower()}@example.com"

                customers.append({
                    "customer_id":         cust_id,
                    "email":               email,
                    "first_name":          first_name,
                    "acquisition_channel": channel,
                    "acquisition_date":    acq_date.strftime("%Y-%m-%d"),
                    "country":             country,
                    "customer_type":       "subscription" if is_subscriber else "one_time",
                    "email_subscribed":    random.choice([True, True, True, False]),
                })
                customer_id += 1

    return customers


# ── 3. Subscriptions (one per subscription customer)

def generate_subscriptions(customers: list[dict]) -> tuple[list[dict], dict]:
    subscriptions     = []
    sub_by_customer   = {}
    subscription_id   = 1

    for customer in customers:
        if customer["customer_type"] != "subscription":
            continue

        cust_id   = customer["customer_id"]
        acq_date  = datetime.strptime(customer["acquisition_date"], "%Y-%m-%d")
        category  = weighted_choice(PRODUCT_CATEGORIES, CATEGORY_WEIGHTS)
        plan      = weighted_choice(
            ["monthly", "quarterly"],
            [PLAN_WEIGHTS["monthly"], PLAN_WEIGHTS["quarterly"]]
        )

        # Simulate churn
        status           = "active"
        cancellation_date = None
        current_date     = acq_date
        churn_rate       = MONTHLY_CHURN[plan]
        check_interval   = 30 if plan == "monthly" else 90

        while current_date < END_DATE:
            current_date += timedelta(days=check_interval)
            if current_date >= END_DATE:
                break
            if random.random() < churn_rate:
                status            = "cancelled"
                cancellation_date = current_date
                break

        sub_id = f"SUB{subscription_id:05d}"

        subscriptions.append({
            "subscription_id":   sub_id,
            "customer_id":       cust_id,
            "product_category":  category,
            "plan_type":         plan,
            "start_date":        acq_date.strftime("%Y-%m-%d"),
            "status":            status,
            "cancellation_date": cancellation_date.strftime("%Y-%m-%d") if cancellation_date else None,
        })

        sub_by_customer[cust_id] = {
            "subscription_id":  sub_id,
            "category":         category,
            "plan":             plan,
            "start_date":       acq_date,
            "end_date":         cancellation_date if cancellation_date else END_DATE,
        }

        subscription_id += 1

    return subscriptions, sub_by_customer


# ── 4. Orders (derived from customers + subscriptions)

def generate_orders(
    customers: list[dict],
    sub_by_customer: dict
) -> list[dict]:
    orders   = []
    order_id = 1

    for customer in customers:
        cust_id      = customer["customer_id"]
        acq_date     = datetime.strptime(customer["acquisition_date"], "%Y-%m-%d")
        cust_type    = customer["customer_type"]
        acq_channel  = customer["acquisition_channel"]

        if cust_type == "subscription" and cust_id in sub_by_customer:
            sub       = sub_by_customer[cust_id]
            category  = sub["category"]
            plan      = sub["plan"]
            sub_id    = sub["subscription_id"]
            end_date  = sub["end_date"]
            interval  = 30 if plan == "monthly" else 90

            # Generate recurring orders throughout subscription lifetime
            order_date = acq_date
            while order_date <= min(end_date, END_DATE):
                revenue     = round(AOV[category] * random.uniform(0.90, 1.10), 2)
                is_returned = random.random() < RETURN_RATES["subscription"]
                discount    = 0.0

                # Subscribers get loyalty discount after 3rd order
                order_count = (order_date - acq_date).days // interval
                if order_count >= 3 and random.random() < 0.30:
                    discount = round(revenue * random.uniform(0.05, 0.15), 2)

                net_revenue = round(
                    revenue - discount - (revenue * 0.85 if is_returned else 0), 2
                )

                orders.append({
                    "order_id":       f"ORD{order_id:06d}",
                    "customer_id":    cust_id,
                    "subscription_id": sub_id,
                    "order_date":     order_date.strftime("%Y-%m-%d"),
                    "product_category": category,
                    "country":        customer["country"],
                    "gross_revenue":  revenue,
                    "discount":       discount,
                    "net_revenue":    net_revenue,
                    "returned":       is_returned,
                    "status":         "returned" if is_returned else "completed",
                })
                order_id += 1

                # Next order date
                next_date = order_date + timedelta(days=interval)
                if next_date > END_DATE:
                    break
                order_date = next_date

        else:
            # One-time buyer — first order always, 25% chance of second
            category = weighted_choice(PRODUCT_CATEGORIES, CATEGORY_WEIGHTS)
            n_orders = random.choices([1, 2], weights=[0.75, 0.25])[0]

            for order_num in range(n_orders):
                if order_num == 0:
                    max_first = min(acq_date + timedelta(days=14), END_DATE)
                    order_date = random_date(acq_date, max_first) if max_first > acq_date else acq_date
                else:
                    repeat_start = acq_date + timedelta(days=30)
                    if repeat_start >= END_DATE:
                        break
                    order_date = random_date(repeat_start, END_DATE)

                revenue     = round(AOV[category] * random.uniform(0.80, 1.30), 2)
                is_returned = random.random() < RETURN_RATES["one_time"]

                # One-time buyers on Meta and TikTok get heavier discounts
                discount = 0.0
                if acq_channel in ("meta", "tiktok") and random.random() < 0.40:
                    discount = round(revenue * random.uniform(0.10, 0.25), 2)

                net_revenue = round(
                    revenue - discount - (revenue * 0.85 if is_returned else 0), 2
                )

                orders.append({
                    "order_id":         f"ORD{order_id:06d}",
                    "customer_id":      cust_id,
                    "subscription_id":  None,
                    "order_date":       order_date.strftime("%Y-%m-%d"),
                    "product_category": category,
                    "country":          customer["country"],
                    "gross_revenue":    revenue,
                    "discount":         discount,
                    "net_revenue":      net_revenue,
                    "returned":         is_returned,
                    "status":           "returned" if is_returned else "completed",
                })
                order_id += 1

    return orders


# ── 5. Fulfilment

def generate_fulfilment(orders: list[dict]) -> list[dict]:
    fulfilment_rows = []

    for order in orders:
        order_date   = datetime.strptime(order["order_date"], "%Y-%m-%d")
        shipped_at   = order_date + timedelta(days=random.randint(1, 3))
        delivered_at = shipped_at + timedelta(days=random.randint(2, 6))

        return_requested_at = None
        return_completed_at = None

        if order["returned"]:
            return_requested_at = delivered_at + timedelta(days=random.randint(3, 21))
            return_completed_at = return_requested_at + timedelta(days=random.randint(5, 14))

        fulfilment_rows.append({
            "order_id":            order["order_id"],
            "shipped_at":          shipped_at.strftime("%Y-%m-%d"),
            "delivered_at":        delivered_at.strftime("%Y-%m-%d"),
            "return_requested_at": return_requested_at.strftime("%Y-%m-%d") if return_requested_at else None,
            "return_completed_at": return_completed_at.strftime("%Y-%m-%d") if return_completed_at else None,
            "fulfilment_status":   "returned" if order["returned"] else "delivered",
        })

    return fulfilment_rows


# ── Write CSVs

def write_csv(filename: str, rows: list[dict]):
    if not rows:
        print(f"  ⚠ No data for {filename}")
        return
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ {filename} — {len(rows):,} rows written to {filepath}")


# ── Main

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("\n🌸 Petal & Co — Mock Data Generator")
    print("=" * 45)

    print("\n[1/5] Generating ad spend...")
    ad_spend, monthly_spend = generate_ad_spend()
    write_csv("ad_spend.csv", ad_spend)

    print("\n[2/5] Generating customers from spend + target CAC...")
    customers = generate_customers(monthly_spend)
    write_csv("customers.csv", customers)

    print("\n[3/5] Generating subscriptions...")
    subscriptions, sub_by_customer = generate_subscriptions(customers)
    write_csv("subscriptions.csv", subscriptions)

    print("\n[4/5] Generating orders...")
    orders = generate_orders(customers, sub_by_customer)
    write_csv("orders.csv", orders)

    print("\n[5/5] Generating fulfilment records...")
    fulfilment = generate_fulfilment(orders)
    write_csv("fulfilment.csv", fulfilment)

    # Summary stats
    sub_customers  = sum(1 for c in customers if c["customer_type"] == "subscription")
    one_time_custs = sum(1 for c in customers if c["customer_type"] == "one_time")
    sub_orders     = sum(1 for o in orders if o["subscription_id"] is not None)
    one_time_orders = sum(1 for o in orders if o["subscription_id"] is None)

    print("\n✅ All done. Files saved to ./data/")
    print("\nKey story in the data:")
    print(f"  • Total customers: {len(customers):,} ({sub_customers:,} subscribers, {one_time_custs:,} one-time)")
    print(f"  • Total orders: {len(orders):,} ({sub_orders:,} subscription, {one_time_orders:,} one-time)")
    print(f"  • Total subscriptions: {len(subscriptions):,}")
    print("  • Subscription customers: 3-4x LTV vs one-time buyers")
    print("  • Meta: lowest subscriber rate (25%) → lowest LTV channel")
    print("  • Email/organic: highest subscriber rate (65-70%) → highest LTV")
    print("  • GDPR: email + first_name hashed at dbt staging layer")
    print("\nNext step: Load CSVs into Snowflake RAW schema.\n")


if __name__ == "__main__":
    main()