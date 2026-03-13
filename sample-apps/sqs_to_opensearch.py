"""
Demo: push a message to SQS (Moto), retrieve it, and index it into OpenSearch.

Usage:
  python sample-apps/sqs_to_opensearch.py
  python sample-apps/sqs_to_opensearch.py --message '{"event":"signup","user":"alice"}'
  python sample-apps/sqs_to_opensearch.py --sqs-endpoint http://localhost:5000 \
        --opensearch-url http://localhost:9200 --index events
"""

import argparse
import json
import uuid
from datetime import datetime, timezone

import boto3
from opensearchpy import OpenSearch


QUEUE_NAME = "demo-queue"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send a message through SQS and index it in OpenSearch.",
    )
    parser.add_argument(
        "--message",
        default='{"event": "order_placed", "customer": "Jane Doe", "amount": 99.95}',
        help="JSON message body to send (default: sample order event)",
    )
    parser.add_argument(
        "--sqs-endpoint",
        default="http://localhost:5000",
        help="SQS endpoint URL (Moto)",
    )
    parser.add_argument(
        "--opensearch-url",
        default="http://localhost:9200",
        help="OpenSearch base URL",
    )
    parser.add_argument("--index", default="events", help="OpenSearch index name")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--access-key", default="test", help="AWS access key")
    parser.add_argument("--secret-key", default="test", help="AWS secret key")
    return parser.parse_args()


def get_or_create_queue(sqs_client, queue_name: str) -> str:
    """Return the queue URL, creating the queue if it does not exist."""
    try:
        resp = sqs_client.get_queue_url(QueueName=queue_name)
        return resp["QueueUrl"]
    except sqs_client.exceptions.QueueDoesNotExist:
        resp = sqs_client.create_queue(QueueName=queue_name)
        return resp["QueueUrl"]


def send_message(sqs_client, queue_url: str, body: str) -> str:
    """Send a message to SQS and return the message ID."""
    resp = sqs_client.send_message(QueueUrl=queue_url, MessageBody=body)
    return resp["MessageId"]


def receive_message(sqs_client, queue_url: str) -> dict | None:
    """Receive and delete one message from SQS. Returns the message or None."""
    resp = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=5,
    )
    messages = resp.get("Messages", [])
    if not messages:
        return None
    msg = messages[0]
    sqs_client.delete_message(
        QueueUrl=queue_url,
        ReceiptHandle=msg["ReceiptHandle"],
    )
    return msg


def index_to_opensearch(os_client: OpenSearch, index: str, document: dict) -> dict:
    """Create the index (if needed) and index a document."""
    if not os_client.indices.exists(index=index):
        os_client.indices.create(
            index=index,
            body={"settings": {"number_of_shards": 1, "number_of_replicas": 0}},
        )
    return os_client.index(
        index=index,
        id=str(uuid.uuid4()),
        body=document,
        refresh="wait_for",
    )


def main() -> None:
    args = parse_args()

    # ── SQS client (Moto) ────────────────────────────────────────────────────
    sqs = boto3.client(
        "sqs",
        endpoint_url=args.sqs_endpoint,
        region_name=args.region,
        aws_access_key_id=args.access_key,
        aws_secret_access_key=args.secret_key,
    )

    # ── OpenSearch client ─────────────────────────────────────────────────────
    os_client = OpenSearch(
        hosts=[args.opensearch_url],
        use_ssl=False,
        verify_certs=False,
    )

    # 1. Create / get queue
    queue_url = get_or_create_queue(sqs, QUEUE_NAME)
    print(f"Queue URL: {queue_url}")

    # 2. Send message
    message_id = send_message(sqs, queue_url, args.message)
    print(f"Sent message {message_id}")

    # 3. Receive message
    msg = receive_message(sqs, queue_url)
    if msg is None:
        print("No message received – aborting.")
        return
    print(f"Received message {msg['MessageId']}")

    # 4. Build document and index into OpenSearch
    try:
        body = json.loads(msg["Body"])
    except json.JSONDecodeError:
        body = {"raw": msg["Body"]}

    document = {
        "sqs_message_id": msg["MessageId"],
        "body": body,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
    result = index_to_opensearch(os_client, args.index, document)
    print(f"Indexed to OpenSearch: index={args.index}  _id={result['_id']}")

    # 5. Verify by searching
    search = os_client.search(
        index=args.index,
        body={"query": {"match_all": {}}},
    )
    hits = search["hits"]["hits"]
    print(f"\nDocuments in '{args.index}' index ({len(hits)} total):")
    for hit in hits:
        print(f"  {hit['_id']}: {json.dumps(hit['_source'], indent=2)}")


if __name__ == "__main__":
    main()
