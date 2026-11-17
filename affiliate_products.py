"""
選品模組（公開示範版）

提供 prompts_smartcat.py 與 recovery.py 需要的兩個函式：
  - get_product_from_weekly(day_offset=0) -> dict
  - build_description(product, extra_tags=None) -> str

這裡內建的是虛構的示範產品，沒有真實商品連結或聯盟代碼。
要換成自己的選品，建立 config/products.json，格式如下：

  {"products": [
     {"name": "...", "category": "litter_box", "key_feature": "...",
      "color": "...", "size": "...", "link": "https://..."}
  ]}

category 可用：litter_box、smart_feeder、water_fountain、pet_camera、gps_tracker、smart_pet
"""

import datetime
import json
from pathlib import Path

PRODUCTS_FILE = Path(__file__).parent / "config" / "products.json"

DEMO_PRODUCTS = [
    {
        "name": "Demo Self-Cleaning Litter Box",
        "category": "litter_box",
        "key_feature": "rotating drum that sifts litter automatically after each visit",
        "color": "matte white",
        "size": "large",
    },
    {
        "name": "Demo Smart Feeder with Portion Control",
        "category": "smart_feeder",
        "key_feature": "app-scheduled meals with precise portion sizes",
        "color": "silver",
        "size": "compact",
    },
    {
        "name": "Demo Quiet Water Fountain",
        "category": "water_fountain",
        "key_feature": "triple filtration with a near-silent pump",
        "color": "frosted blue",
        "size": "medium",
    },
    {
        "name": "Demo Pet Camera with Treat Toss",
        "category": "pet_camera",
        "key_feature": "two-way audio and remote treat tossing",
        "color": "charcoal",
        "size": "compact",
    },
    {
        "name": "Demo GPS Cat Collar",
        "category": "gps_tracker",
        "key_feature": "real-time location tracking with safe-zone alerts",
        "color": "orange",
        "size": "lightweight",
    },
    {
        "name": "Demo Interactive Laser Toy",
        "category": "smart_pet",
        "key_feature": "random laser patterns that keep cats moving",
        "color": "white",
        "size": "palm-sized",
    },
]


def _load_products() -> list:
    """優先讀 config/products.json，沒有或格式不對就用內建示範產品。"""
    if PRODUCTS_FILE.exists():
        try:
            products = json.loads(PRODUCTS_FILE.read_text("utf-8")).get("products", [])
            if products:
                return products
        except (OSError, ValueError, AttributeError):
            pass
    return DEMO_PRODUCTS


def get_product_from_weekly(day_offset: int = 0) -> dict:
    """依日期輪替選一個產品；day_offset 為負數代表過去的日期。"""
    products = _load_products()
    day_index = datetime.datetime.now().timetuple().tm_yday + day_offset
    return dict(products[day_index % len(products)])


def build_description(product: dict, extra_tags: list = None) -> str:
    """產生影片說明文字：產品名稱、連結（有的話）與 hashtag。"""
    tags = ["SmartCatLife", "PetTech", "CatGadgets", "SmartPet", "Shorts"]
    if extra_tags:
        tags = list(dict.fromkeys(tags + list(extra_tags)))
    hashtags = " ".join(f"#{t}" for t in tags)

    lines = ["🤖 AI-generated video.", "", f"🛒 {product.get('name', 'Smart cat gadget')}"]
    if product.get("link"):
        lines.append(product["link"])
    lines += ["", hashtags]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    p = get_product_from_weekly()
    print(f"今日選品: {p['name']}（{p.get('category', '?')}）")
    print(build_description(p))
