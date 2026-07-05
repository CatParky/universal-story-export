#!/usr/bin/env python3
"""
Claude Chat Extractor — for universal-story-export
===================================================
Extracts a single roleplay chat from a claude.ai data export
(conversations.json) and saves it as .txt or .md.

How to get conversations.json:
  claude.ai -> Settings -> Privacy -> Export data
  You'll receive an email with a download link. Unzip it and
  find conversations.json inside.

Usage:
  python3 claude_export.py conversations.json
  python3 claude_export.py conversations.json --prefix RP
  python3 claude_export.py conversations.json --format txt

The script is interactive: it lists matching chats, you pick one,
it resolves retry branches, and writes the file next to the JSON.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT_UUID = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Stage One — filter chats by name prefix and let the user choose one
# ---------------------------------------------------------------------------

def find_chats(data, prefix):
    """Return (index, chat) pairs whose name starts with the prefix
    (case-insensitive, ignoring leading spaces)."""
    matches = []
    for i, chat in enumerate(data):
        name = (chat.get("name") or "").strip()
        if name.upper().startswith(prefix.upper()):
            matches.append((i, chat))
    return matches


def choose_chat(matches):
    """Show a numbered menu and return the chosen chat."""
    print(f"\nFound {len(matches)} matching chat(s):\n")
    for n, (i, chat) in enumerate(matches, start=1):
        updated = (chat.get("updated_at") or "")[:10]
        count = len(chat.get("chat_messages", []))
        print(f"  {n}. {chat.get('name', '(unnamed)')}  "
              f"[{count} messages, last updated {updated}]")

    while True:
        choice = input("\nEnter the number of the chat to export: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(matches):
            return matches[int(choice) - 1][1]
        print("Please enter a valid number from the list.")


# ---------------------------------------------------------------------------
# Stage Two — extract the messages
#
# Note on pagination: the claude.ai website API serves messages in pages
# of ~100, but the data-export file contains the complete flat list per
# chat, so no pagination handling is required here.
# ---------------------------------------------------------------------------

def resolve_active_thread(messages):
    """
    Retried/edited messages create branches. Every message has a uuid and
    a parent_message_uuid. Alternative retries share the same parent; the
    branch that was KEPT is the one that later messages descend from.

    So: find the most recently created 'leaf' (a message no other message
    points to as parent) and walk backwards up the parent chain to the
    root. That path is the conversation as it appears on screen.
    """
    by_uuid = {m["uuid"]: m for m in messages}
    has_children = {m.get("parent_message_uuid") for m in messages}

    leaves = [m for m in messages if m["uuid"] not in has_children]
    if not leaves:
        return messages  # no branching info; return as-is

    # The active branch ends at the newest leaf
    tip = max(leaves, key=lambda m: m.get("created_at") or "")

    chain = []
    current = tip
    while current is not None:
        chain.append(current)
        parent_id = current.get("parent_message_uuid")
        if parent_id == ROOT_UUID:
            break
        current = by_uuid.get(parent_id)

    chain.reverse()
    return chain


# ---------------------------------------------------------------------------
# Stage Three — format and save
#
# sender is 'human' or 'assistant'. Escape sequences such as \n are
# already converted to real line breaks by json.load(), so the text
# needs no further unescaping.
# ---------------------------------------------------------------------------

def clean_text(text):
    """Remove placeholder blocks the export inserts where thinking or
    tool-use blocks sat in the original chat."""
    import re
    text = re.sub(
        r"```\s*\nThis block is not supported on your current device yet\.\s*\n```\s*\n?",
        "", text)
    return text.strip()


def format_timestamp(iso_string):
    if not iso_string:
        return ""
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M")
    except ValueError:
        return iso_string


def build_markdown(chat, messages):
    lines = [f"# {chat.get('name', 'Conversation with Claude')}\n"]
    for m in messages:
        who = "Human" if m["sender"] == "human" else "Claude"
        ts = format_timestamp(m.get("created_at"))
        header = f"## {who} ({ts}):" if ts else f"## {who}:"
        lines.append(f"{header}\n\n{clean_text(m.get('text', ''))}\n\n---\n")
    return "\n".join(lines)


def build_text(chat, messages):
    lines = [chat.get("name", "Conversation with Claude"),
             "=" * 40, ""]
    for m in messages:
        who = "HUMAN" if m["sender"] == "human" else "CLAUDE"
        ts = format_timestamp(m.get("created_at"))
        lines.append(f"[{who}] {ts}".rstrip())
        lines.append("")
        lines.append(m.get("text", ""))
        lines.append("")
        lines.append("-" * 40)
        lines.append("")
    return "\n".join(lines)


def safe_filename(name):
    keep = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
    return "_".join(keep.split()).lower()[:100] or "claude_conversation"


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract a chat from a claude.ai conversations.json export")
    parser.add_argument("json_file", help="path to conversations.json")
    parser.add_argument("--prefix", default="RP",
                        help="only list chats whose name starts with this "
                             "(default: RP)")
    parser.add_argument("--format", choices=["md", "txt"], default=None,
                        help="output format (if omitted, you'll be asked)")
    args = parser.parse_args()

    json_path = Path(args.json_file)
    if not json_path.exists():
        sys.exit(f"File not found: {json_path}")

    print(f"Reading {json_path.name} ...")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    # Stage One
    matches = find_chats(data, args.prefix)
    if not matches:
        sys.exit(f"No chats found starting with '{args.prefix}'.")
    chat = choose_chat(matches)

    # Stage Two
    all_messages = chat.get("chat_messages", [])
    thread = resolve_active_thread(all_messages)
    skipped = len(all_messages) - len(thread)
    print(f"\n{len(all_messages)} messages in file; "
          f"{len(thread)} on the active thread "
          f"({skipped} abandoned retry/edit branches skipped).")

    # Stage Three
    fmt = args.format
    while fmt not in ("md", "txt"):
        fmt = input("Export as (md/txt)? ").strip().lower()

    content = build_markdown(chat, thread) if fmt == "md" \
        else build_text(chat, thread)

    out_path = Path.cwd() / f"{safe_filename(chat.get('name', ''))}.{fmt}"
    out_path.write_text(content, encoding="utf-8")
    print(f"\nDone! Saved to: {out_path}")


if __name__ == "__main__":
    main()
