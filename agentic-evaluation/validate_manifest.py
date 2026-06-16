"""Temporary script to validate the agents manifest."""
import json
import sys
sys.path.insert(0, ".")

from src.models.data_models import AgentDescriptor

with open("src/agents/agents_manifest.json") as f:
    data = json.load(f)

agents = data["agents"]
print(f"Valid JSON with {len(agents)} agents")

for entry in agents:
    descriptor = AgentDescriptor(**entry)
    print(f"  OK: {descriptor.agent_id} ({descriptor.dimension}) - {descriptor.display_name}")

print("\nAll entries validated against AgentDescriptor model successfully!")
