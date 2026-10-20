import json
import os
import sys
import urllib.request


SHOP = "ad1ec2-pb.myshopify.com"
API_VERSION = "2026-07"


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
    query = """
    query($search: String!) {
      taxonomy {
        categories(first: 20, search: $search) {
          nodes {
            id
            name
            fullName
            isLeaf
          }
        }
      }
    }
    """
    for term in sys.argv[1:]:
        print("TERM", term)
        print(json.dumps(graphql(query, {"search": term}), indent=2))


if __name__ == "__main__":
    main()
