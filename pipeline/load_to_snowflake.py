"""
Petal & Co — Snowflake Ingestion Script
Schema Works Demo Project 2

Loads all four mock CSVs into Snowflake RAW schema.

Usage:
  1. Set environment variables (copy .env.example to .env and fill in values)
  2. On Windows, run:
       set SNOWFLAKE_ACCOUNT=QYFPUER-MJ41274
       set SNOWFLAKE_USER=SIDDARTHSCHEMAWORKS
       set SNOWFLAKE_PASSWORD=your_password
       set SNOWFLAKE_WAREHOUSE=COMPUTE_WH
  3. Then run:
       python pipeline/load_to_snowflake.py
"""

import os
import csv
import sys
from dotenv import load_dotenv
import snowflake.connector
from pathlib import Path

load_dotenv()

# ── Config from environment variables ─────────────────────────────────────────

SNOWFLAKE_ACCOUNT   = os.environ.get("SNOWFLAKE_ACCOUNT")
SNOWFLAKE_USER      = os.environ.get("SNOWFLAKE_USER")
SNOWFLAKE_PASSWORD  = os.environ.get("SNOWFLAKE_PASSWORD")
SNOWFLAKE_WAREHOUSE = os.environ.get("SNOWFLAKE_WAREHOUSE")
SNOWFLAKE_DATABASE  = "PETAL_CO_DW"
SNOWFLAKE_ROLE      = "SYSADMIN"

DATA_DIR = Path("./data")

# ── Validate environment variables ───────────────────────────────────────────

def validate_env():
    missing = []
    for var in ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_WAREHOUSE"]:
        if not os.environ.get(var):
            missing.append(var)
    if missing:
        print("\n✗ Missing environment variables:")
        for var in missing:
            print(f"  - {var}")
        print("\nRun the following before executing this script:")
        for var in missing:
            print(f"  set {var}=your_value")
        sys.exit(1)

# ── Table definitions ─────────────────────────────────────────────────────────

TABLES = {
    "SUBSCRIPTIONS": {
        "file": "subscriptions.csv",
        "ddl": """
            CREATE TABLE IF NOT EXISTS RAW.SUBSCRIPTIONS (
                SUBSCRIPTION_ID     VARCHAR(20)   NOT NULL,
                CUSTOMER_ID         VARCHAR(20),
                PRODUCT_CATEGORY    VARCHAR(50),
                PLAN_TYPE           VARCHAR(20),
                START_DATE          DATE,
                STATUS              VARCHAR(20),
                CANCELLATION_DATE   DATE,
                LOADED_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
        """
    },
    "ORDERS": {
        "file": "orders.csv",
        "ddl": """
            CREATE TABLE IF NOT EXISTS RAW.ORDERS (
                ORDER_ID            VARCHAR(20)    NOT NULL,
                CUSTOMER_ID         VARCHAR(20),
                SUBSCRIPTION_ID     VARCHAR(20),
                ORDER_DATE          DATE,
                PRODUCT_CATEGORY    VARCHAR(50),
                COUNTRY             VARCHAR(5),
                GROSS_REVENUE       NUMBER(10, 2),
                DISCOUNT            NUMBER(10, 2),
                NET_REVENUE         NUMBER(10, 2),
                RETURNED            BOOLEAN,
                STATUS              VARCHAR(20),
                LOADED_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
        """
    },
    "CUSTOMERS": {
        "file": "customers.csv",
        "ddl": """
            CREATE TABLE IF NOT EXISTS RAW.CUSTOMERS (
                CUSTOMER_ID             VARCHAR(20)   NOT NULL,
                EMAIL                   VARCHAR(200),
                FIRST_NAME              VARCHAR(100),
                ACQUISITION_CHANNEL     VARCHAR(50),
                ACQUISITION_DATE        DATE,
                COUNTRY                 VARCHAR(5),
                CUSTOMER_TYPE           VARCHAR(20),
                EMAIL_SUBSCRIBED        BOOLEAN,
                LOADED_AT               TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
        """
    },
    "AD_SPEND": {
        "file": "ad_spend.csv",
        "ddl": """
            CREATE TABLE IF NOT EXISTS RAW.AD_SPEND (
                DATE                    DATE,
                CHANNEL                 VARCHAR(50),
                SPEND_GBP               NUMBER(10, 2),
                IMPRESSIONS             INTEGER,
                CLICKS                  INTEGER,
                LOADED_AT               TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP()
            )
        """
    },
    "FULFILMENT": {
        "file": "fulfilment.csv",
        "ddl": """
            CREATE TABLE IF NOT EXISTS RAW.FULFILMENT (
                ORDER_ID                VARCHAR(20),
                SHIPPED_AT              DATE,
                DELIVERED_AT            DATE,
                RETURN_REQUESTED_AT     DATE,
                RETURN_COMPLETED_AT     DATE,
                FULFILMENT_STATUS       VARCHAR(20),
                LOADED_AT               TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP()
            )
        """
    }
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_connection():
    return snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT,
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        warehouse=SNOWFLAKE_WAREHOUSE,
        role=SNOWFLAKE_ROLE,
    )


def setup_database(cursor):
    print("\n[Setup] Creating database and schemas...")
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {SNOWFLAKE_DATABASE}")
    cursor.execute(f"USE DATABASE {SNOWFLAKE_DATABASE}")
    cursor.execute("CREATE SCHEMA IF NOT EXISTS RAW")
    cursor.execute("CREATE SCHEMA IF NOT EXISTS STAGING")
    cursor.execute("CREATE SCHEMA IF NOT EXISTS MARTS")
    cursor.execute(f"USE WAREHOUSE {SNOWFLAKE_WAREHOUSE}")
    print(f"Database {SNOWFLAKE_DATABASE} ready")
    print("Schemas RAW, STAGING, MARTS ready")


def load_table(cursor, table_name: str, config: dict):
    filepath = DATA_DIR / config["file"]

    if not filepath.exists():
        print(f"File not found: {filepath} — skipping {table_name}")
        return

    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"No rows in {filepath} — skipping {table_name}")
        return

    cursor.execute("USE SCHEMA RAW")
    cursor.execute(config["ddl"])
    cursor.execute(f"TRUNCATE TABLE IF EXISTS RAW.{table_name}")

    columns = [k.upper() for k in rows[0].keys()]
    placeholders = ", ".join(["%s"] * len(columns))
    col_list = ", ".join(columns)
    insert_sql = f"INSERT INTO RAW.{table_name} ({col_list}) VALUES ({placeholders})"

    def clean(val):
        if val == "" or val == "None":
            return None
        if val in ("True", "False"):
            return val == "True"
        return val

    data = [tuple(clean(v) for v in row.values()) for row in rows]

    chunk_size = 1000
    total = len(data)
    for i in range(0, total, chunk_size):
        chunk = data[i:i + chunk_size]
        cursor.executemany(insert_sql, chunk)

    print(f"RAW.{table_name} — {total:,} rows loaded")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\nPetal & Co — Snowflake Ingestion")
    print("=" * 45)

    validate_env()

    print("\nConnecting to Snowflake...")
    try:
        conn = get_connection()
        cursor = conn.cursor()
        print("Connected successfully")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    try:
        setup_database(cursor)

        print("\n[Loading tables into RAW schema...]")
        for table_name, config in TABLES.items():
            load_table(cursor, table_name, config)

        conn.commit()

        print("\nAll tables loaded into PETAL_CO_DW.RAW")
        print("\nNext step: Run dbt models")
        print("  dbt run --profiles-dir .\n")

    except Exception as e:
        print(f"\n Error during load: {e}")
        conn.rollback()

    finally:
        cursor.close()
        conn.close()
        print("Connection closed.")


if __name__ == "__main__":
    main()