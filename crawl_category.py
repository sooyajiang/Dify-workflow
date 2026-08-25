#!/usr/bin/env python3
"""多类目竞品爬取入口 v1 (amazon-bestseller-to-feishu 扩展)

设计原则(来自 category_directory.json 约定):
  - 支持任意类目, 但 node_id 必须来自「真实 Amazon BSR 链接」或「已核实目录」, 禁止编造。
  - 解析置信度分三档: URL/目录命中=high(直接爬); 含糊=low(交人工确认 HITL)。
  - 命中后可 --save-seed 写回 category_directory.json 供复用(符合其"种子/缓存"定位)。

用法:
  # 直接给 Amazon BSR 链接(最稳, node/dept 全从真实 URL 来)
  python crawl_category.py "https://www.amazon.com/Best-Sellers/zgbs/sporting-goods/1265804011/"

  # 给已核实目录里的名字/关键词(如 kids bicycle)
  python crawl_category.py "kids bicycle"

  # 指定 node+dept(跳过解析)
  python crawl_category.py --node 1265804011 --dept sporting-goods --name "Kids Bicycles"

  # 只测解析、不抓亚马逊/不写飞书
  python crawl_category.py "yoga mat" --dry-run

  # 把跑通的节点存回目录, 下次直接用名字即可
  python crawl_category.py --node 1265804011 --dept sporting-goods --name "Kids Bicycles" --save-seed
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
CATEGORY_DIR_PATH = os.environ.get(
    "CATEGORY_DIR_PATH", os.path.join(HERE, "category_directory.json"))


def load_dir():
    try:
        with open(CATEGORY_DIR_PATH, encoding="utf-8") as f:
            return json.load(f).get("categories", [])
    except Exception:
        return []


def resolve_from_url(query):
    """从 Amazon BSR 链接提取真实 node + dept. 最可靠, 不靠猜."""
    m = re.search(r"/zgbs/([\w-]+)/(\d{9,})", query)
    if m:
        return {"node": m.group(2), "dept": m.group(1),
                "name": "从URL解析", "conf": "high", "src": "url", "ask": False}
    return None


def _tokens(s):
    """拆词元: 按非字母数字切, 含下划线/撇号/空格都算分隔."""
    return set(t for t in re.split(r"[^a-z0-9]+", s.lower()) if t)


def resolve_from_directory(query, cats):
    q_tokens = _tokens(query)
    if not q_tokens:
        return None
    for c in cats:
        blob = " ".join([c.get("key", ""), c.get("display_name", ""),
                         " ".join(c.get("seed_keywords", []))])
        c_tokens = _tokens(blob)
        # 每个 query 词元都能在类目词表里找到(精确或包含), 才算命中
        ok = all(any(t == qt or t in qt or qt in t for t in c_tokens)
                 for qt in q_tokens)
        if ok:
            return {"node": c["node_id"], "dept": c["dept"],
                    "name": c["display_name"], "conf": "high",
                    "src": "directory", "ask": False}
    return None


def resolve_category(query, cats):
    r = resolve_from_url(query)
    if r:
        return r
    r = resolve_from_directory(query, cats)
    if r:
        return r
    # 中等置信: 自动搜亚马逊解析 BSR 节点(需联网, 失败则 HITL)
    r = resolve_from_search(query)
    if r:
        return r
    # 低置信度 -> 人工确认(HITL), 绝不编造 node
    return {"node": None, "dept": None, "name": query,
            "conf": "low", "src": "hitl", "ask": True}


def parse_search_node(html):
    """纯函数: 从亚马逊搜索结果页 HTML 解析 (dept, node). 正则版, 无 bs4 依赖.
    返回 (dept, node) 或 None. 多来源交叉验证, 取最可靠者. 绝不编造 node.
    （抽成纯函数便于离线单测, 用 mock HTML 验证解析逻辑.）"""
    if not html:
        return None
    low = html.lower()
    if "captcha" in low[:5000] or "robot check" in low[:5000]:
        return None
    # 来源1: 面包屑 Best Sellers 链接(最可靠, 含 dept+node; 有的带 zgbs 有的不带)
    m = re.search(r"/Best-Sellers/([\w-]+)/(?:zgbs/)?(\d{9,})", html)
    if m:
        return (m.group(1), m.group(2))
    # 来源2: 任意 zgbs 链接(dept+node)
    m = re.search(r"/zgbs/([\w-]+)/(\d{9,})", html)
    if m:
        return (m.group(1), m.group(2))
    # 来源3: 带 node 的搜索/部门链接(中等可靠)
    m = re.search(r"[?&]node=(\d{9,})", html)
    if m:
        node = m.group(1)
        dm = re.search(r"[?&]i=([\w-]+)", html)
        return (dm.group(1) if dm else "unknown", node)
    return None


# 亚马逊顶层 department node（超大根节点），搜索页左侧 facet 常包含它们，
# 但不应作为“最相关类目”返回；否则竞品参考会太宽泛。
_AMAZON_ROOT_NODES = {
    "283155", "172282", "1055398", "3375251", "16310091",
    "2335752011", "6669702011", "1084128", "51503011", "3760911",
    "284507", "2617942011", "2972638011", "11971251", "133140011",
    "3580501", "599872", "16310231", "12923371",
}


def _pick_search_nodes(html, top_n=5):
    """从亚马逊搜索结果页左侧分类 facet 提取候选类目 node 列表.
    策略: 按出现频率+出现位置综合排序, 排除超大根节点和重复项.
    返回 list[str], 优先试最细粒度/最相关的节点."""
    rh_nodes = re.findall(r'rh=n%3A(\d+)', html)
    rh_nodes = [n for n in rh_nodes if len(n) >= 9 and n not in _AMAZON_ROOT_NODES]
    if not rh_nodes:
        return []
    # 去重同时保留频率信息
    freq = Counter(rh_nodes)
    # 频率高 + 在列表中出现晚(更细)的优先
    ordered = sorted(set(rh_nodes), key=lambda n: (-freq[n], rh_nodes[::-1].index(n)))
    return ordered[:top_n]


def _resolve_from_asin_detail(sess, query, max_asins=6):
    """通过搜索结果 ASIN 详情页中的 BSR 类目路径反推真实 dept/node.
    比 facet 更准, 因为详情页的类目路径直接对应商品."""
    try:
        kw = requests.utils.quote(query)
        r = sess.get(f"https://www.amazon.com/s?k={kw}", timeout=20)
        if r.status_code != 200:
            return None, None
        asins = re.findall(r'/dp/([A-Z0-9]{10})', r.text)
        asins = list(dict.fromkeys(asins))[:max_asins]
        if not asins:
            return None, None
        pair_counter = Counter()
        for asin in asins:
            d = sess.get(f"https://www.amazon.com/dp/{asin}", timeout=20)
            if d.status_code != 200:
                continue
            # 取页面内所有 zgbs 链接, 过滤根节点
            links = re.findall(r'/zgbs/([\w-]+)/(\d{9,})', d.text)
            for dept, node in links:
                if node not in _AMAZON_ROOT_NODES:
                    pair_counter[(dept, node)] += 1
        if not pair_counter:
            return None, None
        # 取出现频率最高的 (dept, node)
        (dept, node), _ = pair_counter.most_common(1)[0]
        return dept, node
    except Exception:
        return None, None


def _dept_from_url(url):
    """从 Amazon Best Sellers / zgbs URL 提取 (dept_slug, node_id)."""
    m = re.search(r"/zgbs/([\w-]+)/(\d{9,})", url)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"/Best-Sellers(?:-[\w-]+)?/zgbs/([\w-]+)/(\d{9,})", url)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _probe_dept_node(sess, node, retries=2):
    """通过构造 Best Sellers URL 并抓取页面, 从页面内 zgbs 链接反推真实 dept.
    亚马逊对 dept slug 有容错: 即使占位 dept 不对, 也会返回真实 BSR 页面.
    返回 (dept, node) 或 (None, None). 绝不编造.
    带简单重试, 缓解 503/超时."""
    import time
    for attempt in range(retries + 1):
        try:
            # 占位 dept; 亚马逊会重定向/容错到真实类目, URL 可能不变但内容是真实 BSR
            probe_url = f"https://www.amazon.com/Best-Sellers/zgbs/kitchen/{node}/"
            br = sess.get(probe_url, timeout=20)
            if br.status_code == 503 and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            if br.status_code != 200:
                return None, None
            # 优先在页面内找当前 node 对应的 zgbs 链接 -> 真实 dept
            m = re.search(rf"/zgbs/([\w-]+)/{node}/", br.text)
            if m:
                return m.group(1), node
            # fallback: 解析页面内任意 BSR 链接
            parsed = parse_search_node(br.text)
            if parsed:
                return parsed
            return None, None
        except Exception:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return None, None
    return None, None


def resolve_from_search(query):
    """自动搜亚马逊, 解析真实类目节点(中等置信, 需联网).
    优先通过 ASIN 详情页 BSR 路径反推真实 dept/node(最准);
    失败则 fallback 到 facet 候选探测. 搜不到 / 被验证码拦截返回 None.
    绝不编造 node."""
    try:
        import requests
    except Exception:
        return None
    import time
    try:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        kw = requests.utils.quote(query)
        # 简单重试: 亚马逊偶发 503
        r = None
        for attempt in range(3):
            r = sess.get(f"https://www.amazon.com/s?k={kw}", timeout=20)
            if r.status_code == 200:
                break
            if r.status_code == 503 and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
        if not r or r.status_code != 200:
            return None
        # 兼容旧逻辑: 搜索页若直接出现 Best Sellers 链接, 优先用
        parsed = parse_search_node(r.text)
        if parsed:
            dept, node = parsed
            return {"node": node, "dept": dept, "name": query,
                    "conf": "medium", "src": "search", "ask": False}
        # 主逻辑: ASIN 详情页 BSR 路径反推(最准)
        dept, node = _resolve_from_asin_detail(sess, query)
        if dept and node:
            return {"node": node, "dept": dept, "name": query,
                    "conf": "medium", "src": "search", "ask": False}
        # Fallback: 从左侧 facet 提取候选 node 列表, 逐个探测真实 dept
        candidates = _pick_search_nodes(r.text)
        for cand in candidates:
            dept, final_node = _probe_dept_node(sess, cand)
            if dept and final_node:
                return {"node": final_node, "dept": dept, "name": query,
                        "conf": "medium", "src": "search", "ask": False}
        return None
    except Exception:
        return None
    return None


def save_seed(node, dept, name):
    try:
        with open(CATEGORY_DIR_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {"version": 1, "categories": []}
    cats = data.setdefault("categories", [])
    if any(c.get("node_id") == str(node) for c in cats):
        print(f"  [skip] 目录已存在 node={node}, 不重复写入")
        return
    cats.append({
        "key": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"),
        "display_name": name,
        "node_id": str(node),
        "dept": dept,
        "site": "amazon.com",
        "currency": "USD",
        "language": "en_US",
        "seed_keywords": [],
        "example_asins": [],
        "status": "active",
    })
    with open(CATEGORY_DIR_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [ok] 已写入目录: {name} ({node})")


def crawl_one(node, dept, name, topk=50, dry_run=False):
    """惰性导入 run_pipeline(dry-run 不依赖 requests/bs4)."""
    if not node or node == "TODO_VERIFY":
        print("[跳过] node 未提供或未核实, 无法爬取")
        return 0
    if dry_run:
        print(f"[dry-run] 将爬取 dept={dept} node={node} name={name} topk={topk}")
        return 0
    import run_pipeline as rp  # noqa: WPS433
    return rp.crawl_one(node, dept, name, topk=topk, dry_run=dry_run)


def main():
    ap = argparse.ArgumentParser(description="多类目 Amazon BSR 爬取 v1")
    ap.add_argument("query", nargs="?", help="类目名/关键词, 或直接贴 Amazon BSR 链接")
    ap.add_argument("--node", help="已核实的 Amazon 类目节点 ID(跳过解析)")
    ap.add_argument("--dept", help="Amazon 部门 slug, 如 sporting-goods")
    ap.add_argument("--name", help="展示名(配合 --node 使用)")
    ap.add_argument("--topk", type=int, default=50, help="抓取前 N 名(默认 50)")
    ap.add_argument("--dry-run", action="store_true", help="只解析不爬取/不写飞书")
    ap.add_argument("--save-seed", action="store_true", help="跑通后写回 category_directory.json")
    args = ap.parse_args()

    # 1) 解析出 node/dept/name
    if args.node and args.dept:
        resolved = {"node": args.node, "dept": args.dept,
                    "name": args.name or args.node, "conf": "high",
                    "src": "cli", "ask": False}
    elif args.query:
        resolved = resolve_category(args.query, load_dir())
    else:
        ap.print_help()
        return

    node, dept, name, conf = resolved["node"], resolved["dept"], resolved["name"], resolved["conf"]

    # 2) 低置信度 -> HITL 确认
    if resolved.get("ask"):
        print(f"[HITL] 无法高置信度解析「{args.query}」, 请补充真实 Amazon BSR 节点:")
        print("  方式A: 直接贴 BSR 链接 -> python crawl_category.py \"https://www.amazon.com/Best-Sellers/zgbs/<dept>/<node>/\"")
        print("  方式B: 指定节点 -> python crawl_category.py --node <node> --dept <dept> --name <展示名>")
        print("  (当前目录已核实类目:)")
        for c in load_dir():
            print(f"    - {c.get('display_name')}  node={c.get('node_id')}  dept={c.get('dept')}")
        if sys.stdin.isatty():
            try:
                node = input("请输入 node_id (留空取消): ").strip()
                dept = input("请输入 dept (如 sporting-goods): ").strip()
                name = input("请输入展示名: ").strip() or args.query
            except EOFError:
                node = dept = ""
            if not node or not dept:
                print("已取消."); return
            conf = "high"
        else:
            print("[退出] 非交互环境且置信度低, 终止(请用 --node/--dept 或贴链接).")
            return

    print(f"[解析] name={name} dept={dept} node={node} conf={conf}")
    if conf == "medium":
        print("  [提示] 该类目由搜索自动解析(中等置信), 跑通后建议加 --save-seed 固化节点, 下次直接用名字调用。")
    if args.save_seed and node and dept and not args.dry_run:
        save_seed(node, dept, name)

    # 3) 爬取
    crawl_one(node, dept, name, topk=args.topk, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
