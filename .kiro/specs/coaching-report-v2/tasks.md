# Implementation Plan: Coaching Report v2

## Overview

Replace the existing ReportLab-based PDF coaching report with a WeasyPrint-based HTML/CSS-to-PDF pipeline. Implementation proceeds bottom-up: data models first, then pure-function metrics extraction, then the synthesis pass, then the Jinja2 template and WeasyPrint renderer, and finally Docker container updates and wiring.

## Tasks

- [x] 1. Define data models and core utilities
  - [x] 1.1 Create the SynthesizedReport Pydantic v2 data model
    - Create `src/models/synthesized_report.py` with all model classes: ScoreBand, Severity, EffortTag, ImpactTag, SynthesizedFinding, SwapPair, PracticeDrill, SeverityCounts, DimensionEntry, ThreeMove, TimelinePin, TalkTimeline, TranscriptMetrics, Provenance, SynthesizedReport
    - Include all field validators (word count limits, percentage sum, exactly-one-weakest)
    - Include model validators for cross-field constraints
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14_

  - [x] 1.2 Create score band classification utilities
    - Create `src/services/score_utils.py` with `classify_score_band()` and `compute_distance_to_next_band()` functions
    - Implement boundary logic: Developing < 4.0, Competent [4.0, 6.5), Effective [6.5, 8.5), Exceptional ≥ 8.5
    - _Requirements: 2.3, 2.4_

  - [x] 1.3 Create custom exception hierarchy for report generation
    - Create `src/services/report_errors.py` with ReportError, ReportValidationError, ReportRenderError, ReportUploadError
    - Each exception carries report_id and descriptive message
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [x] 1.4 Write property tests for data model validation (Properties 7, 8)
    - **Property 7: Score band classification and distance-to-next-band are consistent**
    - **Property 8: SynthesizedReport model rejects invalid field values**
    - **Validates: Requirements 2.3, 2.4, 2.14, 2.15**

- [x] 2. Implement transcript metrics extraction
  - [x] 2.1 Create the transcript metrics module
    - Create `src/services/transcript_metrics.py` with WordTiming and TranscriptData dataclasses
    - Implement `compute_metrics()` as the public entry point (returns None for < 2 words)
    - Implement `_compute_speaking_rate_wpm()` — total words / net speaking minutes, rounded to int
    - Implement `_count_filler_words()` — count uh, um, ah, er, and contextual "like"
    - Implement `_count_so_openers()` — "So" after >1s pause or as first word
    - Implement `_count_pauses()` — inter-word gaps > 1.0s
    - Implement `_compute_longest_unbroken_run()` — max segment between >1s pauses, rounded to 1 decimal
    - Implement `_compute_close_share()` — percentage of total audio in closing segment
    - Implement `_compute_enunciation_confidence()` — median of non-null word confidence scores
    - All functions are pure, deterministic, with no side effects
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11_

  - [x] 2.2 Write property tests for transcript metrics (Properties 9, 10, 11, 12, 13)
    - **Property 9: Speaking rate WPM computed correctly**
    - **Property 10: Pause count equals number of inter-word gaps exceeding 1 second**
    - **Property 11: Longest unbroken run is the maximum segment between pauses**
    - **Property 12: Enunciation confidence is the median of word confidence scores**
    - **Property 13: Transcript metrics computation is deterministic**
    - **Validates: Requirements 3.1, 3.4, 3.5, 3.7, 3.8, 3.10, 3.11**

  - [x] 2.3 Write unit tests for transcript metrics edge cases
    - Test < 2 words returns None
    - Test all-pause transcript (every gap > 1s)
    - Test single-word transcript
    - Test "like" disambiguation heuristic
    - Test "So" at transcript start vs mid-transcript
    - _Requirements: 3.9, 3.2, 3.3_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement the Coaching Supervisor synthesis pass
  - [x] 4.1 Implement duplicate collapse logic
    - Add `_collapse_duplicates()` to `src/agents/coaching_supervisor.py`
    - Collapse findings raised by ≥3 agents for the same category/behavior
    - Attribute collapsed finding to the dimension where the issue costs the most points
    - Add cross_dimension_note (max 120 chars) identifying other affected dimensions
    - _Requirements: 1.2, 1.3_

  - [x] 4.2 Implement global ranking and cap enforcement
    - Add `_rank_findings()` — sort by Projected_Impact_Score descending
    - Add `_apply_caps()` — enforce 5 findings/dim, 3 strengths/dim
    - Implement `apply_findings_cap()` with evidence-aware drop priority: no-evidence findings dropped first (lowest impact), then lowest-impact with evidence
    - _Requirements: 1.4, 1.6, 1.7, 1.10_

  - [x] 4.3 Implement Three Move Plan derivation
    - Add `_derive_three_moves()` — extract top 3 ranked findings as ThreeMove objects
    - Generate projected_impact_score and dimensions_lifted for each move
    - Produce strengths_to_protect list (max 4 items)
    - Generate diagnosis_paragraph (max 150 words)
    - _Requirements: 1.5, 1.11, 1.12_

  - [x] 4.4 Implement Swap Pair and Practice Drill generation
    - Add `_generate_swap_pairs()` — one per dimension where evidence_quote ≥ 10 chars
    - Add `_generate_practice_drills()` — one per dimension with findings
    - Enforce field constraints: SwapPair you_said [10,280], try_instead ≤ 400; PracticeDrill time_box [2,15], instructions [50,500]
    - _Requirements: 1.8, 1.9, 11.1, 11.2, 11.3, 11.4, 11.5, 12.1, 12.2, 12.3, 12.4_

  - [x] 4.5 Implement the synthesis_pass() orchestrator method
    - Wire all sub-methods into `synthesis_pass()` on CoachingSupervisor
    - Accept list[EvaluationResult], TranscriptData, SubmissionMetadata
    - Handle partial results (≥1 agent returned) with logging for missing agents
    - Return fully validated SynthesizedReport
    - _Requirements: 1.1, 1.13_

  - [x] 4.6 Write property tests for synthesis pass (Properties 1, 2, 3, 4, 5, 6)
    - **Property 1: Synthesis produces valid output from any valid evaluation results**
    - **Property 2: Duplicate collapse merges same-category findings with impact note**
    - **Property 3: Global ranking is sorted descending by Projected Impact Score**
    - **Property 4: Three Move Plan derives from the top-3 ranked findings**
    - **Property 5: Per-dimension caps are enforced**
    - **Property 6: Finding drop priority preserves evidence over impact**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.10, 1.13**

  - [x] 4.7 Write property tests for Swap Pair and Practice Drill rules (Properties 16, 17)
    - **Property 16: Swap pair presence follows evidence rule**
    - **Property 17: Practice drill presence follows findings rule**
    - **Validates: Requirements 11.1, 11.4, 12.1, 12.4**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement the Jinja2 template and WeasyPrint renderer
  - [x] 6.1 Create the Jinja2 HTML template and CSS
    - Create `src/templates/coaching_report.html` with page structure: Scorecard, Three Moves, Dimension Cards (weakest-first), Progress placeholder, How This Was Scored
    - Create `src/templates/coaching_report.css` with @page rules for US Letter (8.5×11 in), page margins, font fallback chains (sans-serif, serif, monospace)
    - Implement inline SVG generation for: gauge arc, dimension bars, talk timeline, dimension timeline strips
    - Add page footer with page numbers ("N / total"), report_id, brand name
    - Use `break-inside: avoid` for findings
    - _Requirements: 4.2, 4.3, 4.5, 4.6, 5.1–5.14, 6.1–6.7, 7.1–7.12, 8.1–8.5, 9.1–9.5, 10.1–10.5_

  - [x] 6.2 Implement template filters and helper functions
    - Register Jinja2 filters: `format_duration(seconds)`, `format_date(iso_string)`, `score_band_color(band)`, `score_to_arc_degrees(score)`
    - Implement SVG path data generation for the gauge arc visualization
    - Implement dimension bar scaling logic (0–10 range, target line at 6.5)
    - Implement talk timeline rendering with percentage segments and finding pins
    - _Requirements: 5.4, 5.7, 5.8, 10.5_

  - [x] 6.3 Implement the ReportGeneratorV2 class
    - Create `src/services/report_generator.py` with ReportGeneratorV2
    - Implement `generate()` orchestration: validate → render HTML → render PDF → upload → update status
    - Implement `_validate()` — fail immediately with ReportValidationError listing invalid fields
    - Implement `_render_html()` — load Jinja2 template, render with SynthesizedReport as dict context
    - Implement `_render_pdf()` — WeasyPrint HTML→PDF with 30s timeout, unrecoverable on failure
    - Implement `_upload()` — S3 put_object with retry (3 attempts, 1s base, 2× backoff, FULL jitter) for recoverable errors; fail-fast for access denied / bucket not found
    - Implement `_update_status()` — DynamoDB submission status update; on failure log both errors and propagate original
    - S3 path: `reports/{user_id}/{submission_id}/coaching_report.pdf`
    - Max PDF size: 10 MB
    - _Requirements: 4.1, 4.4, 4.8, 4.9, 4.10, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

  - [x] 6.4 Write unit tests for ReportGeneratorV2 error handling
    - Test validation failure returns ReportValidationError with field list
    - Test template missing/syntax error raises ReportRenderError
    - Test WeasyPrint failure raises ReportRenderError
    - Test 30s timeout terminates and raises ReportRenderError
    - Test S3 recoverable error retries 3× with backoff
    - Test S3 unrecoverable error (AccessDenied) fails immediately
    - Test DynamoDB status update failure logs both errors
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

  - [x] 6.5 Write property tests for PDF rendering (Properties 14, 15)
    - **Property 14: PDF page count in valid range for complete reports**
    - **Property 15: PDF page ordering follows specification**
    - **Validates: Requirements 4.3, 4.4**

- [x] 7. Implement second-person voice validation
  - [x] 7.1 Add voice consistency validation to synthesis pass
    - Validate all coaching prose fields use second-person pronouns ("you"/"your")
    - Ensure user_name does not appear in coaching prose fields (two_sentence_verdict, lede_paragraph, diagnosis_paragraph, finding explanations/suggestions, swap pair try_instead, drill instructions)
    - Place speaker identity only in submission metadata fields
    - _Requirements: 15.1, 15.2, 15.3_

  - [x] 7.2 Write property test for voice consistency (Property 18)
    - **Property 18: Coaching prose uses second-person voice and excludes speaker identity**
    - **Validates: Requirements 15.1, 15.2**

- [x] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Update Docker container and wire components
  - [x] 9.1 Update Dockerfile with WeasyPrint dependencies
    - Add apt-get install for: libcairo2, libpango-1.0-0, libpangocairo-1.0-0, libgdk-pixbuf2.0-0, libffi-dev, shared-mime-info, fonts-dejavu-core, fonts-liberation, fonts-freefont-ttf
    - Add HEALTHCHECK that verifies WeasyPrint can render minimal HTML to PDF
    - Clean up apt lists to minimize image size
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [x] 9.2 Update requirements.txt with new Python dependencies
    - Add weasyprint, Jinja2 (if not already present) with pinned versions
    - Verify no dependency conflicts with existing packages
    - _Requirements: 13.1_

  - [x] 9.3 Wire the synthesis pass into the Coaching Supervisor flow
    - Integrate `synthesis_pass()` call after all specialist agents complete in the existing CoachingSupervisor orchestration
    - Pass the SynthesizedReport to ReportGeneratorV2.generate()
    - Replace existing ReportLab report generation call with the new pipeline
    - Ensure existing S3 path convention is maintained: `reports/{user_id}/{submission_id}/coaching_report.pdf`
    - _Requirements: 1.1, 4.1, 4.8_

  - [x] 9.4 Write integration test for end-to-end report generation
    - Test full pipeline from EvaluationResult[] → SynthesizedReport → HTML → PDF → S3 upload (mocked)
    - Verify PDF is valid, non-empty, within size limit
    - Verify S3 key matches expected path
    - _Requirements: 4.1, 4.4, 4.8_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The design uses Python with Pydantic v2, Hypothesis for PBT, and pytest for test execution
- All transcript metrics functions are pure and deterministic — ideal for property-based testing
- Error handling follows workspace standards: fail immediately for unrecoverable, exponential backoff with jitter for recoverable

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3"] },
    { "id": 3, "tasks": ["4.1", "4.2"] },
    { "id": 4, "tasks": ["4.3", "4.4"] },
    { "id": 5, "tasks": ["4.5"] },
    { "id": 6, "tasks": ["4.6", "4.7"] },
    { "id": 7, "tasks": ["6.1", "6.2"] },
    { "id": 8, "tasks": ["6.3"] },
    { "id": 9, "tasks": ["6.4", "6.5", "7.1"] },
    { "id": 10, "tasks": ["7.2"] },
    { "id": 11, "tasks": ["9.1", "9.2"] },
    { "id": 12, "tasks": ["9.3"] },
    { "id": 13, "tasks": ["9.4"] }
  ]
}
```
