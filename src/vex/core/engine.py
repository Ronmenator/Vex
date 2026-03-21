"""VexCore — the shared engine that both CLI and Telegram frontends use.

Consolidates all component initialization that was previously duplicated
between cli/app.py and telegram/bot.py.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable

from vex.agent.conversation import Conversation
from vex.agent.definition import AgentDefinition
from vex.agent.loop import AgentLoop, ApprovalCallback
from vex.agent.registry import AgentRegistry
from vex.agent.strategy import StrategyAdvisor
from vex.audit.log import AuditLog
from vex.chat.history import ChatHistory, EmbeddingClient
from vex.config.loader import load_config
from vex.debug.mode import DebugMode
from vex.llm.base import StreamEvent
from vex.llm.factory import create_llm_client
from vex.metrics.analyzer import MetricsAnalyzer
from vex.metrics.collector import MetricsCollector
from vex.personality.curiosity import CuriosityEngine
from vex.personality.extractor import FactExtractor
from vex.personality.traits import PersonalityManager
from vex.personality.user_profile import UserProfileStore
from vex.safety.conflict import ConflictDetector
from vex.tools.agent_ask import AgentAskTool
from vex.tools.agent_create import AgentCreateTool
from vex.tools.agent_delegate import AgentDelegateTool
from vex.tools.base import ToolSchema
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
    MetricsMiddleware,
    RetryMiddleware,
    TimeoutMiddleware,
    ToolExecutor,
)
from vex.tools.personality_tool import PersonalityTool
from vex.tools.registry import ToolRegistry
from vex.tools.shell import ShellTool
from vex.tools.user_profile_tool import UserProfileTool
from vex.tools.web_fetch import WebFetchTool
from vex.tools.web_search import WebSearchTool
from vex.tools.moltbook import MoltbookTool
from vex.tools.self_improve import SelfImproveTool
from vex.self.rules import RuleStore
from vex.self.enhancer import SelfImprovementEnhancer

logger = logging.getLogger(__name__)


class VexCore:
    """Shared engine that owns all Vex components.

    Both the CLI REPL and the Telegram bot instantiate this once,
    then build thin UI layers on top of it.
    """

    def __init__(self, workspace: str | None = None) -> None:
        self.workspace = workspace or os.getcwd()
        self.config = load_config()

        llm_config = self.config.get("llm", {})
        security_config = self.config.get("security", {})
        audit_config = self.config.get("audit", {})
        telegram_config = self.config.get("telegram", {})
        network_config = self.config.get("network", {})

        self.llm_config = llm_config

        # --- LLM ---
        self.llm = create_llm_client(llm_config)

        # --- Provider / model names (for display) ---
        self.provider = llm_config.get("provider", "anthropic")
        _provider_model = llm_config.get(self.provider, {}).get("model")
        _defaults = {
            "anthropic": "claude-sonnet-4-6",
            "openai": "gpt-4o",
            "ollama": "llama3.2",
        }
        self.model = (
            llm_config.get("model")
            or _provider_model
            or _defaults.get(self.provider, "gpt-4o")
        )

        # --- Audit ---
        audit_dir = os.path.join(
            self.workspace, audit_config.get("directory", ".vex/audit")
        )
        self.audit_log = AuditLog(
            directory=audit_dir,
            enabled=audit_config.get("enabled", True),
        )

        # --- Agent definition ---
        self.dry_run = security_config.get("dry_run", False)
        self.agent_def = AgentDefinition(
            agent_id="default",
            display_name="Vex",
            autonomy_level=security_config.get("autonomy_level", 1),
            max_tool_rounds=security_config.get("max_tool_rounds", 25),
            workspace_root=self.workspace,
            dry_run=self.dry_run,
        )

        # --- Registries ---
        self.agent_registry = AgentRegistry()
        self.agent_registry.register(self.agent_def)

        # --- Debug ---
        self.debug_mode = DebugMode()
        if self.config.get("debug", {}).get("enabled", False):
            self.debug_mode.enable()

        # --- Metrics & strategy ---
        self.metrics_collector = MetricsCollector(self.workspace)
        self.metrics_analyzer = MetricsAnalyzer(self.metrics_collector)
        self.strategy_advisor = StrategyAdvisor(self.metrics_analyzer)

        # --- Conflict detector ---
        self.conflict_detector = ConflictDetector()

        # --- Memory ---
        memory_dir = os.path.join(self.workspace, ".vex", "memory")
        self.memory_store = MemoryStore(memory_dir)

        # --- Self-improvement (bounded Gödel machine) ---
        self_dir = os.path.join(self.workspace, ".vex", "self")
        self.rule_store = RuleStore(self_dir)
        self._self_improvement_enhancer = SelfImprovementEnhancer(self.rule_store)

        # --- Chat history (persistent + vector search) ---
        chat_history_dir = os.path.join(self.workspace, ".vex", "chat_history")
        ollama_config = llm_config.get("ollama", {})
        embedding_base_url = ollama_config.get(
            "base_url", "http://localhost:11434/v1"
        )
        embedding_model = telegram_config.get(
            "embedding_model", "nomic-embed-text"
        )
        self.embedding_client = EmbeddingClient(
            base_url=embedding_base_url, model=embedding_model
        )
        self.chat_history = ChatHistory(
            storage_dir=chat_history_dir,
            embedding_client=self.embedding_client,
        )

        # --- Personality ---
        personality_dir = os.path.join(self.workspace, ".vex", "personality")
        self.personality_manager = PersonalityManager(personality_dir)
        self.personality_manager.load()

        # --- User profiles ---
        users_dir = os.path.join(self.workspace, ".vex", "users")
        self.user_profiles = UserProfileStore(users_dir)

        # --- Fact extractor & curiosity ---
        self.fact_extractor = FactExtractor(self.llm, self.user_profiles)
        self.curiosity_engine = CuriosityEngine(
            self.personality_manager, self.user_profiles
        )

        # --- Tool executor ---
        self.tool_executor = ToolExecutor()
        self.tool_executor.add(DryRunMiddleware())
        self.tool_executor.add(TimeoutMiddleware())
        self.tool_executor.add(RetryMiddleware())
        if self.debug_mode.enabled:
            self.tool_executor.add(MetricsMiddleware())

        # --- VexNet (optional) ---
        self.vexnet_client = None
        self._vexnet_enhancer = None

        if network_config.get("enabled", False):
            try:
                from vex.network.client import VexNetClient

                self.vexnet_client = VexNetClient.from_config(
                    network_config,
                    data_dir=os.path.join(self.workspace, ".vex", "network"),
                )
                logger.info(
                    "VexNet initialized: %s",
                    self.vexnet_client.identity.display_name,
                )
            except Exception as e:
                logger.warning("Failed to initialize VexNet: %s", e)

        if self.vexnet_client:
            from vex.network.prompt import VexNetPromptEnhancer

            self._vexnet_enhancer = VexNetPromptEnhancer(self._get_vexnet_client)

        # --- Moltbook (AI agent social network) ---
        self.moltbook_client = None
        self._moltbook_enhancer = None
        moltbook_config = self.config.get("moltbook", {})

        if moltbook_config.get("enabled", True):
            try:
                from vex.moltbook.client import MoltbookClient

                moltbook_name = moltbook_config.get(
                    "agent_name",
                    network_config.get("display_name", "Vex"),
                )
                moltbook_desc = moltbook_config.get("description")
                self.moltbook_client = MoltbookClient(
                    data_dir=os.path.join(self.workspace, ".vex", "moltbook"),
                    agent_name=moltbook_name,
                    agent_description=moltbook_desc,
                )
                logger.info("Moltbook initialized: %s", moltbook_name)
            except Exception as e:
                logger.warning("Failed to initialize Moltbook: %s", e)

        if self.moltbook_client:
            from vex.moltbook.prompt import MoltbookPromptEnhancer

            self._moltbook_enhancer = MoltbookPromptEnhancer(
                self._get_moltbook_client
            )

        # --- Delegation ---
        self._delegate_func = self._make_delegate_func()
        self._ask_func: Callable[[str], Awaitable[str]] | None = None

        # --- Tool registry ---
        max_depth = security_config.get("max_agent_depth", 3)
        self.tool_registry = self._build_tool_registry(max_depth)

        # --- Load persisted agent configs ---
        try:
            from vex.config.api import AgentConfigAPI

            self._agent_api = AgentConfigAPI(
                self.workspace, self.agent_registry
            )
            self._agent_api.load_persisted()
        except Exception:
            self._agent_api = None

        # --- Telegram config (for user identity) ---
        self.telegram_config = telegram_config
        self.allowed_users = telegram_config.get("allowed_users")
        if self.allowed_users:
            self.allowed_users = [int(uid) for uid in self.allowed_users]
        self.allowed_groups = telegram_config.get("allowed_groups")
        if self.allowed_groups:
            self.allowed_groups = set(int(gid) for gid in self.allowed_groups)

        self.network_config = network_config

    def _get_vexnet_client(self):
        return self.vexnet_client

    def _get_moltbook_client(self):
        return self.moltbook_client

    def _build_tool_registry(self, max_depth: int) -> ToolRegistry:
        """Build the shared tool registry with all tools."""
        registry = ToolRegistry()

        # Read-only tools
        registry.register(FileReadTool())
        registry.register(GlobTool())
        registry.register(GrepTool())
        registry.register(FileDiffTool())

        # Write tools
        registry.register(FileWriteTool())
        registry.register(FileEditTool())
        registry.register(FileBatchTool())
        registry.register(ShellTool())

        # Web tools
        registry.register(WebSearchTool())
        registry.register(WebFetchTool())
        registry.register(BrowserTool())

        # Chat history (now shared across all frontends)
        registry.register(ChatHistoryTool(self.chat_history))

        # Memory
        registry.register(MemoryTool(self.memory_store))

        # Personality
        registry.register(PersonalityTool(self.personality_manager))
        registry.register(UserProfileTool(self.user_profiles))

        # Agent meta-tools
        registry.register(
            AgentCreateTool(self.agent_registry, max_depth=max_depth)
        )
        registry.register(AgentDelegateTool(self._delegate_func))
        # ask_func is set later by the frontend via set_ask_func()
        registry.register(AgentAskTool(self._ask_placeholder))

        # VexNet tools
        if self.vexnet_client:
            from vex.network.client import VexNetClient
            from vex.tools.net_broadcast import NetBroadcastTool
            from vex.tools.net_constitution import NetConstitutionTool
            from vex.tools.net_discover import NetDiscoverTool
            from vex.tools.net_feed import NetFeedTool
            from vex.tools.net_group import NetGroupTool
            from vex.tools.net_jobs import NetJobsTool
            from vex.tools.net_peers import NetPeersTool
            from vex.tools.net_request import NetRequestTool
            from vex.tools.net_wiki import NetWikiTool

            registry.register(NetDiscoverTool(self._get_vexnet_client))
            registry.register(NetRequestTool(self._get_vexnet_client))
            registry.register(NetBroadcastTool(self._get_vexnet_client))
            registry.register(NetPeersTool(self._get_vexnet_client))
            registry.register(NetJobsTool(self._get_vexnet_client))
            registry.register(NetWikiTool(self._get_vexnet_client))
            registry.register(NetGroupTool(self._get_vexnet_client))
            registry.register(NetConstitutionTool(self._get_vexnet_client))
            registry.register(NetFeedTool(self._get_vexnet_client))

        # Moltbook
        if self.moltbook_client:
            registry.register(MoltbookTool(self._get_moltbook_client))

        # Self-improvement
        registry.register(SelfImproveTool(self.rule_store))

        # Plugins
        registry.discover_plugins()
        return registry

    def set_ask_func(self, func: Callable[[str], Awaitable[str]]) -> None:
        """Set the ask-user callback (frontend-specific)."""
        self._ask_func = func
        # Update the existing AgentAskTool
        ask_tool = self.tool_registry.get("agent.ask")
        if ask_tool:
            ask_tool._ask_func = func

    async def _ask_placeholder(self, question: str) -> str:
        """Placeholder until a frontend sets the real ask function."""
        if self._ask_func:
            return await self._ask_func(question)
        return "(No interactive prompt available — proceed with best judgment)"

    def _make_delegate_func(self):
        """Create the delegation function for sub-agents."""
        core = self

        async def delegate_to_agent(agent_id: str, task: str) -> str:
            target_def = core.agent_registry.get(agent_id)
            if not target_def:
                raise ValueError(f"Agent '{agent_id}' not found.")

            sub_llm = create_llm_client(
                core.llm_config,
                provider_override=target_def.llm_provider,
                model_override=target_def.llm_model,
            )

            sub_agent = AgentLoop(
                definition=target_def,
                llm=sub_llm,
                tool_registry=core.tool_registry,
                approval_callback=_auto_approve,
                audit_log=core.audit_log,
                tool_executor=core.tool_executor,
                metrics_collector=core.metrics_collector,
                conflict_detector=core.conflict_detector,
                debug_mode=core.debug_mode,
            )

            sub_conversation = Conversation()
            parts: list[str] = []
            async for event in sub_agent.run(task, sub_conversation):
                if isinstance(event, StreamEvent) and event.text_delta:
                    parts.append(event.text_delta)
            return "".join(parts) or "Agent completed without response."

        return delegate_to_agent

    def build_prompt_enhancers(
        self,
        user_id: int | None = None,
        chat_id: int | None = None,
        is_dm: bool = True,
    ) -> list[Any]:
        """Build the list of prompt enhancers for an agent."""
        enhancers: list[Any] = []

        # Personality
        enhancers.append(self.personality_manager)

        # VexNet
        if self._vexnet_enhancer:
            enhancers.append(self._vexnet_enhancer)

        # Moltbook
        if self._moltbook_enhancer:
            enhancers.append(self._moltbook_enhancer)

        # Self-improvement rules
        enhancers.append(self._self_improvement_enhancer)

        # Per-user context (chat ID, user profile, curiosity hints)
        if user_id is not None and chat_id is not None:
            profiles = self.user_profiles
            curiosity = self.curiosity_engine

            def _user_context_enhancer(
                system_prompt: str, conversation: Any
            ) -> str:
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

                if (
                    is_dm
                    and curiosity
                    and curiosity.should_ask_question(
                        user_id, "", is_dm
                    )
                ):
                    hint = curiosity.generate_question_hint(user_id)
                    if hint:
                        system_prompt = f"{system_prompt}\n{hint}"

                return system_prompt

            enhancers.append(_user_context_enhancer)

        return enhancers

    def create_agent(
        self,
        approval_callback: ApprovalCallback | None = None,
        extra_enhancers: list[Any] | None = None,
        user_id: int | None = None,
        chat_id: int | None = None,
        is_dm: bool = True,
    ) -> AgentLoop:
        """Create an AgentLoop with all shared components wired in."""
        enhancers = self.build_prompt_enhancers(
            user_id=user_id, chat_id=chat_id, is_dm=is_dm
        )
        if extra_enhancers:
            enhancers.extend(extra_enhancers)

        return AgentLoop(
            definition=self.agent_def,
            llm=self.llm,
            tool_registry=self.tool_registry,
            approval_callback=approval_callback,
            audit_log=self.audit_log,
            tool_executor=self.tool_executor,
            metrics_collector=self.metrics_collector,
            conflict_detector=self.conflict_detector,
            debug_mode=self.debug_mode,
            strategy_advisor=self.strategy_advisor,
            prompt_enhancers=enhancers,
        )

    @property
    def cli_user_id(self) -> int:
        """Get the user ID for CLI sessions (from telegram.allowed_users[0])."""
        if self.allowed_users:
            return self.allowed_users[0]
        # Fallback: hash of OS username for a stable numeric ID
        import hashlib
        username = os.getlogin()
        return int(hashlib.sha256(username.encode()).hexdigest()[:15], 16)


async def _auto_approve(tool_call: Any, schema: Any) -> bool:
    """Auto-approve for sub-agents and non-interactive contexts."""
    from vex.tools.base import RiskTier

    if schema and schema.risk_tier >= RiskTier.DESTRUCTIVE:
        return False
    return True
