import json
import os
from pathlib import Path

class SkillManager:
    def __init__(self, db_manager, skill_dir=None):
        self.db = db_manager
        if skill_dir is None:
            self.skill_dir = Path(__file__).resolve().parent / "skill_library"
        else:
            self.skill_dir = Path(skill_dir)
        self.skills = {}
        self._load_all_skills()

    def _load_all_skills(self):
        """加载本地 Skill 模板文件"""
        if not self.skill_dir.exists():
            return
        for file in self.skill_dir.glob("*.json"):
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    skill_data = json.load(f)
                    self.skills[skill_data['skill_name']] = skill_data
            except Exception as e:
                print(f"⚠️ [SkillManager] 加载技能文件 {file.name} 失败: {e}")

    def get_skill_bundle(self, skill_name, audience=None, limit=3):
        """
        组合 Skill 模板与数据库中的动态 Few-Shot 样本。
        返回: {system_prompt, negative_constraints, gold_samples}
        """
        skill_template = self.skills.get(skill_name)
        if not skill_template:
            return None

        # 从模板获取基础内容
        system_prompt = skill_template.get("system_prompt", "")
        neg_constraints = skill_template.get("negative_constraints", [])
        
        # 初始样本来自模板固定部分
        gold_samples = list(skill_template.get("gold_samples", []))
        
        # 从数据库动态加载进化出来的“神作”样本
        category = skill_template.get("category")
        dynamic_samples = self.db.get_expert_samples(category, audience=audience, limit=limit)
        
        if dynamic_samples:
            # 融合动态样本 (去重处理以防模板已有同样的)
            existing_originals = {s['original'] for s in gold_samples}
            for ds in dynamic_samples:
                if ds['original'] not in existing_originals:
                    gold_samples.append(ds)
        
        # 如果样本过多，只保留最高分的几个 (模板优先 + 高分动态)
        final_samples = gold_samples[:limit+1]

        return {
            "skill_name": skill_name,
            "system_prompt": system_prompt,
            "negative_constraints": neg_constraints,
            "gold_samples": final_samples
        }

    def format_few_shot_prompt(self, skill_bundle):
        """将 Skill Bundle 转换为 Prompt 片段"""
        if not skill_bundle:
            return ""
        
        fs_text = "\n\n【创作案例仿写(Few-Shot)】：\n"
        for i, sample in enumerate(skill_bundle['gold_samples']):
            fs_text += f"---\n[案例{i+1} 原始AI稿]: {sample['original']}\n"
            fs_text += f"[案例{i+1} 人类优化/高分结晶]: {sample['improved']}\n"
        
        if skill_bundle['negative_constraints']:
            fs_text += "\n【绝对负面约束】：\n- " + "\n- ".join(skill_bundle['negative_constraints'])
            
        return fs_text
