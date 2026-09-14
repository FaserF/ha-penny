import json
import os
import re
import urllib.request


def get_latest_ha_version():
    try:
        url = "https://pypi.org/pypi/homeassistant/json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data["info"]["version"]
    except Exception as e:  # noqa: BLE001
        print(f"Error fetching HA version: {e}")
        return "2026.8.3"


def clean_and_update_template(file_path, integration_version, ha_version, repo_name):
    if not os.path.exists(file_path):
        return False

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    original_content = content

    clean_ver = integration_version.lstrip("v")
    target_ver = f"v{clean_ver}"

    blocks = re.split(r"(\s*-\s*type:)", content)

    for i in range(2, len(blocks), 2):
        block_content = blocks[i]

        field_id_match = re.search(r"id:\s*([a-zA-Z0-9_-]+)", block_content)
        if not field_id_match:
            continue
        field_id = field_id_match.group(1)

        if field_id in ("integration_version", "version"):
            def repl_ver(match):
                quote = match.group(1) or ""
                prefix = match.group(2) or ""
                return f"placeholder: {quote}{prefix}{target_ver}{quote}"

            new_block = re.sub(
                r'placeholder:\s*(["\']?)(e\.g\.\s*)?[^\n"\']+\1',
                repl_ver,
                block_content,
            )
            blocks[i] = new_block

        elif field_id == "ha_version":
            def repl_ha(match):
                quote = match.group(1) or ""
                prefix = match.group(2) or ""
                return f"placeholder: {quote}{prefix}{ha_version}{quote}"

            new_block = re.sub(
                r'placeholder:\s*(["\']?)(e\.g\.\s*)?[^\n"\']+\1',
                repl_ha,
                block_content,
            )
            blocks[i] = new_block

    updated_content = "".join(blocks)
    if updated_content != original_content:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(updated_content)
        return True
    return False


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: update_templates.py <integration_version>")
        return

    ver = sys.argv[1]
    ha_ver = get_latest_ha_version()
    repo_name = os.path.basename(os.getcwd())

    template_dir = os.path.join(".github", "ISSUE_TEMPLATE")
    if os.path.exists(template_dir):
        for f in os.listdir(template_dir):
            if f.endswith((".yml", ".yaml")):
                clean_and_update_template(
                    os.path.join(template_dir, f), ver, ha_ver, repo_name
                )


if __name__ == "__main__":
    main()
