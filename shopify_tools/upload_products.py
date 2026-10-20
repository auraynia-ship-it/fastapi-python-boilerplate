import argparse
import base64
import html
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .product_doc import PRODUCTS, product_copy


ROOT = Path("New")
STATE_PATH = ROOT / "shopify_upload_state.json"
API_VERSION = "2026-07"


def handle(title):
    value = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return value[:255]


def product_type_and_template(jewellery_type):
    t = jewellery_type.lower()
    if "necklace" in t:
        return "Necklaces", "necklace-products"
    if "earring" in t:
        return "Earrings", "earrings-product"
    if "ring" in t:
        return "Rings", "rings-product"
    return "Bracelets", "bracelet-product"


def description_html(title, visual, accent, jtype, design, closure, qty):
    desc, specs, outro = product_copy(title, visual, accent, jtype, design, closure, qty)
    parts = ['<h3>Description</h3>']
    for para in desc:
        parts.append(f"<p>{html.escape(para).replace(html.escape(title), f'<strong>{html.escape(title)}</strong>')}</p>")
    parts.append("<h3>Specifications</h3>")
    parts.append("<table><tbody>")
    for key, val in specs:
        parts.append(f"<tr><td><strong>{html.escape(key)}</strong></td><td>{html.escape(val)}</td></tr>")
    parts.append("</tbody></table>")
    parts.append("<h3>Care for Your Jewelry</h3>")
    parts.append(
        f"<p>To keep your <strong>{html.escape(title)}</strong> looking beautiful, store it in a soft pouch "
        "or jewellery box when not in use. Avoid direct contact with perfumes, lotions, cosmetics, harsh chemicals, "
        "and excessive moisture.</p>"
    )
    parts.append(
        "<p>After wearing, gently wipe the piece with a soft, dry cloth to remove any residue and maintain its "
        "polished appearance. Store it separately from other jewellery to help prevent scratches and tangling.</p>"
    )
    parts.append("<h3>Customer Satisfaction Guaranteed</h3>")
    parts.append(
        f"<p>We take pride in offering thoughtfully designed jewellery that adds elegance to your everyday style. "
        f"We want you to love your <strong>{html.escape(title)}</strong>, and our customer service team is always "
        "here to assist you with any questions or concerns.</p>"
    )
    parts.append(f"<h3>Order Your {html.escape(title)} Today!</h3>")
    parts.append(
        f"<p>Add this beautiful piece to your jewellery collection with the <strong>{html.escape(title)}</strong>. "
        "Its elegant design makes it versatile enough for everyday styling while adding a polished finish to "
        "special-occasion outfits.</p>"
    )
    parts.append(
        "<p>Whether you're treating yourself or looking for a meaningful gift, this jewellery piece is a beautiful "
        "choice. <strong>Add to Cart today and complete your look with effortless shine.</strong></p>"
    )
    parts.append(f"<h2>{html.escape(title)}: Effortless Everyday Elegance</h2>")
    for para in outro:
        parts.append(f"<p>{html.escape(para).replace(html.escape(title), f'<strong>{html.escape(title)}</strong>')}</p>")
    return "\n".join(parts)


def api_request(shop, token, method, path, payload=None):
    url = f"https://{shop}/admin/api/{API_VERSION}/{path}"
    data = None
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 or (500 <= exc.code < 600):
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {raw}") from exc
        except urllib.error.URLError:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def read_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"products": {}}


def write_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def image_files(folder_num):
    folder = ROOT / str(folder_num)
    return sorted(
        [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif"}],
        key=lambda p: p.name.lower(),
    )


def make_product_payload(product, price, compare_at_price, inventory, vendor, status):
    folder, title, visual, accent, jtype, design, closure, qty = product
    ptype, template = product_type_and_template(jtype)
    tags = ["Auraynia", ptype, design.split(" / ")[0], "18K Gold Tone"]
    return {
        "product": {
            "title": title,
            "body_html": description_html(title, visual, accent, jtype, design, closure, qty),
            "vendor": vendor,
            "product_type": ptype,
            "status": status.lower(),
            "handle": handle(title),
            "template_suffix": template,
            "tags": ", ".join(dict.fromkeys(tags)),
            "variants": [
                {
                    "price": str(price),
                    "compare_at_price": str(compare_at_price),
                    "inventory_management": "shopify",
                    "inventory_quantity": int(inventory),
                    "sku": f"AUR-{folder:03d}",
                    "taxable": True,
                    "requires_shipping": True,
                }
            ],
        }
    }


def upload_images(shop, token, product_id, folder_num, title):
    uploaded = []
    for idx, path in enumerate(image_files(folder_num), start=1):
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        ext = ".jpg" if mime == "image/jpeg" else path.suffix.lower()
        filename = f"{handle(title)}-{idx}{ext}"
        payload = {
            "image": {
                "attachment": base64.b64encode(path.read_bytes()).decode("ascii"),
                "filename": filename,
                "alt": title,
            }
        }
        result = api_request(shop, token, "POST", f"products/{product_id}/images.json", payload)
        uploaded.append(result["image"]["id"])
        time.sleep(0.5)
    return uploaded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop", required=True)
    parser.add_argument("--price", default="999")
    parser.add_argument("--compare-at-price", default="1999")
    parser.add_argument("--inventory", type=int, default=500)
    parser.add_argument("--vendor", default="Auraynia")
    parser.add_argument("--status", default="active", choices=["active", "draft"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set SHOPIFY_ACCESS_TOKEN before running.")

    shop = urllib.parse.urlparse(args.shop).netloc or args.shop
    shop = shop.strip("/")

    state = read_state()
    api_request(shop, token, "GET", "shop.json")

    for product in PRODUCTS:
        folder = str(product[0])
        title = product[1]
        if folder in state["products"]:
            print(f"SKIP folder {folder}: already uploaded product {state['products'][folder]['id']} - {title}")
            continue
        payload = make_product_payload(product, args.price, args.compare_at_price, args.inventory, args.vendor, args.status)
        imgs = image_files(product[0])
        print(f"{'DRY ' if args.dry_run else ''}CREATE folder {folder}: {title} ({len(imgs)} images)")
        if args.dry_run:
            continue
        created = api_request(shop, token, "POST", "products.json", payload)
        product_id = created["product"]["id"]
        uploaded_images = upload_images(shop, token, product_id, product[0], title)
        state["products"][folder] = {"id": product_id, "title": title, "images": uploaded_images}
        write_state(state)
        time.sleep(0.5)

    print(f"Done. State: {STATE_PATH.resolve()}")


if __name__ == "__main__":
    main()
