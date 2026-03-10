# Glue Athena Local
The project has the following dependencies:

Moto — mock S3 + Glue Catalog API + Athena API
Glue — Spark + SparkContext + awsglue libs
Trino — Athena-compatible query engine

The following containers must be deployed `motoserver/moto`, `public.ecr.aws/glue/aws-glue-libs` and `trinodb/trino` on Podman or DOcker.

If you are using WSL and need Podman with Docker-compatible commands (`docker`, `docker compose`), follow [README-podman-wsl.md](README-podman-wsl.md).

## Project Structure

```
glue-athena-local/
├── .devcontainer/
│   └── devcontainer.json
├── .vscode/
│   ├── settings.json
│   └── extensions.json
├── docker-compose.yml
├── data/
│   ├── customers/
│   │   └── customers.json
│   └── orders/
│       └── orders.json
├── glue-jobs/
│   ├── 01_ingest_to_catalog.py
│   └── 02_join_and_write.py
├── trino-config/
│   ├── config.properties
│   ├── jvm.config
│   ├── node.properties
│   └── catalog/
│       └── glue.properties
└── app/
    ├── query_athena_table.py
    ├── query_glue_table.py
    ├── query_utils.py
    ├── requirements.txt
    └── run_pipeline.py
```
### `app/requirements.txt`

```
boto3
trino
pandas
```

---

### Running It

WSL + Podman users: see [README-podman-wsl.md](README-podman-wsl.md) for Docker-compatible setup before running these commands.

Install Astral `uv` on WSL/Linux and create a virtual environment for python 3.11 (one-time):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
uv --version

uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt

```
Install `zip` and `unzip` on WSL/Linux (one-time):

```bash
sudo apt-get update
sudo apt-get install -y zip unzip
zip -v | head -n 2
unzip -v | head -n 2
```

```bash
docker-compose up -d
sleep 30  # wait for Trino to initialize
python run_pipeline.py
```

### Query Scripts

The app includes two standalone query scripts that accept a SQL `SELECT` statement as a command-line argument and print all records to stdout.

1. Query Glue tables through Trino (local Athena-compatible engine):

```bash
python app/query_glue_table.py "SELECT * FROM glue.sales_db.customer_orders ORDER BY order_date"
```

Additional example with optional connection flags:

```bash
python app/query_glue_table.py "SELECT country, SUM(amount) AS revenue FROM glue.sales_db.customer_orders GROUP BY country ORDER BY revenue DESC" \
      --host localhost --port 8080 --user admin --catalog glue --schema sales_db
```

2. Query Athena tables through the Athena API (Moto endpoint):

```bash
python app/query_athena_table.py "SELECT * FROM customer_orders ORDER BY order_date"
```

Additional example with optional endpoint/output flags:

```bash
python app/query_athena_table.py "SELECT customer_name, COUNT(*) AS orders FROM customer_orders GROUP BY customer_name ORDER BY orders DESC" \
      --database sales_db \
      --endpoint-url http://localhost:5000 \
      --output-location s3://glue-bucket/athena-results/ \
      --region us-east-1 \
      --access-key test \
      --secret-key test \
      --timeout-seconds 60
```

Notes:

- Run `python run_pipeline.py` first so the `customer_orders` table exists.
- `query_glue_table.py` expects fully qualified table references (for example `glue.sales_db.customer_orders`).
- `query_athena_table.py` uses `sales_db` as the default Athena database.

---

### VS Code Dev Container

This repository includes a dedicated `devcontainer` service in `docker-compose.yml` and a `.devcontainer/devcontainer.json` config so VS Code can attach directly.

Prerequisite: install the VS Code extension `Dev Containers` (`ms-vscode-remote.remote-containers`).

1. Start containers:

```bash
docker compose up -d
```

2. In VS Code, open the project folder and run:

`Dev Containers: Reopen in Container`

3. Verify you are inside the dev container:

```bash
python --version
pwd
```

Expected workspace path:

`/workspace/glue-athena-local`

---

### Install AWS CLI v2 (WSL/Linux)

Install AWS CLI v2 with the official installer:

```bash
cd /tmp
curl -fsSLo awscliv2.zip https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip
unzip -o awscliv2.zip
sudo ./aws/install --update
aws --version
```

---

### AWS CLI Profile for Local Emulators

Use a dedicated AWS CLI profile (instead of `default`) for local emulator access.

```bash
# one-time profile setup
aws configure set aws_access_key_id test --profile moto
aws configure set aws_secret_access_key test --profile moto
aws configure set region us-east-1 --profile moto
aws configure set output json --profile moto

# start emulator containers
docker compose up -d moto glue trino
```

Run AWS CLI commands against Moto with `--profile moto` and `--endpoint-url http://localhost:5000`:

```bash
# S3
aws --profile moto --endpoint-url http://localhost:5000 s3 ls
aws --profile moto --endpoint-url http://localhost:5000 s3 ls s3://glue-bucket --recursive

# Glue Catalog
aws --profile moto --endpoint-url http://localhost:5000 glue get-databases
aws --profile moto --endpoint-url http://localhost:5000 glue get-tables --database-name sales_db

# Athena API (Moto-emulated)
aws --profile moto --endpoint-url http://localhost:5000 athena list-data-catalogs
```

Optional shell helper:

```bash
alias awsmoto='aws --profile moto --endpoint-url http://localhost:5000'
awsmoto s3 ls
awsmoto glue get-databases
```

---

### Final Architecture

```
  JSON files (local)
        │
        │ uploaded on job start
        ▼
  ┌─────────────┐        ┌──────────────────────────────┐
  │    Moto     │◄───────│   Glue Container             │
  │  S3 + Glue  │        │   (Spark + SparkContext       │
  │  Catalog    │───────►│    + awsglue libs)            │
  │  + Athena   │        │                              │
  │    APIs     │        │  Job 1: JSON → Parquet        │
  └─────────────┘        │          → Glue Catalog       │
        │                │                              │
        │                │  Job 2: Join via Spark        │
        │                │          → Parquet            │
        │                │          → Glue Catalog       │
        │                └──────────────────────────────┘
        │
        │ Glue Catalog (hive metastore=glue)
        ▼
  ┌─────────────┐
  │    Trino    │  ← queries Glue Catalog + reads
  │  (Athena)   │    Parquet directly from mock S3
  └─────────────┘
```

**3 containers, no duplication, Moto handles everything AWS-side.**