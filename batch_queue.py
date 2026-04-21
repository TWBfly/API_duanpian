import asyncio
import re
import shutil
import time
import uuid
from pathlib import Path

from chapter_director import ChapterDirector
from chroma_memory import ChromaMemory
from db import DatabaseManager
from neo4j_db import Neo4jManager
from novel_utils import normalize_total_chapters


class SQLiteTaskWorker:
    def __init__(
        self,
        db_manager=None,
        worker_id=None,
        concurrency=2,
        lease_seconds=900,
        retry_delay_seconds=180,
        poll_interval_seconds=5,
        group_min_interval_seconds=None,
    ):
        self.db = db_manager or DatabaseManager()
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.concurrency = max(1, concurrency)
        self.lease_seconds = max(60, lease_seconds)
        self.retry_delay_seconds = max(30, retry_delay_seconds)
        self.poll_interval_seconds = max(1, poll_interval_seconds)
        self.group_min_interval_seconds = group_min_interval_seconds or {"default": 0.0}
        self._last_group_start = {}

    def enqueue_titles(
        self,
        title_seeds,
        total_chapters=10,
        priority=100,
        candidate_count=1,
        max_attempts=3,
        rate_limit_group="default",
    ):
        queued = []
        total_chapters = normalize_total_chapters(total_chapters)
        for offset, title_seed in enumerate(title_seeds):
            book_id = f"BOOK-{uuid.uuid4().hex[:12]}"
            task_id = self.db.enqueue_generation_task(
                book_id=book_id,
                title_seed=title_seed,
                total_chapters=total_chapters,
                priority=priority + offset,
                candidate_count=candidate_count,
                max_attempts=max_attempts,
                rate_limit_group=rate_limit_group,
            )
            queued.append({"task_id": task_id, "book_id": book_id, "title_seed": title_seed})
        return queued

    async def run_once(self, limit=None):
        self.db.requeue_stale_generation_tasks(retry_delay_seconds=self.retry_delay_seconds)
        ready_tasks = self.db.fetch_generation_tasks(status="ready", limit=limit or self.concurrency * 4)
        if not ready_tasks:
            return []

        semaphore = asyncio.Semaphore(self.concurrency)
        await asyncio.gather(*(self._run_single_task(task, semaphore) for task in ready_tasks))
        return ready_tasks

    async def run_until_empty(self, batch_limit=None):
        processed = 0
        while True:
            batch = await self.run_once(limit=batch_limit)
            if not batch:
                break
            processed += len(batch)
        return processed

    async def run_forever(self):
        while True:
            batch = await self.run_once()
            if not batch:
                await asyncio.sleep(self.poll_interval_seconds)

    async def _run_single_task(self, task, semaphore):
        async with semaphore:
            await self._respect_rate_limit(task.get("rate_limit_group") or "default")
            if not self.db.claim_generation_task(task["id"], worker_id=self.worker_id, lease_seconds=self.lease_seconds):
                return

            workspace_dir = self._workspace_dir_for_task(task)
            self._cleanup_task_artifacts(task["book_id"], workspace_dir)
            snapshot = self.db.snapshot_book_state(task["book_id"])
            self.db.set_task_rollback_state(task["id"], snapshot)
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(task["id"]))

            try:
                await asyncio.to_thread(self._execute_director, task, workspace_dir)
                self.db.complete_generation_task(task["id"])
            except Exception as exc:
                self.db.rollback_book_to_snapshot(task["book_id"], snapshot)
                self._cleanup_task_artifacts(task["book_id"], workspace_dir)
                self.db.fail_generation_task(
                    task["id"],
                    str(exc),
                    retry_delay_seconds=self.retry_delay_seconds,
                    rollback_state=snapshot,
                )
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _heartbeat_loop(self, task_id):
        interval = max(15, self.lease_seconds // 3)
        while True:
            await asyncio.sleep(interval)
            self.db.heartbeat_generation_task(task_id, self.worker_id, lease_seconds=self.lease_seconds)

    async def _respect_rate_limit(self, rate_limit_group):
        min_interval = self.group_min_interval_seconds.get(
            rate_limit_group,
            self.group_min_interval_seconds.get("default", 0.0),
        )
        if min_interval <= 0:
            self._last_group_start[rate_limit_group] = time.time()
            return

        now = time.time()
        last_started = self._last_group_start.get(rate_limit_group, 0.0)
        wait_seconds = min_interval - (now - last_started)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        self._last_group_start[rate_limit_group] = time.time()

    def _workspace_dir_for_task(self, task):
        raw_title = task.get("title_seed") or "untitled"
        safe_title = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", raw_title).strip("_") or "untitled"
        return str(Path(__file__).resolve().parent / "batch_runs" / f"{task['book_id']}_{safe_title}")

    def _cleanup_task_artifacts(self, book_id, workspace_dir):
        Neo4jManager().purge_novel(book_id)
        ChromaMemory().remove_novel_plots(book_id)
        shutil.rmtree(workspace_dir, ignore_errors=True)

    def _execute_director(self, task, workspace_dir):
        task_db = DatabaseManager(self.db.db_path)
        total_chapters = normalize_total_chapters(task["total_chapters"])
        director = ChapterDirector(
            novel_id=task["book_id"],
            novel_name=task["title_seed"],
            total_chapters=total_chapters,
            db_manager=task_db,
            run_autonomous_learning=False,
            candidate_count=task.get("candidate_count", 1),
            workspace_dir=workspace_dir,
            isolated_task_mode=True,
        )
        director.run_pipeline()


class AsyncBatchGenerationRunner(SQLiteTaskWorker):
    pass
