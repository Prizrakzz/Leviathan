-- SILVER-F030 additive-compatibility migration for the ESR contracts (silver_esr + silver_esr_compact).
--
-- STATUS: SPECIFIED, NOT APPLIED. This is the frozen target for BF-W2 (a producer extension + a
-- re-fetch of the FAS commodity-totals / new-crop endpoints). R2 declares the additive schema; it
-- does NOT emit these columns, does NOT mutate the live Glue catalog, and does NOT publish data.
-- Applying it is gated behind a signed approval (publish_guard / INV-7) at BF-W2.
--
-- Doctrine:
--   * ADDITIVE + NULLABLE only (INV-2 schema-evolution default: additive nullable columns are the
--     only compatible evolution; type narrowing, column removal/re-labeling/re-ordering, and
--     partition-key changes are prohibited here -- those are breaking changes needing an ADR).
--   * These are source-aligned net-commitment fields the current allCountries adapter does not yet
--     emit (SILVER-F030 ADR target_additive_schema_bf_w2). ``changes_1000mt`` is retained as a
--     DEPRECATED nullable column -- it is NOT dropped here (breaking) and NOT repurposed.
--   * Registered-partition tables: an additive column is applied via ALTER TABLE ... ADD COLUMNS on
--     the table AND every registered partition's StorageDescriptor must be audited/updated in the
--     same governed migration (SILVER-F012/F013 reconciler), or old partitions read the new column
--     as NULL only after their SD is refreshed. Do NOT MSCK (the ESR as_of=/as_of_date directory vs
--     column mapping breaks it).
--
-- Apply order at BF-W2: extend the producer to emit the columns -> shadow rebuild -> validate value
-- census (SILVER-V001) -> ALTER TABLE (below) under lease -> audit partition SDs -> partition-filtered
-- Athena smoke -> silver_rebuild_gate Branch A.

-- silver_esr (canonical, s3://.../silver/production/source=usda_esr, partitioned by
-- commodity_code, market_year, as_of_date):
ALTER TABLE leviathan_dev.silver_esr ADD COLUMNS (
    accumulated_exports_1000mt        double,
    current_my_net_sales_1000mt       double,
    current_my_total_commitment_1000mt double,
    next_my_outstanding_sales_1000mt  double,
    next_my_net_sales_1000mt          double
);

-- silver_esr_compact (serving, s3://.../silver/esr, partitioned by commodity):
ALTER TABLE leviathan_dev.silver_esr_compact ADD COLUMNS (
    accumulated_exports_1000mt        double,
    current_my_net_sales_1000mt       double,
    current_my_total_commitment_1000mt double,
    next_my_outstanding_sales_1000mt  double,
    next_my_net_sales_1000mt          double
);

-- NOTE: after ADD COLUMNS on a registered-partition table, run the SILVER-F013 partition reconciler
-- to refresh each partition's StorageDescriptor columns; a plain ADD COLUMNS updates only the table
-- descriptor, so historical partitions would otherwise not expose the new (all-NULL) columns.
