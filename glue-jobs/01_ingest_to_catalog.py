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
