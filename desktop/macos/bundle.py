#!/usr/bin/env python3
"""Build a self-contained Verticals.app (Apple Silicon) and a .dmg around it.

    python3 desktop/macos/bundle.py              # -> desktop/dist/Verticals.app, .dmg, .zip and -lite.zip
    python3 desktop/macos/bundle.py --out DIR    # build elsewhere (e.g. while an older build runs)
    python3 desktop/macos/bundle.py --dmg-only   # repackage the existing app
    python3 desktop/macos/bundle.py --version 0.4   # app version (CI passes the release's)
    python3 desktop/macos/bundle.py --dev        # a dev build: the yellow icon, so it never passes for the app people use

Contents/Resources mirrors the repository: verticals/, desktop/ (launcher, chat, UI build) and the
operator skill, plus a trimmed Python 3.12 with the dependencies and PostgreSQL 16 taken from
Homebrew with its Homebrew libraries copied in and relinked. The target Mac needs nothing
installed (only an agent CLI for the chat). Build machine needs: Homebrew postgresql@16, uv with
Python 3.12, Xcode Command Line Tools, and the UI built into desktop/build/web (see README).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # desktop/
REPO = ROOT.parent
DIST = Path(sys.argv[sys.argv.index("--out") + 1]).resolve() if "--out" in sys.argv else ROOT / "dist"
APP = DIST / "Verticals.app"
VERSION = sys.argv[sys.argv.index("--version") + 1] if "--version" in sys.argv else "0.2"
ICON = ROOT / "macos/icon" / ("AppIcon-dev.icns" if "--dev" in sys.argv else "AppIcon.icns")   # macos/icon/make_icon.py
RES = APP / "Contents" / "Resources"
BREW = Path("/opt/homebrew")
PG_OPT = BREW / "opt/postgresql@16"
PG_KEEP_BINS = ["postgres", "initdb", "pg_ctl"]
PG_KEEP_MODULES = ["plpgsql", "dict_snowball", "pg_trgm"]
# What rarely changes between releases: a lite update zip leaves these out, and the app completes it
# from its own copy when Resources/RUNTIME matches (Updater.swift).
RUNTIME_DIRS = ["pg", "python", "site"]
PY_DROP = ["lib/python3.12/idlelib", "lib/python3.12/tkinter", "lib/python3.12/turtledemo",
           "lib/python3.12/ensurepip", "lib/python3.12/test", "lib/python3.12/config-3.12-darwin",
           "lib/python3.12/lib-dynload/_tkinter.cpython-312-darwin.so", "include", "share",
           "lib/tcl8", "lib/tcl8.6", "lib/tk8.6", "lib/itcl4.2.4", "lib/thread2.8.9", "lib/pkgconfig"]


def sh(*args, **kw):
    return subprocess.run([str(a) for a in args], check=True, text=True, capture_output=True, **kw).stdout


def log(msg):
    print(f"[bundle] {msg}", flush=True)


# ---------------------------------------------------------------- Mach-O relinking

def macho_deps(path):
    lines = sh("otool", "-L", path).splitlines()[1:]
    return [line.strip().split(" (")[0] for line in lines if line.strip()]


def rpaths(path):
    out, found, lines = sh("otool", "-l", path).splitlines(), [], None
    for i, line in enumerate(out):
        if line.strip() == "cmd LC_RPATH":
            found.append(out[i + 2].strip().split(" ")[1])
    return found


def resolve(dep, original):
    """Absolute source path of a non-system dependency, or None for system libraries."""
    if dep.startswith(("/usr/lib/", "/System/")):
        return None
    if dep.startswith("/"):
        return Path(dep).resolve()
    if dep.startswith("@loader_path/"):
        return (original.parent / dep.removeprefix("@loader_path/")).resolve()
    if dep.startswith("@rpath/"):
        for rp in rpaths(original):
            candidate = Path(rp.replace("@loader_path", str(original.parent))) / dep.removeprefix("@rpath/")
            if candidate.exists():
                return candidate.resolve()
    raise SystemExit(f"cannot resolve {dep} for {original}")


def relink(files, deps_dir):
    """Copy every Homebrew library the given binaries need into deps_dir and point them there."""
    deps_dir.mkdir(parents=True, exist_ok=True)
    queue = [(f, orig) for f, orig in files]  # (bundle path, original path)
    copied = {}
    while queue:
        target, original = queue.pop()
        os.chmod(target, 0o755)
        if target.parent == deps_dir:
            sh("install_name_tool", "-id", f"@loader_path/{target.name}", target)
        for dep in macho_deps(target):
            src = resolve(dep, original)
            if src is None or src == original.resolve():
                continue
            name = Path(dep).name
            dest = deps_dir / name
            if name not in copied:
                shutil.copy2(src, dest)
                copied[name] = src
                queue.append((dest, src))
            ref = "@loader_path/" + os.path.relpath(dest, target.parent)
            sh("install_name_tool", "-change", dep, ref, target)
    return copied


def sign(path):
    sh("codesign", "--force", "--sign", "-", path)


# ---------------------------------------------------------------- pieces

def copy_code():
    log("code")
    skip = shutil.ignore_patterns("__pycache__", "workspace")
    shutil.copytree(REPO / "verticals", RES / "verticals", ignore=skip)
    (RES / "desktop").mkdir()
    shutil.copy2(ROOT / "launcher.py", RES / "desktop/launcher.py")
    shutil.copytree(ROOT / "chat", RES / "desktop/chat", ignore=skip)
    shutil.copytree(ROOT / "build/web", RES / "desktop/build/web")
    shutil.copytree(REPO / ".agents/skills/verticals-operator", RES / ".agents/skills/verticals-operator")


def copy_python():
    log("python")
    interpreter = sh("uv", "python", "find", "3.12").strip()
    home = Path(interpreter).resolve().parent.parent
    shutil.copytree(home, RES / "python", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "EXTERNALLY-MANAGED"))
    for rel in PY_DROP:
        p = RES / "python" / rel
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    # The library id still names the build machine's uv path (and home folder).
    libpython = RES / "python/lib/libpython3.12.dylib"
    os.chmod(libpython, 0o755)
    sh("install_name_tool", "-id", "@executable_path/../lib/libpython3.12.dylib", libpython)
    sign(libpython)
    python = RES / "python/bin/python3.12"
    log("python dependencies")
    # Dependencies only; verticals itself runs from Resources/verticals (with its SQL files).
    sh("uv", "pip", "install", "--quiet", "--python", python, "--target", RES / "site", "-r", REPO / "pyproject.toml")
    for p in (RES / "site").glob("bin"):
        shutil.rmtree(p)
    for record in (RES / "site").glob("*.dist-info/RECORD"):
        # uv writes these lines in no fixed order, and the bin/ scripts removed above carry the build
        # machine's Python path: sorted and without them, an unchanged runtime builds to the same bytes.
        lines = [line for line in record.read_text().splitlines() if not line.startswith("bin/")]
        record.write_text("\n".join(sorted(lines)) + "\n")
    log("precompiling")
    # Hash-based .pyc files with one recorded path, wherever the build runs, all rewritten (-f: some
    # were cached at import with the build path): an unchanged runtime builds to the same bytes.
    # Python puts the real path back when it loads them.
    subprocess.run([python, "-m", "compileall", "-q", "-f", "-j0", "--invalidation-mode", "unchecked-hash",
                    "-s", RES, "-p", "Verticals.app/Contents/Resources",
                    RES / "python/lib/python3.12", RES / "site",
                    RES / "verticals", RES / "desktop"], check=False)


def copy_postgres():
    log("postgresql")
    cellar = PG_OPT.resolve()                      # /opt/homebrew/Cellar/postgresql@16/<version>
    version = cellar.name
    pg = RES / "pg"
    # Postgres finds share/ and lib/ relative to its own binary, using the layout it was built
    # with (bin in Cellar/…/bin, data in opt/…): recreate that layout under Resources/pg.
    bindir = pg / "Cellar/postgresql@16" / version / "bin"
    sharedir = pg / "opt/postgresql@16/share/postgresql@16"
    pkglib = pg / "opt/postgresql@16/lib/postgresql"
    for d in (bindir, pkglib):
        d.mkdir(parents=True)
    shutil.copytree(PG_OPT / "share/postgresql@16", sharedir)
    ext = sharedir / "extension"
    for f in ext.iterdir():
        if not f.name.startswith(("plpgsql", "pg_trgm")):
            f.unlink()
    files = []
    for b in PG_KEEP_BINS:
        shutil.copy2(cellar / "bin" / b, bindir / b)
        files.append((bindir / b, cellar / "bin" / b))
    for m in PG_KEEP_MODULES:
        src = (PG_OPT / "lib/postgresql" / f"{m}.dylib").resolve()
        shutil.copy2(src, pkglib / src.name)
        files.append((pkglib / src.name, src))
    copied = relink(files, pg / "deps")
    # The app reads where the binaries are from here, so the Swift side never hardcodes a version.
    (pg / "BINDIR").write_text(str(bindir.relative_to(pg)) + "\n")
    log(f"postgresql libraries: {', '.join(sorted(copied))}")
    for path, _ in files:
        sign(path)
    for lib in (pg / "deps").iterdir():
        sign(lib)
    return bindir


def check_postgres(bindir):
    """initdb + start + pg_trgm on a scratch cluster, run from inside the bundle."""
    log("checking bundled postgresql")
    tmp = Path(sh("mktemp", "-d").strip())
    try:
        sh(bindir / "initdb", "-D", tmp / "data", "-U", "check", "--auth=trust", "--no-locale")
        # Unix socket in the scratch dir only, no TCP port.
        sh(bindir / "pg_ctl", "-D", tmp / "data", "-w", "-o", f"-h '' -k {tmp}", "-l", tmp / "log", "start")
        try:
            code = ("import psycopg, sys\n"
                    "c = psycopg.connect(host=sys.argv[1], user='check', dbname='postgres', autocommit=True)\n"
                    "c.execute('CREATE EXTENSION pg_trgm')\n"
                    "print(c.execute(\"SELECT similarity('verticals', 'vertical')\").fetchone()[0])")
            # Bundled python + psycopg against the bundled server, with a bare environment.
            env = {"PYTHONPATH": str(RES / "site"), "PYTHONNOUSERSITE": "1", "PATH": "/usr/bin:/bin"}
            result = subprocess.run([RES / "python/bin/python3", "-c", code, tmp], capture_output=True,
                                    text=True, env=env, check=True).stdout.strip()
            log(f"postgresql ok (pg_trgm similarity = {result})")
        finally:
            sh(bindir / "pg_ctl", "-D", tmp / "data", "-m", "fast", "-w", "stop")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build_launcher():
    log("launcher")
    (APP / "Contents/MacOS").mkdir(parents=True, exist_ok=True)
    sh("swiftc", "-O", "-parse-as-library", "-target", "arm64-apple-macos13.0", "-o", APP / "Contents/MacOS/Verticals",
       *(ROOT / "macos" / name for name in ("Verticals.swift", "Updater.swift", "UpdateIndicator.swift")))
    shutil.copy2(ICON, RES / "AppIcon.icns")
    (APP / "Contents/Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Verticals</string>
  <key>CFBundleDisplayName</key><string>Verticals</string>
  <key>CFBundleIdentifier</key><string>app.verticals.desktop</string>
  <key>CFBundleExecutable</key><string>Verticals</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{VERSION}</string>
  <key>CFBundleVersion</key><string>{VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
""")


def sign_all():
    log("signing")
    # Every Mach-O inside must carry a valid signature on Apple Silicon; sign inside-out.
    macho = (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
    for path in sorted(RES.rglob("*"), key=lambda p: -len(p.parts)):
        if path.is_file() and not path.is_symlink():
            with open(path, "rb") as f:
                if f.read(4) in macho:
                    sign(path)
    (RES / "RUNTIME").write_text(runtime_fingerprint() + "\n")
    sh("codesign", "--force", "--sign", "-", APP)
    sh("codesign", "--verify", "--deep", "--strict", APP)


def runtime_fingerprint():
    """One hash over every file and link of the runtime dirs, as signed: equal means byte-identical."""
    total = hashlib.sha256()
    for top in RUNTIME_DIRS:
        for path in sorted((RES / top).rglob("*")):
            rel = path.relative_to(RES).as_posix()
            if path.is_symlink():
                total.update(f"L {rel} {os.readlink(path)}\n".encode())
            elif path.is_file():
                total.update(f"F {rel} {hashlib.sha256(path.read_bytes()).hexdigest()}\n".encode())
    return total.hexdigest()[:16]


def make_dmg():
    log("dmg")
    stage = DIST / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    sh("ditto", APP, stage / APP.name)
    os.symlink("/Applications", stage / "Applications")
    (stage / "Как установить.txt").write_text(INSTALL_NOTE)
    dmg = DIST / "Verticals.dmg"
    dmg.unlink(missing_ok=True)
    sh("hdiutil", "create", "-volname", "Verticals", "-srcfolder", stage, "-ov", "-format", "UDZO", dmg)
    shutil.rmtree(stage)
    return dmg


def make_zips():
    """What the app downloads to update itself (Updater.swift): the whole app, and a lite one without
    the runtime dirs, which an installed app with the same RUNTIME completes from its own copy."""
    log("zips")
    full, lite = DIST / "Verticals.zip", DIST / "Verticals-lite.zip"
    for archive in (full, lite):
        archive.unlink(missing_ok=True)
    sh("ditto", "-c", "-k", "--keepParent", APP, full)
    stage = DIST / "lite"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    sh("ditto", APP, stage / APP.name)
    for top in RUNTIME_DIRS:
        shutil.rmtree(stage / APP.name / "Contents/Resources" / top)
    sh("ditto", "-c", "-k", "--keepParent", stage / APP.name, lite)
    shutil.rmtree(stage)
    return full, lite


INSTALL_NOTE = """Verticals — установка

1. Перетащите «Verticals» в папку «Программы».

2. Приложение не подписано Apple, поэтому macOS его заблокирует. Снимите карантин
   в Терминале:

   xattr -dr com.apple.quarantine "/Applications/Verticals.app"

   Или: откройте приложение один раз, затем «Системные настройки →
   Конфиденциальность и безопасность» → внизу «Всё равно открыть».

3. Откройте Verticals. Всё нужное внутри: база, сервер, интерфейс.
   Данные хранятся в ~/Library/Application Support/Verticals

Чат с Claude (строка внизу, ⌘K) требует установленный Claude Code с выполненным входом:
   curl -fsSL https://claude.ai/install.sh | bash
   claude auth login

MCP для своих агентов, пока приложение открыто: http://127.0.0.1:8281/mcp
(токен и готовый конфиг: ~/Library/Application Support/Verticals/mcp.json)

Обновления скачиваются сами и ставятся, когда вы закрываете Verticals; справа в полосе
заголовка видно, что стало лучше, и кнопка Update, а в ней Restart. Вручную: меню Verticals →
Check for Updates…

Требуется Mac на Apple Silicon (M1 и новее), macOS 13+.
"""


def main():
    if not (ROOT / "build/web/index.html").exists():
        sys.exit("desktop/build/web is missing; build the UI first (see desktop/README.md)")
    DIST.mkdir(parents=True, exist_ok=True)
    if "--dmg-only" in sys.argv:
        log(f"done: {make_dmg()}")
        return
    shutil.rmtree(APP, ignore_errors=True)
    RES.mkdir(parents=True)
    copy_code()
    copy_python()
    bindir = copy_postgres()
    build_launcher()
    sign_all()
    check_postgres(bindir)
    dmg = make_dmg()
    full, lite = make_zips()
    size = lambda p: sh("du", "-sh", p).split()[0]
    log(f"done: {APP} {VERSION} ({size(APP)}), {dmg} ({size(dmg)}), {full} ({size(full)}), {lite} ({size(lite)}),"
        f" runtime {(RES / 'RUNTIME').read_text().strip()}")


if __name__ == "__main__":
    main()
