#!/usr/bin/env python3
"""Supplement F11 timing evidence. Never change a frozen clock or task result."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sheets_factory.evaluation import tool_time_clock_bounds_v6 as prior

V6_SHA = 'fb6f3a54cf36562eb10d02699e8e8f5b8fe83f8b83f2b0509e84893f9e220cb8'
METHOD = 'supplemental_complete_v6_clock_with_exact_array_value_display_v1'
TASK = 'fm-f11-f7a3b39b327a92e5ed0b'
ERROR = prior.ClockEvidenceError


def reference(path):
    path = Path(path).resolve(strict=True)
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def dependencies():
    pin = reference(prior.__file__)
    if pin['sha256'] != V6_SHA:
        raise ERROR('Frozen v6 code changed')
    return [pin, *prior.dependencies()]


def _display_suffix(tokens, position, variable):
    original = prior.v5._display_suffix(tokens, position, variable)
    if original is not None:
        return original
    suffix = tokens[position:]
    if len(suffix) != 12:
        return None
    value = suffix[4]
    if (not re.fullmatch(r'[A-Za-z_$][\w$]*', value) or value in prior._RESERVED
        or value == variable or variable in prior._RESERVED
        or any(tokens[i:i+3] == ['const', 'text', '='] for i in range(position))):
        return None
    expression = f'{variable}.forEach({value}=>text({value}));'
    expected = [m.group() for m in prior.v5.v4.base._TOKEN.finditer(expression) if not m.group().isspace()]
    return expression if suffix == expected else None


def _static_namespace():
    dependencies()
    namespace = prior._static_namespace()
    if namespace.get('_v5_display_suffix') is not prior.v5._display_suffix:
        raise ERROR('Frozen literal-array display seam changed')
    namespace['_v5_display_suffix'] = _display_suffix
    if namespace['_native'].__globals__ is not namespace:
        raise ERROR('Recognizer escaped its private namespace')
    return namespace


def static_calls(code):
    return _static_namespace()['_StaticExec'](code).parse()


def measure(result, *, budget_seconds=1800):
    """Reuse the complete unchanged primitive/coverage/SUM/overlap algorithm."""
    namespace = prior._algorithm_namespace()
    namespace.update(_namespace=_static_namespace, dependencies=dependencies, METHOD=METHOD)
    bound = namespace['account_complete_clock_overlap'](result, budget_seconds=budget_seconds)
    bound.update(supplemental_method=METHOD, original_v6_result_modified=False,
                 qualification_claimed=False, supplemental_code=reference(__file__))
    return bound


def wrapper_comparison(result):
    files = sorted((Path(result).parent / 'agent/sessions').rglob('*.jsonl'))
    if not files:
        raise ERROR('Native sessions are absent')
    before = [reference(p) for p in files]
    rows = []
    for path in files:
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            item = json.loads(line)
            payload = item.get('payload', {})
            if item.get('type') != 'response_item' or payload.get('type') != 'custom_tool_call' or payload.get('name') != 'exec':
                continue
            code = payload.get('input')
            try:
                original = prior.static_calls(code)
                prior_problem = None
            except ERROR as error:
                original, prior_problem = None, str(error)
            extended = static_calls(code)
            if original is not None and original != extended:
                raise ERROR('An already recognized wrapper changed primitive ownership')
            rows.append({'session': str(path.resolve()), 'line': line_number,
                         'call_id': payload['call_id'], 'code_sha256': hashlib.sha256(code.encode()).hexdigest(),
                         'v6_recognized': original is not None, 'v6_problem': prior_problem,
                         'unchanged_primitive_dispatches': original == extended if original is not None else None,
                         'primitive_count': len(extended), 'new_display_only': original is None})
    if [reference(p) for p in files] != before:
        raise ERROR('Native session changed during comparison')
    return {'sessions': before, 'wrappers': rows, 'wrapper_count': len(rows),
            'v6_already_recognized': sum(r['v6_recognized'] for r in rows),
            'new_display_wrappers': sum(r['new_display_only'] for r in rows)}


def supplement(result, confirmation):
    result = Path(result).resolve(strict=True)
    confirmation = Path(confirmation).resolve(strict=True)
    result_ref, terminal_ref = reference(result), reference(confirmation)
    native = json.loads(result.read_text())
    terminal = json.loads(confirmation.read_text())
    matches = [r for r in terminal.get('results', []) if r.get('task_id') == TASK]
    if (terminal.get('phase') != 'confirmation' or len(matches) != 1
        or native.get('task_name') != 'sheetsfactory/' + TASK):
        raise ERROR('Expected the exact original F11 confirmation attempt')
    attempt = matches[0]['actual_attempt']
    if (Path(attempt['result_file']).resolve() != result or attempt['result_sha256'] != result_ref['sha256']
        or attempt['tool_time'].get('state') != 'unknown'
        or attempt['tool_time'].get('policy_version') != 6):
        raise ERROR('Original F11/v6 UNKNOWN binding changed')
    comparison = wrapper_comparison(result)
    if (comparison['wrapper_count'], comparison['v6_already_recognized'], comparison['new_display_wrappers']) != (22, 21, 1):
        raise ERROR('Expected exactly twenty-one unchanged wrappers and one display extension')
    added = [r for r in comparison['wrappers'] if r['new_display_only']][0]
    if added['code_sha256'] != '1816a80f40cdd6f1b9fe455aa16e623eac9d09a9298927f3ec2df57572ce90b1' or added['primitive_count'] != 2:
        raise ERROR('The predeclared display-only wrapper changed')
    bound = measure(result)
    if reference(result) != result_ref or reference(confirmation) != terminal_ref:
        raise ERROR('Original result or terminal changed during analysis')
    return {'kind': 'readonly_F11_supplemental_complete_tool_time_evidence', 'version': 1,
            'task_id': TASK, 'result': result_ref, 'original_confirmation': terminal_ref,
            'material_identity': deepcopy(matches[0]['material_identity']),
            'retained_trial_resources': deepcopy(matches[0]['resources']),
            'recipes': [reference(__file__), *dependencies()],
            'original_v6_tool_time': deepcopy(attempt['tool_time']), 'wrapper_comparison': comparison,
            'supplemental_clock': bound, 'original_v6_unknown_preserved': True,
            'original_scores_modified': False, 'qualification_claimed': False,
            'new_native_calls': 0, 'new_model_calls': 0}


def validate_supplement(receipt_ref):
    """Cold replay the complete supplement; a JSON passed flag is insufficient."""
    expected = receipt_ref if isinstance(receipt_ref, dict) else None
    path = expected['path'] if expected is not None else receipt_ref
    actual = reference(path)
    if expected is not None and actual != expected:
        raise ERROR('Supplement receipt reference changed')
    stored = json.loads(Path(path).read_text())
    if (stored.get('kind') != 'readonly_F11_supplemental_complete_tool_time_evidence'
        or stored.get('version') != 1):
        raise ERROR('Unknown supplemental receipt')
    for dependency in stored['recipes']:
        if reference(dependency['path']) != dependency:
            raise ERROR('Supplement dependency changed')
    replay = supplement(stored['result']['path'], stored['original_confirmation']['path'])
    if replay != stored or reference(path) != actual:
        raise ERROR('Complete supplemental replay differs')
    return replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--confirmation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    receipt = supplement(args.result, args.confirmation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(receipt, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps(reference(args.output)))


if __name__ == '__main__':
    main()
