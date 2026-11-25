from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from .config import Project


@dataclass
class TestNode:
    label: str
    kind: str
    nodeid: str | None = None
    children: dict[str, "TestNode"] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "kind": self.kind,
            "nodeid": self.nodeid,
            "children": [child.as_dict() for child in self.children.values()],
        }


def parse_nodeids(output: str) -> list[str]:
    """Extract collected pytest node IDs from quiet collection output."""
    nodeids = []
    for line in output.splitlines():
        candidate = line.strip()
        if "::" in candidate and not candidate.startswith("="):
            nodeids.append(candidate)
    return list(dict.fromkeys(nodeids))


def build_tree(nodeids: list[str]) -> TestNode:
    root = TestNode("Tests", "root")
    for nodeid in nodeids:
        parts = nodeid.split("::")
        file_path = PurePosixPath(parts[0])
        current = root
        for folder in file_path.parts[:-1]:
            current = current.children.setdefault(folder, TestNode(folder, "directory"))
        filename = file_path.name
        current = current.children.setdefault(filename, TestNode(filename, "file"))
        for class_name in parts[1:-1]:
            current = current.children.setdefault(
                class_name, TestNode(class_name, "class")
            )
        test_name = parts[-1] if len(parts) > 1 else filename
        current.children.setdefault(
            nodeid, TestNode(test_name, "test", nodeid=nodeid)
        )
    return root


async def discover(project: Project) -> list[str]:
    process = await asyncio.create_subprocess_exec(
        str(project.python),
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "--color=no",
        cwd=project.root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=180)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError("Test discovery timed out after 180 seconds.") from None
    text = output.decode("utf-8", errors="replace")
    if process.returncode:
        detail = text[-4000:].strip() or f"pytest exited with code {process.returncode}"
        raise RuntimeError(detail)
    nodeids = parse_nodeids(text)
    if not nodeids:
        raise RuntimeError("Pytest collection completed but did not find any tests.")
    return nodeids
