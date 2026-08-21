#!/usr/bin/env python3
"""多类目解析链离线测试(不联网, 用 mock HTML 验证解析逻辑).

覆盖:
  1. parse_search_node 多来源解析(面包屑 / zgbs / node链接 / 验证码 / 空)
  2. resolve_from_directory 目录命中(kids bicycle)
  3. resolve_category 全链: 目录命中=high / 未知=gibberish HITL / 搜索中等置信(monkeypatch)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crawl_category as cc


def test_parse_search_node():
    # 来源1: 面包屑 Best Sellers
    h1 = '<div><a href="/Best-Sellers/sporting-goods/1265804011/">Kids\' Bicycles</a></div>'
    assert cc.parse_search_node(h1) == ("sporting-goods", "1265804011"), h1
    # 来源2: 直接 zgbs
    h2 = 'x <a href="/zgbs/home-garden/123456789/">Yoga Mats</a> y'
    assert cc.parse_search_node(h2) == ("home-garden", "123456789"), h2
    # 来源3: ?node= 链接(带 dept i=)
    h3 = '<a href="/s?k=yoga&i=sports&node=987654321">dept</a>'
    assert cc.parse_search_node(h3) == ("sports", "987654321"), h3
    # 验证码拦截
    assert cc.parse_search_node("Robot Check please solve captcha ...") is None
    # 空
    assert cc.parse_search_node("") is None
    # 无节点
    assert cc.parse_search_node("<html>no node here</html>") is None
    print("[ok] test_parse_search_node")


def test_resolve_from_directory():
    cats = cc.load_dir()
    r = cc.resolve_from_directory("kids bicycle", cats)
    assert r and r["conf"] == "high" and r["node"] == "1265804011", r
    # 目录外 -> None(交给 search/HITL)
    assert cc.resolve_from_directory("yoga mat", cats) is None
    print("[ok] test_resolve_from_directory")


def test_resolve_category_hitl():
    # 未知类目, 无网络(search 返回 None) -> HITL ask=True
    cats = cc.load_dir()
    r = cc.resolve_category("asdkjwq something weird", cats)
    assert r["ask"] is True and r["conf"] == "low", r
    print("[ok] test_resolve_category_hitl")


def test_resolve_category_search_mock(monkeypatch):
    # 模拟联网搜索命中(中等置信), 验证全链走到 search 分支
    cats = cc.load_dir()
    fake = {"node": "555666777", "dept": "sports", "name": "yoga mat",
            "conf": "medium", "src": "search", "ask": False}
    monkeypatch.setattr(cc, "resolve_from_search", lambda q: fake)
    r = cc.resolve_category("yoga mat", cats)
    assert r["conf"] == "medium" and r["node"] == "555666777" and r["ask"] is False, r
    print("[ok] test_resolve_category_search_mock")


if __name__ == "__main__":
    test_parse_search_node()
    test_resolve_from_directory()
    test_resolve_category_hitl()
    # monkeypatch 仅在 pytest 下可用, 这里手动包一层
    class M:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)
    mp = M()
    orig = cc.resolve_from_search
    cc.resolve_from_search = lambda q: {"node": "555666777", "dept": "sports",
                                        "name": "yoga mat", "conf": "medium",
                                        "src": "search", "ask": False}
    try:
        test_resolve_category_search_mock(mp)
    finally:
        cc.resolve_from_search = orig
    print("\n全部通过 ✅  多类目解析链逻辑验证完毕")
