import glob
import os
import re
import subprocess


def run_git(args):
    try:
        return (
            subprocess.check_output(["git"] + args, stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
    except subprocess.CalledProcessError:
        return ""


def main():
    rtype = os.environ.get("RELEASE_TYPE", "beta")
    bump_level = os.environ.get("BUMP_LEVEL", "patch")
    version_override = os.environ.get("VERSION_OVERRIDE", "")
    repo = os.environ.get("REPO", "")

    owner = "faserf"
    repo_name = os.path.basename(os.getcwd())
    if "/" in repo:
        owner, repo_name = repo.split("/", 1)

    manifest_files = glob.glob("custom_components/*/manifest.json")
    if not manifest_files:
        print("Error: manifest.json not found!")
        return
    manifest_path = manifest_files[0]

    bump_args = [
        "python",
        ".github/scripts/version_manager.py",
        "bump",
        "--type",
        rtype,
        "--level",
        bump_level,
    ]
    if version_override and version_override.strip():
        bump_args += ["--override", version_override.strip()]

    version = subprocess.check_output(bump_args).decode("utf-8").strip()
    run_git(["checkout", "--", manifest_path])

    print(f"Calculated Version: {version}")
    tag = f"v{version}"
    is_prerelease = "false" if rtype == "stable" else "true"

    changelog_from = ""

    tags_raw = run_git(["tag", "-l", "[0-9]*", "v[0-9]*", "--sort=-v:refname"])
    tags = [t.strip() for t in tags_raw.splitlines() if t.strip()]

    if rtype == "stable":
        for t in tags:
            if re.match(r"^v?\d+\.\d+\.\d+$", t):
                changelog_from = t
                break
    else:
        if tags:
            changelog_from = tags[0]

    repo_url = f"https://github.com/{owner}/{repo_name}"
    cl_args = [
        "python",
        ".github/scripts/changelog_builder.py",
        "--repo-url",
        repo_url,
        "--output",
        "release_body.md",
    ]
    if changelog_from:
        cl_args += ["--from-tag", changelog_from]

    subprocess.check_call(cl_args)

    with open(os.environ.get("GITHUB_OUTPUT", "output.txt"), "a", encoding="utf-8") as f:
        f.write(f"version={version}\n")
        f.write(f"tag={tag}\n")
        f.write(f"is_prerelease={is_prerelease}\n")


if __name__ == "__main__":
    main()
