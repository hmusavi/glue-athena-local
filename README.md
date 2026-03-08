# Glue Athena Local
The project has the following dependencies:

Moto — mock S3 + Glue Catalog API + Athena API
Glue — Spark + SparkContext + awsglue libs
Trino — Athena-compatible query engine

Need to deploy `motoserver/moto`, `public.ecr.aws/glue/aws-glue-libs` and `trinodb/trino` on Podman.

## Project Structure

```
glue-athena-local/
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
    ├── requirements.txt
    └── run_pipeline.py
```

---
### 1. `docker-compose.yml`
```yaml
services:

  moto:
    image: motoserver/moto
    ports:
      - "5000:5000"
    environment:
      - MOTO_PORT=5000

  glue:
    image: public.ecr.aws/glue/aws-glue-libs:5
    volumes:
      - ./glue-jobs:/home/hadoop/jobs
      - ./data:/home/hadoop/data
    environment:
      - AWS_DEFAULT_REGION=us-east-1
      - AWS_ACCESS_KEY_ID=test
      - AWS_SECRET_ACCESS_KEY=test
      - AWS_ENDPOINT_URL=http://moto:5000
      # Point Spark S3 at Moto
      - SPARK_CONF_spark.hadoop.fs.s3a.endpoint=http://moto:5000
      - SPARK_CONF_spark.hadoop.fs.s3a.access.key=test
      - SPARK_CONF_spark.hadoop.fs.s3a.secret.key=test
      - SPARK_CONF_spark.hadoop.fs.s3a.path.style.access=true
      - SPARK_CONF_spark.hadoop.fs.s3a.impl=org.apache.hadoop.fs.s3a.S3AFileSystem
      - SPARK_CONF_spark.hadoop.fs.s3a.aws.credentials.provider=org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider
    depends_on:
      - moto
    entrypoint: ["tail", "-f", "/dev/null"]

  trino:
    image: trinodb/trino
    ports:
      - "8080:8080"
    volumes:
      - ./trino-config:/etc/trino
    depends_on:
      - moto
```

---

### 2. Trino Config

**`trino-config/config.properties`**
```properties
coordinator=true
node-scheduler.include-coordinator=true
http-server.http.port=8080
discovery.uri=http://localhost:8080
```

**`trino-config/jvm.config`**
```
-server
-Xmx2G
-XX:+UseG1GC
-XX:G1HeapRegionSize=32M
-XX:+ExplicitGCInvokesConcurrent
-XX:+HeapDumpOnOutOfMemoryError
-XX:+ExitOnOutOfMemoryError
```

**`trino-config/node.properties`**
```properties
node.environment=local
node.id=local-node
node.data-dir=/data/trino
```

**`trino-config/catalog/glue.properties`**
```properties
connector.name=hive
# Point metastore at Moto's Glue Catalog API
hive.metastore=glue
hive.metastore.glue.region=us-east-1
hive.metastore.glue.endpoint-url=http://moto:5000
hive.metastore.glue.aws-access-key=test
hive.metastore.glue.aws-secret-key=test
# Point S3 reads at Moto
hive.s3.endpoint=http://moto:5000
hive.s3.aws-access-key=test
hive.s3.aws-secret-key=test
hive.s3.path-style-access=true
hive.s3.ssl.enabled=false
hive.non-managed-table-writes-enabled=true
```

---

### 3. Sample Data

**`data/customers/customers.json`**
```json
{"customer_id": "C001", "name": "Alice Smith", "email": "alice@example.com", "country": "US"}
{"customer_id": "C002", "name": "Bob Jones", "email": "bob@example.com", "country": "UK"}
{"customer_id": "C003", "name": "Carol White", "email": "carol@example.com", "country": "US"}
```

**`data/orders/orders.json`**
```json
{"order_id": "O001", "customer_id": "C001", "product": "Widget A", "amount": 100.00, "order_date": "2024-01-01"}
{"order_id": "O002", "customer_id": "C002", "product": "Widget B", "amount": 200.00, "order_date": "2024-01-02"}
{"order_id": "O003", "customer_id": "C001", "product": "Widget C", "amount": 150.00, "order_date": "2024-01-03"}
{"order_id": "O004", "customer_id": "C003", "product": "Widget A", "amount": 100.00, "order_date": "2024-01-04"}
```

---

### 4. Glue Job 1 — Ingest JSON from S3 → Glue Catalog

**`glue-jobs/01_ingest_to_catalog.py`**

```python
"""
Glue Job 1:
  - Reads JSON files from mock S3 (Moto)
  - Converts to Parquet and writes back to mock S3
  - Registers customers and orders tables in Glue Catalog (via Moto)
"""

import boto3
from awsglue.context import GlueContext
from awsglue.transforms import ApplyMapping
from pyspark.context import SparkContext
from pyspark import SparkConf

# ── Spark + Glue init ─────────────────────────────────────────────────────────
conf = SparkConf()
conf.set("spark.hadoop.fs.s3a.endpoint",                          "http://moto:5000")
conf.set("spark.hadoop.fs.s3a.access.key",                        "test")
conf.set("spark.hadoop.fs.s3a.secret.key",                        "test")
conf.set("spark.hadoop.fs.s3a.path.style.access",                 "true")
conf.set("spark.hadoop.fs.s3a.impl",                              "org.apache.hadoop.fs.s3a.S3AFileSystem")
conf.set("spark.hadoop.fs.s3a.aws.credentials.provider",          "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider")

sc = SparkContext(conf=conf)
glueContext = GlueContext(sc)
spark = glueContext.spark_session
logger = glueContext.get_logger()

# ── Config ────────────────────────────────────────────────────────────────────
BUCKET   = "glue-bucket"
DATABASE = "sales_db"
AWS_CREDS = dict(
    aws_access_key_id="test",
    aws_secret_access_key="test",
    region_name="us-east-1",
    endpoint_url="http://moto:5000",
)

TABLES = {
    "customers": {
        "input_path":  f"s3a://{BUCKET}/raw/customers/",
        "output_path": f"s3a://{BUCKET}/warehouse/customers/",
        "mapping": [
            ("customer_id", "string", "customer_id", "string"),
            ("name",        "string", "name",        "string"),
            ("email",       "string", "email",       "string"),
            ("country",     "string", "country",     "string"),
        ],
    },
    "orders": {
        "input_path":  f"s3a://{BUCKET}/raw/orders/",
        "output_path": f"s3a://{BUCKET}/warehouse/orders/",
        "mapping": [
            ("order_id",    "string", "order_id",    "string"),
            ("customer_id", "string", "customer_id", "string"),
            ("product",     "string", "product",     "string"),
            ("amount",      "double", "amount",      "double"),
            ("order_date",  "string", "order_date",  "string"),
        ],
    },
}

# ── Setup S3 bucket and upload raw JSON ──────────────────────────────────────
s3 = boto3.client("s3", **AWS_CREDS)

try:
    s3.create_bucket(Bucket=BUCKET)
    logger.info(f"Created bucket: {BUCKET}")
except Exception:
    pass

# Upload local JSON files into mock S3 raw zone
import os
for table_name in TABLES:
    local_dir = f"/home/hadoop/data/{table_name}/"
    for filename in os.listdir(local_dir):
        if filename.endswith(".json"):
            local_path = os.path.join(local_dir, filename)
            s3_key = f"raw/{table_name}/{filename}"
            s3.upload_file(local_path, BUCKET, s3_key)
            logger.info(f"Uploaded {local_path} → s3://{BUCKET}/{s3_key}")

# ── Create Glue database ──────────────────────────────────────────────────────
glue_client = boto3.client("glue", **AWS_CREDS)

try:
    glue_client.create_database(
        DatabaseInput={"Name": DATABASE, "Description": "Local sales database"}
    )
    logger.info(f"Created Glue database: {DATABASE}")
except glue_client.exceptions.AlreadyExistsException:
    logger.info(f"Database {DATABASE} already exists")

# ── Ingest each table ─────────────────────────────────────────────────────────
def ingest_table(table_name: str, config: dict):
    logger.info(f"\nIngesting {table_name}...")

    # Read JSON from mock S3
    dyf = glueContext.create_dynamic_frame.from_options(
        connection_type="s3",
        connection_options={"paths": [config["input_path"]]},
        format="json",
        transformation_ctx=f"read_{table_name}",
    )
    logger.info(f"  Read {dyf.count()} records")

    # Apply explicit schema mapping
    dyf = ApplyMapping.apply(
        frame=dyf,
        mappings=config["mapping"],
        transformation_ctx=f"map_{table_name}",
    )

    # Write Parquet to mock S3 warehouse zone
    glueContext.write_dynamic_frame.from_options(
        frame=dyf,
        connection_type="s3",
        connection_options={"path": config["output_path"]},
        format="parquet",
        transformation_ctx=f"write_{table_name}",
    )
    logger.info(f"  Written Parquet to {config['output_path']}")

    # Register table in Glue Catalog
    columns = [
        {"Name": src_name, "Type": dst_type}
        for src_name, _, _, dst_type in config["mapping"]
    ]

    table_input = {
        "Name": table_name,
        "StorageDescriptor": {
            "Columns": columns,
            "Location": config["output_path"].replace("s3a://", "s3://"),
            "InputFormat":  "org.apache.hadoop.mapred.TextInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
            "SerdeInfo": {
                "SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
            },
        },
        "TableType": "EXTERNAL_TABLE",
        "Parameters": {"classification": "parquet"},
    }

    try:
        glue_client.create_table(DatabaseName=DATABASE, TableInput=table_input)
        logger.info(f"  Registered {DATABASE}.{table_name} in Glue Catalog")
    except glue_client.exceptions.AlreadyExistsException:
        glue_client.update_table(DatabaseName=DATABASE, TableInput=table_input)
        logger.info(f"  Updated {DATABASE}.{table_name} in Glue Catalog")

for table_name, config in TABLES.items():
    ingest_table(table_name, config)

logger.info("\n✅ Job 1 complete")
sc.stop()
```

---

### 5. Glue Job 2 — Join → Write to Glue Catalog

**`glue-jobs/02_join_and_write.py`**

```python
"""
Glue Job 2:
  - Reads customers + orders from Glue Catalog (via Moto)
  - Joins them on customer_id using Spark
  - Writes result Parquet to mock S3
  - Registers customer_orders table in Glue Catalog
  - Trino (Athena locally) can immediately query this table
"""

import boto3
from awsglue.context import GlueContext
from awsglue.transforms import Join
from pyspark.context import SparkContext
from pyspark import SparkConf

# ── Spark + Glue init ─────────────────────────────────────────────────────────
conf = SparkConf()
conf.set("spark.hadoop.fs.s3a.endpoint",                 "http://moto:5000")
conf.set("spark.hadoop.fs.s3a.access.key",               "test")
conf.set("spark.hadoop.fs.s3a.secret.key",               "test")
conf.set("spark.hadoop.fs.s3a.path.style.access",        "true")
conf.set("spark.hadoop.fs.s3a.impl",                     "org.apache.hadoop.fs.s3a.S3AFileSystem")
conf.set("spark.hadoop.fs.s3a.aws.credentials.provider", "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider")

sc = SparkContext(conf=conf)
glueContext = GlueContext(sc)
spark = glueContext.spark_session
logger = glueContext.get_logger()

# ── Config ────────────────────────────────────────────────────────────────────
BUCKET       = "glue-bucket"
DATABASE     = "sales_db"
OUTPUT_TABLE = "customer_orders"
OUTPUT_PATH  = f"s3a://{BUCKET}/warehouse/customer_orders/"

AWS_CREDS = dict(
    aws_access_key_id="test",
    aws_secret_access_key="test",
    region_name="us-east-1",
    endpoint_url="http://moto:5000",
)

glue_client = boto3.client("glue", **AWS_CREDS)

# ── Read from Glue Catalog ────────────────────────────────────────────────────
logger.info("Reading from Glue Catalog...")

customers_dyf = glueContext.create_dynamic_frame.from_catalog(
    database=DATABASE,
    table_name="customers",
    transformation_ctx="read_customers",
)

orders_dyf = glueContext.create_dynamic_frame.from_catalog(
    database=DATABASE,
    table_name="orders",
    transformation_ctx="read_orders",
)

logger.info(f"  Customers: {customers_dyf.count()} rows")
logger.info(f"  Orders:    {orders_dyf.count()} rows")

# ── Join using native Spark (gives full SparkContext control) ─────────────────
customers_df = customers_dyf.toDF()
orders_df    = orders_dyf.toDF()

# Rename to avoid ambiguous column names after join
customers_df = customers_df.withColumnRenamed("customer_id", "cust_id")

joined_df = orders_df.join(
    customers_df,
    orders_df["customer_id"] == customers_df["cust_id"],
    how="inner"
).drop("cust_id")

# Select and order final columns cleanly
from pyspark.sql.functions import col
result_df = joined_df.select(
    col("order_id"),
    col("customer_id"),
    col("name").alias("customer_name"),
    col("email"),
    col("country"),
    col("product"),
    col("amount"),
    col("order_date"),
)

logger.info(f"  Joined result: {result_df.count()} rows")
result_df.printSchema()
result_df.show()

# ── Write Parquet to mock S3 ──────────────────────────────────────────────────
logger.info(f"Writing to {OUTPUT_PATH}...")
result_df.write.mode("overwrite").parquet(OUTPUT_PATH)
logger.info("  Write complete")

# ── Register result in Glue Catalog ──────────────────────────────────────────
columns = [
    {"Name": field.name, "Type": field.dataType.simpleString()}
    for field in result_df.schema.fields
]

table_input = {
    "Name": OUTPUT_TABLE,
    "StorageDescriptor": {
        "Columns": columns,
        "Location": OUTPUT_PATH.replace("s3a://", "s3://"),
        "InputFormat":  "org.apache.hadoop.mapred.TextInputFormat",
        "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
        "SerdeInfo": {
            "SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
        },
    },
    "TableType": "EXTERNAL_TABLE",
    "Parameters": {"classification": "parquet"},
}

try:
    glue_client.create_table(DatabaseName=DATABASE, TableInput=table_input)
    logger.info(f"Registered {DATABASE}.{OUTPUT_TABLE} in Glue Catalog")
except glue_client.exceptions.AlreadyExistsException:
    glue_client.update_table(DatabaseName=DATABASE, TableInput=table_input)
    logger.info(f"Updated {DATABASE}.{OUTPUT_TABLE} in Glue Catalog")

logger.info("\n✅ Job 2 complete — customer_orders ready for Athena/Trino queries")
sc.stop()
```

---
### 6. `app/run_pipeline.py`
```python
"""
Orchestrates Glue jobs then queries results via Trino (local Athena).
"""

import subprocess
import time
import trino
import pandas as pd

def run_glue_job(job_file: str):
    print(f"\n{'='*60}\nRunning: {job_file}\n{'='*60}")
    result = subprocess.run([
        "docker", "exec", "glue-athena-local-glue-1",
        "spark-submit",
        "--master", "local[*]",
        f"/home/hadoop/jobs/{job_file}",
    ])
    if result.returncode != 0:
        raise RuntimeError(f"{job_file} failed")
    print(f"✅ {job_file} done")

def query(sql: str, label: str):
    print(f"\n── {label} ──")
    conn = trino.dbapi.connect(
        host="localhost",
        port=8080,
        user="admin",
        catalog="glue",
        schema="sales_db",
    )
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    print(df.to_string(index=False))
    return df

# ── Run Glue jobs ─────────────────────────────────────────────────────────────
run_glue_job("01_ingest_to_catalog.py")
run_glue_job("02_join_and_write.py")

# Give Trino a moment to reflect catalog changes
time.sleep(3)

# ── Query via Athena (Trino) ──────────────────────────────────────────────────
query(
    "SELECT * FROM glue.sales_db.customer_orders ORDER BY order_date",
    "All orders with customer details"
)

query(
    """
    SELECT customer_name, country,
           COUNT(*)    AS orders,
           SUM(amount) AS total_spent
    FROM glue.sales_db.customer_orders
    GROUP BY customer_name, country
    ORDER BY total_spent DESC
    """,
    "Spend by customer"
)

query(
    """
    SELECT country, SUM(amount) AS revenue
    FROM glue.sales_db.customer_orders
    GROUP BY country
    ORDER BY revenue DESC
    """,
    "Revenue by country"
)
```

---

### 7. `app/requirements.txt`

```
boto3
trino
pandas
```

---

### Running It

```bash
docker-compose up -d
sleep 30  # wait for Trino to initialize

cd app
pip install -r requirements.txt
python run_pipeline.py
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