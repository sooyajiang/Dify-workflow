# Dify Chatflow 知识库接入指南（demo 最优版）

目标：把「知识检索」节点接进工作流，让 LLM A 生成 Listing 时引用 7月新规（通用规则走本知识库）+ 实时竞品（走 /query 工具节点读飞书 Base，见 `作品集方案总览.md` §3.5 路线 A）。这是面试最加分的能力点。

---

## 准备：两个知识库文件
已为你备好，直接在 Dify 知识库里上传：
1. `amazon_listing_kb_rules.md` —— 2026 7月新规 + 类目规则 + Item Highlights 6维度 + 质检红线（**本文件同目录**）
2. `dify_knowledge_kids_bikes.csv` —— 32 条 Kids Bicycle Best Seller 竞品数据（标题/五点/描述，每条带榜单日期）

> 可把两个文件放进同一个知识库，检索时一起召回。
> **路线 A（已定，详见 `作品集方案总览.md` §3.5）**：通用规则（7月新规/质检红线）由本知识库「知识检索」节点提供；**动态竞品**改由 Dify「工具节点」调 Render `/query`（实时读飞书 Base 该类目最新 BSR）提供，`dify_knowledge_kids_bikes.csv` 仅作离线兜底。本指南 Step 2/3 的「知识检索」按规则检索配置即可。

---

## Step 1：在 Dify 创建知识库
1. 左侧「知识库」→「创建知识库」→ 上传 `amazon_listing_kb_rules.md`（**规则，必选**）。`dify_knowledge_kids_bikes.csv` 可一并上传作**竞品兜底**（路线 A 下动态竞品优先走 /query 工具节点，CSV 仅离线种子）。
2. 索引方式选 **高质量（High Quality）**，检索方式选 **语义检索（或混合检索）**。
3. 分段建议：规则文档按标题自然分段即可；CSV 每条竞品为一条记录。
4. 等待向量化完成 → 记下知识库名称（如 `amazon-listing-kb`）。

## Step 2：在工作流插入「知识检索」节点
1. 打开你的 listing Chatflow。
2. 在「用户输入」和「LLM A」之间，点 `+` 插入 **知识检索（Knowledge Retrieval）** 节点。
3. 该节点配置：
   - 知识库：选刚建好的 `amazon-listing-kb`
   - 查询变量：用 `{{#sys.query#}}`（或你现有的「类目/关键词」变量）
   - TopK：建议 3-5
4. 节点输出变量通常为 `{{#knowledge_retrieval_1.result#}}`（编号按实际）。

## Step 3：把检索结果喂给 LLM A
1. 推荐方式：点开 LLM A 节点 → 在「上下文」区域把「知识检索」节点挂上去，Dify 会自动把检索内容注入 Prompt（无需在 Prompt 里写变量）。备选：在「变量」区新增变量 `context` 取值选 `{{#knowledge_retrieval_1.result#}}`，再在 Prompt 引用 `{{#context#}}`。
2. 在下方的 Prompt 里加一句引用（见下方「更新后的 LLM A Prompt」）。
3. 保存。

## Step 4：更新后的 LLM A Prompt（复制即用）
```
你是一名亚马逊Listing专家。请按以下步骤执行：

第1步 意图解析
读取用户的自然语言输入 {{#userinput.query#}}，判断用户想生成哪些部分。
可选部分：title(标题)、highlights(Item Highlights)、bullets(五点描述)、backend(后台搜索词)。
将结果输出为 requested_parts 数组，例如 ["title"] 或 ["title","bullets"]。
如果用户未指定，默认输出 ["title","highlights","bullets","backend"]。

第2步 规则参考
下方上下文已提供亚马逊平台规则（标题≤75字符、Item Highlights≤125字符等），请严格遵守。

第3步 按需生成
仅生成 requested_parts 中包含的部分，未要求的部分不要输出。

输出必须是纯JSON，不要添加任何注释或代码围栏：
{
  "requested_parts": ["title","highlights","bullets","backend"],
  "title": "字符串",
  "highlights": ["字符串数组"],
  "bullets": ["字符串数组"],
  "backend": ["字符串数组"],
  "reason": "简短说明"
}
```

## Step 5：测试验证
- 输入一条自然语言，如「帮我写一个 kids bicycle 的标题和五点，主打 16 inch 可调训练轮」。
- 检查：标题是否 ≤75 字符、Item Highlights 是否为标签结构、是否参考了检索到的竞品风格。
- LLM B 质检分数应 ≥8 分（之前基线 8.6）。

---

## 面试讲解脚本（1 分钟版）
"我的作品集是一个亚马逊 Listing 智能生成与质检系统，基于 Dify 工作流。
核心设计是 **RAG + 双 Agent 联动**：
1. 用户用自然语言描述一款商品（任意类目）后，通用规则从**知识检索**节点召回（2026 7月新规），竞品由**工具节点**实时调 `/query` 取飞书 Base 该类目最新 BSR——即"实时动态检索"；
2. **生成 Agent** 基于检索内容 + 新规约束输出结构化 Listing（标题/Item Highlights/五点/Backend）；
3. **质检 Agent** 按 7 维度（含新规合规硬性门槛）打分，不达标打回重生成；
4. 我用 Code 节点做 JSON 解析和格式化展示。
这样生成是**有依据**的，不是凭空编，也方便应对平台政策变更——只要更新知识库规则，系统就能快速响应。"

## 关键亮点（写在简历/口述）
- RAG 落地：规则来自知识库、竞品来自实时 `/query`（飞书 Base），生成可溯源；竞品随爬取自动"实时"，无需重建索引。
- 政策响应机制：7月新规通过知识库更新即可生效，体现系统化思维。
- 成本意识：生成用免费 GLM-4-Flash，质检用 DeepSeek，整体近零成本。
- 诚实边界：MVP 性质，评测集 50 条级、当前以 kids bicycle 样例数据跑通（架构支持任意类目），避免过度包装。
