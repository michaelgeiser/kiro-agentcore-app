"""Agent Registry for configuration-driven evaluation agent discovery.

Loads agent descriptors from a JSON manifest file at runtime, enabling
new evaluation agents to be added through configuration rather than
code changes to the orchestration layer.
"""

import json
import logging
from pathlib import Path

from models.data_models import AgentDescriptor

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Discovers available evaluation agents at runtime.

    Reads agent descriptors from a JSON manifest file and provides
    lookup methods for the Coaching Supervisor to discover which
    evaluation agents are available.

    Args:
        manifest_path: Path to the agents_manifest.json file.
            Defaults to agents_manifest.json in the same directory
            as this module.
    """

    def __init__(self, manifest_path: str | Path | None = None) -> None:
        if manifest_path is None:
            manifest_path = Path(__file__).parent / "agents_manifest.json"
        else:
            manifest_path = Path(manifest_path)

        self._manifest_path = manifest_path
        self._agents: list[AgentDescriptor] = self._load_manifest()

    def _load_manifest(self) -> list[AgentDescriptor]:
        """Read and parse the JSON manifest into AgentDescriptor objects.

        Returns:
            A list of AgentDescriptor instances parsed from the manifest.
            Returns an empty list if the manifest file is missing or invalid.
        """
        if not self._manifest_path.exists():
            logger.warning(
                "Agent manifest file not found: %s. "
                "Registry will contain no agents.",
                self._manifest_path,
            )
            return []

        try:
            raw = self._manifest_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(
                "Failed to read or parse agent manifest at %s: %s",
                self._manifest_path,
                exc,
            )
            return []

        agents_data = data.get("agents", [])
        if not isinstance(agents_data, list):
            logger.error(
                "Invalid manifest format: 'agents' key must be a list. "
                "Got %s instead.",
                type(agents_data).__name__,
            )
            return []

        agents: list[AgentDescriptor] = []
        for idx, entry in enumerate(agents_data):
            try:
                agent = AgentDescriptor.model_validate(entry)
                agents.append(agent)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping invalid agent descriptor at index %d: %s",
                    idx,
                    exc,
                )

        logger.info(
            "Loaded %d agent descriptor(s) from manifest.", len(agents)
        )
        return agents

    def get_available_agents(self) -> list[AgentDescriptor]:
        """Return all registered evaluation agents that are enabled.

        Filters out agents where enabled=False, so only active agents
        are returned to the Coaching Supervisor for orchestration.

        Returns:
            A list of enabled AgentDescriptor instances.
        """
        return [agent for agent in self._agents if agent.enabled]

    def get_agent_by_dimension(self, dimension: str) -> AgentDescriptor | None:
        """Lookup a specific enabled agent by its evaluation dimension.

        Args:
            dimension: The evaluation dimension name (e.g. "delivery",
                "structure", "pacing").

        Returns:
            The AgentDescriptor for the given dimension if found and enabled,
            or None if no enabled agent covers that dimension.
        """
        for agent in self._agents:
            if agent.dimension == dimension and agent.enabled:
                return agent
        return None
