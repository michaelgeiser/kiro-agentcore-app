"""Synthesized Report data model for Coaching Report v2.

This module defines the Pydantic v2 models that form the contract between
the Coaching Supervisor synthesis pass and the Report Generator (WeasyPrint).

All models include field-level validators for word count limits, range
constraints, and model-level validators for cross-field consistency.
"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class ScoreBand(str, Enum):
    """Classification of a numeric score into named ranges."""

    DEVELOPING = "Developing"
    COMPETENT = "Competent"
    EFFECTIVE = "Effective"
    EXCEPTIONAL = "Exceptional"


class Severity(str, Enum):
    """Finding severity level."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EffortTag(str, Enum):
    """Estimated effort to address a finding."""

    QUICK_WIN = "quick-win"
    MODERATE = "moderate"
    LONG_TERM = "long-term"


class ImpactTag(str, Enum):
    """Projected impact of addressing a finding."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SynthesizedFinding(BaseModel):
    """A single deduplicated, ranked finding from the synthesis pass."""

    severity: Severity
    title: str = Field(..., max_length=80)
    explanation: str  # max 100 words enforced by validator
    suggestion: str  # max 80 words enforced by validator
    effort_tag: EffortTag
    impact_tag: ImpactTag
    evidence_quote: str | None = Field(default=None, max_length=200)
    evidence_timestamp_seconds: float | None = Field(default=None, ge=0.0)
    cross_dimension_note: str | None = Field(default=None, max_length=120)
    projected_impact_score: float = Field(..., ge=0.0, le=10.0)

    @field_validator("explanation")
    @classmethod
    def explanation_max_words(cls, v: str) -> str:
        if len(v.split()) > 100:
            raise ValueError("explanation must be 100 words or fewer")
        return v

    @field_validator("suggestion")
    @classmethod
    def suggestion_max_words(cls, v: str) -> str:
        if len(v.split()) > 80:
            raise ValueError("suggestion must be 80 words or fewer")
        return v


class SwapPair(BaseModel):
    """A 'you said / try instead' coaching panel."""

    you_said: str = Field(..., min_length=10, max_length=280)
    try_instead: str = Field(..., max_length=400)


class PracticeDrill(BaseModel):
    """A concrete, time-boxed rehearsal exercise for a dimension."""

    time_box_minutes: int = Field(..., ge=2, le=15)
    instructions: str = Field(..., min_length=50, max_length=500)


class SeverityCounts(BaseModel):
    """Count of findings by severity level plus strengths."""

    high: int = Field(..., ge=0)
    medium: int = Field(..., ge=0)
    low: int = Field(..., ge=0)
    strength: int = Field(..., ge=0)


class DimensionEntry(BaseModel):
    """One of seven dimension evaluations in the report."""

    dimension_name: str
    score: float = Field(..., ge=0.0, le=10.0)
    score_band: ScoreBand
    rank: int = Field(..., ge=1, le=7)
    one_sentence_verdict: str  # max 25 words
    severity_counts: SeverityCounts
    findings: list[SynthesizedFinding] = Field(..., max_length=5)
    strengths: list[str] = Field(..., max_length=3)
    swap_pair: SwapPair | None = None
    practice_drill: PracticeDrill | None = None
    is_weakest: bool = False

    @field_validator("one_sentence_verdict")
    @classmethod
    def verdict_max_words(cls, v: str) -> str:
        if len(v.split()) > 25:
            raise ValueError("one_sentence_verdict must be 25 words or fewer")
        return v


class ThreeMove(BaseModel):
    """One of the top-3 highest-leverage coaching recommendations."""

    title: str = Field(..., max_length=60)
    coaching_advice: str  # max 150 words
    projected_impact_score: float = Field(..., ge=0.0, le=10.0)
    dimensions_lifted: list[str] = Field(..., min_length=1, max_length=7)

    @field_validator("coaching_advice")
    @classmethod
    def advice_max_words(cls, v: str) -> str:
        if len(v.split()) > 150:
            raise ValueError("coaching_advice must be 150 words or fewer")
        return v


class TimelinePin(BaseModel):
    """A finding pinned to a specific timestamp on the talk timeline."""

    timestamp_seconds: float = Field(..., ge=0.0)
    label: str = Field(..., max_length=60)
    severity: Severity
    dimension: str


class TalkTimeline(BaseModel):
    """Timeline segmentation of the audio into open/body/close."""

    total_duration_seconds: float = Field(..., ge=0.0)
    open_percent: float = Field(..., ge=0.0, le=100.0)
    body_percent: float = Field(..., ge=0.0, le=100.0)
    close_percent: float = Field(..., ge=0.0, le=100.0)
    timeline_pins: list[TimelinePin] = Field(default_factory=list)

    @model_validator(mode="after")
    def percentages_sum_to_100(self) -> "TalkTimeline":
        total = self.open_percent + self.body_percent + self.close_percent
        if abs(total - 100.0) > 0.01:
            raise ValueError(
                f"open_percent + body_percent + close_percent must equal 100.0, got {total}"
            )
        return self


class TranscriptMetrics(BaseModel):
    """Objective measurements computed from transcript word-level timings."""

    speaking_rate_wpm: int = Field(..., ge=0)
    target_range_wpm: tuple[int, int]
    filler_word_count: int = Field(..., ge=0)
    so_opener_count: int = Field(..., ge=0)
    pauses_over_one_second: int = Field(..., ge=0)
    longest_unbroken_run_seconds: float = Field(..., ge=0.0)
    close_share_percent: float = Field(..., ge=0.0, le=100.0)
    enunciation_confidence: float = Field(..., ge=0.0, le=1.0)


class Provenance(BaseModel):
    """Full provenance metadata for the evaluation run."""

    report_id: str  # UUID string
    evaluator_release: str  # semver
    rubric_version: str  # semver
    prompt_set_version: str  # semver
    model_id: str
    model_temperature: float = Field(..., ge=0.0, le=2.0)
    transcription_service: str
    evaluation_window: str  # ISO 8601 duration
    run_completed_timestamp: str  # ISO 8601 UTC


class SynthesizedReport(BaseModel):
    """The complete data model produced by the Coaching Supervisor synthesis pass.

    Acts as the single contract between the supervisor and the Report Generator.
    Contains all fields needed to render the coaching report PDF.
    """

    # Submission metadata
    user_name: str = Field(..., max_length=100)
    presentation_title: str = Field(..., max_length=200)
    file_name: str = Field(..., max_length=255)
    upload_date: str  # ISO 8601 UTC
    audio_duration_seconds: float = Field(..., ge=0.0)
    report_id: str  # UUID string
    speaker_identified: bool

    # Scores
    overall_score: float = Field(..., ge=0.0, le=10.0)
    score_band: ScoreBand
    distance_to_next_band: float = Field(..., ge=0.0)

    # Narrative
    two_sentence_verdict: str  # max 80 words enforced by validator
    lede_paragraph: str  # max 120 words enforced by validator

    # Dimensions
    dimensions: list[DimensionEntry] = Field(..., min_length=7, max_length=7)

    # Three Moves
    three_moves: list[ThreeMove] = Field(..., min_length=3, max_length=3)
    strengths_to_protect: list[str] = Field(..., min_length=1, max_length=4)
    diagnosis_paragraph: str  # max 150 words enforced by validator

    # Metrics & Timeline
    transcript_metrics: TranscriptMetrics | None = None
    talk_timeline: TalkTimeline

    # Provenance
    provenance: Provenance

    @field_validator("two_sentence_verdict")
    @classmethod
    def verdict_constraints(cls, v: str) -> str:
        if len(v.split()) > 80:
            raise ValueError("two_sentence_verdict must be 80 words or fewer")
        return v

    @field_validator("lede_paragraph")
    @classmethod
    def lede_max_words(cls, v: str) -> str:
        if len(v.split()) > 120:
            raise ValueError("lede_paragraph must be 120 words or fewer")
        return v

    @field_validator("diagnosis_paragraph")
    @classmethod
    def diagnosis_max_words(cls, v: str) -> str:
        if len(v.split()) > 150:
            raise ValueError("diagnosis_paragraph must be 150 words or fewer")
        return v

    @model_validator(mode="after")
    def exactly_one_weakest(self) -> "SynthesizedReport":
        weakest_count = sum(1 for d in self.dimensions if d.is_weakest)
        if weakest_count != 1:
            raise ValueError(
                f"Exactly one dimension must have is_weakest=True, got {weakest_count}"
            )
        return self
