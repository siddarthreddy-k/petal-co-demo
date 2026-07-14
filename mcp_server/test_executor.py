"""
Standalone smoke test for Tasks 6 + 7 — run this BEFORE wiring the MCP client.
It exercises the cage check, the catalog, and a real governed query directly,
so you can confirm the plumbing works without any MCP/LLM setup.

Run from the dbt project root (where profiles.yml lives), in the (dbt) env:
    python mcp_server/test_executor.py
"""
from mf_executor import assert_read_only_cage, run_metric_query, CageBreachError
from catalog import MetricCatalog


def main():
    print("1) Cage check (RAW must be unreachable)...")
    try:
        assert_read_only_cage()
        print("   OK — agent connection cannot read RAW.\n")
    except CageBreachError as e:
        print(f"   FAILED — {e}")
        return

    print("2) Catalog (loading allowlist from live semantic layer)...")
    cat = MetricCatalog.load()
    print(f"   {len(cat.metric_names)} metrics, {len(cat.dimension_names)} dimensions.")
    print(f"   churn metrics present: "
          f"{[m for m in cat.metric_names if 'churn' in m or 'risk' in m]}\n")

    print("3) Governed query: at-risk vs total MRR by risk band...")
    rows = run_metric_query(
        metric_names=["at_risk_mrr", "total_scored_mrr"],
        group_by=["customer__risk_band_label"],
    )
    for r in rows:
        print("  ", r)

    print("\n4) Refusal test: an undefined metric must be rejected...")
    ok, problem = cat.validate(["definitely_not_a_metric"], None, None)
    print(f"   validate() -> ok={ok}, reason={problem}")


if __name__ == "__main__":
    main()