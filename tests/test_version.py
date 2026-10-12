"""Die Versionsnummer steht an einer Stelle (modules/__init__.py); der Installer muss sie spiegeln."""

import re
from pathlib import Path

import modules

ROOT = Path(__file__).resolve().parent.parent


def test_installer_version_matches_package():
    iss = (ROOT / "installer" / "Lichtloch.iss").read_text(encoding="utf-8")
    match = re.search(r'#define\s+AppVersion\s+"([^"]+)"', iss)
    assert match, "AppVersion fehlt in installer/Lichtloch.iss"
    assert match.group(1) == modules.__version__


def test_user_agent_identifies_app_and_project():
    assert modules.USER_AGENT.startswith(f"lichtloch-app/{modules.__version__}")
    assert modules.PROJECT_URL in modules.USER_AGENT
