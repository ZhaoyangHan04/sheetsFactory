import ast
import base64
import io
import json
import zipfile
import openpyxl
import pytest
from test_recovery_witness_history import witness

from sheets_factory.workbook.composite_finance.public_recovery import (
    CONTRACT_ORDER,compile_public_composite_recovery,read_public_contracts)


def public_book():
    book=openpyxl.Workbook();sheet=book.active;sheet.title='Model Input Contracts'
    for row,name in enumerate(CONTRACT_ORDER,4):sheet.cell(row,1,name);sheet.cell(row,2,json.dumps({'parameters':{'provided_rate':'.05'}}))
    return book


def test_public_contract_requires_exact_literals_and_rejects_computed_or_local_evidence():
    book=public_book();specs,hashes=read_public_contracts(book)
    assert tuple(specs)==CONTRACT_ORDER and all(len(v)==64 for v in hashes.values())
    for payload in ['{"annual":[{"net_income":100}]}','{"parameters":{"path":"/data/private.json"}}',
                    '{"parameters":{"x":1,"x":2}}','{"source":"file:///tmp/answers.json"}']:
        book=public_book();book['Model Input Contracts']['B4']=payload
        with pytest.raises(ValueError):read_public_contracts(book)
    book=public_book();book['Model Input Contracts']['B4']='=B5'
    with pytest.raises(ValueError):read_public_contracts(book)


def test_compiler_has_deterministic_independent_ledger_allowlist_no_emitter_or_answers():
    first=compile_public_composite_recovery();assert first==compile_public_composite_recovery()
    tree=ast.parse(first)
    payloads=[node.args[0].value for node in ast.walk(tree) if isinstance(node,ast.Call)
              and isinstance(node.func,ast.Attribute) and node.func.attr=='b64decode'
              and node.args and isinstance(node.args[0],ast.Constant)]
    assert len(payloads)==1
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(payloads[0]))) as archive:
        names=archive.namelist();assert len([n for n in names if n.endswith('ledger.py')])==5
        assert 'sheets_factory/workbook/contingent_recovery/solver.py' in names
        assert not any(n.endswith(('excel.py','build.py','source.py','bindings.json')) or n.endswith('.xlsx') for n in names)
        source=ast.parse(archive.read('sheets_factory/workbook/derived_gold/ledger.py').decode())
        defaults=next(n for n in source.body if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='_DEFAULTS')
        assert all(isinstance(v,ast.Constant) and v.value is None for v in defaults.value.values)
    assert '/workspace/input.xlsx' in first and '/workspace/output.xlsx' in first
    assert 'private/entities' not in first


def test_optional_business_contracts_are_explicit_and_cannot_replace_required_inputs():
    book=public_book();sheet=book['Model Input Contracts']
    sheet['A8']='contingent';sheet['B8']=json.dumps({'annual_terms':[{'year':2024,'eligible_fraction':'.85'}]})
    sheet['A9']='waterfall';sheet['B9']=json.dumps({'opening_capital':'250000'})
    specs,hashes=read_public_contracts(book)
    assert set(specs)==set(CONTRACT_ORDER)|{'contingent','waterfall'}
    assert len(hashes)==6
    sheet['A9']='contingent'
    with pytest.raises(ValueError,match='duplicate'):read_public_contracts(book)
    sheet['A9']='hidden_answer'
    with pytest.raises(ValueError,match='Unknown'):read_public_contracts(book)


def test_composite_backend_routes_to_independent_public_compiler_and_standard_isolated_receipt(witness,monkeypatch):
    from sheets_factory.nodes.quality import RecoveryNode
    from test_recovery_witness_history import PROGRAM
    calls=[]
    def compiler():calls.append('composite');return PROGRAM
    monkeypatch.setattr('sheets_factory.workbook.composite_finance.public_recovery.compile_public_composite_recovery',compiler)
    witness.ctx.config['recovery']={'compiler_backend':'composite_journal'}
    witness.ctx.data['finance_evidence']={'financial_seed_verified':True}
    result=RecoveryNode().execute(witness.ctx)['recovery']
    assert calls==['composite'] and witness.backend.calls==[]
    assert result['verified'] is True and result['compiler_backend']=='composite_journal'
    assert result['compiler']['implementation']=='independent_decimal_composite_journals'
    assert result['compiler']['is_llm_attempt'] is False
    assert result['usage_attribution']=='not_applicable_programmatic'
    assert result['replay']['fresh_network_disabled_container'] is True
    assert set(result['replay']['initial_files'])=={'input.xlsx','recovery.py'}
    assert result['witness_binding']['input_sha256']==result['replay']['initial_files']['input.xlsx']
    assert result['attempt_record_sha256']


def test_composite_backend_rejects_unverified_source_before_compilation_or_execution(witness):
    from sheets_factory.nodes.quality import RecoveryNode
    from sheets_factory.core.node import TaskRejected
    witness.ctx.config['recovery']={'compiler_backend':'composite_journal'}
    with pytest.raises(TaskRejected,match='verified financial source'):RecoveryNode().execute(witness.ctx)
    assert witness.backend.calls==[] and witness.replay.calls==[]
