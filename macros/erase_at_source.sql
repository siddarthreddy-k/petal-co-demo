{% macro erase_at_source() %}
  {% set sql %}
    update PETAL_CO_DW.RAW.CUSTOMERS t
    set email      = sha2(t.customer_id || ':email', 256),
        first_name = sha2(t.customer_id || ':first_name', 256)
    from {{ ref('gdpr_erasure_registry') }} r
    where t.customer_id = r.customer_id
      and r.status = 'erased'
      and t.email != sha2(t.customer_id || ':email', 256)
  {% endset %}
  {% do run_query(sql) %}
  {% if execute %}{{ log("Erasure applied to RAW.CUSTOMERS.", info=True) }}{% endif %}
{% endmacro %}