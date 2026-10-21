"""Deterministic exports assembled exclusively from stored incident history."""
import json


def markdown_report(data):
    incident = data['incident']
    lines = [f"# {incident['number']} — {incident['title']}", '',
             '> Local demonstration report. Runbook guidance does not replace approved industrial safety procedures.', '',
             '| Field | Value |','|---|---|']
    for key in ('type','severity','status','site','line','started_at','detected_at','created_at',
                'acknowledged_at','investigating_at','mitigated_at','resolved_at',
                'duration_seconds','mtta_seconds','mttr_seconds'):
        value = str(incident.get(key) if incident.get(key) is not None else 'Not recorded')
        lines.append(f"| {key} | {value.replace('|', '/').replace(chr(10), ' ')} |")
    for title, key in [('Suggested root cause','suggested_root_cause'),('Operator root cause','root_cause'),
                       ('Impact','impact'),('Remediation actions recorded','remediation_actions'),
                       ('Resolution summary','resolution_summary')]:
        lines.extend(['', '## '+title, '', incident.get(key) or 'Not recorded.'])
    lines.extend(['','## Demonstration / runbook guidance',''])
    lines.extend(f'{i}. {step}' for i,step in enumerate(incident['remediation'],1))
    lines.extend(['','## Correlated alert occurrences',''])
    for alert in data['alerts']:
        lines.append(f"- {alert['name']} — {alert['status']} — {alert['starts_at']} → {alert.get('ends_at') or 'not recovered'}")
    lines.extend(['','## Timeline',''])
    for event in data['timeline']:
        lines.append(f"- {event['timestamp']} [{event['source']}/{event['event_type']}] {event['message']}")
    lines.extend(['','## Recorded evidence',''])
    for evidence in data['evidence']:
        lines.extend([f"### {evidence['source']} — {evidence['timestamp']}", '', '```json',
                      json.dumps(evidence['payload'],ensure_ascii=False,indent=2).replace('```','\\u0060\\u0060\\u0060'), '```',''])
    return '\n'.join(lines)+'\n'
