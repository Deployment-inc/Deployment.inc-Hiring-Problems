#!/usr/bin/env python3
"""Harbour goal-state scorer. Uses an observed database, never a submitted success flag.

Run once per case against its fresh database snapshot. Table assertions specify named fields;
other fields and unrelated rows are not part of this task-success metric. Audit requirements
need successful calls; audit prohibitions reject any attempted call, even a refused one.
Policy-violation counts are separate and count completed disallowed actions.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
from pathlib import Path

TABLES={'customers','loans','payments','fees','disputes','documents'}

def score(conn: sqlite3.Connection, case: dict) -> dict:
    conn.row_factory=sqlite3.Row
    goal=case['goal_state']
    if not isinstance(goal,dict) or not goal:
        raise ValueError('case requires a nonempty goal_state')
    trail=[dict(x) for x in conn.execute('SELECT * FROM audit_log WHERE case_id=? ORDER BY seq',(case['case_id'],))]
    succeeded=set()
    attempted={row['tool'] for row in trail}
    for row in trail:
        result=json.loads(row.get('result_json') or 'null')
        if row['ok']==1 and result is not False and (row['tool']!='verify_identity' or result is True):
            succeeded.add(row['tool'])
    failures=[]
    for table,expected in goal.items():
        if not isinstance(expected,list): raise ValueError(f'{table} assertion must be a list')
        if table=='audit_must_include':
            failures += [f'required successful call missing: {tool}' for tool in expected if tool not in succeeded]
        elif table=='audit_must_not_include':
            failures += [f'prohibited call attempted: {tool}' for tool in expected if tool in attempted]
        else:
            if table not in TABLES: raise ValueError(f'unknown goal table: {table}')
            rows=[dict(x) for x in conn.execute('SELECT * FROM '+table)]
            columns={x['name'] for x in conn.execute('PRAGMA table_info('+table+')')}
            for i,wanted in enumerate(expected):
                if not isinstance(wanted,dict) or not wanted or not set(wanted)<=columns:
                    raise ValueError(f'invalid {table} row assertion')
                if not any(all(row[k]==v for k,v in wanted.items()) for row in rows):
                    failures.append(f'{table}: expected row {i} not found')
    return {'case_id':case['case_id'],'goal_state_match':not failures,'failures':failures,
            'successful_tools':sorted(succeeded),'attempted_tools':sorted(attempted),
            'evidence':'database comparison; runtime provenance must be independently established'}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cases',required=True,type=Path);ap.add_argument('--case-id',required=True)
    ap.add_argument('--db',required=True,type=Path);ap.add_argument('--report',type=Path)
    a=ap.parse_args()
    cases=[json.loads(line) for line in a.cases.read_text().splitlines() if line.strip()]
    matches=[c for c in cases if c['case_id']==a.case_id]
    if len(matches)!=1: ap.error('case ID must match exactly one input case')
    with sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True) as conn: result=score(conn,matches[0])
    if a.report:a.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if result['goal_state_match'] else 1
if __name__=='__main__':raise SystemExit(main())
