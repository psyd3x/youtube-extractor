"""Multi-persona instructions-extraction engine.

Turns a YouTube transcript into a build-ready InstructionsAndData document via a team of
distilled agency personas (Architect, Writer, Synthesizer, Orchestrator, Reality Checker,
ZK Steward). Entry point: extract_instructions.
"""

from __future__ import annotations

from youtube_extractor.pipeline.instructions.team import (
    InstructionsError,
    extract_instructions,
)

__all__ = ["extract_instructions", "InstructionsError"]
