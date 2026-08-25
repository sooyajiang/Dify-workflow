#!/usr/bin/env python3
"""云端部署入口(脱离 WorkBuddy): 把 run_pipeline 暴露为 HTTP 接口,
支持 /run 触发抓取(写本地缓存) 与 /compete 取实时竞品. 不依赖飞书(项目A 已剥离).

零依赖(仅标准库 + requests), 部署到 Render / Railway / VPS.
启动:  python serve.py   (默认端口 8080, 可用环境变量 PORT 覆盖)
接口:
  GET  /          健康检查
  POST /run        触发抓取(可选 ?token=); 若环境变量 FEISHU_CHAT_ID 已设, 抓完自动推日报
  GET  /report     手动推送一次日报到飞书(可选 ?token= &chat_id=)
  GET  /query      返回结构化数据 JSON(供调试或独立助手使用)
  GET  /compete     一体化竞品接口(任意自然语言类目: 查缓存->无则同步现爬->返回结构化竞品); Dify 接实时竞品用此
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_pipeline as rp
import query_core as qc

SECRET = os.environ.get("RUN_SECRET", "")
import requests


def _check_token(path):
    if not SECRET:
        return True
    q = path.split("?", 1)[1] if "?" in path else ""
    tok = dict(x.split("=", 1) for x in q.split("&") if "=" in x).get("token", "")
    return tok == SECRET


def _run_and_report(node=None, dept=None, name=None, topk=50):
    """抓取单个类目(crawl_one 写本地缓存); 或跑全目录(main). 不推送飞书(项目A 已剥离飞书)."""
    if node and dept:
        rp.crawl_one(node, dept, name or node, topk=topk)
    else:
        rp.main()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", ""):
            self._send(200, {"status": "ok", "msg": "竞品监控服务运行中",
                             "tip": "POST /run 触发抓取(自动推日报); GET /report 手动推; GET /query 取数据"})
            return
        if path in ("/query", "/query/"):
            if not _check_token(self.path):
                self._send(403, {"error": "unauthorized"})
                return
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = dict(x.split("=", 1) for x in q.split("&") if "=" in x)
            try:
                self._send(200, qc.build_query_payload(
                    category=params.get("category"),
                    node=params.get("node")))
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        if path in ("/compete", "/compete/"):
            # 一体化竞品接口(多类目闭环): 任意自然语言类目 -> 查缓存 -> 无则同步现爬 -> 返回结构化竞品
            if not _check_token(self.path):
                self._send(403, {"error": "unauthorized"})
                return
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = dict(x.split("=", 1) for x in q.split("&") if "=" in x)
            category = params.get("category") or params.get("node")
            if not category:
                self._send(400, {"error": "缺少 category 参数(自然语言类目名, 如 'girl kids bicycle')"})
                return
            # 1) 先查已缓存竞品
            try:
                payload = qc.build_query_payload(category=category)
            except Exception as e:
                self._send(500, {"error": str(e)})
                return
            # 2) 命中缓存直接返回
            if payload.get("error") != "unknown_category":
                payload["_source"] = "cache"
                self._send(200, payload)
                return
            # 3) 无缓存 -> 解析真实节点(三源交叉验证) -> 同步现爬 -> 再查
            import crawl_category as cc
            try:
                resolved = cc.resolve_category(category, cc.load_dir())
            except Exception as e:
                self._send(500, {"error": f"类目解析失败: {e}"})
                return
            if resolved.get("ask"):
                self._send(400, {"error": "无法高置信解析该类目",
                                 "hint": "请贴 Amazon BSR 链接或显式传 node/dept/name",
                                 "detail": resolved})
                return
            node, dept, name = resolved["node"], resolved["dept"], resolved["name"]
            try:
                cc.save_seed(node, dept, name)
            except Exception:
                pass
            try:
                topk = int(params.get("topk", 10))
            except ValueError:
                topk = 10
            try:
                _run_and_report(node=node, dept=dept, name=name, topk=topk)
            except Exception as e:
                self._send(500, {"error": f"抓取失败: {e}"})
                return
            payload = qc.build_query_payload(category=category)
            payload["_source"] = "fresh_crawl"
            self._send(200, payload)
            return
        if path in ("/report", "/report/"):
            if not _check_token(self.path):
                self._send(403, {"error": "unauthorized"})
                return
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = dict(x.split("=", 1) for x in q.split("&") if "=" in x)
            chat = params.get("chat_id") or os.environ.get("FEISHU_CHAT_ID")
            open_id = params.get("open_id") or os.environ.get("FEISHU_USER_OPEN_ID")
            try:
                import feishu_report
                self._send(200, feishu_report.run_report(chat, open_id))
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/run", "/run/"):
            self._send(404, {"error": "not found, use POST /run"})
            return
        if not _check_token(self.path):
            self._send(403, {"error": "unauthorized"})
            return
        # 解析可选类目参数: ?category=自然语言 或 ?node=&dept=&name= (多类目现爬)
        q = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = dict(x.split("=", 1) for x in q.split("&") if "=" in x)
        # topk: 抓取前 N 名, 默认 50; sync 模式下默认降到 10 以适配 HTTP 超时
        try:
            topk = int(params.get("topk", 50))
        except ValueError:
            topk = 50
        sync = params.get("sync") in ("1", "true", "True")
        if sync and "topk" not in params:
            topk = 10
        category = params.get("category")
        if category:
            # 自然语言任意类目 -> 自动解析真实节点 -> 现爬
            import crawl_category as cc
            resolved = cc.resolve_category(category, cc.load_dir())
            if resolved.get("ask"):
                self._send(400, {"error": "无法高置信解析该类目",
                                 "hint": "请贴 Amazon BSR 链接, 或显式传 ?node=&dept=&name=, "
                                         "或在 crawl_category.py 用 --save-seed 固化节点"})
                return
            node, dept, name = resolved["node"], resolved["dept"], resolved["name"]
            # 固化节点到目录(同实例内让 /query?category= 能解析; 重启后失效, 正式复用请 --save-seed)
            try:
                cc.save_seed(node, dept, name)
            except Exception:
                pass
            if sync:
                try:
                    _run_and_report(node=node, dept=dept, name=name, topk=topk)
                    self._send(200, {"status": "done",
                                     "msg": f"已抓取并写入飞书 Base(category='{category}' -> node={node})",
                                     "node": node, "name": name, "topk": topk})
                except Exception as e:
                    self._send(500, {"error": f"抓取失败: {e}"})
                return
            threading.Thread(target=_run_and_report,
                             kwargs={"node": node, "dept": dept, "name": name, "topk": topk},
                             daemon=True).start()
            self._send(202, {"status": "accepted",
                             "msg": f"多类目抓取已启动(category='{category}' -> node={node}, conf={resolved.get('conf')}), "
                                    f"完成后写入飞书 Base"})
            return
        node = params.get("node")
        dept = params.get("dept")
        name = params.get("name")
        if sync:
            try:
                _run_and_report(node=node, dept=dept, name=name, topk=topk)
                self._send(200, {"status": "done", "msg": "抓取完成", "node": node})
            except Exception as e:
                self._send(500, {"error": f"抓取失败: {e}"})
            return
        # 后台线程跑抓取(+可选推送), 立即返回 202, 避免飞书/网关超时
        threading.Thread(target=_run_and_report,
                         kwargs={"node": node, "dept": dept, "name": name, "topk": topk},
                         daemon=True).start()
        if node and dept:
            self._send(202, {"status": "accepted",
                             "msg": f"单类目抓取已启动(node={node}), 完成后写入飞书 Base"})
        else:
            self._send(202, {"status": "accepted",
                             "msg": "抓取任务已启动, 完成后写入飞书 Base 并推送日报"})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"竞品监控服务启动: http://0.0.0.0:{port}  (POST /run 触发)")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
