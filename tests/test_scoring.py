"""Maintainer regression tests for scoring and harness infrastructure, not solution behavior."""
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
def module(relative,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/relative)
    mod=importlib.util.module_from_spec(spec); sys.modules[name]=mod; spec.loader.exec_module(mod); return mod
policy=module('references/OP-02/policy_scorer.py','policy_scorer')
triage=module('references/OP-06/grader.py','triage_grader')
judge=module('references/OP-04/score.py','judge_score')
book=module('references/OP-05/grader.py','book_grader')
ledger=module('references/OP-03/ledger_reader.py','ledger_reader')

def entry(tool,args,result,seq):
    return {'tool':tool,'ok':1,'args_json':json.dumps(args),'result_json':json.dumps(result),'seq':seq}

@pytest.mark.parametrize('verification,customer,expected',[(False,'a',1),(True,'b',1),(True,'a',0)])
def test_verification_result_and_owner(verification,customer,expected):
    trail=[entry('verify_identity',{'customer_id':customer},verification,1),
           entry('schedule_payment',{'loan_id':'loan-a'},True,2),entry('commit',{},True,3)]
    actual=policy.violations('case',trail,{'loan-a':'a'})
    assert sum(x['rule']=='identity_before_money' for x in actual)==expected

@pytest.mark.parametrize('confidence',[float('nan'),float('inf'),-0.1,1.1,True,'0.5'])
def test_confidence_values_are_not_silently_valid(confidence):
    pred={'intent':'recover_password','action':'enter-details','confidence':confidence,'needs_human':False}
    assert not triage.schema_valid(pred,None)

def test_missing_confidence_cannot_disappear_from_calibration():
    gold=[{'id':'a','intent':'i','action':'a'},{'id':'b','intent':'i','action':'a'}]
    pred={'a':{'intent':'i','action':'a','confidence':1,'needs_human':False}}
    report=triage.grade(gold,[],[],pred,{'required':['confidence']})
    assert report['confidence']['all']['n']==2
    assert report['confidence']['all']['overall_accuracy']==0.5

def test_duplicate_ids_rejected(tmp_path):
    p=tmp_path/'bad.jsonl'; p.write_text('{"id":"a"}\n{"id":"a"}\n')
    for loader in (lambda:judge.load_jsonl(str(p)), lambda:triage.load_jsonl(str(p),'predictions'), lambda:book.load_jsonl(str(p))):
        with pytest.raises(SystemExit): loader()

def test_perfect_judge_has_undefined_discrimination():
    assert judge.auroc([1,1],[1,1]) is None
    assert judge.auroc([1,0],[0.5,0.5])==0.5

class StubJudge:
    enabled=True
    calls=0
    def ask(self,prompt):
        self.calls+=1
        if 'PASSAGE' in prompt: return 'SUPPORTS'
        if 'cannot be answered' in prompt: return 'HEDGED'
        return 'CORRECT'

def test_citation_denominator_and_missing_answers(tmp_path):
    (tmp_path/'doc.txt').write_text('The limit is 10. A different statement.')
    docs={'d':{'doc_id':'d','role':'public','text_path':'doc.txt'}}
    gold=[{'id':'a','question':'What is the limit?','expected_status':'answered','role':'public','gold_answer':'10','tags':['temporal']},
          {'id':'b','question':'Which unknown rule?','expected_status':'not_in_corpus','role':'public'}]
    pred=[{'id':'a','status':'answered','answer':'10','citations':[{'doc_id':'d','section':'s','quote':'The limit is 10.'},{'doc_id':'d','section':'s','quote':'Invented text'}]}]
    result=book.grade(gold,pred,docs,tmp_path,StubJudge())['summary']
    assert result['citation_verbatim_rate']==0.5
    assert result['citation_support_rate']==0.5
    assert result['ooc_refusal_rate']==0
    assert result['role_semantic_review_complete'] is False
    assert result['slices']['temporal']['answer_accuracy']==1

def test_judge_error_is_pending_not_incorrect_or_silently_dropped(tmp_path):
    class Broken(StubJudge):
        def ask(self,prompt): return 'ERROR'
    (tmp_path/'doc.txt').write_text('Fact')
    gold=[{'id':'a','question':'q','expected_status':'answered','role':'public','gold_answer':'Fact'}]
    pred=[{'id':'a','status':'answered','answer':'Fact','citations':[{'doc_id':'d','section':'s','quote':'Fact'}]}]
    result=book.grade(gold,pred,{'d':{'doc_id':'d','text_path':'doc.txt'}},tmp_path,Broken())['summary']
    assert result['answer_accuracy'] is None and result['citation_support_rate'] is None
    assert result['judge_errors']==2

@pytest.mark.parametrize('cost',[float('nan'),-1,None])
def test_unpriced_or_invalid_ledger_rejected(cost):
    with pytest.raises(ValueError): ledger.by_case([{'case_id':'a','input_tokens':1,'output_tokens':1,'cost_usd':cost}])

def test_deferred_goal_match_is_not_resolved(tmp_path):
    run=tmp_path/'runs.jsonl'; cost=tmp_path/'ledger.jsonl'; report=tmp_path/'report.json'
    run.write_text('{"case_id":"a","goal_state_match":true,"deferred":true,"latency_s":1}\n')
    cost.write_text('{"case_id":"a","input_tokens":1,"output_tokens":1,"cost_usd":1}\n')
    assert ledger.main(['--runs',str(run),'--ledger',str(cost),'--report',str(report)])==0
    data=json.loads(report.read_text()); assert data['resolved']==0 and data['cost_per_resolved_case'] is None


def test_goal_scorer_does_not_treat_failed_calls_as_completed():
    import sqlite3
    goals=module('references/OP-01/goal_scorer.py','goal_scorer')
    conn=sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE audit_log (seq INTEGER,case_id TEXT,tool TEXT,ok INTEGER,result_json TEXT)')
    conn.execute("INSERT INTO audit_log VALUES (1,'case','verify_identity',1,'false')")
    case={'case_id':'case','goal_state':{'audit_must_include':['verify_identity']}}
    assert not goals.score(conn,case)['goal_state_match']
    conn.execute("UPDATE audit_log SET result_json='true'")
    assert goals.score(conn,case)['goal_state_match']
    conn.execute("INSERT INTO audit_log VALUES (2,'case','forbidden',0,'null')")
    case['goal_state']['audit_must_not_include']=['forbidden']
    assert not goals.score(conn,case)['goal_state_match']
    conn.close()


def test_mandatory_escalation_is_not_an_elective_deferral(tmp_path):
    run=tmp_path/'runs.jsonl';cost=tmp_path/'ledger.jsonl';cases=tmp_path/'cases.jsonl';report=tmp_path/'report.json'
    run.write_text('{"case_id":"a","goal_state_match":true,"deferred":true,"latency_s":1}\n{"case_id":"b","goal_state_match":true,"deferred":false,"latency_s":1}\n')
    cost.write_text(''.join(json.dumps({'case_id':cid,'input_tokens':1,'output_tokens':1,'cost_usd':1})+'\n' for cid in ('a','b')))
    cases.write_text('{"case_id":"a","goal_state":{"audit_must_include":["escalate"]}}\n{"case_id":"b","goal_state":{"audit_must_include":["commit"]}}\n')
    assert ledger.main(['--runs',str(run),'--ledger',str(cost),'--cases',str(cases),'--report',str(report)])==0
    data=json.loads(report.read_text())
    assert data['deferral_rate']==0.5 and data['elective_deferral_rate']==0
    assert data['cost_per_resolved_case']==2 and data['policy_escalation_required_cases']==1

    assert data["success_rate"] == 1 and data["resolved_rate"] == 0.5


def test_inference_projection_excludes_gold_and_nested_reviewer_fields():
    inputs=module('references/evaluation_inputs.py','evaluation_inputs')
    row={'id':'a','intent':'secret','action':'secret','flow':'secret','permitted_actions':['secret'],'original_id':'secret','context':[{'speaker':'customer','text':'hello','gold':'secret'}],'turn_index':1}
    assert inputs.project('OP-06',row)=={'id':'a','turn_index':1,'context':[{'speaker':'customer','text':'hello'}]}
    row={'id':'a','question':'q','role':'public','gold_answer':'secret','expected_status':'answered'}
    assert set(inputs.project('OP-05',row))=={'id','question','role'}
    row={'id':'a','label':1,'trajectory':{'case':{'case_id':'a','customer_id':'c','message':'q','goal_state':{'secret':1}},'turns':[],'audited_tool_calls':[],'backend_rows':['secret']}}
    assert 'goal_state' not in inputs.project('OP-04',row)['trajectory']['case']
    assert 'backend_rows' not in inputs.project('OP-04',row)['trajectory']


def test_unreached_contract_regressions_remain_explicit(tmp_path):
    sys.path.insert(0,str(ROOT/'references/OP-01'))
    from contract_check import check
    h=check.Harness(check.parse_args(['--target','http://127.0.0.1:19299','--repo',str(tmp_path)]))
    report=h.report();h.http.close()
    assert {r['name'] for r in report['regressions']}==set(check.REGRESSIONS)
    assert all(r['status']=='skip' for r in report['regressions'])
    assert not report['summary']['all_run_items_passed']


def test_gateway_never_invents_missing_prices_or_usage(tmp_path):
    sys.path.insert(0,str(ROOT/'references/OP-01'))
    from contract_check import proxy
    assert proxy.cost_of({'default':(1,4),'mini':(1,4)},('mini-unknown',10,20)) is None
    assert proxy.extract_usage({'model':'m','usage':{'input_tokens':10}}) is None
    assert proxy.extract_usage({'model':'m','usage':{'input_tokens':-1,'output_tokens':2}}) is None
    assert proxy.extract_usage({'model':'m','usage':{'input_tokens':True,'output_tokens':2}}) is None
    record={};ledger=proxy.Ledger();ledger.record({},('unknown',10,20),record)
    assert record['cost_usd'] is None and record['measurement_status']=='price_unavailable'
    p=tmp_path/'prices.yaml';p.write_text('m: {input: .nan, output: 1}\n')
    with pytest.raises(ValueError):proxy.load_prices(p)
