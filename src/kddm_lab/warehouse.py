from pathlib import Path

import duckdb

SOURCE_FILES = {
    "raw_customers": "olist_customers_dataset.csv",
    "raw_orders": "olist_orders_dataset.csv",
    "raw_order_items": "olist_order_items_dataset.csv",
    "raw_order_payments": "olist_order_payments_dataset.csv",
    "raw_order_reviews": "olist_order_reviews_dataset.csv",
    "raw_products": "olist_products_dataset.csv",
    "raw_sellers": "olist_sellers_dataset.csv",
}

WAREHOUSE_TABLES = (
    "fact_order_items",
    "fact_payments",
    "dim_customers",
    "dim_products",
    "dim_sellers",
    "dim_payment_types",
    "dim_date",
    *SOURCE_FILES,
)

ANALYSIS_VIEWS = (
    "monthly_sales",
    "category_sales",
    "state_sales",
    "ml_customer_features",
)


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_warehouse(data_dir: Path, db_path: Path) -> dict[str, int]:
    """Load Olist CSVs and rebuild the DuckDB star-schema warehouse."""
    data_dir = data_dir.resolve()
    db_path = db_path.resolve()
    missing = [filename for filename in SOURCE_FILES.values() if not (data_dir / filename).is_file()]
    if missing:
        missing_files = ", ".join(missing)
        raise FileNotFoundError(f"Missing required Olist CSV file(s) in {data_dir}: {missing_files}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(db_path))
    try:
        connection.execute("BEGIN TRANSACTION")
        for view in ANALYSIS_VIEWS:
            connection.execute(f"DROP VIEW IF EXISTS {view}")
        for table in WAREHOUSE_TABLES:
            connection.execute(f"DROP TABLE IF EXISTS {table}")

        for table, filename in SOURCE_FILES.items():
            csv_path = _sql_string(str(data_dir / filename).replace("\\", "/"))
            connection.execute(
                f"CREATE TABLE {table} AS "
                f"SELECT * FROM read_csv_auto({csv_path}, header = true)"
            )

        order_count = connection.execute("SELECT count(*) FROM raw_orders").fetchone()[0]
        item_count = connection.execute("SELECT count(*) FROM raw_order_items").fetchone()[0]
        if not order_count or not item_count:
            raise ValueError("Olist orders and order-items CSV files must both contain rows.")

        connection.execute(
            """
            CREATE TABLE dim_customers AS
            SELECT
                row_number() OVER (ORDER BY customer_id) AS customer_key,
                customer_id,
                customer_unique_id,
                customer_zip_code_prefix,
                customer_city,
                customer_state
            FROM raw_customers
            """
        )
        connection.execute(
            """
            CREATE TABLE dim_products AS
            SELECT
                row_number() OVER (ORDER BY product_id) AS product_key,
                product_id,
                product_category_name,
                coalesce(product_category_name_english, product_category_name) AS category_name,
                product_name_lenght AS product_name_length,
                product_description_lenght AS product_description_length,
                product_photos_qty,
                product_weight_g,
                product_length_cm,
                product_height_cm,
                product_width_cm
            FROM raw_products
            """
        )
        connection.execute(
            """
            CREATE TABLE dim_sellers AS
            SELECT
                row_number() OVER (ORDER BY seller_id) AS seller_key,
                seller_id,
                seller_zip_code_prefix,
                seller_city,
                seller_state
            FROM raw_sellers
            """
        )
        connection.execute(
            """
            CREATE TABLE dim_payment_types AS
            SELECT
                row_number() OVER (ORDER BY payment_type) AS payment_type_key,
                payment_type
            FROM (
                SELECT DISTINCT coalesce(payment_type, 'unknown') AS payment_type
                FROM raw_order_payments
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE dim_date AS
            WITH bounds AS (
                SELECT
                    min(try_cast(order_purchase_timestamp AS DATE)) AS start_date,
                    max(try_cast(order_estimated_delivery_date AS DATE)) AS end_date
                FROM raw_orders
            ),
            calendar AS (
                SELECT calendar_date::DATE AS calendar_date
                FROM bounds,
                LATERAL generate_series(start_date, end_date, INTERVAL 1 DAY) AS dates(calendar_date)
            )
            SELECT
                strftime(calendar_date, '%Y%m%d')::INTEGER AS date_key,
                calendar_date,
                year(calendar_date) AS year,
                quarter(calendar_date) AS quarter,
                month(calendar_date) AS month,
                monthname(calendar_date) AS month_name,
                day(calendar_date) AS day_of_month,
                isodow(calendar_date) AS day_of_week,
                isodow(calendar_date) IN (6, 7) AS is_weekend
            FROM calendar
            UNION ALL
            SELECT 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
            """
        )
        connection.execute(
            """
            CREATE TABLE fact_order_items AS
            SELECT
                row_number() OVER (ORDER BY i.order_id, i.order_item_id) AS order_item_key,
                i.order_id,
                i.order_item_id,
                c.customer_key,
                p.product_key,
                s.seller_key,
                coalesce(strftime(try_cast(o.order_purchase_timestamp AS DATE), '%Y%m%d')::INTEGER, 0)
                    AS order_date_key,
                coalesce(strftime(try_cast(o.order_estimated_delivery_date AS DATE), '%Y%m%d')::INTEGER, 0)
                    AS estimated_delivery_date_key,
                o.order_status,
                i.price::DOUBLE AS item_price,
                i.freight_value::DOUBLE AS freight_value,
                (i.price + i.freight_value)::DOUBLE AS gross_item_value
            FROM raw_order_items AS i
            LEFT JOIN raw_orders AS o USING (order_id)
            LEFT JOIN dim_customers AS c ON o.customer_id = c.customer_id
            LEFT JOIN dim_products AS p USING (product_id)
            LEFT JOIN dim_sellers AS s USING (seller_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE fact_payments AS
            SELECT
                row_number() OVER (ORDER BY p.order_id, p.payment_sequential) AS payment_key,
                p.order_id,
                p.payment_sequential AS payment_sequence,
                c.customer_key,
                t.payment_type_key,
                coalesce(strftime(try_cast(o.order_purchase_timestamp AS DATE), '%Y%m%d')::INTEGER, 0)
                    AS order_date_key,
                p.payment_installments,
                p.payment_value::DOUBLE AS payment_value
            FROM raw_order_payments AS p
            LEFT JOIN raw_orders AS o USING (order_id)
            LEFT JOIN dim_customers AS c ON o.customer_id = c.customer_id
            LEFT JOIN dim_payment_types AS t
                ON coalesce(p.payment_type, 'unknown') = t.payment_type
            """
        )
        connection.execute(
            """
            CREATE VIEW monthly_sales AS
            SELECT
                d.year,
                d.month,
                d.month_name,
                count(DISTINCT f.order_id) AS order_count,
                count(*) AS item_count,
                sum(f.item_price) AS item_revenue,
                sum(f.freight_value) AS freight_revenue,
                sum(f.gross_item_value) AS gross_merchandise_value
            FROM fact_order_items AS f
            JOIN dim_date AS d ON f.order_date_key = d.date_key
            WHERE f.order_date_key != 0
            GROUP BY d.year, d.month, d.month_name
            """
        )
        connection.execute(
            """
            CREATE VIEW category_sales AS
            SELECT
                coalesce(p.category_name, 'unknown') AS category_name,
                count(DISTINCT f.order_id) AS order_count,
                count(*) AS item_count,
                sum(f.gross_item_value) AS gross_merchandise_value
            FROM fact_order_items AS f
            LEFT JOIN dim_products AS p USING (product_key)
            GROUP BY 1
            """
        )
        connection.execute(
            """
            CREATE VIEW state_sales AS
            SELECT
                coalesce(c.customer_state, 'unknown') AS customer_state,
                count(DISTINCT f.order_id) AS order_count,
                count(*) AS item_count,
                sum(f.gross_item_value) AS gross_merchandise_value
            FROM fact_order_items AS f
            LEFT JOIN dim_customers AS c USING (customer_key)
            GROUP BY 1
            """
        )
        connection.execute(
            """
            CREATE VIEW ml_customer_features AS
            WITH order_features AS (
                SELECT
                    c.customer_unique_id,
                    f.order_id,
                    max(d.calendar_date) AS purchase_date,
                    sum(f.gross_item_value) AS order_gmv
                FROM fact_order_items AS f
                JOIN dim_customers AS c USING (customer_key)
                JOIN dim_date AS d ON f.order_date_key = d.date_key
                GROUP BY c.customer_unique_id, f.order_id
            ),
            customer_features AS (
                SELECT
                    customer_unique_id,
                    count(*) AS order_count,
                    sum(order_gmv) AS total_gmv,
                    avg(order_gmv) AS average_order_gmv,
                    min(purchase_date) AS first_purchase_date,
                    max(purchase_date) AS last_purchase_date
                FROM order_features
                GROUP BY customer_unique_id
            ),
            review_features AS (
                SELECT
                    c.customer_unique_id,
                    avg(try_cast(r.review_score AS DOUBLE)) AS average_review_score,
                    count(r.review_id) AS review_count
                FROM raw_order_reviews AS r
                JOIN raw_orders AS o USING (order_id)
                JOIN dim_customers AS c ON o.customer_id = c.customer_id
                GROUP BY c.customer_unique_id
            ),
            snapshot AS (
                SELECT max(purchase_date) AS snapshot_date FROM order_features
            )
            SELECT
                c.customer_unique_id,
                coalesce(f.order_count, 0) AS order_count,
                coalesce(f.total_gmv, 0.0) AS total_gmv,
                f.average_order_gmv,
                coalesce(r.average_review_score, 0.0) AS average_review_score,
                coalesce(r.review_count, 0) AS review_count,
                f.first_purchase_date,
                f.last_purchase_date,
                date_diff('day', f.last_purchase_date, s.snapshot_date) AS recency_days,
                s.snapshot_date
            FROM (SELECT DISTINCT customer_unique_id FROM dim_customers) AS c
            LEFT JOIN customer_features AS f USING (customer_unique_id)
            LEFT JOIN review_features AS r USING (customer_unique_id)
            CROSS JOIN snapshot AS s
            """
        )

        row_counts = {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("dim_customers", "dim_products", "dim_sellers", "fact_order_items", "fact_payments")
        }
        connection.execute("COMMIT")
        return row_counts
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def export_analysis(db_path: Path, output_dir: Path) -> list[Path]:
    """Export OLAP summaries and ML features, and render a monthly GMV chart."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(db_path.resolve()), read_only=True)
    exports: list[Path] = []
    try:
        for view in ("monthly_sales", "category_sales", "state_sales"):
            result = connection.execute(f"SELECT * FROM {view} ORDER BY 1, 2").fetchdf()
            if view == "monthly_sales":
                result = result.sort_values(["year", "month"])
            destination = output_dir / f"{view}.csv"
            result.to_csv(destination, index=False)
            exports.append(destination)

        features_path = output_dir / "customer_features.parquet"
        connection.execute("SELECT * FROM ml_customer_features").fetchdf().to_parquet(
            features_path, index=False
        )
        exports.append(features_path)

        monthly = connection.execute(
            "SELECT year, month, gross_merchandise_value FROM monthly_sales ORDER BY year, month"
        ).fetchdf()
    finally:
        connection.close()

    figure, axis = plt.subplots(figsize=(12, 5))
    axis.plot(
        monthly["year"].astype(str) + "-" + monthly["month"].astype(str).str.zfill(2),
        monthly["gross_merchandise_value"],
        marker="o",
    )
    axis.set(title="Olist monthly gross merchandise value", xlabel="Purchase month", ylabel="GMV")
    axis.tick_params(axis="x", labelrotation=60)
    figure.tight_layout()
    chart_path = output_dir / "monthly_gmv.png"
    figure.savefig(chart_path, dpi=150)
    plt.close(figure)
    exports.append(chart_path)
    return exports
