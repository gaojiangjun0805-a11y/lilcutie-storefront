import csv
import io
import tempfile
import unittest
from pathlib import Path

import app


class ChinaDtcLaunchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db_path = app.DB_PATH
        app.DB_PATH = Path(self.tmp.name) / "launch.db"
        app.init_db()

    def tearDown(self):
        app.DB_PATH = self.old_db_path
        self.tmp.cleanup()

    def import_ready_jewelry(self):
        return app.import_products(
            [
                {
                    "sku": "HWG-001",
                    "title": "Discipline Shield Pendant",
                    "supplier": "Dongguan Metal Studio",
                    "source_url": "https://supplier.example/hwg-001",
                    "cost": "5.20",
                    "shipping_cost": "4.80",
                    "pack_cost": "1.10",
                    "stock": "120",
                    "lead_days": "2",
                    "category": "mens jewelry pendant",
                    "authorized": "yes",
                    "invoice_available": "yes",
                    "image_rights": "yes",
                    "primary_image": "/media/products/HWG-001/approved-01.jpg",
                    "image_source": "owned studio photo",
                    "image_license": "brand owned",
                    "target_platform": "shopify_us",
                    "market_price": "49",
                    "market_sales": "1800",
                    "test_budget": "250",
                    "quality_checked": "yes",
                    "supplier_sla_hours": "36",
                    "material": "316L stainless steel",
                    "plating": "PVD gold",
                    "size": "22 mm pendant, 22 inch chain",
                    "weight_g": "28",
                    "hs_code": "711719",
                    "country_of_origin": "China",
                    "compliance_report_url": "https://docs.example/reach-lead-nickel.pdf",
                    "product_story": "A daily reminder to keep promises when nobody is watching.",
                    "ad_angle": "Wear your discipline.",
                    "content_status": "ready",
                    "shopify_tags": "pendant,mens-jewelry,best-seller",
                }
            ]
        )

    def test_shopify_us_settings_are_available(self):
        with app.connect() as conn:
            settings = app.load_settings(conn)

        self.assertIn("shopify_us", settings)
        self.assertEqual(app.PLATFORM_NAMES["shopify_us"], "Shopify US")

    def test_import_keeps_jewelry_launch_fields_and_metrics(self):
        result = self.import_ready_jewelry()

        self.assertEqual(result, {"imported": 1, "skipped": 0})
        summary = app.build_summary()
        product = summary["products"][0]

        self.assertEqual(product["material"], "316L stainless steel")
        self.assertEqual(product["plating"], "PVD gold")
        self.assertEqual(product["hs_code"], "711719")
        self.assertEqual(product["opportunity"]["platform"], "shopify_us")
        self.assertGreaterEqual(summary["metrics"]["shopify_ready"], 1)
        self.assertEqual(summary["metrics"]["launch_blockers"], 0)

    def test_shopify_product_export_uses_shopify_csv_shape(self):
        self.import_ready_jewelry()

        body, filename = app.export_shopify_products()
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))

        self.assertEqual(filename, "shopify_us_products.csv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Handle"], "discipline-shield-pendant")
        self.assertEqual(rows[0]["Variant SKU"], "HWG-001")
        self.assertEqual(rows[0]["Variant Grams"], "28")
        self.assertEqual(rows[0]["Variant Inventory Tracker"], "shopify")
        self.assertEqual(rows[0]["Google Shopping / Custom Product"], "TRUE")
        self.assertIn("Ships from China", rows[0]["Body (HTML)"])
        self.assertIn("316L stainless steel", rows[0]["Body (HTML)"])

    def test_meta_ad_plan_exports_launch_assets(self):
        self.import_ready_jewelry()

        body, filename = app.export_meta_ad_plan()
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))

        self.assertEqual(filename, "meta_ad_test_plan.csv")
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["sku"], "HWG-001")
        self.assertEqual(rows[0]["market"], "United States")
        self.assertEqual(rows[0]["destination"], "Shopify product page")
        self.assertIn(rows[0]["creative_type"], {"product close-up", "model wear", "gift scene", "story hook", "bundle offer"})
        self.assertIn("Wear your discipline.", rows[0]["primary_text"])


if __name__ == "__main__":
    unittest.main()
