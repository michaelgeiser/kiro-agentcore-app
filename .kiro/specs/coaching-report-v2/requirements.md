# Requirements Document

## Introduction

This document specifies the requirements for Coaching Report v2, a complete replacement of the existing ReportLab-based PDF coaching report with a WeasyPrint-based HTML/CSS-to-PDF pipeline. The new system produces a visually rich, 6+ page coaching report from a Jinja2 template, driven by structured JSON output from a new Coaching Supervisor synthesis pass. The report replaces a 14-page evaluation log with a focused, actionable coaching document that separates measured transcript metrics from model-judged dimension scores.

## Glossary

- **Coaching_Supervisor**: The agent that orchestrates evaluation, performs the synthesis pass after all specialist agents complete, and produces the SynthesizedReport used by the Report_Generator.
- **Report_Generator**: The service that renders a SynthesizedReport into a PDF file using WeasyPrint and a Jinja2 HTML template.
- **SynthesizedReport**: The structured data model produced by the Coaching_Supervisor synthesis pass, containing all fields needed to render the coaching report PDF.
- **EvaluationResult**: The structured output from a single specialist evaluation agent, containing dimension, score, findings, strengths, improvements, agent_id, and timestamp.
- **Finding**: A single observation from an evaluation agent, containing category, detail, severity (low/medium/high), suggestion, and optionally timestamp and evidence quote.
- **Specialist_Agent**: One of seven evaluation agents, each responsible for scoring and producing findings for a single dimension.
- **Dimension**: One of seven evaluation categories: Delivery, Structure, Executive Presence, Technical Communication, Audience Engagement, Pacing, Persuasion.
- **Score_Band**: A classification of a numeric score into one of four named ranges: Developing (0–4.0), Competent (4.0–6.5), Effective (6.5–8.5), Exceptional (8.5–10.0).
- **Three_Move_Plan**: The top three highest-leverage coaching recommendations derived from globally-ranked findings after the synthesis collapse pass.
- **Transcript_Metrics**: Objective measurements computed from the transcript and word-level timings: speaking rate (WPM), filler word count, "So" as sentence opener count, pause count (over 1 second), longest unbroken run, close share of talk, and enunciation confidence.
- **Talk_Timeline**: A visual representation of the audio duration segmented into open/body/close with findings pinned to their timestamps.
- **Swap_Pair**: A "you said / try instead" panel pairing a verbatim transcript quote with a rewritten version demonstrating the coaching advice.
- **Practice_Drill**: A concrete, time-boxed rehearsal exercise assigned per dimension.
- **WeasyPrint**: An HTML/CSS-to-PDF rendering engine used to produce the final report PDF from a Jinja2 template.
- **Projected_Impact_Score**: A numeric estimate of the score improvement achievable by addressing a specific finding, derived from rubric weightings.

## Requirements

### Requirement 1: Coaching Supervisor Synthesis Pass

**User Story:** As a coaching report consumer, I want duplicate findings collapsed and findings ranked globally, so that the report presents a concise, prioritized set of coaching actions rather than repetitive observations from multiple agents.

#### Acceptance Criteria

1. WHEN all seven Specialist_Agents have returned EvaluationResults, THE Coaching_Supervisor SHALL execute a synthesis pass that produces a SynthesizedReport.
2. WHEN three or more Specialist_Agents raise findings with the same category field referencing the same underlying behavior in the transcript, THE Coaching_Supervisor SHALL collapse those findings into one finding attributed to the Dimension where the issue costs the most points.
3. WHEN findings have been collapsed, THE Coaching_Supervisor SHALL include a cross-dimension impact note on the collapsed finding of no more than 120 characters identifying which other dimensions are affected.
4. WHEN the collapse pass is complete, THE Coaching_Supervisor SHALL rank all surviving findings globally in descending order of Projected_Impact_Score.
5. THE Coaching_Supervisor SHALL derive the Three_Move_Plan from the top three globally-ranked findings.
6. THE Coaching_Supervisor SHALL enforce a cap of 5 findings per Dimension in the SynthesizedReport.
7. THE Coaching_Supervisor SHALL enforce a cap of 3 strengths per Dimension in the SynthesizedReport.
8. THE Coaching_Supervisor SHALL enforce a cap of 1 Swap_Pair per Dimension in the SynthesizedReport.
9. THE Coaching_Supervisor SHALL enforce a cap of 1 Practice_Drill per Dimension in the SynthesizedReport.
10. WHEN the number of findings exceeds the cap for a Dimension, THE Coaching_Supervisor SHALL drop findings without evidence (no timestamp and no quoted phrase) first, then drop remaining lowest-Projected_Impact_Score findings until the cap is met.
11. THE Coaching_Supervisor SHALL generate a Projected_Impact_Score in the range 0.0 to 10.0 for each of the Three_Move_Plan items.
12. THE Coaching_Supervisor SHALL produce a maximum of 4 strengths-to-protect items for the Three_Move_Plan page.
13. IF one or more Specialist_Agents fail to return an EvaluationResult, THEN THE Coaching_Supervisor SHALL log the missing agent identifiers and proceed with the synthesis pass using available results, provided at least one result was obtained.

### Requirement 2: SynthesizedReport Data Model

**User Story:** As a template author, I want a well-defined data model containing all fields needed by the report template, so that template rendering is deterministic given valid input.

#### Acceptance Criteria

1. THE SynthesizedReport SHALL include submission metadata: user_name (max 100 characters), presentation_title (max 200 characters), file_name (max 255 characters), upload_date (ISO 8601 UTC timestamp), audio_duration_seconds (float ≥ 0.0), report_id (UUID string), and speaker_identified (boolean indicating whether audio speaker was identified as distinct from account holder).
2. THE SynthesizedReport SHALL include an overall_score field as a float in the range 0.0 to 10.0.
3. THE SynthesizedReport SHALL include a score_band field classified as one of: Developing, Competent, Effective, Exceptional.
4. THE SynthesizedReport SHALL include a distance_to_next_band field as a float representing points needed to reach the next Score_Band boundary, or 0.0 when the overall_score is in the Exceptional band.
5. THE SynthesizedReport SHALL include a two_sentence_verdict field containing a plain-language summary of the coaching diagnosis, constrained to exactly two sentences and a maximum of 80 words.
6. THE SynthesizedReport SHALL include a lede_paragraph field containing a one-paragraph summary for the scorecard page, constrained to a maximum of 120 words.
7. THE SynthesizedReport SHALL include a dimensions list of exactly 7 entries (one per Dimension), each entry containing: dimension_name, score (float 0.0–10.0), score_band, rank (integer 1–7, weakest-first), one_sentence_verdict (max 25 words), severity_counts (object with integer fields: high, medium, low, strength), findings list (max 5 items), strengths list (max 3 items), swap_pair (object or null), practice_drill (object or null), and is_weakest flag (boolean, true for exactly one entry).
8. THE SynthesizedReport SHALL include a three_moves list of exactly 3 entries, each containing: title (max 60 characters), coaching_advice (max 150 words), projected_impact_score (float 0.0–10.0), and dimensions_lifted (list of 1–7 Dimension names).
9. THE SynthesizedReport SHALL include a strengths_to_protect list of 1 to 4 items, each a single sentence of no more than 30 words.
10. THE SynthesizedReport SHALL include a diagnosis_paragraph field explaining why the three moves matter together, constrained to a maximum of 150 words.
11. THE SynthesizedReport SHALL include a transcript_metrics object containing: speaking_rate_wpm (integer ≥ 0), target_range_wpm (tuple of two integers representing lower and upper bounds), filler_word_count (integer ≥ 0), so_opener_count (integer ≥ 0), pauses_over_one_second (integer ≥ 0), longest_unbroken_run_seconds (float ≥ 0.0), close_share_percent (float 0.0–100.0), and enunciation_confidence (float 0.0–1.0).
12. THE SynthesizedReport SHALL include a talk_timeline object containing: total_duration_seconds (float ≥ 0.0), open_percent (float 0.0–100.0), body_percent (float 0.0–100.0), close_percent (float 0.0–100.0) where open_percent + body_percent + close_percent equals 100.0, and a list of timeline_pins (each with timestamp_seconds as float, label as string max 60 characters, severity as one of high/medium/low, and dimension as a valid Dimension name).
13. THE SynthesizedReport SHALL include a provenance object containing: report_id (UUID string), evaluator_release (semantic version string), rubric_version (semantic version string), prompt_set_version (semantic version string), model_id (string), model_temperature (float 0.0–2.0), transcription_service (string), evaluation_window (ISO 8601 duration string), and run_completed_timestamp (ISO 8601 UTC timestamp).
14. WHEN a Finding is included in the SynthesizedReport, THE Finding SHALL contain: severity (one of: high, medium, low), title (max 80 characters), explanation (max 100 words), suggestion (max 80 words), effort_tag (one of: quick-win, moderate, long-term), impact_tag (one of: high, medium, low), and optionally evidence_quote (verbatim transcript text, max 200 characters) and evidence_timestamp_seconds (float ≥ 0.0).
15. IF any required field in the SynthesizedReport is null or outside its specified range, THEN THE Report_Generator SHALL reject the report with an error identifying all invalid fields.

### Requirement 3: Transcript Metrics Extraction

**User Story:** As a report consumer, I want objective, reproducible metrics computed from the transcript, so that I can track measurable speaking improvements independently of model-judged scores.

#### Acceptance Criteria

1. WHEN a transcript with word-level timings is provided, THE Report_Generator SHALL compute speaking_rate_wpm as total words divided by total speaking duration in minutes, where total speaking duration is the elapsed time from the start of the first word to the end of the last word excluding any pauses exceeding 1.0 second.
2. WHEN a transcript with word-level timings is provided, THE Report_Generator SHALL count filler words (uh, um, ah, er, and "like" when it appears immediately before a pause of 0.2 seconds or more or when it is not followed by a noun, adjective, or verb within the next two words) and report the count as filler_word_count.
3. WHEN a transcript with word-level timings is provided, THE Report_Generator SHALL count occurrences of "So" appearing as the first word after a pause exceeding 1.0 second or as the first word of the transcript and report the count as so_opener_count.
4. WHEN a transcript with word-level timings is provided, THE Report_Generator SHALL identify all pauses exceeding 1.0 second between the end timestamp of one word and the start timestamp of the next word and report the count as pauses_over_one_second.
5. WHEN a transcript with word-level timings is provided, THE Report_Generator SHALL compute longest_unbroken_run_seconds as the maximum duration between any two consecutive pauses exceeding 1.0 second, treating the start of the transcript and the end of the transcript as implicit boundaries.
6. WHEN a transcript with word-level timings is provided, THE Report_Generator SHALL compute close_share_percent as the percentage of total audio duration occupied by the closing segment, where the closing segment boundary is determined by the close_start_seconds field from the Talk_Timeline segmentation.
7. WHEN a transcript with word-level timings is provided, THE Report_Generator SHALL compute enunciation_confidence as the median of all word-level confidence scores from the transcription service output, excluding words that have no confidence score.
8. THE Transcript_Metrics computation SHALL produce identical results when run multiple times on the same transcript input (deterministic, no randomness or floating-point order dependence).
9. IF the transcript contains fewer than 2 words with timing data, THEN THE Report_Generator SHALL return null for all computed metrics and indicate that insufficient data was available for metrics extraction.
10. WHEN computing speaking_rate_wpm, THE Report_Generator SHALL round the result to the nearest integer.
11. WHEN computing longest_unbroken_run_seconds, THE Report_Generator SHALL round the result to one decimal place.

### Requirement 4: Report PDF Rendering

**User Story:** As a coaching report consumer, I want a visually polished multi-page PDF report, so that I receive an actionable, professionally designed coaching document.

#### Acceptance Criteria

1. WHEN a valid SynthesizedReport is provided, THE Report_Generator SHALL render it into a PDF file using WeasyPrint with a Jinja2 HTML template within 30 seconds of rendering start.
2. THE Report_Generator SHALL produce a PDF with US Letter page size (8.5 × 11 inches).
3. THE Report_Generator SHALL render the following pages in order: Scorecard, Three Moves, Dimension Cards (7 dimensions, weakest-first), Progress (placeholder), and How This Was Scored.
4. THE Report_Generator SHALL produce a minimum of 6 pages and a maximum of 20 pages for a complete report with all 7 dimensions evaluated.
5. THE Report_Generator SHALL use system-safe fonts with a fallback chain of sans-serif for UI text, serif for body text, and monospace for metric values, without requiring specific proprietary or uncommon font families.
6. THE Report_Generator SHALL include page numbers in the format "N / total" in the page footer.
7. THE Report_Generator SHALL include the report identifier and brand name in the page footer.
8. WHEN rendering is complete, THE Report_Generator SHALL upload the PDF (maximum file size 10 MB) to S3 at the path reports/{user_id}/{submission_id}/coaching_report.pdf.
9. IF WeasyPrint rendering fails, THEN THE Report_Generator SHALL log the full error context including the SynthesizedReport report_id and the exception details, and return an error immediately without retrying.
10. IF rendering does not complete within 30 seconds, THEN THE Report_Generator SHALL terminate the rendering operation, log the timeout with the report_id, and return an error immediately without retrying.

### Requirement 5: Scorecard Page

**User Story:** As a report reader, I want a single page that shows my overall score, all seven dimension scores ranked weakest-first, objective transcript metrics, severity counts, and a talk timeline, so that I can assess my performance at a glance.

#### Acceptance Criteria

1. THE Report_Generator SHALL render the Scorecard page as the first page of the report.
2. THE Scorecard page SHALL display a brand/identity bar with the report issue date formatted as "MONTH DAY, YEAR" (e.g., "AUGUST 5, 2026").
3. THE Scorecard page SHALL display submission metadata: presentation title, user name, file name, audio duration formatted as M min SS sec, upload time in ET, and speaker identified (if different from account holder).
4. THE Scorecard page SHALL display the overall score in a semi-circular arc gauge visualization spanning 0 to 10, with the four Score_Band boundaries (4.0, 6.5, 8.5) marked as tick lines on the arc.
5. THE Scorecard page SHALL display the Score_Band label and distance to next band (e.g., "0.6 below Effective") below the gauge.
6. THE Scorecard page SHALL display the two_sentence_verdict.
7. THE Scorecard page SHALL display a Talk_Timeline as a horizontal band showing open/body/close segments with their percentage labels, and high-severity findings pinned to their timestamp positions along the band.
8. THE Scorecard page SHALL display seven dimension bars ranked weakest-first, each scaled 0 to 10, with a vertical target line at score 6.5 labelled "Effective starts at 6.5".
9. THE Scorecard page SHALL display a delta column next to each dimension bar, stubbed with em dashes until the trend service is available.
10. THE Scorecard page SHALL display severity counts as four labeled chips: High, Medium, Low, and Strengths, each showing the numeric count.
11. THE Scorecard page SHALL display the eight Transcript_Metrics in a "Measured, not judged" panel, each with its label and formatted value.
12. THE Scorecard page SHALL flag metric values that fall outside their target range by rendering the value in a contrasting color (red/alert for outside range, green for within range).
13. THE Scorecard page SHALL display the lede_paragraph at the bottom of the page.
14. IF all Scorecard content does not fit within a single US Letter page, THEN THE Report_Generator SHALL allow the Scorecard to extend onto a second page rather than clipping or overlapping content.

### Requirement 6: Three Moves Page

**User Story:** As a report reader, I want to see the three highest-leverage changes I can make, with projected impact scores and clear coaching advice, so that I know where to focus my practice effort.

#### Acceptance Criteria

1. THE Report_Generator SHALL render the Three Moves page as the second page of the report.
2. THE Three Moves page SHALL display the diagnosis_paragraph explaining why these three changes matter together.
3. THE Three Moves page SHALL display exactly three move cards, each containing: projected_impact_score (formatted as "+N.N"), title, coaching_advice paragraph, and a list of dimensions it lifts.
4. THE Three Moves page SHALL order move cards by projected_impact_score descending (highest impact first).
5. IF the strengths_to_protect list contains one or more items, THEN THE Three Moves page SHALL display a "Do not lose these while you fix the rest" panel containing the strengths_to_protect list (max 4 items).
6. IF the strengths_to_protect list is empty, THEN THE Three Moves page SHALL omit the "Do not lose these while you fix the rest" panel.
7. THE Three Moves page SHALL display a footnote describing that projected impact scores are estimates derived from rubric weightings and do not guarantee exact score increases.

### Requirement 7: Dimension Card Pages

**User Story:** As a report reader, I want each of the seven dimensions presented as a structured card with score, verdict, findings, evidence, a rewrite example, and a practice drill, so that I can understand and act on feedback for each dimension.

#### Acceptance Criteria

1. THE Report_Generator SHALL render Dimension Card pages after the Three Moves page, ordered by score ascending (weakest dimension first), with ties broken by alphabetical dimension name.
2. WHEN a dimension has the lowest score among all seven dimensions, THE Report_Generator SHALL render its score block with a visually distinct alert background color.
3. Each Dimension Card SHALL display: score as a large numeral with "/10" and the Score_Band label.
4. Each Dimension Card SHALL display a one_sentence_verdict of 25 words or fewer.
5. Each Dimension Card SHALL display a rank line showing position among seven dimensions (e.g., "Weakest dimension" or "Rank 3 of 7") and the count of high-severity findings for that dimension.
6. Each Dimension Card SHALL display a timeline strip showing that dimension's findings that have an evidence_timestamp_seconds value pinned to the audio timeline; findings without timestamps SHALL be excluded from the timeline strip.
7. Each Dimension Card SHALL display a "What is working" section with up to 3 strengths; IF a dimension has zero strengths, THEN the "What is working" section SHALL be omitted.
8. Each Dimension Card SHALL display findings sorted by severity (high first, then medium, then low), each containing: severity tag, title, explanation, evidence quote with timestamp (when available), suggestion, and effort/impact tags.
9. IF a dimension has zero findings, THEN THE Dimension Card SHALL display a message indicating no findings were identified for that dimension.
10. WHEN a Swap_Pair exists for a dimension, THE Dimension Card SHALL display a "Say this instead" panel with the verbatim transcript quote and the rewritten version.
11. WHEN a Practice_Drill exists for a dimension, THE Dimension Card SHALL display the drill with a time-box indicator (showing the time_box_minutes value) and concrete rehearsal instructions.
12. THE Report_Generator SHALL allow dimension cards to span across page breaks as needed, with findings using CSS break-inside:avoid to prevent splitting individual findings across pages.

### Requirement 8: Progress Page (Placeholder)

**User Story:** As a report reader, I want to see a placeholder for the progress trend section, so that I understand this capability is planned and know how many submissions are needed to activate it.

#### Acceptance Criteria

1. THE Report_Generator SHALL render a Progress page after the Dimension Card pages.
2. THE Progress page SHALL display an empty-state message: "This is your first submission. Trends need three data points before they mean anything."
3. THE Progress page SHALL display progress pip indicators showing 1 of 3 submissions completed.
4. THE Progress page SHALL display a flag box noting this is a preview of a capability not yet live.
5. THE Progress page SHALL render as a static placeholder page with no dynamic data requirements beyond the SynthesizedReport provenance.

### Requirement 9: How This Was Scored Page

**User Story:** As a report reader, I want to understand the scoring methodology and see full provenance for the evaluation run, so that I can trust the report as an instrument rather than an opinion.

#### Acceptance Criteria

1. THE Report_Generator SHALL render a "How this was scored" page as the final page of the report.
2. THE "How this was scored" page SHALL display the four Score_Band definitions with their numeric ranges and descriptions: Developing (0.0–4.0, "Content or delivery is getting in the audience's way"), Competent (4.0–6.5, "Clear and correct. Not yet memorable or persuasive"), Effective (6.5–8.5, "Lands with the room and holds attention throughout"), Exceptional (8.5–10.0, "People quote it afterward and then act on it").
3. THE "How this was scored" page SHALL display a methodology explanation covering: seven specialist agents evaluating independently, supervisor merge that collapses duplicate findings, and the distinction between measured metrics (reproducible) and model judgment (may vary between runs).
4. THE "How this was scored" page SHALL display a provenance table containing all fields from the provenance object: report_id, evaluator_release, rubric_version, prompt_set_version, model_id and temperature, transcription_service, evaluation_window, and run_completed_timestamp.
5. THE "How this was scored" page SHALL display a disclaimer stating that scores are guidance from an automated evaluator, most useful compared against the reader's own earlier runs on the same rubric version, and least useful compared against another speaker.

### Requirement 10: Jinja2 Template System

**User Story:** As a developer, I want report rendering driven by a Jinja2 HTML template with a separate CSS file, so that visual design changes do not require code changes to the Report_Generator logic.

#### Acceptance Criteria

1. THE Report_Generator SHALL load an HTML template from a Jinja2 template file at a configurable path defaulting to templates/coaching_report.html within the application directory.
2. THE Report_Generator SHALL pass the SynthesizedReport as the template context for rendering, serialized as a dictionary.
3. THE Jinja2 template SHALL produce valid HTML that WeasyPrint can render without errors for all valid SynthesizedReport inputs.
4. THE template system SHALL support CSS in a separate file or inline style block referenced by the HTML template.
5. THE Report_Generator SHALL generate SVG elements inline within the HTML for the gauge, dimension bars, talk timeline, and dimension timeline strips using Jinja2 template logic or Python helper functions registered as template filters.
6. IF the template file is missing or contains syntax errors, THEN THE Report_Generator SHALL raise an error immediately with a clear message identifying the template path and error location.

### Requirement 11: Swap Pair Generation

**User Story:** As a report reader, I want to see my own words next to a rewritten version demonstrating the coaching advice, so that I can hear the improvement applied to my actual speech.

#### Acceptance Criteria

1. THE Coaching_Supervisor SHALL produce one Swap_Pair per Dimension where at least one Finding for that dimension contains a non-empty evidence_quote of 10 or more characters.
2. THE Swap_Pair "you said" field SHALL contain a verbatim quote from the transcript, between 10 and 280 characters in length.
3. THE Swap_Pair "try instead" field SHALL contain a rewritten version of the quote demonstrating the coaching advice for that dimension, not exceeding 400 characters in length.
4. WHEN a dimension has no Finding with a non-empty evidence_quote of at least 10 characters, THE Coaching_Supervisor SHALL omit the Swap_Pair for that dimension rather than inventing a quote.
5. THE Swap_Pair "try instead" field SHALL preserve the original intent of the speaker's statement while demonstrating the coaching improvement for the associated dimension.

### Requirement 12: Practice Drill Generation

**User Story:** As a report reader, I want a concrete, time-boxed rehearsal exercise for each dimension, so that I have an actionable next step rather than abstract advice.

#### Acceptance Criteria

1. THE Coaching_Supervisor SHALL produce one Practice_Drill per Dimension that has at least one Finding.
2. Each Practice_Drill SHALL include a time_box_minutes field as an integer in the range 2 to 15 indicating the recommended practice duration.
3. Each Practice_Drill SHALL contain rehearsal instructions of 50 to 500 characters that describe a specific action the speaker can perform, referencing at least one finding from that dimension.
4. WHEN a Dimension has no findings, THE Coaching_Supervisor SHALL omit the Practice_Drill for that dimension.

### Requirement 13: Docker Container Dependencies

**User Story:** As a DevOps engineer, I want the Docker container to include WeasyPrint and its font dependencies, so that PDF rendering works correctly in the ECS Fargate Spot environment.

#### Acceptance Criteria

1. THE Docker container SHALL include WeasyPrint and its system-level dependencies (cairo, pango, gdk-pixbuf).
2. THE Docker container SHALL include at least one serif, one sans-serif, and one monospace font family with a CSS fallback chain defined for each category.
3. WHEN the container starts, THE Report_Generator SHALL verify that WeasyPrint can render a minimal HTML document to PDF within 10 seconds.
4. IF required system dependencies for WeasyPrint are missing at startup, THEN THE Report_Generator SHALL log a clear error message identifying the missing dependency and exit with a non-zero status code.

### Requirement 14: Report Generation Error Handling

**User Story:** As a system operator, I want clear error handling during report generation, so that failures are diagnosable and do not cause silent data loss.

#### Acceptance Criteria

1. IF the SynthesizedReport fails validation (missing required fields, scores outside 0.0–10.0), THEN THE Report_Generator SHALL return an error immediately with a message identifying each invalid field and the reason it failed validation.
2. IF the Jinja2 template rendering raises an exception or produces output that WeasyPrint cannot render, THEN THE Report_Generator SHALL log the rendering error with template path and error location, and return a failure status without uploading to S3.
3. IF the S3 upload fails with a recoverable error (throttling, timeout, service unavailable), THEN THE Report_Generator SHALL retry with exponential backoff starting at 1 second with jitter, up to 3 attempts.
4. IF the S3 upload fails with an unrecoverable error (access denied, bucket not found, invalid credentials), THEN THE Report_Generator SHALL return an error immediately without retrying.
5. WHEN report generation fails for any reason, THE Report_Generator SHALL update the submission status to Failed in DynamoDB with the failure reason truncated to 1000 characters.
6. IF the DynamoDB status update to Failed itself fails, THEN THE Report_Generator SHALL log the original failure reason and the DynamoDB error, and propagate the original error to the caller.

### Requirement 15: Second-Person Voice Consistency

**User Story:** As a report reader, I want all coaching content written in consistent second-person voice, so that the report reads as direct coaching addressed to me.

#### Acceptance Criteria

1. THE Coaching_Supervisor SHALL produce all coaching text (verdicts, findings, suggestions, swap pairs, drills, diagnosis paragraph) using second-person pronouns ("you", "your") and SHALL NOT refer to the speaker by name or in third person within coaching prose.
2. THE SynthesizedReport SHALL place speaker identity information (speaker name, account holder name, and any personal identifiers) only in the submission metadata fields, not within coaching prose.
3. WHEN the speaker identified in audio differs from the account holder, THE Scorecard page SHALL display a single line in the metadata section indicating that the evaluated speaker differs from the account holder and identifying the detected speaker name.
