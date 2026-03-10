"""
Reusable query helpers for local Glue and Athena emulators.
"""

import time
from typing import List, Sequence, Tuple

import boto3
import trino


def run_trino_query(
    sql: str,
    host: str = "localhost",
    port: int = 8080,
    user: str = "admin",
    catalog: str = "glue",
    schema: str = "sales_db",
) -> Tuple[List[str], List[Tuple]]:
    """Run SQL through Trino and return column names and rows."""
    conn = trino.dbapi.connect(
        host=host,
        port=port,
        user=user,
        catalog=catalog,
        schema=schema,
    )
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    return cols, rows


def run_athena_query(
    sql: str,
    database: str = "sales_db",
    output_location: str = "s3://glue-bucket/athena-results/",
    endpoint_url: str = "http://localhost:5000",
    region_name: str = "us-east-1",
    aws_access_key_id: str = "test",
    aws_secret_access_key: str = "test",
    poll_seconds: float = 1.0,
    timeout_seconds: int = 60,
) -> Tuple[List[str], List[Tuple[str, ...]]]:
    """Run SQL through Athena API and return column names and rows."""
    client = boto3.client(
        "athena",
        endpoint_url=endpoint_url,
        region_name=region_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )

    response = client.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": database},
        ResultConfiguration={"OutputLocation": output_location},
    )

    execution_id = response["QueryExecutionId"]
    started = time.time()

    while True:
        status_response = client.get_query_execution(QueryExecutionId=execution_id)
        state = status_response["QueryExecution"]["Status"]["State"]

        if state == "SUCCEEDED":
            break
        if state in {"FAILED", "CANCELLED"}:
            reason = status_response["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {state}: {reason}")
        if time.time() - started > timeout_seconds:
            raise TimeoutError(f"Athena query timed out after {timeout_seconds}s")

        time.sleep(poll_seconds)

    paginator = client.get_paginator("get_query_results")
    cols: List[str] = []
    rows: List[Tuple[str, ...]] = []
    is_first_row = True

    for page in paginator.paginate(QueryExecutionId=execution_id):
        result_set = page["ResultSet"]
        if not cols:
            cols = [c["Name"] for c in result_set["ResultSetMetadata"]["ColumnInfo"]]

        for row in result_set["Rows"]:
            values = tuple(item.get("VarCharValue", "") for item in row.get("Data", []))
            # Athena includes a header row in results.
            if is_first_row:
                is_first_row = False
                continue
            rows.append(values)

    return cols, rows


def print_rows_stdout(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    """Print query results as tab-separated output."""
    print("\t".join(str(c) for c in columns))
    for row in rows:
        print("\t".join("" if value is None else str(value) for value in row))
