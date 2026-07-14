"""
P3 — Slack front door for the governed analytics agent.

The non-technical-team endpoint: someone @-mentions the bot (or DMs it) in
Slack, asks a question in plain English, and gets an answer computed through
the governed semantic layer under the read-only role.

NOTHING about the agent changes. This file only translates Slack events into
calls to agent.ask(). Every guarantee still holds:
  * one governed tool, fail-closed allowlist (no invented metrics)
  * read-only Snowflake role — the agent cannot see RAW / PII
  * boot cage check (inherited: importing agent.py runs assert_read_only_cage)
  * EVERY query audited, now ATTRIBUTED to the Slack user who asked

Socket Mode: opens an outbound WebSocket to Slack. No public URL, no hosting,
no ngrok. Runs from your laptop.

Setup (create the app at api.slack.com/apps, then):
    set SLACK_BOT_TOKEN=xoxb-...     (OAuth & Permissions -> Bot User OAuth Token)
    set SLACK_APP_TOKEN=xapp-...     (Socket Mode -> App-Level Token, connections:write)
    set ANTHROPIC_API_KEY=sk-ant-...
    set AGENT_RO_KEY_PASSPHRASE=...
    set SNOWFLAKE_KEY_PASSPHRASE=...

Run from the dbt project root:
    python mcp_server/slack_bot.py
"""

from __future__ import annotations
import os
import re
import sys

import anthropic
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Importing agent runs the fail-closed boot cage check. If the read-only cage
# is not in effect, agent.py exits before Slack ever connects.
from agent import ask

BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")

if not BOT_TOKEN or not APP_TOKEN:
    print("[ERROR] Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in this terminal.",
          file=sys.stderr)
    sys.exit(1)

app = App(token=BOT_TOKEN)
claude = anthropic.Anthropic()          # reads ANTHROPIC_API_KEY

_MENTION_RE = re.compile(r"<@[^>]+>")   # strip the "@bot" from the text


def _answer(question: str, slack_user: str) -> str:
    """Route one Slack question through the governed agent."""
    question = _MENTION_RE.sub("", question).strip()
    if not question:
        return ("Ask me a business question about Petal & Co — e.g. "
                "_how many customers are high risk for churn?_")
    try:
        # slack_user lands in the audit log as team_context: every governed
        # query is attributable to the human who asked it.
        return ask(claude, question, team_context=f"slack:{slack_user}")
    except Exception as e:                      # noqa: BLE001 - surface, don't crash the bot
        return f"Sorry — that failed: `{e}`"


@app.event("app_mention")
def handle_mention(event, say):
    """Someone @-mentioned the bot in a channel."""
    answer = _answer(event.get("text", ""), event.get("user", "unknown"))
    # Reply in-thread so channels stay tidy.
    say(text=answer, thread_ts=event.get("thread_ts") or event.get("ts"))


@app.event("message")
def handle_dm(event, say):
    """Direct message to the bot. Ignore its own messages and channel noise."""
    if event.get("channel_type") != "im":
        return
    if event.get("bot_id") or event.get("subtype"):
        return
    say(_answer(event.get("text", ""), event.get("user", "unknown")))


if __name__ == "__main__":
    print("Governed analytics agent is live in Slack (Socket Mode). Ctrl+C to stop.")
    SocketModeHandler(app, APP_TOKEN).start()