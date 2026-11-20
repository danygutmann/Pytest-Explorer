from __future__ import annotations

import asyncio
import html
import json
import os
import re
import signal
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Project

RESULT_RE = re.compile(r"^(?P<nodeid>.+?)\s+(?P<result>PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\b")


@dataclass
class Run:
    id: str
    project_id: str
    project_name: str
    status: str
    started_at: str
    selectors: list[str]
    output: str = ""
    current_test: str = ""
    counts: dict[str, int] = field(default_factory=lambda: {
        "passed": 0, "failed": 0, "skipped": 0
    })
    completed: int = 0
    returncode: int | None = None
    report_path: str = ""
    log_path: str = ""
    duration: float = 0.0
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)

    def public(self) -> dict:
        data = asdict(self)
        data.pop("process", None)
        return data


class RunManager:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.runs_dir = data_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.runs: dict[str, Run] = {}
        self.active_by_project: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self.history_path = data_dir / "history.json"
        self.history = self._load_history()

    def _load_history(self) -> list[dict]:
        try:
            history = json.loads(self.history_path.read_text(encoding="utf-8"))
            return history if isinstance(history, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_history(self) -> None:
        temporary = self.history_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.history, indent=2), encoding="utf-8")
        temporary.replace(self.history_path)

    async def start(self, project: Project, selectors: list[str]) -> Run:
        lock = self._locks.setdefault(project.id, asyncio.Lock())
        async with lock:
            active_id = self.active_by_project.get(project.id)
            if active_id and self.runs[active_id].status == "running":
                raise RuntimeError("A test run is already active for this project.")
            if not selectors:
                raise ValueError("Select at least one test before starting a run.")

            run_id = uuid.uuid4().hex
            run_dir = self.runs_dir / run_id
            run_dir.mkdir()
            started_at = datetime.now(timezone.utc).isoformat()
            run = Run(
                id=run_id,
                project_id=project.id,
                project_name=project.name,
                status="running",
                started_at=started_at,
                selectors=selectors,
                report_path=str(run_dir / "report.html"),
                log_path=str(run_dir / "pytest.log"),
            )
            self.runs[run_id] = run
            self.active_by_project[project.id] = run_id
            self._tasks[run_id] = asyncio.create_task(self._execute(project, run))
            return run

    async def _execute(self, project: Project, run: Run) -> None:
        started = time.monotonic()
        try:
            run.process = await asyncio.create_subprocess_exec(
                str(project.python),
                "-m",
                "pytest",
                "-vv",
                "--color=no",
                "--tb=short",
                *run.selectors,
                cwd=project.root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            assert run.process.stdout is not None
            with Path(run.log_path).open("w", encoding="utf-8") as log:
                while line := await run.process.stdout.readline():
                    text = line.decode("utf-8", errors="replace")
                    run.output += text
                    log.write(text)
                    log.flush()
                    self._update_progress(run, text.rstrip())
                run.returncode = await run.process.wait()
            if run.status != "stopping":
                run.status = "passed" if run.returncode == 0 else "failed"
        except Exception as exc:
            run.status = "failed"
            message = f"\nPytest could not be started: {exc}\n"
            run.output += message
            Path(run.log_path).write_text(run.output, encoding="utf-8")
        finally:
            run.duration = time.monotonic() - started
            run.process = None
            self._write_report(run)
            self.history.insert(0, self._history_entry(run))
            self.history = self.history[:100]
            self._save_history()
            self.active_by_project.pop(project.id, None)

    @staticmethod
    def _update_progress(run: Run, line: str) -> None:
        match = RESULT_RE.match(line)
        if not match:
            if "::" in line and not line.startswith("="):
                run.current_test = line.strip()
            return
        result = match.group("result")
        run.current_test = match.group("nodeid")
        if result == "PASSED":
            run.counts["passed"] += 1
        elif result in {"FAILED", "ERROR", "XPASS"}:
            run.counts["failed"] += 1
        else:
            run.counts["skipped"] += 1
        run.completed += 1

    def _write_report(self, run: Run) -> None:
        rows = "".join(
            f"<tr><th>{html.escape(label.title())}</th><td>{count}</td></tr>"
            for label, count in run.counts.items()
        )
        report = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Pytest run {run.id}</title>
<style>body{{font:16px sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem}}
pre{{white-space:pre-wrap;background:#f4f4f4;padding:1rem}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:.5rem}}</style><body>
<h1>{html.escape(run.project_name)} — {html.escape(run.status.title())}</h1>
<p>Started: {html.escape(run.started_at)} · Duration: {run.duration:.1f}s</p>
<table>{rows}</table><h2>Pytest output</h2><pre>{html.escape(run.output)}</pre></body></html>"""
        Path(run.report_path).write_text(report, encoding="utf-8")

    @staticmethod
    def _history_entry(run: Run) -> dict:
        return {
            "id": run.id,
            "project_id": run.project_id,
            "project_name": run.project_name,
            "status": run.status,
            "started_at": run.started_at,
            "duration": round(run.duration, 2),
            "counts": run.counts,
            "report_path": run.report_path,
            "log_path": run.log_path,
        }

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    async def stop(self, project_id: str) -> bool:
        run_id = self.active_by_project.get(project_id)
        if not run_id:
            return False
        run = self.runs[run_id]
        process = run.process
        if process is None or process.returncode is not None:
            return False
        run.status = "stopping"
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        run.status = "stopped"
        return True
