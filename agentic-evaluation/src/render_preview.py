"""Render the coaching report template to an HTML file for browser preview.

Usage: python render_preview.py
Output: preview_report.html (open in browser to inspect layout)
"""

import jinja2
from pathlib import Path
from services.template_filters import register_filters
from models.synthesized_report import (
    SynthesizedReport, DimensionEntry, ScoreBand, Severity, SeverityCounts,
    SynthesizedFinding, EffortTag, ImpactTag, ThreeMove, TalkTimeline,
    TranscriptMetrics, Provenance, SwapPair, PracticeDrill,
)

# Build a realistic report with all fields populated
dims = []
names = ['Delivery', 'Structure', 'Executive Presence', 'Technical Communication',
         'Audience Engagement', 'Pacing', 'Persuasion']
scores = [7.2, 6.8, 5.5, 7.0, 4.2, 3.9, 6.5]
bands = [ScoreBand.EFFECTIVE, ScoreBand.EFFECTIVE, ScoreBand.COMPETENT, ScoreBand.EFFECTIVE,
         ScoreBand.COMPETENT, ScoreBand.DEVELOPING, ScoreBand.COMPETENT]

for i, (name, score, band) in enumerate(zip(names, scores, bands)):
    findings = [
        SynthesizedFinding(
            severity=Severity.HIGH, title=f'Critical issue in {name.lower()}',
            explanation=f'Your {name.lower()} shows a significant gap that impacts audience perception.',
            suggestion=f'Focus on improving your {name.lower()} by practicing targeted exercises.',
            effort_tag=EffortTag.QUICK_WIN, impact_tag=ImpactTag.HIGH,
            projected_impact_score=3.5,
            evidence_quote=f'And so basically what we do here is kind of like...',
            evidence_timestamp_seconds=45.2 + i * 30,
        ),
        SynthesizedFinding(
            severity=Severity.MEDIUM, title=f'Moderate concern in {name.lower()}',
            explanation=f'There are opportunities to strengthen your approach in this area.',
            suggestion=f'Consider restructuring your approach to {name.lower()}.',
            effort_tag=EffortTag.MODERATE, impact_tag=ImpactTag.MEDIUM,
            projected_impact_score=2.0,
        ),
    ]
    dims.append(DimensionEntry(
        dimension_name=name,
        score=score,
        score_band=band,
        rank=i + 1,
        one_sentence_verdict=f'Your {name.lower()} is solid but has room to grow.',
        severity_counts=SeverityCounts(high=1, medium=1, low=0, strength=2),
        findings=findings,
        strengths=[f'Good baseline {name.lower()} skills', 'Consistent effort throughout'],
        swap_pair=SwapPair(
            you_said='And so basically what we do here is kind of like a platform.',
            try_instead='Our platform delivers three specific capabilities that solve this problem.',
        ) if i < 3 else None,
        practice_drill=PracticeDrill(
            time_box_minutes=5,
            instructions=f'Spend five minutes practicing your {name.lower()} by recording a 60-second segment and reviewing it for the specific issues identified above. Focus on one finding at a time.',
        ) if findings else None,
        is_weakest=(i == 5),  # Pacing is weakest at 3.9
    ))

report = SynthesizedReport(
    user_name='Michael Geiser',
    presentation_title='Introduction to Agent Core Platform',
    description='A technical overview of the Agent Core platform architecture and deployment capabilities.',
    file_name='agentcore-intro-2026.mp3',
    upload_date='2026-08-27T10:30:00Z',
    audio_duration_seconds=485.5,
    report_id='d9d32b59-5912-4c0d-a2fc-e576625aa350',
    speaker_identified=False,
    overall_score=5.9,
    score_band=ScoreBand.COMPETENT,
    distance_to_next_band=0.6,
    two_sentence_verdict='Your presentation is competent with a solid foundation in technical communication. Prioritizing improvements in pacing and audience engagement will yield the greatest score gains.',
    lede_paragraph='You scored 5.9 out of 10, placing you in the Competent band. Your three highest-leverage improvements are: Eliminate hedging language, Add a compelling opening story, and Slow your pacing during technical sections. Addressing these will create measurable progress toward the Effective band.',
    executive_summary=(
        'This presentation sits at a 5.9 out of 10, which is best described as technically credible but not '
        'yet persuasive. The knowledge is clearly there, but the communication choices consistently undercut '
        'the weight of what is being said. The content is sound, the structure is recognizable, and the delivery '
        'is energetic, but the overall impression is of a knowledgeable practitioner explaining a product rather '
        'than a confident expert making a compelling case for it.\n\n'
        'The clearest strength here is Delivery combined with Technical Communication. There is a natural, '
        'conversational teaching quality that makes genuinely complex infrastructure concepts feel approachable. '
        'The consistent second-person framing, the rhetorical questions that frame problems before solutions, '
        'and the low filler-word count all signal real command of the material.\n\n'
        'The highest-leverage opportunity is eliminating hedging language while simultaneously adding one or two '
        'credibility anchors. Phrases like "kind of a mishmash," "sort of," "pretty cool," and "I\'m sure there\'ll '
        'be more" appear throughout and are doing real damage to Executive Presence and Persuasion simultaneously.\n\n'
        'For the next recording, focus on three specific changes: rewrite the first 30 seconds to open with a '
        'concrete developer scenario, conduct a deliberate pass to remove hedging language, and add one quantified '
        'claim that gives the audience something concrete to hold onto.'
    ),
    coaching_assessment=(
        'You are performing at the upper end of Competent, which means the fundamentals are in place and the '
        'path to Effective is about precision rather than reinvention. Your technical knowledge and conversational '
        'delivery style are genuine assets that should not be sacrificed while fixing weaker areas.\n\n'
        'The priority is clear: Executive Presence and Audience Engagement are the two dimensions dragging the '
        'overall score down. Fixing hedging language alone will lift Presence, Persuasion, and likely Structure '
        'simultaneously. Adding one story to the opening will address Engagement and make the entire presentation '
        'more memorable.'
    ),
    dimensions=dims,
    three_moves=[
        ThreeMove(title='Eliminate hedging language', coaching_advice='Remove every instance of "kind of," "sort of," "pretty cool," and "I\'m sure" from your script. Replace each with a direct, confident assertion. This single change lifts Executive Presence and Persuasion simultaneously.', projected_impact_score=2.5, dimensions_lifted=['Executive Presence', 'Persuasion']),
        ThreeMove(title='Open with a developer scenario', coaching_advice='Replace the current abstract opening with a concrete 30-second story of a developer struggling with the exact problem your platform solves. Make the pain visceral before naming the solution.', projected_impact_score=2.0, dimensions_lifted=['Audience Engagement', 'Structure']),
        ThreeMove(title='Slow pacing in technical sections', coaching_advice='Your speaking rate exceeds 180 WPM during technical explanations. Target 140-150 WPM for complex concepts. Add deliberate 2-second pauses after key assertions to let them land.', projected_impact_score=1.5, dimensions_lifted=['Pacing', 'Delivery']),
    ],
    strengths_to_protect=['Natural conversational teaching quality that makes complex concepts accessible.', 'Low filler-word count signals command of material.', 'Strong technical accuracy throughout.'],
    diagnosis_paragraph='These three moves matter because they address the gap between technical credibility and persuasive authority. Hedging undermines every strong point you make, storytelling creates the emotional hook that technical content alone cannot provide, and pacing gives the audience time to absorb what you are saying.',
    transcript_metrics=TranscriptMetrics(
        speaking_rate_wpm=175, target_range_wpm=(130, 160),
        filler_word_count=12, so_opener_count=31,
        pauses_over_one_second=8, longest_unbroken_run_seconds=62.3,
        close_share_percent=10.5, enunciation_confidence=0.82,
    ),
    talk_timeline=TalkTimeline(
        total_duration_seconds=485.5, open_percent=12.0, body_percent=73.0, close_percent=15.0,
    ),
    provenance=Provenance(
        report_id='d9d32b59-5912-4c0d-a2fc-e576625aa350', evaluator_release='2.0.0', rubric_version='1.0.0',
        prompt_set_version='1.0.0', model_id='us.anthropic.claude-sonnet-4-6',
        model_temperature=0.0, transcription_service='aws-transcribe',
        evaluation_window='PT30M', run_completed_timestamp='2026-08-27T10:35:00Z',
    ),
)

# Render
template_dir = Path('templates')
env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(template_dir)),
    autoescape=jinja2.select_autoescape(['html']),
    undefined=jinja2.StrictUndefined,
)
register_filters(env)

context = report.model_dump(mode="json")
template = env.get_template('coaching_report.html')
html = template.render(**context)

# Write to file
output_path = Path('preview_report.html')
output_path.write_text(html, encoding='utf-8')
print(f"Preview written to: {output_path.resolve()}")
print(f"Open in your browser to inspect the layout.")
print(f"Note: CSS will load if you open from the src/ directory (relative path to templates/coaching_report.css)")
