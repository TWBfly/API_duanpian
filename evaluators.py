import re


class QuantitativeEvaluator:
    AI_FLAVOR_TERMS = [
        "宛如",
        "仿佛",
        "似乎",
        "这一刻",
        "不由",
        "忽然意识到",
        "他知道",
        "她知道",
    ]
    HOOK_TERMS = [
        "死",
        "血",
        "杀",
        "断",
        "火",
        "坠",
        "疯",
        "婚",
        "背叛",
        "悬崖",
        "刺",
        "枪",
    ]
    FEMALE_TERMS = ["目光", "掌心", "呼吸", "婚约", "宴会", "冷笑", "眼尾", "心口", "唇", "压低声音"]
    MALE_TERMS = ["刀", "剑", "拳", "宗门", "杀", "阵", "血", "战", "灵力", "骨", "霸", "敌"]

    def evaluate(
        self,
        text,
        audience_type,
        chapter_type="normal",
        audit_results=None,
        skeleton_data=None,
        due_clues=None,
        resolved_ids=None,
        absolute_state=None,
    ):
        audit_results = audit_results or {}
        resolved_ids = resolved_ids or []
        skeleton_data = skeleton_data or {}
        due_clues = due_clues or []

        metrics = {
            "hook_strength": self._score_hook(text, chapter_type, audit_results.get("hook")),
            "audience_alignment": self._score_audience(text, audience_type, audit_results.get("demographic")),
            "ai_scent": self._score_ai_scent(text, audit_results.get("scent")),
            "stylistic_integrity": self._score_stylistic(text, audit_results.get("stylistic")),
            "truth_consistency": self._score_truth(absolute_state, audit_results.get("truth")),
            "style_humanity": self._score_style(
                text,
                audit_results.get("style"),
                audit_results.get("scent"),
                audit_results.get("stylistic"),
            ),
            "foreshadow_closure": self._score_foreshadow(text, skeleton_data, due_clues, resolved_ids),
            "coherence": self._score_coherence(text, skeleton_data),
        }

        weights = {
            "hook_strength": 0.12,
            "audience_alignment": 0.13,
            "ai_scent": 0.13,
            "stylistic_integrity": 0.14,
            "truth_consistency": 0.14,
            "style_humanity": 0.14,
            "foreshadow_closure": 0.10,
            "coherence": 0.10,
        }
        overall = 0.0
        for metric_name, score in metrics.items():
            overall += score * weights[metric_name]
        metrics["overall"] = round(overall, 2)

        risk_flags = [name for name, score in metrics.items() if name != "overall" and score < 70]
        highlights = [name for name, score in metrics.items() if name != "overall" and score >= 88]

        return {
            "metrics": metrics,
            "risk_flags": risk_flags,
            "highlights": highlights,
        }

    def _score_pass_fail(self, audit_text, base_pass=88, base_fail=58):
        if not audit_text:
            return 70.0
        return float(base_pass if "[通过]" in audit_text else base_fail)

    def _score_hook(self, text, chapter_type, audit_text):
        if chapter_type != "prologue":
            return 85.0
        opening = text[:100]
        score = 55.0
        score += 25.0 if audit_text and "[通过]" in audit_text else 0.0
        hit_terms = sum(1 for term in self.HOOK_TERMS if term in opening)
        score += min(15.0, hit_terms * 3.0)
        if any(mark in opening for mark in ("？", "!", "！", "——")):
            score += 5.0
        return round(min(100.0, score), 2)

    def _score_audience(self, text, audience_type, audit_text):
        terms = self.FEMALE_TERMS if audience_type == "female_oriented" else self.MALE_TERMS
        opposing = self.MALE_TERMS if audience_type == "female_oriented" else self.FEMALE_TERMS
        matched = sum(1 for term in terms if term in text)
        opposing_hits = sum(1 for term in opposing if term in text)
        score = 62.0
        score += 20.0 if audit_text and "[通过]" in audit_text else 0.0
        score += min(18.0, matched * 2.5)
        score -= min(10.0, opposing_hits * 1.5)
        return round(max(0.0, min(100.0, score)), 2)

    def _score_ai_scent(self, text, audit_text):
        ai_hits = sum(text.count(term) for term in self.AI_FLAVOR_TERMS)
        score = 60.0
        score += 22.0 if audit_text and "[通过]" in audit_text else 0.0
        score -= min(20.0, ai_hits * 4.0)
        if "\n" in text:
            score += 4.0
        return round(max(0.0, min(100.0, score)), 2)

    def _score_stylistic(self, text, audit_text):
        paragraphs = [p for p in text.splitlines() if p.strip()]
        paragraph_count = len(paragraphs)
        sentence_parts = re.split(r"[。！？!?；;]", text)
        sentence_lengths = [len(item.strip()) for item in sentence_parts if item.strip()]
        avg_sentence = sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0
        longest_paragraph = max((len(p) for p in paragraphs), default=0)
        length_variance = (max(sentence_lengths) - min(sentence_lengths)) if len(sentence_lengths) >= 2 else 0

        score = 60.0
        score += 18.0 if audit_text and "[通过]" in audit_text else 0.0
        if paragraph_count >= 4:
            score += 10.0
        elif paragraph_count >= 2:
            score += 5.0
        if 10 <= avg_sentence <= 32:
            score += 8.0
        elif avg_sentence <= 40:
            score += 3.0
        if longest_paragraph <= 160:
            score += 4.0
        if length_variance >= 12:
            score += 4.0
        return round(min(100.0, score), 2)

    def _score_style(self, text, audit_text, scent_audit_text=None, stylistic_audit_text=None):
        ai_hits = sum(text.count(term) for term in self.AI_FLAVOR_TERMS)
        score = 58.0
        score += 16.0 if audit_text and "[通过]" in audit_text else 0.0
        score += 8.0 if scent_audit_text and "[通过]" in scent_audit_text else 0.0
        score += 6.0 if stylistic_audit_text and "[通过]" in stylistic_audit_text else 0.0
        score -= min(18.0, ai_hits * 4.0)
        if "\n" in text:
            score += 4.0
        return round(max(0.0, min(100.0, score)), 2)

    def _score_truth(self, absolute_state, audit_text):
        if not absolute_state:
            return 84.0
        score = 58.0
        score += 24.0 if audit_text and "[通过]" in audit_text else 0.0
        if isinstance(absolute_state, dict) and absolute_state:
            score += 5.0
        return round(min(100.0, score), 2)

    def _score_foreshadow(self, text, skeleton_data, due_clues, resolved_ids):
        score = 72.0
        planned_clue = (skeleton_data or {}).get("foreshadowing_to_plant", "")
        if planned_clue and planned_clue != "无":
            overlap = sum(1 for token in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", planned_clue) if token in text)
            score += min(10.0, overlap * 2.0)
        if due_clues:
            score = 60.0
            score += min(25.0, len(resolved_ids) * 8.0)
        return round(min(100.0, score), 2)

    def _score_coherence(self, text, skeleton_data):
        plot_hint = (skeleton_data or {}).get("plot_beat", "")
        score = 70.0
        if plot_hint:
            tokens = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", plot_hint)
            overlap = sum(1 for token in tokens[:8] if token in text)
            score += min(18.0, overlap * 3.0)
        if len(text) >= 300:
            score += 6.0
        return round(min(100.0, score), 2)
