import duckdb
import pandas as pd
import pytest

from kddm_lab.warehouse import build_warehouse, export_analysis


@pytest.fixture
def olist_csv_dir(tmp_path):
    data_dir = tmp_path / "raw"
    data_dir.mkdir()
    datasets = {
        "olist_customers_dataset.csv": [
            {
                "customer_id": "c1",
                "customer_unique_id": "u1",
                "customer_zip_code_prefix": 1000,
                "customer_city": "sao paulo",
                "customer_state": "SP",
            },
            {
                "customer_id": "c2",
                "customer_unique_id": "u1",
                "customer_zip_code_prefix": 2000,
                "customer_city": "sao paulo",
                "customer_state": "SP",
            },
        ],
        "olist_orders_dataset.csv": [
            {
                "order_id": "o1",
                "customer_id": "c1",
                "order_status": "delivered",
                "order_purchase_timestamp": "2018-01-01 10:00:00",
                "order_approved_at": "2018-01-01 11:00:00",
                "order_delivered_carrier_date": "2018-01-02 10:00:00",
                "order_delivered_customer_date": "2018-01-05 10:00:00",
                "order_estimated_delivery_date": "2018-01-10 00:00:00",
            },
            {
                "order_id": "o2",
                "customer_id": "c2",
                "order_status": "delivered",
                "order_purchase_timestamp": "2018-02-02 10:00:00",
                "order_approved_at": "2018-02-02 11:00:00",
                "order_delivered_carrier_date": "2018-02-03 10:00:00",
                "order_delivered_customer_date": "2018-02-06 10:00:00",
                "order_estimated_delivery_date": "2018-02-10 00:00:00",
            },
        ],
        "olist_order_items_dataset.csv": [
            {
                "order_id": "o1",
                "order_item_id": 1,
                "product_id": "p1",
                "seller_id": "s1",
                "shipping_limit_date": "2018-01-03 00:00:00",
                "price": 100.0,
                "freight_value": 10.0,
            },
            {
                "order_id": "o2",
                "order_item_id": 1,
                "product_id": "p1",
                "seller_id": "s1",
                "shipping_limit_date": "2018-02-03 00:00:00",
                "price": 50.0,
                "freight_value": 5.0,
            },
        ],
        "olist_order_payments_dataset.csv": [
            {
                "order_id": "o1",
                "payment_sequential": 1,
                "payment_type": "credit_card",
                "payment_installments": 1,
                "payment_value": 110.0,
            },
            {
                "order_id": "o2",
                "payment_sequential": 1,
                "payment_type": "boleto",
                "payment_installments": 1,
                "payment_value": 55.0,
            },
        ],
        "olist_order_reviews_dataset.csv": [
            {"review_id": "r1", "order_id": "o1", "review_score": 5},
            {"review_id": "r2", "order_id": "o2", "review_score": 3},
        ],
        "olist_products_dataset.csv": [
            {
                "product_id": "p1",
                "product_category_name": "beleza",
                "product_name_lenght": 10,
                "product_description_lenght": 20,
                "product_photos_qty": 1,
                "product_weight_g": 500,
                "product_length_cm": 10,
                "product_height_cm": 10,
                "product_width_cm": 10,
                "product_category_name_english": "beauty",
            }
        ],
        "olist_sellers_dataset.csv": [
            {
                "seller_id": "s1",
                "seller_zip_code_prefix": 3000,
                "seller_city": "sao paulo",
                "seller_state": "SP",
            }
        ],
    }
    for filename, rows in datasets.items():
        pd.DataFrame(rows).to_csv(data_dir / filename, index=False)
    return data_dir


def test_build_creates_star_schema_and_customer_features(olist_csv_dir, tmp_path):
    database = tmp_path / "warehouse.duckdb"

    counts = build_warehouse(olist_csv_dir, database)
    assert counts["fact_order_items"] == 2
    assert counts["fact_payments"] == 2

    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT gross_merchandise_value FROM monthly_sales WHERE year = 2018 AND month = 1"
        ).fetchone()[0] == 110
        assert connection.execute(
            "SELECT gross_merchandise_value FROM category_sales WHERE category_name = 'beauty'"
        ).fetchone()[0] == 165
        features = connection.execute(
            """
            SELECT order_count, total_gmv, average_order_gmv, average_review_score,
                   review_count, recency_days
            FROM ml_customer_features
            WHERE customer_unique_id = 'u1'
            """
        ).fetchone()
        assert features == (2, 165, 82.5, 4.0, 2, 0)

    exports = export_analysis(database, tmp_path / "processed")
    assert {path.name for path in exports} == {
        "monthly_sales.csv",
        "category_sales.csv",
        "state_sales.csv",
        "customer_features.parquet",
        "monthly_gmv.png",
    }
    assert all(path.is_file() for path in exports)


def test_build_reports_missing_source_files(tmp_path):
    with pytest.raises(FileNotFoundError, match="olist_orders_dataset.csv"):
        build_warehouse(tmp_path, tmp_path / "warehouse.duckdb")
