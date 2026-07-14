"""
P3 · Task 6 — Metric catalog (the fail-closed allowlist).

Builds the set of queryable metrics + dimensions by reading the LIVE semantic
layer via `mf list`, so the allowlist can never drift from what's actually
defined. This is a coarse first gate: it rejects obviously-unknown metrics or
dimensions with a clear message before we spend a warehouse round-trip.
MetricFlow itself does the fine-grained check (is THIS dimension valid for THIS
metric, are the joins defined) and also fails closed — so the two layers stack.

MetricFlow is one implementation behind this interface. Swap `load()` for a
hand-authored catalog (non-dbt sources) or a dbt Cloud API call later without
touching server.py.
"""

from __future__ import annotations
import subprocess
from dataclasses import dataclass, field

from mf_executor import _run_plain   # metadata listing (no RO target needed)


import re

# A valid metric/dimension name: lowercase alnum + underscore, optionally with
# the '__' entity path (e.g. customer__risk_band_label). Nothing else qualifies.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _parse_names(raw: str) -> list[str]:
    """Pull valid names out of `mf list` output, rejecting spinner frames and
    status text.

    Real entries are bulleted ('• name: ...'). When mf output is captured (not a
    live terminal), spinner frames and status lines ('v 🌱 ...', '🔍 Looking...',
    '\\', '/', '|') also appear — none of which start with the bullet. So we
    accept ONLY bulleted lines whose leading token is a valid identifier.
    """
    names = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped.startswith("\u2022"):   # '•' bullet required
            continue
        token = stripped[1:].strip().split(":")[0].split()[0].strip()
        if _NAME_RE.match(token):
            names.append(token)
    seen = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def _mf_list(kind: str, for_metrics: list[str] | None = None) -> list[str]:
    """kind in {'metrics', 'dimensions'}.
    `mf list dimensions` requires --metrics in this MetricFlow version, so pass
    the metric names when listing dimensions.
    """
    cmd = ["mf", "list", kind]
    if for_metrics:
        cmd += ["--metrics", ",".join(for_metrics)]
    proc = _run_plain(cmd)
    if proc.returncode != 0:
        # mf writes some failures to stdout, not stderr — show both.
        msg = (proc.stderr.strip() + "\n" + proc.stdout.strip()).strip()
        raise RuntimeError(f"`mf list {kind}` failed:\n{msg}")
    return _parse_names(proc.stdout)


@dataclass
class MetricCatalog:
    metric_names: list[str] = field(default_factory=list)
    dimension_names: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "MetricCatalog":
        metrics = _mf_list("metrics")
        dims = _mf_list("dimensions", for_metrics=metrics)
        return cls(metric_names=metrics, dimension_names=dims)

    def validate(
        self,
        metric_names: list[str],
        group_by: list[str] | None,
        order_by: str | None,
    ) -> tuple[bool, str | None]:
        """Fail-closed: every requested name must be declared, else refuse."""
        if not metric_names:
            return False, "No metric requested."
        for m in metric_names:
            if m not in self.metric_names:
                return False, f"Unknown metric '{m}' — not defined in the semantic layer."
        for d in (group_by or []):
            if d not in self.dimension_names:
                return False, f"Unknown dimension '{d}' — not defined in the semantic layer."
        if order_by:
            key = order_by.lstrip("-")
            if key not in self.metric_names and key not in self.dimension_names:
                return False, f"Cannot order by '{key}' — not a known metric or dimension."
        return True, None