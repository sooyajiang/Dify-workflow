"""
构建 Dify 知识库数据集（竞品情报）
================================
从本地 BSR 抓取数据中提取竞品全文（五点 + 描述），清洗 Amazon A+ 噪声，
按 ASIN 去重，生成 Dify 知识库可导入的 CSV（title + content 两列）。

用法:
    python build_dify_knowledge.py
产物:
    dify_knowledge_kids_bikes.csv   (每行一个竞品, Dify 导入即可)
"""
import json
import csv
import re
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "amazon_bsr_consolidated.json")
OUT = os.path.join(HERE, "dify_knowledge_kids_bikes.csv")


# ---------- 清洗工具 ----------
def bullets_to_text(b):
    """五点描述统一成换行文本。"""
    if not b:
        return ""
    if isinstance(b, list):
        return "\n".join(str(x).strip() for x in b if str(x).strip())
    return str(b).strip()


def clean_description(text):
    """去掉 Amazon A+ 的噪声前缀, 保留真正的产品描述。"""
    if not text:
        return ""
    t = str(text)
    # 去掉 "Brief content visible ... Product description" 这类折叠提示
    m = re.search(r"Product description\s*(.*)", t, re.S | re.I)
    if m:
        t = m.group(1)
    # 去掉常见按钮/噪声词
    t = re.sub(r"\s*(Add to Cart|Buying Options|Customer Reviews|See more|Read full content|double tap to read)\s*",
               " ", t, flags=re.I)
    # 去掉孤立的价格表噪声 "CNY 742.60" / "Price — no data"
    t = re.sub(r"(CNY|USD)\s*[\d.,]+\s*", " ", t)
    t = re.sub(r"Price\s*[—-]\s*no data", " ", t, flags=re.I)
    # 压缩多余空白
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def scrub(t):
    if not t:
        return ""
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


# ---------- 主流程 ----------
def main():
    rows = json.load(open(SRC, encoding="utf-8"))

    # 按 ASIN 去重: 优先保留有内容的版本
    best = {}
    for r in rows:
        asin = r.get("asin")
        if not asin:
            continue
        has_content = bool(bullets_to_text(r.get("bullets")) or clean_description(r.get("description")))
        cur = best.get(asin)
        if cur is None or (has_content and not cur["_has"]):
            best[asin] = {"r": r, "_has": has_content}

    records = []
    for asin, item in best.items():
        r = item["r"]
        bullets = bullets_to_text(r.get("bullets"))
        desc = clean_description(r.get("description"))
        brand = r.get("brand") or "Unknown"
        title = f"Kids Bike 竞品 - {brand} {asin} (榜单#{r.get('rank')}, {r.get('date')})"

        content = "\n".join([
            f"# {brand} - {r.get('title','')}",
            "",
            f"- ASIN: {asin}",
            f"- 榜单排名: #{r.get('rank')} (抓取日期 {r.get('date')})",
            f"- 品牌: {brand}",
            f"- 价格: {r.get('price_usd','')}",
            f"- 评分: {r.get('rating','')}/5 ({r.get('reviews','')} 条评论)",
            f"- 链接: {r.get('url','')}",
            "",
            "## 五点描述 (Bullet Points)",
            scrub(bullets) if bullets else "(无)",
            "",
            "## 产品描述 (Description)",
            scrub(desc) if desc else "(无)",
        ])
        records.append({"title": title, "content": content})

    # 按品牌+排名排序, 稳定输出
    records.sort(key=lambda x: x["title"])

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["title", "content"])
        w.writeheader()
        w.writerows(records)

    print(f"✅ 生成 {os.path.basename(OUT)}: 共 {len(records)} 条竞品记录 (去重后, 原始 {len(rows)} 条)")


if __name__ == "__main__":
    main()
