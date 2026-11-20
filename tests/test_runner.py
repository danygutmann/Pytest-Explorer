import asyncio
import tempfile
import unittest
from pathlib import Path

from pytest_explorer.config import Project
from pytest_explorer.runner import RunManager


class RunProgressTests(unittest.TestCase):
    def test_progress_counts_pytest_results(self):
        from pytest_explorer.runner import Run

        run = Run("id", "project", "Project", "running", "now", [])
        RunManager._update_progress(run, "tests/test_api.py::test_ok PASSED")
        RunManager._update_progress(run, "tests/test_api.py::test_bad FAILED")
        RunManager._update_progress(run, "tests/test_api.py::test_skip SKIPPED")

        self.assertEqual(run.counts, {"passed": 1, "failed": 1, "skipped": 1})
        self.assertEqual(run.completed, 3)


class RunManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_writes_full_log_and_html_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "project"
            root.mkdir()
            interpreter = base / "fake-python"
            interpreter.write_text(
                "#!/usr/bin/env python3\n"
                "print('tests/test_sample.py::test_pass PASSED', flush=True)\n",
                encoding="utf-8",
            )
            interpreter.chmod(0o755)
            project = Project("sample", "Sample", root, interpreter)
            manager = RunManager(base / "data")
            run = await manager.start(project, ["tests/test_sample.py::test_pass"])
            task = manager._tasks[run.id]
            await asyncio.wait_for(task, timeout=5)

            self.assertEqual(run.status, "passed")
            self.assertIn("test_pass PASSED", Path(run.log_path).read_text())
            self.assertIn("Sample", Path(run.report_path).read_text())
            self.assertEqual(manager.history[0]["id"], run.id)

    async def test_one_run_per_project_and_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "project"
            root.mkdir()
            interpreter = base / "fake-python"
            interpreter.write_text(
                "#!/usr/bin/env python3\n"
                "import time\n"
                "print('tests/test_sample.py::test_wait', flush=True)\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            interpreter.chmod(0o755)
            project = Project("sample", "Sample", root, interpreter)
            manager = RunManager(base / "data")
            run = await manager.start(project, ["tests/test_sample.py::test_wait"])
            await asyncio.sleep(0.1)

            with self.assertRaisesRegex(RuntimeError, "already active"):
                await manager.start(project, ["tests/test_sample.py::test_wait"])

            run.status = "stopping"
            with self.assertRaisesRegex(RuntimeError, "already active"):
                await manager.start(project, ["tests/test_sample.py::test_wait"])
            run.status = "running"
            self.assertTrue(await manager.stop(project.id))
            await asyncio.wait_for(manager._tasks[run.id], timeout=5)
            self.assertEqual(run.status, "stopped")

    async def test_old_run_cleanup_preserves_new_active_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "project"
            root.mkdir()
            interpreter = base / "fake-python"
            interpreter.write_text(
                "#!/usr/bin/env python3\n"
                "print('tests/test_sample.py::test_pass PASSED', flush=True)\n",
                encoding="utf-8",
            )
            interpreter.chmod(0o755)
            project = Project("sample", "Sample", root, interpreter)
            manager = RunManager(base / "data")
            run = await manager.start(project, ["tests/test_sample.py::test_pass"])
            original_write_report = manager._write_report

            def write_report_and_replace_mapping(completed_run):
                manager.active_by_project[project.id] = "newer-run"
                original_write_report(completed_run)

            manager._write_report = write_report_and_replace_mapping
            await asyncio.wait_for(manager._tasks[run.id], timeout=5)

            self.assertEqual(manager.active_by_project[project.id], "newer-run")


if __name__ == "__main__":
    unittest.main()
