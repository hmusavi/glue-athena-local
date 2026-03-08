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
