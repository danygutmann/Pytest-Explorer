from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when the configured test projects cannot be loaded safely."""


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    root: Path
    python: Path


def load_projects(config_path: Path) -> list[Project]:
    try:
        raw_projects = json.loads(config_path.read_text(encoding="utf-8"))["projects"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Unable to read project configuration: {exc}") from exc

    if not isinstance(raw_projects, list) or not raw_projects:
        raise ConfigurationError("Project configuration must contain at least one project.")

    projects: list[Project] = []
    seen_ids: set[str] = set()
    for raw in raw_projects:
        try:
            project_id = raw["id"]
            name = raw["name"]
            root = Path(raw["path"]).expanduser().resolve(strict=True)
            python = Path(raw["python"]).expanduser().resolve(strict=True)
        except (KeyError, TypeError, OSError, RuntimeError) as exc:
            raise ConfigurationError(f"Invalid project configuration entry: {exc}") from exc
        if not isinstance(project_id, str) or not project_id or project_id in seen_ids:
            raise ConfigurationError("Project IDs must be non-empty and unique.")
        if not isinstance(name, str) or not name.strip():
            raise ConfigurationError(f"Project {project_id!r} must have a name.")
        if not root.is_dir():
            raise ConfigurationError(f"Project directory does not exist: {root}")
        if not python.is_file():
            raise ConfigurationError(f"Python interpreter does not exist: {python}")
        seen_ids.add(project_id)
        projects.append(Project(project_id, name.strip(), root, python))
    return projects
