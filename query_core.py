#!/usr/bin/env python3
"""数据聚合核心(被 serve.py 与飞书推送共用): 读飞书 Base -> 算概览/品牌/异常.

纯数据层, 不依赖 HTTP 框架, 可独立 import.
"""
import requests
import run_pipeline as rp


def feishu_read_all():
    """分页读取飞书 Base 全部记录, 返回统一字典列表."""
    token = rp.feishu_token()
    rows, url = [], (
        f"{rp.BASE_URL}/bitable/v1/apps/{rp.BASE_APP_TOKEN}"
        f"/tables/{rp.BASE_TABLE_ID}/records?page_size=100")
    while url:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        d = r.json().get("data", {})
        for it in d.get("items", []):
            f = it.get("fields", {})
            rows.append({
                "date": f.get("抓取日期"),
                "rank": f.get("排名"),
                "asin": f.get("ASIN"),
                "brand": f.get("品牌") or "未知",
                "title": f.get("标题"),
                "price": f.get("价格USD"),
                "rating": f.get("评分"),
                "reviews": f.get("评论数"),
                "quality": f.get("数据质量"),
                "url": f.get("链接"),
                "cat_node": f.get("类目节点ID"),
            })
        pt = d.get("page_token")
        url = (f"{rp.BASE_URL}/bitable/v1/apps/{rp.BASE_APP_TOKEN}"
               f"/tables/{rp.BASE_TABLE_ID}/records?page_size=100&page_token={pt}") \
            if (pt and len(d.get("items", [])) == 100) else None
    return rows


def _price_num(v):
    if not v or not str(v).startswith("$"):
        return None
    try:
        return float(str(v).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def compute_anomalies(latest, prev):
    """对比最新日与上一日, 输出异常清单(价格/排名/新上榜/跌出)."""
    out = []
    pmap = {r["asin"]: r for r in prev if r.get("asin")}
    latest_asins = {r.get("asin") for r in latest if r.get("asin")}
    for r in latest:
        a = r.get("asin")
        if not a:
            continue
        p = pmap.get(a)
        if not p:
            out.append({"asin": a, "brand": r.get("brand"), "type": "新上榜",
                        "detail": f"最新排名 {r.get('rank')}"})
            continue
        pr, pp = _price_num(r.get("price")), _price_num(p.get("price"))
        if pr is not None and pp is not None and pp > 0:
            ch = (pr - pp) / pp
            if ch <= -0.05:
                out.append({"asin": a, "brand": r.get("brand"), "type": "降价",
                            "detail": f"{p.get('price')}→{r.get('price')} ({(ch*100):.1f}%)"})
            elif ch >= 0.05:
                out.append({"asin": a, "brand": r.get("brand"), "type": "涨价",
                            "detail": f"{p.get('price')}→{r.get('price')} ({(ch*100):.1f}%)"})
        rr, rp_ = r.get("rank"), p.get("rank")
        try:
            rr_i, rp_i = int(rr), int(rp_)
        except (TypeError, ValueError):
            rr_i = rp_i = None
        if rr_i is not None and rp_i is not None:
            delta = rp_i - rr_i
            if delta >= 3:
                out.append({"asin": a, "brand": r.get("brand"), "type": "排名上升",
                            "detail": f"{rp_i}→{rr_i} (上升{delta}名)"})
            elif delta <= -3:
                out.append({"asin": a, "brand": r.get("brand"), "type": "排名下降",
                            "detail": f"{rp_i}→{rr_i} (下降{-delta}名)"})
    for r in prev:
        if r.get("asin") and r.get("asin") not in latest_asins:
            out.append({"asin": r.get("asin"), "brand": r.get("brand"),
                        "type": "跌出榜单", "detail": f"上一日排名 {r.get('rank')}"})
    return out


def _resolve_node_from_dir(category):
    """仅本地目录匹配(不联网), 返回 node_id 或 None. 供 /query 按类目过滤."""
    try:
        import crawl_category as cc
        r = cc.resolve_from_directory(category, cc.load_dir())
        return r["node"] if r else None
    except Exception:
        return None


def _dir_display_names():
    try:
        import crawl_category as cc
        return [c.get("display_name") for c in cc.load_dir()]
    except Exception:
        return []


def build_query_payload(category=None, node=None):
    """聚合并返回结构化数据: {stats, brands, anomalies, latest}.

    可选过滤:
      - category: 类目名/关键词, 按已核实目录解析出 node_id 后按类目过滤
      - node:     直接传 Amazon 类目节点 ID
    过滤后仅返回该类目数据, 供 Dify 按类目取竞品参考(多类目隔离)。
    不传则保持原行为: 返回 Base 全量。
    """
    rows = feishu_read_all()

    # 按类目过滤(仅当显式传了 category 或 node)
    if category and not node:
        target = _resolve_node_from_dir(category)
        if not target:
            return {"error": "unknown_category",
                    "msg": f"类目「{category}」未在已核实目录中, 无法按类目过滤",
                    "hint": "请先在 crawl_category.py 用 --save-seed 固化节点, "
                            "或直接传 ?node=<node_id>",
                    "available_categories": _dir_display_names()}
        rows = [r for r in rows if str(r.get("cat_node")) == str(target)]
    elif node:
        rows = [r for r in rows if str(r.get("cat_node")) == str(node)]

    by_date = {}
    for r in rows:
        if r.get("date"):
            by_date.setdefault(r["date"], []).append(r)
    dates = sorted(by_date.keys())
    latest_date = dates[-1] if dates else None
    prev_date = dates[-2] if len(dates) >= 2 else None
    latest = by_date.get(latest_date, [])
    prev = by_date.get(prev_date, [])
    bmap = {}
    for r in latest:
        bmap.setdefault(r.get("brand") or "未知", []).append(r)
    brands = []
    for b, rs in sorted(bmap.items(), key=lambda x: -len(x[1])):
        prices = [p for p in (_price_num(x.get("price")) for x in rs) if p]
        rates = [float(x["rating"]) for x in rs if x.get("rating")]
        brands.append({
            "brand": b, "count": len(rs),
            "avg_price": (f"${sum(prices)/len(prices):.2f}" if prices else "N/A"),
            "avg_rating": (round(sum(rates)/len(rates), 2) if rates else "N/A"),
        })
    anomalies = compute_anomalies(latest, prev) if prev else []
    prices = [p for p in (_price_num(x.get("price")) for x in latest) if p]
    rates = [float(x["rating"]) for x in latest if x.get("rating")]
    stats = {
        "latest_date": latest_date,
        "prev_date": prev_date,
        "total_records": len(rows),
        "days_covered": len(dates),
        "latest_count": len(latest),
        "brand_count": len(brands),
        "price_median": (f"${sorted(prices)[len(prices)//2]:.2f}" if prices else "N/A"),
        "avg_rating": (round(sum(rates)/len(rates), 2) if rates else "N/A"),
        "missing_flag_count": sum(1 for x in latest if x.get("quality")),
        "filter": ({"category": category, "node": node}
                   if (category or node) else None),
    }
    return {"stats": stats, "brands": brands, "anomalies": anomalies, "latest": latest}
