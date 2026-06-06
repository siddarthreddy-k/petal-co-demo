-- =============================================================
-- Ember & Co — Custom Schema Name Macro
-- File: macros/generate_schema_name.sql
-- Description: Overrides dbt's default schema naming behaviour.
--              By default dbt appends the custom schema to the
--              target schema (e.g. MARTS + STAGING = MARTS_STAGING)
--              This macro uses the custom schema name exactly
--              as defined in dbt_project.yml — no appending.
-- =============================================================

{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}