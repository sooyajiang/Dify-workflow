#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预热缓存 + 延迟测量（二合一）。

用途：
  1) 演示/面试前批量预热热门类目 -> Render 实例本地缓存(data_cache/)秒回，消除现爬卡顿。
  2) 同时测出「冷（首次现爬）」与「热（缓存命中）」两份延迟，给 PRD 填真实数字。

用法：
  python warm_cache.py                 # 用默认 URL/TOKEN/类目列表 预热+测量
  python warm_cache.py --only-warm    # 只预热不打印详细计时（适合定时任务）
  python warm_cache.py --url https://xxx.onrender.com --token sooya1030

注意：
  - 预热的是「部署实例」的本地缓存，实例重启/重新部署后失效，演示前重跑一次即可。
  - 冷测量会真实触发一次 Amazon 现爬（15~60s/类目），请耐心等待。
"""
import argparse
import time
import json
import sys
import urllib.parse
import urllib.request
import urllib.error

DEFAULT_URL = "https://amazon-competitor-api.onrender.com"
DEFAULT_TOKEN = "sooya1030"
TIMEOUT = 180  # 单次请求超时(秒)，匹配 Dify HTTP 节点 120s 余量

# 热门/演示常用类目（中英文混合，覆盖多类目能力）。按需增删。
DEFAULT_CATEGORIES = [
    "游戏手柄",
    "不锈钢保温水杯",
    "笔记本电脑",
    "儿童自行车",
    "蓝牙耳机",
    "瑜伽垫",
    "led string lights",
    "dog chew toys",
]


def _http_get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": "warm-cache/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def measure_once(base, token, category, timeout=TIMEOUT):
    """调用 /compete 一次，返回 (source, elapsed_sec, ok)。"""
    q = urllib.parse.urlencode({"category": category, "token": token})
    url = f"{base}/compete?{q}"
    t0 = time.time()
    try:
        status, body = _http_get(url, timeout=timeout)
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}", time.time() - t0, False
    except Exception as e:
        return f"ERR {type(e).__name__}", time.time() - t0, False
    dt = time.time() - t0
    try:
        src = json.loads(body).get("_source", "?")
    except Exception:
        src = "parse_fail"
    return src, dt, (status == 200)


def warm_and_measure(base, token, categories, only_warm=False):
    print(f"目标服务: {base}  |  TOKEN: {token[:3]}***  |  类目数: {len(categories)}")
    print("-" * 78)
    rows = []
    for cat in categories:
        # 冷：首次现爬
        src_cold, dt_cold, ok_cold = measure_once(base, token, cat)
        # 热：缓存命中（冷跑完缓存已建）
        src_warm, dt_warm, ok_warm = measure_once(base, token, cat)
        rows.append((cat, src_cold, dt_cold, ok_cold, src_warm, dt_warm, ok_warm))
        print(f"[{cat}]")
        print(f"   冷: source={src_cold:<12} {dt_cold:6.1f}s  ok={ok_cold}")
        print(f"   热: source={src_warm:<12} {dt_warm:6.1f}s  ok={ok_warm}")

    if only_warm:
        print("-" * 78)
        print(f"预热完成：{len(categories)} 个类目已落缓存（实例重启前有效）。")
        return

    # 汇总
    cold_ok = [r[2] for r in rows if r[3]]
    warm_ok = [r[5] for r in rows if r[6]]
    print("-" * 78)
    print("汇总（仅统计成功请求）:")
    if cold_ok:
        print(f"  冷(现爬)  : 平均 {sum(cold_ok)/len(cold_ok):.1f}s  最大 {max(cold_ok):.1f}s  n={len(cold_ok)}")
    if warm_ok:
        print(f"  热(缓存)  : 平均 {sum(warm_ok)/len(warm_ok):.2f}s  最大 {max(warm_ok):.2f}s  n={len(warm_ok)}")
    print("\n>>> 把上面『冷/热』数字填进 PRD 的 NFR-1 / 第8节（替换『待实测』）。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--token", default=DEFAULT_TOKEN)
    ap.add_argument("--only-warm", action="store_true")
    ap.add_argument("--categories", nargs="*", default=DEFAULT_CATEGORIES)
    args = ap.parse_args()
    warm_and_measure(args.url, args.token, args.categories, only_warm=args.only_warm)


if __name__ == "__main__":
    main()
