#!/usr/bin/env python3
# scripts/release.py
# Bump version, update CHANGELOG, commit & tag.



"""
utilisation:
# Patch (1.5.0 -> 1.5.1), commit, tag
python scripts/release.py --patch

# Minor (1.5.0 -> 1.6.0) + push vers origin
python scripts/release.py --minor --push

# Fixer explicitement
python scripts/release.py --set 1.5.2

# Dry run (voir juste le résultat)
python scripts/release.py --patch --dry-run


"""


import argparse, re, sys, subprocess, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO / "core" / "version.py"
CHANGELOG = REPO / "CHANGELOG.md"

VER_RE = re.compile(r'^__version__\s*=\s*"(.*?)"\s*$', re.M)

CHANGELOG_TEMPLATE = """# Changelog

All notable changes to this project will be documented here.
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- 
### Changed
- 
### Fixed
- 
"""

def run(cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True)

def get_current_branch():
    res = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return res.stdout.strip()

def read_version():
    txt = VERSION_FILE.read_text(encoding="utf-8")
    m = VER_RE.search(txt)
    if not m:
        print(f"[ERR] __version__ introuvable dans {VERSION_FILE}")
        sys.exit(1)
    return m.group(1), txt

def write_version(new_version, content):
    new = VER_RE.sub(f'__version__ = "{new_version}"', content)
    VERSION_FILE.write_text(new, encoding="utf-8")

def parse_semver(v):
    parts = v.split(".")
    if len(parts) != 3: raise ValueError("Version doit être X.Y.Z")
    return tuple(int(p) for p in parts)

def bump(ver, kind):
    major, minor, patch = parse_semver(ver)
    if kind == "major":
        return f"{major+1}.0.0"
    if kind == "minor":
        return f"{major}.{minor+1}.0"
    if kind == "patch":
        return f"{major}.{minor}.{patch+1}"
    raise ValueError("kind inconnu")

def ensure_changelog():
    if not CHANGELOG.exists():
        CHANGELOG.write_text(CHANGELOG_TEMPLATE, encoding="utf-8")

def update_changelog(new_version):
    ensure_changelog()
    txt = CHANGELOG.read_text(encoding="utf-8")

    today = datetime.date.today().isoformat()
    hdr_new = f"## [{new_version}] - {today}"

    # Cherche la section Unreleased et isole son contenu
    # On capture tout ce qui est entre "## [Unreleased]" et la prochaine "## [..]" ou fin
    unreleased_pat = re.compile(r"(## \[Unreleased\]\s*)(.*?)(\n## \[.*?\]|$)", re.S)
    m = unreleased_pat.search(txt)
    if not m:
        # Pas de section Unreleased => on insère en haut
        insert_after = txt.find("\n## ")
        if insert_after == -1:
            # juste le titre
            txt = txt.rstrip() + f"\n\n{hdr_new}\n\n### Added\n- \n### Changed\n- \n### Fixed\n- \n"
        else:
            head = txt[:insert_after]
            rest = txt[insert_after:]
            new_sec = f"\n{hdr_new}\n\n### Added\n- \n### Changed\n- \n### Fixed\n- \n"
            txt = head + new_sec + rest
        CHANGELOG.write_text(txt, encoding="utf-8")
        return

    prefix, body, tail = m.group(1), m.group(2), m.group(3)

    # Nettoyage léger : si body est quasi vide, on met des placeholders
    content = body.strip()
    if not content or content == "":
        content = "### Added\n- \n### Changed\n- \n### Fixed\n- \n"
    # Évite le doublon de titres si l’utilisateur a déjà mis des "### ..." : OK.

    # Reconstruit : Unreleased (vide) en tête + section versionnée juste après
    unreleased_new = "## [Unreleased]\n### Added\n- \n### Changed\n- \n### Fixed\n- \n"
    versioned = f"{hdr_new}\n\n{content.strip()}\n"

    new_txt = unreleased_pat.sub(unreleased_new + "\n" + versioned + ("\n" if tail else "") + tail, txt, count=1)
    CHANGELOG.write_text(new_txt, encoding="utf-8")

def git_add_commit_tag(new_version, push=False):
    run(["git", "add", str(VERSION_FILE), str(CHANGELOG)])
    msg = f"chore(release): v{new_version}"
    run(["git", "commit", "-m", msg])
    run(["git", "tag", "-a", f"v{new_version}", "-m", f"RBciAD {new_version}"])

    if push:
        branch = get_current_branch()
        run(["git", "push", "origin", branch])
        run(["git", "push", "origin", "--tags"])

def main():
    ap = argparse.ArgumentParser(description="Release helper: bump version, update changelog, tag.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--major", action="store_true", help="bump major (X+1.0.0)")
    g.add_argument("--minor", action="store_true", help="bump minor (Y+1)")
    g.add_argument("--patch", action="store_true", help="bump patch (Z+1)")
    g.add_argument("--set", metavar="X.Y.Z", help="set explicit version")

    ap.add_argument("--push", action="store_true", help="push branch & tags to origin")
    ap.add_argument("--no-tag", action="store_true", help="do not create a git tag")
    ap.add_argument("--dry-run", action="store_true", help="compute only, no file or git changes")

    args = ap.parse_args()

    cur, content = read_version()
    if args.set:
        new_ver = args.set.strip()
    elif args.major:
        new_ver = bump(cur, "major")
    elif args.minor:
        new_ver = bump(cur, "minor")
    elif args.patch:
        new_ver = bump(cur, "patch")
    else:
        ap.error("choose --major/--minor/--patch or --set X.Y.Z")
        return

    print(f"Current: {cur} -> New: {new_ver}")

    if args.dry_run:
        return

    write_version(new_ver, content)
    update_changelog(new_ver)

    # commit + tag
    run(["git", "add", str(VERSION_FILE), str(CHANGELOG)])
    run(["git", "diff", "--staged"], check=False)  # Feedback
    run(["git", "commit", "-m", f"chore(release): v{new_ver}"])

    if not args.no_tag:
        run(["git", "tag", "-a", f"v{new_ver}", "-m", f"RBciAD {new_ver}"])

    if args.push:
        branch = get_current_branch()
        run(["git", "push", "origin", branch])
        if not args.no_tag:
            run(["git", "push", "origin", "--tags"])

    print("Done.")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(e.stderr or str(e))
        sys.exit(e.returncode)
