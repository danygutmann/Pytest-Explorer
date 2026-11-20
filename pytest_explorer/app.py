from __future__ import annotations

import os
from pathlib import Path

from nicegui import app, ui

from .config import ConfigurationError, Project, load_projects
from .discovery import TestNode, build_tree, discover
from .runner import Run, RunManager

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("PYTEST_EXPLORER_CONFIG", ROOT / "config/projects.json"))
DATA_DIR = Path(os.environ.get("PYTEST_EXPLORER_DATA_DIR", ROOT / "data")).expanduser()


def _leaf_ids(node: TestNode) -> list[str]:
    if node.nodeid:
        return [node.nodeid]
    return [node_id for child in node.children.values() for node_id in _leaf_ids(child)]


def _render_node(
    node: TestNode,
    selected: set[str],
    search: str,
    on_select,
) -> None:
    children = [
        child for child in node.children.values()
        if not search or search in child.label.lower()
        or any(search in test_id.lower() for test_id in _leaf_ids(child))
    ]
    if not children:
        return
    with ui.expansion(node.label, icon="folder_open").classes("w-full"):
        for child in children:
            if child.nodeid:
                ui.checkbox(
                    child.label,
                    value=child.nodeid in selected,
                    on_change=lambda event, nodeid=child.nodeid: on_select(
                        nodeid, event.value
                    ),
                ).classes("w-full")
            else:
                node_ids = _leaf_ids(child)
                checked = bool(node_ids) and all(node_id in selected for node_id in node_ids)
                with ui.row().classes("items-center w-full"):
                    ui.checkbox(
                        child.label,
                        value=checked,
                        on_change=lambda event, ids=node_ids: on_select(ids, event.value),
                    )
                    _render_node(child, selected, search, on_select)


def create_app() -> None:
    try:
        projects = load_projects(CONFIG_PATH)
    except ConfigurationError as exc:
        projects = []
        configuration_error = str(exc)
    else:
        configuration_error = ""
    manager = RunManager(DATA_DIR)
    app.add_static_files("/runs", str(manager.runs_dir))
    ui.add_head_html(
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
    )
    ui.add_css(
        "body { background: #f5f7fa; } "
        ".q-card { border-radius: 12px; } "
        ".run-output textarea { font-family: monospace; }"
    )

    @ui.page("/")
    def index() -> None:
        selected: set[str] = set()
        discovered: list[str] = []
        current_run: Run | None = None
        project_by_id = {project.id: project for project in projects}

        with ui.header().classes("items-center justify-between bg-indigo-900"):
            ui.label("Pytest Explorer").classes("text-h5 font-bold")
            ui.label("Discover · select · run").classes("text-sm")

        with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
            if configuration_error:
                ui.label(f"Project configuration error: {configuration_error}").classes(
                    "text-negative"
                )
                ui.label(f"Edit {CONFIG_PATH} and restart the application.")
                return

            with ui.card().classes("w-full"):
                ui.label("Test project").classes("text-h6")
                with ui.row().classes("items-end w-full"):
                    project_select = ui.select(
                        {project.id: project.name for project in projects},
                        value=projects[0].id,
                        label="Project",
                    ).classes("min-w-64")
                    discover_button = ui.button(
                        "Refresh collection", icon="refresh"
                    ).props("color=indigo")

            with ui.row().classes("w-full items-start gap-4"):
                with ui.card().classes("grow"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label("Test explorer").classes("text-h6")
                        with ui.row():
                            ui.button("Select all", on_click=lambda: select_all()).props(
                                "flat"
                            )
                            ui.button("Clear", on_click=lambda: clear_selection()).props(
                                "flat"
                            )
                    search_box = ui.input(
                        "Search test names", placeholder="Type to filter tests"
                    ).props("clearable").classes("w-full")
                    tree_container = ui.column().classes("w-full")
                    collection_status = ui.label("Refresh collection to discover tests.")
                    with ui.row():
                        run_button = ui.button("Run selected", icon="play_arrow").props(
                            "color=positive"
                        )
                        stop_button = ui.button("Stop", icon="stop").props(
                            "color=negative"
                        )

                with ui.card().classes("grow"):
                    ui.label("Live run").classes("text-h6")
                    run_status = ui.label("No run started.")
                    progress = ui.linear_progress(value=0, show_value=False).classes(
                        "w-full"
                    )
                    counts = ui.label("Passed 0 · Failed 0 · Skipped 0")
                    output = ui.textarea("Live output").props(
                        "readonly autogrow"
                    ).classes("w-full run-output")

            with ui.card().classes("w-full"):
                ui.label("Execution history").classes("text-h6")
                history_container = ui.column().classes("w-full")

        def active_project() -> Project:
            return project_by_id[project_select.value]

        def on_select(node_ids, checked: bool) -> None:
            ids = [node_ids] if isinstance(node_ids, str) else node_ids
            if checked:
                selected.update(ids)
            else:
                selected.difference_update(ids)

        def render_tree() -> None:
            tree_container.clear()
            if not discovered:
                return
            tree = build_tree(discovered)
            with tree_container:
                _render_node(tree, selected, search_box.value.lower().strip(), on_select)

        def select_all() -> None:
            selected.update(discovered)
            render_tree()

        def clear_selection() -> None:
            selected.clear()
            render_tree()

        async def refresh_collection() -> None:
            nonlocal discovered
            collection_status.set_text("Discovering tests…")
            discover_button.disable()
            try:
                discovered = await discover(active_project())
                selected.clear()
                render_tree()
                collection_status.set_text(f"Found {len(discovered)} tests.")
            except Exception as exc:
                discovered = []
                selected.clear()
                render_tree()
                collection_status.set_text(f"Collection failed: {exc}")
            finally:
                discover_button.enable()

        async def start_run() -> None:
            nonlocal current_run
            if not selected:
                ui.notify("Select at least one test.", type="warning")
                return
            if not set(selected).issubset(discovered):
                ui.notify("Refresh the collection before running tests.", type="warning")
                return
            try:
                current_run = await manager.start(active_project(), sorted(selected))
                run_status.set_text("Starting pytest…")
            except (RuntimeError, ValueError) as exc:
                ui.notify(str(exc), type="negative")

        async def stop_run() -> None:
            if not current_run:
                return
            if not await manager.stop(current_run.project_id):
                ui.notify("There is no active run to stop.", type="warning")

        def render_history() -> None:
            history_container.clear()
            with history_container:
                if not manager.history:
                    ui.label("No runs yet.")
                for entry in manager.history:
                    with ui.row().classes("items-center gap-3"):
                        ui.label(
                            f"{entry['started_at'][:19].replace('T', ' ')} · "
                            f"{entry['project_name']} · {entry['status']} · "
                            f"{entry['duration']}s"
                        )
                        ui.link("Report", f"/runs/{entry['id']}/report.html").props(
                            "target=_blank"
                        )
                        ui.link("pytest.log", f"/runs/{entry['id']}/pytest.log").props(
                            "target=_blank"
                        )

        def refresh_run_view() -> None:
            if not current_run:
                return
            run = manager.get(current_run.id)
            if not run:
                return
            run_status.set_text(
                f"{run.status.title()} · {run.current_test or 'Waiting for first test'}"
            )
            total = len(run.selectors)
            progress.set_value(min(run.completed / total, 1) if total else 0)
            counts.set_text(
                f"Passed {run.counts['passed']} · Failed {run.counts['failed']} · "
                f"Skipped {run.counts['skipped']} · "
                f"{run.completed}/{total} · {run.duration:.1f}s"
            )
            output.value = run.output[-30000:]
            output.update()
            render_history()

        discover_button.on_click(refresh_collection)
        project_select.on_value_change(
            lambda _: refresh_collection()
        )
        search_box.on_value_change(lambda _: render_tree())
        run_button.on_click(start_run)
        stop_button.on_click(stop_run)
        ui.timer(0.5, refresh_run_view)
        render_history()
        ui.timer(0.1, refresh_collection, once=True)

    ui.run(
        title="Pytest Explorer",
        host=os.environ.get("PYTEST_EXPLORER_HOST", "0.0.0.0"),
        port=int(os.environ.get("PYTEST_EXPLORER_PORT", "8080")),
        reload=False,
        show=False,
    )
