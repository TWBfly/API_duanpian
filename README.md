# API_duanpian: 工业化自主进化短篇小说引擎

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-green.svg)
![Framework](https://img.shields.io/badge/Engine-Narrative--Evolution-orange.svg)

**API_duanpian** 是一个基于大语言模型、ChromaDB 向量记忆、以及 Neo4j 因果图谱构建的工业级短篇小说自主生成与进化系统。它旨在通过多级审计、分层生成以及贝叶斯学习闭环，生产出具备“人味”、逻辑自洽且风格鲜明的高质量文学作品。

---

## 核心架构：神级质感的三大支柱

### 1. 外科手术式“去 AI 化”管线 (De-AI Surgery)
系统放弃了传统的一遍式生成，采用了 **3-Pass 串行生成 + 5 级动态审计**：
*   **Pass 1 (Sensory Architect)**：感官降临。强迫模型禁用背景叙事，仅允许物理动作与五感（嗅/触/听）细节。
*   **Pass 2 (Rhythm Specialist)**：节奏粉碎。由专门的节奏专家通过 Few-Shot 样本重塑长短句张力，打破 AI 惯有的排比感。
*   **Pass 3 (Soul Master)**：灵魂对冲。在终审环节剔除所有总结性抒情，强行拦截“不禁、缓缓、总之”等 AI 烂梗。

### 2. 深度因果逻辑闭环 (Causal DAG & Neo4j)
利用图数据库 Neo4j，系统实现了：
*   **状态感知**：实时追踪角色的物理状态、认知边界及“马甲身份（Identity Mask）”。
*   **伏笔池 (Foreshadowing DB)**：自动在章节中埋下 S/A/B 级伏笔，并在 8-10 章强制回路回收，确保零烂尾。
*   **绝对物理真理校验**：通过 `TruthCompositeAuditor` 严防在“女扮男装”等设定下的代词穿帮。

### 3. 贝叶斯自主进化回路 (Bayesian Evolution Loop)
系统具备自我迭代能力：
*   **DNA 学习**：模仿路径可自动提取原著的冲突公式与文笔 DNA。
*   **权重漂移**：系统通过对生成结果的量化评分，动态调整基于受众（男频/女频）的规则权重。
*   **技能固化**：高质量的“人-机”修复对会被自动归档为 Few-Shot 样本，实现模型侧的无监督进化。

---

## 快速开始

### 运行环境
*   **Neo4j**: 确保本地 Neo4j 服务已启动并配置 `NEO4J_PASSWORD`。
*   **ChromaDB**: 本地向量数据库自动维护。
*   **API Key**: 在 `.env` 中配置 `ARK_API_KEY` (优先) 或 `OPENROUTER_API_KEY`。

### 启动创作
```bash
# 模式一：原著仿写（DNA 提取与载体映射）
python3 unified_entry.py --mode reference --paths ./your_source.md --chapters 10 --workers 1

# 模式二：命题创作（基于背景设定推演）
python3 unified_entry.py --mode prompt --background "现代职场，马甲流，反派大女主" --chapters 10
```

---

## 目录矩阵

*   `evolution_api.py`: 核心进化引擎。
*   `auditors.py`: 审计管线集群。
*   `db.py`: 规则账本与 SQLite 记忆。
*   `neo4j_db.py`: 图数据库因果层。
*   `genesis_api.py`: 创世大脑（设定推演）。
*   `skill_library/`: 专家库 Few-Shot 样本。

---

## 法律说明与版权保护
系统内置 `PlagiarismGuard` 插件。在 `reference` 模式下，系统会自动分析原著实体并将其列入黑名单，严禁生成物出现原著中的专有名词、人名或独特道具名，确保每一份产出均为**神似而形不似**的原创结晶。

---

## 作者
[TWBfly](https://github.com/TWBfly)
