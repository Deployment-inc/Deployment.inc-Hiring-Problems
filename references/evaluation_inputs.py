#!/usr/bin/env python3
"""Allowlist candidate-visible inputs. Gold and private metadata stay with the reviewer."""
import argparse
import json
from pathlib import Path

def project(problem, row):
    def pick(obj, keys):
        return {key:obj[key] for key in keys if key in obj}
    if problem == 'OP-04':
        trajectory = row['trajectory']
        return {'id':row['id'], 'trajectory':{
            'case':pick(trajectory['case'], ('case_id','customer_id','loan_id','message','family','difficulty')),
            'turns':[pick(turn, ('role','content')) for turn in trajectory['turns']],
            'audited_tool_calls':trajectory['audited_tool_calls']}}
    if problem == 'OP-05':
        return pick(row, ('id','question','role','as_of'))
    if problem == 'OP-06':
        result = pick(row, ('id','turn_index'))
        result['context'] = [pick(turn, ('speaker','text')) for turn in row['context']]
        return result
    raise ValueError('only OP-04, OP-05 and OP-06 use this projection')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--problem', choices=['OP-04','OP-05','OP-06'], required=True)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args=ap.parse_args()
    rows=[json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    args.output.write_text(''.join(json.dumps(project(args.problem,row),ensure_ascii=False,allow_nan=False)+'\n' for row in rows))
if __name__ == '__main__': main()
