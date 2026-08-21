# ============================================================
# Dify「代码报告」节点 — 最终版（直接粘贴进 Dify 代码节点）
# 功能：① 清洗 LLM A/B 的脏输出（<think>/```json 围栏/前后废话）
#      ② 三轮回合：挑最早 pass=true 的轮输出；全败则兜底最后一轮并标 ❌
#      ③ 渲染：生成结果 + 四柱评分(CDQ/A9/COSMO/Alexa) + P0/P1/P2 行动清单
# 输入变量（在 Dify 节点里声明）：gen1,qa1,gen2,qa2,gen3,qa3
# 输出变量：result
# ============================================================
import re, json

def _strip_think(s):
    """三层清洗第 1 层: 剥推理模型(DeepSeek 思考模式等)的 <think>...</think> 块。
    不剥会导致 JSON 解析失败或把推理文本当数据。"""
    return re.sub(r"<think>[\s\S]*?</think>", "", s, flags=re.IGNORECASE)

def parse(s):
    if not s:
        return {}
    s = _strip_think(str(s))
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

def is_pass(qa_str):
    """三层清洗 + 阈值硬卡: 必须 score>=8.5 且 LLM 自评 pass=true 才算通过。
    代码侧兜底, 不信任 LLM 自评(曾出现 8.3 分却标合格)。"""
    b = parse(qa_str)
    try:
        return (float(b.get("score", 0)) >= 8.5) and (b.get("pass") is True)
    except (TypeError, ValueError):
        return False

def render(gen, qa, idx):
    a = parse(gen)
    b = parse(qa)
    parts = a.get("requested_parts") or ["title", "highlights", "bullets", "backend"]
    sections = []
    if "title" in parts and a.get("title"):
        # 标题长度用 Python 实算(len), 不信任 LLM 自报的 title_length(曾误报 67 vs 实 62)
        title = a.get("title", "")
        title_len = len(title) if title else a.get("title_length", "?")
        sections.append(f"**标题**（{title_len} 字符 · 合规：{'✅' if a.get('title_compliant') else '❌'}）\n> {title}")
    if "highlights" in parts and a.get("item_highlights"):
        sections.append(f"**Item Highlights**（属性标签）\n> {a.get('item_highlights','')}")
    if "bullets" in parts and a.get("bullets"):
        bl = a.get("bullets", [])
        bl_md = "\n".join(f"{i+1}. {x}" for i,x in enumerate(bl)) if isinstance(bl,list) else str(bl)
        sections.append(f"**五点描述（Bullet Points）**\n{bl_md}")
    if "backend" in parts and a.get("backend_terms"):
        sections.append(f"**Backend Search Terms**\n> {a.get('backend_terms','')}")
    # 缺失事实与数据补全建议（防编造闭环，新增，兼容旧输出：没有就不显示）
    nc = a.get("needs_clarification")
    if isinstance(nc, list) and nc:
        sections.append("**⚠️ 待补全（无依据，未编造）**\n> " + "；".join(str(x) for x in nc))
    ds = a.get("data_suggestions")
    if isinstance(ds, list) and ds:
        sections.append("**💡 数据补全建议**\n> " + "\n> ".join(str(x) for x in ds))
    # 四柱评分（v3 新增，兼容旧输出：没有 pillars 就跳过）
    p = b.get("pillars")
    if isinstance(p, dict):
        pillars_md = " | ".join(f"{k} {v}" for k, v in p.items())
        sections.append(f"**四柱评分（CDQ/A9/COSMO/Alexa）**：{pillars_md}")
    al = b.get("action_list")
    if isinstance(al, dict):
        lines = []
        for lvl in ("P0", "P1", "P2"):
            if al.get(lvl):
                lines.append(f"- {lvl}：{('；'.join(al[lvl]))}")
        if lines:
            sections.append("**改进行动清单**\n" + "\n".join(lines))
    gen_md = "\n\n".join(sections) if sections else "_（本次未生成具体字段）_"
    score = b.get("score", "N/A")
    passed = is_pass(qa)  # 代码侧硬卡阈值, 不读 LLM 自评 pass
    issues = b.get("issues", [])
    return (f"## 🎯 亚马逊 Listing 生成结果\n\n{gen_md}\n\n---\n"
            f"### 🔍 质检报告（第 {idx} 轮）\n"
            f"- **综合评分**：{score} / 10\n"
            f"- **是否通过**：{'✅ 通过' if passed else '❌ 未通过'}\n"
            f"- **问题清单**：{('；'.join(issues)) if issues else '无明显问题'}\n"
            f"- **改进建议**：{b.get('suggestion','-')}\n")

def main(*args, **kwargs):
    """兼容 Dify 里不同的输入变量命名。
    Dify 代码节点会把声明的输入变量作为关键字参数传入，参数名=变量名。
    常见命名：单轮 gen/qa；多轮 gen1/qa1, gen2/qa2, gen3/qa3。
    用 *args/**kwargs 兜底，避免变量名不一致直接 TypeError。"""
    gen1 = kwargs.get("gen1") or kwargs.get("gen") or (args[0] if len(args) > 0 else "")
    qa1  = kwargs.get("qa1") or kwargs.get("qa") or (args[1] if len(args) > 1 else "")
    gen2 = kwargs.get("gen2") or (args[2] if len(args) > 2 else "")
    qa2  = kwargs.get("qa2") or (args[3] if len(args) > 3 else "")
    gen3 = kwargs.get("gen3") or (args[4] if len(args) > 4 else "")
    qa3  = kwargs.get("qa3") or (args[5] if len(args) > 5 else "")

    rounds = [(gen1, qa1), (gen2, qa2), (gen3, qa3)]
    chosen = None
    chosen_idx = None
    # 第一遍：挑最早 pass=true(且 score>=8.5) 的轮
    for i, (g, q) in enumerate(rounds, 1):
        if not g or not str(g).strip():
            continue
        if is_pass(q):
            chosen = (g, q); chosen_idx = i; break
    # 兜底：全失败则取最后一轮（按索引倒序找第一个非空）
    if chosen is None:
        for i, (g, q) in enumerate(reversed(rounds), 1):
            if g and str(g).strip():
                chosen = (g, q); chosen_idx = len(rounds) - i + 1; break
    if chosen is None:
        return {"result": "_（未生成任何结果）_"}
    g, q = chosen
    return {"result": render(g, q, chosen_idx)}
