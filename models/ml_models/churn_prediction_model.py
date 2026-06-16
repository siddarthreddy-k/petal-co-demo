"""
Petal & Co — Churn Prediction Model
Schema Works | CTO Skills Gap: Data & AI

Day 1: Data exploration, feature engineering, baseline logistic regression
Day 2: Random Forest, XGBoost, SHAP explainability, final risk scores + Snowflake write

Source: PETAL_CO_DW.MARTS.FACT_SUBSCRIPTIONS (Snowflake)
Target: IS_CHURNED (boolean)
Stack: Python · scikit-learn · xgboost · shap · snowflake-connector-python

Place this file at:
    petal-co-demo/models/ml_models/churn_prediction_model.py

Output folder (auto-created):
    petal-co-demo/pipeline/data/ml_output/

Run from the repo root:
    python models/ml_models/churn_prediction_model.py
"""

import os
import sys
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import snowflake.connector
from pathlib import Path
from dotenv import load_dotenv
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
    RocCurveDisplay,
)

warnings.filterwarnings("ignore")

# ── PATHS ──────────────────────────────────────────────────────────────────────
REPO_ROOT  = Path(__file__).resolve().parent.parent.parent
ENV_PATH   = REPO_ROOT / "pipeline" / ".env"
OUTPUT_DIR = REPO_ROOT / "pipeline" / "data" / "ml_output"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 60)
print("  Petal & Co — Churn Prediction Model  |  Day 1 + 2")
print("=" * 60)
print(f"Repo root : {REPO_ROOT}")
print(f".env path : {ENV_PATH}")
print(f"Output dir: {OUTPUT_DIR}")

# ── CREDENTIALS ────────────────────────────────────────────────────────────────
if not ENV_PATH.exists():
    print(f"❌ .env not found at {ENV_PATH}")
    sys.exit(1)

load_dotenv(ENV_PATH)

REQUIRED = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_WAREHOUSE"]
missing = [v for v in REQUIRED if not os.environ.get(v)]
if missing:
    print(f"❌ Missing .env variables: {missing}")
    sys.exit(1)

print(f"   Credentials loaded")
print(f"   Account  : {os.environ['SNOWFLAKE_ACCOUNT']}")
print(f"   User     : {os.environ['SNOWFLAKE_USER']}")
print(f"   Warehouse: {os.environ['SNOWFLAKE_WAREHOUSE']}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — CONNECT & LOAD FROM SNOWFLAKE
# ══════════════════════════════════════════════════════════════════════════════

def load_data() -> pd.DataFrame:
    print("\n── Step 1: Loading FACT_SUBSCRIPTIONS from Snowflake ────────────")

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database="PETAL_CO_DW",
        schema="MARTS",
        role="SYSADMIN",
    )

    query = """
        SELECT
            SUBSCRIPTION_ID, CUSTOMER_ID, PRODUCT_CATEGORY_KEY, PLAN_TYPE,
            START_DATE, START_COHORT, CANCELLATION_DATE, FIRST_ORDER_DATE,
            LAST_ORDER_DATE, STATUS, IS_ACTIVE, IS_CHURNED, LIFETIME_DAYS,
            ORDER_INTERVAL_DAYS, TOTAL_ORDERS, TOTAL_RETURNS,
            TOTAL_GROSS_REVENUE, TOTAL_NET_REVENUE, TOTAL_ADJUSTED_REVENUE,
            TOTAL_DISCOUNTS, AVG_ORDER_VALUE, RETURN_RATE, ESTIMATED_MRR
        FROM PETAL_CO_DW.MARTS.FACT_SUBSCRIPTIONS
    """

    cursor = conn.cursor()
    cursor.execute(query)
    df = cursor.fetch_pandas_all()
    cursor.close()
    conn.close()

    df.columns = df.columns.str.lower()
    print(f"   Loaded {len(df):,} rows x {df.shape[1]} columns")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — EXPLORATORY DATA ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def explore(df: pd.DataFrame) -> None:
    print("\n── Step 2: Exploratory Data Analysis ───────────────────────────")

    print(f"Shape: {df.shape}")
    null_counts = df.isnull().sum()
    if null_counts.any():
        print("Null counts:")
        print(null_counts[null_counts > 0])
    else:
        print("   No null values found")

    churn_counts = df["is_churned"].value_counts()
    churn_pct    = df["is_churned"].value_counts(normalize=True)
    print("\nIS_CHURNED distribution:")
    print(pd.DataFrame({"count": churn_counts, "pct_%": churn_pct.round(4)}))

    minority_pct = churn_pct.min()
    if minority_pct < 0.2:
        print(f"⚠️  Class imbalance ({minority_pct:.1%} minority) — using class_weight='balanced'")
    else:
        print(f"   Class balance OK ({minority_pct:.1%} minority class)")

    plan_churn = (
        df.groupby("plan_type")["is_churned"]
        .agg(["sum", "count"])
        .rename(columns={"sum": "churned", "count": "total"})
    )
    plan_churn["churn_rate_%"] = (plan_churn["churned"] / plan_churn["total"]).round(2)
    print("\nChurn rate by plan type:")
    print(plan_churn.sort_values("churn_rate_%", ascending=False))

    cat_churn = (
        df.groupby("product_category_key")["is_churned"]
        .agg(["sum", "count"])
        .rename(columns={"sum": "churned", "count": "total"})
    )
    cat_churn["churn_rate_%"] = (cat_churn["churned"] / cat_churn["total"]).round(2)
    print("\nChurn rate by product category:")
    print(cat_churn.sort_values("churn_rate_%", ascending=False))

    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    fig.suptitle("Petal & Co — Feature Distributions by Churn Status", fontsize=14)

    plot_features = [
        ("total_orders",        "Total orders"),
        ("avg_order_value",     "Avg order value (£)"),
        ("return_rate",         "Return rate"),
        ("total_net_revenue",   "Net revenue (£)"),
        ("total_discounts",     "Total discounts (£)"),
        ("order_interval_days", "Order interval (days)"),
    ]

    for ax, (col, label) in zip(axes.flatten(), plot_features):
        for churned, color, name in [
            (False, "#1D9E75", "Active"),
            (True,  "#E8593C", "Churned"),
        ]:
            subset = df[df["is_churned"] == churned][col].dropna()
            ax.hist(subset, bins=30, alpha=0.6, color=color, label=name, density=True)
        ax.set_title(label, fontsize=11)
        ax.legend(fontsize=9)

    plt.tight_layout()
    out = OUTPUT_DIR / "churn_eda_distributions.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {out.relative_to(REPO_ROOT)}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════════════════════

def engineer_features(df: pd.DataFrame):
    print("\n── Step 3: Feature Engineering ─────────────────────────────────")

    df = df.copy()

    # Dropped: post-churn leakage
    # cancellation_date   → only populated after churn
    # is_active           → inverse of is_churned
    # status              → string encoding of is_churned
    # total_gross_revenue / total_adjusted_revenue → collinear with total_net_revenue
    # first_order_date / last_order_date → post-event timestamps
    # start_date          → redundant with start_cohort
    # lifetime_days       → = cancellation_date - start_date for churned; encodes churn
    # estimated_mrr       → dbt sets to 0 when IS_ACTIVE=False; direct churn proxy
    # orders_per_month / revenue_per_day → derived from lifetime_days; inherit leakage
    LEAKAGE_COLS = [
        "cancellation_date", "is_active", "status",
        "total_adjusted_revenue", "total_gross_revenue",
        "first_order_date", "last_order_date", "start_date",
        "lifetime_days", "estimated_mrr",
    ]
    ID_COLS = ["subscription_id", "customer_id"]
    df = df.drop(columns=LEAKAGE_COLS + ID_COLS, errors="ignore")

    # Engineered features
    df["discount_rate"] = np.where(
        df["total_net_revenue"] > 0,
        df["total_discounts"] / df["total_net_revenue"], 0,
    )
    df["return_ratio"] = np.where(
        df["total_orders"] > 0,
        df["total_returns"] / df["total_orders"], 0,
    )
    df["start_cohort"]   = pd.to_datetime(df["start_cohort"])
    df["cohort_month"]   = df["start_cohort"].dt.month
    df["cohort_quarter"] = df["start_cohort"].dt.quarter
    df = df.drop(columns=["start_cohort"])

    le_plan = LabelEncoder()
    le_cat  = LabelEncoder()
    df["plan_type_enc"]   = le_plan.fit_transform(df["plan_type"].fillna("unknown"))
    df["product_cat_enc"] = le_cat.fit_transform(df["product_category_key"].fillna("unknown"))

    print("Plan type encoding :",
          dict(zip(le_plan.classes_, le_plan.transform(le_plan.classes_))))
    print("Product cat encoding:",
          dict(zip(le_cat.classes_, le_cat.transform(le_cat.classes_))))

    # Final feature set — 13 features (no post-event information)
    FEATURES = [
        "plan_type_enc", "product_cat_enc", "order_interval_days",
        "cohort_month", "cohort_quarter",
        "avg_order_value", "total_net_revenue", "total_discounts", "discount_rate",
        "total_orders", "total_returns", "return_rate", "return_ratio",
    ]

    X = df[FEATURES].fillna(0)
    y = df["is_churned"].astype(int)

    print(f"   Feature matrix: {X.shape}")
    print(f"   Target distribution: {y.value_counts().to_dict()}")
    return X, y, df, le_plan, le_cat


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — BASELINE MODEL: LOGISTIC REGRESSION
# ══════════════════════════════════════════════════════════════════════════════

def train_baseline(X: pd.DataFrame, y: pd.Series):
    print("\n── Step 4: Baseline Logistic Regression ─────────────────────────")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"Train: {X_train.shape[0]} rows | Test: {X_test.shape[0]} rows")
    print(f"Train churn rate: {y_train.mean():.1%} | Test: {y_test.mean():.1%}")

    scaler = StandardScaler()
    X_train_sc = scaler.fit_transform(X_train)
    X_test_sc  = scaler.transform(X_test)

    lr = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)
    lr.fit(X_train_sc, y_train)

    y_pred      = lr.predict(X_test_sc)
    y_pred_prob = lr.predict_proba(X_test_sc)[:, 1]

    auc = roc_auc_score(y_test, y_pred_prob)
    print(f"Test AUC-ROC: {auc:.3f}")
    print(classification_report(y_test, y_pred, target_names=["Active", "Churned"]))

    cv        = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    X_sc_full = scaler.fit_transform(X)
    cv_scores = cross_val_score(
        LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42),
        X_sc_full, y, cv=cv, scoring="roc_auc",
    )
    print(f"5-fold CV AUC: {cv_scores.mean():.3f} +/- {cv_scores.std():.3f}")
    print(f"Fold scores  : {cv_scores.round(3)}")

    return lr, scaler, X_test, y_test, y_pred, y_pred_prob


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — EVALUATION PLOTS
# ══════════════════════════════════════════════════════════════════════════════

def evaluate(lr, X: pd.DataFrame, y_test, y_pred, y_pred_prob) -> None:
    print("\n── Step 5: Evaluation ───────────────────────────────────────────")

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Baseline Logistic Regression — Petal & Co Churn Model", fontsize=13)

    cm = confusion_matrix(y_test, y_pred)
    sns.heatmap(cm, annot=True, fmt="d", cmap="Greens",
                xticklabels=["Active", "Churned"],
                yticklabels=["Active", "Churned"], ax=axes[0])
    axes[0].set_title("Confusion Matrix")
    axes[0].set_ylabel("Actual")
    axes[0].set_xlabel("Predicted")

    RocCurveDisplay.from_predictions(y_test, y_pred_prob,
        name="Logistic Regression", ax=axes[1], color="#1D9E75")
    axes[1].plot([0, 1], [0, 1], "k--", linewidth=0.8, label="Random")
    axes[1].set_title("ROC Curve")
    axes[1].legend()

    plt.tight_layout()
    out = OUTPUT_DIR / "churn_baseline_evaluation.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {out.relative_to(REPO_ROOT)}")

    coef_df = pd.DataFrame({
        "feature": X.columns,
        "coefficient": lr.coef_[0],
    }).sort_values("coefficient", ascending=False)

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ["#E8593C" if c > 0 else "#1D9E75" for c in coef_df["coefficient"]]
    ax.barh(coef_df["feature"], coef_df["coefficient"], color=colors)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title("Feature Coefficients — Logistic Regression\n"
                 "Red = increases churn risk  |  Green = decreases churn risk",
                 fontsize=12)
    ax.set_xlabel("Coefficient value")
    plt.tight_layout()
    out = OUTPUT_DIR / "churn_feature_importance.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {out.relative_to(REPO_ROOT)}")

    print("Top 5 churn risk drivers:")
    print(coef_df.head(5).to_string(index=False))
    print("Top 5 retention signals:")
    print(coef_df.tail(5).to_string(index=False))


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — CHURN RISK SCORE OUTPUT (logistic regression)
# ══════════════════════════════════════════════════════════════════════════════

def score_subscribers(lr, scaler, X: pd.DataFrame, df_raw: pd.DataFrame) -> None:
    print("\n── Step 6: Churn Risk Scores (Logistic Regression) ──────────────")

    X_sc        = scaler.transform(X)
    churn_probs = lr.predict_proba(X_sc)[:, 1]

    risk_df = df_raw[[
        "subscription_id", "customer_id", "plan_type",
        "product_category_key", "lifetime_days", "is_churned", "estimated_mrr",
    ]].copy().reset_index(drop=True)

    risk_df["churn_probability"] = churn_probs.round(4)
    risk_df["risk_band"] = pd.cut(churn_probs, bins=[0, 0.33, 0.66, 1.0],
                                  labels=["Low", "Medium", "High"])

    print("Risk band distribution:")
    print(risk_df["risk_band"].value_counts())
    high_risk_mrr = risk_df[risk_df["risk_band"] == "High"]["estimated_mrr"].sum()
    print(f"High-risk MRR at stake: £{high_risk_mrr:,.0f}")

    out = OUTPUT_DIR / "churn_risk_scores.csv"
    risk_df.to_csv(out, index=False)
    print(f"   Saved: {out.relative_to(REPO_ROOT)} | {len(risk_df):,} rows")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — RANDOM FOREST
# ══════════════════════════════════════════════════════════════════════════════

def train_random_forest(X: pd.DataFrame, y: pd.Series):
    print("\n── Step 7: Random Forest ────────────────────────────────────────")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    rf = RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=10,
                                class_weight="balanced", random_state=42, n_jobs=-1)
    rf.fit(X_train, y_train)

    y_pred      = rf.predict(X_test)
    y_pred_prob = rf.predict_proba(X_test)[:, 1]

    auc = roc_auc_score(y_test, y_pred_prob)
    print(f"Test AUC-ROC: {auc:.3f}")
    print(classification_report(y_test, y_pred, target_names=["Active", "Churned"]))

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(
        RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=10,
                               class_weight="balanced", random_state=42, n_jobs=-1),
        X, y, cv=cv, scoring="roc_auc",
    )
    print(f"5-fold CV AUC: {cv_scores.mean():.3f} +/- {cv_scores.std():.3f}")
    print(f"Fold scores  : {cv_scores.round(3)}")

    fi_df = pd.DataFrame({"feature": X.columns,
                          "importance": rf.feature_importances_}
                         ).sort_values("importance", ascending=False)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(fi_df["feature"], fi_df["importance"], color="#1D9E75")
    ax.set_title("Random Forest — Feature Importance (Gini)", fontsize=12)
    ax.set_xlabel("Mean decrease in impurity")
    ax.invert_yaxis()
    plt.tight_layout()
    out = OUTPUT_DIR / "churn_rf_feature_importance.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {out.relative_to(REPO_ROOT)}")

    return rf, y_test, y_pred_prob


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — XGBOOST
# ══════════════════════════════════════════════════════════════════════════════

def train_xgboost(X: pd.DataFrame, y: pd.Series):
    print("\n── Step 8: XGBoost ──────────────────────────────────────────────")

    try:
        from xgboost import XGBClassifier
    except ImportError:
        print("⚠️  XGBoost not installed. Run: pip install xgboost")
        return None, None, None

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    scale_pos_weight = (y == 0).sum() / (y == 1).sum()

    xgb = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                        subsample=0.8, colsample_bytree=0.8,
                        scale_pos_weight=scale_pos_weight,
                        random_state=42, eval_metric="auc", verbosity=0)
    xgb.fit(X_train, y_train)

    y_pred      = xgb.predict(X_test)
    y_pred_prob = xgb.predict_proba(X_test)[:, 1]

    auc = roc_auc_score(y_test, y_pred_prob)
    print(f"Test AUC-ROC: {auc:.3f}")
    print(classification_report(y_test, y_pred, target_names=["Active", "Churned"]))

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(
        XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05,
                      subsample=0.8, colsample_bytree=0.8,
                      scale_pos_weight=scale_pos_weight,
                      random_state=42, eval_metric="auc", verbosity=0),
        X, y, cv=cv, scoring="roc_auc",
    )
    print(f"5-fold CV AUC: {cv_scores.mean():.3f} +/- {cv_scores.std():.3f}")
    print(f"Fold scores  : {cv_scores.round(3)}")

    return xgb, y_test, y_pred_prob


# ══════════════════════════════════════════════════════════════════════════════
# STEP 9 — MODEL COMPARISON
# ══════════════════════════════════════════════════════════════════════════════

def compare_models(X: pd.DataFrame, y: pd.Series, lr, scaler, rf, xgb) -> None:
    print("\n── Step 9: Model Comparison ─────────────────────────────────────")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    X_test_sc = scaler.transform(X_test)

    fig, ax = plt.subplots(figsize=(10, 6))
    models = [
        (lr,  X_test_sc, "Logistic Regression", "#534AB7"),
        (rf,  X_test,    "Random Forest",        "#1D9E75"),
    ]
    if xgb is not None:
        models.append((xgb, X_test, "XGBoost", "#E8593C"))

    for model, X_eval, name, color in models:
        prob = model.predict_proba(X_eval)[:, 1]
        auc  = roc_auc_score(y_test, prob)
        RocCurveDisplay.from_predictions(y_test, prob,
            name=f"{name} (AUC={auc:.3f})", ax=ax, color=color)
        print(f"  {name:<25} AUC = {auc:.3f}")

    ax.plot([0, 1], [0, 1], "k--", linewidth=0.8, label="Random")
    ax.set_title("Model Comparison — ROC Curves\nPetal & Co Churn Model", fontsize=13)
    ax.legend(fontsize=10)
    plt.tight_layout()
    out = OUTPUT_DIR / "churn_model_comparison.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {out.relative_to(REPO_ROOT)}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 10 — SHAP EXPLAINABILITY
# ══════════════════════════════════════════════════════════════════════════════

def shap_analysis(rf, X: pd.DataFrame):
    print("\n── Step 10: SHAP Explainability ─────────────────────────────────")

    try:
        import shap
    except ImportError:
        print("⚠️  SHAP not installed. Run: pip install shap")
        return None

    print("Computing SHAP values (Random Forest)...")
    explainer   = shap.TreeExplainer(rf)
    shap_values = explainer.shap_values(X)

    # Normalise to 2D array for churn class (class 1)
    if isinstance(shap_values, list):
        sv = shap_values[1]
    elif hasattr(shap_values, "ndim") and shap_values.ndim == 3:
        sv = shap_values[:, :, 1]
    else:
        sv = shap_values

    plt.figure(figsize=(10, 7))
    shap.summary_plot(sv, X, show=False, plot_size=None)
    plt.title("SHAP Summary — Feature Impact on Churn Probability", fontsize=13)
    plt.tight_layout()
    out = OUTPUT_DIR / "churn_shap_summary.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {out.relative_to(REPO_ROOT)}")

    mean_shap_vals = np.abs(sv).mean(axis=0)
    mean_shap = pd.DataFrame({
        "feature":   list(X.columns),
        "mean_shap": list(mean_shap_vals),
    }).sort_values("mean_shap", ascending=False)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(mean_shap["feature"], mean_shap["mean_shap"], color="#534AB7")
    ax.set_title("Mean |SHAP| — Average Impact on Churn Prediction", fontsize=12)
    ax.set_xlabel("Mean |SHAP value|")
    ax.invert_yaxis()
    plt.tight_layout()
    out = OUTPUT_DIR / "churn_shap_bar.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {out.relative_to(REPO_ROOT)}")

    print("Top features by mean |SHAP|:")
    print(mean_shap.head(8).to_string(index=False))

    return sv, mean_shap


# ══════════════════════════════════════════════════════════════════════════════
# STEP 11 — FINAL RISK SCORES v2 (Random Forest + SHAP)
# ══════════════════════════════════════════════════════════════════════════════

def final_risk_scores(rf, X: pd.DataFrame, df_raw: pd.DataFrame, sv) -> pd.DataFrame:
    print("\n── Step 11: Final Risk Scores v2 ────────────────────────────────")

    churn_probs = rf.predict_proba(X)[:, 1]

    risk_df = df_raw[[
        "subscription_id", "customer_id", "plan_type",
        "product_category_key", "lifetime_days", "is_churned", "estimated_mrr",
    ]].copy().reset_index(drop=True)

    risk_df["churn_probability"] = churn_probs.round(4)
    risk_df["risk_band"] = pd.cut(churn_probs, bins=[0, 0.33, 0.66, 1.0],
                                  labels=["Low", "Medium", "High"])

    if sv is not None:
        top_reason_idx = np.abs(sv).argmax(axis=1)
        risk_df["top_churn_driver"] = [X.columns[i] for i in top_reason_idx]
    else:
        risk_df["top_churn_driver"] = "n/a"

    print("Risk band distribution:")
    print(risk_df["risk_band"].value_counts())
    high_risk_mrr = risk_df[risk_df["risk_band"] == "High"]["estimated_mrr"].sum()
    print(f"High-risk MRR at stake: £{high_risk_mrr:,.0f}")

    print("\nTop churn drivers across high-risk subscribers:")
    print(risk_df[risk_df["risk_band"] == "High"]["top_churn_driver"].value_counts().head(5))

    print("\nTop 10 highest-risk active subscribers:")
    top10 = (
        risk_df[risk_df["is_churned"] == False]
        .sort_values("churn_probability", ascending=False)
        .head(10)[[
            "subscription_id", "plan_type", "product_category_key",
            "churn_probability", "risk_band", "top_churn_driver", "estimated_mrr",
        ]]
    )
    print(top10.to_string(index=False))

    out = OUTPUT_DIR / "churn_risk_scores_v2.csv"
    risk_df.to_csv(out, index=False)
    print(f"\n   Saved: {out.relative_to(REPO_ROOT)} | {len(risk_df):,} rows scored")

    return risk_df


# ══════════════════════════════════════════════════════════════════════════════
# STEP 12 — WRITE RESULTS TO SNOWFLAKE (ML SCHEMA)
# ══════════════════════════════════════════════════════════════════════════════

def write_to_snowflake(risk_df: pd.DataFrame, mean_shap: pd.DataFrame, df_raw: pd.DataFrame) -> None:
    print("\n── Step 12: Writing to Snowflake ML Schema ──────────────────────")

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database="PETAL_CO_DW",
        role="SYSADMIN",
    )
    cursor = conn.cursor()

    cursor.execute("USE DATABASE PETAL_CO_DW")
    cursor.execute("CREATE SCHEMA IF NOT EXISTS PETAL_CO_DW.ML")
    cursor.execute(f"USE WAREHOUSE {os.environ['SNOWFLAKE_WAREHOUSE']}")
    scored_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Numeric risk band: Low=1, Medium=2, High=3
    band_map = {"Low": 1, "Medium": 2, "High": 3}
    risk_df = risk_df.copy()
    risk_df["risk_band_num"] = risk_df["risk_band"].map(band_map).fillna(1).astype(int)
    risk_df["scored_at"]     = scored_at

    # ── TABLE 1: ML_CHURN_RISK_SCORES ─────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS PETAL_CO_DW.ML.ML_CHURN_RISK_SCORES (
            SUBSCRIPTION_ID      VARCHAR(20),
            CUSTOMER_ID          VARCHAR(20),
            PLAN_TYPE            VARCHAR(20),
            PRODUCT_CATEGORY_KEY VARCHAR(50),
            LIFETIME_DAYS        NUMBER(9,0),
            IS_CHURNED           BOOLEAN,
            ESTIMATED_MRR        NUMBER(31,2),
            CHURN_PROBABILITY    NUMBER(6,4),
            RISK_BAND            NUMBER(1,0),
            RISK_BAND_LABEL      VARCHAR(10),
            TOP_CHURN_DRIVER     VARCHAR(50),
            SCORED_AT            TIMESTAMP_NTZ
        )
    """)
    cursor.execute("TRUNCATE TABLE IF EXISTS PETAL_CO_DW.ML.ML_CHURN_RISK_SCORES")

    rows = []
    for _, r in risk_df.iterrows():
        rows.append((
            str(r["subscription_id"]),
            str(r["customer_id"]),
            str(r["plan_type"]),
            str(r["product_category_key"]),
            int(r["lifetime_days"]) if pd.notna(r["lifetime_days"]) else None,
            bool(r["is_churned"]),
            float(r["estimated_mrr"]) if pd.notna(r["estimated_mrr"]) else 0.0,
            float(r["churn_probability"]),
            int(r["risk_band_num"]),
            str(r["risk_band"]),
            str(r["top_churn_driver"]),
            scored_at,
        ))

    cursor.executemany("""
        INSERT INTO PETAL_CO_DW.ML.ML_CHURN_RISK_SCORES (
            SUBSCRIPTION_ID, CUSTOMER_ID, PLAN_TYPE, PRODUCT_CATEGORY_KEY,
            LIFETIME_DAYS, IS_CHURNED, ESTIMATED_MRR, CHURN_PROBABILITY,
            RISK_BAND, RISK_BAND_LABEL, TOP_CHURN_DRIVER, SCORED_AT
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, rows)
    print(f"   ML_CHURN_RISK_SCORES — {len(rows):,} rows written")

    # ── TABLE 2: ML_CHURN_SUMMARY (C-suite scorecard) ─────────────────────────
    active_df  = risk_df[risk_df["is_churned"] == False]

    total_subs      = len(risk_df)
    active_subs     = len(active_df)
    churned_subs    = len(risk_df[risk_df["is_churned"] == True])
    high_risk       = int((active_df["risk_band_num"] == 3).sum())
    medium_risk     = int((active_df["risk_band_num"] == 2).sum())
    low_risk        = int((active_df["risk_band_num"] == 1).sum())
    total_mrr       = float(active_df["estimated_mrr"].sum())
    high_risk_mrr   = float(active_df[active_df["risk_band_num"] == 3]["estimated_mrr"].sum())
    pct_mrr_at_risk = round(high_risk_mrr / total_mrr * 100, 2) if total_mrr > 0 else 0.0

    # MRR-weighted average churn probability, scaled to 1-3 band range
    if total_mrr > 0:
        overall_risk_band = float(
            (active_df["churn_probability"] * active_df["estimated_mrr"]).sum()
            / total_mrr * 2 + 1
        )
    else:
        overall_risk_band = float(active_df["churn_probability"].mean() * 2 + 1)

    overall_risk_band  = round(min(max(overall_risk_band, 1.0), 3.0), 3)
    overall_risk_label = "Low" if overall_risk_band < 1.5 else "Medium" if overall_risk_band < 2.0 else "High"

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS PETAL_CO_DW.ML.ML_CHURN_SUMMARY (
            TOTAL_SUBSCRIBERS    NUMBER(9,0),
            ACTIVE_SUBSCRIBERS   NUMBER(9,0),
            CHURNED_SUBSCRIBERS  NUMBER(9,0),
            HIGH_RISK_COUNT      NUMBER(9,0),
            MEDIUM_RISK_COUNT    NUMBER(9,0),
            LOW_RISK_COUNT       NUMBER(9,0),
            HIGH_RISK_MRR        NUMBER(31,2),
            TOTAL_MRR            NUMBER(31,2),
            PCT_MRR_AT_RISK      NUMBER(6,2),
            OVERALL_RISK_BAND    NUMBER(6,3),
            OVERALL_RISK_LABEL   VARCHAR(10),
            SCORED_AT            TIMESTAMP_NTZ
        )
    """)
    cursor.execute("TRUNCATE TABLE IF EXISTS PETAL_CO_DW.ML.ML_CHURN_SUMMARY")
    cursor.execute("""
        INSERT INTO PETAL_CO_DW.ML.ML_CHURN_SUMMARY (
            TOTAL_SUBSCRIBERS, ACTIVE_SUBSCRIBERS, CHURNED_SUBSCRIBERS,
            HIGH_RISK_COUNT, MEDIUM_RISK_COUNT, LOW_RISK_COUNT,
            HIGH_RISK_MRR, TOTAL_MRR, PCT_MRR_AT_RISK,
            OVERALL_RISK_BAND, OVERALL_RISK_LABEL, SCORED_AT
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (total_subs, active_subs, churned_subs,
          high_risk, medium_risk, low_risk,
          high_risk_mrr, total_mrr, pct_mrr_at_risk,
          overall_risk_band, overall_risk_label, scored_at))

    print(f"   ML_CHURN_SUMMARY — 1 row written")
    print(f"\n── C-Suite Summary ──────────────────────────────────────────────")
    print(f"   Total subscribers  : {total_subs:,}")
    print(f"   Active             : {active_subs:,} | Churned: {churned_subs:,}")
    print(f"   High risk          : {high_risk:,} | Medium: {medium_risk:,} | Low: {low_risk:,}")
    print(f"   Total MRR          : £{total_mrr:,.2f}")
    print(f"   High-risk MRR      : £{high_risk_mrr:,.2f} ({pct_mrr_at_risk:.1f}% of total)")
    print(f"   Overall risk band  : {overall_risk_band:.3f} — {overall_risk_label}")

     # ── TABLE 3: ML_CHURN_SHAP_IMPORTANCE ────────────────────────────────────
    # Human-readable feature labels for Looker Studio axis display
    FEATURE_LABELS = {
        "cohort_month":        "Acquisition month",
        "order_interval_days": "Order interval (days)",
        "cohort_quarter":      "Acquisition quarter",
        "plan_type_enc":       "Plan type",
        "total_net_revenue":   "Net revenue (£)",
        "total_orders":        "Total orders",
        "total_discounts":     "Total discounts (£)",
        "avg_order_value":     "Avg order value (£)",
        "discount_rate":       "Discount rate",
        "product_cat_enc":     "Product category",
        "total_returns":       "Total returns",
        "return_ratio":        "Return ratio",
        "return_rate":         "Return rate",
    }

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS PETAL_CO_DW.ML.ML_CHURN_SHAP_IMPORTANCE (
            FEATURE_NAME    VARCHAR(50),
            FEATURE_LABEL   VARCHAR(100),
            MEAN_SHAP       NUMBER(10,6),
            SHAP_RANK       NUMBER(3,0),
            SCORED_AT       TIMESTAMP_NTZ
        )
    """)
    cursor.execute(
        "TRUNCATE TABLE IF EXISTS PETAL_CO_DW.ML.ML_CHURN_SHAP_IMPORTANCE"
    )

    mean_shap_sorted = mean_shap.sort_values(
        "mean_shap", ascending=False
    ).reset_index(drop=True)

    shap_rows = []
    for rank, (_, row) in enumerate(mean_shap_sorted.iterrows(), start=1):
        shap_rows.append((
            str(row["feature"]),
            FEATURE_LABELS.get(str(row["feature"]), str(row["feature"])),
            float(row["mean_shap"]),
            rank,
            scored_at,
        ))

    cursor.executemany("""
        INSERT INTO PETAL_CO_DW.ML.ML_CHURN_SHAP_IMPORTANCE (
            FEATURE_NAME, FEATURE_LABEL, MEAN_SHAP, SHAP_RANK, SCORED_AT
        ) VALUES (%s,%s,%s,%s,%s)
    """, shap_rows)

    print(f"   ML_CHURN_SHAP_IMPORTANCE — {len(shap_rows)} rows written")
    print("\nSHAP importance ranking:")
    for r in shap_rows:
        print(f"   {r[3]:>2}. {r[1]:<30} {r[2]:.6f}")

    
    # ── TABLE 4: ML_CHURN_INSIGHTS (dynamic key-value insight store) ──────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS PETAL_CO_DW.ML.ML_CHURN_INSIGHTS (
            INSIGHT_KEY      VARCHAR(50),
            INSIGHT_LABEL    VARCHAR(100),
            INSIGHT_VALUE    VARCHAR(200),
            INSIGHT_NUMERIC  NUMBER(10,4),
            SCORED_AT        TIMESTAMP_NTZ
        )
    """)
    cursor.execute("TRUNCATE TABLE IF EXISTS PETAL_CO_DW.ML.ML_CHURN_INSIGHTS")

    # ── COMPUTE INSIGHT VALUES FROM DATA ──────────────────────────────────────
    # Plan churn rates
    monthly_churn   = float(risk_df[risk_df["plan_type"] == "monthly"]["is_churned"].mean())
    quarterly_churn = float(risk_df[risk_df["plan_type"] == "quarterly"]["is_churned"].mean())
    plan_multiplier = round(monthly_churn / quarterly_churn, 2) if quarterly_churn > 0 else 0.0

    # Highest churn cohort quarter (from df_raw using cohort data)
    df_raw_copy = df_raw.copy()
    df_raw_copy["start_cohort"] = pd.to_datetime(df_raw_copy["start_cohort"])
    df_raw_copy["cohort_quarter"] = df_raw_copy["start_cohort"].dt.quarter
    cohort_churn = (
        df_raw_copy.groupby("cohort_quarter")["is_churned"]
        .mean()
        .sort_values(ascending=False)
    )
    high_risk_cohort_q   = int(cohort_churn.index[0])
    high_risk_cohort_val = float(cohort_churn.iloc[0])

    # Returns SHAP rank — find rank of return_rate in mean_shap_sorted
    returns_rank = None
    for i, row in enumerate(shap_rows, start=1):
        if row[0] == "return_rate":
            returns_rank = i
            returns_shap = row[2]
            break
    if returns_rank is None:
        returns_rank = len(shap_rows)
        returns_shap = 0.0

    # Top driver overall
    top_driver_row  = shap_rows[0]  # already sorted by SHAP rank asc, rank 1 = top
    top_driver_name = top_driver_row[0]
    top_driver_label = top_driver_row[1]
    top_driver_shap  = top_driver_row[2]

    # Top driver % of high-risk subscribers
    active_high_risk = risk_df[(risk_df["is_churned"] == False) & (risk_df["risk_band_num"] == 3)]
    total_high_risk_active = len(active_high_risk)
    top_driver_count = int((active_high_risk["top_churn_driver"] == top_driver_name).sum())
    top_driver_pct   = round(top_driver_count / total_high_risk_active, 6) if total_high_risk_active > 0 else 0.0

    # ── INSERT INSIGHT ROWS ───────────────────────────────────────────────────
    insight_rows = [
        (
            "plan_churn_multiplier",
            "Monthly vs quarterly churn multiplier",
            f"{plan_multiplier:.1f}×",
            plan_multiplier,
            scored_at,
        ),
        (
            "monthly_churn_rate",
            "Monthly plan churn rate",
            f"{monthly_churn:.0%}",
            round(monthly_churn, 4),
            scored_at,
        ),
        (
            "quarterly_churn_rate",
            "Quarterly plan churn rate",
            f"{quarterly_churn:.0%}",
            round(quarterly_churn, 4),
            scored_at,
        ),
        (
            "high_risk_cohort",
            "Highest churn cohort quarter",
            f"Q{high_risk_cohort_q}",
            float(high_risk_cohort_q),
            scored_at,
        ),
        (
            "high_risk_cohort_churn_rate",
            "Churn rate of highest-risk cohort quarter",
            f"{high_risk_cohort_val:.0%}",
            round(high_risk_cohort_val, 4),
            scored_at,
        ),
        (
            "returns_shap_rank",
            "Return rate SHAP rank (out of 13)",
            f"{returns_rank}th of {len(shap_rows)}",
            float(returns_rank),
            scored_at,
        ),
        (
            "returns_shap_value",
            "Return rate mean SHAP value",
            f"{returns_shap:.4f}",
            round(returns_shap, 6),
            scored_at,
        ),
        (
            "top_driver",
            "Top churn driver (feature name)",
            top_driver_name,
            None,
            scored_at,
        ),
        (
            "top_driver_label",
            "Top churn driver (readable)",
            top_driver_label,
            None,
            scored_at,
        ),
        (
            "top_driver_shap",
            "Top churn driver mean SHAP value",
            f"{top_driver_shap:.4f}",
            round(top_driver_shap, 6),
            scored_at,
        ),
        (
            "top_driver_pct",
            "% of high-risk subscribers driven by top driver",
            f"{top_driver_pct:.1f}%",
            round(top_driver_pct, 4),
            scored_at,
        ),
    ]

    cursor.executemany("""
        INSERT INTO PETAL_CO_DW.ML.ML_CHURN_INSIGHTS (
            INSIGHT_KEY, INSIGHT_LABEL, INSIGHT_VALUE,
            INSIGHT_NUMERIC, SCORED_AT
        ) VALUES (%s,%s,%s,%s,%s)
    """, insight_rows)

    print(f"   ML_CHURN_INSIGHTS — {len(insight_rows)} rows written")
    print("\nKey insights:")
    for r in insight_rows:
        print(f"   {r[1]:<50} {r[2]}")
    
    conn.commit()
    cursor.close()
    conn.close()
    print(f"\n   All tables written to PETAL_CO_DW.ML")
    print(f"   PETAL_CO_DW.ML.ML_CHURN_RISK_SCORES")
    print(f"   PETAL_CO_DW.ML.ML_CHURN_SUMMARY")
    print(f"   PETAL_CO_DW.ML.ML_CHURN_SHAP_IMPORTANCE")
    print(f"   PETAL_CO_DW.ML.ML_CHURN_INSIGHTS")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    # ── DAY 1 ──────────────────────────────────────────────────────────────────
    df_raw = load_data()
    explore(df_raw)
    X, y, df_eng, le_plan, le_cat = engineer_features(df_raw)
    lr, scaler, X_test, y_test, y_pred, y_pred_prob = train_baseline(X, y)
    evaluate(lr, X, y_test, y_pred, y_pred_prob)
    score_subscribers(lr, scaler, X, df_raw)

    # ── DAY 2 ──────────────────────────────────────────────────────────────────
    rf,  _, rf_prob  = train_random_forest(X, y)
    xgb, _, xgb_prob = train_xgboost(X, y)
    compare_models(X, y, lr, scaler, rf, xgb)
    sv, mean_shap = shap_analysis(rf, X)
    if sv is None:
        mean_shap = pd.DataFrame(columns=["feature", "mean_shap"])
    risk_df = final_risk_scores(rf, X, df_raw, sv)

    # ── STEP 12: WRITE TO SNOWFLAKE ML SCHEMA ──────────────────────────────────
    write_to_snowflake(risk_df, mean_shap, df_raw)

    print("\n" + "=" * 60)
    print("  All steps complete.")
    print("  Outputs in: pipeline/data/ml_output/")
    print("    churn_eda_distributions.png")
    print("    churn_baseline_evaluation.png")
    print("    churn_feature_importance.png")
    print("    churn_risk_scores.csv")
    print("    churn_rf_feature_importance.png")
    print("    churn_model_comparison.png")
    print("    churn_shap_summary.png")
    print("    churn_shap_bar.png")
    print("    churn_risk_scores_v2.csv")
    print("  Snowflake:")
    print("    PETAL_CO_DW.ML.ML_CHURN_RISK_SCORES")
    print("    PETAL_CO_DW.ML.ML_CHURN_SUMMARY")
    print("    PETAL_CO_DW.ML.ML_CHURN_SHAP_IMPORTANCE")
    print("    PETAL_CO_DW.ML.ML_CHURN_INSIGHTS")
    print("=" * 60)