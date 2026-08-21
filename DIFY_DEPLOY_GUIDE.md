# Dify Listing 生成 Chatflow：发布为 API + 接入知识库 操作指南

> 面向 AI PM（零基础可照抄）。目标：把你之前搭的「亚马逊 listing 生成 + 质检」Chatflow（自然语言 + 双 LLM + /query 竞品），
> 从「只能在 Dify 网页里手动试」升级成「对外发布成 API、可被代码/飞书调用」，
> 并接上规则知识库 + 实时竞品（RAG：规则走知识检索、竞品走 /query 工具节点，见 `作品集方案总览.md` §3.5），让生成结果有真实数据支撑。
> 这是你转型作品集里**最有分量的一件**——它证明你能把一个 AI 应用真正"产品化落地"。

---

## 一、你已经有什么（本目录交付物）

| 文件 | 作用 |
|------|------|
| `dify_knowledge_kids_bikes.csv` | 32 条 Kids Bike 真实竞品（五点+描述+价格+评分），**作竞品兜底素材**；路线 A 下动态竞品优先走 /query 工具节点（实时读飞书 Base） |
| `build_dify_knowledge.py` | 知识库生成脚本（以后想增量更新竞品数据，跑它即可） |
| `dify_listing_client.py` | **API 调用客户端**：发布后从代码侧调用 Chatflow 生成 listing |
| 本指南 | 发布 + 接知识库 + 联调的完整步骤 |

---

## 二、步骤 1：发布 Chatflow 为 API（拿两个值）

1. 打开 Dify，进入你的「listing 生成」Chatflow 应用。
2. 右上角点 **「发布」→「更新」**，确保是最新版本。
3. 点发布按钮**旁边的「API 访问」**（有的版本叫「访问 API」/「API 文档」）。
4. 记下两个东西：
   - **API 服务器地址**：云端默认 `https://api.dify.ai/v1`；自建填你的域名（**一定要带 `/v1` 后缀**）。
   - **API Key**：点「生成」或「显示」，复制形如 `app-xxxxxx` 的那串。
5. 这两个值就是后面脚本要填的 `DIFY_BASE_URL` 和 `DIFY_API_KEY`。

> ⚠️ API Key 等同于你应用的"密码"，**不要写进要公开分享的文件**；本指南用 `.env` 或脚本顶部配置，不会主动泄露。

---

## 三、步骤 2：确认你的输入 / 输出变量名

脚本要往 Dify 传参数，变量名必须和 Dify 里**一模一样**（大小写敏感）。

- **看输入变量**：应用内点「预览」，左侧有个「输入变量」面板；或「编排」页里各节点之间的变量。
- **看输出变量**（仅 Workflow 模式）：看「结束」节点里定义的输出变量名（例如 `generated_listing`、`quality_score`）。

> 把你在 Dify 看到的变量名，填进 `dify_listing_client.py` 的 `INPUTS = {...}` 字典的**键**里。
> 示例常见命名：`product_keyword` / `target_audience` / `tone` / `language`——**以你 Dify 里实际为准**，示例只是参考。

---

## 四、步骤 3：创建并导入知识库（RAG 核心，路线 A）

让 listing 生成"有依据"，靠的就是这步（检索架构见 `作品集方案总览.md` §3.5）：
- **通用规则**（7月新规/质检红线）→ 知识库（知识检索节点）；
- **动态竞品**（该类目最新 BSR）→ Dify「工具节点」调 Render `/query`（实时读飞书 Base），`dify_knowledge_kids_bikes.csv` 仅作离线兜底。

1. Dify 左侧点 **「知识库」→「创建知识库」→「导入已有文本」**。
2. 上传 `amazon_listing_kb_rules.md`（**规则，必选**）；`dify_knowledge_kids_bikes.csv` 可一并上传作竞品兜底。
3. 索引方式选 **「高质量」**（云端默认自带 Embedding 模型）。
4. 分段设置：规则文档按标题自然分段；CSV 每条竞品为一条。
5. 点「保存并处理」，等索引完成（几十秒到几分钟）。
6. **把知识库接到 Chatflow（规则检索）**：
   - 回到应用「编排」页面，在「知识检索」节点选刚建的知识库（含规则）。
   - 召回参数：召回数量 `3~5`，相似度阈值先默认。
   - 在 LLM A 提示词里引用规则：`{{#rules_context#}}`（竞品引用 `{{#comp_context#}}`，来自 /query 工具节点）。
7. **竞品走工具节点**：在「知识检索」后加「工具」节点，调用 `GET https://bsr-monitor.onrender.com/query?token=sooya1030`，输出 `{{#comp_context#}}`。
8. 改完**重新「发布」一次**（接了知识库/工具要重新发布才生效）。

---

## 五、步骤 4：用客户端脚本联调跑通

1. 打开 `dify_listing_client.py`，两种方式填凭证：
   - **方式 A（推荐新手）**：直接改顶部 `CONFIG` 区的 `DIFY_BASE_URL`、`DIFY_API_KEY`、`INPUTS`。
   - **方式 B（上线用）**：在旁边放一个 `.env` 文件，写：
     ```
     DIFY_BASE_URL=https://api.dify.ai/v1
     DIFY_API_KEY=app-xxxxxx
     DIFY_MODE=chat
     ```
2. 确认 `MODE` / `--mode`：
   - 你的应用是**对话型 Chatflow** → 用 `chat`
   - 你的应用是**Workflow（工作流）** → 用 `workflow`
3. 运行（示例）：
   ```bash
   # chat 模式，顺手覆盖关键词测试
   python dify_listing_client.py --mode chat --keyword "kids balance bike 2-5 years"
   # workflow 模式
   python dify_listing_client.py --mode workflow
   ```
4. 终端打印出生成的 listing = **联调成功** ✅

---

## 六、常见报错速查

| 现象 | 原因 | 解决 |
|------|------|------|
| `401 Unauthorized` | API Key 错 / 没填 | 重新复制 Dify 的 Key，检查前后空格 |
| `400 variable xxx not found` | `INPUTS` 键名和 Dify 不一致 | 回到步骤 2，核对变量名大小写 |
| `404 Not Found` | `BASE_URL` 没带 `/v1`，或应用未发布 | 补全 `/v1`；确认已点「发布」 |
| 规则召回为空 / 回答没用到新规 | 知识库未索引完 / 未接知识检索 / 召回参数太严 | 等索引完成；确认「知识检索」节点已接规则库；放宽阈值 |
| 竞品没用到 / 像"凭空写" | 工具节点未配 / 提示词没引用 `{{#comp_context#}}` | 检查步骤 4 第 7 点；确认 /query 返回该类目数据 |

---

## 七、做完之后（作品集加分项，可选）

- **接入飞书**：把 `dify_listing_client.py` 包装成定时任务，每天用最新 BSR 数据生成 listing 草稿，自动写入飞书 Base——形成"竞品抓取 → AI 生成 → 沉淀"闭环。
- **做效果评估**：用已抓的 80 条竞品，人工抽检 10 条生成结果，写一段"生成质量评估"放进作品集说明。
- **讲设计决策**：面试时能说清"为什么接 RAG 而不是纯 prompt""召回参数怎么定""质量节点怎么打分"，就是 PM 的核心竞争力。

---

> 需要我帮你联调时，把 **Dify API Key** 和**你的输入/输出变量名**发我，我可以直接把 `dify_listing_client.py` 填好并跑通给你看。
