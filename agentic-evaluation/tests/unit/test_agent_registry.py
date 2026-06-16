"""Unit tests for the Agent Registry.

Tests agent discovery from the JSON manifest, filtering of disabled agents,
dimension lookup, and error handling for missing or invalid manifest files.

Requirements: 3.3, 3.4, 12.2
"""

import json

import pytest

from agents.registry import AgentRegistry
from models.data_models import AgentDescriptor


# ---------------------------------------------------------------------------
# Loading agents from the default manifest
# ---------------------------------------------------------------------------


class TestAgentRegistryDefaultManifest:
    """Tests that the registry loads agents from the default manifest."""

    def test_loads_all_agents_from_default_manifest(self):
        """Registry loads all 7 agents from the default agents_manifest.json."""
        registry = AgentRegistry()
        agents = registry.get_available_agents()
        assert len(agents) == 7

    def test_all_agents_are_agent_descriptor_instances(self):
        """Each loaded agent is an AgentDescriptor instance."""
        registry = AgentRegistry()
        agents = registry.get_available_agents()
        for agent in agents:
            assert isinstance(agent, AgentDescriptor)

    def test_all_seven_dimensions_present(self):
        """All 7 expected evaluation dimensions are present in the registry."""
        registry = AgentRegistry()
        agents = registry.get_available_agents()
        dimensions = {agent.dimension for agent in agents}
        expected = {
            "delivery",
            "structure",
            "executive_presence",
            "technical_communication",
            "audience_engagement",
            "pacing",
            "persuasion",
        }
        assert dimensions == expected


# ---------------------------------------------------------------------------
# Filtering disabled agents
# ---------------------------------------------------------------------------


class TestAgentRegistryFiltering:
    """Tests that disabled agents are filtered from available agents."""

    def test_disabled_agents_filtered_out(self, tmp_path):
        """get_available_agents() excludes agents with enabled=False."""
        manifest = {
            "agents": [
                {
                    "agent_id": "agent-1",
                    "dimension": "delivery",
                    "display_name": "Delivery Evaluator",
                    "description": "Evaluates delivery",
                    "version": "1.0.0",
                    "enabled": True,
                    "tool_module": "agents.delivery_evaluator",
                },
                {
                    "agent_id": "agent-2",
                    "dimension": "structure",
                    "display_name": "Structure Evaluator",
                    "description": "Evaluates structure",
                    "version": "1.0.0",
                    "enabled": False,
                    "tool_module": "agents.structure_evaluator",
                },
                {
                    "agent_id": "agent-3",
                    "dimension": "pacing",
                    "display_name": "Pacing Evaluator",
                    "description": "Evaluates pacing",
                    "version": "1.0.0",
                    "enabled": True,
                    "tool_module": "agents.pacing_evaluator",
                },
            ]
        }
        manifest_file = tmp_path / "agents_manifest.json"
        manifest_file.write_text(json.dumps(manifest))

        registry = AgentRegistry(manifest_path=manifest_file)
        available = registry.get_available_agents()

        assert len(available) == 2
        dimensions = {a.dimension for a in available}
        assert "delivery" in dimensions
        assert "pacing" in dimensions
        assert "structure" not in dimensions

    def test_all_disabled_returns_empty(self, tmp_path):
        """If all agents are disabled, get_available_agents() returns empty list."""
        manifest = {
            "agents": [
                {
                    "agent_id": "agent-1",
                    "dimension": "delivery",
                    "display_name": "Delivery Evaluator",
                    "description": "Evaluates delivery",
                    "version": "1.0.0",
                    "enabled": False,
                    "tool_module": "agents.delivery_evaluator",
                },
            ]
        }
        manifest_file = tmp_path / "agents_manifest.json"
        manifest_file.write_text(json.dumps(manifest))

        registry = AgentRegistry(manifest_path=manifest_file)
        assert registry.get_available_agents() == []


# ---------------------------------------------------------------------------
# Dimension lookup
# ---------------------------------------------------------------------------


class TestAgentRegistryDimensionLookup:
    """Tests for get_agent_by_dimension()."""

    def test_get_agent_by_dimension_returns_correct_agent(self):
        """get_agent_by_dimension('delivery') returns the delivery agent."""
        registry = AgentRegistry()
        agent = registry.get_agent_by_dimension("delivery")
        assert agent is not None
        assert agent.dimension == "delivery"
        assert agent.agent_id == "delivery-evaluator-v1"

    def test_get_agent_by_dimension_nonexistent_returns_none(self):
        """get_agent_by_dimension('nonexistent') returns None."""
        registry = AgentRegistry()
        agent = registry.get_agent_by_dimension("nonexistent")
        assert agent is None

    def test_get_agent_by_dimension_disabled_returns_none(self, tmp_path):
        """get_agent_by_dimension() returns None for disabled agents."""
        manifest = {
            "agents": [
                {
                    "agent_id": "agent-1",
                    "dimension": "delivery",
                    "display_name": "Delivery Evaluator",
                    "description": "Evaluates delivery",
                    "version": "1.0.0",
                    "enabled": False,
                    "tool_module": "agents.delivery_evaluator",
                },
            ]
        }
        manifest_file = tmp_path / "agents_manifest.json"
        manifest_file.write_text(json.dumps(manifest))

        registry = AgentRegistry(manifest_path=manifest_file)
        assert registry.get_agent_by_dimension("delivery") is None


# ---------------------------------------------------------------------------
# Missing and invalid manifest handling
# ---------------------------------------------------------------------------


class TestAgentRegistryErrorHandling:
    """Tests for missing or invalid manifest files."""

    def test_missing_manifest_returns_empty_list(self, tmp_path):
        """Missing manifest file results in an empty agent list."""
        non_existent = tmp_path / "does_not_exist.json"
        registry = AgentRegistry(manifest_path=non_existent)
        assert registry.get_available_agents() == []

    def test_invalid_json_manifest_returns_empty_list(self, tmp_path):
        """Invalid JSON in the manifest results in an empty agent list."""
        invalid_file = tmp_path / "agents_manifest.json"
        invalid_file.write_text("this is not valid json {{{")

        registry = AgentRegistry(manifest_path=invalid_file)
        assert registry.get_available_agents() == []

    def test_manifest_missing_agents_key_returns_empty(self, tmp_path):
        """Manifest without 'agents' key results in an empty list."""
        manifest_file = tmp_path / "agents_manifest.json"
        manifest_file.write_text(json.dumps({"version": "1.0"}))

        registry = AgentRegistry(manifest_path=manifest_file)
        assert registry.get_available_agents() == []

    def test_manifest_agents_not_list_returns_empty(self, tmp_path):
        """Manifest with 'agents' as non-list results in an empty list."""
        manifest_file = tmp_path / "agents_manifest.json"
        manifest_file.write_text(json.dumps({"agents": "not a list"}))

        registry = AgentRegistry(manifest_path=manifest_file)
        assert registry.get_available_agents() == []

    def test_manifest_with_invalid_entry_skips_it(self, tmp_path):
        """Invalid entries in the agents list are skipped gracefully."""
        manifest = {
            "agents": [
                {
                    "agent_id": "agent-1",
                    "dimension": "delivery",
                    "display_name": "Delivery Evaluator",
                    "description": "Evaluates delivery",
                    "version": "1.0.0",
                    "enabled": True,
                    "tool_module": "agents.delivery_evaluator",
                },
                {
                    # Missing required fields
                    "agent_id": "bad-agent",
                },
            ]
        }
        manifest_file = tmp_path / "agents_manifest.json"
        manifest_file.write_text(json.dumps(manifest))

        registry = AgentRegistry(manifest_path=manifest_file)
        available = registry.get_available_agents()
        assert len(available) == 1
        assert available[0].agent_id == "agent-1"
