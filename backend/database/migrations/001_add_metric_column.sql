-- ============================================================
-- Migration 001 — Add METRIC column to pricing_cache
-- and repurpose INSTANCE_TYPE as a billing-type category.
--
-- Run once against an existing database.
-- Safe to re-run: the IF-NOT-EXISTS guard prevents duplicates.
-- ============================================================

-- 1. Add the new METRIC column (raw billing unit string)
--    e.g. "Per OCPU Per Hour", "1 Hour", "1 GB/Month"
DECLARE
    col_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO col_exists
    FROM   user_tab_columns
    WHERE  UPPER(table_name)  = 'PRICING_CACHE'
    AND    UPPER(column_name) = 'METRIC';

    IF col_exists = 0 THEN
        EXECUTE IMMEDIATE
            'ALTER TABLE pricing_cache ADD (metric VARCHAR2(200))';
        DBMS_OUTPUT.PUT_LINE('Added column: pricing_cache.metric');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Column already exists: pricing_cache.metric — skipped.');
    END IF;
END;
/

-- 2. Optional: index on METRIC for grouping / filtering queries
DECLARE
    idx_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO idx_exists
    FROM   user_indexes
    WHERE  UPPER(index_name) = 'IDX_PRICING_METRIC';

    IF idx_exists = 0 THEN
        EXECUTE IMMEDIATE
            'CREATE INDEX idx_pricing_metric ON pricing_cache(metric)';
        DBMS_OUTPUT.PUT_LINE('Created index: idx_pricing_metric');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Index already exists: idx_pricing_metric — skipped.');
    END IF;
END;
/

-- 3. Back-fill METRIC from the specifications JSON for existing OCI rows
--    (rows inserted before this migration had metric only inside the JSON blob)
UPDATE pricing_cache
SET    metric = JSON_VALUE(specifications, '$.metric')
WHERE  cloud_provider = 'OCI'
AND    metric IS NULL
AND    JSON_VALUE(specifications, '$.metric') IS NOT NULL;

COMMIT;

-- 4. Back-fill INSTANCE_TYPE for existing OCI rows that still hold the
--    service name (old behaviour).  Derive a billing-type category from metric.
UPDATE pricing_cache
SET instance_type =
    CASE
        WHEN LOWER(metric) LIKE '%ocpu%'     OR LOWER(metric) LIKE '%ecpu%'
          OR LOWER(metric) LIKE '%per hour%' OR LOWER(metric) LIKE '%node per%'
          OR LOWER(metric) LIKE '%instance per%'                          THEN 'Compute'
        WHEN LOWER(metric) LIKE '%gb%'       OR LOWER(metric) LIKE '%tb%'
          OR LOWER(metric) LIKE '%gigabyte%' OR LOWER(metric) LIKE '%terabyte%'
          OR LOWER(metric) LIKE '%storage%'  OR LOWER(metric) LIKE '%capacity%' THEN 'Storage'
        WHEN LOWER(metric) LIKE '%transfer%' OR LOWER(metric) LIKE '%bandwidth%'
          OR LOWER(metric) LIKE '%egress%'   OR LOWER(metric) LIKE '%ingress%'  THEN 'Network'
        WHEN LOWER(metric) LIKE '%request%'  OR LOWER(metric) LIKE '%api call%'
          OR LOWER(metric) LIKE '%query%'    OR LOWER(metric) LIKE '%million%'  THEN 'API/Request'
        WHEN LOWER(metric) LIKE '%license%'  OR LOWER(metric) LIKE '%byol%'     THEN 'License'
        WHEN LOWER(metric) LIKE '%support%'                                      THEN 'Support'
        ELSE 'Other'
    END
WHERE cloud_provider = 'OCI'
AND   metric IS NOT NULL;

COMMIT;

DBMS_OUTPUT.PUT_LINE('Migration 001 complete.');
