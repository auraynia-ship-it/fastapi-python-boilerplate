"""Send a signed sample Shopify orders/create webhook to the deployed API.

Set SHOPIFY_CLIENT_SECRET in the environment before running this script.
The secret is used locally to compute the HMAC and is never sent to the API.
"""

import base64
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request


WEBHOOK_URL = (
    "https://fastapi-python-boilerplate-rho-roan.vercel.app"
    "/webhooks/shopify/orders-create"
)

PAYLOAD = {
    "id": 123456789,
    "admin_graphql_api_id": "gid://shopify/Order/123456789",
    "order_number": 4675,
    "name": "#4675",
    "created_at": "2026-09-20T13:20:00+05:30",
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
    secret = os.getenv("SHOPIFY_CLIENT_SECRET")
    if not secret:
        raise SystemExit(
            "SHOPIFY_CLIENT_SECRET is not set. Set it in your environment and retry."
        )

    # Sign precisely the bytes that will be sent in the HTTP request.
    body = json.dumps(PAYLOAD, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("ascii")

    request = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={
            "Accept": "*/*",
            "Content-Type": "application/json",
            "X-Shopify-Hmac-Sha256": signature,
            "X-Shopify-Webhook-Id": "manual-test-delivery-001",
            "X-Shopify-Topic": "orders/create",
            "X-Shopify-Shop-Domain": "your-store.myshopify.com",
            "X-Shopify-Api-Version": "2026-10",
        },
        method="POST",
    )

    try:
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
