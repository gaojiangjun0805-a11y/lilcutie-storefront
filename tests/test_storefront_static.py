import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"


class StorefrontStaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding="utf-8")

    def test_homepage_is_customer_facing_storefront(self):
        self.assertIn("<title>lilcutie", self.html)
        self.assertIn('aria-label="lilcutie home"', self.html)
        self.assertNotIn("Iron Vow", self.html)
        self.assertIn("Shop meaningful jewelry", self.html)
        self.assertNotIn("运营控制台", self.html)
        self.assertNotIn("导入商品库", self.html)

    def test_storefront_has_conversion_paths(self):
        for anchor in ['href="#shop"', 'href="#drops"', 'href="#shipping"', 'href="#contact"']:
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, self.html)
        self.assertIn('id="cartDrawer"', self.html)
        self.assertIn('data-add="${product.id}"', self.html)
        self.assertIn('data-add-bundle', self.html)
        self.assertIn('data-product-modal', self.html)

    def test_storefront_has_transparent_cross_border_policy(self):
        self.assertIn("Ships from China", self.html)
        self.assertIn("7-15 business days", self.html)
        self.assertIn("14-day returns", self.html)
        self.assertIn("Track Order", self.html)

    def test_storefront_has_placeholder_product_catalog(self):
        expected_products = [
            "Golden Shield Pendant",
            "Black Link Bracelet",
            "Silver Signet Ring",
            "Midnight Pendant Set",
            "Celestial Charm Necklace",
            "Obsidian Cuff Bracelet",
        ]
        for product in expected_products:
            with self.subTest(product=product):
                self.assertIn(product, self.html)
        for product_id in ["golden-shield", "black-link", "silver-signet", "midnight-set", "celestial-charm", "obsidian-cuff"]:
            with self.subTest(product_id=product_id):
                self.assertIn(f'id: "{product_id}"', self.html)
        self.assertGreaterEqual(self.html.count("media/products/lilcutie-"), 8)

    def test_storefront_has_five_language_interfaces(self):
        self.assertIn('data-language-select', self.html)
        for language_code, label in [
            ("en", "English"),
            ("zh", "中文"),
            ("ja", "日本語"),
            ("de", "Deutsch"),
            ("es", "Español"),
        ]:
            with self.subTest(language_code=language_code):
                self.assertIn(f'value="{language_code}"', self.html)
                self.assertIn(f'{language_code}: {{', self.html)
                self.assertIn(label, self.html)
        for translation in [
            "Shop meaningful jewelry",
            "选购有意义的饰品",
            "意味のあるジュエリーを見る",
            "Bedeutungsvollen Schmuck kaufen",
            "Comprar joyería con significado",
        ]:
            with self.subTest(translation=translation):
                self.assertIn(translation, self.html)
        self.assertIn("function setLanguage", self.html)
        self.assertIn("localStorage.setItem(\"lilcutie-language\"", self.html)


if __name__ == "__main__":
    unittest.main()
