# Shopify `ORDERS_CREATE` → FastAPI Webhook
## Developer Handoff Document

**Project:** Auraynia / fastrr checkout  
**Phases covered:** Shopify order webhook ingestion and Meta CAPI implementation  
**Deployment status:** Code is ready; production environment configuration,
database migration, and Meta Events Manager verification remain.

---

## 1. Objective

Implement a FastAPI endpoint that receives an order automatically whenever a new order is created in Shopify.

Expected flow:

```text
Customer
   ↓
fastrr Checkout
   ↓
fastrr exports/imports order
   ↓
Shopify creates order
   ↓
Shopify ORDERS_CREATE webhook
   ↓
FastAPI endpoint
   ↓
Receive and log Shopify order payload
```

Shopify pushes webhook event data to the configured endpoint when the event occurs. The application does not need to continuously poll Shopify for new orders.

## 2. Important concept

FastAPI does **not** call Shopify to ask for new orders. Shopify makes an HTTP `POST` request to FastAPI when the subscribed event occurs.

Example endpoint:

```http
POST https://api.example.com/webhooks/shopify/orders-create
```

The endpoint must be publicly reachable over HTTPS.

## 3. Requirements

- Public HTTPS endpoint accessible by Shopify.
- Endpoint accepts HTTP `POST` requests with a JSON body.
- Verify Shopify's webhook HMAC before processing in production.
- Store/deduplicate webhook delivery IDs.
- Respond quickly after safely accepting the webhook.
- Log enough information to debug delivery and order processing.
- The Shopify-to-FastAPI flow was tested before Meta CAPI implementation.

Do not use `localhost` as the production destination; Shopify cannot reach a developer's local machine directly.

## 4. Basic FastAPI endpoint for initial testing

This example is for initial connectivity testing only. It is **not production-secure** because it does not verify the webhook signature.

```python
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/webhooks/shopify/orders-create")
async def shopify_orders_create(request: Request):
    payload = await request.json()

    print("SHOPIFY ORDER RECEIVED")
    print("Order ID:", payload.get("id"))
    print("Order number:", payload.get("order_number"))
    print("Name:", payload.get("name"))
    print("Total:", payload.get("total_price"))
    print("Currency:", payload.get("currency"))
    print("Payment gateways:", payload.get("payment_gateway_names"))

    # Initial phase: log/inspect the payload only.
    return {"status": "received"}
```

## 5. What Shopify sends

The webhook subscription does not require the developer to pass an order ID. When a new order is created, Shopify constructs the event payload and sends it to the configured endpoint.

The payload normally includes order fields such as identifiers, timestamps, currency, totals, line items, and payment gateway names. The exact fields depend on the webhook payload/version and the data Shopify makes available.

Example for illustration only:

```json
{
  "id": 123456789,
  "admin_graphql_api_id": "gid://shopify/Order/123456789",
  "order_number": 4675,
  "name": "#4675",
  "created_at": "2026-09-20T13:20:00+05:30",
  "currency": "INR",
  "total_price": "1000.00",
  "financial_status": "pending",
  "payment_gateway_names": ["Cash on Delivery (COD)"],
  "line_items": [
    {
      "product_id": 123456,
      "variant_id": 456789,
      "title": "Example product",
      "quantity": 1,
      "price": "1000.00"
    }
  ]
}
```

Do not assume this illustrative JSON exactly matches the live payload. Capture and inspect an actual test event.

If required information is absent, FastAPI can use the received order ID to call the Shopify Admin API for additional order data, subject to the app's scopes.

## 6. Create the Shopify webhook subscription

Use Shopify's Admin GraphQL API mutation `webhookSubscriptionCreate` with topic `ORDERS_CREATE`.

### Request

**Method:** `POST`

**Endpoint:**

```text
https://YOUR_STORE.myshopify.com/admin/api/YYYY-MM/graphql.json
```

Use a currently supported Shopify Admin API version for your app. Replace `YYYY-MM` with the version selected by the team; do not blindly copy an outdated version.

**Headers:**

```http
Content-Type: application/json
X-Shopify-Access-Token: YOUR_ADMIN_API_ACCESS_TOKEN
```

### GraphQL mutation

```graphql
mutation webhookSubscriptionCreate(
  $topic: WebhookSubscriptionTopic!,
  $webhookSubscription: WebhookSubscriptionInput!
) {
  webhookSubscriptionCreate(
    topic: $topic
    webhookSubscription: $webhookSubscription
  ) {
    webhookSubscription {
      id
      topic
      uri
    }
    userErrors {
      field
      message
    }
  }
}
```

### Variables

```json
{
  "topic": "ORDERS_CREATE",
  "webhookSubscription": {
    "uri": "https://api.example.com/webhooks/shopify/orders-create"
  }
}
```

### Complete cURL — Bash, Git Bash, Linux, or macOS

Replace the store domain, API version, access token, and destination URL with the real values. Never commit a real token to source control or share it in chat.

```bash
curl -X POST \
  "https://YOUR_STORE.myshopify.com/admin/api/YYYY-MM/graphql.json" \
  -H "Content-Type: application/json" \
  -H "X-Shopify-Access-Token: YOUR_ADMIN_API_ACCESS_TOKEN" \
  -d '{
    "query": "mutation webhookSubscriptionCreate($topic: WebhookSubscriptionTopic!, $webhookSubscription: WebhookSubscriptionInput!) { webhookSubscriptionCreate(topic: $topic, webhookSubscription: $webhookSubscription) { webhookSubscription { id topic uri } userErrors { field message } } }",
    "variables": {
      "topic": "ORDERS_CREATE",
      "webhookSubscription": {
        "uri": "https://api.example.com/webhooks/shopify/orders-create"
      }
    }
  }'
```

### Windows CMD note

The Bash cURL above uses single-quoted JSON, which is convenient in Bash/Git Bash but not directly portable to Windows CMD. For Windows, use PowerShell's `Invoke-RestMethod` with a JSON body, or adapt the quoting to CMD.

### Successful response

A successful response should include a subscription ID, topic `ORDERS_CREATE`, the destination URI, and an empty `userErrors` array:

```json
{
  "data": {
    "webhookSubscriptionCreate": {
      "webhookSubscription": {
        "id": "gid://shopify/WebhookSubscription/123456789",
        "topic": "ORDERS_CREATE",
        "uri": "https://api.example.com/webhooks/shopify/orders-create"
      },
      "userErrors": []
    }
  }
}
```

Check both GraphQL errors and `userErrors`; an HTTP 200 response alone does not guarantee the mutation succeeded.

## 7. App permissions and API version

Before creating the subscription, confirm:

- The Admin API access token belongs to the intended Shopify store and app.
- The app has the required permission to create/manage webhook subscriptions.
- The app has the required order-reading scope for any order data it needs to access or fetch separately.
- The app's configured webhook API version is supported and understood by the team.

The API version in the Admin GraphQL URL is not necessarily an independent setting for webhook delivery serialization. Verify the webhook API version configured for the app.

Use least-privilege scopes and follow Shopify's current app configuration requirements.

## 8. Production security: HMAC verification

The basic endpoint above is for testing only. In production, verify the `X-Shopify-Hmac-Sha256` header against the **raw request body** using the app's Shopify client secret.

```python
import base64
import hashlib
import hmac

def verify_shopify_hmac(
    raw_body: bytes,
    hmac_header: str,
    shopify_client_secret: str,
) -> bool:
    digest = hmac.new(
        shopify_client_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()

    calculated = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(calculated, hmac_header)
```

Example endpoint structure:

```python
import json
import os

from fastapi import FastAPI, Request, HTTPException

app = FastAPI()
SHOPIFY_CLIENT_SECRET = os.environ["SHOPIFY_CLIENT_SECRET"]

@app.post("/webhooks/shopify/orders-create")
async def shopify_orders_create(request: Request):
    raw_body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")

    if not hmac_header or not verify_shopify_hmac(
        raw_body,
        hmac_header,
        SHOPIFY_CLIENT_SECRET,
    ):
        raise HTTPException(status_code=401, detail="Invalid Shopify HMAC")

    payload = json.loads(raw_body)

    # TODO: deduplicate, persist, and enqueue processing.
    return {"status": "received"}
```

The secret used here is the Shopify app's **client secret** used for webhook HMAC validation, not the Admin API access token. Store it in environment variables or a secret manager.

## 9. Deduplication and reliable processing

Shopify may retry webhook deliveries. Do not assume each HTTP request is a unique order or unique event.

Use the `X-Shopify-Webhook-Id` header as a delivery identifier and store it with a unique constraint. For example:

```sql
CREATE TABLE shopify_webhook_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    webhook_id VARCHAR(255) NOT NULL UNIQUE,
    topic VARCHAR(100) NOT NULL,
    shop_domain VARCHAR(255),
    order_id VARCHAR(255),
    order_number VARCHAR(100),
    payload JSON NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'RECEIVED',
    received_at DATETIME NOT NULL,
    processed_at DATETIME NULL,
    error_message TEXT NULL
);
```

Recommended flow:

1. Read and validate the request signature.
2. Read `X-Shopify-Webhook-Id`, `X-Shopify-Topic`, and `X-Shopify-Shop-Domain`.
3. Persist the event and payload safely.
4. If the delivery ID already exists, avoid repeating processing.
5. Acknowledge quickly after durable acceptance.
6. Process downstream tasks asynchronously where appropriate.
7. Record failures and support safe retries.

Delivery-ID deduplication prevents processing the same delivery repeatedly. If business logic also needs to prevent multiple Purchase events for the same Shopify order, use a separate unique constraint/idempotency key based on the order ID and event purpose.

## 10. Recommended logging

Log operational metadata, not unnecessary sensitive customer details:

- Webhook delivery ID
- Topic
- Shop domain
- API version header
- Shopify order ID and order number
- Currency and total
- Payment gateway names
- Received timestamp
- Processing status and error details

Avoid logging full payloads containing customer addresses, emails, phone numbers, or other personal data in production unless there is a clear need and suitable access controls.

## 11. Test plan

### Test A — FastAPI endpoint

Before subscribing Shopify, test the endpoint using a dummy request:

```bash
curl -X POST \
  "https://api.example.com/webhooks/shopify/orders-create" \
  -H "Content-Type: application/json" \
  -d '{"test": true}'
```

This tests reachability only. Once HMAC verification is enabled, an unsigned dummy request should be rejected; use a test-only route or a properly signed fixture for further tests.

### Test B — Create subscription

Run the GraphQL cURL and confirm:

- `webhookSubscription` is returned.
- Topic is `ORDERS_CREATE`.
- URI matches the deployed FastAPI endpoint.
- `userErrors` is empty.
- There are no top-level GraphQL errors.

### Test C — fastrr-imported order

1. Place a suitable test order through fastrr.
2. Confirm the order appears in Shopify.
3. Confirm FastAPI receives an `orders/create` delivery.
4. Inspect the real payload and headers.
5. Verify order ID, total, currency, line items, and payment fields.
6. Repeat with COD and prepaid test orders if possible.

Do not assume the event is delivered only after every part of fastrr's export process has completed; verify the actual order creation behavior with a test.

## 12. Phase 1 scope — completed

Shopify `ORDERS_CREATE` ingestion has been verified with test orders. The endpoint
verifies the Shopify HMAC, stores the full webhook payload, deduplicates delivery
IDs, and records operational metadata without logging customer payloads.

The fastrr browser Purchase event has been disabled before enabling server-side
Purchase events.

## 13. Phase 2 — Meta CAPI integration

The production value rule confirmed by the team is:

```text
COD order value     → Meta Purchase value = order value × 0.60
Prepaid order value → Meta Purchase value = order value × 1.00
```

For example:

```text
Shopify order ₹1,000, COD     → Meta value ₹600
Shopify order ₹1,000, prepaid → Meta value ₹1,000
```

The actual Shopify order and invoice values must remain unchanged.

Prepaid gateways include PayU and Razorpay. COD is identified by the gateway name
containing COD / Cash on Delivery. Both COD and prepaid orders are sent on
`ORDERS_CREATE`, even when `financial_status` is pending. An `ORDERS_PAID`
subscription is not required for this launch. Use Shopify's `total_price` as the
starting value. Meta customer match identifiers are normalized and SHA-256 hashed
before sending.

## 14. Developer checklist

### Shopify → FastAPI

- [ ] Public HTTPS endpoint deployed
- [ ] Endpoint accepts POST
- [ ] Admin API token and required scopes confirmed
- [ ] `ORDERS_CREATE` subscription created
- [ ] Subscription response checked for GraphQL errors and `userErrors`
- [ ] Test fastrr order created/imported
- [ ] FastAPI receives the event
- [ ] Actual payload inspected
- [ ] COD and prepaid fields verified
- [ ] HMAC verification enabled
- [ ] Delivery ID deduplication implemented
- [ ] Durable storage/logging implemented
- [ ] Retries and failure handling tested

### Before Meta launch

- [ ] Confirm payment-method classification is reliable
- [ ] Confirm value/currency rules
- [x] Confirm fastrr's existing Purchase event is disabled
- [x] Implement Meta CAPI securely
- [x] Implement order-level idempotency and stable event IDs
- [ ] Test COD and prepaid end-to-end
- [ ] Verify Meta Events Manager reports the intended values
- [ ] Confirm there are no duplicate Purchase conversions

## 15. Official references

- Shopify webhook subscriptions: https://shopify.dev/docs/apps/build/webhooks/subscribe
- Shopify `webhookSubscriptionCreate`: https://shopify.dev/docs/api/admin-graphql/latest/mutations/webhooksubscriptioncreate
- Shopify webhook overview: https://shopify.dev/docs/apps/build/webhooks
