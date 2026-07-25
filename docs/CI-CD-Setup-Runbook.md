# CI/CD Setup Runbook

One-time setup to make the CI pipeline green. ~15–20 minutes. Do the steps in order.

Prerequisites: you can run SQL in Snowsight as `ACCOUNTADMIN`/`SYSADMIN`, and you have
admin on the GitHub repo.

---

## 0. Add the files to the repo

Drop the delivered files into the repo at these paths (they're already laid out this way):

```
.github/workflows/ci.yml
.sqlfluff
.sqlfluffignore
ci/profiles.yml
ci/requirements-ci.txt
ci/.yamllint
ci/ci_setup.sql
macros/ci_teardown.sql
docs/CI-CD-Pipeline.md
docs/CI-CD-Setup-Runbook.md
```

Your `.gitignore` already covers `*.p8`, `*.pub`, `*.pem`, `*.key`, `.env`, and
`profiles.yml`, so nothing sensitive can be committed. `ci/profiles.yml` is safe to commit
(no secrets — only `env_var()` references).

---

## 1. Generate the CI key pair (a NEW 4th pair — never reuse an existing one)

Use a **shell-safe passphrase**: letters/digits only, no `%`, `^`, `#`, spaces, or quotes.

```bash
# Encrypted private key (PKCS#8)
openssl genrsa 2048 | openssl pkcs8 -topk8 -v2 des3 -inform PEM -out ci_key.p8
#   ^ you'll be prompted for the passphrase — remember it, it becomes a GitHub Secret

# Matching public key (body is what Snowflake wants)
openssl rsa -in ci_key.p8 -pubout -out ci_key.pub
```

Get the **public key body** (single line, no header/footer) for the SQL step:

```bash
# prints the key with the BEGIN/END lines stripped and newlines removed
grep -v -- '-----' ci_key.pub | tr -d '\n'
```

Keep `ci_key.p8` out of the repo (it already matches `*.p8` in `.gitignore`).

---

## 2. Create the Snowflake CI objects

Open `ci/ci_setup.sql` in Snowsight. Paste the **public key body** from step 1 into the
`RSA_PUBLIC_KEY = '<PASTE_CI_PUBLIC_KEY_BODY_HERE>'` line, then run the whole script.

> The resource-monitor block needs `ACCOUNTADMIN`; the rest uses
> `SECURITYADMIN`/`USERADMIN`/`SYSADMIN`. The script sets roles as it goes.

Then run the sanity checks at the bottom of the file (as `SCHEMA_WORKS_CI`) to confirm:
reads from `RAW` succeed, create/drop in `PETAL_CO_CI` succeeds, and a write to
`PETAL_CO_DW.MARTS` **fails** (that failure is the isolation working).

---

## 3. Add the GitHub Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add three:

| Secret name | Value |
|---|---|
| `SNOWFLAKE_ACCOUNT` | your account identifier (e.g. `ABCDEFG-XY12345`) |
| `SNOWFLAKE_CI_PRIVATE_KEY` | the **entire** contents of `ci_key.p8`, including the `-----BEGIN/END ENCRYPTED PRIVATE KEY-----` lines |
| `SNOWFLAKE_CI_PRIVATE_KEY_PASSPHRASE` | the passphrase from step 1 |

To copy the private key contents:

```bash
cat ci_key.p8        # select all, paste into the secret value box
```

Everything else (`SNOWFLAKE_CI_USER`, `_ROLE`, `_WAREHOUSE`, `_DATABASE`, `_SCHEMA`) has a
correct default baked into `ci/profiles.yml`, so you only need these three secrets.

---

## 4. First run

1. Create a branch, commit the CI files, and open a **pull request into `main`**.
2. **Job A (`lint-validate`)** should go green in ~1 minute.
3. **Job B (`build-test`)** spins up `CI_WH`, builds the DAG into `PETAL_CO_CI`, runs
   tests + `mf validate-configs` + the `at_risk_mrr` smoke query, then drops the CI
   schemas. Green when all pass.

If you'd rather test before opening a PR: **Actions → CI → Run workflow** (manual dispatch
runs Job B directly).

---

## 5. Make the checks required (recommended)

Repo → **Settings → Branches → Add branch ruleset / protection** for `main`:

- Require a pull request before merging.
- Require status checks to pass: select **`lint-validate (no warehouse)`** and
  **`build-test (Snowflake, isolated)`**.

Now nothing merges to `main` while CI is red.

---

## Troubleshooting

- **Job B: "target.database is not PETAL_CO_CI"** — the `ci_guard` fired. Check the
  `SNOWFLAKE_CI_DATABASE` default wasn't overridden by a stray secret/var.
- **JWT / key auth errors** — the `SNOWFLAKE_CI_PRIVATE_KEY` secret must include the BEGIN/END
  lines, and the passphrase must match. Re-check the public key body on the Snowflake user
  (`DESC USER SVC_SCHEMA_WORKS_CI`).
- **`mf` can't find a target** — MetricFlow reads `DBT_TARGET` (it ignores `--target`); the
  workflow already sets `DBT_TARGET=ci`. Don't remove it.
- **Private repo + gitleaks** — `gitleaks-action` is free on public repos. If you make the
  repo private, add a `GITLEAKS_LICENSE` secret (free for personal use) or drop that step.
- **`PETAL_CO_CI` schemas left behind** after a cancelled run — the next run's pre-clean
  step (`ci_teardown`) removes them; or run `dbt run-operation ci_teardown --target ci`
  locally.
- **Credit monitor tripped (`RM_CI`)** — expected only if something loops; the XSMALL +
  60s auto-suspend keeps real runs to a few cents of a credit each.