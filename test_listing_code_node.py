# 本地验证：Dify Listing Chatflow 的「代码」节点逻辑
# 不依赖任何外部 API，纯 Python 验证 parse() 在各类脏输入下都能正确解析 LLM A/B 的输出。
import json
import re


def main(gen: str, qa: str) -> dict:
    def parse(s):
        if not s:
            return {}
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
        txt = m.group(1).strip() if m else s.strip()
        if not txt.startswith("{"):
            a = txt.find("{")
            b = txt.rfind("}")
            if a != -1 and b != -1:
                txt = txt[a:b + 1]
        try:
            return json.loads(txt)
        except Exception:
            return {}

    a = parse(gen)
    b = parse(qa)
    bullets = a.get("bullets", [])
    if isinstance(bullets, list):
        bullets_md = "\n".join(f"{i+1}. {x}" for i, x in enumerate(bullets))
    else:
        bullets_md = str(bullets)

    score = b.get("score", "N/A")
    passed = b.get("pass", False)
    issues = b.get("issues", [])

    md = f"""## 🎯 亚马逊 Listing 生成结果

**标题**（{a.get('title_length', '?')} 字符 · 合规：{'✅' if a.get('title_compliant') else '❌'}）
> {a.get('title', '')}

**Item Highlights**（属性标签）
> {a.get('item_highlights', '')}

**五点描述（Bullet Points）**
{bullets_md}

**Backend Search Terms**
> {a.get('backend_terms', '')}

---
### 🔍 质检报告
- **综合评分**：{score} / 10
- **是否通过**：{'✅ 通过' if passed else '❌ 未通过'}
- **问题清单**：{('；'.join(issues)) if issues else '无明显问题'}
- **改进建议**：{b.get('suggestion', '-')}
"""
    return {"result": md}


# ---- 测试用例 ----
SAMPLE_B = json.dumps({
    "score": 8.5, "pass": True,
    "issues": ["Highlights 稍偏长"], "suggestion": "可精简 1-2 个标签"
})

cases = {
    "① 裸 JSON（gpt 类）": (
        json.dumps({
            "title": "WEIZE 16 Inch Kids Bike Girls Boys", "title_length": 31,
            "title_compliant": True,
            "item_highlights": "16 Inch / Training Wheels / High Carbon Steel / Pink / Adjustable Seat / Ages 3-5",
            "bullets": ["A great bike for kids.", "Safe and stable.", "Easy to install.", "Durable frame.", "Cute pink color."],
            "backend_terms": "toddler bicycle princess bike first bike", "category": "Kids Bicycle", "language": "en"
        }),
        SAMPLE_B,
    ),
    "② ```json 围栏（claude 类）": (
        "```json\n" + json.dumps({
            "title": "JOYSTAR 14 Inch Balance Bike for Toddlers",
            "title_length": 39, "title_compliant": True,
            "item_highlights": "14 Inch / Balance Bike / Ages 2-4 / Lightweight / No Pedal / Training",
            "bullets": ["Helps toddlers learn balance.", "Lightweight frame.", "Safe no-pedal design.", "Easy to carry.", "Cute colors."],
            "backend_terms": "toddler balance bike first bicycle", "category": "Kids Bicycle", "language": "en"
        }) + "\n```",
        SAMPLE_B,
    ),
    "③ DeepSeek 思考模式：<think> + ```json 围栏": (
        "<think>用户要一款粉色 16 寸小女孩自行车，带辅助轮，主打安全好安装。先提取信息...</think>\n"
        "```json\n" + json.dumps({
            "title": "WEIZE 16 Inch Girls Bike with Training Wheels",
            "title_length": 43, "title_compliant": True,
            "item_highlights": "16 Inch / Girls / Training Wheels / Pink / Adjustable Seat / Easy Assembly",
            "bullets": ["Designed for girls 3-5.", "Stable training wheels.", "85% pre-assembled.", "Safe carbon steel.", "Lovely pink look."],
            "backend_terms": "kids bike for girls first bicycle", "category": "Kids Bicycle", "language": "en"
        }) + "\n```",
        SAMPLE_B,
    ),
    "④ 兜底：JSON 前后有废话": (
        "好的，这是生成的 Listing：\n" + json.dumps({
            "title": "RoyalBaby 16 Inch Kids Bike", "title_length": 25,
            "title_compliant": True,
            "item_highlights": "16 Inch / Boys Girls / Training Wheels / Blue / Kickstand / Safe",
            "bullets": ["Classic design.", "Sturdy build.", "Easy brake.", "Comfortable seat.", "Fun to ride."],
            "backend_terms": "children bicycle royal baby", "category": "Kids Bicycle", "language": "en"
        }) + "\n希望满意。",
        SAMPLE_B,
    ),
    "⑤ 异常：LLM A 返回空/乱码": (
        "抱歉我无法生成。",
        SAMPLE_B,
    ),
    "⑥ 异常：LLM B 返回空": (
        json.dumps({"title": "X", "title_length": 1, "title_compliant": True,
                    "item_highlights": "X", "bullets": ["a"], "backend_terms": "x",
                    "category": "Kids Bicycle", "language": "en"}),
        "",
    ),
}

if __name__ == "__main__":
    ok = 0
    for name, (gen, qa) in cases.items():
        try:
            out = main(gen, qa)
            r = out["result"]
            # 基本健全性：不要抛错、含标题与质检段、不残留 ```json
            assert "亚马逊 Listing 生成结果" in r
            assert "🔍 质检报告" in r
            assert "```json" not in r
            ok += 1
            print(f"[PASS] {name}  (输出 {len(r)} 字符)")
        except Exception as e:
            print(f"[FAIL] {name}  -> {e}")
    print(f"\n=== {ok}/{len(cases)} 用例通过 ===")
