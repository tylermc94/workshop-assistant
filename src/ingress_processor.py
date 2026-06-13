# To install cron: crontab -e
# */10 * * * * cd /home/tyler/projects/workshop-assistant && /home/tyler/projects/workshop-assistant/venv/bin/python -c "from src.ingress_processor import process_ingress; process_ingress()"

import json
import os
import sys
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from config.secrets import CLAUDE_API_KEY as ANTHROPIC_API_KEY
from config.settings import VAULT_PATH
os.environ['ANTHROPIC_API_KEY'] = ANTHROPIC_API_KEY

sys.path.insert(0, VAULT_PATH)
import forge_capture
import anthropic

from config.logging_config import setup_logging
setup_logging()
import logging
logger = logging.getLogger(__name__)

forge_capture.VAULT = Path(VAULT_PATH)
forge_capture.PROJECTS_DIR = forge_capture.VAULT / "Projects"
forge_capture.ACTIVE_DIR = forge_capture.VAULT / "Projects" / "Active"
forge_capture.SOMEDAY_DIR = forge_capture.VAULT / "Projects" / "Someday"
forge_capture.AREAS_DIR = forge_capture.VAULT / "Areas"
forge_capture.INBOX_DIR = forge_capture.VAULT / "Inbox"
forge_capture.RESOURCES_DIR = forge_capture.VAULT / "Resources"
forge_capture.INGRESS_DIR = forge_capture.VAULT / "Ingress"
forge_capture.INGRESS_PROCESSED_DIR = forge_capture.VAULT / "Ingress" / "Processed"
forge_capture.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

VAULT = forge_capture.VAULT
INGRESS_DIR = forge_capture.INGRESS_DIR
INGRESS_PROCESSED_DIR = forge_capture.INGRESS_PROCESSED_DIR
NEEDS_REVIEW_DIR = VAULT / "Ingress" / "Needs Review"
FORGE_LOG = VAULT / "Forge Log.md"


def detect_target(filepath: Path, projects: list[str], areas: list[str]) -> tuple[str | None, str]:
    """
    Try to detect the target project/area for the given file.
    Returns (target_name, method) where method is one of:
    "frontmatter", "body", "filename", "inferred", or "unknown"
    """
    content = filepath.read_text(encoding='utf-8')

    # 1. Frontmatter: look for forge-target field between --- markers
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if frontmatter_match:
        fm_body = frontmatter_match.group(1)
        target_match = re.search(r'^forge-target:\s*(.+)$', fm_body, re.MULTILINE)
        if target_match:
            return target_match.group(1).strip(), "frontmatter"

    # 2. Body line: scan for "> Target: <value>" or "Target: <value>"
    for line in content.splitlines():
        body_match = re.match(r'^>?\s*Target:\s*(.+)$', line.strip())
        if body_match:
            return body_match.group(1).strip(), "body"

    # 3. Filename: check if filename starts with [ProjectName] pattern
    filename_match = re.match(r'^\[(.+?)\]', filepath.stem)
    if filename_match:
        return filename_match.group(1).strip(), "filename"

    # 4. Claude inference
    all_targets = projects + areas
    prompt = (
        f"Available projects and areas: {', '.join(all_targets)}\n\n"
        f"File name: {filepath.name}\n\n"
        f"File content:\n{content[:2000]}\n\n"
        "Based on the file name and content, which project or area from the list above "
        "does this note most likely belong to? "
        'Reply with JSON only, no other text: {"target": "<name or null>", "confidence": "<high|medium|low>", "reason": "<one sentence>"}'
    )
    try:
        raw = forge_capture.call_claude(
            "You are a second brain file router. Identify the most likely target project or area for a note.",
            prompt,
            max_tokens=150
        )
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            target = result.get('target')
            confidence = result.get('confidence', 'low')
            reason = result.get('reason', '')
            if target and confidence in ('high', 'medium'):
                return target, "inferred"
            return None, "unknown"
    except Exception:
        pass

    return None, "unknown"


def _resolve_target_path(target: str, areas: list[str]) -> Path:
    """Resolve a target project/area *name* to its markdown file Path.

    upsert_section needs a Path, not the bare name. Prefer an existing project
    file, then an existing Area file, else default to a new Active project file
    (upsert_section creates the file if it doesn't exist).
    """
    project_file = forge_capture.find_project_file(target)
    if project_file is not None:
        return project_file
    match = next((a for a in areas if a.lower() == target.lower()), target)
    area_file = forge_capture.AREAS_DIR / f"{match}.md"
    if area_file.exists():
        return area_file
    return forge_capture.ACTIVE_DIR / f"{target}.md"


def route_content(filepath: Path, content: str, target: str, projects: list[str], areas: list[str]) -> tuple[str, Path]:
    """
    Call Claude to decide how to integrate the content, then execute the action.
    Returns (action_taken_description, target_filepath).
    """
    prompt = (
        f"Target: {target}\n\n"
        f"File name: {filepath.name}\n\n"
        f"Content:\n{content[:3000]}\n\n"
        'Decide how to integrate this note into the target. Reply with JSON only, no other text: '
        '{"action": "<append_research|create_subproject|add_tasks|append_note>", "reason": "<one sentence>"}'
    )
    action = "append_note"
    try:
        raw = forge_capture.call_claude(
            "You are a second brain content router. Given a note, decide the best way to integrate it into the target project. "
            'Reply with JSON only: {"action": one of "append_research", "create_subproject", "add_tasks", "append_note", "reason": one sentence explaining the decision}',
            prompt,
            max_tokens=100
        )
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            action = result.get('action', 'append_note')
            if action not in ('append_research', 'create_subproject', 'add_tasks', 'append_note'):
                action = 'append_note'
    except Exception:
        pass

    stem = filepath.stem
    target_filepath = None

    if action == 'append_research':
        target_filepath = _resolve_target_path(target, areas)
        forge_capture.upsert_section(target_filepath, f"## Research: {stem}", content)
        action_desc = f"append_research in {target}"
    elif action == 'create_subproject':
        target_filepath = forge_capture.write_new_project(
            {"title": stem, "content": content, "is_future": False}
        )
        action_desc = f"create_subproject under {target}"
    elif action == 'add_tasks':
        task_lines = [
            line.lstrip('- ').lstrip('* ').lstrip('[ ] ').lstrip('[x] ').strip()
            for line in content.splitlines()
            if re.match(r'^\s*[-*]\s+\[[ x]\]', line) or re.match(r'^\s*[-*]\s+', line)
        ]
        task_lines = [t for t in task_lines if t]
        for task in task_lines:
            forge_capture.write_project_task(
                {"target": target, "folder": "Projects", "title": task},
                projects,
                areas,
            )
        target_filepath = forge_capture.find_project_file(target) if task_lines else None
        action_desc = f"add_tasks to {target} ({len(task_lines)} tasks)"
    else:
        # append_note (default)
        target_filepath = _resolve_target_path(target, areas)
        forge_capture.upsert_section(target_filepath, f"## Note: {stem}", content)
        action_desc = f"append_note in {target}"

    return action_desc, target_filepath


def process_ingress() -> list[str]:
    """
    Scan Ingress/, process each file, return list of log lines.
    """
    # Git pull first, non-fatal
    subprocess.run(
        ['git', 'pull', '--rebase'],
        cwd=str(VAULT),
        check=False,
        capture_output=True,
        text=True
    )

    INGRESS_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    NEEDS_REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    # Immediate .md children only (not in subdirectories)
    md_files = [f for f in INGRESS_DIR.iterdir() if f.is_file() and f.suffix == '.md']

    if not md_files:
        return []

    projects, areas = forge_capture.get_vault_context()
    log_lines = []

    for filepath in md_files:
        try:
            content = filepath.read_text(encoding='utf-8')
            target, method = detect_target(filepath, projects, areas)

            if target:
                action_desc, _ = route_content(filepath, content, target, projects, areas)
                shutil.move(str(filepath), str(INGRESS_PROCESSED_DIR / filepath.name))
                log_line = (
                    f"✅ Processed `{filepath.name}` → {action_desc} (target via {method})\n"
                    f"   ➡️ Moved to Ingress/Processed/"
                )
                log_lines.append(log_line)
            else:
                # Capture inference reason for review file
                reason = "No confident target could be determined."
                try:
                    all_targets = projects + areas
                    prompt = (
                        f"Available projects and areas: {', '.join(all_targets)}\n\n"
                        f"File name: {filepath.name}\n\n"
                        f"File content:\n{content[:2000]}\n\n"
                        "What did you try? Return JSON with inferred_target (string or null), confidence, reason."
                    )
                    raw = forge_capture.call_claude(
                        "You are a second brain file router.",
                        prompt,
                        max_tokens=150
                    )
                    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
                    if json_match:
                        result = json.loads(json_match.group(0))
                        inferred = result.get('inferred_target') or result.get('target')
                        confidence = result.get('confidence', 'low')
                        reason = result.get('reason', reason)
                        review_content = (
                            f"# Review Needed: {filepath.name}\n\n"
                            f"**Inferred target:** {inferred or 'None'}\n"
                            f"**Confidence:** {confidence}\n"
                            f"**Reason:** {reason}\n\n"
                            f"## Original Content\n\n{content}"
                        )
                    else:
                        review_content = (
                            f"# Review Needed: {filepath.name}\n\n"
                            f"**Reason:** {reason}\n\n"
                            f"## Original Content\n\n{content}"
                        )
                except Exception:
                    review_content = (
                        f"# Review Needed: {filepath.name}\n\n"
                        f"**Reason:** {reason}\n\n"
                        f"## Original Content\n\n{content}"
                    )

                shutil.move(str(filepath), str(NEEDS_REVIEW_DIR / filepath.name))
                review_file = NEEDS_REVIEW_DIR / f"{filepath.stem}_review.md"
                review_file.write_text(review_content, encoding='utf-8')
                log_line = (
                    f"⚠️ Could not process `{filepath.name}` — {reason}\n"
                    f"   ➡️ Moved to Ingress/Needs Review/"
                )
                log_lines.append(log_line)

        except Exception as e:
            # Log the full traceback — previously this was discarded, which is
            # how the route_content signature bug stayed hidden for so long.
            logger.exception(f"Error processing ingress file {filepath.name}")
            log_lines.append(f"❌ Error processing `{filepath.name}` — {e}")
            continue

    if log_lines:
        append_forge_log(log_lines)
        git_commit_all(f"Ingress: processed {len(md_files)} file(s)")

    return log_lines


def git_commit_all(message: str) -> None:
    try:
        subprocess.run(['git', 'pull', '--rebase'], cwd=str(VAULT), check=False, capture_output=True, text=True)
        subprocess.run(['git', 'add', '-A'], cwd=str(VAULT), check=True, capture_output=True, text=True)
        subprocess.run(['git', 'commit', '-m', message], cwd=str(VAULT), check=True, capture_output=True, text=True)
        subprocess.run(['git', 'push'], cwd=str(VAULT), check=False, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        pass


def append_forge_log(log_lines: list[str]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    section = f"\n## {now}\n" + "\n".join(f"- {line}" for line in log_lines) + "\n"
    if not FORGE_LOG.exists():
        FORGE_LOG.write_text(f"# Forge Log\n{section}", encoding="utf-8")
    else:
        with open(FORGE_LOG, "a", encoding="utf-8") as f:
            f.write(section)
