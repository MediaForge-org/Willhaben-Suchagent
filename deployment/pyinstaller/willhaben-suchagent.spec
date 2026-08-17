# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the Willhaben-Suchagent runtime.

Produces one onedir bundle containing two executables that share the same
Python runtime and dependencies (a "multipackage" bundle, see PyInstaller's
MERGE()):

  willhaben-suchagent        the FastAPI agent/server (agent.app.main:run)
  willhaben-suchagent-host   the Firefox native-messaging bridge
                              (agent.app.native_messaging.host:main)

Build on the target OS — see deployment/build-release-linux.sh and
deployment/build-release-windows.ps1. Do not cross-compile.
"""

import os

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
REPO_ROOT = os.path.abspath(os.path.join(SPEC_DIR, "..", ".."))

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

agent_analysis = Analysis(
    ["run_agent.py"],
    pathex=[SPEC_DIR, REPO_ROOT],
    hiddenimports=hiddenimports,
    noarchive=False,
)

host_analysis = Analysis(
    ["run_native_host.py"],
    pathex=[SPEC_DIR, REPO_ROOT],
    hiddenimports=hiddenimports,
    noarchive=False,
)

setup_analysis = Analysis(
    ["run_setup.py"],
    pathex=[SPEC_DIR, REPO_ROOT],
    hiddenimports=hiddenimports,
    noarchive=False,
)

MERGE(
    (agent_analysis, "willhaben-suchagent", "willhaben-suchagent"),
    (host_analysis, "willhaben-suchagent-host", "willhaben-suchagent-host"),
    (setup_analysis, "willhaben-suchagent-setup", "willhaben-suchagent-setup"),
)

agent_pyz = PYZ(agent_analysis.pure)
agent_exe = EXE(
    agent_pyz,
    agent_analysis.scripts,
    [],
    exclude_binaries=True,
    name="willhaben-suchagent",
    console=True,
)

host_pyz = PYZ(host_analysis.pure)
host_exe = EXE(
    host_pyz,
    host_analysis.scripts,
    [],
    exclude_binaries=True,
    name="willhaben-suchagent-host",
    console=True,
)

setup_pyz = PYZ(setup_analysis.pure)
setup_exe = EXE(
    setup_pyz,
    setup_analysis.scripts,
    [],
    exclude_binaries=True,
    name="willhaben-suchagent-setup",
    console=True,
)

COLLECT(
    agent_exe,
    agent_analysis.binaries,
    agent_analysis.zipfiles,
    agent_analysis.datas,
    host_exe,
    host_analysis.binaries,
    host_analysis.zipfiles,
    host_analysis.datas,
    setup_exe,
    setup_analysis.binaries,
    setup_analysis.zipfiles,
    setup_analysis.datas,
    name="runtime",
)
