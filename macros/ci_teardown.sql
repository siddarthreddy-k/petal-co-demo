-- =============================================================
-- Petal & Co — CI guard + teardown macros
-- -------------------------------------------------------------
-- ci_guard():    fail-closed check that a CI operation can only
--                ever run against the isolated PETAL_CO_CI database
--                and the CI role. Refuses to touch production.
-- ci_teardown(): drops every schema the CI build created in
--                PETAL_CO_CI (all except INFORMATION_SCHEMA / PUBLIC),
--                keeping the ephemeral CI database clean between runs.
--
-- These only ever act on PETAL_CO_CI. They are inert in normal
-- dev/agent targets and are invoked exclusively by the CI workflow
-- via `dbt run-operation`. Uses the same run_query() execution
-- pattern proven in erase_at_source.sql.
-- =============================================================

{% macro ci_guard() %}
    {% if target.database | upper != 'PETAL_CO_CI' %}
        {{ exceptions.raise_compiler_error(
            "CI guard: target.database is '" ~ target.database ~
            "', expected 'PETAL_CO_CI'. Refusing to run against production.") }}
    {% endif %}
    {% if 'CI' not in (target.role | upper) %}
        {{ exceptions.raise_compiler_error(
            "CI guard: target.role is '" ~ target.role ~
            "', expected the CI role. Refusing.") }}
    {% endif %}
    {% if execute %}{{ log("CI guard passed: database=" ~ target.database ~ " role=" ~ target.role, info=True) }}{% endif %}
{% endmacro %}


{% macro ci_teardown() %}
    {% if not execute %}{{ return('') }}{% endif %}

    -- Never proceed unless we are certainly pointed at the CI database.
    {{ ci_guard() }}

    {% set find_schemas %}
        select schema_name
        from PETAL_CO_CI.INFORMATION_SCHEMA.SCHEMATA
        where schema_name not in ('INFORMATION_SCHEMA', 'PUBLIC')
    {% endset %}

    {% set results = run_query(find_schemas) %}

    {% if results and results.rows | length > 0 %}
        {% for row in results.rows %}
            {% set drop_sql %}
                drop schema if exists PETAL_CO_CI.{{ row[0] }} cascade
            {% endset %}
            {% do run_query(drop_sql) %}
            {{ log("CI teardown: dropped schema PETAL_CO_CI." ~ row[0], info=True) }}
        {% endfor %}
    {% else %}
        {{ log("CI teardown: no CI schemas to drop.", info=True) }}
    {% endif %}
{% endmacro %}