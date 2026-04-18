import json
import os
from pathlib import Path
from db import DatabaseManager

class SFTExporter:
    """SFT/DPO 数据导出工具：将进化出的专家样本转化为模型微调格式"""
    def __init__(self):
        self.db = DatabaseManager()
        self.export_dir = Path(__file__).resolve().parent / "exports"
        self.export_dir.mkdir(exist_ok=True)

    def export_to_jsonl(self, filename="sft_dataset_v1.jsonl"):
        """将 expert_samples 导出为 OpenAI/DeepSeek 兼容的 SFT 格式"""
        self.db.cursor.execute("SELECT category, audience, original_text, improved_text FROM expert_samples WHERE is_active = 1")
        rows = self.db.cursor.fetchall()
        
        if not rows:
            print(">> [导出终止] 专家库中尚无有效样本。")
            return

        export_path = self.export_dir / filename
        count = 0
        with open(export_path, 'w', encoding='utf-8') as f:
            for row in rows:
                cat, audience, source, target = row
                
                # 构造标准微调指令格式
                # 可以根据需要调整 system 和 instruction
                entry = {
                    "instruction": f"请作为精通{cat}的小说大神，优化以下初稿片段。受众定位：{audience}。要求：去除AI感，断句有力，五感充沛。",
                    "input": source,
                    "output": target
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                count += 1
        
        print(f"🎉 [导出成功] 已将 {count} 条黄金训练数据写入：{export_path}")
        return export_path

if __name__ == "__main__":
    exporter = SFTExporter()
    exporter.export_to_jsonl()
