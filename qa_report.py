"""Export all 200 requested questions, preserving missing and failed actual runs."""
import json
from pathlib import Path
from qa_conversations import conversations


def write_report(jsonl, target, reviews=None):
    records={}
    for line in Path(jsonl).read_text().splitlines():
        row=json.loads(line)
        records[row['id']]=row
    reviews=reviews or {}
    lines=['HOTEL RECEPTIONIST — 200 CUSTOMER QUESTIONS / ACTUAL AI ANSWERS',
           'Scope: 20 linked conversations, 10 turns each. Independent synthetic guest records.',
           'Method: batched real-model AI using shared production interpretation instructions.',
           'No actual WhatsApp, staff messages, orders, payments or Google Sheet edits executed.',
           'Production independent AI review stage and real operational end-to-end delivery are not exercised by this batch.',
           'A model answer is never invented where the provider did not return one.',
           'Automatic PASS checks routing/data contracts only; factual review is recorded separately.', '']
    counts={'PASS':0,'FAIL':0,'UNVERIFIED':0,'NOT RUN':0}
    for chat in conversations():
        lines.extend(['='*72,chat['id']+' — '+chat['segment'],'='*72])
        for i,turn in enumerate(chat['turns'],1):
            key=f"{chat['id']}-{i:02}"
            row=records.get(key)
            manual=reviews.get(key,{})
            if row is None:
                state='NOT RUN'
            elif not row.get('reply'):
                state='UNVERIFIED'
            elif row.get('errors') or manual.get('errors'):
                state='FAIL'
            elif manual.get('verified'):
                state='PASS'
            else:
                state='UNVERIFIED'
            counts[state]+=1
            lines.extend(['',key+' | '+state,'Customer: '+turn['text'],
                          'Actual bot answer: '+((row.get('reply') if row else '') or '[No actual AI answer]')])
            if row:
                lines.extend(['Model: '+str(row.get('model')),'Actual action: '+str((row.get('plan') or {}).get('action')),
                              'Automatic checks: '+('FAIL — '+'; '.join(row['errors']) if row.get('errors') else 'PASS — routing/data checks only')])
                if row.get('source'):
                    lines.append('Isolated execution result: '+row['source'])
            if manual:
                lines.append('Factual review: '+manual.get('note',''))
                if manual.get('errors'):
                    lines.append('Review failures: '+'; '.join(manual['errors']))
                if manual.get('fix'):
                    lines.append('Fix: '+manual['fix'])
                if manual.get('recheck_reply'):
                    lines.append('Actual recheck answer: '+manual['recheck_reply'])
            else:
                lines.append('Factual review: not yet completed')
    lines[1:1]=['Results: '+', '.join(f'{k}={v}' for k,v in counts.items()),'Actual model replies: '+str(sum(bool(r.get('reply')) for r in records.values()))+' / 200','']
    Path(target).write_text('\n'.join(lines)+'\n')
    return counts
