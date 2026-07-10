# 中国发货独立站运营控制台

这是一个本地运行的跨境饰品首测工具，面向“大陆公司 + Shopify 独立站 + Instagram/Meta 广告 + 中国直邮美国”的落地模式。

它把供应商商品表和 Shopify 订单表导入后，自动完成利润测算、风控筛查、Shopify 商品 CSV、Meta 广告素材计划、7 天测试计划、采购单和美国上线手册导出。

它不会做这些事：

- 盗用图片、搬运别人的设计和品牌文案
- 假装美国本土发货
- 虚标 gold、silver、防水、防过敏、防褪色等未经检测支撑的卖点
- 使用灰产广告账户、买号或规避平台风控
- 通过未授权接口抓取、下单或处理客户数据

## 启动

```bash
python3 app.py --open
```

默认地址：

```text
http://127.0.0.1:8765
```

如果端口被占用，可以换一个：

```bash
python3 app.py --port 8776 --open
```

## 推荐工作流

1. 注册英文品牌名、`.com` 域名、Instagram 用户名和 Facebook Page。
2. 准备 15-30 个首批饰品 SKU，优先男士吊坠、项链、戒指、手链、礼盒套装。
3. 用“商品模板”整理供应商数据，重点填材质、镀层、尺寸、克重、HS Code、原产国、检测报告、图片授权、素材状态。
4. 导入商品库，先看“风控看板”和“美国首测”标签页。
5. 修复阻断项，例如缺图、未验样、缺检测报告、素材未 ready。
6. 导出 `Shopify 商品 CSV`，导入 Shopify 后再人工检查商品页。
7. 导出 `Meta 广告计划`，按产品特写、佩戴、礼物、故事钩子、套装优惠制作素材。
8. 先只开美国市场，Meta 每天 USD 30-50 小预算测试 7 天。
9. 导入 Shopify 订单 CSV，导出采购单给供应商、ERP 或物流商履约。
10. 每单必须有 tracking，物流延误要主动通知，降低 PayPal 争议和信用卡拒付。

## 批处理模式

不打开网页也可以跑完整链路：

```bash
python3 app.py batch \
  --products data/sample_products.csv \
  --orders data/sample_orders.csv \
  --platform shopify_us \
  --out exports
```

默认只导出无风控阻断的数据。如果只是内部排查，可以追加：

```bash
--include-risky
```

批处理会生成：

```text
exports/shopify_us_listing_export.csv
exports/shopify_us_products.csv
exports/meta_ad_test_plan.csv
exports/us_shopify_launch_playbook.md
exports/supplier_purchase_orders.csv
exports/image_generation_prompts.csv
exports/sku_opportunity_scores.csv
exports/7_day_sku_test_plan.md
exports/marketing_plan.md
exports/outreach_templates.csv
```

## 商品 CSV 字段

商品表支持中文或英文字段名。核心字段：

```text
sku,title,supplier,source_url,cost,shipping_cost,pack_cost,stock,lead_days,category
authorized,invoice_available,image_rights,primary_image,target_platform,market_price
quality_checked,supplier_sla_hours,material,plating,size,weight_g,hs_code
country_of_origin,compliance_report_url,product_story,ad_angle,content_status
shopify_handle,shopify_tags,notes
```

关键字段建议：

- `target_platform`：美国独立站填 `shopify_us`
- `material`：例如 `316L stainless steel`
- `plating`：例如 `PVD gold`、`black vacuum plating`
- `size`：项链长度、吊坠尺寸、戒指 US 尺码等
- `weight_g`：克重，用于 Shopify 重量字段和物流估算
- `hs_code`：饰品常见可先填供应商/报关行确认后的编码
- `country_of_origin`：中国发货通常填 `China`
- `compliance_report_url`：铅、镉、镍等检测报告链接或内部文件地址
- `content_status`：素材齐全后填 `ready`
- `primary_image`：已授权图片路径，例如 `/media/approved/discipline-pendant.svg`

## 订单 CSV 字段

最小字段：

```text
platform,order_id,sku,qty,paid_amount,buyer_name,phone,address,deadline
```

美国 Shopify 订单的 `platform` 填：

```text
shopify_us
```

## 风控规则

系统会阻断或提示这些问题：

- 缺少授权/代发协议确认
- 发票或进货凭证未确认
- 图片/视频授权未确认
- 缺少可用主图
- 样品未验货
- 库存不足或发货 SLA 偏慢
- Shopify US 饰品缺材质、尺寸、克重、HS Code、原产国、检测报告
- Instagram/广告素材未就绪
- 儿童、穿刺、贵金属、天然宝石等首阶段高风险方向

## 首测建议

- 店铺主币种设 USD。
- 收款先准备 PayPal Business 中国商户，再申请一个 Shopify 支持的第三方信用卡收单。
- 页面写保守物流承诺：处理时间 2-4 个工作日，美国运输 7-15 个工作日。
- 满额免邮建议先设在 USD 75-99。
- 广告首轮只推 3-5 个主 SKU，不要全站一起推。
- 首轮广告预算控制在 USD 1,000-2,000。
- 30-50 单跑通后再扩 SKU，100 单/月后再考虑美国海外仓、香港实体或更多市场。

## 示例数据

`data/sample_products.csv` 已内置 4 个美国首测饰品 SKU：

- `USJ-001` Discipline Shield Pendant，可上线
- `USJ-002` Resolve Bar Bracelet，可上线
- `USJ-003` North Star Signet Ring，可上线
- `USJ-004` Faith Anchor Gift Set，故意保留缺报告/未验样阻断项

打开网页后点击“加载示例”，即可看到 Shopify 候选、独立站就绪、Meta 素材就绪和上线阻断指标。
