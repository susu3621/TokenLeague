-- Compare logical contents across major versions without exporting row values.
SET timezone = 'UTC';
SET datestyle = 'ISO, YMD';
SET intervalstyle = 'postgres';
-- The source is frozen. Only this local session may create a temporary function.
SET default_transaction_read_only = off;

CREATE FUNCTION pg_temp.relation_inventory(schema_name text, relation_name text, kind "char")
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE result jsonb;
BEGIN
    IF kind = 'S' THEN
        EXECUTE format('SELECT jsonb_build_object(''last_value'', last_value, ''is_called'', is_called) FROM %I.%I',
                       schema_name, relation_name) INTO result;
    ELSE
        EXECUTE format(
            'SELECT jsonb_build_object(''rows'', count(*), ''md5'', md5(coalesce(string_agg(digest, '''' ORDER BY digest), '''')))
             FROM (SELECT md5(row_to_json(t)::text) AS digest FROM %I.%I t) rows',
            schema_name, relation_name) INTO result;
    END IF;
    RETURN result;
END $$;
SET default_transaction_read_only = on;

WITH relations AS (
    SELECT c.oid, n.nspname, c.relname, c.relkind, pg_get_userbyid(c.relowner) AS owner
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp%'
), entries AS (
    SELECT 'relation' AS kind, nspname || '.' || relname AS name,
           pg_temp.relation_inventory(nspname, relname, relkind) || jsonb_build_object('owner', owner) AS value
    FROM relations WHERE relkind IN ('r', 'S', 'm')
    UNION ALL
    SELECT 'index', nspname || '.' || relname,
           jsonb_build_object('definition', pg_get_indexdef(i.indexrelid), 'valid', i.indisvalid)
    FROM relations JOIN pg_index i ON i.indexrelid = relations.oid
    UNION ALL
    SELECT 'constraint', r.nspname || '.' || r.relname || '.' || c.conname,
           jsonb_build_object('definition', pg_get_constraintdef(c.oid), 'validated', c.convalidated)
    FROM relations r JOIN pg_constraint c ON c.conrelid = r.oid
    -- PostgreSQL 18 also represents NOT NULL here; attnotnull covers both versions.
    WHERE c.contype <> 'n'
    UNION ALL
    SELECT 'column', r.nspname || '.' || r.relname || '.' || a.attnum,
           jsonb_build_object('name', a.attname, 'type', format_type(a.atttypid, a.atttypmod),
                             'not_null', a.attnotnull, 'default', pg_get_expr(d.adbin, d.adrelid))
    FROM relations r JOIN pg_attribute a ON a.attrelid = r.oid
    LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
    WHERE r.relkind IN ('r', 'm') AND a.attnum > 0 AND NOT a.attisdropped
    UNION ALL
    SELECT 'sequence', r.nspname || '.' || r.relname,
           to_jsonb(s) - 'seqrelid'
    FROM relations r JOIN pg_sequence s ON s.seqrelid = r.oid
    UNION ALL
    SELECT 'extension', extname, jsonb_build_object('version', extversion)
    FROM pg_extension
)
SELECT coalesce(jsonb_object_agg(kind || ':' || name, value), '{}'::jsonb) FROM entries;
