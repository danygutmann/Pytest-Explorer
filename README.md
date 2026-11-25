# Pytest Explorer

Pytest Explorer is a standalone NiceGUI application for discovering, selecting,
and running tests in configured external pytest projects. The external test
project and its virtual environment are not modified.

## Features

- Discover tests with the configured project interpreter and `pytest --collect-only`.
- Browse directories, files, classes, and individual tests; filter and select groups.
- Run selected tests asynchronously with live output, counts, elapsed time, and stop.
- Keep each run's full `pytest.log`, self-contained HTML report, and history entry.

## Raspberry Pi installation (without Docker)

Use Python 3.10 or later and install Pytest Explorer in its own virtual environment:

```bash
git clone https://github.com/danygutmann/Pytest-Explorer.git
cd Pytest-Explorer
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Create the preferred project symlink (or configure the actual directory directly):

```bash
sudo mkdir -p /opt/pytest-projects
sudo ln -s /home/pi/ctc_ta_vtc_ngcp_coretura_smoke_test /opt/pytest-projects/ngcp
```

Edit [`config/projects.json`](config/projects.json) to set each project's stable
`id`, display `name`, project `path`, and the project's existing `python`
interpreter. Add another object to `projects` to configure another project.
The app only runs configured projects; paths and test selectors are never passed
through a shell. The configuration and interpreter must exist when the app starts.

Start the application:

```bash
python -m pytest_explorer
```

Open `http://<raspberry-pi-address>:8080`. Set `PYTEST_EXPLORER_HOST`,
`PYTEST_EXPLORER_PORT`, `PYTEST_EXPLORER_CONFIG`, or
`PYTEST_EXPLORER_DATA_DIR` to override the defaults. The default listener accepts
LAN connections; use a trusted network and restrict port 8080 with the host
firewall. The application does not provide user authentication.

Docker deployment is intentionally not provided: the runner launches the
configured interpreter directly on the Raspberry Pi so host virtual-environment
and hardware access are not silently changed by container isolation.

## Development and tests

Run the focused standard-library tests with:

```bash
python -m unittest discover -s tests -v
```

Pytest is provided by each configured test project's interpreter, not by this
application. Do not start real hardware tests without explicit authorization.
