# 本地验证：最终版 Dify 代码节点（三轮回合 + 四柱/P0-P2 渲染）
import json
from Dify_代码节点_最终版 import main, parse

QA_FAIL = json.dumps({
    "score": 8.0, "pass": False,
    "issues": ["五点前2条缺核心关键词 kids bicycle"],
    "pillars": {"CDQ": 7, "A9": 7, "COSMO": 7, "Alexa": 7},
    "title_triage": {"keep": ["kids bike"], "move_down": [], "delete": ["best"]},
    "action_list": {"P0": ["第1条五点嵌入 kids bicycle"], "P1": ["补充适龄场景"], "P2": ["优化 Alexa 话术"]},
    "suggestion": "第1条五点未出现 kids bicycle，请在第1条开头嵌入核心词 kids bicycle 并说明适用 3-5 岁"
})
QA_PASS = json.dumps({
    "score": 9.0, "pass": True,
    "issues": [],
    "pillars": {"CDQ": 9, "A9": 9, "COSMO": 9, "Alexa": 8},
    "title_triage": {"keep": ["kids bike"], "move_down": [], "delete": []},
    "action_list": {"P0": [], "P1": ["可补适龄"], "P2": ["Alexa 话术"]},
    "suggestion": "-"
})
GEN_BAD = json.dumps({
    "requested_parts": ["title","highlights","bullets","backend"],
    "title": "Brand 16 Inch Bike", "title_length": 18, "title_compliant": True,
    "item_highlights": "16 Inch / Training Wheels / Steel",
    "bullets": ["Good bike.", "Safe.", "Stable.", "Easy install.", "Nice color."],
    "backend_terms": "kids bicycle", "category": "Kids Bicycle", "language": "en"
})
GEN_GOOD = json.dumps({
    "requested_parts": ["title","highlights","bullets","backend"],
    "title": "Brand 16 Inch Kids Bike with Training Wheels", "title_length": 44, "title_compliant": True,
    "item_highlights": "16 Inch / Training Wheels / High Carbon Steel / Pink / Adjustable Seat",
    "bullets": ["Kids bicycle for 3-5 years: stable training wheels keep little riders safe.",
                "For kids and parents: 85% pre-assembled, tool-free setup in minutes.",
                "Durable carbon steel frame survives rough play.",
                "Adjustable seat grows with your child.",
                "Cute pink color boys and girls love."],
    "backend_terms": "toddler bicycle princess bike first bike", "category": "Kids Bicycle", "language": "en"
})

# 脏输入：DeepSeek 思考模式 <think> + ```json 围栏
GEN_DIRTY = "<think>用户要粉色16寸女童车...</think>\n```json\n" + GEN_GOOD + "\n```"
QA_DIRTY = "<think>检查...</think>\n```json\n" + QA_PASS + "\n```"

cases = {
    "① 首轮失败→二轮通过（应挑第2轮, 显示四柱/P0-P2）": dict(
        gen1=GEN_BAD, qa1=QA_FAIL, gen2=GEN_GOOD, qa2=QA_PASS, gen3="", qa3=""),
    "② 全失败兜底（应挑第3轮并标❌）": dict(
        gen1=GEN_BAD, qa1=QA_FAIL, gen2=GEN_BAD, qa2=QA_FAIL, gen3=GEN_BAD, qa3=QA_FAIL),
    "③ 首轮即通过（应挑第1轮）": dict(
        gen1=GEN_GOOD, qa1=QA_PASS, gen2="", qa2="", gen3="", qa3=""),
    "④ 脏输入(<think>+```json)仍能解析+渲染四柱": dict(
        gen1=GEN_DIRTY, qa1=QA_DIRTY, gen2="", qa2="", gen3="", qa3=""),
}

expected = {
    "① 首轮失败→二轮通过（应挑第2轮, 显示四柱/P0-P2）": ("第 2 轮", "✅"),
    "② 全失败兜底（应挑第3轮并标❌）": ("第 3 轮", "❌"),
    "③ 首轮即通过（应挑第1轮）": ("第 1 轮", "✅"),
    "④ 脏输入(<think>+```json)仍能解析+渲染四柱": ("第 1 轮", "✅"),
}

ok = 0
for name, kw in cases.items():
    try:
        out = main(**kw)
        r = out["result"]
        assert "亚马逊 Listing 生成结果" in r
        assert "🔍 质检报告" in r
        assert "```json" not in r
        # 四柱必须出现（v3）
        assert "CDQ" in r and "COSMO" in r
        # 轮次与通过状态必须符合预期
        exp_round, exp_pass = expected[name]
        assert exp_round in r, f"轮次错误：期待 {exp_round}"
        assert exp_pass in r, f"通过状态错误：期待 {exp_pass}"
        print(f"[PASS] {name}")
        print("      轮次标记:", exp_round, "｜ 是否通过:", exp_pass)
        ok += 1
    except Exception as e:
        print(f"[FAIL] {name} -> {e}")
print(f"\n=== {ok}/{len(cases)} 用例通过 ===")
