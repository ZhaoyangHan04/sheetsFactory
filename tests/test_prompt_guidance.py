"""Text-only private audit boundaries; no workbook, source, model or pipeline IO."""
import json

import pytest

from sheets_factory.evaluation.prompt_guidance import audit_prompt_guidance


def edit(sheet='Finance',cell='B12',before='=SUM(A1:A3)',after='=0'):
    return {'sheet':sheet,'cell':cell,'before':before,'after':after}


def signals(report):return {finding['signal'] for finding in report['findings']}


def test_qualified_debugging_root_quote_dollar_and_case_normalization():
    instruction="Repair 'Cash O''Brien'!$b$12 and Finance!C13; save /app/output.xlsx."
    report=audit_prompt_guidance(instruction,mode='debugging',private_edits=[edit("Cash O'Brien"),edit('Finance','C13')])
    assert report['summary']['qualified_debugging_edit_addresses_visible']==2
    assert {'PG001','PG003','PG007'}<=signals(report)
    for finding in report['findings']:
        assert finding['severity']=='review_only'
        assert finding['excerpt']==instruction[finding['start']:min(finding['end'],finding['start']+160)]
    assert audit_prompt_guidance(instruction,mode='debugging',private_edits=[edit("Cash O'Brien"),edit('Finance','C13')])==report


def test_financial_modeling_targets_and_debugging_ranges_are_neutral_scope_not_exact_faults():
    instruction="Complete Finance!B12 and Finance!C13 in the financial model."
    report=audit_prompt_guidance(instruction,mode='financial_modeling',private_edits=[edit()])
    assert 'PG001' not in signals(report)
    assert next(f for f in report['findings'] if f['signal']=='PG003')['details']['financial_modeling_target_scope_is_legitimate'] is True
    ranged=audit_prompt_guidance('Review Finance!A1:B20.',mode='debugging',private_edits=[edit()])
    assert 'PG003' in signals(ranged) and 'PG001' not in signals(ranged)


def test_bare_cells_need_explicit_context_and_do_not_establish_a_worksheet():
    hidden=[edit('Private','B12'),edit('Other','B12'),edit('Year','FY2024')]
    plain=audit_prompt_guidance('The FY2024 cash policy requires business review.',mode='debugging',private_edits=hidden)
    assert not ({'PG001','PG008'}&signals(plain))
    code=audit_prompt_guidance('Inspect cell B12 or `B12`.',mode='debugging',private_edits=hidden)
    assert 'PG008' in signals(code) and 'PG001' not in signals(code)
    assert all(f['details'].get('worksheet_not_established') is True for f in code['findings'] if f['signal']=='PG008')


def test_repair_formula_signal_preserves_excel_text_literals_and_intersection_spaces():
    instruction='Try `=sum(A1:A3)` and `=IF(A1="YES",1,0)`.'
    report=audit_prompt_guidance(instruction,mode='debugging',private_edits=[edit(),edit('F','A1','=IF(A1="YES",1,0)')])
    assert sum(f['signal']=='PG002' for f in report['findings'])==2
    different=audit_prompt_guidance('Use `=IF(A1="yes",1,0)` or `=SUM(A1A2)`.',mode='debugging',
        private_edits=[edit(before='=IF(A1="YES",1,0)'),edit('F','C1','=SUM(A1 A2)')])
    assert 'PG002' not in signals(different)
    partial=audit_prompt_guidance('Use `=10` or `=SUM(A1:A3)+1`.',mode='debugging',private_edits=[edit(before='=1'),edit('F','C1')])
    assert 'PG002' not in signals(partial)


def test_escaped_formula_quotes_and_whole_formula_lines_are_supported():
    text='=IF(A1="say ""YES""",2,0)\n'
    report=audit_prompt_guidance(text,mode='debugging',private_edits=[edit(before='=if(A1="say ""YES""",2,0)')])
    assert 'PG002' in signals(report)
    assert 'PG002' not in signals(audit_prompt_guidance(text,mode='debugging',private_edits=[edit(before='=IF(A1="say ""yes""",2,0)')]))


def test_surviving_public_formula_is_context_instead_of_automatic_gold_leak():
    report=audit_prompt_guidance('The provided worksheet retains `=SUM(A1:A3)`.',mode='debugging',
        private_edits=[edit()],public_formula_texts=['=sum(A1:A3)'])
    assert 'PG005' in signals(report) and 'PG002' not in signals(report)
    assert report['gold_leak_verdict'] is None
    reference=audit_prompt_guidance('The public workbook retains `=SUM(Finance!B12,Finance!C13)`.',mode='debugging',
        private_edits=[edit(),edit('Finance','C13')],public_formula_texts=['=SUM(Finance!B12,Finance!C13)'])
    assert 'PG005' in signals(reference) and not ({'PG001','PG003','PG008'}&signals(reference))


@pytest.mark.parametrize('text',[
    'Assume a 0/1 switch and a one-year collection lag.',
    '{"assumptions":{"switch":1,"round":0}}',
    '```json\n{"schema_version":true,"projects":[{}],"years":[2024]}\n```',
    '```json\n{"schema_version":1,"schema_version":2,"projects":[{}],"years":[2024]}\n```',
    '```json\n{"schema_version":1,"projects":[{}],"years":[NaN]}\n```',
    'Ordinary prose with {braces}, not a machine contract.',
])
def test_prose_binary_assumptions_and_invalid_json_are_not_machine_schemas(text):
    assert 'PG004' not in signals(audit_prompt_guidance(text,mode='debugging',public_contract_texts=[text]))


def test_only_explicit_parsed_contract_syntax_is_reported_with_public_offsets():
    payload=json.dumps({'schema_version':1,'projects':[{'id':'P01'}],'years':[2024]})
    instruction='Apply the public rules.\n```json\n'+payload+'\n```\nSave /app/output.xlsx.'
    report=audit_prompt_guidance(instruction,mode='debugging',public_contract_texts=['  '+payload+'  '])
    found=[f for f in report['findings'] if f['signal']=='PG004']
    assert len(found)==2
    assert all(f['details']['parsed_explicit_public_JSON'] and f['details']['contract_completeness_verified'] is False for f in found)
    supplied=next(f for f in found if f['source']=='public_contract_texts[0]')
    assert supplied['start']==2 and supplied['excerpt']==payload
    assert 'PG004' not in signals(audit_prompt_guidance('An unfenced example '+payload,mode='debugging'))


def test_json_schema_is_recognized_without_claiming_financial_completeness():
    payload='{"$schema":"https://example.invalid/schema","properties":{"cash":{"type":"integer"}}}'
    report=audit_prompt_guidance('Use the supplied public definition.',mode='financial_modeling',public_contract_texts=[payload])
    assert 'PG004' in signals(report) and report['difficulty_verdict'] is None


def test_assumptions_submission_and_semantic_scope_have_neutral_signals():
    text='Given the fixed plan, round monthly interest to pence. Preserve worksheets and save /app/output.xlsx.'
    report=audit_prompt_guidance(text,mode='debugging')
    assert {'PG006','PG007','PG009'}<=signals(report)
    assert all(f['details'].get('neutral_context_only') for f in report['findings'])
    assert report['automatic_Q01_Q02_verdict'] is False and report['prompts_or_policies_modified'] is False


def test_private_edits_and_unmatched_formulas_never_appear_in_report():
    private=[edit('DO_NOT_EXPORT_THIS_SHEET','XFD1048576','=SECRET_GOLD_FUNCTION(918273645)','=PRIVATE_BAD_FORMULA()')]
    report=audit_prompt_guidance('Repair the financial policy. Read /app/input.xlsx; save /app/output.xlsx.',mode='debugging',private_edits=private)
    encoded=json.dumps(report)
    assert all(hidden not in encoded for hidden in ('DO_NOT_EXPORT_THIS_SHEET','XFD1048576','SECRET_GOLD','918273645','PRIVATE_BAD'))
    assert report['private_only'] is True and report['public_export_allowed'] is False
    assert report['private_edit_records_serialized'] is False and report['goal_or_gold_values_read'] is False
    assert report['coverage_complete'] is False and report['no_finding_is_not_proof_of_absence'] is True


def test_unicode_offsets_excerpt_cap_and_stable_ids():
    text='业务约束：\nFinance!B12 '+('business ' * 30)+' Finance!C13'
    report=audit_prompt_guidance(text,mode='debugging',private_edits=[edit(),edit('Finance','C13')])
    assert len({f['id'] for f in report['findings']})==len(report['findings'])
    for finding in report['findings']:
        assert finding['excerpt']==text[finding['start']:min(finding['end'],finding['start']+160)]
    assert next(f for f in report['findings'] if f['signal']=='PG003')['excerpt_truncated'] is True
    assert report['offset_unit']=='Unicode code points'


@pytest.mark.parametrize('kwargs',[
    {'mode':'other'},{'mode':'debugging','instruction':None},
    {'mode':'debugging','private_edits':[edit(cell='XFE1')]},
    {'mode':'debugging','private_edits':[edit(cell='A1048577')]},
    {'mode':'debugging','private_edits':[edit(),edit('finance','$B$12')]},
    {'mode':'debugging','public_contract_texts':'not a sequence'},
    {'mode':'debugging','public_formula_texts':[None]},
])
def test_malformed_inputs_fail_explicitly(kwargs):
    values={'instruction':'Public instruction',**kwargs}
    with pytest.raises(ValueError):audit_prompt_guidance(**values)


def test_explicit_text_bounds_are_enforced(monkeypatch):
    import sheets_factory.evaluation.prompt_guidance as module
    monkeypatch.setattr(module,'MAX_TEXT_CHARACTERS',16)
    with pytest.raises(ValueError):audit_prompt_guidance('x'*17,mode='debugging')
    with pytest.raises(ValueError):audit_prompt_guidance('Public',mode='debugging',public_contract_texts=['x'*17])
    monkeypatch.setattr(module,'MAX_TOTAL_CHARACTERS',20)
    with pytest.raises(ValueError):audit_prompt_guidance('Public',mode='debugging',public_contract_texts=['x'*10],public_formula_texts=['=SUM(A1:A3)'])


def test_audit_never_opens_workbooks_goals_or_any_file(monkeypatch):
    from pathlib import Path
    def forbidden(*args,**kwargs):raise AssertionError('No file IO is authorized by this text audit')
    monkeypatch.setattr('builtins.open',forbidden)
    monkeypatch.setattr(Path,'read_bytes',forbidden);monkeypatch.setattr(Path,'read_text',forbidden)
    report=audit_prompt_guidance('Read /app/input.xlsx; save /app/output.xlsx.',mode='debugging',
        private_edits=[edit('PRIVATE_TARGET','B12','=PRIVATE_GOLD()',None)])
    assert report['goal_or_gold_values_read'] is False and 'PRIVATE_GOLD' not in json.dumps(report)
