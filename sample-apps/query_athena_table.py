"""
Query Athena tables via Athena API using a SQL SELECT statement.

Usage:
  python query_athena_table.py "SELECT * FROM customer_orders"
"""

import argparse

from query_utils import print_rows_stdout, run_athena_query


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a SQL SELECT query against Athena tables.",
    )
    parser.add_argument("sql", help="SQL SELECT statement to execute")
    parser.add_argument("--database", default="sales_db", help="Athena database")
    parser.add_argument(
        "--output-location",
        default="s3://glue-bucket/athena-results/",
        help="S3 output location for Athena query results",
    )
    parser.add_argument(
        "--endpoint-url",
        default="http://localhost:5000",
        help="Athena endpoint URL",
    )
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--access-key", default="test", help="AWS access key")
    parser.add_argument("--secret-key", default="test", help="AWS secret key")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=60,
        help="Maximum time to wait for query completion",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    columns, rows = run_athena_query(
        sql=args.sql,
        database=args.database,
        output_location=args.output_location,
        endpoint_url=args.endpoint_url,
        region_name=args.region,
        aws_access_key_id=args.access_key,
        aws_secret_access_key=args.secret_key,
        timeout_seconds=args.timeout_seconds,
    )
    print_rows_stdout(columns, rows)


if __name__ == "__main__":
    main()
