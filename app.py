#!/usr/bin/env python3
"""Local compliant dropship automation console.

The app intentionally works from authorized supplier feeds and marketplace
exports. It does not scrape marketplaces, bypass anti-bot controls, or submit
orders through unofficial channels.
"""

from __future__ import annotations

import csv
import html
import io
import json
import math
import mimetypes
import os
import re
import sqlite3
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "static"
DB_PATH = DATA_DIR / "resell_automation.db"
MEDIA_DIR = STATIC_DIR / "media"
APPROVED_IMAGES_PATH = DATA_DIR / "approved_images.csv"

DEFAULT_SETTINGS = {
    "douyin": {"fee_rate": 0.055, "ad_rate": 0.06, "return_rate": 0.08, "target_margin": 0.22, "min_profit": 6.0},
    "taobao": {"fee_rate": 0.050, "ad_rate": 0.04, "return_rate": 0.07, "target_margin": 0.20, "min_profit": 5.0},
    "xiaohongshu": {"fee_rate": 0.060, "ad_rate": 0.07, "return_rate": 0.10, "target_margin": 0.25, "min_profit": 8.0},
    "pinduoduo": {"fee_rate": 0.025, "ad_rate": 0.04, "return_rate": 0.08, "target_margin": 0.16, "min_profit": 4.0},
    "shopify_us": {"fee_rate": 0.065, "ad_rate": 0.22, "return_rate": 0.08, "target_margin": 0.20, "min_profit": 9.0},
}

PLATFORM_NAMES = {
    "douyin": "抖音",
    "taobao": "淘宝",
    "xiaohongshu": "小红书",
    "pinduoduo": "拼多多",
    "shopify_us": "Shopify US",
}

PRODUCT_FIELD_MAP = {
    "sku": "sku",
    "货号": "sku",
    "商品编码": "sku",
    "title": "title",
    "标题": "title",
    "商品标题": "title",
    "supplier": "supplier",
    "供应商": "supplier",
    "source_url": "source_url",
    "1688链接": "source_url",
    "货源链接": "source_url",
    "cost": "cost",
    "成本": "cost",
    "拿货价": "cost",
    "shipping_cost": "shipping_cost",
    "运费": "shipping_cost",
    "pack_cost": "pack_cost",
    "包装成本": "pack_cost",
    "stock": "stock",
    "库存": "stock",
    "lead_days": "lead_days",
    "发货天数": "lead_days",
    "category": "category",
    "类目": "category",
    "authorized": "authorized",
    "授权": "authorized",
    "invoice_available": "invoice_available",
    "可开发票": "invoice_available",
    "image_rights": "image_rights",
    "图片授权": "image_rights",
    "quality_checked": "quality_checked",
    "已验样": "quality_checked",
    "supplier_sla_hours": "supplier_sla_hours",
    "发货SLA小时": "supplier_sla_hours",
    "image_urls": "image_urls",
    "图片链接": "image_urls",
    "授权图片链接": "image_urls",
    "primary_image": "primary_image",
    "主图": "primary_image",
    "image_source": "image_source",
    "图片来源": "image_source",
    "image_license": "image_license",
    "图片许可": "image_license",
    "image_prompt": "image_prompt",
    "图片生成提示词": "image_prompt",
    "image_status": "image_status",
    "图片状态": "image_status",
    "target_platform": "target_platform",
    "目标平台": "target_platform",
    "market_price": "market_price",
    "平台参考价": "market_price",
    "竞品价": "market_price",
    "market_sales": "market_sales",
    "平台销量": "market_sales",
    "竞品销量": "market_sales",
    "competitor_url": "competitor_url",
    "竞品链接": "competitor_url",
    "test_budget": "test_budget",
    "测试预算": "test_budget",
    "notes": "notes",
    "备注": "notes",
    "material": "material",
    "材质": "material",
    "plating": "plating",
    "镀层": "plating",
    "size": "size",
    "尺寸": "size",
    "weight_g": "weight_g",
    "克重": "weight_g",
    "重量g": "weight_g",
    "hs_code": "hs_code",
    "海关编码": "hs_code",
    "country_of_origin": "country_of_origin",
    "原产国": "country_of_origin",
    "compliance_report_url": "compliance_report_url",
    "检测报告": "compliance_report_url",
    "product_story": "product_story",
    "产品故事": "product_story",
    "ad_angle": "ad_angle",
    "广告角度": "ad_angle",
    "content_status": "content_status",
    "素材状态": "content_status",
    "shopify_handle": "shopify_handle",
    "Shopify链接名": "shopify_handle",
    "shopify_tags": "shopify_tags",
    "Shopify标签": "shopify_tags",
}

ORDER_FIELD_MAP = {
    "platform": "platform",
    "平台": "platform",
    "order_id": "order_id",
    "订单号": "order_id",
    "sku": "sku",
    "货号": "sku",
    "qty": "qty",
    "数量": "qty",
    "paid_amount": "paid_amount",
    "实收金额": "paid_amount",
    "buyer_name": "buyer_name",
    "收件人": "buyer_name",
    "phone": "phone",
    "手机号": "phone",
    "address": "address",
    "地址": "address",
    "deadline": "deadline",
    "最晚发货时间": "deadline",
}

SENSITIVE_TERMS = [
    "药",
    "医疗",
    "医用",
    "械字号",
    "食品",
    "保健",
    "奶粉",
    "婴幼儿",
    "化妆品",
    "美白",
    "祛斑",
    "减肥",
    "杀菌",
    "消毒",
    "3c",
    "充电宝",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def boolish(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if value is None:
        return 0
    text = str(value).strip().lower()
    return int(text in {"1", "true", "yes", "y", "是", "有", "已", "已确认", "授权", "ok"})


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return default


def normalize_platform(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "抖音": "douyin",
        "抖店": "douyin",
        "douyin": "douyin",
        "淘宝": "taobao",
        "taobao": "taobao",
        "小红书": "xiaohongshu",
        "xhs": "xiaohongshu",
        "rednote": "xiaohongshu",
        "拼多多": "pinduoduo",
        "pdd": "pinduoduo",
        "pinduoduo": "pinduoduo",
        "shopify": "shopify_us",
        "shopify us": "shopify_us",
        "shopify_us": "shopify_us",
        "独立站": "shopify_us",
        "美国独立站": "shopify_us",
    }
    return aliases.get(text, text)


def normalize_row(row: dict[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_key, value in row.items():
        key = field_map.get(str(raw_key).strip(), str(raw_key).strip())
        normalized[key] = value
    return normalized


def ceil_price(value: float) -> float:
    if value <= 0:
        return 0.0
    return round(math.ceil(value * 10) / 10, 2)


def safe_slug(value: str) -> str:
    slug = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip())
    return slug.strip("-") or "item"


def row_get(row: sqlite3.Row | dict[str, Any], key: str, default: Any = "") -> Any:
    if isinstance(row, sqlite3.Row):
        return row[key] if key in row.keys() else default
    return row.get(key, default)


def shopify_handle_for(product: sqlite3.Row | dict[str, Any]) -> str:
    explicit = str(row_get(product, "shopify_handle", "") or "").strip()
    source = explicit or str(row_get(product, "title", "") or row_get(product, "sku", "")).strip()
    handle = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")
    return handle or safe_slug(str(row_get(product, "sku", "item"))).lower()


def split_values(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    parts: list[str] = []
    for chunk in text.replace("\r", "\n").replace("；", "|").replace(";", "|").split("|"):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def public_media_path(path: Path) -> str:
    return "/" + path.relative_to(STATIC_DIR).as_posix()


def extension_from_source(source: str, content_type: str = "") -> str:
    parsed = urlparse(source)
    ext = Path(parsed.path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}:
        return ext
    guessed = mimetypes.guess_extension(content_type.split(";")[0].strip()) if content_type else ""
    if guessed in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}:
        return guessed
    return ".jpg"


def copy_or_download_image(source: str, dest_dir: Path, stem: str) -> str:
    dest_dir.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(source)

    if parsed.scheme in {"http", "https"}:
        request = Request(source, headers={"User-Agent": "ResellAutomation/1.0"})
        with urlopen(request, timeout=15) as response:
            content_type = response.headers.get("Content-Type", "")
            if content_type and not content_type.lower().startswith("image/"):
                raise ValueError(f"not an image: {source}")
            body = response.read(12 * 1024 * 1024 + 1)
            if len(body) > 12 * 1024 * 1024:
                raise ValueError(f"image too large: {source}")
            ext = extension_from_source(source, content_type)
            target = dest_dir / f"{stem}{ext}"
            target.write_bytes(body)
            return public_media_path(target)

    if parsed.scheme == "file":
        source_path = Path(parsed.path)
    else:
        source_path = Path(source).expanduser()
        if not source_path.is_absolute():
            source_path = (ROOT / source_path).resolve()
    if not source_path.exists() or not source_path.is_file():
        raise ValueError(f"image file not found: {source}")
    ext = source_path.suffix.lower() if source_path.suffix else ".jpg"
    target = dest_dir / f"{stem}{ext}"
    target.write_bytes(source_path.read_bytes())
    return public_media_path(target)


def load_approved_images() -> list[dict[str, Any]]:
    if not APPROVED_IMAGES_PATH.exists():
        return []
    return read_csv_file(APPROVED_IMAGES_PATH)


def stage_approved_image(row: dict[str, Any], product: dict[str, Any]) -> tuple[str, str, str]:
    sku = safe_slug(str(product.get("sku") or "item"))
    source = str(row.get("file_path") or row.get("source_url") or "").strip()
    if not source:
        return "", "", ""
    image_url = copy_or_download_image(source, MEDIA_DIR / "products" / sku, "approved-01")
    image_source = str(row.get("source") or row.get("source_url") or row.get("file_path") or "approved library").strip()
    image_license = str(row.get("license") or "commercial-use approved").strip()
    return image_url, image_source, image_license


def match_approved_image(product: dict[str, Any]) -> tuple[str, str, str]:
    title = str(product.get("title") or "").lower()
    category = str(product.get("category") or "").lower()
    best: tuple[int, dict[str, Any] | None] = (0, None)
    for row in load_approved_images():
        if not boolish(row.get("usage_rights") or row.get("可商用") or row.get("authorized")):
            continue
        row_category = str(row.get("category") or "").lower()
        tags = [tag.lower() for tag in split_values(row.get("tags"))]
        score = 0
        if row_category and row_category == category:
            score += 10
        elif row_category and (row_category in category or category in row_category):
            score += 5
        for tag in tags:
            if tag and (tag in title or tag in category):
                score += 2
        if score > best[0]:
            best = (score, row)
    if best[1] is None:
        return "", "", ""
    try:
        return stage_approved_image(best[1], product)
    except Exception:
        return "", "", ""


def collect_authorized_images(row: dict[str, Any]) -> tuple[str, str, str]:
    explicit = str(row.get("primary_image") or "").strip()
    sku = safe_slug(str(row.get("sku") or "item"))
    dest_dir = MEDIA_DIR / "products" / sku

    if explicit:
        return explicit, str(row.get("image_source") or "manual").strip(), str(row.get("image_license") or "").strip()

    if boolish(row.get("image_rights")):
        for index, source in enumerate(split_values(row.get("image_urls")), start=1):
            try:
                image_url = copy_or_download_image(source, dest_dir, f"source-{index:02d}")
                image_source = str(row.get("image_source") or source).strip()
                image_license = str(row.get("image_license") or "supplier authorized").strip()
                return image_url, image_source, image_license
            except Exception:
                continue

    return match_approved_image(row)


def build_image_prompt(product: dict[str, Any]) -> str:
    title = str(product.get("title") or "").strip()
    category = str(product.get("category") or "").strip()
    supplier_note = str(product.get("notes") or "").strip()
    return (
        "Use case: product-mockup\n"
        "Asset type: ecommerce listing main image\n"
        f"Primary request: create an original, unbranded product-style image for: {title}\n"
        f"Category: {category}\n"
        "Style/medium: clean commercial product photography, realistic but generic\n"
        "Composition/framing: single product or simple set, centered, square 1:1 crop, enough padding\n"
        "Scene/backdrop: plain white or light neutral studio background\n"
        "Lighting/mood: soft diffused studio light, clear shape and material details\n"
        f"Product notes: {supplier_note}\n"
        "Constraints: no brand names, no logos, no packaging claims, no platform UI, no watermark, no text.\n"
        "Accuracy constraint: do not invent regulated claims; final image must be manually checked against the real supplier SKU before publishing."
    )


def choose_image_fields(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    primary_image, image_source, image_license = collect_authorized_images(row)
    explicit_prompt = str(row.get("image_prompt") or "").strip()
    if primary_image:
        status = "ready"
        prompt = explicit_prompt or build_image_prompt(row)
    else:
        status = "needs_generation"
        prompt = explicit_prompt or build_image_prompt(row)
        if not image_source:
            image_source = "ai-generation-prompt"
        if not image_license:
            image_license = "original image required"
    return primary_image, image_source, image_license, prompt, status


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                supplier TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                cost REAL DEFAULT 0,
                shipping_cost REAL DEFAULT 0,
                pack_cost REAL DEFAULT 0,
                stock INTEGER DEFAULT 0,
                lead_days INTEGER DEFAULT 2,
                category TEXT DEFAULT '',
                authorized INTEGER DEFAULT 0,
                invoice_available INTEGER DEFAULT 0,
                image_rights INTEGER DEFAULT 0,
                quality_checked INTEGER DEFAULT 0,
                supplier_sla_hours INTEGER DEFAULT 48,
                image_urls TEXT DEFAULT '',
                primary_image TEXT DEFAULT '',
                image_source TEXT DEFAULT '',
                image_license TEXT DEFAULT '',
                image_prompt TEXT DEFAULT '',
                image_status TEXT DEFAULT '',
                target_platform TEXT DEFAULT '',
                market_price REAL DEFAULT 0,
                market_sales INTEGER DEFAULT 0,
                competitor_url TEXT DEFAULT '',
                test_budget REAL DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                order_id TEXT NOT NULL UNIQUE,
                sku TEXT NOT NULL,
                qty INTEGER DEFAULT 1,
                paid_amount REAL DEFAULT 0,
                buyer_name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                address TEXT DEFAULT '',
                deadline TEXT DEFAULT '',
                status TEXT DEFAULT 'new',
                risk_flags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                platform TEXT PRIMARY KEY,
                fee_rate REAL NOT NULL,
                ad_rate REAL NOT NULL,
                return_rate REAL NOT NULL,
                target_margin REAL NOT NULL,
                min_profit REAL NOT NULL
            );
            """
        )
        ensure_columns(
            conn,
            "products",
            {
                "image_urls": "TEXT DEFAULT ''",
                "primary_image": "TEXT DEFAULT ''",
                "image_source": "TEXT DEFAULT ''",
                "image_license": "TEXT DEFAULT ''",
                "image_prompt": "TEXT DEFAULT ''",
                "image_status": "TEXT DEFAULT ''",
                "target_platform": "TEXT DEFAULT ''",
                "market_price": "REAL DEFAULT 0",
                "market_sales": "INTEGER DEFAULT 0",
                "competitor_url": "TEXT DEFAULT ''",
                "test_budget": "REAL DEFAULT 0",
                "material": "TEXT DEFAULT ''",
                "plating": "TEXT DEFAULT ''",
                "size": "TEXT DEFAULT ''",
                "weight_g": "REAL DEFAULT 0",
                "hs_code": "TEXT DEFAULT ''",
                "country_of_origin": "TEXT DEFAULT ''",
                "compliance_report_url": "TEXT DEFAULT ''",
                "product_story": "TEXT DEFAULT ''",
                "ad_angle": "TEXT DEFAULT ''",
                "content_status": "TEXT DEFAULT ''",
                "shopify_handle": "TEXT DEFAULT ''",
                "shopify_tags": "TEXT DEFAULT ''",
            },
        )
        for platform, settings in DEFAULT_SETTINGS.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO settings
                    (platform, fee_rate, ad_rate, return_rate, target_margin, min_profit)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    platform,
                    settings["fee_rate"],
                    settings["ad_rate"],
                    settings["return_rate"],
                    settings["target_margin"],
                    settings["min_profit"],
                ),
            )


def load_settings(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    rows = conn.execute("SELECT * FROM settings ORDER BY platform").fetchall()
    return {row["platform"]: dict(row) for row in rows}


def product_risks(product: sqlite3.Row | dict[str, Any]) -> list[str]:
    title = str(row_get(product, "title", "") or "")
    category = str(row_get(product, "category", "") or "")
    notes = str(row_get(product, "notes", "") or "")
    haystack = f"{title} {category}".lower()
    risks: list[str] = []
    if not int(row_get(product, "authorized", 0) or 0):
        risks.append("缺少授权/代发协议确认")
    if not int(row_get(product, "invoice_available", 0) or 0):
        risks.append("发票或进货凭证未确认")
    if not int(row_get(product, "image_rights", 0) or 0):
        if not str(row_get(product, "primary_image", "") or "").strip():
            risks.append("图片/视频授权未确认")
    if not str(row_get(product, "primary_image", "") or "").strip():
        risks.append("缺少可用主图或待生成图片")
    if not int(row_get(product, "quality_checked", 0) or 0):
        risks.append("样品未验货")
    if as_int(row_get(product, "stock", 0)) <= 0:
        risks.append("供应商库存不足")
    if as_int(row_get(product, "lead_days", 0)) > 3 or as_int(row_get(product, "supplier_sla_hours", 0)) > 48:
        risks.append("发货时效偏慢")
    hit_terms = [term for term in SENSITIVE_TERMS if term.lower() in haystack]
    if hit_terms:
        risks.append("可能需要资质/谨慎宣传: " + "、".join(hit_terms[:4]))
    if is_shopify_us_candidate(product):
        if not str(row_get(product, "material", "") or "").strip():
            risks.append("缺少饰品材质")
        if not str(row_get(product, "size", "") or "").strip():
            risks.append("缺少饰品尺寸")
        if as_float(row_get(product, "weight_g", 0)) <= 0:
            risks.append("缺少克重")
        if not str(row_get(product, "hs_code", "") or "").strip():
            risks.append("缺少HS Code")
        if not str(row_get(product, "country_of_origin", "") or "").strip():
            risks.append("缺少原产国")
        if not str(row_get(product, "compliance_report_url", "") or "").strip():
            risks.append("缺少铅镉镍等检测报告")
        if str(row_get(product, "content_status", "") or "").strip().lower() != "ready":
            risks.append("Instagram/广告素材未就绪")
        risky_claims = ["hypoallergenic", "waterproof", "sweat-proof", "sweatproof", "tarnish", "防过敏", "防水", "防汗", "防褪色"]
        if any(claim in f"{title} {category} {notes}".lower() for claim in risky_claims) and not str(row_get(product, "compliance_report_url", "") or "").strip():
            risks.append("防水/防汗/防过敏等宣传需检测支撑")
        blocked_terms = ["children", "kids", "child", "儿童", "童款", "穿刺", "piercing", "pierced", "天然宝石", "真金", "纯银"]
        if any(term in f"{title} {category} {notes}".lower() for term in blocked_terms):
            risks.append("首阶段不建议销售儿童/穿刺/贵金属高风险饰品")
    return risks


def price_for_platform(product: sqlite3.Row | dict[str, Any], settings: dict[str, float]) -> dict[str, float]:
    landed = as_float(product["cost"]) + as_float(product["shipping_cost"]) + as_float(product["pack_cost"])
    total_rate = settings["fee_rate"] + settings["ad_rate"] + settings["return_rate"] + settings["target_margin"]
    denominator = max(0.08, 1 - total_rate)
    recommended = ceil_price((landed + settings["min_profit"]) / denominator)
    profit = recommended * (1 - settings["fee_rate"] - settings["ad_rate"] - settings["return_rate"]) - landed
    margin = profit / recommended if recommended else 0
    return {
        "landed_cost": round(landed, 2),
        "recommended_price": recommended,
        "expected_profit": round(profit, 2),
        "expected_margin": round(margin, 4),
    }


def is_shopify_us_candidate(product: sqlite3.Row | dict[str, Any]) -> bool:
    target = normalize_platform(row_get(product, "target_platform", ""))
    title = str(row_get(product, "title", "") or "").lower()
    category = str(row_get(product, "category", "") or "").lower()
    return target == "shopify_us" or any(term in f"{title} {category}" for term in ["jewelry", "pendant", "necklace", "bracelet", "ring", "饰品", "首饰", "吊坠", "项链", "手链", "戒指"])


def image_compliance_note(product: sqlite3.Row | dict[str, Any]) -> str:
    status = str(product["image_status"] or "").strip()
    source = str(product["image_source"] or "").strip()
    if status == "ready":
        if "ai" in source.lower() or "generated" in source.lower():
            return "AI生成图已配置，发布前需人工核对与真实SKU一致"
        return "图片来源已配置，发布前复核授权和实物一致性"
    if status == "needs_generation":
        return "需先按提示词生成图片并人工复核后再发布"
    return "图片状态未确认"


def selected_platform(product: sqlite3.Row | dict[str, Any], settings: dict[str, dict[str, float]]) -> str:
    target = normalize_platform(product["target_platform"] if "target_platform" in product.keys() else "")
    if target in settings:
        return target
    best_platform = "douyin"
    best_profit = -999999.0
    for platform, platform_settings in settings.items():
        price = price_for_platform(product, platform_settings)
        if price["expected_profit"] > best_profit:
            best_profit = price["expected_profit"]
            best_platform = platform
    return best_platform


def product_opportunity(product: sqlite3.Row | dict[str, Any], settings: dict[str, dict[str, float]]) -> dict[str, Any]:
    risks = product_risks(product)
    platform = selected_platform(product, settings)
    price = price_for_platform(product, settings[platform])
    market_price = as_float(product["market_price"] if "market_price" in product.keys() else 0)
    market_sales = as_int(product["market_sales"] if "market_sales" in product.keys() else 0)
    budget = as_float(product["test_budget"] if "test_budget" in product.keys() else 0)

    if market_price > 0:
        gap_margin = max(0.0, (market_price - price["landed_cost"]) / market_price)
    else:
        gap_margin = max(0.0, price["expected_margin"])

    profit_score = min(32.0, max(0.0, price["expected_margin"]) * 70)
    cash_score = min(16.0, max(0.0, price["expected_profit"]) * 1.8)
    gap_score = min(18.0, gap_margin * 26)
    demand_score = min(14.0, math.log10(market_sales + 1) * 4.2) if market_sales > 0 else 0.0
    readiness_score = 0.0
    readiness_score += 6.0 if product["primary_image"] else 0.0
    readiness_score += 6.0 if int(product["authorized"] or 0) else 0.0
    readiness_score += 4.0 if int(product["invoice_available"] or 0) else 0.0
    readiness_score += 4.0 if int(product["quality_checked"] or 0) else 0.0
    stock_score = min(6.0, max(0, as_int(product["stock"])) / 50)
    speed_score = 4.0 if as_int(product["lead_days"], 99) <= 2 and as_int(product["supplier_sla_hours"], 999) <= 48 else 0.0
    risk_penalty = min(38.0, len(risks) * 8.0)

    score = int(round(max(0.0, min(100.0, profit_score + cash_score + gap_score + demand_score + readiness_score + stock_score + speed_score - risk_penalty))))
    has_blocker = any(
        risk in risks
        for risk in ["缺少授权/代发协议确认", "发票或进货凭证未确认", "缺少可用主图或待生成图片", "样品未验货", "供应商库存不足"]
    )
    if has_blocker:
        action = "补资料后再测"
    elif score >= 75:
        action = "优先7天测试"
    elif score >= 60:
        action = "小预算测试"
    elif score >= 45:
        action = "备选观察"
    else:
        action = "暂缓"

    test_budget = budget if budget > 0 else min(300.0, max(80.0, price["recommended_price"] * 8))
    daily_budget = round(test_budget / 5, 2)
    break_even_orders = math.ceil(test_budget / price["expected_profit"]) if price["expected_profit"] > 0 else 0
    return {
        "score": score,
        "action": action,
        "platform": platform,
        "platform_name": PLATFORM_NAMES.get(platform, platform),
        "recommended_price": price["recommended_price"],
        "expected_profit": price["expected_profit"],
        "expected_margin": price["expected_margin"],
        "landed_cost": price["landed_cost"],
        "market_price": market_price,
        "market_sales": market_sales,
        "gap_margin": round(gap_margin, 4),
        "test_budget": round(test_budget, 2),
        "daily_budget": daily_budget,
        "break_even_orders": break_even_orders,
        "primary_blocker": risks[0] if risks else "",
    }


def row_to_product(row: sqlite3.Row, settings: dict[str, dict[str, float]]) -> dict[str, Any]:
    product = dict(row)
    product["risks"] = product_risks(row)
    product["publishable"] = not product["risks"]
    product["prices"] = {
        platform: price_for_platform(row, platform_settings)
        for platform, platform_settings in settings.items()
    }
    product["opportunity"] = product_opportunity(row, settings)
    product["shopify_handle"] = product.get("shopify_handle") or shopify_handle_for(product)
    product["launch_ready"] = is_shopify_us_candidate(product) and not product["risks"]
    return product


def launch_blocker_count(product: sqlite3.Row | dict[str, Any]) -> int:
    if not is_shopify_us_candidate(product):
        return 0
    return len(product_risks(product))


def order_risks(order: sqlite3.Row | dict[str, Any], product: sqlite3.Row | None, settings: dict[str, dict[str, float]]) -> list[str]:
    risks: list[str] = []
    if product is None:
        return ["商品 SKU 未在商品库中"]

    risks.extend(product_risks(product))
    qty = max(1, as_int(order["qty"], 1))
    stock = as_int(product["stock"])
    if stock < qty:
        risks.append("库存不足以履约")
    if not str(order["buyer_name"] or "").strip() or not str(order["phone"] or "").strip() or not str(order["address"] or "").strip():
        risks.append("收件信息不完整")

    platform = normalize_platform(order["platform"])
    platform_settings = settings.get(platform)
    if platform_settings:
        landed = as_float(product["cost"]) + as_float(product["shipping_cost"]) + as_float(product["pack_cost"])
        paid = as_float(order["paid_amount"])
        profit = paid * (1 - platform_settings["fee_rate"] - platform_settings["ad_rate"] - platform_settings["return_rate"]) - landed * qty
        if paid > 0 and profit < platform_settings["min_profit"]:
            risks.append("订单利润低于最低利润")
    else:
        risks.append("未知平台费率设置")
    return risks


def refresh_order_risks(conn: sqlite3.Connection) -> None:
    settings = load_settings(conn)
    orders = conn.execute("SELECT * FROM orders").fetchall()
    for order in orders:
        product = conn.execute("SELECT * FROM products WHERE sku = ?", (order["sku"],)).fetchone()
        risks = order_risks(order, product, settings)
        status = "risk_hold" if risks else "purchase_ready"
        conn.execute(
            "UPDATE orders SET risk_flags = ?, status = ?, updated_at = ? WHERE id = ?",
            (json.dumps(risks, ensure_ascii=False), status, utc_now(), order["id"]),
        )


def import_products(rows: list[dict[str, Any]]) -> dict[str, int]:
    imported = 0
    skipped = 0
    now = utc_now()
    with connect() as conn:
        for raw in rows:
            row = normalize_row(raw, PRODUCT_FIELD_MAP)
            sku = str(row.get("sku") or "").strip()
            title = str(row.get("title") or "").strip()
            if not sku or not title:
                skipped += 1
                continue
            primary_image, image_source, image_license, image_prompt, image_status = choose_image_fields(row)
            conn.execute(
                """
                INSERT INTO products (
                    sku, title, supplier, source_url, cost, shipping_cost, pack_cost, stock,
                    lead_days, category, authorized, invoice_available, image_rights,
                    quality_checked, supplier_sla_hours, image_urls, primary_image,
                    image_source, image_license, image_prompt, image_status, target_platform,
                    market_price, market_sales, competitor_url, test_budget, notes, material,
                    plating, size, weight_g, hs_code, country_of_origin, compliance_report_url,
                    product_story, ad_angle, content_status, shopify_handle, shopify_tags,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sku) DO UPDATE SET
                    title = excluded.title,
                    supplier = excluded.supplier,
                    source_url = excluded.source_url,
                    cost = excluded.cost,
                    shipping_cost = excluded.shipping_cost,
                    pack_cost = excluded.pack_cost,
                    stock = excluded.stock,
                    lead_days = excluded.lead_days,
                    category = excluded.category,
                    authorized = excluded.authorized,
                    invoice_available = excluded.invoice_available,
                    image_rights = excluded.image_rights,
                    quality_checked = excluded.quality_checked,
                    supplier_sla_hours = excluded.supplier_sla_hours,
                    image_urls = excluded.image_urls,
                    primary_image = excluded.primary_image,
                    image_source = excluded.image_source,
                    image_license = excluded.image_license,
                    image_prompt = excluded.image_prompt,
                    image_status = excluded.image_status,
                    target_platform = excluded.target_platform,
                    market_price = excluded.market_price,
                    market_sales = excluded.market_sales,
                    competitor_url = excluded.competitor_url,
                    test_budget = excluded.test_budget,
                    notes = excluded.notes,
                    material = excluded.material,
                    plating = excluded.plating,
                    size = excluded.size,
                    weight_g = excluded.weight_g,
                    hs_code = excluded.hs_code,
                    country_of_origin = excluded.country_of_origin,
                    compliance_report_url = excluded.compliance_report_url,
                    product_story = excluded.product_story,
                    ad_angle = excluded.ad_angle,
                    content_status = excluded.content_status,
                    shopify_handle = excluded.shopify_handle,
                    shopify_tags = excluded.shopify_tags,
                    updated_at = excluded.updated_at
                """,
                (
                    sku,
                    title,
                    str(row.get("supplier") or "").strip(),
                    str(row.get("source_url") or "").strip(),
                    as_float(row.get("cost")),
                    as_float(row.get("shipping_cost")),
                    as_float(row.get("pack_cost")),
                    as_int(row.get("stock")),
                    as_int(row.get("lead_days"), 2),
                    str(row.get("category") or "").strip(),
                    boolish(row.get("authorized")),
                    boolish(row.get("invoice_available")),
                    boolish(row.get("image_rights")),
                    boolish(row.get("quality_checked")),
                    as_int(row.get("supplier_sla_hours"), 48),
                    str(row.get("image_urls") or "").strip(),
                    primary_image,
                    image_source,
                    image_license,
                    image_prompt,
                    image_status,
                    normalize_platform(row.get("target_platform")),
                    as_float(row.get("market_price")),
                    as_int(row.get("market_sales")),
                    str(row.get("competitor_url") or "").strip(),
                    as_float(row.get("test_budget")),
                    str(row.get("notes") or "").strip(),
                    str(row.get("material") or "").strip(),
                    str(row.get("plating") or "").strip(),
                    str(row.get("size") or "").strip(),
                    as_float(row.get("weight_g")),
                    str(row.get("hs_code") or "").strip(),
                    str(row.get("country_of_origin") or "China").strip(),
                    str(row.get("compliance_report_url") or "").strip(),
                    str(row.get("product_story") or "").strip(),
                    str(row.get("ad_angle") or "").strip(),
                    str(row.get("content_status") or "").strip(),
                    str(row.get("shopify_handle") or "").strip(),
                    str(row.get("shopify_tags") or "").strip(),
                    now,
                    now,
                ),
            )
            imported += 1
        refresh_order_risks(conn)
    return {"imported": imported, "skipped": skipped}


def import_orders(rows: list[dict[str, Any]]) -> dict[str, int]:
    imported = 0
    skipped = 0
    now = utc_now()
    with connect() as conn:
        for raw in rows:
            row = normalize_row(raw, ORDER_FIELD_MAP)
            order_id = str(row.get("order_id") or "").strip()
            sku = str(row.get("sku") or "").strip()
            platform = normalize_platform(row.get("platform"))
            if not order_id or not sku or not platform:
                skipped += 1
                continue
            conn.execute(
                """
                INSERT INTO orders (
                    platform, order_id, sku, qty, paid_amount, buyer_name, phone,
                    address, deadline, status, risk_flags, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', '[]', ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    platform = excluded.platform,
                    sku = excluded.sku,
                    qty = excluded.qty,
                    paid_amount = excluded.paid_amount,
                    buyer_name = excluded.buyer_name,
                    phone = excluded.phone,
                    address = excluded.address,
                    deadline = excluded.deadline,
                    updated_at = excluded.updated_at
                """,
                (
                    platform,
                    order_id,
                    sku,
                    as_int(row.get("qty"), 1),
                    as_float(row.get("paid_amount")),
                    str(row.get("buyer_name") or "").strip(),
                    str(row.get("phone") or "").strip(),
                    str(row.get("address") or "").strip(),
                    str(row.get("deadline") or "").strip(),
                    now,
                    now,
                ),
            )
            imported += 1
        refresh_order_risks(conn)
    return {"imported": imported, "skipped": skipped}


def build_summary() -> dict[str, Any]:
    with connect() as conn:
        settings = load_settings(conn)
        product_rows = conn.execute("SELECT * FROM products ORDER BY updated_at DESC, sku").fetchall()
        order_rows = conn.execute("SELECT * FROM orders ORDER BY updated_at DESC, order_id").fetchall()
        products = [row_to_product(row, settings) for row in product_rows]
        products.sort(key=lambda product: product["opportunity"]["score"], reverse=True)
        orders = []
        for row in order_rows:
            order = dict(row)
            try:
                order["risk_flags"] = json.loads(order["risk_flags"] or "[]")
            except json.JSONDecodeError:
                order["risk_flags"] = []
            order["platform_name"] = PLATFORM_NAMES.get(order["platform"], order["platform"])
            orders.append(order)
        risk_counts: dict[str, int] = {}
        for product in products:
            for risk in product["risks"]:
                risk_counts[risk] = risk_counts.get(risk, 0) + 1
        for order in orders:
            for risk in order["risk_flags"]:
                risk_counts[risk] = risk_counts.get(risk, 0) + 1
        return {
            "settings": settings,
            "products": products,
            "orders": orders,
            "metrics": {
                "products": len(products),
                "publishable": sum(1 for product in products if product["publishable"]),
                "test_ready": sum(1 for product in products if product["opportunity"]["action"] in {"优先7天测试", "小预算测试"}),
                "top_score": max([product["opportunity"]["score"] for product in products], default=0),
                "images_ready": sum(1 for product in products if product.get("primary_image")),
                "images_need_generation": sum(1 for product in products if product.get("image_status") == "needs_generation"),
                "shopify_candidates": sum(1 for product in products if is_shopify_us_candidate(product)),
                "shopify_ready": sum(1 for product in products if product.get("launch_ready")),
                "meta_assets_ready": sum(1 for product in products if is_shopify_us_candidate(product) and str(product.get("content_status") or "").lower() == "ready"),
                "launch_blockers": sum(launch_blocker_count(product) for product in products),
                "orders": len(orders),
                "purchase_ready": sum(1 for order in orders if order["status"] == "purchase_ready"),
                "risk_orders": sum(1 for order in orders if order["status"] == "risk_hold"),
            },
            "risk_counts": sorted(
                [{"risk": key, "count": value} for key, value in risk_counts.items()],
                key=lambda item: item["count"],
                reverse=True,
            ),
        }


def update_settings(payload: dict[str, Any]) -> dict[str, str]:
    with connect() as conn:
        for platform, raw_settings in payload.get("settings", {}).items():
            platform = normalize_platform(platform)
            if platform not in DEFAULT_SETTINGS:
                continue
            existing = DEFAULT_SETTINGS[platform]
            settings = {
                "fee_rate": as_float(raw_settings.get("fee_rate"), existing["fee_rate"]),
                "ad_rate": as_float(raw_settings.get("ad_rate"), existing["ad_rate"]),
                "return_rate": as_float(raw_settings.get("return_rate"), existing["return_rate"]),
                "target_margin": as_float(raw_settings.get("target_margin"), existing["target_margin"]),
                "min_profit": as_float(raw_settings.get("min_profit"), existing["min_profit"]),
            }
            conn.execute(
                """
                INSERT INTO settings (platform, fee_rate, ad_rate, return_rate, target_margin, min_profit)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform) DO UPDATE SET
                    fee_rate = excluded.fee_rate,
                    ad_rate = excluded.ad_rate,
                    return_rate = excluded.return_rate,
                    target_margin = excluded.target_margin,
                    min_profit = excluded.min_profit
                """,
                (
                    platform,
                    settings["fee_rate"],
                    settings["ad_rate"],
                    settings["return_rate"],
                    settings["target_margin"],
                    settings["min_profit"],
                ),
            )
        refresh_order_risks(conn)
    return {"status": "ok"}


def csv_response(headers: list[str], rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")


def export_listings(platform: str, include_risky: bool = False) -> tuple[bytes, str]:
    platform = normalize_platform(platform)
    with connect() as conn:
        settings = load_settings(conn)
        if platform not in settings:
            platform = "douyin"
        rows = conn.execute("SELECT * FROM products ORDER BY sku").fetchall()
        output = []
        for row in rows:
            risks = product_risks(row)
            if risks and not include_risky:
                continue
            price = price_for_platform(row, settings[platform])
            output.append(
                {
                    "platform": PLATFORM_NAMES.get(platform, platform),
                    "sku": row["sku"],
                    "title": row["title"],
                    "category": row["category"],
                    "price": price["recommended_price"],
                    "stock": row["stock"],
                    "lead_days": row["lead_days"],
                    "main_image": row["primary_image"],
                    "image_status": row["image_status"],
                    "image_source": row["image_source"],
                    "image_license": row["image_license"],
                    "image_generation_prompt": row["image_prompt"],
                    "source_url": row["source_url"],
                    "supplier": row["supplier"],
                    "description": f"{row['title']}。由授权供应商履约，售后按本店铺规则处理。",
                    "compliance_notes": "；".join(risks) if risks else image_compliance_note(row),
                }
            )
    headers = [
        "platform",
        "sku",
        "title",
        "category",
        "price",
        "stock",
        "lead_days",
        "main_image",
        "image_status",
        "image_source",
        "image_license",
        "image_generation_prompt",
        "source_url",
        "supplier",
        "description",
        "compliance_notes",
    ]
    return csv_response(headers, output), f"{platform}_listing_export.csv"


def product_body_html(product: sqlite3.Row | dict[str, Any]) -> str:
    story = str(row_get(product, "product_story", "") or "").strip()
    material = str(row_get(product, "material", "") or "").strip()
    plating = str(row_get(product, "plating", "") or "").strip()
    size = str(row_get(product, "size", "") or "").strip()
    origin = str(row_get(product, "country_of_origin", "China") or "China").strip()
    report_url = str(row_get(product, "compliance_report_url", "") or "").strip()
    parts = []
    if story:
        parts.append(f"<p>{html.escape(story)}</p>")
    facts = [
        ("Material", material),
        ("Finish", plating),
        ("Size", size),
        ("Origin", origin),
    ]
    fact_items = [f"<li><strong>{label}:</strong> {html.escape(value)}</li>" for label, value in facts if value]
    if fact_items:
        parts.append("<ul>" + "".join(fact_items) + "</ul>")
    parts.append("<p>Ships from China with tracked cross-border shipping. Processing takes 2-4 business days. Estimated US delivery is 7-15 business days after dispatch.</p>")
    parts.append("<p>Returns are accepted within 14 days for unused items in original packaging. Quality issues are handled with refund or replacement support.</p>")
    if report_url:
        parts.append(f"<p>Compliance report available: {html.escape(report_url)}</p>")
    return "\n".join(parts)


def export_shopify_products(include_risky: bool = False) -> tuple[bytes, str]:
    with connect() as conn:
        settings = load_settings(conn)
        shopify_settings = settings.get("shopify_us", DEFAULT_SETTINGS["shopify_us"])
        rows = conn.execute("SELECT * FROM products ORDER BY sku").fetchall()
        output = []
        for row in rows:
            if not is_shopify_us_candidate(row):
                continue
            risks = product_risks(row)
            if risks and not include_risky:
                continue
            price = price_for_platform(row, shopify_settings)
            market_price = as_float(row_get(row, "market_price", 0))
            handle = shopify_handle_for(row)
            title = str(row_get(row, "title", "") or "").strip()
            tags = split_values(row_get(row, "shopify_tags", "")) or ["mens-jewelry", "china-fulfilled", "us-test"]
            output.append(
                {
                    "Handle": handle,
                    "Title": title,
                    "Body (HTML)": product_body_html(row),
                    "Vendor": str(row_get(row, "supplier", "") or "China jewelry supplier").strip(),
                    "Product Category": "Apparel & Accessories > Jewelry",
                    "Type": str(row_get(row, "category", "") or "Jewelry").strip(),
                    "Tags": ", ".join(tags),
                    "Published": "TRUE",
                    "Option1 Name": "Title",
                    "Option1 Value": "Default Title",
                    "Variant SKU": row_get(row, "sku", ""),
                    "Variant Grams": str(int(round(as_float(row_get(row, "weight_g", 0))))),
                    "Variant Inventory Tracker": "shopify",
                    "Variant Inventory Qty": row_get(row, "stock", 0),
                    "Variant Inventory Policy": "deny",
                    "Variant Fulfillment Service": "manual",
                    "Variant Price": f"{price['recommended_price']:.2f}",
                    "Variant Compare At Price": f"{market_price:.2f}" if market_price > price["recommended_price"] else "",
                    "Variant Requires Shipping": "TRUE",
                    "Variant Taxable": "TRUE",
                    "Variant Barcode": "",
                    "Image Src": row_get(row, "primary_image", ""),
                    "Image Position": "1",
                    "Image Alt Text": title,
                    "SEO Title": f"{title} | Discipline Jewelry",
                    "SEO Description": str(row_get(row, "product_story", "") or f"{title} ships from China with tracked US delivery.")[:155],
                    "Google Shopping / Google Product Category": "Apparel & Accessories > Jewelry",
                    "Google Shopping / Gender": "male",
                    "Google Shopping / Age Group": "adult",
                    "Google Shopping / MPN": row_get(row, "sku", ""),
                    "Google Shopping / Condition": "new",
                    "Google Shopping / Custom Product": "TRUE",
                    "Variant Weight Unit": "g",
                    "Status": "active",
                }
            )
    headers = [
        "Handle",
        "Title",
        "Body (HTML)",
        "Vendor",
        "Product Category",
        "Type",
        "Tags",
        "Published",
        "Option1 Name",
        "Option1 Value",
        "Variant SKU",
        "Variant Grams",
        "Variant Inventory Tracker",
        "Variant Inventory Qty",
        "Variant Inventory Policy",
        "Variant Fulfillment Service",
        "Variant Price",
        "Variant Compare At Price",
        "Variant Requires Shipping",
        "Variant Taxable",
        "Variant Barcode",
        "Image Src",
        "Image Position",
        "Image Alt Text",
        "SEO Title",
        "SEO Description",
        "Google Shopping / Google Product Category",
        "Google Shopping / Gender",
        "Google Shopping / Age Group",
        "Google Shopping / MPN",
        "Google Shopping / Condition",
        "Google Shopping / Custom Product",
        "Variant Weight Unit",
        "Status",
    ]
    return csv_response(headers, output), "shopify_us_products.csv"


def export_meta_ad_plan() -> tuple[bytes, str]:
    creative_types = [
        ("product close-up", "Show pendant detail in hand or on a dark stone surface.", "The reminder you can wear every day."),
        ("model wear", "Male model wearing the piece with a plain black tee or jacket.", "Built for the man becoming more."),
        ("gift scene", "Unboxing shot with gift box, chain, pendant, and handwritten card.", "A gift with a message, not just a shine."),
        ("story hook", "Fast Reel with symbol close-up, one line of meaning, and final product shot.", "A reminder to keep going."),
        ("bundle offer", "Two-piece layout: pendant plus chain or bracelet, clear offer framing.", "Build the set before the first test ends."),
    ]
    rows = []
    for product in ranked_products():
        if not is_shopify_us_candidate(product) or product_risks(product):
            continue
        opp = product["opportunity"]
        ad_angle = str(product.get("ad_angle") or "Wear the reminder.").strip()
        for creative_type, visual_brief, hook in creative_types:
            rows.append(
                {
                    "sku": product["sku"],
                    "title": product["title"],
                    "market": "United States",
                    "destination": "Shopify product page",
                    "creative_type": creative_type,
                    "primary_text": f"{ad_angle} {product.get('product_story') or hook}",
                    "visual_brief": visual_brief,
                    "hook": hook,
                    "cta": "Shop Now",
                    "daily_budget_usd": opp["daily_budget"],
                    "test_days": 7,
                    "success_metric": "CTR > 1%, add-to-cart > 5%, purchase conversion > 1%, CPA below expected profit",
                }
            )
            if len(rows) >= 25:
                break
        if len(rows) >= 25:
            break
    headers = [
        "sku",
        "title",
        "market",
        "destination",
        "creative_type",
        "primary_text",
        "visual_brief",
        "hook",
        "cta",
        "daily_budget_usd",
        "test_days",
        "success_metric",
    ]
    return csv_response(headers, rows), "meta_ad_test_plan.csv"


def export_us_launch_playbook() -> tuple[bytes, str]:
    summary = build_summary()
    metrics = summary["metrics"]
    lines = [
        "# Mainland China to US Shopify Launch Playbook",
        "",
        "## Operating model",
        "",
        "- Instagram and Meta Ads create demand.",
        "- Instagram bio links to the Shopify storefront.",
        "- Shopify collects payment in USD through PayPal China and one approved third-party card processor.",
        "- Orders ship from China with tracked cross-border small parcel service.",
        "- Reviews, UGC, and ad winners feed the next creative cycle.",
        "",
        "## First market",
        "",
        "Open United States only until the store has 30-50 completed orders, stable tracking, and dispute handling under control.",
        "",
        "## Launch checklist",
        "",
        "- Brand name, .com domain, Instagram handle, Facebook Page, and Shopify store are created.",
        "- Store currency is USD.",
        "- PayPal Business China is approved.",
        "- One third-party Shopify card processor is approved or under review.",
        "- Shipping policy says ships from China with tracked delivery.",
        "- Refund policy allows 14-day returns for unused items in original packaging.",
        "- Each product has material, plating, size, weight, HS Code, origin, and compliance report.",
        "- Each hero SKU has product close-up, model wear, gift scene, story hook, and bundle offer creatives.",
        "- Meta Pixel and Conversions API are connected through Shopify.",
        "",
        "## Current readiness",
        "",
        f"- Shopify US candidates: {metrics['shopify_candidates']}",
        f"- Shopify-ready SKUs: {metrics['shopify_ready']}",
        f"- Meta-ready assets: {metrics['meta_assets_ready']}",
        f"- Launch blockers: {metrics['launch_blockers']}",
        "",
        "## 90-day execution",
        "",
        "Weeks 1-2: finish brand assets, domain, Shopify, payment applications, and sample QC.",
        "Weeks 3-4: shoot product media, build the store, test two US logistics lines, and publish 30 Instagram posts.",
        "Week 5: launch the site and place 5-10 real test orders.",
        "Weeks 6-8: run Meta tests at USD 30-50 per day, only on 3-5 hero SKUs.",
        "Weeks 9-12: scale winners, add bundles and reviews, improve support macros, and target 50-100 monthly orders.",
        "",
        "## Scale gate",
        "",
        "Consider a US warehouse, Hong Kong entity, Shopify Payments HK, and more markets only after 100 orders per month with stable dispute rates.",
    ]
    return markdown_bytes("\n".join(lines) + "\n"), "us_shopify_launch_playbook.md"


def export_purchase_orders(include_risky: bool = False) -> tuple[bytes, str]:
    with connect() as conn:
        settings = load_settings(conn)
        rows = conn.execute("SELECT * FROM orders ORDER BY platform, order_id").fetchall()
        output = []
        for order in rows:
            product = conn.execute("SELECT * FROM products WHERE sku = ?", (order["sku"],)).fetchone()
            risks = order_risks(order, product, settings)
            if risks and not include_risky:
                continue
            output.append(
                {
                    "supplier": product["supplier"] if product else "",
                    "platform": PLATFORM_NAMES.get(order["platform"], order["platform"]),
                    "platform_order_id": order["order_id"],
                    "sku": order["sku"],
                    "title": product["title"] if product else "",
                    "qty": order["qty"],
                    "buyer_name": order["buyer_name"],
                    "phone": order["phone"],
                    "address": order["address"],
                    "source_url": product["source_url"] if product else "",
                    "purchase_note": "请按本店授权代发协议发货，不放第三方平台广告单；售后退换货按协议处理。",
                    "risk_notes": "；".join(risks),
                }
            )
    headers = [
        "supplier",
        "platform",
        "platform_order_id",
        "sku",
        "title",
        "qty",
        "buyer_name",
        "phone",
        "address",
        "source_url",
        "purchase_note",
        "risk_notes",
    ]
    return csv_response(headers, output), "supplier_purchase_orders.csv"


def export_image_prompts() -> tuple[bytes, str]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY sku").fetchall()
        output = []
        for row in rows:
            if row["primary_image"]:
                continue
            output.append(
                {
                    "sku": row["sku"],
                    "title": row["title"],
                    "category": row["category"],
                    "image_status": row["image_status"],
                    "image_generation_prompt": row["image_prompt"] or build_image_prompt(dict(row)),
                    "review_note": "生成后需人工核对与真实SKU一致，再把图片路径回填到 primary_image",
                }
            )
    headers = ["sku", "title", "category", "image_status", "image_generation_prompt", "review_note"]
    return csv_response(headers, output), "image_generation_prompts.csv"


def ranked_products() -> list[dict[str, Any]]:
    with connect() as conn:
        settings = load_settings(conn)
        rows = conn.execute("SELECT * FROM products ORDER BY sku").fetchall()
        products = [row_to_product(row, settings) for row in rows]
    products.sort(key=lambda product: product["opportunity"]["score"], reverse=True)
    return products


def export_opportunities() -> tuple[bytes, str]:
    output = []
    for product in ranked_products():
        opp = product["opportunity"]
        output.append(
            {
                "sku": product["sku"],
                "title": product["title"],
                "category": product["category"],
                "score": opp["score"],
                "action": opp["action"],
                "target_platform": opp["platform_name"],
                "landed_cost": opp["landed_cost"],
                "recommended_price": opp["recommended_price"],
                "expected_profit": opp["expected_profit"],
                "expected_margin": opp["expected_margin"],
                "market_price": opp["market_price"],
                "market_sales": opp["market_sales"],
                "test_budget": opp["test_budget"],
                "daily_budget": opp["daily_budget"],
                "break_even_orders": opp["break_even_orders"],
                "primary_blocker": opp["primary_blocker"],
                "risks": "；".join(product["risks"]),
                "supplier": product["supplier"],
                "source_url": product["source_url"],
                "competitor_url": product["competitor_url"],
            }
        )
    headers = [
        "sku",
        "title",
        "category",
        "score",
        "action",
        "target_platform",
        "landed_cost",
        "recommended_price",
        "expected_profit",
        "expected_margin",
        "market_price",
        "market_sales",
        "test_budget",
        "daily_budget",
        "break_even_orders",
        "primary_blocker",
        "risks",
        "supplier",
        "source_url",
        "competitor_url",
    ]
    return csv_response(headers, output), "sku_opportunity_scores.csv"


def markdown_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def export_test_plan() -> tuple[bytes, str]:
    products = [
        product for product in ranked_products()
        if product["opportunity"]["action"] in {"优先7天测试", "小预算测试", "补资料后再测"}
    ][:20]
    lines = [
        "# 7天SKU验证计划",
        "",
        "目标：用小预算验证商品是否值得放量，不用主观判断替代数据。",
        "",
        "## 测试队列",
        "",
        "| 排名 | SKU | 商品 | 平台 | 分数 | 售价 | 单件预估利润 | 预算 | 动作 |",
        "|---:|---|---|---|---:|---:|---:|---:|---|",
    ]
    for index, product in enumerate(products, start=1):
        opp = product["opportunity"]
        lines.append(
            f"| {index} | {product['sku']} | {product['title']} | {opp['platform_name']} | {opp['score']} | "
            f"{opp['recommended_price']} | {opp['expected_profit']} | {opp['test_budget']} | {opp['action']} |"
        )
    if not products:
        lines.append("| - | - | 暂无可测试SKU | - | - | - | - | - | 先补商品资料 |")

    lines.extend(
        [
            "",
            "## 执行节奏",
            "",
            "Day 1：补齐授权、发票/凭证、图片、验样记录；只保留评分前20的SKU。",
            "Day 2：生成上架表，发布商品；标题避免夸大词和资质敏感词。",
            "Day 3：每个SKU小预算测试，预算按表格 daily_budget 执行；不追单量，先看点击和收藏。",
            "Day 4：停掉无点击、低收藏、咨询差的SKU；保留有加购/成交信号的SKU。",
            "Day 5：检查退款、发货时效、客服问题；利润低于最低利润的SKU直接暂停。",
            "Day 6：对成交SKU追加素材和标题版本；预算只加给利润为正且无售后异常的SKU。",
            "Day 7：做决策：放量、继续小测、下架。放量前必须确认供应商库存和售后协议。",
            "",
            "## 放量门槛",
            "",
            "- 单件预估利润 > 最低利润线。",
            "- 订单能在平台承诺时效内履约。",
            "- 退款/投诉原因不是商品本身缺陷。",
            "- 供应商能稳定代发并不放第三方平台广告单。",
            "- 图片、文案、资质不存在明显侵权或虚假宣传风险。",
        ]
    )
    return markdown_bytes("\n".join(lines) + "\n"), "7_day_sku_test_plan.md"


def export_marketing_plan() -> tuple[bytes, str]:
    metrics = build_summary()["metrics"]
    lines = [
        "# Shopify US 饰品品牌获客方案",
        "",
        "## 产品定位",
        "",
        "面向美国男性礼物和自我激励场景的符号饰品品牌。核心卖点不是便宜饰品，而是有意义的日常提醒、礼物表达、套装折扣和稳定可追踪履约。",
        "",
        "## 目标买家",
        "",
        "- 18-44 岁美国男性，关注纪律、目标感、健身、创业、户外或信念表达。",
        "- 伴侣、家人、朋友给男性买礼物的人群。",
        "- 喜欢项链、戒指、手链、礼盒套装，但不想买高价贵金属的人群。",
        "",
        "## 首测商品结构",
        "",
        "- 15-30 个 SKU：吊坠、项链、戒指、手链、礼盒套装。",
        "- 3-5 个主推款用于广告首测，其余作为集合页和加购补充。",
        "- 每个主推款至少有 5 类素材：产品特写、佩戴、礼物场景、故事钩子、套装优惠。",
        "",
        "## 一句话卖点",
        "",
        "Meaningful jewelry for the man becoming more. Ships from China with tracked US delivery.",
        "",
        "## 内容渠道",
        "",
        "- Instagram Reels：符号意义、佩戴场景、开箱礼物、套装优惠。",
        "- Instagram Feed：统一黑白灰视觉，先铺 30 条内容再跑广告。",
        "- Meta Ads：每天 USD 30-50，优先测试 3-5 个主推 SKU。",
        "- 邮件：下单确认、物流通知、延误解释、评价请求和套装复购。",
        "",
        "## 14 天内容节奏",
        "",
        "Day 1-2：确定 3 个品牌价值词和 5 个符号故事，完成主页 bio 和官网链接。",
        "Day 3-5：发布 9 条产品图和佩戴图，每条围绕一个意义表达。",
        "Day 6-8：发布 6 条 Reels，测试开头 2 秒的情绪钩子。",
        "Day 9-11：发布评论、订单、包装、物流透明说明。",
        "Day 12-14：整理表现最好的 5 条素材进入 Meta 广告首测。",
        "",
        "## 当前首测数据",
        "",
        f"- 商品数：{metrics['products']}",
        f"- Shopify 候选：{metrics['shopify_candidates']}",
        f"- 独立站就绪：{metrics['shopify_ready']}",
        f"- Meta 素材就绪：{metrics['meta_assets_ready']}",
        f"- 上线阻断项：{metrics['launch_blockers']}",
        f"- 风险订单：{metrics['risk_orders']}",
        "",
        "## 风控底线",
        "",
        "不要假装美国发货，不要虚标 gold、silver、防水、防过敏、防褪色，不要用未授权图片，不要等广告开跑后才申请收款。页面必须透明说明中国发货、预计时效和退换条件。",
    ]
    return markdown_bytes("\n".join(lines) + "\n"), "marketing_plan.md"


def export_outreach_templates() -> tuple[bytes, str]:
    rows = [
        {
            "channel": "Instagram bio",
            "scenario": "主页简介",
            "message": "Meaningful jewelry for discipline, courage, and the man becoming more. Tracked US delivery. Shop the latest drop below.",
        },
        {
            "channel": "Instagram Reel",
            "scenario": "7秒脚本",
            "message": "Close-up on the pendant. Text: Wear your discipline. Cut to model wearing it. End card: A reminder to keep going. Shop now.",
        },
        {
            "channel": "Meta Ads",
            "scenario": "主文案",
            "message": "A simple piece with a meaning you can carry every day. Ships from China with tracked US delivery. Limited first drop pricing.",
        },
        {
            "channel": "客服邮件",
            "scenario": "物流透明说明",
            "message": "Your order ships from China with full tracking. Processing usually takes 2-4 business days, and estimated US delivery is 7-15 business days after dispatch.",
        },
        {
            "channel": "评论回复",
            "scenario": "材质问题",
            "message": "This piece uses 316L stainless steel with the listed finish. Full material, size, origin, and shipping details are on the product page.",
        },
    ]
    return csv_response(["channel", "scenario", "message"], rows), "outreach_templates.csv"


def seed_demo() -> dict[str, int]:
    sample_products = DATA_DIR / "sample_products.csv"
    sample_orders = DATA_DIR / "sample_orders.csv"
    product_rows = read_csv_file(sample_products)
    order_rows = read_csv_file(sample_orders)
    products = import_products(product_rows)
    orders = import_orders(order_rows)
    return {"products": products["imported"], "orders": orders["imported"]}


def read_csv_file(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def template_csv(kind: str) -> tuple[bytes, str]:
    if kind == "orders":
        headers = ["platform", "order_id", "sku", "qty", "paid_amount", "buyer_name", "phone", "address", "deadline"]
        name = "orders_template.csv"
    elif kind == "approved-images":
        headers = ["category", "tags", "file_path", "source_url", "source", "license", "usage_rights"]
        name = "approved_images_template.csv"
    else:
        headers = [
            "sku",
            "title",
            "supplier",
            "source_url",
            "cost",
            "shipping_cost",
            "pack_cost",
            "stock",
            "lead_days",
            "category",
            "authorized",
            "invoice_available",
            "image_rights",
            "image_urls",
            "primary_image",
            "image_source",
            "image_license",
            "image_prompt",
            "image_status",
            "target_platform",
            "market_price",
            "market_sales",
            "competitor_url",
            "test_budget",
            "quality_checked",
            "supplier_sla_hours",
            "material",
            "plating",
            "size",
            "weight_g",
            "hs_code",
            "country_of_origin",
            "compliance_report_url",
            "product_story",
            "ad_angle",
            "content_status",
            "shopify_handle",
            "shopify_tags",
            "notes",
        ]
        name = "products_template.csv"
    return csv_response(headers, []), name


class Handler(BaseHTTPRequestHandler):
    server_version = "ResellAutomation/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_csv(self, body: bytes, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_download(self, body: bytes, filename: str, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/api/summary":
                self.send_json(build_summary())
                return
            if path == "/api/export/listings":
                body, filename = export_listings(
                    query.get("platform", ["douyin"])[0],
                    query.get("include_risky", ["0"])[0] == "1",
                )
                self.send_csv(body, filename)
                return
            if path == "/api/export/shopify-products":
                body, filename = export_shopify_products(query.get("include_risky", ["0"])[0] == "1")
                self.send_csv(body, filename)
                return
            if path == "/api/export/meta-ad-plan":
                body, filename = export_meta_ad_plan()
                self.send_csv(body, filename)
                return
            if path == "/api/export/us-launch-playbook":
                body, filename = export_us_launch_playbook()
                self.send_download(body, filename, "text/markdown; charset=utf-8")
                return
            if path == "/api/export/purchase-orders":
                body, filename = export_purchase_orders(query.get("include_risky", ["0"])[0] == "1")
                self.send_csv(body, filename)
                return
            if path == "/api/export/image-prompts":
                body, filename = export_image_prompts()
                self.send_csv(body, filename)
                return
            if path == "/api/export/opportunities":
                body, filename = export_opportunities()
                self.send_csv(body, filename)
                return
            if path == "/api/export/test-plan":
                body, filename = export_test_plan()
                self.send_download(body, filename, "text/markdown; charset=utf-8")
                return
            if path == "/api/export/marketing-plan":
                body, filename = export_marketing_plan()
                self.send_download(body, filename, "text/markdown; charset=utf-8")
                return
            if path == "/api/export/outreach-templates":
                body, filename = export_outreach_templates()
                self.send_csv(body, filename)
                return
            if path == "/api/template/products":
                body, filename = template_csv("products")
                self.send_csv(body, filename)
                return
            if path == "/api/template/orders":
                body, filename = template_csv("orders")
                self.send_csv(body, filename)
                return
            if path == "/api/template/approved-images":
                body, filename = template_csv("approved-images")
                self.send_csv(body, filename)
                return
            self.serve_static(path)
        except Exception as exc:  # pragma: no cover - defensive server boundary
            self.send_json({"error": str(exc)}, 500)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        target = (STATIC_DIR / parsed.path.lstrip("/")).resolve()
        if str(target).startswith(str(STATIC_DIR.resolve())) and target.exists() and target.is_file():
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/api/import/products":
                self.send_json(import_products(payload.get("rows", [])))
                return
            if parsed.path == "/api/import/orders":
                self.send_json(import_orders(payload.get("rows", [])))
                return
            if parsed.path == "/api/settings":
                self.send_json(update_settings(payload))
                return
            if parsed.path == "/api/seed":
                self.send_json(seed_demo())
                return
            self.send_json({"error": "not found"}, 404)
        except Exception as exc:  # pragma: no cover - defensive server boundary
            self.send_json({"error": str(exc)}, 500)

    def serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            target = STATIC_DIR / "index.html"
        else:
            target = (STATIC_DIR / path.lstrip("/")).resolve()
            if not str(target).startswith(str(STATIC_DIR.resolve())):
                self.send_error(403)
                return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    init_db()
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"Resell automation console running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server")
    finally:
        server.server_close()


def arg_value(argv: list[str], key: str, default: str = "") -> str:
    if key not in argv:
        return default
    index = argv.index(key)
    if index + 1 >= len(argv):
        return default
    return argv[index + 1]


def run_batch(argv: list[str]) -> int:
    init_db()
    products_path = arg_value(argv, "--products")
    orders_path = arg_value(argv, "--orders")
    platform = normalize_platform(arg_value(argv, "--platform", "douyin"))
    out_dir = Path(arg_value(argv, "--out", str(ROOT / "exports"))).expanduser().resolve()
    include_risky = "--include-risky" in argv
    out_dir.mkdir(parents=True, exist_ok=True)

    if products_path:
        result = import_products(read_csv_file(Path(products_path).expanduser().resolve()))
        print(f"Imported products: {result['imported']} imported, {result['skipped']} skipped")
    if orders_path:
        result = import_orders(read_csv_file(Path(orders_path).expanduser().resolve()))
        print(f"Imported orders: {result['imported']} imported, {result['skipped']} skipped")

    listing_body, listing_name = export_listings(platform, include_risky)
    shopify_body, shopify_name = export_shopify_products(include_risky)
    meta_body, meta_name = export_meta_ad_plan()
    playbook_body, playbook_name = export_us_launch_playbook()
    purchase_body, purchase_name = export_purchase_orders(include_risky)
    prompt_body, prompt_name = export_image_prompts()
    opportunity_body, opportunity_name = export_opportunities()
    test_plan_body, test_plan_name = export_test_plan()
    marketing_body, marketing_name = export_marketing_plan()
    outreach_body, outreach_name = export_outreach_templates()
    listing_path = out_dir / listing_name
    shopify_path = out_dir / shopify_name
    meta_path = out_dir / meta_name
    playbook_path = out_dir / playbook_name
    purchase_path = out_dir / purchase_name
    prompt_path = out_dir / prompt_name
    opportunity_path = out_dir / opportunity_name
    test_plan_path = out_dir / test_plan_name
    marketing_path = out_dir / marketing_name
    outreach_path = out_dir / outreach_name
    listing_path.write_bytes(listing_body)
    shopify_path.write_bytes(shopify_body)
    meta_path.write_bytes(meta_body)
    playbook_path.write_bytes(playbook_body)
    purchase_path.write_bytes(purchase_body)
    prompt_path.write_bytes(prompt_body)
    opportunity_path.write_bytes(opportunity_body)
    test_plan_path.write_bytes(test_plan_body)
    marketing_path.write_bytes(marketing_body)
    outreach_path.write_bytes(outreach_body)

    summary = build_summary()["metrics"]
    print(f"Wrote {listing_path}")
    print(f"Wrote {shopify_path}")
    print(f"Wrote {meta_path}")
    print(f"Wrote {playbook_path}")
    print(f"Wrote {purchase_path}")
    print(f"Wrote {prompt_path}")
    print(f"Wrote {opportunity_path}")
    print(f"Wrote {test_plan_path}")
    print(f"Wrote {marketing_path}")
    print(f"Wrote {outreach_path}")
    print(
        "Summary: "
        f"{summary['products']} products, "
        f"{summary['publishable']} publishable, "
        f"{summary['test_ready']} test-ready, "
        f"{summary['orders']} orders, "
        f"{summary['purchase_ready']} purchase-ready, "
        f"{summary['risk_orders']} risk orders"
    )
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "batch":
        return run_batch(argv[1:])
    host = "127.0.0.1"
    port = int(os.environ.get("PORT", "8765"))
    open_browser = "--open" in argv
    if "--host" in argv:
        host = argv[argv.index("--host") + 1]
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    run_server(host, port, open_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
