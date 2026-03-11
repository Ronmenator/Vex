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

from vex.agent.conversation import Conversation, RetrievalConversation
from vex.agent.definition import AgentDefinition
from vex.agent.loop import AgentLoop, ToolCallEvent
from vex.config.loader import load_config
from vex.core import VexCore
from vex.llm.base import Message, StreamEvent
from vex.security.sanitizer import redact_secrets, sanitize
from vex.tools.base import RiskTier
from vex.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Per-chat state
_chat_conversations: dict[int, RetrievalConversation] = {}
_chat_agents: dict[int, AgentLoop] = {}
_chat_cancel_events: dict[int, asyncio.Event] = {}

# Shared engine (initialized in run_bot)
_core: VexCore | None = None


# ──────────────── Group conversation monitor ────────────────


@dataclass
class GroupMonitor:
    """Tracks group conversation and decides when Vex should chime in.

    Messages are persisted via ChatHistory (JSONL + vector embeddings).
    The in-memory buffer is a lightweight recent window for eval decisions.
    """
    chat_id: int = 0
    chat_title: str = ""
    _recent: list[dict[str, str]] = field(default_factory=list)
    _last_eval_count: int = 0
    _last_interjection_time: float = 0.0

    MIN_MESSAGES_BEFORE_EVAL: int = 5
    MIN_INTERJECTION_GAP: float = 120.0
    MAX_BUFFER: int = 50

    async def add(self, sender: str, text: str) -> None:
        """Add a message to the buffer and persist to chat history."""
        self._recent.append({"sender": sender, "text": text})
        if len(self._recent) > self.MAX_BUFFER:
            self._recent = self._recent[-self.MAX_BUFFER:]

        # Persist to ChatHistory (with embeddings)
        if _core:
            try:
                await _core.chat_history.add_message(
                    chat_id=self.chat_id,
                    sender=sender,
                    text=text,
                    chat_title=self.chat_title,
                )
            except Exception as e:
                logger.debug("Failed to persist group message: %s", e)

    def should_evaluate(self) -> bool:
        """Check if we have enough new messages to evaluate."""
        new_since_eval = len(self._recent) - self._last_eval_count
        if new_since_eval < self.MIN_MESSAGES_BEFORE_EVAL:
            return False
        if time.time() - self._last_interjection_time < self.MIN_INTERJECTION_GAP:
            return False
        return True

    def mark_evaluated(self) -> None:
        self._last_eval_count = len(self._recent)

    def mark_interjected(self) -> None:
        self._last_interjection_time = time.time()
        self.mark_evaluated()

    def get_transcript(self, max_messages: int = 30) -> str:
        """Build a readable transcript from recent messages."""
        msgs = self._recent[-max_messages:]
        return "\n".join(f"{m['sender']}: {m['text']}" for m in msgs)


_group_monitors: dict[int, GroupMonitor] = {}

_EVAL_SYSTEM_PROMPT = """\
You are an AI monitoring a group chat to decide whether to chime in.
You should respond with a JSON object:
{"should_respond": true/false, "reason": "...", "task": "what to say or do"}

Respond when:
- Someone asks a question you can help with
- There's a factual error you can correct
- The conversation stalls and you have something valuable to add
- Someone explicitly asks for help or information

Do NOT respond when:
- The conversation is flowing naturally between humans
- Your input wouldn't add value
- You recently interjected (avoid being annoying)
- The topic is purely social/personal between the humans
"""


async def _evaluate_group_conversation(chat_id: int, chat: Any) -> None:
    """Background task: evaluate if Vex should chime in."""
    monitor = _group_monitors.get(chat_id)
    if not monitor or not _core:
        return

    monitor.mark_evaluated()
    transcript = monitor.get_transcript()
    if not transcript.strip():
        return

    llm = _core.llm
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

            bot_message = await _run_group_interjection(chat_id, task, transcript)

            if bot_message:
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
    """Run a task through the full agent loop for a group interjection."""
    try:
        agent = _get_agent(chat_id)
        conversation = Conversation()  # Fresh conversation for the interjection

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
    chat_id: int, user_id: int | None = None, user_name: str | None = None,
    chat_title: str = "",
) -> RetrievalConversation:
    if chat_id not in _chat_conversations:
        _chat_conversations[chat_id] = RetrievalConversation(
            chat_id=chat_id,
            chat_history=_core.chat_history,
            user_name=user_name or "",
            chat_title=chat_title,
        )
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
    return _core.create_agent(
        approval_callback=_auto_approve,
    )


def _inject_user_enhancers(
    agent: AgentLoop, user_id: int, chat_id: int, user_text: str, is_dm: bool
) -> None:
    """Add per-user prompt enhancers to the agent for this call."""
    # Remove any previous per-user enhancers (they're callables, not managers)
    agent._prompt_enhancers = [
        e for e in agent._prompt_enhancers if not callable(e) or hasattr(e, "enhance_prompt")
    ]

    profiles = _core.user_profiles
    curiosity = _core.curiosity_engine

    if not profiles:
        return

    def _user_context_enhancer(system_prompt: str, conversation: Any) -> str:
        """Inject user profile, chat context, and curiosity hints into system prompt."""
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
    """
    if schema and schema.risk_tier >= RiskTier.DESTRUCTIVE:
        return False
    return True


def _is_authorized(chat_id: int, chat_type: str) -> bool:
    """Check if a chat is authorized to use the bot."""
    allowed_users = _core.allowed_users
    allowed_groups = _core.allowed_groups

    if chat_type == "private":
        if not allowed_users:
            return True
        return chat_id in allowed_users
    else:
        if not allowed_groups:
            return False
        return chat_id in allowed_groups


def _is_bot_addressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """In group chats, check if the bot is being addressed."""
    message = update.message
    text = message.text or ""

    if update.effective_chat.type == "private":
        return text

    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == context.bot.id:
            return text

    bot_username = context.bot.username
    if bot_username:
        mention = f"@{bot_username}"
        if mention.lower() in text.lower():
            cleaned = text.replace(mention, "").replace(mention.lower(), "").strip()
            return cleaned or text

    bot_name = _core.telegram_config.get("bot_name", "Vex")
    if text.lower().startswith(bot_name.lower()):
        rest = text[len(bot_name):].lstrip(" ,:")
        if rest:
            return rest

    return None


def _escape(text: str) -> str:
    return html.escape(text)


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting so Telegram shows clean plain text."""
    text = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).strip("`").strip(), text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*+]\s+", "• ", text, flags=re.MULTILINE)
    return text.strip()


def _format_tool_event(event: ToolCallEvent) -> str:
    tc = event.tool_call
    schema = event.schema

    if event.result is None:
        risk_label = schema.risk_tier.name if schema else "UNKNOWN"
        return f"🔧 <b>{_escape(tc.name)}</b> [{risk_label}]"
    else:
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
        "/stop — Stop a running agent\n"
        "/tools — List available tools\n"
        "/agents — List registered agents\n"
        "/autonomy [0-3] — Set autonomy level\n"
        "/metrics — Show performance stats\n"
        "/status — Show current config"
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    if not _is_authorized(update.effective_chat.id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return
    tools = _core.tool_registry.list_all()
    lines = [f"🔧 <b>{_escape(t.name)}</b> [{t.risk_tier.name}] — {_escape(t.description)}" for t in tools]
    text = "\n".join(lines) if lines else "No tools registered."
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await update.message.reply_html(text)


async def cmd_agents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update.effective_chat.id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return
    agents = _core.agent_registry.list_all()
    lines = [
        f"🤖 <b>{_escape(a.agent_id)}</b> ({_escape(a.display_name)}) autonomy={a.autonomy_level}"
        for a in agents
    ]
    await update.message.reply_html("\n".join(lines) or "No agents registered.")


async def cmd_autonomy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update.effective_chat.id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return
    args = context.args

    if not args:
        await update.message.reply_text(f"Current autonomy level: {_core.agent_def.autonomy_level}")
        return

    try:
        level = int(args[0])
        if not 0 <= level <= 3:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Autonomy level must be 0-3.")
        return

    _core.agent_def = AgentDefinition(
        agent_id=_core.agent_def.agent_id,
        display_name=_core.agent_def.display_name,
        system_prompt=_core.agent_def.system_prompt,
        autonomy_level=level,
        max_tool_rounds=_core.agent_def.max_tool_rounds,
        workspace_root=_core.agent_def.workspace_root,
        dry_run=_core.agent_def.dry_run,
    )
    _core.agent_registry.register(_core.agent_def)
    _chat_agents.clear()
    await update.message.reply_text(f"Autonomy level set to {level}.")


async def cmd_metrics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update.effective_chat.id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return
    stats = _core.metrics_collector.get_tool_stats()
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


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not _is_authorized(chat_id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return
    cancel_event = _chat_cancel_events.get(chat_id)
    if cancel_event and not cancel_event.is_set():
        cancel_event.set()
        await update.message.reply_text("🛑 Stopping...")
    else:
        await update.message.reply_text("No agent running.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update.effective_chat.id, update.effective_chat.type):
        await update.message.reply_text("⛔ Not authorized.")
        return

    text = (
        f"⚙️ <b>Vex Status</b>\n"
        f"Provider: {_core.provider}\n"
        f"Model: {_core.model}\n"
        f"Autonomy: {_core.agent_def.autonomy_level}\n"
        f"Dry-run: {'yes' if _core.agent_def.dry_run else 'no'}\n"
        f"Workspace: {_core.agent_def.workspace_root}\n"
        f"Active chats: {len(_chat_conversations)}"
    )
    await update.message.reply_html(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages — the main agent interaction."""
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    if not update.message or not update.message.text:
        return

    logger.info("Message from chat_id=%d type=%s title=%s", chat_id, chat_type,
                getattr(update.effective_chat, 'title', None) or 'DM')

    if not _is_authorized(chat_id, chat_type):
        if chat_type != "private":
            return
        await update.message.reply_text("⛔ Not authorized.")
        return

    raw_text = update.message.text

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
            m.MIN_MESSAGES_BEFORE_EVAL = _core.telegram_config.get(
                "group_monitor", {}
            ).get("min_messages", 5)
            m.MIN_INTERJECTION_GAP = _core.telegram_config.get(
                "group_monitor", {}
            ).get("interjection_gap_seconds", 120.0)
            _group_monitors[chat_id] = m
        monitor = _group_monitors[chat_id]
        await monitor.add(sender_name, raw_text)

    # Check if bot is directly addressed
    user_text = _is_bot_addressed(update, context)
    if user_text is None:
        if is_group:
            monitor = _group_monitors[chat_id]
            if monitor.should_evaluate():
                asyncio.create_task(
                    _evaluate_group_conversation(chat_id, update.effective_chat)
                )
        return

    # Show typing indicator
    await update.effective_chat.send_action(ChatAction.TYPING)

    # Extract user info
    tg_user = update.message.from_user
    tg_user_id = tg_user.id if tg_user else chat_id
    tg_user_name = tg_user.first_name if tg_user else "Unknown"
    if tg_user and tg_user.last_name:
        tg_user_name += f" {tg_user.last_name}"
    tg_username = tg_user.username if tg_user else None

    # Update user profile
    if not is_group:
        _core.user_profiles.get_or_create(tg_user_id, tg_user_name, tg_username)

    chat_title = f"DM with {tg_user_name}" if not is_group else (
        getattr(update.effective_chat, 'title', '') or f"Group {chat_id}"
    )
    conversation = _get_conversation(
        chat_id, user_id=tg_user_id, user_name=tg_user_name, chat_title=chat_title,
    )
    agent = _get_agent(chat_id)

    # Inject per-user context
    _inject_user_enhancers(agent, tg_user_id, chat_id, user_text, is_dm=not is_group)

    # Set up cancellation for this chat
    cancel_event = asyncio.Event()
    _chat_cancel_events[chat_id] = cancel_event

    # Collect the response
    text_parts: list[str] = []
    all_sent_text: list[str] = []
    first_tool_seen = False
    tool_start_time = 0.0
    last_progress_time = 0.0
    tools_completed = 0

    async def _flush_text() -> None:
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
        async for event in agent.run(user_text, conversation, cancel_event=cancel_event):
            if isinstance(event, StreamEvent):
                if event.text_delta:
                    text_parts.append(event.text_delta)
            elif isinstance(event, ToolCallEvent):
                if event.result is None:
                    pending_text = "".join(text_parts).strip()

                    if not first_tool_seen:
                        first_tool_seen = True
                        tool_start_time = time.time()
                        last_progress_time = tool_start_time
                        if pending_text:
                            await _flush_text()
                        else:
                            await update.message.reply_text(
                                "On it, let me look into that..."
                            )
                            all_sent_text.append("On it, let me look into that...")
                    elif pending_text:
                        await _flush_text()

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
        _chat_cancel_events.pop(chat_id, None)
        return
    finally:
        _chat_cancel_events.pop(chat_id, None)

    if cancel_event.is_set() and not text_parts and not all_sent_text:
        await update.message.reply_text("🛑 Stopped.")
        return

    # Send remaining text
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

    response_text = "\n".join(all_sent_text) if all_sent_text else ""
    if not response_text:
        response_text = "Done."
        await update.message.reply_text(response_text)

    # Track Vex's response in group monitor
    if is_group and chat_id in _group_monitors:
        await _group_monitors[chat_id].add("Vex", response_text)
        _group_monitors[chat_id].mark_interjected()

    # Async fact extraction for DM conversations
    if not is_group:
        asyncio.create_task(
            _core.fact_extractor.extract_and_update(tg_user_id, user_text, response_text)
        )


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


# ──────────────── Bot initialization ────────────────


async def _proactive_outreach_loop(application: Application) -> None:
    """Periodically check if Vex should proactively reach out to any users."""
    while True:
        await asyncio.sleep(3600)
        try:
            curiosity = _core.curiosity_engine
            profiles = _core.user_profiles
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
    """Start the Telegram bot."""
    global _core
    _core = VexCore(workspace=workspace or os.getcwd())

    # Set Telegram-specific ask function (non-interactive)
    async def ask_user_telegram(question: str) -> str:
        return "(User was not available to answer: please proceed with your best judgment)"

    _core.set_ask_func(ask_user_telegram)

    if not token:
        token = (
            os.environ.get("TELEGRAM_BOT_TOKEN")
            or _core.telegram_config.get("bot_token")
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
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start proactive outreach background task + VexNet
    async def _post_init(application: Application) -> None:
        asyncio.create_task(_proactive_outreach_loop(application))
        if _core.vexnet_client:
            try:
                await _core.vexnet_client.connect()
                logger.info("VexNet connected: %s", _core.vexnet_client.identity.display_name)
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
