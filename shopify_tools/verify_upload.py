import json
import os
import urllib.request
from pathlib import Path

from .product_doc import PRODUCTS
from .upload_products import product_type_and_template, image_files


SHOP = "ad1ec2-pb.myshopify.com"
API_VERSION = "2026-07"
STATE_PATH = Path("New/shopify_upload_state.json")


def graphql(query, variables=None):
    token = os.environ["SHOPIFY_ACCESS_TOKEN"]
    req = urllib.request.Request(
        f"https://{SHOP}/admin/api/{API_VERSION}/graphql.json",
        data=json.dumps({"query": query, "variables": variables or {}}).encode("utf-8"),
        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    query = """
    query($id: ID!) {
      product(id: $id) {
        id
        legacyResourceId
        title
        vendor
        productType
        status
        templateSuffix
        category { fullName }
        media(first: 25) { nodes { ... on MediaImage { id image { url altText } } } }
        variants(first: 10) {
          nodes {
            sku
            price
            compareAtPrice
            inventoryQuantity
          }
        }
      }
    }
    """
    issues = []
    rows = []
    for product in PRODUCTS:
        folder, title, *_rest = product
        _folder, _title, _visual, _accent, jtype, _design, _closure, _qty = product
        expected_type, expected_template = product_type_and_template(jtype)
        expected_images = len(image_files(folder))
        product_id = state["products"].get(str(folder), {}).get("id")
        if not product_id:
            issues.append(f"Folder {folder}: missing from local upload state")
            continue
        result = graphql(query, {"id": f"gid://shopify/Product/{product_id}"})
        if result.get("errors"):
            issues.append(f"Folder {folder}: GraphQL errors {result['errors']}")
            continue
        p = result["data"]["product"]
        if not p:
            issues.append(f"Folder {folder}: product ID {product_id} not found")
            continue
        variant = p["variants"]["nodes"][0] if p["variants"]["nodes"] else {}
        image_count = len(p["media"]["nodes"])
        checks = {
            "title": p["title"] == title,
            "vendor": p["vendor"] == "Auraynia",
            "type": p["productType"] == expected_type,
            "status": p["status"] == "ACTIVE",
            "template": p["templateSuffix"] == expected_template,
            "price": variant.get("price") == "999.00",
            "compare": variant.get("compareAtPrice") == "1999.00",
            "inventory": variant.get("inventoryQuantity") == 500,
            "sku": variant.get("sku") == f"AUR-{folder:03d}",
            "images": image_count == expected_images,
        }
        if not all(checks.values()):
            issues.append(f"Folder {folder}: failed checks {', '.join(k for k,v in checks.items() if not v)}")
        rows.append(
            {
                "folder": folder,
                "id": product_id,
                "title": p["title"],
                "status": p["status"],
                "template": p["templateSuffix"],
                "category": (p["category"] or {}).get("fullName"),
                "images": image_count,
                "expected_images": expected_images,
            }
        )
    print(json.dumps({"checked": len(rows), "issues": issues, "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
