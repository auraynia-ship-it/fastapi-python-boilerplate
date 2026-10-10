"""Send a signed sample Shopify orders/create webhook to the deployed API.

Set SHOPIFY_CLIENT_SECRET in the environment before running this script.
The secret is used locally to compute the HMAC and is never sent to the API.
Use --meta-test with META_CAPI_TEST_EVENT_CODE for one Meta Test Events send.
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone


WEBHOOK_URL = (
    "https://fastapi-python-boilerplate-rho-roan.vercel.app"
    "/webhooks/shopify/orders-create"
)

PAYLOAD = {
    "id": 9876543210123,
    "admin_graphql_api_id": "gid://shopify/Order/9876543210123",
    "order_number": 990001,
    "name": "#990001",
    "created_at": None,
    "currency": "INR",
    "total_price": "1538.00",
    "subtotal_price": "1538.00",
    "total_tax": "0.00",
    "financial_status": "pending",
    "test": True,
    "payment_gateway_names": ["Cash on Delivery (COD)"],
    "line_items": [
        {
            "product_id": 123456,
            "variant_id": 456789,
            "title": "Gold Bangle",
            "quantity": 1,
            "price": "1538.00",
        }
    ],
}


def main():
    meta_test_mode = "--meta-test" in sys.argv[1:]
    secret = os.getenv("SHOPIFY_CLIENT_SECRET")
    if not secret:
        raise SystemExit(
            "SHOPIFY_CLIENT_SECRET is not set. Set it in your environment and retry."
        )

    payload = dict(PAYLOAD)
    unique_order_id = 9876543000000 + (uuid.uuid4().int % 1000000000)
    payload["id"] = unique_order_id
    payload["admin_graphql_api_id"] = f"gid://shopify/Order/{unique_order_id}"
    payload["order_number"] = unique_order_id % 1000000
    payload["name"] = f"#{payload['order_number']}"
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "X-Shopify-Webhook-Id": f"manual-meta-test-{uuid.uuid4()}",
        "X-Shopify-Topic": "orders/create",
        "X-Shopify-Shop-Domain": "ad1ec2-pb.myshopify.com",
        "X-Shopify-Api-Version": "2026-01",
    }
    if meta_test_mode:
        test_event_code = os.getenv("META_CAPI_TEST_EVENT_CODE")
        if not test_event_code:
            raise SystemExit(
                "Set META_CAPI_TEST_EVENT_CODE to the Events Manager code before using --meta-test."
            )
        payload["test"] = False
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        headers["X-Meta-Test-Event-Code"] = test_event_code
    else:
        payload["created_at"] = datetime.now(timezone.utc).isoformat()

    # Sign precisely the bytes that will be sent in the HTTP request.
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("ascii")

    request = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={**headers, "X-Shopify-Hmac-Sha256": signature},
        method="POST",
    )

    try:
        print("Sending a Meta Test Events Purchase." if meta_test_mode else "Sending a Shopify webhook test (Meta skipped).")
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            print(f"HTTP {response.status}")
            print(response_body)
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        print(f"HTTP {error.code}")
        print(response_body)
        raise SystemExit(1) from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Request failed: {error.reason}") from error


if __name__ == "__main__":
    main()
