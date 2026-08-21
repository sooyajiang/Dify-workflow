"""
Dify Listing 生成 Chatflow 调用客户端
====================================
在 Dify 把 Chatflow「发布为 API」之后, 用这个脚本从代码侧调用它,
生成亚马逊 listing (标题/五点/描述)。这是把 Chatflow "发布出去真正能用"的关键一步。

支持两种模式:
  - chat     : Chatflow(对话型)  ->  POST /chat-messages
  - workflow : Workflow(工作流)  ->  POST /workflows/run

────────────────────────────────────────────────────────
配置方式(二选一):
  A. 直接改下方 CONFIG 区块(适合新手)
  B. 用 .env 环境变量(适合上线/不泄露 key):
        DIFY_BASE_URL=https://api.dify.ai/v1
        DIFY_API_KEY=app-xxxxxxxx
        DIFY_MODE=chat
────────────────────────────────────────────────────────

怎么知道 INPUTS 里该填哪些变量?
  -> 打开 Dify 你的应用 -> 右上「预览」左侧的「输入变量」面板,
     或「编排」页面里每个节点之间的变量, 照着名字填到 INPUTS 里即可。
     变量名必须和 Dify 里一模一样(大小写敏感)!

运行示例:
  python dify_listing_client.py --mode chat --query "我想上架一款 3-5 岁小女孩的 16 寸儿童自行车，带辅助轮、粉色、主打安全和好安装，美国市场，英文文案。"
  python dify_listing_client.py --mode chat   # 用上方默认 QUERY
"""
import os
import sys
import json
import argparse
import requests

# ===================== CONFIG 配置区 =====================
# 1) Dify API 地址: 云端默认 https://api.dify.ai/v1 ; 自建改成你的域名
DIFY_BASE_URL = os.environ.get("DIFY_BASE_URL", "https://api.dify.ai/v1")

# 2) API Key: Dify 应用 -> 发布 -> API 访问凭证 -> 生成 (形如 app-xxxx)
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "在此填写你的Dify API Key")

# 3) 调用模式: chat 或 workflow
MODE = os.environ.get("DIFY_MODE", "chat")

# 4) 输入变量: 本 Chatflow 走「自然语言对话」，【不定义任何结构化输入变量】，
#    全部靠 sys.query 驱动。所以 Chatflow 模式下 inputs 留空 {} 即可，
#    自然语言描述通过下方 QUERY 传。若你以后改成 Workflow + 结构化变量，再来填这里。
INPUTS = {}

# 5) chat 模式下发给模型的「自然语言产品描述」(即 Dify 里的 sys.query)
QUERY = os.environ.get(
    "DIFY_QUERY",
    "我想上架一款 3-5 岁小女孩的 16 寸儿童自行车，带辅助轮、粉色、"
    "主打安全和好安装，目标市场美国，英文文案。",
)

# 6) 用户标识(随便填, Dify 用来区分不同调用者/会话)
USER = os.environ.get("DIFY_USER", "workbuddy-user")
# =======================================================


def _headers():
    return {"Authorization": f"Bearer {DIFY_API_KEY}", "Content-Type": "application/json"}


def call_chat(base, key, inputs, query, user):
    """Chatflow 模式: 返回模型最终的 answer 文本。"""
    payload = {
        "inputs": inputs,
        "query": query,
        "response_mode": "blocking",   # blocking=等结果返回; streaming=流式
        "user": user,
        "conversation_id": "",
    }
    r = requests.post(f"{base}/chat-messages", json=payload,
                      headers=_headers(), timeout=180)
    r.raise_for_status()
    return r.json()


def call_workflow(base, key, inputs, user):
    """Workflow 模式: 返回结束节点的 outputs(你的输出变量字典)。"""
    payload = {
        "inputs": inputs,
        "response_mode": "blocking",
        "user": user,
    }
    r = requests.post(f"{base}/workflows/run", json=payload,
                      headers=_headers(), timeout=180)
    r.raise_for_status()
    return r.json()


def main():
    p = argparse.ArgumentParser(description="调用 Dify Listing 生成 Chatflow")
    p.add_argument("--mode", choices=["chat", "workflow"], default=MODE,
                   help="调用模式 (默认读 DIFY_MODE 或 chat)")
    p.add_argument("--keyword", default=None, help="(兼容别名) 自然语言产品描述，等同 --query")
    p.add_argument("--query", default=None, help="自然语言产品描述，作为 Dify 的 sys.query 发送")
    args = p.parse_args()

    inputs = dict(INPUTS)  # 当前为 {} (自然语言对话模式，无结构化变量)
    query = args.query or args.keyword or QUERY

    # 友好提示: 没填 key 就先别发请求
    if DIFY_API_KEY.startswith("在此填写") or not DIFY_API_KEY:
        print("❌ 请先在脚本顶部 CONFIG 区, 或环境变量 DIFY_API_KEY 里填入你的 Dify API Key。")
        print("   获取位置: Dify 应用 -> 发布 -> API 访问凭证 -> 生成。")
        sys.exit(1)

    try:
        if args.mode == "chat":
            resp = call_chat(DIFY_BASE_URL, DIFY_API_KEY, inputs, query, USER)
            answer = resp.get("answer", "")
            print("\n========== 生成的 Listing ==========\n")
            print(answer.strip())
            # 顺便把本次对话 id 打印出来, 方便 continuation
            if resp.get("conversation_id"):
                print(f"\n[conversation_id] {resp['conversation_id']}")
        else:
            resp = call_workflow(DIFY_BASE_URL, DIFY_API_KEY, inputs, USER)
            outputs = resp.get("data", {}).get("outputs", {})
            print("\n========== 工作流输出 ==========\n")
            print(json.dumps(outputs, ensure_ascii=False, indent=2))
    except requests.HTTPError as e:
        print("❌ 调用失败:", e)
        # 把 Dify 返回的错误原文打出来, 方便排查(通常是变量名不匹配/key 无效)
        body = getattr(e.response, "text", "")[:800]
        print("错误信息:", body)
        sys.exit(1)
    except requests.RequestException as e:
        print("❌ 网络/请求异常:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
