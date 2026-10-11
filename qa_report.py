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
                              'Code revision: '+str(row.get('code_revision','initial diagnostic run')),
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
            wanted=['Allowed action: '+', '.join(turn['actions'])]
            if turn.get('names'):
                wanted.append('Requested configured items: '+', '.join(turn['names']))
            if 'qty' in turn:
                wanted.append('Explicit quantity: '+str(turn['qty']))
            if turn.get('scope'):
                wanted.append('Bill scope: '+turn['scope'])
            if turn.get('no_handoff'):
                wanted.append('No staff handoff or unauthorized action')
            lines.append('Verification expectation (NOT an AI answer): '+'; '.join(wanted))
    lines[1:1]=['Results: '+', '.join(f'{k}={v}' for k,v in counts.items()),'Actual model replies: '+str(sum(bool(r.get('reply')) for r in records.values()))+' / 200','']
    Path(target).write_text('\n'.join(lines)+'\n')
    return counts


def append_probe_report(target, paths):
    """Record the normal pipeline probes without counting them as the 200 chats."""
    with Path(target).open('a') as out:
        out.write('\n'+'='*72+'\nNORMAL PRODUCTION AI PIPELINE — SEPARATE BASELINES / RECHECKS\n'+'='*72+'\n')
        out.write('These use real interpreter, independent review and composer, with isolated execution receipts. They are not real WhatsApp delivery tests.\n')
        for label,path in paths:
            out.write('\n'+label+'\n')
            for line in Path(path).read_text().splitlines():
                r=json.loads(line)
                valid=bool((r.get('plan') or {}).get('action'))
                out.write('\n'+r['id']+' | revision '+r.get('code_revision','baseline')+'\nCustomer: '+r['question']+'\n')
                out.write('Actual AI answer: '+(r.get('reply') if valid and r.get('reply') else '[No completed actual-model response]')+'\n')
                if not valid and r.get('reply'):
                    out.write('Diagnostic executor fallback (NOT an AI answer): '+r['reply']+'\n')
                out.write('Automatic checks: '+('; '.join(r.get('errors',[])) or 'Routing checks pass; factual/language review still required')+'\n')
                out.write('Actual reviewed plan: '+json.dumps(r.get('plan'),ensure_ascii=False)+'\n')
        out.write('\nVERIFIED CODE CHANGES / OUTSTANDING WORK\n')
        out.write('1. Independent review now covers orders, quantity revisions, confirmations, services and complaints. Canonical items, explicit integer quantities and saved confirmation state remain strictly validated.\n')
        out.write('2. Observed operational RECEPTION output previously failed validation. A resolved request with empty items now routes to reception; its unverified availability/success reply is discarded. Regression reproduced before fix, passes afterwards.\n')
        out.write('3. Every review branch now explicitly requests current language; Roman Hindi means Hinglish. This repairs the missing language field in the menu-review prompt. Actual model language quality still needs further rechecks.\n')
        out.write('4. Composer/critic require disclosure of failed staff delivery and reject unsupported update/arrival promises. Guard failure retains the verified result.\n')
        out.write('5. Check-in policy prompting preserves possible requirements instead of inventing mandatory rules. Actual-model results were inconsistent, so this is NOT claimed resolved.\n')
        out.write('Validation: 249 automated repository tests passed; independent code review found no blocker in targeted reception/language repair. These are not 249 customer-model tests.\n')
        out.write('Live acceptance: latest post-fix AI rechecks were blocked/incomplete by provider cooldown/quota. Earlier quantity recheck preserved 2 Masala Chai and ₹60 but replied in English. No claim that all failures are fixed.\n')
        out.write('Other unresolved findings: conversation routing/scope, saved cart revisions, preparation assumptions, factual response grounding and language/script consistency. Originals above are preserved, not replaced with hoped-for answers.\n')
