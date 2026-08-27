"""Synthesis utility functions for the Coaching Report v2 pipeline.

This module provides standalone, testable utility functions used by the
Coaching Supervisor's synthesis pass. Functions here are importable
independently for unit and property-based testing.
"""

from models.synthesized_report import SynthesizedFinding


def _has_evidence(finding: SynthesizedFinding) -> bool:
    """Check if a finding has evidence.

    A finding "has evidence" if it has a non-empty evidence_quote
    OR a non-None evidence_timestamp_seconds.
    """
    has_quote = bool(finding.evidence_quote)
    has_timestamp = finding.evidence_timestamp_seconds is not None
    return has_quote or has_timestamp


def apply_findings_cap(
    findings: list[SynthesizedFinding], cap: int = 5
) -> list[SynthesizedFinding]:
    """Enforce per-dimension findings cap.

    Drop order:
    1. Findings without evidence (no timestamp AND no quote) — lowest impact first
    2. Remaining findings — lowest Projected_Impact_Score first

    Returns at most `cap` findings.
    """
    if len(findings) <= cap:
        return findings

    has_evidence: list[SynthesizedFinding] = []
    no_evidence: list[SynthesizedFinding] = []
    for f in findings:
        if _has_evidence(f):
            has_evidence.append(f)
        else:
            no_evidence.append(f)

    # Sort no-evidence by impact ascending (lowest dropped first)
    no_evidence.sort(key=lambda f: f.projected_impact_score)

    # Drop no-evidence findings until at cap or exhausted
    while len(has_evidence) + len(no_evidence) > cap and no_evidence:
        no_evidence.pop(0)

    # If still over cap, drop lowest-impact from has_evidence
    has_evidence.sort(key=lambda f: f.projected_impact_score)
    remaining = has_evidence + no_evidence
    remaining.sort(key=lambda f: f.projected_impact_score, reverse=True)

    return remaining[:cap]
