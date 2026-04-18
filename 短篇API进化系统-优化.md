本项目致力于构建一个支撑**亿级量产**、基于 OpenAI Agents SDK 的**无限进化级**短篇小说创作引擎。通过深度整合“绝对知识防火墙 (Data Quarantine Wall)”、“Master Editor V6 (去AI化手术)”与“贝叶斯记忆衰减机制”，彻底解决 AI 写作中的“近亲繁殖”、“悬浮感”与“逻辑断层”。

**进化终极目标**：永久记忆，原著与人工精修纯正文章持续学习，越写越精，字里行间具备真人大师的“毛刺感”与“灵魂张力”，实现写几万几亿本小说也绝不退化且绝不套路化的“神级质感”。

---

## 🏛️ 全局系统宪法 (Global System Axioms)
*所有 Agent 必须无条件执行的最高原语，严禁任何形式的变异或突破。*

1.  **绝对去AI感约束 (No AI-Flavor)**：拒绝解释性尾注（不写“——那是XXX”）；拒绝回声头排比；感官降临为先（不用视觉起笔，切入嗅觉/触觉）；长短句极端错落（模拟人类呼吸节奏）。
2.  **男女频靶向隔离 (Demographic Quarantine)**：男频与女频的叙事逻辑、爽点模式、情感维度必须绝对隔离。男频主攻杀伐果断/逻辑闭环/宏大叙事；女频主攻情感拉扯/修罗场/微表情侧写。
3.  **多重物理/伪装逻辑锁 (Strict Disguise Logic)**：针对**男扮女装/女扮男装**、多重马甲身份，建立表（公共认知表象视角）里（本质与私人视角）两套独立状态账本，从代词、体貌特征、行为反馈彻底杜绝“一眼假穿帮”。
4.  **去套路化底线 (Zero-Cliche Principle)**：拒绝俗套降智反派。每段情节生成前强制撞页亿级知识库，反向变异老旧桥段设计（如退婚流、送金币流）。
5.  **设定绝对统辖 (Setting Absolute Compliance)**：生成内容必须与大纲和时代背景100%咬合。古代严禁现代思维或跨界道具，逻辑与剧情必须做到情理之中、意料之外。

---

## 🛠️ 亿级智能基建 (Billion-Scale Infrastructure)

- **核心大脑层**：接入 `main.py` 配置的 **DeepSeek-V3** (Volcengine Ark)。
- **长短期双线程记忆引擎 (Dual Memory Core)**：
   - **短期滑动窗口 (Short-Term Window)**：保持剧集进行时的情绪连续性、微动作衔接，精确控制场域氛围。
   - **长期因果图谱 (Long-Term Causal DAG)**：基于 **Neo4j** 管理数千万字的时间线与人物动态账本，保障长线逻辑如钢丝般严密。
- **伏笔与悬念独立池 (Foreshadow & Payoff Ledger)**：系统将所有“抛出的线索/隐秘人物/残缺道具”推入伏笔库，并在特定规划阶段触发回调提示，强制完成逻辑闭环，“挖坑必填”。
- **绝对知识层级防火墙**：存储分为 `Gold库 (大师原著/精修)` 与 `Sandbox库 (AI初稿)`。仅在人工校验打分（或多模态交叉高分验证）无误的Sandbox数据，才被洗入Gold库。原稿作为永恒北极星，抵御模型崩塌。

---

## 📋 全维度多Agent任务流水线 (Omni-Agent Workflow)

### 1. 自动高保真抓取与净化 (Link, Parse & Quarantine)
- **监听与存证**：自动化提取外部原著高质量片段与爆文链接，深度解析提取剧情要素，存入 Gold 库。
- **去噪洗稿**：剥离无效网文口语，纯化具备持久生命力的“大作家文风片段”。

### 2. 人物多轨建构与频段定位 (Targeting & Multi-Track Setup)
- **频段锚定**：首轮 Agent 分析，锁定受众定位（男频/女频），动态切换叙事语言模型与冲突类型库。
- **伪装防穿帮矩阵**：对含“男扮女装/隐藏首富”等元素主角引入【状态锁】机制。审计Agent会在文本生成期强制拦截类似“男扮女装状态下被路人称呼‘他’”或“未解除伪装时暴露喉结生理特征”的低级错误。

### 3. 因果剧情池排雷与反套路化生成 (Plot De-duplication & Anti-Cliche)
- **设定对齐查重**：在生成 10卷/大纲 以及每一阶段细纲前，把“核心梗”推入 Milvus 历史长河库比对。高相似（>75%）立即触发“反俗套变异机制”，强制转变剧情走势，拒绝同质化。
- **环境一致性审计**：环境道具、时代特质白名单/黑名单校验，斩断一切背景不搭的违和感。

### 4. 章节细纲裂变与多级审计定调 (Planning, Foreshadowing & Scoring)
- **布局编织**：生成“楔子 + 章纲”。并在过程中强制向“伏笔账本”写入悬念。
- **对抗性双盲审计**：以极其严苛的“逻辑法官”+“文风大师”进行打分，<85 分立即销毁并 Handoff 重新回滚种子生成。

### 5. 拟人代词与语境双重固化 (Semantic Alignment)
- 通过 `fixAI_prompt.md` 深度约束违禁词典，封杀“不禁莞尔”、“宛如”、“不可测的深渊”等AI烂梗高频词。
- 强制上下文语义角色认知审计：角色绝对不能未卜先知，只有其当前所掌握或推演范围内的信息流露。

### 6. 三层次去AI化手术体系 (3-Pass De-AI Surgery Writing)
- **Pass 1: 感官降临**：强制物理反应、嗅觉/听觉作为场景切入，禁止心理活动白描。
- **Pass 2: 节奏粉碎**：打破文字排平，强逼高强度动作交杂内心短句，重塑真人的行文张力。
- **Pass 3: 灵魂对冲**：去除任何狗尾续貂的“总结式形容词”，让行为本身直接刺向读者。

### 7. 终途：闭环净化与记忆结晶 (Bayesian Decay & Permanent Evolution)
- **伏笔回收审计**：最终章节核销对照表，如果有遗漏的伏笔，指令 Agent 重溯或后延补充。
- **贝叶斯记忆汰换**：在数以万计小说的生成循环中，对那些从未被触发、或经常遭遇人工否定的“烂梗规则”执行降权直至彻底失忆。
- **人机联觉进化**：当人工精修了一段被退回的情节后，系统对比差异，提取出“风格差值特征”，自动编译为一条新的金科玉律，永久纳入全球宪兵体系。

---

## 🚀 核心架构演示代码 (Architecture Demo Logic)
```python
# 基于混合记忆与双频段隔离的无尽演化引擎
from evolution_api import MasterEvolutionEngine
from auditors import DisguiseLogicAuditor, DemographicAuditor, ForeshadowingLedger

# 装载全局法则 (涵盖男女频禁词、去AI手术刀与身份追踪底座)
axioms = load_global_axioms()
ledger = ForeshadowingLedger(db="Neo4j_Causal_Core")

# 启动靶向级深潜写作进化
engine = MasterEvolutionEngine(
    axioms=axioms,
    audience_type="female_oriented", # 或者 male_oriented 切分频段
    logic_layer=DisguiseLogicAuditor,  # 专门负责如女扮男装的物理/社会认知防穿帮
)

# 开启绝对知识领域的无监督进阶学习 (原著 Gold 层级)
engine.start_perpetual_learning(source="Gold_Library")
```
