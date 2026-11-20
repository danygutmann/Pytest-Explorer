import json
import tempfile
import unittest
from pathlib import Path

from pytest_explorer.config import ConfigurationError, load_projects
from pytest_explorer.discovery import build_tree, parse_nodeids


class ProjectConfigTests(unittest.TestCase):
    def test_project_symlink_resolves_to_existing_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            actual = base / "actual"
            actual.mkdir()
            interpreter = base / "python"
            interpreter.touch()
            link = base / "ngcp"
            link.symlink_to(actual, target_is_directory=True)
            config = base / "projects.json"
            config.write_text(json.dumps({"projects": [{
                "id": "ngcp",
                "name": "NGCP",
                "path": str(link),
                "python": str(interpreter),
            }]}), encoding="utf-8")

            project = load_projects(config)[0]

            self.assertEqual(project.root, actual.resolve())
            self.assertEqual(project.python, interpreter.resolve())

    def test_invalid_project_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "projects.json"
            config.write_text(json.dumps({"projects": [{
                "id": "missing",
                "name": "Missing",
                "path": str(config.parent / "not-a-project"),
                "python": str(config.parent / "python"),
            }]}), encoding="utf-8")

            with self.assertRaises(ConfigurationError):
                load_projects(config)


class DiscoveryTreeTests(unittest.TestCase):
    def test_parse_node_ids_ignores_collection_summary_and_deduplicates(self):
        output = """tests/test_a.py::TestGroup::test_one
tests/test_a.py::test_two
tests/test_a.py::TestGroup::test_one
2 tests collected in 0.01s"""

        self.assertEqual(parse_nodeids(output), [
            "tests/test_a.py::TestGroup::test_one",
            "tests/test_a.py::test_two",
        ])

    def test_build_tree_groups_directories_files_classes_and_tests(self):
        tree = build_tree([
            "tests/unit/test_api.py::TestApi::test_get",
            "tests/unit/test_api.py::test_post",
        ])

        tests = tree.children["tests"].children["unit"].children["test_api.py"]
        self.assertIn("TestApi", tests.children)
        self.assertIn("tests/unit/test_api.py::test_post", tests.children)
        self.assertEqual(
            tests.children["TestApi"].children[
                "tests/unit/test_api.py::TestApi::test_get"
            ].label,
            "test_get",
        )


if __name__ == "__main__":
    unittest.main()
