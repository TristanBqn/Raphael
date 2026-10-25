"""Lecture des transcripts Claude Code et masquage des secrets.

Réutilisable : le futur second cerveau passera par les mêmes fonctions.
"""
import glob
import json
import os
import re
import sys
from dataclasses import dataclass, field

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cerveau"))
from masque import SYSTEM_BLOCK, mask_secrets  # noqa: E402


@dataclass
class Event:
    role: str          # "user", "assistant" ou "tool_error"
    text: str
    timestamp: str


@dataclass
class Session:
    session_id: str
    project: str
    events: list = field(default_factory=list)
    cwd: str = ""

    @property
    def started(self) -> str:
        return self.events[0].timestamp if self.events else ""


def _project_label(folder: str) -> str:
    # Claude Code nomme le dossier d'un projet d'après son chemin, chaque caractère non alphanumérique devenant « - »
    perso = re.sub(r"[^A-Za-z0-9]", "-", os.path.expanduser("~"))
    label = folder.removeprefix(perso + "-").removeprefix(perso)
    return label or "(dossier personnel)"


def _is_noise(text: str) -> bool:
    t = text.lstrip()
    return (not t or t.startswith("<command-") or t.startswith("<local-command")
            or t.startswith("Caveat:") or t.startswith("[Request interrupted"))


def load_sessions() -> list[Session]:
    sessions = []
    for path in glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl")):
        folder = os.path.basename(os.path.dirname(path))
        session = Session(os.path.splitext(os.path.basename(path))[0], _project_label(folder))
        tool_names = {}
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("isSidechain"):
                    continue
                ts = d.get("timestamp", "")
                if not session.cwd and d.get("cwd"):
                    session.cwd = d["cwd"]
                content = (d.get("message") or {}).get("content")
                if d.get("type") == "assistant" and isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text" and part["text"].strip():
                            session.events.append(Event("assistant", mask_secrets(part["text"].strip()), ts))
                        elif part.get("type") == "tool_use":
                            tool_names[part.get("id")] = part.get("name", "outil")
                elif d.get("type") == "user":
                    parts = [content] if isinstance(content, str) else (content or [])
                    for part in parts:
                        if isinstance(part, str):
                            text = part
                        elif part.get("type") == "text":
                            text = part["text"]
                        elif part.get("type") == "tool_result" and part.get("is_error"):
                            raw = part.get("content")
                            if isinstance(raw, list):
                                raw = " ".join(x.get("text", "") for x in raw if isinstance(x, dict))
                            msg = " ".join(str(raw or "").split())[:200]
                            name = tool_names.get(part.get("tool_use_id"), "outil")
                            session.events.append(Event("tool_error", mask_secrets(f"{name} : {msg}"), ts))
                            continue
                        else:
                            continue
                        text = SYSTEM_BLOCK.sub("", text).strip()
                        if not _is_noise(text):
                            session.events.append(Event("user", mask_secrets(text), ts))
        if any(e.role == "user" for e in session.events):
            sessions.append(session)
    sessions.sort(key=lambda s: s.started)
    return sessions
