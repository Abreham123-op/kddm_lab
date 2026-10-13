# kddm_lab

A reproducible Windows data-science project for exploring the Olist Brazilian
E-Commerce dataset. Python 3.14 and `uv` manage the environment; DuckDB builds
a local star-schema warehouse for OLAP analysis and customer-level ML features.

## Toolchain

- Python 3.14, managed and pinned by `uv` (`.python-version`, `uv.lock`)
- DuckDB, pandas, and PyArrow for data loading, analytics, and Parquet exports
- Matplotlib and JupyterLab for charts and exploratory notebooks
- Git and GitHub CLI (`gh`) for version control and remote publishing

Install Git and GitHub CLI using their official Windows installers if needed.
Install `uv` from [docs.astral.sh/uv](https://docs.astral.sh/uv/).

```powershell
uv python install 3.14
uv sync --locked
```

`uv sync --locked` creates `.venv` from the checked-in lockfile and fails if
the lockfile and project dependencies are out of sync.

## Get the data

Download the Olist Brazilian E-Commerce dataset ZIP from
[Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), extract
the CSV files, and place them in `data/raw/`. The data is not included in this
repository. The warehouse build expects these original Olist filenames:

```text
olist_customers_dataset.csv
olist_orders_dataset.csv
olist_order_items_dataset.csv
olist_order_payments_dataset.csv
olist_order_reviews_dataset.csv
olist_products_dataset.csv
olist_sellers_dataset.csv
```

The geolocation CSV is intentionally not needed for the initial warehouse.
Keep the source data under `data/raw/`; local source data and generated
artifacts are excluded from Git.

## Build and analyze

Run from the repository root in PowerShell:

```powershell
uv run kddm-lab build
uv run kddm-lab analyze
```

The build reads CSVs from `data/raw/` and creates `data/olist.duckdb`. Paths
can be overridden:

```powershell
uv run kddm-lab build --data-dir data/raw --db data/olist.duckdb
uv run kddm-lab analyze --db data/olist.duckdb --output-dir data/processed
```

The build is repeatable: it replaces the project's raw, dimension, fact, and
analytics tables in a transaction. The model is a small constellation schema:

- Dimensions: `dim_customers`, `dim_products`, `dim_sellers`,
  `dim_payment_types`, and `dim_date`
- Facts: `fact_order_items` (one row per order line) and `fact_payments`
  (one row per payment record)
- Analysis views: `monthly_sales`, `category_sales`, `state_sales`, and
  `ml_customer_features`

`analyze` writes monthly, category, and state CSV summaries, exports the
customer feature view as `customer_features.parquet`, and renders a monthly
GMV chart. Generated files go to `data/processed/`.

The ML feature view contains customer-level order count, item GMV, average
order GMV, review score, first and last purchase dates, and recency at the
dataset's latest purchase date. It is a feature-table starting point, not a
training pipeline: define a prediction cutoff and future outcome window before
using it for supervised learning to avoid temporal leakage.

## Notebook and tests

Start JupyterLab:

```powershell
uv run jupyter lab
```

Open `notebooks/01_olist_olap_and_ml.ipynb` after building the warehouse.
Run the small synthetic-data tests (no Kaggle download required) with:

```powershell
uv run pytest
```

## GitHub workflow

```powershell
git add .
git commit -m "Set up reproducible Olist analytics project"
gh auth login
gh repo create kddm_lab --source . --remote origin --push
```

Choose public or private visibility when creating the remote repository.
Do not commit the downloaded dataset, local DuckDB database, or generated
analysis outputs.
