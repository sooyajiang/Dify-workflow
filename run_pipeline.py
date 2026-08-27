#!/usr/bin/env python3
"""Amazon 类目 BSR 情报管线 (v4, 单管线整合版).

流程: 读 category_directory.json -> 抓类目 BSR 榜单 -> 抓每个 ASIN 详情(强制 USD) ->
质量标记 -> 写飞书多维表格(Base, bitable API).

注意: 抓取受 Amazon ToS 约束, 仅用于个人 demo / 竞品监控研究.
"""
import json
import os
import re
import time
import random
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup

# ---------------- 配置 ----------------
# 配置支持环境变量覆盖(部署到云函数/服务器时更安全, 本地不填则用默认值)
APP_ID = os.environ.get("FS_APP_ID", "cli_aae6d6fabe3adbe8")
APP_SECRET = os.environ.get("FS_APP_SECRET", "")  # 部署到 Render 时请在环境变量中配置 FS_APP_SECRET（勿硬编码）
BASE_URL = "https://open.feishu.cn/open-apis"

# 飞书多维表格(Base) 目标: 用户在自己云盘建好的 Base, 已把自建应用加为「可编辑」协作者.
# 应用需开通 bitable:app(查看/编辑多维表格)权限并发布版本.
BASE_APP_TOKEN = os.environ.get("FS_BASE_TOKEN", "")  # 部署到 Render 时请在环境变量中配置 FS_BASE_TOKEN（勿硬编码）
BASE_TABLE_ID = os.environ.get("FS_TABLE_ID", "tbld8CYX6PpyUdzg")

# 类目目录: 默认同目录(category_directory.json), 部署时一起上传即可
CATEGORY_DIR_PATH = os.environ.get(
    "CATEGORY_DIR_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "category_directory.json"))
SITE = "https://www.amazon.com"

# 强制 USD: locale cookie + 可选 US 邮编加固
US_ZIP = "10001"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

# UA 池: 每次请求轮换, 降低被 Amazon 按固定指纹识别的概率
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/118.0 Safari/537.36",
]


# ---------------- 飞书多维表格(Base) ----------------
def feishu_token():
    r = requests.post(f"{BASE_URL}/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=30)
    return r.json()["tenant_access_token"]


def _to_float(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(v):
    if v is None:
        return None
    s = re.sub(r"[^\d]", "", str(v))
    return int(s) if s else None


def build_records(all_rows):
    """把长表行(14 列)映射成 Base 记录. 列顺序见 process_category 的 rows.append."""
    records = []
    for row in all_rows:
        records.append({"fields": {
            "抓取日期": row[0],
            "类目节点ID": row[1],
            "排名": int(row[2]) if str(row[2]).strip().isdigit() else None,
            "ASIN": row[3],
            "品牌": row[4],
            "标题": row[5],
            "价格USD": row[6],
            "评分": _to_float(row[7]),
            "评论数": _to_int(row[8]),
            "类目内BSR": row[9],
            "五点描述": row[10],
            "商品描述": row[11],
            "链接": row[12],
            "数据质量": row[13],
        }})
    return records


def bitable_write(token, records):
    """批量写入 Base, 每次最多 400 条."""
    BATCH = 400
    total = 0
    for i in range(0, len(records), BATCH):
        chunk = records[i:i + BATCH]
        r = requests.post(
            f"{BASE_URL}/bitable/v1/apps/{BASE_APP_TOKEN}/tables/{BASE_TABLE_ID}/records/batch_create",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"records": chunk}, timeout=120)
        j = r.json()
        print(f"  写入 {len(chunk)} 条: code={j.get('code')} msg={j.get('msg')}")
        if j.get("code") == 0:
            total += len(j.get("data", {}).get("records", []))
        else:
            print("  失败详情:", j.get("msg"))
            break
    return total


def feishu_today_exists(token, today):
    """幂等判断: 今天是否已写过数据, 避免重复行."""
    r = requests.get(
        f"{BASE_URL}/bitable/v1/apps/{BASE_APP_TOKEN}/tables/{BASE_TABLE_ID}/records",
        headers={"Authorization": f"Bearer {token}"},
        params={"page_size": 100}, timeout=30)
    for it in r.json().get("data", {}).get("items", []):
        if it.get("fields", {}).get("抓取日期") == today:
            return True
    return False


# ---------------- 本地缓存(替代飞书, 项目A 不依赖飞书) ----------------
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache")

def _rows_to_dicts(rows):
    """长表行(14列) -> 与 feishu_read_all 一致的字典列表, 供 build_query_payload 复用."""
    out = []
    for r in rows:
        out.append({
            "date": r[0], "cat_node": r[1], "rank": r[2], "asin": r[3],
            "brand": (r[4] or "未知"), "title": r[5], "price": r[6],
            "rating": r[7], "reviews": r[8], "quality": r[13], "url": r[12],
        })
    return out

def save_local(node, dicts, date):
    """把某类目抓取结果存本地 JSON(按 node 隔离)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{node}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"node": node, "date": date, "rows": dicts}, f, ensure_ascii=False)

def load_local_all():
    """合并读取所有本地缓存类目, 返回字典列表(结构同 feishu_read_all)."""
    rows = []
    if not os.path.isdir(CACHE_DIR):
        return rows
    for fn in sorted(os.listdir(CACHE_DIR)):
        if fn.endswith(".json"):
            try:
                d = json.load(open(os.path.join(CACHE_DIR, fn), encoding="utf-8"))
                rows.extend(d.get("rows", []))
            except Exception:
                pass
    return rows


# ---------------- 抓取 ----------------
session = requests.Session()
session.headers.update(HEADERS)
session.cookies.set("i18n-prefs", "CURRENCY:USD&LOCALE:en_US", domain=".amazon.com")
session.cookies.set("lc-main", "en_US", domain=".amazon.com")


def _set_us_zip():
    """尽力用 US 邮编锁定配送地(用户要求). 失败不影响 i18n-prefs 的 USD 强制."""
    try:
        session.post(f"{SITE}/gp/delivery/ajax-address-change.html",
                     data={"locationType": "COUNTRY", "countryCode": "US", "zipCode": US_ZIP},
                     timeout=15)
    except Exception:
        pass


def fetch(url, retries=3):
    for i in range(retries):
        try:
            session.headers["User-Agent"] = random.choice(UA_POOL)
            r = session.get(url, timeout=30, allow_redirects=True)
            if r.status_code == 200 and "captcha" not in r.text.lower()[:3000]:
                return r.text
        except Exception as e:
            print(f"    重试{i+1}: {e}")
        time.sleep(1 + random.random() * 1)
    return None


def parse_bsr(html):
    soup = BeautifulSoup(html, "lxml")
    items, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/dp/([A-Z0-9]{10})")):
        href = a.get("href", "")
        m = re.search(r"/dp/([A-Z0-9]{10})", href)
        if not m:
            continue
        asin = m.group(1)
        if asin in seen:
            continue
        rm = re.search(r"d_sccl_(\d+)", href)
        rank = int(rm.group(1)) if rm else len(items) + 1
        title = a.get_text(strip=True)
        if not title:
            img = a.find("img")
            title = img.get("alt", "") if img else ""
        seen.add(asin)
        items.append({"rank": rank, "asin": asin, "title": title})
    items.sort(key=lambda x: x["rank"])
    return items[:20]


def extract_detail(html):
    soup = BeautifulSoup(html, "lxml")
    res = {"bullets": [], "description": "", "price_usd": "", "rating": "",
           "review_count": "", "title": "", "brand": "", "bsr_in_category": "",
           "currency_flag": ""}

    # 标题
    for sid in ["productTitle", "title"]:
        t = soup.find(["span", "h1"], {"id": sid})
        if t:
            res["title"] = t.get_text(strip=True)
            break
    if not res["title"]:
        tt = soup.find("title")
        if tt:
            res["title"] = re.sub(r"^Amazon\.com\s*:?\s*", "", tt.get_text(strip=True))

    # 价格 (USD 优先)
    price = ""
    for sel in [("span", {"id": "priceblock_ourprice"}),
                ("span", {"id": "priceblock_dealprice"}),
                ("span", {"id": "apexPriceToPay"}),
                ("span", {"class": "a-price-whole"})]:
        tag = soup.find(*sel)
        if tag:
            if sel[1].get("class") == "a-price-whole":
                frac = soup.find("span", {"class": "a-price-fraction"})
                price = f"${tag.get_text(strip=True)}{frac.get_text(strip=True) if frac else ''}"
                break
            txt = tag.get_text(strip=True)
            if "$" in txt:
                price = txt
                break
    if not price:
        div = soup.find("div", {"id": "corePriceDisplay_desktop_feature_div"}) or \
              soup.find("span", {"class": "a-offscreen"})
        if div:
            m = re.search(r'([$€£¥₹]\s?[\d,]+\.?\d*)', div.get_text())
            if m:
                price = m.group(1)
    res["price_usd"] = price.strip()

    # 评分
    r = soup.find("span", {"class": "a-icon-alt"})
    if r:
        m = re.search(r'(\d+\.?\d*)\s*out of\s*\d+', r.get_text())
        if m:
            res["rating"] = m.group(1)
    if not res["rating"]:
        for s in soup.find_all("span"):
            m = re.match(r'^(\d+\.?\d*)\s*out of\s*5\s*stars?$', s.get_text(strip=True))
            if m:
                res["rating"] = m.group(1)
                break

    # 评论数
    rc = soup.find("span", {"id": "acrCustomerReviewText"})
    if rc:
        res["review_count"] = rc.get_text(strip=True).strip("()")

    # 五点
    bd = soup.find("div", {"id": "feature-bullets"}) or soup.find("div", {"id": "featurebullets_feature_div"})
    if bd:
        for li in bd.find_all("li"):
            txt = li.get_text(strip=True)
            if txt and "Show more" not in txt and len(txt) > 10:
                res["bullets"].append(txt)
    if not res["bullets"]:
        ab = soup.find(string=lambda t: t and "About this item" in str(t))
        if ab:
            c = ab.parent
            for _ in range(5):
                c = c.parent if c else None
                if not c:
                    break
                lis = c.find_all("li")
                if lis:
                    res["bullets"] = [l.get_text(strip=True) for l in lis
                                      if len(l.get_text(strip=True)) > 10]
                    break

    # 描述
    d = soup.find("div", {"id": "productDescription"})
    if d:
        res["description"] = d.get_text(separator=" ", strip=True)[:3000]

    # 品牌
    b = soup.find("a", {"id": "bylineInfo"})
    if b:
        brand = re.sub(r"^(Visit the |Brand: )", "", b.get_text(strip=True))
        # 去掉亚马逊店铺后缀, 如 "cubsala Store" -> "cubsala"
        brand = re.sub(r"\s+store$", "", brand, flags=re.IGNORECASE).strip()
        res["brand"] = brand

    # 类目内 BSR
    # 关键修复(8/12): 原始 HTML 中 "#N" 与 "in" 之间隔着 </span>/<a> 等标签,
    # 直接在 html 上用 [^<] 匹配会立刻被标签阻断而永远失败。改为先在纯文本上匹配。
    text = soup.get_text(" ")
    m = re.search(r'#\d[\d,]*\s*in\s+[A-Za-z0-9 &;\'’/-]{2,40}', text)
    if m:
        res["bsr_in_category"] = m.group(0).strip()

    # 币种检测
    if price and not price.startswith("$"):
        res["currency_flag"] = "币种异常(非USD)"
    return res


def quality_flags(p):
    flags = []
    if p.get("currency_flag"):
        flags.append(p["currency_flag"])
    if not p.get("price_usd"):
        flags.append("价格缺失")
    if not p.get("rating"):
        flags.append("评分缺失")
    if not p.get("review_count"):
        flags.append("评论数缺失")
    if not p.get("bullets"):
        flags.append("五点缺失")
    if not p.get("description"):
        flags.append("描述缺失")
    return flags


# ---------------- 多类目 v1：按需爬取单个类目 ----------------
def crawl_one(node, dept, name, topk=50, scrape_date=None, dry_run=False):
    """按需爬取单个类目(多类目入口). 不走 main() 的「今日去重」, 便于抓取新类目.
    入参 node/dept 必须来自真实 Amazon BSR 链接或已核实目录, 禁止编造.
    """
    if not node or node == "TODO_VERIFY":
        print("[跳过] node 未提供或未核实, 无法爬取")
        return 0
    cat = {"key": name, "display_name": name, "node_id": str(node), "dept": dept}
    if dry_run:
        print(f"[dry-run] 将爬取 dept={dept} node={node} name={name} topk={topk}")
        return 0
    sd = scrape_date or datetime.date.today().isoformat()
    rows = process_category(cat, sd, topk)
    if topk and topk < len(rows):
        rows = rows[:topk]
    if not rows:
        print("无数据, 终止.")
        return 0
    dicts = _rows_to_dicts(rows)
    save_local(node, dicts, sd)
    print(f"完成: 已存 {len(dicts)} 条 ({name}) 到本地缓存.")
    return len(dicts)


# ---------------- 主流程 ----------------
def load_categories():
    with open(CATEGORY_DIR_PATH, encoding="utf-8") as f:
        return json.load(f)["categories"]


def process_category(cat, scrape_date, topk=20):
    node = cat["node_id"]
    if not node or node == "TODO_VERIFY":
        print(f"  [跳过] {cat['key']} node_id 未核实")
        return []
    print(f"\n=== 类目: {cat['display_name']} ({node}) ===")
    url = f"{SITE}/Best-Sellers/zgbs/{cat['dept']}/{node}/"
    html = fetch(url)
    if not html:
        print("  BSR 榜单抓取失败, 跳过")
        return []
    items = parse_bsr(html)
    print(f"  榜单解析到 {len(items)} 个 ASIN")
    if topk and topk < len(items):
        items = items[:topk]
    node_id = cat["node_id"]

    def _scrape(it):
        asin = it["asin"]
        print(f"  [{it['rank']}] {asin} 抓取详情...")
        d = extract_detail(fetch(f"{SITE}/dp/{asin}") or "")
        if not d.get("title"):
            d["title"] = it["title"]
        d["rank"] = it["rank"]
        d["asin"] = asin
        d["url"] = f"{SITE}/dp/{asin}"
        d["data_quality"] = ";".join(quality_flags(d))
        return [
            scrape_date, node_id, d["rank"], asin, d.get("brand", ""),
            d.get("title", ""), d.get("price_usd", ""), d.get("rating", ""),
            d.get("review_count", ""), d.get("bsr_in_category", ""),
            "\n".join(d.get("bullets", [])), d.get("description", ""),
            d.get("url", ""), d.get("data_quality", ""),
        ]

    rows = []
    # 并发抓取详情(降低单类目总耗时, 让 /compete 同步现爬能在网关超时内返回)
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(_scrape, it) for it in items]
        for f in as_completed(futs):
            try:
                rows.append(f.result())
            except Exception as e:
                print(f"    详情抓取异常: {e}")
    rows.sort(key=lambda r: r[2] if isinstance(r[2], int) else 999)
    return rows


def brand_summary(all_rows):
    brands = {}
    for r in all_rows:
        b = r[4] or "未知"
        brands.setdefault(b, []).append(r)
    out = [["品牌", "席位", "平均价格", "平均评分", "平均评论数"]]
    for b, rs in sorted(brands.items(), key=lambda x: -len(x[1])):
        prices = [float(x[6].replace("$", "").replace(",", "")) for x in rs
                  if x[6].startswith("$")]
        rates = [float(x[7]) for x in rs if x[7]]
        revs = [int(re.sub(r"[^\d]", "", x[8])) for x in rs if x[8] and re.sub(r"[^\d]", "", x[8])]
        out.append([
            b, len(rs),
            f"${sum(prices)/len(prices):.2f}" if prices else "N/A",
            f"{sum(rates)/len(rates):.2f}" if rates else "N/A",
            f"{int(sum(revs)/len(revs))}" if revs else "N/A",
        ])
    return out


def main():
    # 抖动: 避免与大量定时任务在同一整点并发被识别为机器人
    time.sleep(random.uniform(0, 300))

    _set_us_zip()
    cats = load_categories()
    scrape_date = datetime.date.today().isoformat()

    for cat in cats:
        rows = process_category(cat, scrape_date)
        if not rows:
            continue
        dicts = _rows_to_dicts(rows)
        save_local(cat["node_id"], dicts, scrape_date)
    print(f"\n完成. 已存 {len(cats)} 个类目到本地缓存(data_cache/).")


if __name__ == "__main__":
    main()
