# Dify Listing Chatflow — Prompt v2 + 闭环接线（按 2026 新规 / COSMO 场景化重写）

> 用途：直接覆盖 Dify 里 LLM A / LLM B 的提示词，并指导把"质检不通过→重生成"闭环接上线。
> 配套：规则库已更新为 `amazon_listing_kb_rules.md`（RAG 检索源，2026 新规 + 品牌前置 + 前 30 字符核心词 + Bullets COSMO 场景化 + Backend ≤249 字节 + 自查清单）。
> 生效前提：改完 Dify 节点后**必须点「发布」**，否则预览/运行仍是旧版。

---

## 〇、为什么之前"没闭"（一句话）

当前线上流程是 **线性** 的：`LLM B → 代码 → 直接回复`，**没有节点去读 `pass` 做分支**。LLM B 输出了 `pass` 但没人管，所以 8.0/10（还缺关键词）直接溜出去了。闭环设计写在 `Dify_Listing_Chatflow_搭建指南.md` 第 320-415 行，但**只设计未接线**。下面第 三 节就是接线步骤。

---

## 一、LLM A 提示词（复制即用，覆盖原节点 3）

```
你是一名资深亚马逊跨境电商 Listing 专家，精通 2026 年 7 月新规与 COSMO / A9 算法。

# 通用规则参考（来自知识库，含标题/Highlights/Bullets/Backend 全部硬性门槛）
{{#rules_context#}}

# 竞品参考（来自实时 BSR，/query 工具节点）
{{#comp_context#}}

# 用户输入（自然语言）
{{#user_input#}}

# 任务
用户用自然语言描述了一款产品（可能口语化、信息不全、顺序混乱），并可能只要求生成其中某一部分。请按以下步骤：

**第 1 步｜意图解析（部分生成 or 全量）**
- 判断用户想要哪些部分：title / highlights / bullets / backend。
- 点名某部分（"优化标题""写五点""补 backend"）→ requested_parts 只含这些。
- 未指定 → 全量四项。
- 用户给了现有内容 → 基于它优化而非从零；没给则从零生成。

**第 2 步｜提取关键信息**
提取产品类型 / 尺寸 / 适龄人群 / 材质 / 核心卖点 / 目标市场 / 语种等。

**第 2.5 步｜事实依据门禁（防编造，优先于生成）**
- 把内容分成两类：**硬事实**（材质 / 尺寸 / 规格 / 认证 / 数量，可编造、必须溯源）与**软卖点**（人群 / 场景 / 定性利益，可常写）。
- 硬事实只能来自：① 用户输入 ② 竞品真实数据（comp_context）③ 类目共识（仅作通用措辞）。三者皆无 → 该硬事实不写，改用软卖点，并记录到 `needs_clarification`。
- **有需求才建议补全数据**：仅当缺失的硬事实属于本类目关键决策属性（C 层 6 维度 / 高频卖点词，如车架材质 / 轮径 / 辅助轮），或用户点名但未给值时，才在 `data_suggestions` 给出"补全真实数据"建议（提供实拍参数 / 接入 Best Seller 抓取）；非关键属性缺失则安静省略，不触发建议。
- 软卖点可自由使用，但不得伪装成可量化参数。绝不虚构任何材质 / 尺寸 / 认证来凑满字段。

**第 3 步｜定向生成（严格遵守下方 2026 新规，任何字段都不得违反）**

【标题 title，≤75 字符（硬上限，超了必须回缩，见第 4 步自检）】
- 结构：[品牌名] + [核心品类词] + [1 个最强差异化属性/适配型号/基础规格]
- 品牌名前置；前 30 字符必须放核心流量大词（如 kids bicycle）；
- 禁止堆砌超过 3 个场景词；禁止虚词（Best/Top/Premium 等）；
- 核心关键词必须留在标题，不可移到 Highlights。

【Item Highlights，≤125 字符，属性标签（非句子）】
- 短句词条、逗号分隔，适配 Alexa 抓取；
- 覆盖：材质 + 使用场景 + 核心功能 + 规格参数；融入 2-3 个场景；
- 公式：[材质/规格] + [核心功能] + [使用场景/适配对象]。

【Bullet Points，4-5 条，适配 COSMO】
- 每条公式：[场景/痛点] + [产品如何解决] + [用户获得什么利益]；
- 每条专注一个卖点、带一个具体场景；至少 1 条专门讲适用人群+场景；
- 前 1-2 条必须自然嵌入核心关键词（kids bicycle / for kids / 适龄），禁止用 "little riders" 等过度同义替换替代核心词；
- 单条 ≤150 字符（前 100 字符最关键），禁止 ALL CAPS。

【Backend Search Terms，≤249 字节】
- 同义替换词 / 长尾变体 / 不适合前台展示的词；不重复标题与 Highlights。

- requested_parts 之外的字段返回空字符串 / 空数组，不要占位填充。

**第 4 步｜标题长度自检（强制，杜绝偶发超 75 字符）**
- 生成 title 后，立刻数一遍字符数（含空格、标点、连字符都算）。
- 若 > 75 字符：**必须**回缩——优先删修饰形容词、合并 / 删多余场景词、缩短规格表述，但**必须保留"品牌前置 + 前 30 字符含核心流量大词"**。
- 回缩后重新计数，直到 ≤ 75；把实际字符数填入 `title_length`，`title_compliant` 填 true。
- 绝不允许输出 > 75 字符的标题；这是硬上限，不是建议。

# 输出（严格只输出 JSON，不要任何额外文字、不要 markdown 围栏）
{
  "requested_parts": ["title", "highlights", "bullets", "backend"],
  "title": "≤75字符标题(品牌前置,前30字符含核心词)",
  "title_length": 数字,
  "title_compliant": true,
  "item_highlights": "标签1, 标签2, ...（≤125字符）",
  "bullets": ["4-5条场景化五点,前1-2条含核心关键词,单条≤150字符"],
  "backend_terms": "长尾补充词,≤249字节,不重复前两层",
  "category": "类目",
  "language": "en/zh/ja",
  "needs_clarification": ["未提供的硬事实,如 wheel_size / frame_material"],
  "data_suggestions": ["关键属性 wheel_size 缺失,建议提供真实参数或接入 Best Seller 抓取以确定,避免编造"]
}
```

> 若为**重生成轮（A2/A3）**，在变量区额外注入 `prev_feedback ← {{#llm_bN.suggestion#}}`（N=上一轮编号），并在「任务」末尾追加一句：
> `参考上轮质检改进建议：{{#prev_feedback#}}，在不违反用户原意前提下修正后重新生成，重点补齐被指出的缺失关键词/场景。`

---

## 二、LLM B 提示词（复制即用，覆盖原节点 4）

```
你是一名严格的亚马逊 Listing 合规质检员，依据 2026 年 7 月新规与 COSMO 算法判定。

# 质检红线与规则（来自知识库，含硬性不通过项）
{{#rules_context#}}

# 待质检的 Listing（生成节点输出）
{{#listing#}}

# 质检任务
**先判断上方 Listing 实际生成了哪些字段**（参考生成节点的 requested_parts，或看哪些字段非空）。**只评估已生成字段**，未生成字段标注「未生成，跳过」。

按以下维度逐项检查，给出 0-10 综合评分与问题清单：
1. 标题合规：≤75 字符？品牌前置？前 30 字符含核心流量大词？堆砌>3 场景词/含虚词？
2. Item Highlights：属性标签而非句子？≤125 字符？覆盖材质/场景/功能/规格？
3. Bullet Points：4-5 条场景化？每条 [场景→方案→利益]？前 1-2 条含核心关键词？单条≤150 字符？无 ALL CAPS？
4. Backend Terms：≤249 字节？长尾/同义补充、不重复前两层？
5. 关键词堆砌 / 与标题重复？
6. 文化差异 / 翻译地道度？
7. COSMO 覆盖度（尺寸/适龄/材质/刹车/辅助轮等）？
8. 必备信息：是否包含适龄 / 尺寸？
9. 事实依据核查：标题 / Highlights / Bullets 中材质 / 尺寸 / 认证等硬事实，能否追溯到用户输入或竞品真实数据？无依据的确定性参数（非类目通用措辞）→ 违规 [官方·A2]（虚构材质 / 规格）。
10. 数据补全闭环：若关键硬事实缺失，是否已在 `needs_clarification` / `data_suggestions` 中提示？该提示缺漏 → 扣分 [共识]（未引导用户补全真实数据）。

# pass 判定口径（务必严格执行）
- 命中任一"违规"（尤其：标题>75、品牌未前置、前 30 字符无核心词、Highlights 写句子、Bullets 前 1-2 条缺核心关键词、单条>150、ALL CAPS）→ **pass=false**
- 无违规项 且 score ≥ 8.5 → pass=true
- pass=false 时，suggestion 必须写**具体可执行的修改意见**（如："第 1 条五点未出现 kids bicycle，请在第 1 条开头嵌入核心关键词 kids bicycle 并说明适用 3-5 岁"）。

# 输出（严格只输出 JSON，不要任何额外文字、不要 markdown 围栏）
{
  "score": 数字(0-10),
  "pass": true或false,
  "issues": ["问题1", "问题2"],
  "suggestion": "一句话改进建议（pass=false 时必须具体）"
}
```

---

## 三、闭环接线步骤（把设计的"打回重生成"真正接上）

> 技术现实：Dify Chatflow 是 **DAG（有向无环图）**，不允许从后节点拉回边到前节点，没有"原生 while 循环"。标准做法 = **把"最多 3 轮"显式展开**为 A1→B1→判断→A2→B2→判断→A3，每轮失败都把上一轮 suggestion 回灌下一轮 A。下列步骤在 Dify 网页里手动拖拽即可。

### 步骤 1：备份
先在 Dify 里把当前 Chatflow 另存/导出一份（万一接错可回滚）。

### 步骤 2：把现有 LLM A / LLM B 提示词换成上面的 v2
- 节点 3（LLM A）← 复制「一、LLM A 提示词」
- 节点 4（LLM B）← 复制「二、LLM B 提示词」
- 变量不变：`rules_context` / `comp_context` / `user_input`（A）；`rules_context` / `listing`（B）。

### 步骤 3：复制出重试轮（A2/B2/A3/B3）
- 复制 LLM A 节点 → 得 **LLM A2**、**LLM A3**（提示词同 A，但各加一个变量 `prev_feedback` 并补一句"参考上轮建议重生成"）。
- 复制 LLM B 节点 → 得 **LLM B2**、**LLM B3**（提示词同 B）。
- 接线：A1→B1；A2→B2；A3→B3。

### 步骤 4：加两个「条件分支 / IF」节点
- **分支 1**（接在 B1 后）：IF `{{#llm_b1.pass#}} == true` → 走"直达代码节点"；ELSE（false）→ 接 LLM A2。
- **分支 2**（接在 B2 后）：IF `{{#llm_b2.pass#}} == true` → 直达代码节点；ELSE → 接 LLM A3。
- B3 后无条件，直接接代码节点。

### 步骤 5：接代码节点（挑最早通过轮，全败兜底最后一轮）
代码节点输入映射：
```
gen1 ← llm_a1.text , qa1 ← llm_b1.text
gen2 ← llm_a2.text , qa2 ← llm_b2.text
gen3 ← llm_a3.text , qa3 ← llm_b3.text
```
代码（已本地验证 5/5，复制即用）：
```python
import re, json

def parse(s):
    if not s:
        return {}
    s = str(s)
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

def render(gen, qa, idx):
    a = parse(gen)
    b = parse(qa)
    parts = a.get("requested_parts") or ["title", "highlights", "bullets", "backend"]
    sections = []
    if "title" in parts and a.get("title"):
        sections.append(f"**标题**（{a.get('title_length','?')} 字符 · 合规：{'✅' if a.get('title_compliant') else '❌'}）\n> {a.get('title','')}")
    if "highlights" in parts and a.get("item_highlights"):
        sections.append(f"**Item Highlights**（属性标签）\n> {a.get('item_highlights','')}")
    if "bullets" in parts and a.get("bullets"):
        bl = a.get("bullets", [])
        bl_md = "\n".join(f"{i+1}. {x}" for i,x in enumerate(bl)) if isinstance(bl,list) else str(bl)
        sections.append(f"**五点描述（Bullet Points）**\n{bl_md}")
    if "backend" in parts and a.get("backend_terms"):
        sections.append(f"**Backend Search Terms**\n> {a.get('backend_terms','')}")
    gen_md = "\n\n".join(sections) if sections else "_（本次未生成具体字段）_"
    score = b.get("score","N/A")
    passed = b.get("pass", False)
    issues = b.get("issues", [])
    return (f"## 🎯 亚马逊 Listing 生成结果\n\n{gen_md}\n\n---\n"
            f"### 🔍 质检报告（第 {idx} 轮）\n"
            f"- **综合评分**：{score} / 10\n"
            f"- **是否通过**：{'✅ 通过' if passed else '❌ 未通过'}\n"
            f"- **问题清单**：{('；'.join(issues)) if issues else '无明显问题'}\n"
            f"- **改进建议**：{b.get('suggestion','-')}\n")

def main(gen1, qa1, gen2="", qa2="", gen3="", qa3=""):
    rounds = [(gen1, qa1), (gen2, qa2), (gen3, qa3)]
    chosen = None
    for g, q in rounds:
        if not g or not str(g).strip():
            continue
        if parse(q).get("pass") is True:
            chosen = (g, q)
            break
    if chosen is None:
        for g, q in reversed(rounds):
            if g and str(g).strip():
                chosen = (g, q)
                break
    if chosen is None:
        return {"result": "_（未生成任何结果）_"}
    g, q = chosen
    idx = [i for i,(x,_) in enumerate(rounds, 1) if x is g][0]
    return {"result": render(g, q, idx)}
```

### 步骤 6：发布 + 验证
1. 右上「发布」（必须，否则预览不更新）。
2. 用之前那句 kids bicycle 输入重跑 → 若首轮缺关键词，应**自动进入 A2 带建议重生成**，直到某轮 `pass=true` 才输出；全失败也至少输出最后一轮并标 ❌。
3. 截图新结果（应见"第 2 轮 / 第 3 轮"字样）覆盖 `assets/screenshots/` 旧图，作作品集"闭环前 vs 闭环后"对比。

---

## 四、关键提醒（演示时都讲得清）
- **闭环的本质**：不是"生成错了就无限重试"，而是"最多 3 轮、每轮把上轮质检意见回灌，挑最早通过轮输出"——确定性、可控、可解释。
- **Dify 限制**：DAG 不支持回边，所以用"展开重试链"而非 while 循环，这是 Dify 里最稳的做法。
- **两道防线**：v2 提示词从**源头**卡住关键词/场景（治本）；闭环从**出口**卡住不合格（兜底）。两者配合，8.0/10 漏网问题才会真正消失。
