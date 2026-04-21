import hashlib
import re
from collections import Counter

from novel_utils import extract_skeleton_segments, tokenize_cn_text

GENERIC_TOKENS = {
    "楔子", "序章", "结局", "第一章", "第二章", "第三章", "第四章", "第五章",
    "第六章", "第七章", "第八章", "第九章", "第十章", "主角", "剧情", "故事",
    "场景", "人物", "本章", "章节",
}


def _normalize_text(text):
    normalized = re.sub(r"\s+", "", text or "")
    normalized = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", normalized)
    return normalized.lower()


def _split_paragraphs(text, min_len=24, max_len=220):
    parts = []
    for chunk in re.split(r"\n{2,}|[。！？!?]", text or ""):
        cleaned = re.sub(r"\s+", " ", chunk).strip()
        if len(cleaned) < min_len:
            continue
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len]
        parts.append(cleaned)
    return parts


def _extract_headings(text):
    headings = []
    pattern = re.compile(r"^(?:#+\s*)?(楔子|序章|结局|第[0-9零一二三四五六七八九十百两]+章.*)$", re.MULTILINE)
    for match in pattern.finditer(text or ""):
        heading = match.group(1).strip()
        if heading not in headings:
            headings.append(heading)
    return headings


def _build_ngram_hashes(text, size, limit):
    normalized = _normalize_text(text)
    if len(normalized) < size:
        return []
    counter = Counter(normalized[idx:idx + size] for idx in range(0, len(normalized) - size + 1))
    most_common = [item for item, _ in counter.most_common(limit)]
    return [hashlib.md5(item.encode("utf-8")).hexdigest() for item in most_common]


def _compress_event_signature(item):
    tokens = [token for token in item.get("tokens", []) if token not in GENERIC_TOKENS]
    if tokens:
        return "/".join(tokens[:4])
    cleaned = re.sub(r"\s+", "", item.get("text", ""))
    return cleaned[:20]


class ReferenceFingerprintLibrary:
    def __init__(self, db_manager, vector_db=None):
        self.db = db_manager
        if vector_db is None:
            from chroma_memory import ChromaMemory

            vector_db = ChromaMemory()
        self.vector_db = vector_db

    def build_bundle(self, file_paths, essence_report=None):
        texts = []
        for path in file_paths or []:
            with open(path, "r", encoding="utf-8") as handle:
                texts.append(handle.read())

        combined_text = "\n".join(texts)
        headings = []
        for text in texts:
            headings.extend(_extract_headings(text))

        paragraphs = _split_paragraphs(combined_text, min_len=28, max_len=180)
        event_signatures = []
        seen_text = set()
        for item in headings + paragraphs:
            cleaned = item.strip()
            if len(cleaned) < 8 or cleaned in seen_text:
                continue
            seen_text.add(cleaned)
            event_signatures.append(
                {
                    "text": cleaned,
                    "tokens": tokenize_cn_text(cleaned, max_tokens=12),
                }
            )
            if len(event_signatures) >= 80:
                break

        skeleton_signatures = []
        for idx, item in enumerate(event_signatures[:40], start=1):
            skeleton_signatures.append(
                {
                    "chapter_like_index": idx,
                    "text": item["text"],
                    "tokens": item["tokens"],
                }
            )

        entity_blacklist = list(essence_report.get("entity_blacklist", []) if isinstance(essence_report, dict) else [])
        for heading in headings:
            for token in tokenize_cn_text(heading, max_tokens=8):
                if token in GENERIC_TOKENS:
                    continue
                if len(token) <= 6 and token not in entity_blacklist:
                    entity_blacklist.append(token)
        entity_blacklist = sorted({
            item.strip() for item in entity_blacklist
            if isinstance(item, str) and len(item.strip()) >= 2 and item.strip() not in GENERIC_TOKENS
        })

        chunks = []
        normalized_paragraphs = _split_paragraphs(combined_text, min_len=40, max_len=240)
        for paragraph in normalized_paragraphs[:120]:
            chunks.append(paragraph)

        outline_text = "\n".join([item["text"] for item in event_signatures[:60]])
        bundle = {
            "source_paths": list(file_paths or []),
            "entity_blacklist": entity_blacklist[:300],
            "event_signatures": event_signatures[:80],
            "skeleton_signatures": skeleton_signatures[:40],
            "outline_ngram_size": 8,
            "outline_ngram_hashes": _build_ngram_hashes(outline_text, size=8, limit=4000),
            "body_ngram_size": 12,
            "body_ngram_hashes": _build_ngram_hashes(combined_text, size=12, limit=8000),
            "reference_chunks": chunks[:120],
        }
        return bundle

    def save_bundle(self, book_id, file_paths, bundle):
        self.db.save_reference_fingerprint_bundle(book_id, file_paths, bundle)
        if not self.vector_db:
            return

        self.vector_db.remove_reference_chunks(book_id)
        for idx, chunk in enumerate((bundle or {}).get("reference_chunks", []), start=1):
            self.vector_db.add_reference_chunk(
                chunk,
                metadata={
                    "book_id": book_id,
                    "source": "reference_chunk",
                    "chunk_index": idx,
                },
            )

    def load_bundle(self, book_id):
        return self.db.get_reference_fingerprint_bundle(book_id)


class HardReferenceGuard:
    OUTLINE_EVENT_THRESHOLD = 0.62
    BODY_EVENT_THRESHOLD = 0.72
    OUTLINE_EMBED_THRESHOLD = 0.86
    BODY_EMBED_THRESHOLD = 0.90
    OUTLINE_NGRAM_RATIO = 0.20
    BODY_NGRAM_RATIO = 0.12

    def __init__(self, book_id, bundle, vector_db=None):
        self.book_id = book_id
        self.bundle = bundle or {}
        self.vector_db = vector_db

    def has_reference(self):
        return bool(self.bundle)

    def planner_constraints(self, failure_report=None):
        if not self.has_reference():
            return ""

        entity_text = "、".join(self.bundle.get("entity_blacklist", [])[:60]) or "无"
        compressed_events = [
            _compress_event_signature(item)
            for item in self.bundle.get("event_signatures", [])[:6]
        ]
        event_text = "；".join(item for item in compressed_events if item) or "无"
        lines = [
            "【原著硬性隔离规则】",
            f"- 严禁出现以下原著实体或其近似变体：{entity_text}",
            f"- 严禁复用以下原著事件抽象骨架：{event_text}",
            "- 可以继承情绪公式，但必须重做事件触发器、对抗场景、关键道具、登场顺序和解决路径。",
        ]
        if failure_report and failure_report.get("blockers"):
            blocker_text = "；".join(failure_report["blockers"][:4])
            lines.append(f"- 上一版因以下原因被法务拦截，必须彻底避开：{blocker_text}")
        return "\n".join(lines)

    def audit_outline_payload(self, skeleton):
        outline_text = self._outline_to_text(skeleton)
        return self._audit_text(outline_text, mode="outline")

    def audit_body_text(self, text):
        return self._audit_text(text, mode="body")

    def format_report(self, result):
        if result.get("passed"):
            return "[通过] 原著硬查重闸门通过。"
        return "[拦截] " + "；".join(result.get("blockers", [])[:5])

    def _outline_to_text(self, skeleton):
        pieces = []
        for chapter in (skeleton or {}).get("novel_arc", []):
            pieces.extend(extract_skeleton_segments(chapter))
        global_resolution = (skeleton or {}).get("global_resolution")
        if isinstance(global_resolution, str) and global_resolution.strip():
            pieces.append(global_resolution.strip())
        return "\n".join(pieces)

    def _audit_text(self, text, mode):
        blockers = []
        evidence = {}

        entity_hits = self._find_entity_hits(text)
        if entity_hits:
            blockers.append(f"直接命中原著实体禁语：{'、'.join(entity_hits[:8])}")
            evidence["entity_hits"] = entity_hits[:8]

        event_hits = self._find_event_overlaps(text, mode=mode)
        if event_hits:
            blockers.append(f"与原著事件外壳高度重合：{'；'.join(item['candidate'] for item in event_hits[:2])}")
            evidence["event_hits"] = event_hits[:3]

        ngram_hit = self._find_ngram_overlap(text, mode=mode)
        if ngram_hit:
            blockers.append(
                f"{mode} 文本与原著共享连续片段过多，n-gram 重合率 {ngram_hit['ratio']:.2f}"
            )
            evidence["ngram"] = ngram_hit

        embed_hit = self._find_embedding_overlap(text, mode=mode)
        if embed_hit:
            blockers.append(
                f"{mode} 文本与原著向量相似度过高 ({embed_hit['similarity']:.2f})"
            )
            evidence["embedding"] = embed_hit

        return {
            "passed": not blockers,
            "blockers": blockers,
            "evidence": evidence,
        }

    def _find_entity_hits(self, text):
        haystack = text or ""
        hits = []
        for entity in self.bundle.get("entity_blacklist", []):
            if entity and entity in haystack:
                hits.append(entity)
        return sorted(set(hits))

    def _find_event_overlaps(self, text, mode):
        candidates = _split_paragraphs(text, min_len=20 if mode == "outline" else 35, max_len=180)
        if mode == "outline" and not candidates:
            candidates = [line.strip() for line in (text or "").splitlines() if line.strip()]
        threshold = self.OUTLINE_EVENT_THRESHOLD if mode == "outline" else self.BODY_EVENT_THRESHOLD
        reference_items = self.bundle.get("skeleton_signatures", []) if mode == "outline" else self.bundle.get("event_signatures", [])
        hits = []
        for candidate in candidates[:40]:
            candidate_tokens = {token for token in tokenize_cn_text(candidate, max_tokens=14) if token not in GENERIC_TOKENS}
            if len(candidate_tokens) < 3:
                continue
            for ref in reference_items:
                ref_tokens = {token for token in ref.get("tokens", []) if token not in GENERIC_TOKENS}
                if len(ref_tokens) < 3:
                    continue
                shared = candidate_tokens & ref_tokens
                ratio = len(shared) / max(1, min(len(candidate_tokens), len(ref_tokens)))
                if len(shared) >= 4 and ratio >= threshold:
                    hits.append(
                        {
                            "candidate": candidate[:80],
                            "reference": ref.get("text", "")[:80],
                            "shared_tokens": sorted(shared)[:8],
                            "ratio": round(ratio, 3),
                        }
                    )
                    break
        return hits

    def _find_ngram_overlap(self, text, mode):
        hashes = self.bundle.get("outline_ngram_hashes", []) if mode == "outline" else self.bundle.get("body_ngram_hashes", [])
        if not hashes:
            return None

        size = self.bundle.get("outline_ngram_size", 8) if mode == "outline" else self.bundle.get("body_ngram_size", 12)
        normalized = _normalize_text(text)
        if len(normalized) < size:
            return None

        candidate_ngrams = [normalized[idx:idx + size] for idx in range(0, len(normalized) - size + 1)]
        candidate_hashes = {hashlib.md5(item.encode("utf-8")).hexdigest() for item in candidate_ngrams}
        overlap = candidate_hashes & set(hashes)
        ratio = len(overlap) / max(1, len(candidate_hashes))
        threshold = self.OUTLINE_NGRAM_RATIO if mode == "outline" else self.BODY_NGRAM_RATIO
        min_hits = 6 if mode == "outline" else 10
        if len(overlap) >= min_hits and ratio >= threshold:
            return {"ratio": ratio, "hits": len(overlap), "ngram_size": size}
        return None

    def _find_embedding_overlap(self, text, mode):
        if not self.vector_db:
            return None

        candidates = _split_paragraphs(text, min_len=22 if mode == "outline" else 40, max_len=220)
        if not candidates:
            candidates = [text[:220]]

        threshold = self.OUTLINE_EMBED_THRESHOLD if mode == "outline" else self.BODY_EMBED_THRESHOLD
        best = None
        for candidate in candidates[:8]:
            doc, similarity, metadata = self.vector_db.search_similar_reference(
                candidate,
                threshold=threshold,
                where_filter={"book_id": self.book_id},
            )
            if not doc:
                continue
            payload = {
                "similarity": similarity,
                "candidate": candidate[:120],
                "reference": doc[:120],
                "metadata": metadata or {},
            }
            if best is None or payload["similarity"] > best["similarity"]:
                best = payload
        return best
