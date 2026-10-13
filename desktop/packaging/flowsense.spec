# PyInstaller build for the FlowSense desktop app (one folder, no console window).
#
#   pyinstaller desktop/packaging/flowsense.spec --distpath build/dist --workpath build/work --noconfirm
#
# The result, build/dist/FlowSense/, contains FlowSense(.exe) plus its libraries, the web UI and the
# database migrations. PostgreSQL itself is not bundled (see the README).

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821 (SPECPATH is provided by PyInstaller)
BACKEND = ROOT / "backend"
DESKTOP = ROOT / "desktop"

hidden_imports = (
    collect_submodules("app")  # the backend, imported by the embedded server
    + collect_submodules("agent")
    + collect_submodules("uvicorn")  # protocol/loop implementations are chosen at runtime
    + collect_submodules("websockets")
    + collect_submodules("psycopg")
    + collect_submodules("psycopg_binary")
    + collect_submodules("alembic")
    + ["plyer.platforms.win.notification", "plyer.platforms.macosx.notification", "plyer.platforms.linux.notification"]
)

a = Analysis(  # noqa: F821
    [str(DESKTOP / "flowsense.py")],
    pathex=[str(BACKEND), str(DESKTOP)],
    datas=[
        (str(ROOT / "frontend"), "frontend"),
        (str(BACKEND / "alembic"), "backend/alembic"),
        (str(BACKEND / "alembic.ini"), "backend"),
        *collect_data_files("tzdata"),  # time zone database (Windows has none built in)
    ],
    hiddenimports=hidden_imports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "playwright", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FlowSense",
    console=False,  # no console window
    icon=str(DESKTOP / "packaging" / "flowsense.ico"),
    upx=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="FlowSense",
)
