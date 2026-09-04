#!/usr/bin/env python3
"""按 ASIN 抓取单个亚马逊商品详情（供质检 Agent 的 get_listing 工具调用）。

复用 enrich_details_20260803_v2.py 的解析逻辑，并：
- 增加主图 URL 提取（#landingImage data-old-hires / #imgBlkFront data-a-dynamic-image）
- 增加 captcha / Robot Check 检测与 ASIN 格式校验
- 桌面 UA 失败自动回退移动端 UA

返回统一结构 dict，含 _status（ok / error / captcha）与 _msg，便于 Dify Agent 判断。
"""
import json
import re
import time
import random

import requests
from bs4 import BeautifulSoup

DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$", re.IGNORECASE)

_EMPTY = {
    "title": "", "brand": "", "price": "", "bullets": [], "description": "",
    "rating": None, "review_count": None, "image_url": "", "url": "",
    "aplus": "", "has_aplus": False,
}

# 反爬对抗：复用 session 拿一次 cookie，再带 referer/sec-fetch-* 抓商品页
_SESSION = None


def _session():
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": DESKTOP_UA,
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            # 预热拿 set-cookie（amazon 部分反爬靠 session 判定）
            s.get("https://www.amazon.com/", timeout=10)
        except Exception:
            pass
        _SESSION = s
    return _SESSION


def _fetch(asin, ua, timeout=30, retries=2):
    url = f"https://www.amazon.com/dp/{asin}"
    headers = {
        "User-Agent": ua,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Referer": "https://www.amazon.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    sess = _session()
    last_err = None
    for _ in range(retries):
        try:
            resp = sess.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                low = resp.text.lower()
                if "captcha" in low[:8000] or "robot check" in low:
                    return None, "captcha"
                if "currently unavailable" in low[:8000]:
                    # 商品存在但下架，仍可抓标题/五点
                    return resp.text, None
                return resp.text, None
            last_err = f"status={resp.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(random.uniform(2, 4))
    return None, last_err


def _parse_price(soup):
    for sel in [".a-price .a-offscreen", ".a-price-whole", "#apexPriceToPay",
                "#priceblock_ourprice", "#priceblock_dealprice",
                '[data-a-color="price"] .a-offscreen']:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(strip=True)
            if txt:
                return txt  # 原样返回，保留 $/¥/US$ 等符号
    return ""


def _parse_image(soup):
    el = soup.select_one("#landingImage")
    if el:
        hires = el.get("data-old-hires") or el.get("src")
        if hires:
            return hires
    el = soup.select_one("#imgBlkFront")
    if el and el.get("data-a-dynamic-image"):
        try:
            d = json.loads(el["data-a-dynamic-image"])
            # 取分辨率最高的那张
            return max(d, key=lambda k: (d[k][0] if d[k] else 0))
        except Exception:
            pass
    el = soup.select_one("img.a-dynamic-image")
    if el and el.get("src"):
        return el["src"]
    return ""


def _parse(html):
    soup = BeautifulSoup(html, "html.parser")
    out = dict(_EMPTY)

    # 标题
    t = soup.select_one("#productTitle")
    if t:
        out["title"] = t.get_text(strip=True)

    # 品牌
    b = soup.select_one("#bylineInfo")
    if b:
        txt = re.sub(r"^(Visit the |Brand: )", "", b.get_text(strip=True))
        txt = re.sub(r"\s+(Store|Brand)$", "", txt)
        out["brand"] = txt

    # 五点描述
    for li in soup.select("#feature-bullets ul li:not(.aok-hidden)"):
        text = li.get_text(" ", strip=True)
        if text and not text.lower().startswith("read more"):
            out["bullets"].append(text)

    # 描述 / A+ 页 —— 二者必须分开，不可混用
    # 背景：商品启用 A+ 后，详情页原 description 区域会被 A+ 图文模块取代。
    #       A+ 内容不被搜索索引（无 SEO 价值），description 才被索引。
    #       旧版把 A+ 顶替成 description，导致抓到碎片文字（如 "Road Bikes"）
    #       并被质检误判为"描述错填/空置"，属数据污染。
    d = soup.select_one("#productDescription")
    if d:
        out["description"] = d.get_text(" ", strip=True)[:2000]

    a = soup.select_one("#aplus_feature_div, #aplus")
    if a is not None:
        aplus_text = a.get_text(" ", strip=True)
        has_img = bool(a.select("img"))
        # 有配图 或 有实质文本 → 才算真的启用了 A+（空占位符不算）
        # 注意：纯图片型 A+ 的 get_text 可能几乎为空，但 has_aplus 仍应为 True，
        #       否则质检会误判成"既无 description 也无 A+ = 描述缺失"
        if has_img or len(aplus_text.strip()) >= 20:
            out["has_aplus"] = True
            out["aplus"] = aplus_text[:2000] if len(aplus_text.strip()) >= 20 else ""

    # 价格
    out["price"] = _parse_price(soup)

    # 评分
    r = (soup.select_one('[data-hook="average-star-rating"] .a-icon-alt')
         or soup.select_one(".a-icon-alt"))
    if r:
        m = re.search(r"([\d.]+)\s*out\s*of\s*5", r.get_text(strip=True), re.I)
        if m:
            out["rating"] = float(m.group(1))

    # 评论数
    rc = soup.select_one(".rating-count") or soup.select_one("#acrCustomerReviewText")
    if rc:
        m = re.search(r"([\d,]+)", rc.get_text(strip=True))
        if m:
            out["review_count"] = int(m.group(1).replace(",", ""))

    # 主图
    out["image_url"] = _parse_image(soup)
    return out


def scrape_listing(asin):
    """按 ASIN 抓取单个商品详情。

    返回 dict，字段：asin, title, brand, price, bullets[], description,
    aplus, has_aplus, rating, review_count, image_url, url, _status, _msg, _html_size

    字段说明（description vs aplus，重要）：
      description  标准商品描述（#productDescription），~2000 字符，**被搜索索引**，有 SEO 价值
      aplus        A+ 图文内容（#aplus_feature_div），**不被搜索索引**，只有转化价值
      has_aplus    该商品是否启用了 A+ 内容
      注意：商品启用 A+ 后，详情页原 description 区域会被 A+ 取代显示，
            但 description 字段本身仍存在且仍被索引。二者不可混为一谈。

    _status:
      ok      抓取并解析成功（部分字段可能为空，属正常）
      error   网络失败 / ASIN 无效
      captcha 触发亚马逊反爬验证码，需稍后重试或换代理
    """
    asin = (asin or "").strip().upper()
    if not ASIN_RE.match(asin):
        return {"asin": asin, "_status": "error", "_msg": "ASIN 格式无效（应为10位字母数字）",
                "url": "", **_EMPTY}

    html, err = _fetch(asin, DESKTOP_UA)
    if html is None:
        html, err = _fetch(asin, MOBILE_UA)  # 桌面失败回退移动端
    if html is None:
        return {"asin": asin, "_status": "error", "_msg": f"抓取失败: {err}",
                "url": f"https://www.amazon.com/dp/{asin}", **_EMPTY}

    data = _parse(html)
    data["asin"] = asin
    data["url"] = f"https://www.amazon.com/dp/{asin}"
    data["_html_size"] = len(html)  # 诊断用：真实 amazon 商品页通常 > 500KB
    return data


if __name__ == "__main__":
    import sys
    a = sys.argv[1] if len(sys.argv) > 1 else "B08N5WRWNW"
    print(json.dumps(scrape_listing(a), ensure_ascii=False, indent=2))
