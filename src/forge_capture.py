#!/usr/bin/env python3
"""
forge_capture.py — Unified capture and query tool for the second-brain Obsidian vault.

Commands:
  /project <description>   — create a new project note
  /budget  <project>       — research real-world costs and generate a budget table
  /research <topic>        — research a topic with web search and save findings
  /task    <description>   — add a task (high-confidence routing only)
  /query   <question>      — scan vault and answer a question
  /help                    — show this help text
  Default (no slash)       — natural language: auto-detect capture or query
"""

import json
import os
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
import anthropic
import requests

VAULT = Path("C:/second-brain")

RESERVED_WORDS = {"done", "cancel", "quit", "exit", "no", "n", "yes", "y"}

KNOWN_TAGS = ["#shopping", "#3dprint", "#blocked", "#priority", "#someday"]

PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}

PROJECTS_DIR = VAULT / "Projects"
ACTIVE_DIR = VAULT / "Projects" / "Active"
SOMEDAY_DIR = VAULT / "Projects" / "Someday"
AREAS_DIR = VAULT / "Areas"
INBOX_DIR = VAULT / "Inbox"
RESOURCES_DIR = VAULT / "Resources"
INGRESS_DIR = VAULT / "Ingress"
INGRESS_PROCESSED_DIR = VAULT / "Ingress" / "Processed"

QUERY_STARTERS = {
    "what", "who", "when", "where", "why", "how", "show", "list",
    "tell", "find", "do", "is", "are", "can", "which", "give",
}

PURCHASE_VERB_RE = re.compile(
    r"^([-*]\s+(?:[^\s\n]+\s+)*)(Buy|Order|Get|Purchase|Pick up|Grab)\s+",
    re.IGNORECASE,
)

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}

load_dotenv(VAULT / ".env")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------

def detect_mode(thought: str) -> str:
    """Return 'query' or 'capture' based on the input text."""
    stripped = thought.strip()
    if stripped.endswith("?"):
        return "query"
    first_word = stripped.lower().split()[0] if stripped.split() else ""
    if first_word in QUERY_STARTERS:
        return "query"
    return "capture"


# ---------------------------------------------------------------------------
# Vault scanning for query mode
# ---------------------------------------------------------------------------

def scan_vault_for_query(question: str) -> str:
    """Scan vault files for content relevant to the question."""
    lower = question.lower()
    collected = []

    explicit_tags = re.findall(r"#\w+", question)

    implied_tags: list[str] = []
    if "shopping" in lower:
        implied_tags.append("#shopping")
    if "3d print" in lower or "3dprint" in lower:
        implied_tags.append("#3dprint")
    if "blocked" in lower:
        implied_tags.append("#blocked")
    if "someday" in lower or "maybe" in lower:
        implied_tags.append("#someday")
    if "priority" in lower or "urgent" in lower or "important" in lower:
        implied_tags.append("#priority")

    search_tags = list(set(explicit_tags + implied_tags))

    md_files = [
        f for f in VAULT.rglob("*.md")
        if ".obsidian" not in str(f)
    ]

    if search_tags:
        for md_file in md_files:
            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            matching = [
                line for line in text.splitlines()
                if any(tag.lower() in line.lower() for tag in search_tags)
            ]
            if matching:
                rel = md_file.relative_to(VAULT)
                collected.append(f"From {rel}:\n" + "\n".join(f"  {l}" for l in matching))

    if any(w in lower for w in ("project", "active", "working on", "current")):
        project_list = [p.stem for p in PROJECTS_DIR.rglob("*.md")]
        if project_list:
            collected.append("Projects in vault:\n" + "\n".join(f"  - {p}" for p in sorted(project_list)))

    if not collected:
        stopwords = {
            "what", "who", "when", "where", "why", "how", "show", "list", "tell",
            "find", "have", "does", "that", "this", "with", "from", "into", "there",
            "their", "they", "them", "then", "than", "just", "like", "also", "been",
            "were", "would", "could", "should", "which", "while", "about", "after",
            "give", "your", "mine", "some", "many", "much",
        }
        words = [
            w.strip("?.,!") for w in lower.split()
            if len(w.strip("?.,!")) > 3 and w.strip("?.,!") not in stopwords
        ]
        for md_file in md_files[:30]:
            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            matching = [
                l for l in text.splitlines()
                if any(w in l.lower() for w in words) and l.strip()
            ][:5]
            if matching:
                rel = md_file.relative_to(VAULT)
                collected.append(f"From {rel}:\n" + "\n".join(f"  {l}" for l in matching))

    return "\n\n".join(collected)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

CAPTURE_SYSTEM_PROMPT = """\
You are a personal knowledge management assistant for a PARA-style Obsidian vault.
The vault has these folders: Projects/Active/, Projects/Someday/, Projects/Archive/, Areas/, Inbox/, Resources/, Archive/, Daily Notes/
New projects go to Projects/Active/ unless the user says someday/future/maybe/later, in which case use Projects/Someday/.

Given a thought or idea from the user, decide the best way to capture it:

1. **new_project** — a new goal/initiative with a defined outcome
2. **project_task** — a task or note that belongs to an existing project
3. **area_note** — ongoing reference content for an existing area
4. **inbox** — something that doesn't clearly fit anywhere yet

Respond with a JSON object (no markdown fences) with these fields:
- "decision": one of "new_project", "project_task", "area_note", "inbox"
- "target": the project/area name (for project_task or area_note), or a suggested filename stem (for new_project or inbox)
- "folder": for "project_task", either "Projects" or "Areas" — indicates which folder the target note lives in. Omit for other decisions.
- "is_future": true if this is a someday/maybe future project (only relevant for new_project)
- "title": a clean, concise title for the note or task (strip any hashtags — those go in "tags")
- "content": the full markdown content to write (for new_project, omit frontmatter — you'll only write the body sections)
- "task_line": if decision is "project_task", the exact markdown task line to append (e.g. "- [ ] Do the thing")
- "tags": a list of applicable tags for this task. Always include any hashtags the user explicitly wrote. Also suggest additional tags that clearly apply based on context. Only use tags from this known list: #shopping, #3dprint, #blocked, #priority, #someday
- "priority": one of "high", "medium", "low" — assign based on urgency and importance. Default to "medium" if unclear. Tasks that are blocking other work or time-sensitive are "high"; routine or nice-to-have items are "low".
- "confidence": one of "high", "medium", "low" — how confident you are that the target project is the right one. Use "high" only when the project name is an obvious match. Use "medium" if it seems plausible but not certain. Use "low" if you are guessing.
- "explanation": one sentence explaining your decision
"""

QUERY_SYSTEM_PROMPT = """\
You are a personal knowledge management assistant with direct access to the user's second-brain Obsidian vault.
Answer the user's question clearly and concisely using the vault content provided.
Format your answer in clean, readable plain text (use markdown lists or headers if they help).
If the vault content is insufficient to answer fully, say so briefly.
Do not repeat the question back or add unnecessary preamble — just answer.
"""

PROJECT_SYSTEM_PROMPT = """\
You are a personal knowledge management assistant. The user wants to create a new project note.
Generate a clean, useful project note body (no frontmatter — that is added separately).

Respond with a JSON object (no markdown fences) with:
- "title": a clean, concise project title (proper title case, no special chars except hyphens)
- "body": the full markdown body with exactly these sections in order:

  # {title}

  ## Overview
  (1-2 sentence description of the project goal)

  ## Goals

  - (2-3 specific goals)

  ## Tasks

  - [ ]

  ## Notes

  ## Budget

  - [ ] Research and estimate budget

  ## Related

  -

Keep content minimal — just enough to scaffold the note. User will fill in the details.
"""

IDENTIFY_PROJECT_SYSTEM_PROMPT = """\
You are a personal knowledge management assistant. Given a description, identify which existing project it refers to.
Respond with a JSON object (no markdown fences):
- "project": the exact project name from the provided list, or null if no confident match
- "confidence": "high", "medium", or "low"
- "explanation": one sentence
"""

BUDGET_SYSTEM_PROMPT = """\
You are a cost estimator. Use web search to find current prices for the project's components.
Respond with ONLY a markdown table and a total line — no descriptions, no tips, no narrative.

| Item | Low | High |
|------|-----|------|
| ... | $X | $X |

**Total: $X – $X**

Rules:
- Maximum 10 line items
- Item names only — no descriptions or explanations
- Dollar amounts only — no footnotes or commentary
- Nothing else before or after the table and total
"""

RESEARCH_CLASSIFY_SYSTEM_PROMPT = """\
You are a research classifier. Given a topic and a list of existing projects, determine whether this research
belongs to one of those projects or should be saved as a standalone resource.

Respond with a JSON object (no markdown fences):
- "is_project_related": true or false
- "project": exact project name from the list (or null if standalone)
- "title": a clean title for this research (e.g. "FPV Motor Selection" or "Proxmox ZFS Setup")
"""

RESEARCH_SYSTEM_PROMPT = """\
You are a research assistant. Use web search to gather current, accurate information on the topic provided.
Synthesize findings into well-organized markdown. Be concise but thorough — prioritize actionable information.
End with a ## Sources section listing URLs as bullet points.
Return only markdown content (no JSON, no preamble).
"""

PROCESS_SYSTEM_PROMPT = """\
You are a knowledge assistant for a maker and hobbyist project vault.
Summarize the provided content for inclusion in a project note.

Extract and format as clean markdown sections:

## Overview
(1-3 sentence summary of what this is about)

## Parts & Components
(bullet list of any hardware, materials, or components mentioned — omit if none)

## Cost & Budget
(any pricing or budget information — omit section if none found)

## Key Steps & Instructions
(numbered or bulleted steps, techniques, or procedures — omit if not applicable)

## Notes
(any other relevant details: tips, gotchas, compatibility notes, links, etc.)

Rules:
- Omit any section that has no relevant content
- Be concise — this goes into a project note, not a full article
- Keep markdown clean: use ##, -, and numbered lists only
- Do not add preamble or commentary outside the sections
"""


# ---------------------------------------------------------------------------
# Claude API calls
# ---------------------------------------------------------------------------

def call_claude(system: str, prompt: str, max_tokens: int = 1024) -> str:
    """Single-turn Claude call, returns text."""
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def call_claude_json(system: str, prompt: str, max_tokens: int = 1024) -> dict:
    """Single-turn Claude call that parses and returns JSON."""
    return json.loads(call_claude(system, prompt, max_tokens))


def call_claude_with_web_search(system: str, prompt: str, max_tokens: int = 4096) -> str:
    """Call Claude with web_search tool, handling the agentic tool-use loop."""
    messages = [{"role": "user", "content": prompt}]
    tools = [WEB_SEARCH_TOOL]
    text_parts: list[str] = []

    for _ in range(10):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )

        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)

        if response.stop_reason != "tool_use":
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = [
            {"type": "tool_result", "tool_use_id": block.id, "content": ""}
            for block in response.content
            if block.type == "tool_use"
        ]
        messages.append({"role": "user", "content": tool_results})

    return "\n".join(t for t in text_parts if t)


def ask_claude_capture(thought: str, projects: list[str], areas: list[str]) -> dict:
    context = (
        f"Existing projects (folder=Projects): {', '.join(projects) if projects else 'none'}\n"
        f"Existing areas (folder=Areas): {', '.join(areas) if areas else 'none'}\n\n"
        f"User's thought: {thought}"
    )
    return call_claude_json(CAPTURE_SYSTEM_PROMPT, context)


def ask_claude_query(question: str, vault_context: str) -> str:
    if vault_context:
        prompt = f"Vault content relevant to your question:\n\n{vault_context}\n\nQuestion: {question}"
    else:
        prompt = f"Question: {question}\n\n(No relevant vault content was found.)"
    return call_claude(QUERY_SYSTEM_PROMPT, prompt)


def ask_claude_new_project(description: str) -> dict:
    return call_claude_json(PROJECT_SYSTEM_PROMPT, description)


def ask_claude_identify_project(description: str, projects: list[str]) -> dict:
    prompt = f"Projects: {', '.join(projects)}\n\nDescription: {description}"
    return call_claude_json(IDENTIFY_PROJECT_SYSTEM_PROMPT, prompt, max_tokens=256)


def ask_claude_budget(project_name: str, project_content: str) -> str:
    prompt = (
        f"Project: {project_name}\n\n"
        f"Project note:\n{project_content}\n\n"
        "Research current real-world costs for this project and produce a budget table."
    )
    return call_claude_with_web_search(BUDGET_SYSTEM_PROMPT, prompt)


def ask_claude_classify_research(topic: str, projects: list[str]) -> dict:
    prompt = f"Projects: {', '.join(projects) if projects else 'none'}\n\nResearch topic: {topic}"
    return call_claude_json(RESEARCH_CLASSIFY_SYSTEM_PROMPT, prompt, max_tokens=256)


def ask_claude_do_research(topic: str, project_context: str = "") -> str:
    prompt = f"{project_context}\n\nResearch topic: {topic}".strip()
    return call_claude_with_web_search(RESEARCH_SYSTEM_PROMPT, prompt)


def ask_claude_process(content: str) -> str:
    return call_claude(PROCESS_SYSTEM_PROMPT, content, max_tokens=2048)


# ---------------------------------------------------------------------------
# Vault helpers
# ---------------------------------------------------------------------------

def find_project_file(name: str) -> Path | None:
    """Search Active, Someday, and Archive subdirs for a project file by stem."""
    for subdir in (ACTIVE_DIR, SOMEDAY_DIR, VAULT / "Projects" / "Archive"):
        candidate = subdir / f"{name}.md"
        if candidate.exists():
            return candidate
    return None


def get_vault_context() -> tuple[list[str], list[str]]:
    projects = [p.stem for p in PROJECTS_DIR.rglob("*.md")]
    areas = [a.stem for a in AREAS_DIR.glob("*.md")]
    return projects, areas


def build_task_line(result: dict) -> str:
    title = result["title"]
    priority = result.get("priority", "medium")
    tags = result.get("tags", [])
    emoji = PRIORITY_EMOJI.get(priority, "🟡")
    parts = [f"- [ ] {title}", emoji]
    if tags:
        parts.append(" ".join(tags))
    return " ".join(parts)


def build_project_note(title: str, body: str, is_future: bool) -> str:
    status = "someday" if is_future else "active"
    today = date.today().isoformat()
    frontmatter = f'---\ntitle: "{title}"\nstatus: {status}\ntags:\n  - project\ncreated: "{today}"\n---\n\n'
    return frontmatter + body


def upsert_section(filepath: Path, section_header: str, content: str) -> None:
    """Insert or replace a markdown section (## Header) in a file."""
    text = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
    lines = text.splitlines(keepends=True)

    section_start = None
    section_end = None
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            section_start = i
        elif section_start is not None and line.startswith("## ") and i > section_start:
            section_end = i
            break

    new_section_lines = [f"{section_header}\n", "\n"] + [l + "\n" for l in content.strip().splitlines()] + ["\n"]

    if section_start is not None:
        end = section_end if section_end is not None else len(lines)
        lines[section_start:end] = new_section_lines
    else:
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.extend(["\n"] + new_section_lines)

    filepath.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def write_new_project(result: dict) -> Path:
    title = result["title"]
    is_future = result.get("is_future", False)
    body = result.get(
        "content",
        f"# {title}\n\n## Overview\n\n## Goals\n\n-\n\n## Tasks\n\n- [ ]\n\n## Notes\n\n## Budget\n\n- [ ] Research and estimate budget\n\n## Related\n\n-\n",
    )
    note = build_project_note(title, body, is_future)
    dest_dir = SOMEDAY_DIR if is_future else ACTIVE_DIR
    filename = dest_dir / f"{title}.md"
    filename.write_text(note, encoding="utf-8")
    return filename


def write_project_task(result: dict, projects: list[str], areas: list[str]) -> Path:
    target = result["target"]
    folder = result.get("folder", "Projects")
    if folder == "Areas":
        match = next((a for a in areas if a.lower() == target.lower()), target)
        filepath = AREAS_DIR / f"{match}.md"
    else:
        match = next((p for p in projects if p.lower() == target.lower()), target)
        filepath = find_project_file(match) or (ACTIVE_DIR / f"{match}.md")
    task_line = build_task_line(result)

    text = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
    lines = text.splitlines(keepends=True)

    tasks_section = None
    for i, line in enumerate(lines):
        if line.strip() == "## Tasks":
            tasks_section = i
            break

    if tasks_section is None:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"\n{task_line}\n")
        return filepath

    last_task_line = None
    placeholder_line = None
    for i in range(tasks_section + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("- [ ]") or stripped.startswith("- [x]"):
            if stripped == "- [ ]":
                placeholder_line = i
            else:
                last_task_line = i

    if placeholder_line is not None and last_task_line is None:
        lines[placeholder_line] = task_line + "\n"
    elif last_task_line is not None:
        lines.insert(last_task_line + 1, task_line + "\n")
    else:
        lines.insert(tasks_section + 1, task_line + "\n")

    filepath.write_text("".join(lines), encoding="utf-8")
    return filepath


def write_area_note(result: dict, areas: list[str]) -> Path:
    target = result["target"]
    match = next((a for a in areas if a.lower() == target.lower()), target)
    filepath = AREAS_DIR / f"{match}.md"
    content = result.get("content", f"\n## {result['title']}\n\n{result.get('task_line', '')}\n")
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"\n{content}\n")
    return filepath


def write_inbox(result: dict) -> Path:
    title = result["title"]
    today = date.today().isoformat()
    content = result.get("content", title)
    note = f'---\ncreated: "{today}"\ntags:\n  - inbox\n---\n\n# {title}\n\n{content}\n'
    base = INBOX_DIR / f"{title}.md"
    filepath = base
    counter = 1
    while filepath.exists():
        filepath = INBOX_DIR / f"{title} {counter}.md"
        counter += 1
    filepath.write_text(note, encoding="utf-8")
    return filepath


def write_unassigned_task(result: dict) -> Path:
    filepath = INBOX_DIR / "Unassigned Tasks.md"
    task_line = build_task_line(result)
    target = result.get("target", "unknown")
    entry = f"{task_line} (→ {target}?)\n"
    if not filepath.exists():
        filepath.write_text(f"# Unassigned Tasks\n\n{entry}", encoding="utf-8")
    else:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(entry)
    return filepath


def execute_write(result: dict, projects: list[str], areas: list[str]) -> Path:
    decision = result["decision"]
    if decision == "new_project":
        return write_new_project(result)
    elif decision == "project_task":
        return write_project_task(result, projects, areas)
    elif decision == "area_note":
        return write_area_note(result, areas)
    else:
        return write_inbox(result)


# ---------------------------------------------------------------------------
# Display and git helpers
# ---------------------------------------------------------------------------

def strip_purchase_verbs(answer: str) -> str:
    return "\n".join(
        PURCHASE_VERB_RE.sub(r"\1", line) for line in answer.splitlines()
    )


def describe_action(result: dict) -> str:
    decision = result["decision"]
    title = result["title"]
    target = result.get("target", "")
    explanation = result.get("explanation", "")

    if decision == "new_project":
        subfolder = "Someday" if result.get("is_future") else "Active"
        return f"  New project note: Projects/{subfolder}/{title}.md\n  Reason: {explanation}"
    elif decision == "project_task":
        priority = result.get("priority", "medium")
        priority_emoji = PRIORITY_EMOJI.get(priority, "🟡")
        tags = result.get("tags", [])
        tags_str = " ".join(tags) if tags else "(none)"
        confidence = result.get("confidence", "high")
        folder = result.get("folder", "Projects")
        task_line = build_task_line(result)
        return (
            f"  Append task to: {folder}/{target}.md\n"
            f"  Task: {task_line}\n"
            f"  Priority: {priority_emoji} {priority}  |  Tags: {tags_str}  |  Confidence: {confidence}\n"
            f"  Reason: {explanation}"
        )
    elif decision == "area_note":
        return f"  Append to area: Areas/{target}.md\n  Reason: {explanation}"
    else:
        return f"  New inbox note: Inbox/{title}.md\n  Reason: {explanation}"


def build_commit_message(result: dict) -> str:
    decision = result["decision"]
    title = result["title"]
    target = result.get("target", "")
    if decision == "new_project":
        return f"forge: add project {title}"
    elif decision == "project_task":
        return f"forge: add task to {target}"
    elif decision == "area_note":
        return f"forge: update area {target}"
    else:
        return f"forge: add inbox note {title}"


def git_commit(filepath: Path, message: str) -> None:
    try:
        subprocess.run(
            ["git", "add", str(filepath)],
            cwd=str(VAULT), check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(VAULT), check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() if e.stderr else ""
        print(f"  Git commit failed: {stderr or e}")
        return

    try:
        subprocess.run(
            ["git", "push"],
            cwd=str(VAULT), check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError:
        print("  Push failed — run 'git pull --rebase && git push' to sync.")


def confirm(prompt: str = "Write this? [y/N] ") -> bool:
    return input(f"\n{prompt}").strip().lower() == "y"


# ---------------------------------------------------------------------------
# Ingress / process helpers
# ---------------------------------------------------------------------------

URL_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)


def extract_url_from_text(text: str) -> str | None:
    """Return the first HTTP(S) URL found in text, or None."""
    m = URL_RE.search(text)
    return m.group(0) if m else None


def fetch_page_content(url: str) -> str:
    """Fetch a URL and return the main text content, stripping nav/boilerplate."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("beautifulsoup4 is required: pip install beautifulsoup4")

    headers = {"User-Agent": "Mozilla/5.0 (compatible; ForgeCapture/1.0)"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove boilerplate elements
    for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                     "form", "noscript", "iframe", "svg", "figure"]):
        tag.decompose()

    # Try to find the main content area
    main = (
        soup.find("main") or
        soup.find("article") or
        soup.find(id=re.compile(r"(content|main|post|article)", re.I)) or
        soup.find(class_=re.compile(r"(content|main|post|article|entry|body)", re.I)) or
        soup.body
    )
    if main is None:
        main = soup

    lines = []
    for el in main.descendants:
        if not hasattr(el, "name"):
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            text = el.get_text(" ", strip=True)
            if text:
                hashes = "#" * int(el.name[1])
                lines.append(f"\n{hashes} {text}\n")
        elif el.name == "p":
            text = el.get_text(" ", strip=True)
            if text:
                lines.append(text)
        elif el.name in ("li",):
            text = el.get_text(" ", strip=True)
            if text:
                lines.append(f"- {text}")
        elif el.name == "tr":
            cells = [td.get_text(" ", strip=True) for td in el.find_all(["td", "th"])]
            if cells:
                lines.append(" | ".join(cells))

    return "\n".join(lines).strip()


def scan_ingress_files() -> list[Path]:
    """Return files in INGRESS_DIR that are not inside INGRESS_PROCESSED_DIR."""
    if not INGRESS_DIR.exists():
        return []
    return [
        f for f in INGRESS_DIR.iterdir()
        if f.is_file() and INGRESS_PROCESSED_DIR not in f.parents
    ]


# ---------------------------------------------------------------------------
# Slash command handlers
# ---------------------------------------------------------------------------

def cmd_project(arg: str) -> None:
    if not arg:
        print("Usage: /project <description>")
        return

    subfolder_choice = input("Active or someday? [a/s] ").strip().lower()
    is_future = subfolder_choice == "s"
    subfolder = "Someday" if is_future else "Active"

    print(f"\n[/project] Generating project note...", flush=True)
    try:
        result = ask_claude_new_project(arg)
    except Exception as e:
        print(f"Error calling Claude: {e}")
        return

    title = result["title"]
    body = result["body"]
    note = build_project_note(title, body, is_future)

    print(f"\n  File: Projects/{subfolder}/{title}.md")
    print(f"  Status: {'someday' if is_future else 'active'}")
    preview_len = 600
    print(f"\n--- Preview ---\n{note[:preview_len]}{'...' if len(note) > preview_len else ''}\n--- End ---")

    if not confirm():
        print("Skipped.")
        return

    dest_dir = SOMEDAY_DIR if is_future else ACTIVE_DIR
    filepath = dest_dir / f"{title}.md"
    filepath.write_text(note, encoding="utf-8")
    print(f"Written: {filepath}")
    git_commit(filepath, f"forge: add project {title}")
    print(f"Committed: forge: add project {title}")


def cmd_budget(arg: str) -> None:
    if not arg:
        print("Usage: /budget <project name or description>")
        return

    projects, _ = get_vault_context()
    if not projects:
        print("No projects found in vault.")
        return

    print(f"\n[/budget] Identifying project...", flush=True)
    try:
        identified = ask_claude_identify_project(arg, projects)
    except Exception as e:
        print(f"Error calling Claude: {e}")
        return

    project_name = identified.get("project")
    confidence = identified.get("confidence", "low")

    if not project_name or confidence == "low":
        print(f"  Could not confidently identify a project for: {arg!r}")
        print(f"  Known projects: {', '.join(sorted(projects))}")
        return

    filepath = find_project_file(project_name)
    if not filepath:
        print(f"  Project file not found for: {project_name!r}")
        return

    print(f"  Matched: {filepath.relative_to(VAULT)}  (confidence: {confidence})", flush=True)
    print(f"  Researching costs with web search...", flush=True)

    try:
        project_content = filepath.read_text(encoding="utf-8")
        budget_content = ask_claude_budget(project_name, project_content)
    except Exception as e:
        print(f"Error researching budget: {e}")
        return

    print(f"\n--- Budget Preview ---\n{budget_content}\n--- End ---")

    if not confirm(f"Insert ## Budget into {filepath.name}? [y/N] "):
        print("Skipped.")
        return

    upsert_section(filepath, "## Budget", budget_content)
    print(f"Written: {filepath}")
    git_commit(filepath, f"forge: add budget to {project_name}")
    print(f"Committed: forge: add budget to {project_name}")


def cmd_research(arg: str) -> None:
    if not arg:
        print("Usage: /research <topic or question>")
        return

    projects, _ = get_vault_context()

    print(f"\n[/research] Classifying topic...", flush=True)
    try:
        classification = ask_claude_classify_research(arg, projects)
    except Exception as e:
        print(f"Error classifying research: {e}")
        return

    is_project = classification.get("is_project_related", False)
    project_name = classification.get("project")
    title = classification.get("title", arg[:50])

    project_filepath = None
    project_context = ""
    if is_project and project_name:
        project_filepath = find_project_file(project_name)
        if not project_filepath:
            print(f"  Project '{project_name}' not found — saving as standalone resource.")
            is_project = False
        else:
            project_context = f"This research is for the project: {project_name}\n"

    if is_project and project_filepath:
        print(f"  Project: {project_filepath.relative_to(VAULT)}", flush=True)
    else:
        print(f"  Standalone resource: Resources/{title}.md", flush=True)

    print(f"  Researching with web search...", flush=True)
    try:
        content = ask_claude_do_research(arg, project_context)
    except Exception as e:
        print(f"Error researching: {e}")
        return

    preview_len = 800
    print(f"\n--- Research Preview ---\n{content[:preview_len]}{'...' if len(content) > preview_len else ''}\n--- End ---")

    if not confirm():
        print("Skipped.")
        return

    if is_project and project_filepath:
        upsert_section(project_filepath, "## Research", content)
        written = project_filepath
        commit_msg = f"forge: add research to {project_name}"
    else:
        today = date.today().isoformat()
        full_note = f'---\ncreated: "{today}"\ntags:\n  - resource\n---\n\n# {title}\n\n{content}\n'
        written = RESOURCES_DIR / f"{title}.md"
        written.write_text(full_note, encoding="utf-8")
        commit_msg = f"forge: add resource {title}"

    print(f"Written: {written}")
    git_commit(written, commit_msg)
    print(f"Committed: {commit_msg}")


def cmd_task(arg: str) -> None:
    if not arg:
        print("Usage: /task <description>")
        return

    projects, areas = get_vault_context()
    print(f"\n[/task] Thinking...", flush=True)
    try:
        result = ask_claude_capture(arg, projects, areas)
    except Exception as e:
        print(f"Error calling Claude: {e}")
        return

    confidence = result.get("confidence", "high")
    low_confidence = result["decision"] == "project_task" and confidence in ("medium", "low")

    print("\nClaude's plan:")
    print(describe_action(result))
    if low_confidence:
        print(f"  → Low confidence ({confidence}): will route to Inbox/Unassigned Tasks.md")

    if not confirm():
        print("Skipped.")
        return

    try:
        if low_confidence:
            written = write_unassigned_task(result)
            commit_msg = "forge: add task to Inbox/Unassigned Tasks"
        else:
            written = execute_write(result, projects, areas)
            commit_msg = build_commit_message(result)
        print(f"Written: {written}")
        git_commit(written, commit_msg)
        print(f"Committed: {commit_msg}")
    except Exception as e:
        print(f"Error writing file: {e}")


def cmd_query(arg: str) -> None:
    if not arg:
        print("Usage: /query <question>")
        return
    print(f"\n[/query] Scanning vault...", flush=True)
    vault_context = scan_vault_for_query(arg)
    if vault_context:
        print(f"  Found relevant content. Asking Claude...", flush=True)
    else:
        print(f"  No specific vault content found. Asking Claude anyway...", flush=True)
    try:
        answer = ask_claude_query(arg, vault_context)
    except Exception as e:
        print(f"Error calling Claude: {e}")
        return
    print(f"\n{strip_purchase_verbs(answer)}")


def cmd_process(arg: str) -> None:
    # Parse optional inline target: /process → FPV Tiny Whoop
    inline_target: str | None = None
    if "→" in arg:
        _, inline_target = arg.split("→", 1)
        inline_target = inline_target.strip()
    elif arg.strip():
        # Allow /process FPV Tiny Whoop (no arrow) as shorthand
        inline_target = arg.strip()

    # Step 1: Scan Ingress/
    files = scan_ingress_files()
    if not files:
        print("No files found in Ingress/ (excluding Processed/).")
        return

    if len(files) == 1:
        chosen = files[0]
        print(f"\n[/process] Found one file: {chosen.name}")
    else:
        print(f"\n[/process] Files in Ingress/:")
        for i, f in enumerate(files, 1):
            print(f"  {i}. {f.name}")
        raw = input("Process which file? (number or filename) ").strip()
        if raw.isdigit():
            idx = int(raw) - 1
            if not (0 <= idx < len(files)):
                print("Invalid selection.")
                return
            chosen = files[idx]
        else:
            match = next((f for f in files if f.name == raw), None)
            if not match:
                print(f"File not found: {raw!r}")
                return
            chosen = match

    # Step 2: Read file and determine content
    print(f"  Reading {chosen.name}...", flush=True)
    raw_content = chosen.read_text(encoding="utf-8").strip()
    source_title = chosen.stem

    url = extract_url_from_text(raw_content)
    if url:
        print(f"  URL detected: {url}", flush=True)
        print(f"  Fetching page content...", flush=True)
        try:
            page_text = fetch_page_content(url)
            content_to_process = f"Source URL: {url}\n\n{page_text}"
        except Exception as e:
            print(f"  Warning: could not fetch URL ({e}). Using raw file content.")
            content_to_process = raw_content
    else:
        content_to_process = raw_content

    # Step 3: Send to Claude for summarization
    print(f"  Summarizing with Claude...", flush=True)
    try:
        summary = ask_claude_process(content_to_process)
    except Exception as e:
        print(f"Error calling Claude: {e}")
        return

    # Step 4: Show preview and pick target
    preview_len = 800
    print(f"\n--- Summary Preview ---\n{summary[:preview_len]}{'...' if len(summary) > preview_len else ''}\n--- End ---")

    projects, areas = get_vault_context()
    all_targets = projects + areas

    if inline_target:
        target_name = inline_target
        print(f"\n  Target (from command): {target_name!r}")
    else:
        print(f"\nProjects: {', '.join(projects) if projects else '(none)'}")
        print(f"Areas:    {', '.join(areas) if areas else '(none)'}")
        target_name = input("Append to which project or area? ").strip()
        if not target_name:
            print("No target specified. Skipped.")
            return

    # Fuzzy match target name (case-insensitive)
    matched = next(
        (t for t in all_targets if t.lower() == target_name.lower()),
        None
    )
    if matched:
        target_name = matched

    # Resolve filepath
    project_file = find_project_file(target_name)
    area_file = AREAS_DIR / f"{target_name}.md"
    if project_file and project_file.exists():
        target_filepath = project_file
    elif area_file.exists():
        target_filepath = area_file
    else:
        # Default to active project path even if it doesn't exist yet
        target_filepath = ACTIVE_DIR / f"{target_name}.md"
        print(f"  Warning: {target_filepath.relative_to(VAULT)} does not exist — it will be created.")

    if not confirm(f"Append summary to {target_filepath.relative_to(VAULT)}? [y/N] "):
        print("Skipped.")
        return

    # Step 5: Append summary under ## Research: <source title>
    section_header = f"## Research: {source_title}"
    upsert_section(target_filepath, section_header, summary)
    print(f"Written: {target_filepath}")

    # Step 6: Move processed file
    INGRESS_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    dest = INGRESS_PROCESSED_DIR / chosen.name
    shutil.move(str(chosen), str(dest))
    print(f"Moved: {chosen.name} → Ingress/Processed/")

    # Step 7: Commit and push
    commit_msg = f"forge: process ingress {chosen.name} → {target_name}"
    try:
        subprocess.run(
            ["git", "add", str(target_filepath), str(dest)],
            cwd=str(VAULT), check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=str(VAULT), check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"  Git commit failed: {e.stderr.strip() if e.stderr else e}")
        return

    try:
        subprocess.run(
            ["git", "push"],
            cwd=str(VAULT), check=True, capture_output=True, text=True,
        )
        print(f"Committed and pushed: {commit_msg}")
    except subprocess.CalledProcessError:
        print(f"Committed: {commit_msg}")
        print("  Push failed — run 'git pull --rebase && git push' to sync.")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

HELP_TEXT = """\
Forge — second-brain capture and query tool.

Commands:
  /project <description>         create a new project note (prompts: active or someday)
  /budget  <project>             research real-world costs and generate a budget table
  /research <topic>              research a topic with web search and save findings
  /task    <description>         add a task (high-confidence routing, else → Inbox)
  /query   <question>            scan vault and answer a question
  /process [→ <project/area>]    process a file from Ingress/ into a project note
  /help                          show this help text

Default (no slash): type a thought or question — mode is auto-detected.
Type 'quit' or 'exit' to stop.\
"""

SLASH_COMMANDS: dict[str, object] = {
    "/project": cmd_project,
    "/budget": cmd_budget,
    "/research": cmd_research,
    "/task": cmd_task,
    "/query": cmd_query,
    "/process": cmd_process,
}


def main():
    print(HELP_TEXT + "\n")

    while True:
        try:
            thought = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not thought:
            continue
        if thought.lower() in ("quit", "exit"):
            print("Bye.")
            break
        if thought.lower() in ("/help", "help"):
            print(f"\n{HELP_TEXT}\n")
            continue
        if thought.lower() in RESERVED_WORDS:
            print("That doesn't look like input — type your thought, a command, or 'quit'.\n")
            continue

        # Slash command dispatch
        if thought.startswith("/"):
            parts = thought.split(None, 1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            handler = SLASH_COMMANDS.get(cmd)
            if handler:
                handler(arg)
            else:
                print(f"Unknown command: {cmd}. Type /help for available commands.")
            print()
            continue

        # Natural language fallback
        mode = detect_mode(thought)

        if mode == "query":
            cmd_query(thought)
            print()
            continue

        # Capture mode
        projects, areas = get_vault_context()
        print(f"\n[CAPTURE MODE] Thinking...", flush=True)
        try:
            result = ask_claude_capture(thought, projects, areas)
        except Exception as e:
            print(f"Error calling Claude: {e}\n")
            continue

        print("\nClaude's plan:")
        print(describe_action(result))

        if not confirm():
            print("Skipped.\n")
            continue

        try:
            confidence = result.get("confidence", "high")
            if result["decision"] == "project_task" and confidence in ("medium", "low"):
                written = write_unassigned_task(result)
                print(f"Written: {written}")
                git_commit(written, "forge: add task to Inbox/Unassigned Tasks")
                print("Not sure which project — added to Inbox.\n")
            else:
                written = execute_write(result, projects, areas)
                print(f"Written: {written}")
                commit_msg = build_commit_message(result)
                git_commit(written, commit_msg)
                print(f"Committed: {commit_msg}\n")
        except Exception as e:
            print(f"Error writing file: {e}\n")


if __name__ == "__main__":
    main()
