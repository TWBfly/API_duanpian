import hashlib
import re
from pathlib import Path

from db import DatabaseManager


class HumanRevisionBulkImporter:
    FINAL_PRIORITY = [
        ("仿写-最终", 100),
        ("最终", 90),
        ("终稿", 85),
        ("仿写-优化", 80),
        ("优化", 70),
        ("人工", 65),
    ]
    DRAFT_PRIORITY = [
        ("仿写", 70),
        ("初稿", 60),
        ("draft", 50),
    ]
    CHAPTER_HEADER_RE = re.compile(
        r"^(楔子|序章|第[0-9零一二三四五六七八九十百两]+章(?:[ \t　:：\-—·•|｜【（(].*)?)$",
        re.MULTILINE,
    )
    DATE_SUFFIX_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")

    def __init__(self, db_manager=None, base_dir=None):
        self.db = db_manager or DatabaseManager()
        self.base_dir = Path(base_dir or Path(__file__).resolve().parent)

    def import_from_directory(self, root_dir=None):
        root = Path(root_dir or self.base_dir)
        groups = self.discover_revision_groups(root)
        summary = {
            "groups": len(groups),
            "books_created": 0,
            "chapter_finals_imported": 0,
            "learning_pairs_created": 0,
            "groups_skipped": 0,
            "unmatched_sections": 0,
        }

        for group_key, records in groups.items():
            result = self._import_group(group_key, records)
            for key, value in result.items():
                summary[key] = summary.get(key, 0) + value
        return summary

    def discover_revision_groups(self, root_dir):
        groups = {}
        for file_path in root_dir.rglob("*.md"):
            if self._should_skip_path(file_path):
                continue

            kind, priority = self._classify_file(file_path)
            if not kind:
                continue

            group_key = self._normalized_group_key(file_path)
            display_title = self._display_title(file_path)
            groups.setdefault(group_key, []).append(
                {
                    "path": file_path,
                    "kind": kind,
                    "priority": priority,
                    "display_title": display_title,
                }
            )
        return groups

    def _import_group(self, group_key, records):
        human_record = self._select_best_record(records, "human_final")
        if not human_record:
            return {"groups_skipped": 1}

        draft_record = self._select_best_record(records, "machine_draft")
        title = human_record["display_title"]
        book = self._resolve_book(title)
        created_book = 0
        if not book:
            book_id = f"IMPORT-{hashlib.md5(title.encode('utf-8')).hexdigest()[:12]}"
            self.db.create_or_update_book(
                book_id=book_id,
                title=title,
                genesis={"audience_type": self._infer_audience_type(title, human_record["path"].read_text(encoding="utf-8", errors="ignore"))},
                status="imported",
            )
            book = self.db.get_book(book_id)
            created_book = 1

        final_sections = self._parse_sections(human_record["path"])
        draft_section_map = {}
        if draft_record:
            draft_sections = self._parse_sections(draft_record["path"])
            draft_section_map = {section["chapter_index"]: section for section in draft_sections}

        imported_finals = 0
        learning_pairs = 0
        unmatched_sections = 0

        for section in final_sections:
            chapter_title = section["heading"] or f"第{section['chapter_index']}章"
            chapter = self.db.get_chapter(book["id"], section["chapter_index"])
            if not chapter:
                chapter_id = self.db.upsert_chapter_record(
                    book_id=book["id"],
                    chapter_index=section["chapter_index"],
                    title=chapter_title,
                    chapter_type="imported",
                    skeleton_data={},
                    history_context="批量导入人工终稿",
                    status="imported",
                )
            else:
                chapter_id = chapter["id"]

            source_draft_id = None
            matched_draft = draft_section_map.get(section["chapter_index"])
            if matched_draft:
                source_draft_id = self.db.add_chapter_draft(
                    book_id=book["id"],
                    chapter_id=chapter_id,
                    chapter_index=section["chapter_index"],
                    draft_stage="imported_source_draft",
                    content=matched_draft["content"],
                    seed_prompt="imported_from_markdown",
                    model_name="imported",
                    evaluation=None,
                    is_selected=self.db.get_latest_selected_draft(book["id"], section["chapter_index"]) is None,
                    candidate_label="imported",
                )
            elif self.db.get_latest_selected_draft(book["id"], section["chapter_index"]):
                source_draft_id = self.db.get_latest_selected_draft(book["id"], section["chapter_index"])["id"]
            else:
                unmatched_sections += 1

            before_pairs = len(self.db.get_pending_learning_pairs(limit=100000))
            self.db.register_human_revision(
                book_id=book["id"],
                chapter_index=section["chapter_index"],
                content=section["content"],
                summary=self._build_summary(section["content"]),
                notes=f"bulk_import:{human_record['path']}",
                source_draft_id=source_draft_id,
                metadata={"import_group": group_key},
                source_path=str(human_record["path"]),
            )
            after_pairs = len(self.db.get_pending_learning_pairs(limit=100000))
            imported_finals += 1
            if after_pairs > before_pairs:
                learning_pairs += 1

        return {
            "books_created": created_book,
            "chapter_finals_imported": imported_finals,
            "learning_pairs_created": learning_pairs,
            "unmatched_sections": unmatched_sections,
        }

    def _resolve_book(self, title):
        candidates = self.db.find_books_by_title_like(title, limit=5)
        normalized_title = self._normalize_text(title)
        for candidate in candidates:
            if self._normalize_text(candidate["title"]) == normalized_title:
                return self.db.get_book(candidate["id"])
        if candidates:
            return self.db.get_book(candidates[0]["id"])
        return None

    def _select_best_record(self, records, target_kind):
        filtered = [record for record in records if record["kind"] == target_kind]
        if not filtered:
            return None
        return sorted(filtered, key=lambda item: (-item["priority"], len(str(item["path"]))))[0]

    def _classify_file(self, file_path):
        stem = file_path.stem
        for marker, priority in self.FINAL_PRIORITY:
            if marker in stem:
                return "human_final", priority
        for marker, priority in self.DRAFT_PRIORITY:
            if marker in stem and "优化" not in stem and "最终" not in stem:
                return "machine_draft", priority
        return None, 0

    def _normalized_group_key(self, file_path):
        stem = self.DATE_SUFFIX_RE.sub("", file_path.stem)
        stem = re.sub(r"-(仿写-最终|最终|终稿|仿写-优化|优化|人工|仿写|初稿)$", "", stem)
        parent_title = file_path.parent.name if file_path.parent != self.base_dir else stem
        raw = parent_title if parent_title and parent_title != "prompt" else stem
        return self._normalize_text(raw)

    def _display_title(self, file_path):
        stem = self.DATE_SUFFIX_RE.sub("", file_path.stem)
        stem = re.sub(r"-(仿写-最终|最终|终稿|仿写-优化|优化|人工|仿写|初稿)$", "", stem)
        if file_path.parent.name not in {"prompt", file_path.stem} and "白月光" in file_path.parent.name:
            return file_path.parent.name
        return stem

    def _parse_sections(self, file_path):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        matches = list(self.CHAPTER_HEADER_RE.finditer(text))
        if not matches:
            return [{
                "chapter_index": self._chapter_index_from_heading(file_path.stem, 1),
                "heading": file_path.stem,
                "content": text.strip(),
            }]

        sections = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            heading = match.group(1).strip()
            content = text[start:end].strip()
            if not content:
                continue
            sections.append(
                {
                    "chapter_index": self._chapter_index_from_heading(heading, index + 1),
                    "heading": heading,
                    "content": content,
                }
            )
        return sections or [{
            "chapter_index": self._chapter_index_from_heading(file_path.stem, 1),
            "heading": file_path.stem,
            "content": text.strip(),
        }]

    def _chapter_index_from_heading(self, heading, fallback_index):
        if heading in {"楔子", "序章"}:
            return 0
        match = re.search(r"第([0-9零一二三四五六七八九十百两]+)章", heading)
        if not match:
            return fallback_index
        token = match.group(1)
        if token.isdigit():
            return int(token)
        return self._chinese_number_to_int(token) or fallback_index

    def _chinese_number_to_int(self, token):
        mapping = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        unit_mapping = {"十": 10, "百": 100}
        result = 0
        current = 0
        for char in token:
            if char in mapping:
                current = mapping[char]
            elif char in unit_mapping:
                unit = unit_mapping[char]
                if current == 0:
                    current = 1
                result += current * unit
                current = 0
        return result + current

    def _build_summary(self, content, limit=60):
        cleaned = re.sub(r"\s+", " ", content).strip()
        return cleaned[:limit]

    def _infer_audience_type(self, title, content):
        female_hits = sum(1 for term in ["千金", "白月光", "联姻", "回国", "夫人", "婚"] if term in title + content[:300])
        male_hits = sum(1 for term in ["宗门", "皇子", "朕", "剑", "刀", "帝"] if term in title + content[:300])
        if female_hits >= male_hits and female_hits > 0:
            return "female_oriented"
        if male_hits > female_hits:
            return "male_oriented"
        return None

    def _normalize_text(self, text):
        return re.sub(r"[\W_]+", "", text or "").lower()

    def _should_skip_path(self, file_path):
        parts = {part.lower() for part in file_path.parts}
        if "__pycache__" in parts or "learn" in parts or "prompt" in parts:
            return True
        if file_path.name in {"短篇API进化系统.md", "短篇API进化系统-优化.md"}:
            return True
        return False
