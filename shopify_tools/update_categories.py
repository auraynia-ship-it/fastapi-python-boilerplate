import json
import os
import urllib.request
from pathlib import Path

from .upload_products import product_type_and_template
from .product_doc import PRODUCTS


SHOP = "ad1ec2-pb.myshopify.com"
API_VERSION = "2026-07"
STATE_PATH = Path("New/shopify_upload_state.json")

CATEGORY_BY_TYPE = {
    "Necklaces": "gid://shopify/TaxonomyCategory/aa-6-8",
    "Bracelets": "gid://shopify/TaxonomyCategory/aa-6-3",
    "Earrings": "gid://shopify/TaxonomyCategory/aa-6-6",
    "Rings": "gid://shopify/TaxonomyCategory/aa-6-9",
}


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
    mutation = """
    mutation($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id title category { id fullName } }
        userErrors { field message }
      }
    }
    """
    for product in PRODUCTS:
        folder, title, _visual, _accent, jtype, _design, _closure, _qty = product
        rest_id = state["products"][str(folder)]["id"]
        product_type, _template = product_type_and_template(jtype)
        category_id = CATEGORY_BY_TYPE[product_type]
        variables = {"input": {"id": f"gid://shopify/Product/{rest_id}", "category": category_id}}
        result = graphql(mutation, variables)
        errors = result.get("data", {}).get("productUpdate", {}).get("userErrors", [])
        if errors:
            raise RuntimeError(f"Folder {folder} category update failed: {errors}")
        category = result["data"]["productUpdate"]["product"]["category"]["fullName"]
        print(f"UPDATED folder {folder}: {title} -> {category}")


if __name__ == "__main__":
    main()
