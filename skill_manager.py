import json
import os
from pathlib import Path

from novel_utils import token_safe_prune

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
        返回: {system_prompt, negative_constraints, gold_samples, abstract_rules}
        """
        skill_template = self.skills.get(skill_name)
        if not skill_template:
            return None

        # 从模板获取基础内容
        system_prompt = skill_template.get("system_prompt", "")
        neg_constraints = skill_template.get("negative_constraints", [])
        gold_samples = list(skill_template.get("gold_samples", []))
        category = skill_template.get("category")
        final_samples = gold_samples[:limit+1]
        abstract_rules = self.db.get_skill_rules(category, audience=audience, limit=limit)

        return {
            "skill_name": skill_name,
            "system_prompt": system_prompt,
            "negative_constraints": neg_constraints,
            "gold_samples": final_samples,
            "abstract_rules": abstract_rules,
        }

    def format_few_shot_prompt(self, skill_bundle, max_samples=1):
        """将 Skill Bundle 转换为 Prompt 片段"""
        if not skill_bundle:
            return ""
        
        fs_text = "\n\n【创作案例仿写(Few-Shot)】：\n"
        for i, sample in enumerate(skill_bundle['gold_samples'][:max_samples]):
            improved = token_safe_prune(sample.get("improved", ""), max_chars=260, head_ratio=0.8)
            if not improved:
                continue
            fs_text += f"---\n[案例{i+1} 高分结晶片段]: {improved}\n"

        abstract_rules = [rule for rule in skill_bundle.get("abstract_rules", []) if rule]
        if abstract_rules:
            fs_text += "\n【已蒸馏技能规则】:\n"
            for idx, rule in enumerate(abstract_rules, start=1):
                fs_text += f"- 规则{idx}: {rule}\n"
        
        if skill_bundle['negative_constraints']:
            fs_text += "\n【绝对负面约束】：\n- " + "\n- ".join(skill_bundle['negative_constraints'])
            
        return fs_text
