"""
P3 — Slack front door for the governed analytics agent.

The non-technical-team endpoint: someone @-mentions the bot (or DMs it) in
Slack, asks a question in plain English, and gets an answer computed through
the governed semantic layer under the read-only role.

The agent's guarantees are unchanged. This file only translates Slack events
into calls to agent.ask(). Every guarantee still holds:
  * one governed tool, fail-closed allowlist (no invented metrics)
  * read-only Snowflake role — the agent cannot see RAW / PII
  * boot cage check (inherited: importing agent.py runs assert_read_only_cage)
  * INPUT guardrail + OUTPUT validator (the governance sandwich)
  * EVERY query audited, attributed to the Slack user who asked

Socket Mode: opens an outbound WebSocket to Slack. No public URL, no hosting,
no ngrok. Runs from your laptop.

--------------------------------------------------------------------------
THREAD-READING (opt-in, OFF by default)  ***read this before enabling***
--------------------------------------------------------------------------
When tagged mid-thread the bot by default sees ONLY the tagging message. Set
SLACK_READ_THREADS=1 to let it also read the earlier messages in that thread and
use them as grounding context.

PRIVACY DISCLOSURE — enabling this sends other people's Slack messages in the
thread to the Anthropic API (they become context in the LLM call). That is a
real data-flow change and must be disclosed to anyone whose messages the bot can
read before you turn it on. It stays OFF unless SLACK_READ_THREADS=1 is set
explicitly, and each threaded answer carries a short "I read this thread" note
(SLACK_THREAD_DISCLOSURE=0 to suppress the note only — not the behaviour).

Extra Slack scopes needed for thread-reading (add in OAuth & Permissions, then
reinstall the app):
    channels:history   (public channels)
    groups:history     (private channels)   — only if used in private channels
    im:history         (DMs; already needed)
    mpim:history       (group DMs)           — only if used in group DMs

Setup (create the app at api.slack.com/apps, then):
    set SLACK_BOT_TOKEN=xoxb-...     (OAuth & Permissions -> Bot User OAuth Token)
    set SLACK_APP_TOKEN=xapp-...     (Socket Mode -> App-Level Token, connections:write)
    set ANTHROPIC_API_KEY=sk-ant-...
    set AGENT_RO_KEY_PASSPHRASE=...
    set SNOWFLAKE_KEY_PASSPHRASE=...
    set SLACK_READ_THREADS=1         (optional; opt in to thread-reading)

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


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


# Thread-reading config (see the PRIVACY DISCLOSURE in the docstring).
READ_THREADS = _truthy(os.environ.get("SLACK_READ_THREADS"))
THREAD_MAX = int(os.environ.get("SLACK_THREAD_MAX", "20"))     # cap messages pulled
THREAD_DISCLOSURE = _truthy(os.environ.get("SLACK_THREAD_DISCLOSURE", "1"))

app = App(token=BOT_TOKEN)
claude = anthropic.Anthropic()          # reads ANTHROPIC_API_KEY

_MENTION_RE = re.compile(r"<@[^>]+>")   # strip the "@bot" from the text

_THREAD_NOTE = ("\n\n_(I read this thread for context. Thread-reading is optional "
                "and can be turned off.)_")


def _thread_context(client, channel: str, thread_ts: str | None,
                    exclude_ts: str | None) -> str:
    """Recent messages in the thread as plain text, for grounding context.

    Returns '' when thread-reading is disabled, there is no thread, or on ANY
    error — reading the thread must never break answering. Excludes the current
    tagging message and system/join messages. Speakers are labelled generically
    (User/Bot); we do NOT resolve names (that would pull more identity than the
    question needs).
    """
    if not READ_THREADS or not thread_ts:
        return ""
    try:
        resp = client.conversations_replies(
            channel=channel, ts=thread_ts, limit=THREAD_MAX)
        msgs = resp.get("messages", [])
    except Exception as e:                       # noqa: BLE001
        print(f"[slack] could not read thread ({e}); answering from the mention only",
              file=sys.stderr)
        return ""

    lines = []
    for m in msgs:
        if m.get("ts") == exclude_ts:            # skip the current tagging msg
            continue
        if m.get("subtype"):                     # skip joins/edits/system noise
            continue
        speaker = "Bot" if m.get("bot_id") else "User"
        text = _MENTION_RE.sub("", m.get("text", "")).strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines[-THREAD_MAX:])


def _answer(question: str, slack_user: str, thread_context: str = "") -> str:
    """Route one Slack question through the governed agent."""
    question = _MENTION_RE.sub("", question).strip()
    if not question:
        return ("Ask me a business question about Petal & Co — e.g. "
                "_how many customers are high risk for churn?_")
    try:
        # slack_user lands in the audit log as team_context: every governed
        # query is attributable to the human who asked it. The thread (if any)
        # is passed as CONTEXT only — the input guardrail still vets `question`.
        answer = ask(claude, question, team_context=f"slack:{slack_user}",
                     context=thread_context)
    except Exception as e:                       # noqa: BLE001 - surface, don't crash the bot
        return f"Sorry — that failed: `{e}`"
    if thread_context and THREAD_DISCLOSURE:
        answer += _THREAD_NOTE
    return answer


@app.event("app_mention")
def handle_mention(event, say, client):
    """Someone @-mentioned the bot in a channel (possibly inside a thread)."""
    thread_ts = event.get("thread_ts") or event.get("ts")
    ctx = _thread_context(client, event.get("channel"),
                          event.get("thread_ts"), event.get("ts"))
    answer = _answer(event.get("text", ""), event.get("user", "unknown"), ctx)
    # Reply in-thread so channels stay tidy.
    say(text=answer, thread_ts=thread_ts)


@app.event("message")
def handle_dm(event, say, client):
    """Direct message to the bot. Ignore its own messages and channel noise."""
    if event.get("channel_type") != "im":
        return
    if event.get("bot_id") or event.get("subtype"):
        return
    ctx = _thread_context(client, event.get("channel"),
                          event.get("thread_ts"), event.get("ts"))
    say(_answer(event.get("text", ""), event.get("user", "unknown"), ctx))


if __name__ == "__main__":
    print("Governed analytics agent is live in Slack (Socket Mode). Ctrl+C to stop.")
    if READ_THREADS:
        print("[slack] THREAD-READING IS ON — earlier thread messages are sent to "
              "the Anthropic API as context. Ensure this is disclosed to users.",
              file=sys.stderr)
    else:
        print("[slack] Thread-reading OFF (bot sees only the tagging message). "
              "Set SLACK_READ_THREADS=1 to enable (reads employee messages — see docstring).")
    SocketModeHandler(app, APP_TOKEN).start()