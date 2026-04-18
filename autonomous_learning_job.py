import os
import glob
import time
from pathlib import Path
from db import DatabaseManager
from llm_client import generate_text_safe

class AutonomousLearningEngine:
    """自主读库学习机：自动学习原著断句与风格规律"""
    def __init__(self, target_dir=None, sleep_between_files=0.0):
        self.db = DatabaseManager()
        self.target_dir = target_dir or str(Path(__file__).resolve().parent / "learn")
        self.sleep_between_files = sleep_between_files

    def run_learning_cycle(self):
        print(f"\n🧠 [天道学习机启动] 正在扫描待学习的人类智慧结晶: {self.target_dir}")
        # 清洗历史垃圾数据
        self.db.cleanup_bad_rules()

        if not os.path.exists(self.target_dir):
            os.makedirs(self.target_dir, exist_ok=True)
            print(">> [学习区为空] 正在等待优质语料喂养。")
            return
            
        md_files = glob.glob(os.path.join(self.target_dir, "**/*.md"), recursive=True)
        if not md_files:
             print(">> [学习区为空] 暂无 Markdown 更新。")
             return

        print(f">> [目录分析] 发现 {len(md_files)} 个潜在的学习目标文件。")
        new_learn_count = 0
        for i, file_path in enumerate(md_files):
            if self.db.is_file_learned(file_path):
                continue
                
            print(f"\n进度 [{i+1}/{len(md_files)}] >> [开始顿悟] 正在深度阅读：{os.path.basename(file_path)}")
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # 若文件太大，截断（本地模型建议 1000 字以内以保证速度）
                if len(content) > 1000:
                    content = content[:1000]
                
                if len(content.strip()) < 100:
                     print(f"   ⚠️ 文件内容过短，跳过。")
                     self.db.mark_file_learned(file_path)
                     continue
                     
                # ⏳ 启动分类与特征提取机制 (Cloud Only)
                audience = self._classify_audience(content)
                self._extract_and_persist_rules(content, file_path, audience)
                
                # 记录该文件已学习
                self.db.mark_file_learned(file_path)
                new_learn_count += 1
                
                if self.sleep_between_files > 0:
                    time.sleep(self.sleep_between_files)
            except Exception as e:
                print(f"⚠️ [学习失败] 无法解析 {file_path}: {e}")

        if new_learn_count > 0:
            print(f"\n🎉 [全周期完成] 本次自发顿悟了 {new_learn_count} 卷人类典籍，已刻入全球法则网！")
        else:
            print(f"\n✔️ [无新进展] 所有典籍均已倒背如流。")

    def run_skill_evolution_flywheel(self):
        """核心飞轮：将生产环境的'神修改'对提取为 Skill Few-Shot 样本"""
        print("\n⚙️ [技能进化飞轮启动] 正在提取生产环节中的黄金样本...")
        pairs = self.db.get_pending_learning_pairs(limit=20, purpose="skill")
        if not pairs:
            print(">> [飞轮静默] 暂无待处理的学习配对数据。")
            return

        evolved_count = 0
        for p in pairs:
            try:
                # 1. 甄别该配对属于哪个 Skill 类别
                # 如果是 human_revision 且在第1章，通常是 Hook
                category = "genre_general"
                if p['chapter_index'] == 0 or p['chapter_index'] == 1:
                    category = "hook"
                else:
                    category = self._classify_skill_category(p['final_text'])
                
                # 2. 判别受众
                audience = self._classify_audience(p['final_text'])
                
                # 3. 计算评分 (简化处理，既然入了 pair 库且是 final，默认为高分结晶)
                score = 1.8 if p['pair_source'] == "human_revision" else 1.2
                
                # 4. 入库专家案例
                self.db.add_expert_sample(
                    category=category,
                    audience=audience,
                    original_text=p['draft_text'],
                    improved_text=p['final_text'],
                    score=score,
                    source=p['pair_source']
                )
                
                # 5. 标记处理完成
                self.db.mark_learning_pair_processed(
                    p['id'],
                    {"action": "evolved_to_skill", "category": category},
                    purpose="skill",
                )
                print(f"   => ✨ [进化结晶] 已将第 {p['chapter_index']} 章配对入库为 '{category}' 技能案例。")
                evolved_count += 1
            except Exception as e:
                print(f"   ⚠️ [进化中断] 处理配对 ID {p['id']} 失败: {e}")

        print(f"✔️ [飞轮转动完毕] 本次成功沉淀了 {evolved_count} 个专家级创作技能。")

    def _classify_skill_category(self, text):
        prompt = f"分析以下文本，判定该片段更偏向于哪个创作Skill分类：'genre_female'(重情感拉扯/修罗场), 'genre_male'(重升级/动作/逻辑). 只回复分类名。\n文本：{text[:300]}"
        res = generate_text_safe(prompt, "You are a skill classifier.")
        if not res: return "genre_general"
        if "female" in res.lower(): return "genre_female"
        if "male" in res.lower(): return "genre_male"
        return "genre_general"

    def _classify_audience(self, text):
        """判别语料受众类别"""
        prompt = f"分析以下文本片段，判定其受众群体是‘男频(male_oriented)’还是‘女频(female_oriented)’亦或是‘通用(general)’。只回复核心关键词，不要解释。\n文本：{text[:500]}"
        result = generate_text_safe(prompt, "You are a genre classifier.")
        if not result:
            return "general"
        if "male" in result.lower(): return "male_oriented"
        if "female" in result.lower(): return "female_oriented"
        return "general"

    def _extract_and_persist_rules(self, text, source_name, audience):
        prompts = [
            {
                "cat": "autonomous_plot_logic",
                "desc": "核心剧情与伏笔设计技巧",
                "query": "请从以上文本中提取出【一条】关于‘好的剧情转折、深刻的人物设计或精妙的伏笔设计’的硬核规律。要求：实操性强，严厉指令体，不超过50字。"
            },
            {
                "cat": "autonomous_learned_style",
                "desc": "人类作家的写作风格与断句节奏",
                "query": "请从以上文本中提取出【一条】关于‘人类作家的写作风格、断句节奏或排版张力’的精髓法则。要求：去除AI感，严厉指令体，不超过50字。"
            },
            {
                "cat": "autonomous_style_dna",
                "desc": "文风DNA：动作对话比与断句节奏",
                "query": "请从以上文本中提取出【一条】关于‘对话与动作的比例平衡、或是特殊的段落转场节奏’的精髓法则。要求：去除AI腔，严厉指令体，不超过50字。"
            }
        ]

        # 映射分箱类别
        tag_prefix = "extracted_"
        if audience == "male_oriented": tag_prefix = "demographic_quarantine_male_"
        elif audience == "female_oriented": tag_prefix = "demographic_quarantine_female_"

        for p in prompts:
            full_prompt = f"""你是一名文学解构大师。文本内容截取：\n{text}\n任务：{p['query']}"""
            
            # 使用云端大脑
            rule = generate_text_safe(full_prompt, "You are a master literary extractor.")
            if rule and len(rule.strip()) > 5:
                # 最终检查是否有异常词
                bad_keywords = ["Error generation", "Request timed out", "connection error"]
                if any(kw in rule for kw in bad_keywords):
                    print(f"   ⚠️ [{p['desc']}] 提取结果异常，已自动拦截丢弃。")
                    continue
                
                final_cat = f"{tag_prefix}{p['cat']}"
                self.db.add_dynamic_rule(final_cat, rule.strip(), initial_weight=1.0)
                print(f"   => ✨ [进化收获({audience})] {p['desc']} => {rule.strip()}")
            else:
                print(f"   ⚠️ [{p['desc']}] 提取彻底失败，跳过。")

    def run_rule_distillation_cycle(self):
        """蒸馏过载的短规则，防止爆炸上下文"""
        print("\n🔥 [规则蒸馏引擎启动] 检查是否需要抽象法则...")
        # 如果一个分类下有多于8个活跃规则，则触发合并
        categories_to_distill = self.db.get_rule_categories_needing_distillation(threshold=8)
        if not categories_to_distill:
            print(">> [系统健康] 当前无过载规则类别。")
            return

        for category in categories_to_distill:
            rules = self.db.get_rules_by_category(category)
            if not rules:
                continue

            rule_ids = [r[0] for r in rules]
            rule_texts = [r[1] for r in rules]
            print(f">> [蒸馏提取] 类别 {category} 积累了 {len(rules)} 条散规则，正在进行高维融合...")
            
            prompt = f"""你是一个至高无上的系统架构师。
以下是我们积攒的关于“{category}”的多条创作约束碎片：
{'- ' + chr(10).join('- ' + text for text in rule_texts)}

请分析这些碎片的共同内核，将它们**极致蒸馏融合**为【1至3条】高度精炼、最具概括性且覆盖所有核心痛点的【无上天道法则】。
要求：
1. 完全指令体，绝对不许有废话。
2. 保持对细节的指导意义，不能变成空泛的口号。
3. 总字数不能超过 300 字。
"""
            distilled = generate_text_safe(prompt, "You are the Ultimate Rule Distiller.")
            if distilled and len(distilled.strip()) > 10:
                self.db.replace_distilled_rules(category, rule_ids, distilled.strip())
                print(f"   => ✨ [大道至简] 成功蒸馏 {len(rules)} 条法则为至高元规则！")
            else:
                print(f"   ⚠️ [蒸馏失败] 无法提炼 {category}，保留原规则。")


if __name__ == "__main__":
    engine = AutonomousLearningEngine()
    engine.run_learning_cycle()
    engine.run_rule_distillation_cycle()
    engine.run_skill_evolution_flywheel()
