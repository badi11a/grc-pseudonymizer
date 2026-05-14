-- TPC-H demo schema (scale factor 0.1)
-- 15 000 customers · 150 000 orders

CREATE TABLE customer (
    c_custkey    INTEGER PRIMARY KEY,
    c_name       VARCHAR(25)     NOT NULL,
    c_address    VARCHAR(40)     NOT NULL,
    c_nationkey  INTEGER         NOT NULL,
    c_phone      CHAR(15)        NOT NULL,
    c_acctbal    NUMERIC(15,2)   NOT NULL,
    c_mktsegment VARCHAR(10)     NOT NULL,
    c_comment    VARCHAR(117)    NOT NULL
);

CREATE TABLE orders (
    o_orderkey      INTEGER PRIMARY KEY,
    o_custkey       INTEGER         NOT NULL REFERENCES customer(c_custkey),
    o_orderstatus   CHAR(1)         NOT NULL,
    o_totalprice    NUMERIC(15,2)   NOT NULL,
    o_orderdate     DATE            NOT NULL,
    o_orderpriority VARCHAR(15)     NOT NULL,
    o_clerk         VARCHAR(15)     NOT NULL,
    o_shippriority  INTEGER         NOT NULL,
    o_comment       VARCHAR(79)     NOT NULL
);

-- 15 000 customers generated deterministically (no RANDOM())
INSERT INTO customer
SELECT
    g                                                                           AS c_custkey,
    'Customer#' || LPAD(g::text, 9, '0')                                       AS c_name,
    LPAD(g::text, 5, '0') || ' Gran Vía, piso ' || (g % 20 + 1)               AS c_address,
    (g * 7 + 3) % 25                                                           AS c_nationkey,
    LPAD(((g * 13) % 100)::text, 2, '0') || '-'
        || LPAD(((g * 17) % 1000)::text, 3, '0') || '-'
        || LPAD(((g * 19) % 10000)::text, 4, '0')                             AS c_phone,
    ROUND(((g * 173 + 42) % 11000 - 999)::numeric, 2)                         AS c_acctbal,
    (ARRAY['AUTOMOBILE','BUILDING','FURNITURE','MACHINERY','HOUSEHOLD'])
        [((g - 1) % 5) + 1]                                                    AS c_mktsegment,
    'Demo customer record ' || g                                                AS c_comment
FROM generate_series(1, 15000) g;

-- 150 000 orders: each customer has ~10 orders on average
INSERT INTO orders
SELECT
    g                                                                           AS o_orderkey,
    ((g - 1) % 15000) + 1                                                      AS o_custkey,
    (ARRAY['F','O','P'])[((g - 1) % 3) + 1]                                   AS o_orderstatus,
    ROUND(((g * 251 + 17) % 500000)::numeric, 2)                               AS o_totalprice,
    '1993-01-01'::date + ((g * 7) % 2557)                                      AS o_orderdate,
    (ARRAY['1-URGENT','2-HIGH','3-MEDIUM','4-NOT SPECIFIED','5-LOW'])
        [((g - 1) % 5) + 1]                                                    AS o_orderpriority,
    'Clerk#' || LPAD(((g * 11) % 1000)::text, 9, '0')                         AS o_clerk,
    0                                                                           AS o_shippriority,
    'Order record ' || g                                                        AS o_comment
FROM generate_series(1, 150000) g;
