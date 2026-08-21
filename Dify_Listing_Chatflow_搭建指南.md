# Dify Listing 生成 + 质检 Chatflow 搭建指南（节点 · 纯 Listing 版：自然语言 + 双 LLM + /query 竞品）

> 定位：作品集「智能层」里的 **AI 应用样板**——基于 RAG（知识库召回真实竞品 + 2026 7月新规）+ 双 LLM（生成 / 质检）的亚马逊 Listing 工作流。
> 与竞品监控无关：竞品监控走飞书主动推送（见 `feishu_report.py`），**本 Chatflow 只做 Listing 生成与质检**，是更"AI"的那块。
> 本文是单一可照做入口；通用规则文件已备好上传即可，竞品由「工具节点 /query」实时取飞书 Base（kids bicycle 已爬数据即种子，`dify_knowledge_kids_bikes.csv` 作离线兜底）。

---

## 〇、前置资产（本仓库已备齐，直接上传即可）

| 文件 | 用途 | 怎么用 |
|---|---|---|
| `amazon_listing_kb_rules.md` | 2026 7月新规 + Item Highlights 6 维度 + 质检红线 | 上传到 Dify 知识库 |
| `dify_knowledge_kids_bikes.csv` | 32 条 Kids Bicycle Best Seller 竞品（标题/五点/描述） | 可选：作竞品兜底上传；路线 A 下动态竞品优先走 /query 工具节点 |
| `dify_listing_client.py` | Chatflow 发布为 API 后的调用客户端 | 发布后填 key 即可代码侧调用 |

> 知识库规则详情（三层关键词、75 字符标题、125 字符 Highlights、质检红线）见 `amazon_listing_kb_rules.md`，本指南不重复，生成/质检节点直接引用。

---

## 一、节点架构（知识检索取规则 + /query 工具节点取竞品）

```
[开始] 用户输入自然语言(sys.query)
   │
   ▼
[知识检索] 从 amazon-listing-kb 召回【通用规则】→  rules_context
   │
   ▼
[工具节点 /query] 调 Render 取【该类目最新 BSR 竞品】→  comp_context
   │
   ▼
[LLM A 生成]  rules_context + comp_context + 用户自然语言(sys.query)  →  结构化 Listing JSON
   │
   ▼
[LLM B 质检]  rules_context + LLM A 输出  →  评分 + 是否通过 + 问题清单
   │
   ▼
[代码]  解析 LLM A/B 的 JSON → 合并格式化成美观 Markdown
   │
   ▼
[直接回复]  输出 Code 结果
```

> 设计取舍（面试讲点）：生成与质检**拆成两个 LLM 节点**而非一个，职责单一、可分别调不同模型（生成用强模型、质检用便宜模型）、每步可见好截图。质检节点**当前（v1 线上版）不打回重生成**（无循环），直接给分数与建议——这是确定性的 workflow，不是自主 Agent，更稳更可控，适合 demo。
> **闭环升级（已设计待接线）**：把"质检 `pass=false` → 带 `suggestion` 回灌 LLM A 重生成（最多 3 轮）"的节点图、Prompt 改动、已本地验证 5/5 的代码节点，全部整理在 **`Dify_prompts_v2.md`** —— 当前线上流程未接该回路，所以 8.0/10（缺关键词）会直接溜到「直接回复」。按 `Dify_prompts_v2.md` 第三节接线即可真正闭环比纯线性管线。

---

## 二、输入方式：用户自然语言（无需结构化变量）

本 Chatflow 走**对话型（Chatflow）**，**不定义任何结构化输入变量**——用户直接用大白话描述产品，由 LLM A 自己从中提取关键信息再生成 Listing。

- 用户输入示例（直接发在对话框）：
  > 「我想上架一款 3-5 岁小女孩的 16 寸儿童自行车，带辅助轮、粉色、主打安全和好安装，目标市场美国，英文文案。」
- 按需部分生成示例（用户只想要某块时，工具只出那块，不堆无关字段）：
  > 「帮我优化这个标题：Kids Bike 16 Inch Girls Pink with Training Wheels」→ 只返回优化后的标题，不带五点 / Highlights。
  > 「帮我把五点描述补一下，产品是 16 寸粉色女孩自行车，主打安全」→ 只返回五点，不写标题。
  > 不指定时默认全量输出（标题 + Highlights + 五点 + Backend）。
- **检索分两类（路线 A，详见 `作品集方案总览.md` §3.5）**：
  - **通用规则**（7 月新规 / 质检红线，全类目通用）→ 走「知识检索」节点查 Dify 数据集 `amazon-listing-kb`（含 `amazon_listing_kb_rules.md`）；查询变量绑 `{{#sys.query#}}`，TOP_K=4，混合检索。
  - **动态竞品**（该类目最新 BSR）→ 走「工具节点」调 Render `/query`（读飞书 Base），把返回竞品文本作 `context` 喂 LLM A；`kids bicycle` 已爬数据即由它返回，`dify_knowledge_kids_bikes.csv` 可作离线种子兜底。
- LLM A 拿到 `{{#sys.query#}}` + 规则 `rules_context` + 竞品 `comp_context`，先解析自然语言、再生成结构化 Listing。

> 想做批量/代码侧调用，仍可用 `dify_listing_client.py`（Workflow 模式传结构化 inputs），但**主 demo 就是自然语言对话**，最直观、最贴合「用户说一句话就出 listing」的叙事。

---

## 三、逐节点搭建

### 节点 1：开始（Start）
工作室 → 创建应用 → 选 **Chatflow** → 命名「亚马逊 Listing 生成与质检」。
「开始」节点**保持默认即可，不添加任何输入字段**（靠对话输入 `sys.query` 驱动）。

### 节点 2：知识检索（Knowledge Retrieval，仅查通用规则）
1. 先建知识库（见 §四），上传 `amazon_listing_kb_rules.md`（**只用规则文件**，竞品改走工具节点，见节点 2b）。
2. 在「开始」后点「+」→ 选「知识检索」。
3. 知识库：选 `amazon-listing-kb`（含 `amazon_listing_kb_rules.md`）；查询变量：`{{#sys.query#}}`；TOP_K=4。
4. 该节点输出变量通常为 `{{#knowledge_retrieval.result#}}`（下文用 `rules_context` 代指）。

### 节点 2b：工具节点（竞品，动态，调 /query）
1. 在「知识检索」后点「+」→ 选「工具」（自定义 API 工具 / Tool）。
2. 调用 `GET https://bsr-monitor.onrender.com/query?token=sooya1030`；返回飞书 Base 中该类目最新 BSR 竞品 JSON。
3. 输出变量记为 `{{#tool_query.result#}}`（下文用 `comp_context` 代指）。
4. 流 A 阶段 Base 里仅 `kids bicycle` 种子，`/query` 直接返回它；流 B 接通 `?category=` 过滤后支持任意类目。
5. **兜底**：若暂不想配工具节点，可在「知识检索」节点同时选 `dify_knowledge_kids_bikes.csv` 数据集，用静态竞品代替（架构仍统一，只是非实时）。

### 节点 3：LLM A（生成）
1. 在工具节点后加「LLM」节点，模型选你可用的（如 `gpt-4o-mini` / `deepseek-chat` / `glm-4-flash`）。
2. 变量区新增：
   - `rules_context` ← `{{#knowledge_retrieval.result#}}`（通用规则）
   - `comp_context` ← `{{#tool_query.result#}}`（动态竞品；若用 CSV 兜底则改为对应检索变量）
   - `user_input` ← `{{#sys.query#}}`（用户的自然语言描述）
3. 把下方「系统提示词」整段粘贴（提示词中 `{{#context#}}` 改为同时引用 `{{#rules_context#}}` 与 `{{#comp_context#}}`）。提示词已内置**「意图解析 → 部分生成」**逻辑：用户说"只优化标题"就只出标题、"写五点"就只出五点，不指定则全量（见提示词「第 1 步」）。

**LLM A 提示词（复制即用）：**
```
你是一名资深亚马逊跨境电商 Listing 专家。

# 通用规则参考（来自知识库）
{{#rules_context#}}

# 竞品参考（来自实时 BSR，/query 工具节点）
{{#comp_context#}}

# 用户输入（自然语言）
{{#user_input#}}

# 任务
用户用自然语言描述了一款产品（可能口语化、信息不全、顺序混乱），并可能**只要求生成其中某一部分**。请按以下步骤：

**第 1 步｜意图解析（部分生成 or 全量）**
- 判断用户想要哪些部分：`title`（标题）/ `highlights`（Item Highlights）/ `bullets`（五点）/ `backend`（Backend 关键词）。
- 若用户点名某部分（如"优化标题""写五点""补 backend 词"）→ `requested_parts` 只含这些。
- 若用户未指定 → `requested_parts` = 全部四项（默认全量输出）。
- 若用户提供了现有内容（如"这是我现在的标题，帮我优化"）→ 基于该内容**优化**而非从零；没提供则**从零生成**。

**第 2 步｜提取关键信息**
从中提取产品类型/尺寸/适龄人群/材质/核心卖点/目标市场/语种等。

**第 3 步｜定向生成**
只生成 `requested_parts` 中的部分，且严格遵守亚马逊 2026 年 7 月新规（详见上方参考）：
- 标题 ≤75 字符（含空格）；结构：品牌词 + 核心词 + 差异化卖点。
- Item Highlights ≤125 字符，必须是属性标签（非句子），覆盖 6 维度：
  产品本体 / 使用人群 / 成分结构 / 功能属性 / 使用方式 / 产品规格。
- 三层关键词结构：Title(核心) / Item Highlights(属性) / Backend(长尾，不重复前两层)。
- Bullet Points：5 条完整句子、说服型、面向消费者。
- `requested_parts` 之外的字段**返回空字符串 / 空数组**，不要占位填充。

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
1. 在 LLM A 后加「LLM」节点。
2. 变量区新增：
   - `rules_context` ← `{{#knowledge_retrieval.result#}}`（通用规则，复用检索结果）
   - `listing` ← `{{#llm_a.text#}}`（生成节点输出）
3. 粘贴下方提示词。

**LLM B 提示词（复制即用）：**
```
你是一名严格的亚马逊 Listing 合规质检员。

# 质检红线与规则（来自知识库）
{{#rules_context#}}

# 待质检的 Listing（生成节点输出）
{{#listing#}}

# 质检任务
**先判断上方「待质检 Listing」中实际生成了哪些字段**（参考生成节点的 `requested_parts`，或看哪些字段非空）。**只评估已生成字段对应的维度**，未生成字段标注「未生成，跳过」，不要凭空打分。
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

### 节点 5：代码（Code，解析 + 格式化）
1. 在 LLM B 后加「代码」节点，语言选 **Python**。
2. 输入变量映射：
   - `gen` ← `{{#llm_a.text#}}`
   - `qa` ← `{{#llm_b.text#}}`
3. 输出变量：新增一个 `result`（类型 文本）。
4. 把下方代码整段粘贴（Dify 代码节点用 `main` 函数，return 字典）。

**Code 节点代码（复制即用）：**
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

    # 用户要求生成的部分；缺省视为全量（兼容不带 requested_parts 的旧输出）
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
在代码节点后加「直接回复」节点，内容填 `{{#code.result#}}`。
最后把连线理顺：开始 → 知识检索 → 工具节点(/query) → LLM A → LLM B → 代码 → 直接回复。

---

## 四、知识库创建（一次性）

1. 左侧「知识库」→「创建知识库」→ 上传 `amazon_listing_kb_rules.md`（**规则，必选**，供节点 2 知识检索）。
2. （可选）`dify_knowledge_kids_bikes.csv` 可一并上传到同一库作**竞品兜底**；但路线 A 下动态竞品优先走「工具节点 /query」（读飞书 Base），CSV 仅作离线种子。
3. 索引方式：**高质量**；检索方式：**混合检索**（语义+关键词）。
4. 分段：规则文档按标题自然分段；CSV 每条竞品为一条。
5. 等待向量化完成 → 库名记为 `amazon-listing-kb`，回填到节点 2。

---

## 五、发布与测试

1. 右上「发布」→「运行」。
2. 在对话框直接输入一句自然语言，例如：
   > 「我想上架一款 3-5 岁小女孩的 16 寸儿童自行车，带辅助轮、粉色、主打安全和好安装，美国市场，英文文案。」
3. 发送，应看到：标题（带字符数/合规标）、Item Highlights ��签、5 条五点、Backend 词，以及质检评分与是否通过。
4. 验收：标题 ≤75 字符、Highlights 为标签结构、质检分数 ≥8。截图存档作作品集证据。
5. 发布为 API 后，用 `dify_listing_client.py` 填 `DIFY_API_KEY` 即可代码侧批量调用。

---

## 六、面试讲解脚本（1 分钟）

> "我的作品集里有一块是**亚马逊 Listing 智能生成与质检**，基于 Dify 工作流，核心是 **RAG + 双 LLM 联动**：
> 1. 用户用**自然语言**描述一款商品（任意类目，不填表），系统先**动态匹配类目**；
> 2. **通用规则**（2026 7月新规 / 质检红线）走知识检索节点召回；**竞品**走工具节点实时调我部署在 Render 的 `/query`（读飞书 Base 里该类目最新 BSR 数据）——即"实时动态检索"，不往知识库硬灌；
> 3. **生成 LLM** 基于规则 + 实时竞品 + 新规约束，输出结构化 Listing（标题/Item Highlights/五点/Backend）；
> 4. **质检 LLM** 按 8 维度（含新规硬性门槛）打分，给出是否通过与改进建议；
> 5. 用 **Code 节点** 把两段 JSON 解析、合并、格式化成直观报告。
> 生成是**有依据**的、不是凭空编；政策变了只要更新规则知识库，系统就能快速响应——这体现系统化与可演进思维。"

---

## 七、亮点与诚实边界（写进简历/口述）

- **RAG 落地**：规则来自知识库、竞品来自实时 `/query`（飞书 Base），生成可溯源、可解释；竞品随爬取更新而自动"实时"，无需重建索引。
- **生成/质检职责分离**：可分别选型与控本（如生成用强模型、质检用便宜模型）。
- **政策响应机制**：7月新规通过知识库更新即可生效。
- **诚实边界（务必讲）**：当前流 A 以 kids bicycle 已爬数据跑通（种子数据），但架构支持任意类目——类目匹配（LLM A 归一化）+ 动态竞品走 `/query` 实时取飞书 Base（Render 自动爬已就绪）；接通 `?category=` 过滤即现爬现生成；质检是"评分+建议"非自动打回重生成（确定性 workflow，非自主 Agent）。避免过度包装。

---

## 八、日后优化

- **自动打回重生成**：用「问题分类 / 迭代」节点，当 `pass=false` 时把建议回灌 LLM A 重生成（最多 N 轮）。**→ 已实现设计，落地步骤与代码见 `Dify_prompts_v2.md` 第三节（Dify DAG 限制下用"展开重试链"代替 while 循环，最多 3 轮）。**
- **多类目（核心需求，非固定白名单）**：用户输入任意类目自然语言 → **动态类目匹配**（解析到真实 Amazon 类目节点，防错：真实类目树逐级下钻 + 搜索面包屑交叉验证 + 置信度门控 HITL，LLM 只做归一化）→ **自动爬 BSR**（按匹配类目触发 `serve.py` / 爬虫 skill）→ 落飞书 Base → 生成 listing（检索架构见 `作品集方案总览.md` §3.5：静态规则走 Dify 数据集、动态竞品走 `/query` 工具节点）。即"用户说啥类目就匹配啥、现爬现生成"，不用写死类目列表；`kids bicycle` 仅为已爬样例。详见 `作品集方案总览.md`。
- **评测集沉淀**：建 50 条标准输入→输出的评测集，量化"质检通过率/平均分数"作为作品集指标。
- **与监控联动**：把竞品监控里的高频词/价格带作为生成种子，让用户在自然语言输入里补充，形成"监控→生成"闭环。

---

## 九、Agent 化升级路径（对应 `作品集方案总览.md` §十）

当前是**确定性工作流**（节点顺序写死，LLM 仅在定点调用）。真 Agent 需四大特征：动态规划 / 工具自主决策 / 跨轮记忆 / 反思-迭代闭环。三档递进升级：

- **第 1 档（强烈建议，低成本）**：加「质检 `pass=false` → 带 `suggestion` 回灌 LLM A 重生成 → 再质检（最多 2–3 轮）」闭环 + 多轮记忆。即从 workflow 升为「带反馈闭环的 AI 系统」。这恰是用户最初 v3 设计已规划、v1 线上版暂时未接线的能力——**具体 Prompt 改动、节点接线图、已验证代码均在 `Dify_prompts_v2.md`，照做即可闭环比纯线性管线**。
- **第 2 档（中成本）**：切 Dify「Agent 应用类型」或加「编排 LLM 节点」做动态路由，获得动态规划 + 工具自主决策。
- **第 3 档（高成本，非必）**：代码级 Agent（LangGraph / AutoGen）。PM 作品集通常不必要。

> **面试讲法**：准确称「LLM 工作流 + 双 LLM 质检闭环，架构预留 Agent 化空间」——**不要硬称 agent**，懂 workflow vs agent 的取舍本身就是真实 PM 判断力。

### 9.1 第 1 档落地步骤（重生成闭环 + 多轮记忆）

**技术现实（必读）**：Dify Chatflow 是 **DAG（有向无环图），不允许从后节点拉回边到前节点**，所以没有"原生 while 循环"可拖。第 1 档用「**条件分支展开重试链**」实现：把"最多 3 轮"显式展开为 A1→B1→判断→A2→B2→判断→A3，每轮失败都把 B 的 `suggestion` 回灌下一轮 A。这是 Dify 里最可靠的做法，且每轮真实"学会"了上轮意见。

**节点图**
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

**各节点要点**
1. LLM A1：提示词同 §三 节点 3，变量 `rules_context` / `comp_context` / `user_input`。
2. LLM A2 / A3：提示词同 A1，**额外注入上轮质检意见**——A2 加变量 `prev_feedback ← {{#llm_b1.suggestion#}}`，A3 加 `prev_feedback ← {{#llm_b2.suggestion#}}`；提示词末尾加一句「参考上轮质检改进建议：`{{#prev_feedback#}}`，在不违反用户原意前提下修正后重新生成」。
3. LLM B1 / B2 / B3：提示词同 §三 节点 4，输出 JSON 必须含 `pass`(bool) / `score` / `suggestion`（suggestion 在 pass=false 时写具体修改意见）。
4. 条件分支（两处）：判断 `{{#llm_b1.pass#}}` / `{{#llm_b2.pass#}}` 是否为 true；true 走"直达代码节点"分支，false 走下一轮。
5. 代码节点（见下，已本地验证 5/5）：入参 `gen1←llm_a1.text, qa1←llm_b1.text, gen2←llm_a2.text, qa2←llm_b2.text, gen3←llm_a3.text, qa3←llm_b3.text`；输出 `result`。

**代码节点（main，已验证）**
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

**多轮记忆（跨轮对话）**：在 LLM A1 之前加「对话历史 / 记忆」节点（不同 Dify 版本名称可能为「历史记录」「记忆」「conversation history」），把最近若干轮对话作为上下文喂给 LLM A，使"先改标题 → 再调五点"连续生效。具体节点名在你 Dify 版本里确认，加好后让 A1 引用该历史变量即可。

**验证**：代码节点已本地跑 5 用例全过——①首轮通过选第 1 轮；②重试第 2 轮通过（且兼容 ` ```json ` 脏围栏）；③三轮全败兜底取第 3 轮；④早期分支未触发时选第 1 轮；⑤按需只标题在第 2 轮通过时仅输出标题。
