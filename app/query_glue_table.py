"""
Query Glue tables via Trino using a SQL SELECT statement.

Usage:
  python query_glue_table.py "SELECT * FROM glue.sales_db.customer_orders"
"""

import argparse

from query_runner import print_rows_stdout, run_trino_query


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a SQL SELECT query against Glue tables via Trino.",
    )
    parser.add_argument("sql", help="SQL SELECT statement to execute")
    parser.add_argument("--host", default="localhost", help="Trino host")
    parser.add_argument("--port", type=int, default=8080, help="Trino port")
    parser.add_argument("--user", default="admin", help="Trino user")
    parser.add_argument("--catalog", default="glue", help="Trino catalog")
    parser.add_argument("--schema", default="sales_db", help="Trino schema")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    columns, rows = run_trino_query(
        sql=args.sql,
        host=args.host,
        port=args.port,
        user=args.user,
        catalog=args.catalog,
        schema=args.schema,
    )
    print_rows_stdout(columns, rows)


if __name__ == "__main__":
    main()
