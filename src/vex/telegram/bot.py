"""Telegram bot interface for Vex — chat with your agent via Telegram."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from vex.agent.conversation import Conversation
from vex.agent.definition import AgentDefinition
from vex.agent.loop import AgentLoop, ToolCallEvent
from vex.agent.registry import AgentRegistry
from vex.agent.strategy import StrategyAdvisor
from vex.audit.log import AuditLog
from vex.config.loader import load_config
from vex.debug.mode import DebugMode
from vex.llm.base import Message, StreamEvent
from vex.llm.factory import create_llm_client
from vex.metrics.analyzer import MetricsAnalyzer
from vex.metrics.collector import MetricsCollector
from vex.safety.conflict import ConflictDetector
from vex.security.sanitizer import redact_secrets, sanitize
from vex.chat.history import ChatHistory, EmbeddingClient
from vex.tools.agent_ask import AgentAskTool
from vex.tools.agent_create import AgentCreateTool
from vex.tools.agent_delegate import AgentDelegateTool
from vex.tools.browser import BrowserTool
from vex.tools.chat_history import ChatHistoryTool
from vex.tools.file_batch import FileBatchTool
from vex.tools.file_diff import FileDiffTool
from vex.tools.file_edit import FileEditTool
from vex.tools.file_read import FileReadTool
from vex.tools.file_write import FileWriteTool
from vex.tools.glob_tool import GlobTool
from vex.tools.grep_tool import GrepTool
from vex.tools.memory import MemoryStore, MemoryTool
from vex.tools.middleware import (
    DryRunMiddleware,
    RetryMiddleware,
    TimeoutMiddleware,
    ToolExecutor,
)
from vex.tools.registry import ToolRegistry
from vex.tools.shell import ShellTool
from vex.tools.personality_tool import PersonalityTool
from vex.tools.user_profile_tool import UserProfileTool
from vex.tools.web_fetch import WebFetchTool
from vex.tools.web_search import WebSearchTool
from vex.tools.net_broadcast import NetBroadcastTool
from vex.tools.net_constitution import NetConstitutionTool
from vex.tools.net_discover import NetDiscoverTool
from vex.tools.net_group import NetGroupTool
from vex.tools.net_jobs import NetJobsTool
from vex.tools.net_peers import NetPeersTool
from vex.tools.net_request import NetRequestTool
from vex.tools.net_wiki import NetWikiTool
from vex.personality.traits import PersonalityManager
from vex.personality.user_profile import UserProfileStore
from vex.personality.extractor import FactExtractor
from vex.personality.curiosity import CuriosityEngine

logger = logging.getLogger(__name__)

# Per-chat state
_chat_conversations: dict[int, Conversation] = {}
_chat_agents: dict[int, AgentLoop] = {}

# Shared state (initialized in run_bot)
_shared: dict[str, Any] = {}


# ──────────────── Group conversation monitor ────────────────


@dataclass
class GroupMonitor:
    """Tracks group conversation and decides when Vex should chime in.

    Messages are persisted via ChatHistory (JSONL + vector embeddings).
    The in-memory buffer is a lightweight recent window for eval decisions.
    """
    chat_id: int = 0
    chat_title: str = ""
    messages_since_eval: int = 0
    last_interjection: float = 0.0
    eval_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Tuning knobs
    MIN_MESSAGES_BEFORE_EVAL: int = 5
    MIN_INTERJECTION_GAP: float = 120.0

    # Recent window (for building eval transcripts without disk reads)
    _recent: list[tuple[str, str, float]] = field(default_factory=list)
    _MAX_RECENT: int = 50

    async def add(self, sender: str, text: str) -> None:
        """Add a message to the monitor and persist to ChatHistory."""
        self._recent.append((sender, text, time.time()))
        if len(self._recent) > self._MAX_RECENT:
            self._recent = self._recent[-self._MAX_RECENT:]
        self.messages_since_eval += 1

        # Persist to ChatHistory (with embedding generation)
        history: ChatHistory | None = _shared.get("chat_history")
        if history:
            await history.add_message(
                chat_id=self.chat_id,
                sender=sender,
                text=text,
                chat_title=self.chat_title,
            )

    def should_evaluate(self) -> bool:
        if self.messages_since_eval < self.MIN_MESSAGES_BEFORE_EVAL:
            return False
        if time.time() - self.last_interjection < self.MIN_INTERJECTION_GAP:
            return False
        return True

    def get_recent_transcript(self, max_messages: int = 30) -> str:
        recent = self._recent[-max_messages:]
        lines = [f"{sender}: {text}" for sender, text, _ in recent]
        return "\n".join(lines)

    def mark_evaluated(self) -> None:
        self.messages_since_eval = 0

    def mark_interjected(self) -> None:
        self.last_interjection = time.time()


# Per-group monitors
_group_monitors: dict[int, GroupMonitor] = {}

_EVAL_SYSTEM_PROMPT = """\
You are Vex, an AI assistant participating in a group chat. You are monitoring the conversation \
passively. Your job is to decide whether you should interject with something helpful or interesting.

IMPORTANT: You have access to tools including web search, file reading, code execution, and more. \
So even if a question requires looking something up (weather, prices, facts, current events), \
you CAN help — just decide whether you SHOULD.

You SHOULD interject when:
1. Someone stated something factually incorrect — offer a friendly correction
2. The group is stuck on a problem or question — offer a concrete solution
3. Someone asked or wondered about something and nobody answered — provide the answer
4. Someone is curious about something (e.g. "I wonder...", "what would...", "how does...") — \
you can look it up for them
5. You can add genuinely interesting or useful context to the topic being discussed

Do NOT interject when:
- People are just greeting each other or making small talk with no substance
- Someone expressed a pure opinion with no factual component
- Your input would be unwanted "well actually" energy
- The conversation just started and there's nothing to add yet

Respond with EXACTLY this JSON format, nothing else:
{"should_respond": false, "reason": "brief reason"}
or
{"should_respond": true, "reason": "brief reason", "task": "what you need to do to respond helpfully"}

The "task" field should describe what you'd do (e.g. "look up current weather in Nacogdoches, TX \
and share it"), NOT the final message itself — you'll get to use your tools to do the actual work.\
"""


async def _evaluate_group_conversation(chat_id: int, chat: Any) -> None:
    """Evaluate whether Vex should chime in on a group conversation."""
    monitor = _group_monitors.get(chat_id)
    if not monitor:
        return

    async with monitor.eval_lock:
        # Double-check after acquiring lock
        if not monitor.should_evaluate():
            return

        transcript = monitor.get_recent_transcript()
        monitor.mark_evaluated()

    # Ask the LLM (lightweight, no tools)
    llm = _shared.get("llm")
    if not llm:
        return

    logger.info("Evaluating group conversation for chat %d (%d messages in buffer)",
                chat_id, len(monitor._recent))

    try:
        messages = [
            Message(role="system", content=_EVAL_SYSTEM_PROMPT),
            Message(role="user", content=f"Here is the recent group conversation:\n\n{transcript}"),
        ]
        response = await llm.chat(messages)
        result_text = (response.content or "").strip()
        logger.info("Group eval raw LLM response: %s", result_text[:500])

        # Parse the JSON response
        import json
        try:
            result = json.loads(result_text)
        except json.JSONDecodeError:
            # Try to extract JSON from the response
            start = result_text.find("{")
            end = result_text.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(result_text[start:end])
            else:
                logger.warning("Group eval returned non-JSON: %s", result_text[:500])
                return

        if result.get("should_respond"):
            task = result.get("task") or result.get("message", "")
            reason = result.get("reason", "")
            logger.info("Vex interjecting in chat %d — reason: %s, task: %s",
                        chat_id, reason, task)

            # Run the task through the full agent loop (with tools)
            bot_message = await _run_group_interjection(chat_id, task, transcript)

            if bot_message:
                # Split long messages
                for chunk in _split_message(bot_message):
                    await chat.send_message(chunk)
                monitor.mark_interjected()
                await monitor.add("Vex", bot_message)
        else:
            logger.info("Group eval for chat %d: staying silent — %s",
                        chat_id, result.get("reason", ""))

    except Exception as e:
        logger.warning("Group conversation eval failed for chat %d: %s", chat_id, e, exc_info=True)


async def _run_group_interjection(chat_id: int, task: str, transcript: str) -> str | None:
    """Run a task through the full agent loop for a group interjection.

    This gives Vex access to all tools (web search, etc.) to produce
    a helpful response, rather than relying on the LLM's static knowledge.
    """
    try:
        agent = _get_agent(chat_id)
        conversation = Conversation()  # Fresh conversation for the interjection

        # Give the agent context about the group chat + what to do
        prompt = (
            f"You are participating in a group chat. Here is the recent conversation:\n\n"
            f"{transcript}\n\n"
            f"---\n"
            f"Task: {task}\n\n"
            f"Write a short, casual response to share in the group chat. "
            f"Use your tools if you need to look something up. "
            f"Keep it brief and natural — you're a helpful friend in the chat, not a formal assistant."
        )

        text_parts: list[str] = []
        async for event in agent.run(prompt, conversation):
            if isinstance(event, StreamEvent) and event.text_delta:
                text_parts.append(event.text_delta)

        response = redact_secrets(_strip_markdown("".join(text_parts).strip()))
        return response if response else None

    except Exception as e:
        logger.warning("Group interjection agent failed for chat %d: %s", chat_id, e)
        return None


def _get_conversation(
    chat_id: int, user_id: int | None = None, user_name: str | None = None
) -> Conversation:
    if chat_id not in _chat_conversations:
        _chat_conversations[chat_id] = Conversation()
    conv = _chat_conversations[chat_id]
    if user_id:
        conv.user_id = user_id
    if user_name:
        conv.user_name = user_name
    return conv


def _get_agent(chat_id: int) -> AgentLoop:
    if chat_id not in _chat_agents:
        _chat_agents[chat_id] = _create_agent()
    return _chat_agents[chat_id]


def _create_agent() -> AgentLoop:
    # Build prompt enhancers list
    enhancers: list[Any] = []
    if personality := _shared.get("personality_manager"):
        enhancers.append(personality)
    if vexnet_enhancer := _shared.get("vexnet_enhancer"):
        enhancers.append(vexnet_enhancer)

    return AgentLoop(
        definition=_shared["agent_def"],
        llm=_shared["llm"],
        tool_registry=_shared["tool_registry"],
        approval_callback=_auto_approve,
        audit_log=_shared["audit_log"],
        tool_executor=_shared["tool_executor"],
        metrics_collector=_shared["metrics_collector"],
        conflict_detector=_shared.get("conflict_detector"),
        debug_mode=_shared.get("debug_mode"),
        strategy_advisor=_shared.get("strategy_advisor"),
        prompt_enhancers=enhancers,
    )


def _inject_user_enhancers(
    agent: AgentLoop, user_id: int, chat_id: int, user_text: str, is_dm: bool
) -> None:
    """Add per-user prompt enhancers to the agent for this call."""
    # Remove any previous per-user enhancers (they're callables, not managers)
    agent._prompt_enhancers = [
        e for e in agent._prompt_enhancers if not callable(e) or hasattr(e, "enhance_prompt")
    ]

    profiles: UserProfileStore | None = _shared.get("user_profiles")
    curiosity: CuriosityEngine | None = _shared.get("curiosity_engine")

    if not profiles:
        return

    def _user_context_enhancer(system_prompt: str, conversation: Any) -> str:
        """Inject user profile, chat context, and curiosity hints into system prompt."""
        # Always inject chat_id so Vex can query chat_history
        system_prompt = (
            f"{system_prompt}\n\n"
            f"## Current Chat Context\n"
            f"Chat ID: {chat_id} (use this with chat_history tool)\n"
            f"User ID: {user_id}\n"
            f"Chat type: {'DM' if is_dm else 'group'}"
        )

        section = profiles.build_prompt_section(user_id)
        if section:
            system_prompt = f"{system_prompt}\n\n{section}"

        if is_dm and curiosity and curiosity.should_ask_question(user_id, user_text, is_dm):
            hint = curiosity.generate_question_hint(user_id)
            if hint:
                system_prompt = f"{system_prompt}\n{hint}"

        return system_prompt

    agent._prompt_enhancers.append(_user_context_enhancer)


async def _auto_approve(tool_call: Any, schema: Any) -> bool:
    """Auto-approve in Telegram mode (no interactive prompt available).

    For safety, destructive tools are denied by default.
    Use autonomy level 3 to override, or set allowed_users.
    """
    from vex.tools.base import RiskTier

    if schema and schema.risk_tier >= RiskTier.DESTRUCTIVE:
        return False
    return True


def _is_authorized(chat_id: int, chat_type: str) -> bool:
    """Check if a chat is authorized to use the bot."""
    allowed_users = _shared.get("allowed_users")
    allowed_groups = _shared.get("allowed_groups")

    if chat_type == "private":
        # DM: check allowed_users (empty = allow all)
        if not allowed_users:
            return True
        return chat_id in allowed_users
    else:
        # Group/supergroup: check allowed_groups (empty = deny all)
        if not allowed_groups:
            return False
        return chat_id in allowed_groups


def _is_bot_addressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """In group chats, check if the bot is being addressed.

    Returns the cleaned message text if addressed, None otherwise.
    The bot responds when:
    - Message is a direct reply to one of the bot's messages
    - Message mentions the bot by @username
    - Message starts with the bot's name (case-insensitive)
    """
    message = update.message
    text = message.text or ""

    # Always respond in private chats
    if update.effective_chat.type == "private":
        return text

    # Reply to bot's own message
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == context.bot.id:
            return text

    # @mention
    bot_username = context.bot.username
    if bot_username:
        mention = f"@{bot_username}"
        if mention.lower() in text.lower():
            # Strip the mention from the message
            cleaned = text.replace(mention, "").replace(mention.lower(), "").strip()
            return cleaned or text

    # Name prefix (e.g. "Vex do something")
    bot_name = _shared.get("bot_name", "Vex")
    if text.lower().startswith(bot_name.lower()):
        rest = text[len(bot_name):].lstrip(" ,:")
        if rest:
            return rest

    return None


def _escape(text: str) -> str:
    """Escape HTML for Telegram."""
    return html.escape(text)


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting so Telegram shows clean plain text."""
    # Remove code blocks (``` ... ```)
    text = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).strip("`").strip(), text)
    # Remove inline code (` ... `)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove bold (**text** or __text__)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # Remove italic (*text* or _text_) — careful not to hit underscores in words
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"\1", text)
    # Remove headers (# Header)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove link syntax [text](url) → text (url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    # Remove image syntax ![alt](url) → alt
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    # Remove horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    # Clean up bullet points (- item → • item)
    text = re.sub(r"^[-*+]\s+", "• ", text, flags=re.MULTILINE)
    return text.strip()


def _format_tool_event(event: ToolCallEvent) -> str:
    """Format a tool call event for Telegram display."""
    tc = event.tool_call
    schema = event.schema

    if event.result is None:
        # Tool call starting
        risk_label = schema.risk_tier.name if schema else "UNKNOWN"
        return f"🔧 <b>{_escape(tc.name)}</b> [{risk_label}]"
    else:
        # Tool call completed
        result = event.result
        if result.is_error:
            return f"❌ {_escape(tc.name)}: {_escape(result.error or 'Error')}"
        else:
            output = result.output or "OK"
            if len(output) > 200:
                output = output[:200] + "..."
            return f"✅ {_escape(tc.name)}: {_escape(output)}"


# ──────────────── Telegram handlers ────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    if not _is_authorized(chat_id, chat_type):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return

    await update.message.reply_html(
        "👋 <b>Vex</b> — Autonomous AI Agent\n\n"
        "Send me a message and I'll work on it. I can read/write files, "
        "run commands, search the web, and create sub-agents.\n\n"
        "<b>Commands:</b>\n"
        "/clear — Reset conversation\n"
        "/tools — List available tools\n"
        "/agents — List registered agents\n"
        "/autonomy [0-3] — Set autonomy level\n"
        "/metrics — Show performance stats\n"
        "/status — Show current config"
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear command."""
    chat_id = update.effective_chat.id
    if not _is_authorized(chat_id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return
    if chat_id in _chat_conversations:
        _chat_conversations[chat_id].clear()
    if chat_id in _chat_agents:
        del _chat_agents[chat_id]
    await update.message.reply_text("🗑 Conversation cleared.")


async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tools command."""
    if not _is_authorized(update.effective_chat.id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return
    registry: ToolRegistry = _shared["tool_registry"]
    tools = registry.list_all()
    lines = [f"🔧 <b>{_escape(t.name)}</b> [{t.risk_tier.name}] — {_escape(t.description)}" for t in tools]
    text = "\n".join(lines) if lines else "No tools registered."
    # Split if too long for Telegram (4096 char limit)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await update.message.reply_html(text)


async def cmd_agents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /agents command."""
    if not _is_authorized(update.effective_chat.id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return
    registry: AgentRegistry = _shared["agent_registry"]
    agents = registry.list_all()
    lines = [
        f"🤖 <b>{_escape(a.agent_id)}</b> ({_escape(a.display_name)}) autonomy={a.autonomy_level}"
        for a in agents
    ]
    await update.message.reply_html("\n".join(lines) or "No agents registered.")


async def cmd_autonomy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /autonomy command."""
    if not _is_authorized(update.effective_chat.id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return
    args = context.args
    agent_def: AgentDefinition = _shared["agent_def"]

    if not args:
        await update.message.reply_text(f"Current autonomy level: {agent_def.autonomy_level}")
        return

    try:
        level = int(args[0])
        if not 0 <= level <= 3:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Autonomy level must be 0-3.")
        return

    new_def = AgentDefinition(
        agent_id=agent_def.agent_id,
        display_name=agent_def.display_name,
        system_prompt=agent_def.system_prompt,
        autonomy_level=level,
        max_tool_rounds=agent_def.max_tool_rounds,
        workspace_root=agent_def.workspace_root,
        dry_run=agent_def.dry_run,
    )
    _shared["agent_def"] = new_def
    _shared["agent_registry"].register(new_def)
    # Reset all chat agents to pick up new definition
    _chat_agents.clear()
    await update.message.reply_text(f"Autonomy level set to {level}.")


async def cmd_metrics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /metrics command."""
    if not _is_authorized(update.effective_chat.id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return
    collector: MetricsCollector = _shared["metrics_collector"]
    stats = collector.get_tool_stats()
    if stats["total"] == 0:
        await update.message.reply_text("No metrics collected yet.")
        return

    text = (
        f"📊 <b>Tool Metrics</b>\n"
        f"Total calls: {stats['total']}\n"
        f"Success rate: {stats['success_rate']:.0%}\n"
        f"Avg duration: {stats['avg_duration_s']:.2f}s\n"
        f"Errors: {stats['error_count']}"
    )
    await update.message.reply_html(text)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    if not _is_authorized(update.effective_chat.id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return
    agent_def: AgentDefinition = _shared["agent_def"]
    llm_config = _shared.get("llm_config", {})

    text = (
        f"⚙️ <b>Vex Status</b>\n"
        f"Provider: {llm_config.get('provider', 'unknown')}\n"
        f"Model: {llm_config.get('model', 'unknown')}\n"
        f"Autonomy: {agent_def.autonomy_level}\n"
        f"Dry-run: {'yes' if agent_def.dry_run else 'no'}\n"
        f"Workspace: {agent_def.workspace_root}\n"
        f"Active chats: {len(_chat_conversations)}"
    )
    await update.message.reply_html(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages — the main agent interaction."""
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    if not update.message or not update.message.text:
        return

    # Log chat ID for setup purposes
    logger.info("Message from chat_id=%d type=%s title=%s", chat_id, chat_type,
                getattr(update.effective_chat, 'title', None) or 'DM')

    # Check authorization (user for DMs, group for groups)
    if not _is_authorized(chat_id, chat_type):
        # In groups, silently ignore unauthorized chats
        if chat_type != "private":
            return
        await update.message.reply_text("⛔ Not authorized.")
        return

    raw_text = update.message.text

    # Security: check incoming message for prompt injection (non-CLI channels only)
    san_result = await sanitize(raw_text)
    if san_result.is_blocked:
        logger.warning("Blocked message from chat %d: %s", chat_id, san_result.reason)
        await update.message.reply_text("⚠️ Message blocked by security filter.")
        return

    # In group chats, track ALL messages for passive monitoring
    is_group = chat_type != "private"
    if is_group:
        sender = update.message.from_user
        sender_name = sender.first_name if sender else "Unknown"
        if sender and sender.last_name:
            sender_name += f" {sender.last_name}"

        if chat_id not in _group_monitors:
            m = GroupMonitor(
                chat_id=chat_id,
                chat_title=getattr(update.effective_chat, 'title', '') or '',
            )
            m.MIN_MESSAGES_BEFORE_EVAL = _shared.get("monitor_min_messages", 5)
            m.MIN_INTERJECTION_GAP = _shared.get("monitor_interjection_gap", 120.0)
            _group_monitors[chat_id] = m
        monitor = _group_monitors[chat_id]
        await monitor.add(sender_name, raw_text)

    # Check if bot is directly addressed
    user_text = _is_bot_addressed(update, context)
    if user_text is None:
        # Not addressed — but maybe we should chime in?
        if is_group:
            monitor = _group_monitors[chat_id]
            if monitor.should_evaluate():
                # Fire evaluation in background (don't block message processing)
                asyncio.create_task(
                    _evaluate_group_conversation(chat_id, update.effective_chat)
                )
        return

    # Show typing indicator
    await update.effective_chat.send_action(ChatAction.TYPING)

    # Extract user info for profiling
    tg_user = update.message.from_user
    tg_user_id = tg_user.id if tg_user else chat_id
    tg_user_name = tg_user.first_name if tg_user else "Unknown"
    if tg_user and tg_user.last_name:
        tg_user_name += f" {tg_user.last_name}"
    tg_username = tg_user.username if tg_user else None

    # Update user profile (creates on first interaction)
    profiles: UserProfileStore | None = _shared.get("user_profiles")
    if profiles and not is_group:
        profiles.get_or_create(tg_user_id, tg_user_name, tg_username)

    conversation = _get_conversation(chat_id, user_id=tg_user_id, user_name=tg_user_name)
    agent = _get_agent(chat_id)

    # Persist DM messages to chat history (groups already handled by GroupMonitor)
    if not is_group:
        chat_history: ChatHistory | None = _shared.get("chat_history")
        if chat_history:
            await chat_history.add_message(
                chat_id=chat_id,
                sender=tg_user_name,
                text=user_text,
                chat_title=f"DM with {tg_user_name}",
            )

    # Inject per-user context into the agent's prompt enhancers for this call
    _inject_user_enhancers(agent, tg_user_id, chat_id, user_text, is_dm=not is_group)

    # Collect the response — send text progressively between tool rounds
    text_parts: list[str] = []
    all_sent_text: list[str] = []  # Track everything sent for history
    first_tool_seen = False
    tool_start_time = 0.0
    last_progress_time = 0.0
    tools_completed = 0

    async def _flush_text() -> None:
        """Send any accumulated text to the user immediately."""
        nonlocal text_parts
        text = _strip_markdown("".join(text_parts).strip())
        text_parts.clear()
        if text:
            text = redact_secrets(text)
            for chunk in _split_message(text):
                try:
                    await update.message.reply_text(chunk)
                except Exception as e:
                    logger.error("Failed to send message: %s", e)
            all_sent_text.append(text)

    try:
        async for event in agent.run(user_text, conversation):
            if isinstance(event, StreamEvent):
                if event.text_delta:
                    text_parts.append(event.text_delta)
            elif isinstance(event, ToolCallEvent):
                # When a tool starts, flush any text the LLM produced before it
                if event.result is None:
                    pending_text = "".join(text_parts).strip()

                    if not first_tool_seen:
                        first_tool_seen = True
                        tool_start_time = time.time()
                        last_progress_time = tool_start_time
                        # Send the acknowledgement text (or a default)
                        if pending_text:
                            await _flush_text()
                        else:
                            await update.message.reply_text(
                                "On it, let me look into that..."
                            )
                            all_sent_text.append("On it, let me look into that...")
                    elif pending_text:
                        # LLM produced text between tool rounds — send it now
                        await _flush_text()

                # Track completed tools for progress updates
                if event.result is not None:
                    tools_completed += 1
                    now = time.time()
                    if now - last_progress_time > 15 and tools_completed > 1:
                        last_progress_time = now
                        elapsed = int(now - tool_start_time)
                        await update.message.reply_text(
                            f"Still working... ({tools_completed} steps done, {elapsed}s elapsed)"
                        )
                    else:
                        await update.effective_chat.send_action(ChatAction.TYPING)

    except Exception as e:
        logger.exception("Agent error for chat %d", chat_id)
        await update.message.reply_text(f"❌ Error: {_escape(redact_secrets(str(e)))}")
        return

    # Send any remaining text (the final response after all tools are done)
    remaining = _strip_markdown("".join(text_parts).strip())
    if remaining:
        remaining = redact_secrets(remaining)
        for chunk in _split_message(remaining):
            try:
                await update.message.reply_text(chunk)
            except Exception as e:
                logger.error("Failed to send message: %s", e)
                await update.message.reply_text("(message too long to display)")
                break
        all_sent_text.append(remaining)

    # If nothing was ever sent (pure tool work, no text), confirm completion
    response_text = "\n".join(all_sent_text) if all_sent_text else ""
    if not response_text:
        response_text = "Done."
        await update.message.reply_text(response_text)

    # Track Vex's own response in the group monitor for context continuity
    if is_group and chat_id in _group_monitors:
        await _group_monitors[chat_id].add("Vex", response_text)
        _group_monitors[chat_id].mark_interjected()
    elif not is_group:
        # Persist Vex's response to DM chat history
        chat_history_store: ChatHistory | None = _shared.get("chat_history")
        if chat_history_store:
            await chat_history_store.add_message(
                chat_id=chat_id,
                sender="Vex",
                text=response_text,
                chat_title=f"DM with {tg_user_name}",
            )

    # Async fact extraction for DM conversations
    if not is_group:
        extractor: FactExtractor | None = _shared.get("fact_extractor")
        if extractor:
            asyncio.create_task(
                extractor.extract_and_update(tg_user_id, user_text, response_text)
            )


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a message into chunks that fit Telegram's limit."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Try to split at a newline
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


# ──────────────── Bot initialization ────────────────


def _build_shared_state(workspace: str | None = None) -> None:
    """Initialize all shared Vex components."""
    config = load_config()
    llm_config = config.get("llm", {})
    security_config = config.get("security", {})
    audit_config = config.get("audit", {})
    telegram_config = config.get("telegram", {})

    ws = workspace or os.getcwd()

    # LLM
    llm = create_llm_client(llm_config)

    # Audit
    audit_dir = os.path.join(ws, audit_config.get("directory", ".vex/audit"))
    audit_log = AuditLog(directory=audit_dir, enabled=audit_config.get("enabled", True))

    # Memory
    memory_dir = os.path.join(ws, ".vex", "memory")
    memory_store = MemoryStore(memory_dir)

    # Chat history (persistent + vector search)
    chat_history_dir = os.path.join(ws, ".vex", "chat_history")
    ollama_config = llm_config.get("ollama", {})
    embedding_base_url = ollama_config.get("base_url", "http://localhost:11434/v1")
    embedding_model = telegram_config.get("embedding_model", "nomic-embed-text")
    embedding_client = EmbeddingClient(base_url=embedding_base_url, model=embedding_model)
    chat_history = ChatHistory(storage_dir=chat_history_dir, embedding_client=embedding_client)

    # Registries
    agent_registry = AgentRegistry()

    # Metrics & strategy
    metrics_collector = MetricsCollector(ws)
    metrics_analyzer = MetricsAnalyzer(metrics_collector)
    strategy_advisor = StrategyAdvisor(metrics_analyzer)

    # Conflict & debug
    conflict_detector = ConflictDetector()
    debug_mode = DebugMode()
    if config.get("debug", {}).get("enabled"):
        debug_mode.enable()

    # Tool executor
    tool_executor = ToolExecutor()
    tool_executor.add(DryRunMiddleware())
    tool_executor.add(TimeoutMiddleware())
    tool_executor.add(RetryMiddleware())

    # Agent definition
    dry_run = security_config.get("dry_run", False)
    agent_def = AgentDefinition(
        agent_id="default",
        display_name="Vex",
        autonomy_level=security_config.get("autonomy_level", 1),
        max_tool_rounds=security_config.get("max_tool_rounds", 25),
        workspace_root=ws,
        dry_run=dry_run,
    )
    agent_registry.register(agent_def)

    # Delegation (simplified for Telegram — no interactive ask)
    async def delegate_to_agent(agent_id: str, task: str) -> str:
        target_def = agent_registry.get(agent_id)
        if not target_def:
            raise ValueError(f"Agent '{agent_id}' not found.")

        sub_llm = create_llm_client(
            llm_config,
            provider_override=target_def.llm_provider,
            model_override=target_def.llm_model,
        )
        sub_agent = AgentLoop(
            definition=target_def,
            llm=sub_llm,
            tool_registry=tool_registry,
            approval_callback=_auto_approve,
            audit_log=audit_log,
            tool_executor=tool_executor,
            metrics_collector=metrics_collector,
            conflict_detector=conflict_detector,
            debug_mode=debug_mode,
        )
        sub_conversation = Conversation()
        parts: list[str] = []
        async for event in sub_agent.run(task, sub_conversation):
            if isinstance(event, StreamEvent) and event.text_delta:
                parts.append(event.text_delta)
        return "".join(parts) or "Agent completed without response."

    async def ask_user_telegram(question: str) -> str:
        """In Telegram mode, we can't interactively ask — return a notice."""
        return "(User was not available to answer: please proceed with your best judgment)"

    # Build tool registry
    max_depth = security_config.get("max_agent_depth", 3)
    tool_registry = ToolRegistry()
    tool_registry.register(FileReadTool())
    tool_registry.register(GlobTool())
    tool_registry.register(GrepTool())
    tool_registry.register(FileDiffTool())
    tool_registry.register(FileWriteTool())
    tool_registry.register(FileEditTool())
    tool_registry.register(FileBatchTool())
    tool_registry.register(ShellTool())
    tool_registry.register(WebSearchTool())
    tool_registry.register(WebFetchTool())
    tool_registry.register(BrowserTool())
    tool_registry.register(ChatHistoryTool(chat_history))
    tool_registry.register(MemoryTool(memory_store))
    tool_registry.register(AgentCreateTool(agent_registry, max_depth=max_depth))
    tool_registry.register(AgentDelegateTool(delegate_to_agent))
    tool_registry.register(AgentAskTool(ask_user_telegram))
    tool_registry.discover_plugins()

    # Allowed users and groups (Telegram chat IDs)
    allowed_users = telegram_config.get("allowed_users")
    if allowed_users:
        allowed_users = set(int(uid) for uid in allowed_users)

    allowed_groups = telegram_config.get("allowed_groups")
    if allowed_groups:
        allowed_groups = set(int(gid) for gid in allowed_groups)

    bot_name = telegram_config.get("bot_name", "Vex")

    # Group monitor settings
    monitor_config = telegram_config.get("group_monitor", {})
    _shared["monitor_min_messages"] = monitor_config.get("min_messages", 5)
    _shared["monitor_interjection_gap"] = monitor_config.get("interjection_gap_seconds", 120)

    # Personality system
    personality_dir = os.path.join(ws, ".vex", "personality")
    personality_manager = PersonalityManager(personality_dir)
    personality_manager.load()  # Generate birth personality if first run
    logger.info("Personality loaded: %s", personality_manager.load().traits)

    # User profiling
    users_dir = os.path.join(ws, ".vex", "users")
    user_profiles = UserProfileStore(users_dir)

    # Fact extractor & curiosity engine
    fact_extractor = FactExtractor(llm, user_profiles)
    curiosity_engine = CuriosityEngine(personality_manager, user_profiles)

    # Register personality tools
    tool_registry.register(PersonalityTool(personality_manager))
    tool_registry.register(UserProfileTool(user_profiles))

    # VexNet (conditional)
    network_config = config.get("network", {})
    vexnet_client = None

    if network_config.get("enabled", False):
        try:
            from vex.network.client import VexNetClient

            vexnet_client = VexNetClient.from_config(
                network_config, data_dir=os.path.join(ws, ".vex", "network")
            )

            def _get_client():
                return vexnet_client

            tool_registry.register(NetDiscoverTool(_get_client))
            tool_registry.register(NetRequestTool(_get_client))
            tool_registry.register(NetBroadcastTool(_get_client))
            tool_registry.register(NetPeersTool(_get_client))
            tool_registry.register(NetJobsTool(_get_client))
            tool_registry.register(NetWikiTool(_get_client))
            tool_registry.register(NetGroupTool(_get_client))
            tool_registry.register(NetConstitutionTool(_get_client))

            logger.info("VexNet initialized: %s", vexnet_client.identity.display_name)
        except Exception as e:
            logger.warning("Failed to initialize VexNet: %s", e)
            vexnet_client = None

    # VexNet prompt enhancer (injects guide + network status)
    _vexnet_enhancer = None
    if vexnet_client:
        from vex.network.prompt import VexNetPromptEnhancer

        def _get_client_for_enhancer():
            return vexnet_client

        _vexnet_enhancer = VexNetPromptEnhancer(_get_client_for_enhancer)

    _shared.update(
        {
            "llm": llm,
            "llm_config": llm_config,
            "audit_log": audit_log,
            "agent_def": agent_def,
            "agent_registry": agent_registry,
            "tool_registry": tool_registry,
            "tool_executor": tool_executor,
            "metrics_collector": metrics_collector,
            "conflict_detector": conflict_detector,
            "debug_mode": debug_mode,
            "strategy_advisor": strategy_advisor,
            "allowed_users": allowed_users,
            "allowed_groups": allowed_groups,
            "bot_name": bot_name,
            "chat_history": chat_history,
            "personality_manager": personality_manager,
            "user_profiles": user_profiles,
            "fact_extractor": fact_extractor,
            "curiosity_engine": curiosity_engine,
            "vexnet_client": vexnet_client,
            "vexnet_enhancer": _vexnet_enhancer,
        }
    )


async def _proactive_outreach_loop(application: Application) -> None:
    """Periodically check if Vex should proactively reach out to any users."""
    while True:
        await asyncio.sleep(3600)  # Check every hour
        try:
            curiosity: CuriosityEngine | None = _shared.get("curiosity_engine")
            profiles: UserProfileStore | None = _shared.get("user_profiles")
            if not curiosity or not profiles:
                continue

            for profile in profiles.list_all():
                should, opener = await curiosity.should_reach_out(profile.user_id)
                if should and opener:
                    try:
                        await application.bot.send_message(
                            chat_id=profile.user_id, text=opener
                        )
                        profile.last_proactive_outreach = (
                            datetime.now(timezone.utc).isoformat()
                        )
                        profiles.save(profile)
                        logger.info(
                            "Proactive outreach to %s (%d)",
                            profile.display_name, profile.user_id,
                        )
                    except Exception as e:
                        logger.warning(
                            "Proactive outreach failed for %d: %s",
                            profile.user_id, e,
                        )
        except Exception as e:
            logger.warning("Outreach loop error: %s", e)


def run_bot(token: str | None = None, workspace: str | None = None) -> None:
    """Start the Telegram bot.

    Args:
        token: Telegram bot token. Falls back to TELEGRAM_BOT_TOKEN env var
               or config telegram.bot_token.
        workspace: Workspace directory. Falls back to cwd.
    """
    _build_shared_state(workspace)

    if not token:
        config = load_config()
        token = (
            os.environ.get("TELEGRAM_BOT_TOKEN")
            or config.get("telegram", {}).get("bot_token")
        )

    if not token:
        raise ValueError(
            "Telegram bot token required. Set TELEGRAM_BOT_TOKEN env var, "
            "or add [telegram] bot_token to vex.toml."
        )

    app = Application.builder().token(token).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("tools", cmd_tools))
    app.add_handler(CommandHandler("agents", cmd_agents))
    app.add_handler(CommandHandler("autonomy", cmd_autonomy))
    app.add_handler(CommandHandler("metrics", cmd_metrics))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start proactive outreach background task + VexNet
    async def _post_init(application: Application) -> None:
        asyncio.create_task(_proactive_outreach_loop(application))
        # Connect to VexNet server if enabled
        client = _shared.get("vexnet_client")
        if client:
            try:
                await client.connect()
                logger.info("VexNet connected: %s", client.identity.display_name)
            except Exception as e:
                logger.warning("VexNet connection failed: %s", e)

    app.post_init = _post_init

    logger.info("Starting Vex Telegram bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


def main() -> None:
    """Entry point for the vex-telegram CLI command."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Vex Telegram Bot")
    parser.add_argument("--token", help="Telegram bot token")
    parser.add_argument("--workspace", help="Workspace directory (default: cwd)")
    args = parser.parse_args()

    try:
        run_bot(token=args.token, workspace=args.workspace)
    except ValueError as e:
        print(f"Error: {e}", file=__import__("sys").stderr)
        __import__("sys").exit(1)
    except KeyboardInterrupt:
        pass
