# CDR AWS Local
The project has the following dependencies:

**Moto** — Lightweight, in-memory mock server for AWS services. Emulates S3 (object storage), the Glue Data Catalog (table metadata), the Athena query API, and SQS (message queuing) so that local development never touches real AWS resources.

**Glue** — AWS Glue ETL container (`aws-glue-libs`) that bundles Apache Spark, SparkContext, and the `awsglue` Python libraries. Runs PySpark Glue jobs locally with full access to the Moto-backed Glue Catalog and S3.

**Trino** — Distributed SQL query engine that serves as the local equivalent of Amazon Athena. Connects to the Moto Glue Catalog via a Hive-compatible metastore and reads Parquet/JSON data directly from mock S3.

**OpenSearch** — Open-source search and analytics engine (fork of Elasticsearch 7.x) that mirrors the managed AWS OpenSearch Service. Provides full-text search, structured queries, and analytics over JSON documents via a REST API on port 9200.

**OpenSearch Dashboards** — Browser-based visualization and management UI for OpenSearch (equivalent to Kibana / AWS OpenSearch Dashboards). Available on port 5601 for exploring indices, building visualizations, and running Dev Tools queries.

The following containers must be deployed `motoserver/moto`, `public.ecr.aws/glue/aws-glue-libs`, `trinodb/trino`, `opensearchproject/opensearch` and `opensearchproject/opensearch-dashboards` on Podman or Docker.

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
└── sample-apps/
    ├── query_athena_table.py
    ├── query_glue_table.py
    ├── query_utils.py
    ├── sqs_to_opensearch.py
    ├── requirements.txt
    └── run_pipeline.py
```
### `sample-apps/requirements.txt`

```
boto3
trino
pandas
```

---

### Moto (Local AWS Services)

The `moto` container (`motoserver/moto`) emulates multiple AWS services in a single process. All state is held in memory and resets when the container restarts.

| Emulated Service | AWS Equivalent       | Purpose                                |
|------------------|----------------------|----------------------------------------|
| S3               | Amazon S3            | Object storage for Parquet/JSON files  |
| Glue Catalog     | AWS Glue Data Catalog| Table and database metadata            |
| Athena           | Amazon Athena        | Query execution API                    |
| SQS              | Amazon SQS           | Message queuing                        |

| Service  | URL                   |
|----------|-----------------------|
| Moto API | http://localhost:5000 |

Credentials for all Moto-backed calls: `aws_access_key_id=test`, `aws_secret_access_key=test`, `region=us-east-1`.

Verify Moto is running:

```bash
curl http://localhost:5000/moto-api/
```

List S3 buckets and Glue databases:

```bash
aws --endpoint-url http://localhost:5000 s3 ls \
    --region us-east-1 --no-sign-request

aws --endpoint-url http://localhost:5000 glue get-databases \
    --region us-east-1 --no-sign-request
```

Create an SQS queue and send a message:

```bash
aws --endpoint-url http://localhost:5000 sqs create-queue \
    --queue-name my-queue --region us-east-1 --no-sign-request

aws --endpoint-url http://localhost:5000 sqs send-message \
    --queue-url http://localhost:5000/000000000000/my-queue \
    --message-body '{"hello":"world"}' --region us-east-1 --no-sign-request
```

---

### Glue (Local Spark ETL)

The `glue` container (`public.ecr.aws/glue/aws-glue-libs:5`) provides the same Spark + `awsglue` runtime used by AWS Glue ETL jobs. It starts idle (`tail -f /dev/null`) so you can submit jobs on demand.

| Detail           | Value                                        |
|------------------|----------------------------------------------|
| Image            | `public.ecr.aws/glue/aws-glue-libs:5`       |
| Spark master     | `local[*]`                                   |
| Jobs directory   | `./glue-jobs` → `/home/hadoop/jobs`          |
| Data directory   | `./data` → `/home/hadoop/data`               |
| S3 backend       | Moto (`http://moto:5000`)                    |

Submit a Glue job manually:

```bash
docker compose exec -T glue spark-submit \
    --master "local[*]" \
    /home/hadoop/jobs/01_ingest_to_catalog.py
```

List Glue Catalog tables created by the jobs:

```bash
aws --endpoint-url http://localhost:5000 glue get-tables \
    --database-name sales_db --region us-east-1 --no-sign-request
```

The two included Glue jobs:

| Job | File | Description |
|-----|------|-------------|
| 1 | `01_ingest_to_catalog.py` | Reads local JSON, writes Parquet to S3, registers tables in the Glue Catalog |
| 2 | `02_join_and_write.py` | Joins customer and order tables via Spark, writes joined Parquet, registers the result |

---

### Trino (Local Athena)

The `trino` container (`trinodb/trino`) is a single-node Trino coordinator that acts as a local Amazon Athena. It connects to the Moto Glue Catalog as its Hive metastore and reads Parquet data from mock S3.

| Detail               | Value                          |
|----------------------|--------------------------------|
| Image                | `trinodb/trino`                |
| HTTP port            | `8080`                         |
| Catalog name         | `glue`                         |
| Metastore type       | `glue` (Hive connector)        |
| S3 backend           | Moto (`http://moto:5000`)      |

Configuration files are in `trino-config/`:

| File | Purpose |
|------|---------|
| `config.properties` | Coordinator settings, HTTP port |
| `node.properties` | Node identity |
| `jvm.config` | JVM options |
| `catalog/glue.properties` | Hive connector → Moto Glue + S3 |

Verify Trino is ready:

```bash
curl http://localhost:8080/v1/info
```

Run a query via the Trino CLI (from the container):

```bash
docker compose exec trino trino --execute \
    "SELECT * FROM glue.sales_db.customer_orders LIMIT 5"
```

Or use the Python sample app:

```bash
python sample-apps/query_glue_table.py "SELECT * FROM glue.sales_db.customer_orders ORDER BY order_date"
```

---

### OpenSearch (Local AWS OpenSearch)

The `opensearch` container provides a local, single-node OpenSearch cluster (AWS OpenSearch equivalent). Security is disabled for local development convenience.

| Service               | URL                          |
|-----------------------|------------------------------|
| OpenSearch API        | http://localhost:9200        |
| OpenSearch Dashboards | http://localhost:5601        |

Verify the cluster is running:

```bash
curl http://localhost:9200
curl http://localhost:9200/_cluster/health?pretty
```

Create an index and insert a document:

```bash
curl -X PUT http://localhost:9200/my-index \
  -H 'Content-Type: application/json' \
  -d '{"settings":{"number_of_shards":1,"number_of_replicas":0}}'

curl -X POST http://localhost:9200/my-index/_doc/1 \
  -H 'Content-Type: application/json' \
  -d '{"title":"Hello","content":"OpenSearch is running locally"}'
```

Search the index:

```bash
curl http://localhost:9200/my-index/_search?pretty
```

Open OpenSearch Dashboards in a browser at http://localhost:5601 to explore data visually.

---

### Final Architecture

```
  JSON files (local)
        │
        │ uploaded on job start
        ▼
  ┌─────────────┐        ┌──────────────────────────────┐
  │    Moto     │◄───────│   Glue Container             │
  │  S3 + Glue  │        │   (Spark + SparkContext      │
  │  Catalog    │───────►│    + awsglue libs)           │
  │  + Athena   │        │                              │
  │    APIs     │        │  Job 1: JSON → Parquet       │
  └─────────────┘        │          → Glue Catalog      │
        │                │                              │
        │                │  Job 2: Join via Spark       │
        │                │          → Parquet           │
        │                │          → Glue Catalog      │
        │                └──────────────────────────────┘
        │
        │ Glue Catalog (hive metastore=glue)
        ▼
  ┌─────────────┐
  │    Trino    │  ← queries Glue Catalog + reads
  │  (Athena)   │    Parquet directly from mock S3
  └─────────────┘

  ┌─────────────────────┐
  │     OpenSearch      │  ← full-text search & analytics
  │  (AWS OpenSearch)   │    http://localhost:9200
  └─────────────────────┘
          │
          ▼
  ┌──────────────────────┐
  │ OpenSearch Dashboards│  ← visualization UI
  │   (Kibana equiv.)    │    http://localhost:5601
  └──────────────────────┘
```

**5 containers, no duplication, Moto handles everything AWS-side.**

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
python sample-apps/run_pipeline.py
python sample-apps/sqs_to_opensearch.py
```

### Query Scripts

The app includes two standalone query scripts that accept a SQL `SELECT` statement as a command-line argument and print all records to stdout.

1. Query Glue tables through Trino (local Athena-compatible engine):

```bash
python sample-apps/query_glue_table.py "SELECT * FROM glue.sales_db.customer_orders ORDER BY order_date"
```

Additional example with optional connection flags:

```bash
python sample-apps/query_glue_table.py "SELECT country, SUM(amount) AS revenue FROM glue.sales_db.customer_orders GROUP BY country ORDER BY revenue DESC" \
      --host localhost --port 8080 --user admin --catalog glue --schema sales_db
```

2. Query Athena tables through the Athena API (Moto endpoint):

```bash
python sample-apps/query_athena_table.py "SELECT * FROM customer_orders ORDER BY order_date"
```

Additional example with optional endpoint/output flags:

```bash
python sample-apps/query_athena_table.py "SELECT customer_name, COUNT(*) AS orders FROM customer_orders GROUP BY customer_name ORDER BY orders DESC" \
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

### SQS to OpenSearch Demo

The script `sample-apps/sqs_to_opensearch.py` demonstrates a complete message flow:

1. Creates an SQS queue on the Moto endpoint
2. Sends a JSON message to the queue
3. Receives and deletes the message from the queue
4. Indexes the message into a local OpenSearch cluster
5. Searches the index to verify the document was stored

Run with the default sample message:

```bash
python sample-apps/sqs_to_opensearch.py
```

Run with a custom JSON message:

```bash
python sample-apps/sqs_to_opensearch.py --message '{"event": "signup", "user": "alice"}'
```

All available flags:

```bash
python sample-apps/sqs_to_opensearch.py \
      --message '{"event": "signup", "user": "alice"}' \
      --sqs-endpoint http://localhost:5000 \
      --opensearch-url http://localhost:9200 \
      --index events \
      --region us-east-1 \
      --access-key test \
      --secret-key test
```

Prerequisites:

- Containers must be running: `docker compose up -d`
- Install dependencies: `uv pip install -r requirements.txt`

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

