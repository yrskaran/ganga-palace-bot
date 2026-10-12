"""Export all authored questions with actual production-evaluation evidence."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qa_conversations import conversations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text())
    rows = evidence.get('rows', []) if isinstance(evidence, dict) else evidence
    indexed = {r['id']: r for r in rows}
    accepted = sum(bool(r.get('fresh_model_acceptance')) for r in indexed.values())
    lines = ['HOTEL BOT — 200 CUSTOMER QUESTIONS: ACTUAL EVALUATION',
             f'Attempted: {len(indexed)}/200; automatic acceptance: {accepted}; not run: {200-len(indexed)}.',
             'Automatic acceptance is not independent factual certification.',
             'Real model and production message handler; synthetic guests only.',
             'WhatsApp, Sheets, staff delivery, orders and payments were isolated. Their success is not certified.', '']
    for chat in conversations():
        lines.append('SEGMENT: ' + chat['segment'])
        for number, turn in enumerate(chat['turns'], 1):
            key = f"{chat['id']}-{number:02}"
            row = indexed.get(key)
            lines.extend([key, 'QUESTION: ' + turn['text']])
            if row is None:
                lines.extend(['STATUS: NOT RUN', 'ANSWER: No actual answer available.', ''])
                continue
            lines.extend(['ANSWER: ' + row.get('output', ''),
                          'AUTOMATIC STATUS: ' + ('ACCEPTED' if row.get('fresh_model_acceptance') else 'FAILED CHECK'),
                          'CHECK ERRORS: ' + '; '.join(row.get('errors', [])),
                          'MODEL: ' + row.get('model', 'unknown'),
                          'REVISION: ' + row.get('revision', 'unknown'), ''])
    args.output.write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
