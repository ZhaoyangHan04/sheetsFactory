"""Explicit public input precedence through ordinary plan and repair nodes."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from ..core.node import BaseNode, TaskRejected
from ..nodes.construction import PlanNode
from ..nodes.quality import RepairNode

RULE = ('Scenario-specific values in the labelled input sheets govern timing, rates and amounts '
        'whenever a narrative brief gives a different default.')
POLICY = 'public_input_priority'


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha(path)}


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def checked(record):
    require(isinstance(record, dict) and isinstance(record.get('path'), str), 'Missing public-priority artifact reference')
    path = Path(record['path']).resolve()
    require(path.is_file() and sha(path) == record.get('sha256'), 'Changed public-priority artifact: ' + str(path))
    return path


def read(record):
    return json.loads(checked(record).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, default=str)
        stream.write('\n')


def equivalent(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(equivalent(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(equivalent(a, b) for a, b in zip(left, right))
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if left is None or right is None:
        return left is right
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except Exception:
        return left == right


def audit_source(seed, source_scan, output):
    """Recheck public conflict and replay the unchanged numeric reference, without LO."""
    import openpyxl
    from ..workbook.lease_finance.ledger import simulate_lease
    from ..workbook.derived_regulatory.ledger import simulate
    from ..workbook.contingent_recovery.validate import audit_contingent_workbook
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    source = ref(seed['local_path'])
    require(source['sha256'] == seed['sha256'], 'Source SHA differs during public-priority preparation')
    scan = read(source_scan)
    findings = [f for f in scan.get('findings', []) if f.get('source', {}).get('sha256') == source['sha256']]
    require(len(findings) == 1, 'Source has no unique program conflict scan finding')
    finding = findings[0]
    require(checked(finding['source']) == checked(source) and finding.get('source_unchanged') is True,
            'Conflict scan source differs')
    manifest_ref = seed.get('source_manifest') or seed.get('finance_evidence', {}).get('source_manifest')
    manifest_path = checked(manifest_ref)
    manifest = read(manifest_ref)
    scenarios_ref = manifest['public_scenarios']
    specs = read(scenarios_ref)
    book = openpyxl.load_workbook(source['path'], data_only=True, read_only=True)
    try:
        structured = finding['structured_parameter'];labelled = finding['labelled_input'];narrative = finding['narrative']
        public_programme = json.loads(book[structured['sheet']][structured['cell']].value)
        value = public_programme['parameters']['claim_lag_years']
        table_value = book[labelled['sheet']][labelled['value_cell']].value
        require(public_programme == specs['programme'] and type(value) is int and type(table_value) in (int,float)
                and value == table_value == structured['value'] == labelled['value'], 'Public labelled and JSON timing inputs disagree')
        require(book[labelled['sheet']][labelled['label_cell']].value == labelled['label']
                and book[narrative['sheet']][narrative['cell']].value == narrative['text'], 'Scanned public contract text changed')
        require('two-year collection lag' in narrative['text'] and 'two years after its creation' in narrative['text'],
                'Only the program-audited claim-lag default conflict is supported')
        require(type(finding.get('confirmed_conflict')) is bool and finding['confirmed_conflict'] == (value != 2),
                'Program conflict classification differs from the public inputs')
    finally:
        book.close()
    lease = simulate_lease(specs['lease'])
    programme = simulate(specs['programme'], external_lease_annual=lease['annual'], contingent_spec=specs['contingent'])
    original_path = manifest_path.parent / 'private/programme_ledger.json'
    original = json.loads(original_path.read_text())
    annual = programme['contingent_recovery']['annual']
    require(set(annual) == set(range(2024,2044)), 'Numeric replay does not cover all twenty reporting years')
    require(all(equivalent(row, original['contingent_recovery']['annual'][str(year)]) for year,row in annual.items()),
            'Numeric policy replay differs from the original independent reference')
    bindings_path = manifest_path.parent / 'private/programme_bindings.json'
    bindings = json.loads(bindings_path.read_text())['contingent_binding']
    actual_audit = audit_contingent_workbook(source['path'], specs['contingent'], programme, bindings)
    require(actual_audit.get('passed') is True and actual_audit.get('checked_cells') == 180
            and not actual_audit.get('mismatches') and not actual_audit.get('control_mismatches'),
            'Reference caches do not follow the supplied numeric policy')
    write(output / 'actual_reference_audit.json', actual_audit)
    proof = {'kind':'public_numeric_priority_reference_replay','source':source,
        'source_manifest':deepcopy(manifest_ref),'public_scenarios':deepcopy(scenarios_ref),
        'original_programme_ledger':ref(original_path),'programme_bindings':ref(bindings_path),
        'annual_results':annual,'all_twenty_years_equal_original':True,
        'actual_reference_audit':ref(output/'actual_reference_audit.json'), 'LO_calls':0,'model_calls':0}
    write(output / 'numeric_reference_proof.json', proof)
    record = {'source':source,'source_scan':deepcopy(source_scan),'finding':finding,
        'numeric_reference_proof':ref(output/'numeric_reference_proof.json'),
        'confirmed_conflict':finding['confirmed_conflict'],'labelled_and_JSON_inputs_agree':True,
        'reference_matches_numeric_policy':True, 'quality_or_difficulty_certified':False}
    write(output / 'source_priority_audit.json', record)
    return ref(output / 'source_priority_audit.json')


def validate_source_record(record_reference):
    record = read(record_reference)
    checked(record['source']);scan = read(record['source_scan'])
    require(record['finding'] in scan.get('findings', []) and record['finding']['source']['sha256'] == record['source']['sha256'],
            'Priority source scan binding differs')
    require(type(record.get('confirmed_conflict')) is bool
            and record['confirmed_conflict'] == record['finding'].get('confirmed_conflict'),
            'Priority conflict classification differs from its program scan')
    require(record.get('labelled_and_JSON_inputs_agree') is True and record.get('reference_matches_numeric_policy') is True,
            'Public input or numeric reference evidence is incomplete')
    proof = read(record['numeric_reference_proof'])
    require(proof.get('source') == record['source'] and proof.get('all_twenty_years_equal_original') is True,
            'Numeric reference proof is bound to another source')
    for name in ('source_manifest','public_scenarios','original_programme_ledger','programme_bindings'):
        checked(proof[name])
    annual = proof.get('annual_results', {})
    require(set(annual) == {str(y) for y in range(2024,2044)}, 'Numeric proof reporting-year coverage differs')
    original = read(proof['original_programme_ledger'])['contingent_recovery']['annual']
    for year, row in annual.items():
        p = row.get('proof', {})
        require(equivalent(row, original[year]) and row.get('unique_fixed_point') is True
                and p.get('unique_on_entire_contractual_grid') is True and p.get('endpoint_coalescence') is True
                and equivalent(p.get('lower_fixed_point'), row.get('variable_rent_total'))
                and equivalent(p.get('upper_fixed_point'), row.get('mapped_variable_rent_total'))
                and equivalent(row.get('variable_rent_total'), row.get('mapped_variable_rent_total')),
                'Numeric reference lacks a complete same-state endpoint proof')
    audit = read(proof['actual_reference_audit'])
    require(audit.get('passed') is True and audit.get('checked_cells') == 180
            and not audit.get('mismatches') and not audit.get('control_mismatches'), 'Numeric reference audit is incomplete')
    return record


def binding(ctx):
    setting = ctx.config.get(POLICY)
    if setting is None:
        return None, None
    require(setting.get('version') == 1 and setting.get('rule') == RULE, 'Unsupported public input priority policy')
    manifest = read(setting['manifest'])
    require(manifest.get('kind') == 'public_input_priority_binding' and manifest.get('rule') == RULE,
            'Public priority binding manifest differs')
    source_sha = ctx.data.get('source_id', sha(ctx.source))
    record_ref = manifest.get('sources', {}).get(source_sha)
    if record_ref is None:
        return manifest, None
    record = validate_source_record(record_ref)
    require(record['source']['sha256'] == source_sha == sha(ctx.source), 'Priority source identity changed')
    return manifest, record


def append_rule(plan):
    result = deepcopy(plan)
    rules = result.get('public_rules')
    require(isinstance(rules,list), 'A public priority rule requires ordinary public_rules')
    if RULE not in rules:
        rules.append(RULE)
    return result


class PriorityPlanNode(BaseNode):
    node_id = 'plan'

    def execute(self, ctx):
        _, record = binding(ctx)
        result = PlanNode().execute(ctx)
        if record is None:
            return result
        plan = append_rule(result['plan'])
        ctx.save('public_input_priority_application.json', {'rule':RULE,'source':record['source'],
            'numeric_reference_proof':record['numeric_reference_proof'], 'changed_plan_fields':['public_rules'],
            'before_plan_sha256':canonical(result['plan']),'after_plan_sha256':canonical(plan),
            'quality_or_difficulty_certified':False})
        return {**result,'plan':plan}


class PriorityRepairNode(BaseNode):
    node_id = 'repair'

    def execute(self, ctx):
        manifest, record = binding(ctx)
        authorization = (manifest or {}).get('tasks', {}).get(ctx.task_id)
        if record is None or not record.get('confirmed_conflict') or authorization is None:
            return RepairNode().execute(ctx)
        routes = ctx.data.get('repair_routes', [])
        allowed = set(authorization['authorized_issue_ids'])
        if not routes or any(route.get('issue_id') not in allowed or route.get('problem_id') != 'Q02'
                             or route.get('route_class') != 'repair' for route in routes):
            return RepairNode().execute(ctx)
        require(ctx.revision == authorization['revision'] and authorization['source_sha256'] == record['source']['sha256'],
                'Stale public-priority repair authorization')
        for name in ('plan','baseline','goal','input','instruction','diagnosis','program_review'):
            checked(authorization[name])
        require(canonical(ctx.data['plan']) == canonical(read(authorization['plan'])), 'Public-priority repair plan changed')
        require(authorization['baseline']['sha256'] == authorization['goal']['sha256'] == record['source']['sha256'],
                'Public-priority repair cannot change the immutable numeric reference')
        require(hashlib.sha256(checked(authorization['input']).read_bytes() + checked(authorization['instruction']).read_bytes()).hexdigest()
                == authorization['revision_hash'], 'Public-priority repair public revision changed')
        original_diagnosis = read(authorization['diagnosis'])
        original_issues = {issue['issue_id']:issue for issue in original_diagnosis.get('issues', [])}
        review = read(authorization['program_review'])
        require(review.get('task_id') == ctx.task_id and review.get('revision') == ctx.revision,
                'Program review belongs to another task or revision')
        require(all(issue.get('task_id') == ctx.task_id and issue.get('revision') == ctx.revision
                    and issue.get('revision_hash') == authorization['revision_hash'] for issue in review['issues']),
                'Program review public revision binding differs')
        issues = {**original_issues, **{issue['issue_id']:issue for issue in review['issues']}}
        require(any(issue['problem_id'] == 'Q02' and issue.get('certainty') == 'confirmed' for issue in review['issues']),
                'Priority repair requires the program-confirmed Q02 issue')
        require(all(issues.get(route['issue_id'], {}).get('certainty') == 'confirmed' for route in routes),
                'Unconfirmed issue in deterministic priority repair')
        require(all(issues[route['issue_id']].get('problem_id') == route['problem_id']
                    and route.get('route_id') == 'R02'
                    for route in routes), 'Priority route differs from the bound issue or route catalog')
        proposed = append_rule(ctx.data['plan'])
        if proposed == ctx.data['plan']:
            raise TaskRejected('Public priority rule already present; no deterministic repair progress')
        ctx.save('public_input_priority_repair.json', {'rule':RULE,'assigned_issue_ids':[r['issue_id'] for r in routes],
            'changed_plan_fields':['public_rules'],'source':record['source'],'revision_before':ctx.revision,
            'old_diagnostic_clearance_claimed':False,'requires_full_new_revision_quality':True,
            'reuse_old_harbor_controls':False,'numeric_reference_unchanged':True})
        return {'next_plan':proposed}
