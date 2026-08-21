# 本地验证: 复刻 YAML「多轮择优代码」节点逻辑(passed/dimensions 八维度版, 与线上一致)
# 证明: 解析B(剥<think>/```json) + 三轮择优(挑最早 passed / 否则最高分) + 渲染 全链路无误.
import json
import re


def clean(t):
    t = re.sub(r"<think>.*?</think>", "", t or "", flags=re.DOTALL)
    t = re.sub(r"```json\s*", "", t or "", flags=re.IGNORECASE)
    t = re.sub(r"\s*```", "", t or "")
    s, e = (t or "").find("{"), (t or "").rfind("}")
    if s != -1 and e > s:
        t = t[s:e + 1]
    return t


def load(t):
    try:
        return json.loads(clean(t))
    except Exception:
        return {}


def qa(t):
    d = load(t)
    passed = d.get("passed", False)
    if isinstance(passed, str):
        passed = passed.lower() == "true"
    try:
        score = float(d.get("score", 0))
    except Exception:
        score = 0
    return passed, score, d


def render(g):
    parts = g.get("requested_parts", []) or ["title", "highlights", "bullets", "backend"]
    lines = ["## 生成结果"]
    if "title" in parts and g.get("title"):
        tl = g.get("title_length") or len(g.get("title", ""))
        comp = g.get("title_compliant")
        lines += [f"标题：{g['title']}", f"标题长度：{tl}字符",
                  f"标题合规：{'✅ 合规' if comp else '❌ 不合规'}", ""]
    if "bullets" in parts and g.get("bullets"):
        lines.append("五点描述：")
        for b in g["bullets"]:
            lines.append(f"- {b}")
        lines.append("")
    if "highlights" in parts and g.get("highlights"):
        lines.append("Item Highlights：")
        for h in g["highlights"]:
            lines.append(f"- {h}")
        lines.append("")
    if "backend" in parts and g.get("backend"):
        lines.append("后台搜索词：")
        for b in g["backend"]:
            lines.append(f"- {b}")
        lines.append("")
    return "\n".join(lines)


def choose(a1, a2, a3, b1, b2, b3):
    """等价于 YAML「多轮择优代码」节点: 挑最早 passed 的轮; 全失败取最高分."""
    rounds = [(a1, b1), (a2, b2), (a3, b3)]
    best = None
    best_score = -1
    for a, b in rounds:
        if not a and not b:
            continue
        g = load(a)
        passed, score, qd = qa(b)
        if passed:
            best = (g, qd)
            break
        if score > best_score:
            best_score = score
            best = (g, qd)
    if best is None:
        best = (load(a1), qa(b1)[2])
    g, qd = best
    out = [render(g)]
    out.append("## 质检报告")
    out.append(f"状态：{'✅ 合格，可发布' if qd.get('passed') else '❌ 不合格，需重写'}")
    out.append(f"综合得分：{qd.get('score', 'N/A')}/10")
    out.append(f"硬门槛违规：{'有' if qd.get('hard_violation') else '无'}")
    out.append("")
    out.append("各维度评分：")
    for k, v in (qd.get("dimensions") or {}).items():
        out.append(f"- {k}：{v}/10")
    issues = qd.get("issues") or []
    if issues:
        out.append("")
        out.append("问题：")
        for i in issues:
            out.append(f"- {i}")
    sugg = qd.get("suggestions") or []
    if sugg:
        out.append("")
        out.append("优化建议：")
        for s in sugg:
            out.append(f"- {s}")
    return "\n".join(out)


# ---------- 样例数据(八维度 passed 版, 与 YAML 的 LLM B 输出契约一致) ----------
GEN_GOOD = json.dumps({
    "requested_parts": ["title", "highlights", "bullets", "backend"],
    "title": "Brand 16 Inch Kids Bike with Training Wheels",
    "title_length": 44, "title_compliant": True,
    "highlights": ["16 Inch", "Training Wheels", "Steel Frame"],
    "bullets": ["Kids bicycle for 3-5 years: stable training wheels keep riders safe.",
                "85% pre-assembled, tool-free setup in minutes.",
                "Durable carbon steel frame survives rough play."],
    "backend": ["kids bicycle", "training wheels bike", "16 inch kids bike"]})
GEN_BAD = json.dumps({
    "requested_parts": ["title", "highlights", "bullets", "backend"],
    "title": "Brand 16 Inch Bike", "title_length": 18, "title_compliant": True,
    "highlights": ["16 Inch", "Training Wheels"],
    "bullets": ["Good bike.", "Safe.", "Stable."],
    "backend": ["kids bicycle"]})
QA_PASS = json.dumps({"score": 9.0, "passed": True, "hard_violation": False,
                      "dimensions": {"关键词相关性": 9, "卖点吸引力": 8, "语法可读性": 9,
                                     "平台合规性": 8, "COSMO/A9覆盖": 8, "2026新规合规": 8,
                                     "Alexa优化": 8, "多语言本地化": 8},
                      "issues": [], "suggestions": []})
QA_FAIL = json.dumps({"score": 7.0, "passed": False, "hard_violation": False,
                      "dimensions": {"关键词相关性": 6, "卖点吸引力": 7, "语法可读性": 8,
                                     "平台合规性": 8, "COSMO/A9覆盖": 7, "2026新规合规": 8,
                                     "Alexa优化": 7, "多语言本地化": 8},
                      "issues": ["五点前2条缺核心关键词 kids bicycle"],
                      "suggestions": ["第1条五点嵌入 kids bicycle"]})
GEN_DIRTY = "<think>用户要粉色16寸女童车...</think>\n```json\n" + GEN_GOOD + "\n```"
QA_DIRTY = "<think>检查...</think>\n```json\n" + QA_PASS + "\n```"

cases = {
    "① 首轮失败→二轮通过(应挑第2轮 GOOD)": dict(
        a1=GEN_BAD, b1=QA_FAIL, a2=GEN_GOOD, b2=QA_PASS, a3="", b3=""),
    "② 首轮即通过(应挑第1轮 GOOD)": dict(
        a1=GEN_GOOD, b1=QA_PASS, a2="", b2="", a3="", b3=""),
    "③ 全失败兜底(应挑最高分=第3轮 BAD, 标❌)": dict(
        a1=GEN_BAD, b1=QA_FAIL, a2=GEN_BAD, b2=QA_FAIL, a3=GEN_BAD, b3=QA_FAIL),
    "④ 脏输入(<think>+```json)仍能解析": dict(
        a1=GEN_DIRTY, b1=QA_DIRTY, a2="", b2="", a3="", b3=""),
}
expected = {
    "① 首轮失败→二轮通过(应挑第2轮 GOOD)": ("Brand 16 Inch Kids Bike with Training Wheels", "✅ 合格"),
    "② 首轮即通过(应挑第1轮 GOOD)": ("Brand 16 Inch Kids Bike with Training Wheels", "✅ 合格"),
    "③ 全失败兜底(应挑最高分=第3轮 BAD, 标❌)": ("Brand 16 Inch Bike", "❌ 不合格"),
    "④ 脏输入(<think>+```json)仍能解析": ("Brand 16 Inch Kids Bike with Training Wheels", "✅ 合格"),
}

ok = 0
for name, kw in cases.items():
    try:
        out = choose(**kw)
        assert "生成结果" in out and "质检报告" in out
        assert "```json" not in out
        exp_title, exp_state = expected[name]
        assert exp_title in out, f"标题错误：期待含「{exp_title}」"
        assert exp_state in out, f"状态错误：期待「{exp_state}」"
        print(f"[PASS] {name}")
        ok += 1
    except Exception as e:
        print(f"[FAIL] {name} -> {e}")
print(f"\n=== 闭环逻辑验证 {ok}/{len(cases)} 通过 ===")
