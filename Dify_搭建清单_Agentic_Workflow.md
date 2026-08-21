# 最终版搭建清单（Agentic Workflow）

> 目标一句话：用 Dify Chatflow 搭一个「亚马逊 Listing 生成 + 质检」应用，**用户只说一句自然语言就出合规 Listing**，且**质检不过会自动重试**，形成"工作流为手脚 + 闭环为大脑"的 Agentic Workflow。
>
> 怎么算 Agentic：
> - **骨架（手脚）= 确定性工作流**：知识检索 → 生成 → 质检 → 格式化 → 回复，顺序写死、可控可复现。
> - **大脑① 意图路由**：LLM A 自己解析用户要生成哪部分（标题/Highlights/五点/Backend），按需只出对应的。
> - **大脑② 反思闭环（Tier-1）**：质检不过 → 把建议回灌 → 重新生成 → 再质检，最多 3 轮，挑最早通过的那版。
>
> 分两阶段搭（**先 Phase 1 跑通截图，再 Phase 2 叠闭环**），避免同时改两处、debug 无从下手。

---

## 阶段 0：前置（一次性，约 10 分钟）

1. 进 Dify → 左侧「知识库」→「创建知识库」。
2. 上传本仓库的 `amazon_listing_kb_rules.md`（**必选**，2026 7月新规 + Item Highlights 6 维度 + 质检红线）。
3. （可选兜底）同一库再上传 `dify_knowledge_kids_bikes.csv`（32 条 kids bicycle 竞品），仅作离线种子；动态竞品优先走工具节点（见节点 2b）。
4. 索引方式选「**高质量**」；检索方式选「**混合检索**（语义+关键词）」；等向量化完成。库名记为 `amazon-listing-kb`。
5. 工作室 → 创建应用 → 选 **Chatflow** → 命名「亚马逊 Listing 生成与质检」。

> 模型提醒：选你账号里有额度的模型（推荐 `deepseek-chat` 或 `glm-4-flash`，**避开 qwen-plus**，曾额度耗尽报错）。生成/质检可用同一模型。

---

## 阶段 1：搭骨架（确定性工作流，先跑通）

### 节点 1：开始（Start）
- 「开始」节点**保持默认，不添加任何输入字段**——靠对话框输入 `sys.query` 驱动。

### 节点 2：知识检索（Knowledge Retrieval，只查规则）
1. 「开始」后点「+」→ 选「知识检索」。
2. 知识库选 `amazon-listing-kb`；查询变量：`{{#sys.query#}}`；TOP_K = 4。
3. 输出变量名：`{{#knowledge_retrieval.result#}}`（下文代称 `rules_context`）。

### 节点 2b：工具节点 /query（动态竞品，可选）
- 想要"实时竞品"就加：在「知识检索」后点「+」→ 选「工具」→ 调 `GET https://bsr-monitor.onrender.com/query?token=sooya1030`，输出记为 `{{#tool_query.result#}}`（代称 `comp_context`）。
- **不想配外部工具**：跳过本节点，改为在节点 2 的知识检索里同时选 `dify_knowledge_kids_bikes.csv` 数据集，用静态竞品兜底（架构仍统一，只是非实时）。Phase 1 推荐先用兜底，跑通后再换实时。

### 节点 3：LLM A（生成）
1. 加「LLM」节点。变量区新增三个：
   - `rules_context` ← `{{#knowledge_retrieval.result#}}`
   - `comp_context` ← `{{#tool_query.result#}}`（若用 CSV 兜底则改为对应检索变量）
   - `user_input` ← `{{#sys.query#}}`
2. 把下方系统提示词整段粘贴（里面的 `{{#变量#}}` 就是上面三个）。

```
你是一名资深亚马逊跨境电商 Listing 专家。

# 通用规则参考（来自知识库）
{{#rules_context#}}

# 竞品参考（来自实时 BSR，/query 工具节点）
{{#comp_context#}}

# 用户输入（自然语言）
{{#user_input#}}

# 任务
用户用自然语言描述了一款产品（可能口语化、信息不全、顺序混乱），并可能只要求生成其中某一部分。请按以下步骤：

第 1 步｜意图解析（部分生成 or 全量）
- 判断用户想要哪些部分：title（标题）/ highlights（Item Highlights）/ bullets（五点）/ backend（Backend 关键词）。
- 若用户点名某部分（如"优化标题""写五点""补 backend 词）→ requested_parts 只含这些。
- 若用户未指定 → requested_parts = 全部四项（默认全量输出）。
- 若用户提供了现有内容（如"这是我现在的标题，帮我优化"）→ 基于该内容优化而非从零；没提供则从零生成。

第 2 步｜提取关键信息
从中提取产品类型/尺寸/适龄人群/材质/核心卖点/目标市场/语种等。

第 3 步｜定向生成
只生成 requested_parts 中的部分，且严格遵守亚马逊 2026 年 7 月新规（详见上方参考）：
- 标题 ≤75 字符（含空格）；结构：品牌词 + 核心词 + 差异化卖点。
- Item Highlights ≤125 字符，必须是属性标签（非句子），覆盖 6 维度：产品本体 / 使用人群 / 成分结构 / 功能属性 / 使用方式 / 产品规格。
- 三层关键词结构：Title(核心) / Item Highlights(属性) / Backend(长尾，不重复前两层)。
- Bullet Points：5 条完整句子、说服型、面向消费者。
- requested_parts 之外的字段返回空字符串 / 空数组，不要占位填充。

# 输出（严格只输出 JSON，不要任何额外文字、不要 markdown 围栏）
{
  "requested_parts": ["title", "highlights", "bullets", "backend"],
  "title": "≤75字符标题",
  "title_length": 数字,
  "title_compliant": true,
  "item_highlights": "标签1 / 标签2 / ...（≤125字符）",
  "bullets": ["5条五点描述完整句子"],
  "backend_terms": "长尾补充词，不重复标题/Highlights",
  "category": "类目",
  "language": "en/zh/ja"
}
```

### 节点 4：LLM B（质检）
1. 加「LLM」节点。变量区新增：
   - `rules_context` ← `{{#knowledge_retrieval.result#}}`（复用检索）
   - `listing` ← `{{#llm_a.text#}}`
2. 粘贴下方提示词。

```
你是一名严格的亚马逊 Listing 合规质检员。

# 质检红线与规则（来自知识库）
{{#rules_context#}}

# 待质检的 Listing（生成节点输出）
{{#listing#}}

# 质检任务
先判断上方「待质检 Listing」中实际生成了哪些字段（参考生成节点的 requested_parts，或看哪些字段非空）。只评估已生成字段对应的维度，未生成字段标注「未生成，跳过」，不要凭空打分。
按以下维度逐项检查（仅针对已生成字段），给出 0-10 综合评分与问题清单：
1. 标题合规：≤75 字符？（硬性门槛，超了直接判不合规）
2. Item Highlights：是否为属性标签而非句子？≤125 字符？是否覆盖 6 维度？
3. 关键词堆砌 / 与标题重复？
4. Bullet Points：5 条完整句子、说服力、面向消费者？
5. Backend Terms：是否补充长尾、不重复标题/Highlights？
6. 文化差异 / 翻译地道度？
7. COSMO 覆盖度（是否覆盖算法关注属性：尺寸/适龄/材质/刹车/辅助轮等）？
8. 必备信息：是否包含适龄 / 尺寸？

# 输出（严格只输出 JSON，不要任何额外文字、不要 markdown 围栏）
{
  "score": 数字(0-10),
  "pass": true或false,
  "issues": ["问题1", "问题2"],
  "suggestion": "一句话改进建议"
}
```

### 节点 5：代码（解析 + 格式化，Phase 1 版）
1. 加「代码」节点，语言 Python。
2. 输入映射：`gen` ← `{{#llm_a.text#}}`，`qa` ← `{{#llm_b.text#}}`。
3. 输出变量：新增 `result`（类型 文本）。
4. 粘贴下方代码。

```python
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

    parts = a.get("requested_parts") or ["title", "highlights", "bullets", "backend"]

    sections = []
    if "title" in parts and a.get("title"):
        sections.append(
            f"**标题**（{a.get('title_length', '?')} 字符 · 合规：{'✅' if a.get('title_compliant') else '❌'}）\n> {a.get('title', '')}"
        )
    if "highlights" in parts and a.get("item_highlights"):
        sections.append(f"**Item Highlights**（属性标签）\n> {a.get('item_highlights', '')}")
    if "bullets" in parts and a.get("bullets"):
        bullets = a.get("bullets", [])
        if isinstance(bullets, list):
            bullets_md = "\n".join(f"{i+1}. {x}" for i, x in enumerate(bullets))
        else:
            bullets_md = str(bullets)
        sections.append(f"**五点描述（Bullet Points）**\n{bullets_md}")
    if "backend" in parts and a.get("backend_terms"):
        sections.append(f"**Backend Search Terms**\n> {a.get('backend_terms', '')}")

    gen_md = "\n\n".join(sections) if sections else "_（本次未生成具体字段）_"

    score = b.get("score", "N/A")
    passed = b.get("pass", False)
    issues = b.get("issues", [])

    md = f"""## 🎯 亚马逊 Listing 生成结果

{gen_md}

---
### 🔍 质检报告
- **综合评分**：{score} / 10
- **是否通过**：{'✅ 通过' if passed else '❌ 未通过'}
- **问题清单**：{('；'.join(issues)) if issues else '无明显问题'}
- **改进建议**：{b.get('suggestion', '-')}
"""
    return {"result": md}
```

### 节点 6：直接回复（Answer）
- 加「直接回复」节点，内容填 `{{#code.result#}}`。

### 连线 + 发布 + 测试（Phase 1 必做）
1. 连线：开始 → 知识检索 →（工具节点/query）→ LLM A → LLM B → 代码 → 直接回复。
2. 右上「发布」→「运行」。
3. 对话框输入一句自然语言测试，例如：
   > 「我想上架一款 3-5 岁小女孩的 16 寸儿童自行车，带辅助轮、粉色、主打安全和好安装，美国市场，英文文案。」
4. 应看到：标题（带字符数/合规标）、Item Highlights 标签、5 条五点、Backend 词 + 质检评分与是否通过。
5. **截图存档**（生成结果 + 质检报告）——这是作品集核心证据。
6. 顺手测"按需"：输入「帮我优化这个标题：Kids Bike 16 Inch Girls Pink with Training Wheels」→ 应只返回优化后标题，不带五点。

> Phase 1 到此截图完成，你已有一个稳定可控的工作流 demo。下面 Phase 2 把它升成 Agentic。

---

## 阶段 2：升 Agentic（加 Tier-1 重生成闭环 = 大脑②）

### 技术现实（必读）
Dify Chatflow 是 **DAG（有向无环图），不允许从后节点拉回边到前节点**，所以没有"原生 while 循环"。第 2 阶段用「**条件分支展开重试链**」实现：把"最多 3 轮"显式展开为 A1→B1→判断→A2→B2→判断→A3→B3，每轮失败把 B 的 `suggestion` 回灌下一轮 A。这是 Dify 里最可靠的做法，且每轮真实"学会"了上轮意见。

### 节点图
```
开始(sys.query)
  → 知识检索(规则)
  → 工具节点(/query 竞品)
  → LLM A1(生成)
  → LLM B1(质检)
  → 条件分支: B1.pass == true ? ── YES ──┐
  → (NO) LLM A2(带 B1.suggestion)                 │
  →      LLM B2(质检)                              │
  →      条件分支: B2.pass == true ? ── YES ──┐   │
  →      (NO) LLM A3(带 B2.suggestion)        │   │
  →           LLM B3(质检) ───────────────────┤   │
                                              ▼   ▼
                              代码节点(从第1/2/3轮挑 pass=true 的最早一轮; 全未过则取最后一轮)
                                              ▼
                                          直接回复
```

### 改造步骤（在 Phase 1 基础上）
1. **复制生成/质检为三轮**：
   - 保留 A1、B1（提示词同 Phase 1 节点 3、4）。
   - 复制出 A2、B2、A3、B3（提示词同 A1/B1）。
   - A2 额外加变量 `prev_feedback` ← `{{#llm_b1.suggestion#}}`；A3 加 `prev_feedback` ← `{{#llm_b2.suggestion#}}`。
   - A2/A3 提示词末尾加一句：「参考上轮质检改进建议：`{{#prev_feedback#}}`，在不违反用户原意前提下修正后重新生成」。
2. **加两处条件分支**：
   - 分支 1：判断 `{{#llm_b1.pass#}}` 是否为 true；true → 直达「代码节点」；false → 走 A2。
   - 分支 2：判断 `{{#llm_b2.pass#}}` 是否为 true；true → 直达「代码节点」；false → 走 A3→B3。
3. **B1/B2/B3 输出 JSON 必须含** `pass`(bool) / `score` / `suggestion`（pass=false 时 suggestion 写具体修改意见）。
4. **替换代码节点**为下方 Tier-1 版（入参 6 个：gen1/qa1/gen2/qa2/gen3/qa3）。

### 代码节点（Tier-1 版，已本地验证 5/5）
输入映射：
- `gen1` ← `{{#llm_a1.text#}}`，`qa1` ← `{{#llm_b1.text#}}`
- `gen2` ← `{{#llm_a2.text#}}`，`qa2` ← `{{#llm_b2.text#}}`
- `gen3` ← `{{#llm_a3.text#}}`，`qa3` ← `{{#llm_b3.text#}}`
- 输出变量 `result`（文本）。

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

### 多轮记忆（可选，跨轮对话）
- 在 LLM A1 之前可加「记忆 / 对话历史」节点（不同 Dify 版本名称可能为「历史记录」「记忆」），把最近若干轮对话作上下文喂给 A1，使「先改标题 → 再调五点」连续生效。节点名在你 Dify 版本里确认，加好后让 A1 引用该历史变量即可。

### 发布 + 测试（Phase 2）
1. 「发布」→「运行」。
2. 正常测试一句自然语言，确认出合规 Listing + 质检报告。
3. **验证闭环**：故意让首轮违规（如输入一个超长标题要求「帮我写个 200 字符的标题」），看系统是否自动重试出通过版，且报告标注「第 2 轮 / 第 3 轮」。
4. 截图存档「首轮违规→自动重试通过」的过程，作为"Agentic 反思闭环"的硬证据。

---

## 验收 & 截图清单（作品集证据）
- [ ] Phase 1：自然语言全量生成（标题≤75 + Highlights 标签 + 五点 + Backend + 8 维质检评分）截图。
- [ ] Phase 1：按需生成（只优化标题 / 只写五点）截图。
- [ ] Phase 2：故意违规 → 自动重试通过 截图（闭环证据）。
- [ ] 知识库规则文件 + 竞品种子 截图（RAG 可溯源）。

## 面试一句话讲法
> "我用 **Agentic Workflow**——工作流保证可控可复现（知识检索→生成→质检→格式化），Agent 式闭环保证质量自纠（质检不过自动带建议重生成、最多 3 轮挑最早通过版）。我没盲目上纯 Agent，因为输出失控对 demo 是灾难；选 workflow+闭环，是 PM 对'可控性 vs 智能度'的取舍判断。"

> 准确称「LLM 工作流 + 双 LLM 质检闭环，架构预留 Agent 化空间」，**不要硬称 agent**——懂 workflow vs agent 的取舍本身就是真实 PM 判断力。
