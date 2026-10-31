"""Prospective display-suffix support; all frozen clock algorithms stay intact.

This module measures evidence only. It neither changes historical selections
nor applies rewards. A future runner must explicitly freeze this policy first.
"""
from __future__ import annotations
import ast
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import re
from types import FunctionType

from . import tool_time_clock_bounds_v4 as v4
from . import linear_capital_scaled_frontier_v4 as prior

V4_SHA256 = '2552cc167641da6cd86da267c01f7674348d44555695cc7cec75dd23b81a5a49'
PRIOR_SHA256 = '8db68c60c6ae3260c1b4114c394e697e0dad81040ad15d733779242b189e1ce2'
METHOD = 'complete_dual_clock_envelope_with_literal_result_display_v5'
ClockEvidenceError = v4.ClockEvidenceError
NS = v4.NS
POLICY_V5 = {**deepcopy(prior.POLICY_V4), 'version': 5,
    'measurement': 'native_exact_or_complete_owned_overlap_literal_display_v5',
    'complete_clock_measurement': METHOD,
    'complete_clock_result_display': 'terminal alpha-equivalent result.forEach((value,index)=>text({index,...value})); after an awaited literal Promise array only'}
_prior_account = prior.account_trial_tool_time_v4


def dependencies():
    records = [v4.base._read(v4.__file__)[1], v4.base._read(prior.__file__)[1]]
    if records[0]['sha256'] != V4_SHA256 or records[1]['sha256'] != PRIOR_SHA256:
        raise ClockEvidenceError('The frozen v4 clock algorithm or prior timing policy changed')
    return [*records, *v4.dependencies()]


def _display_suffix(tokens, position, variable):
    """Recognize one terminal data-display expression, never evaluate user JS."""
    remaining = tokens[position:]
    if len(remaining) != 21:
        return None
    value, index = remaining[5], remaining[7]
    reserved = {'text', 'tools', 'Promise', 'ALL_TOOLS', 'eval', *('await break case catch class const continue debugger default delete do else enum export extends false finally for function if implements import in instanceof interface let new null package private protected public return static super switch this throw true try typeof var void while with yield'.split())}
    if (variable == 'text' or ['const', 'text', '='] in [tokens[i:i+3] for i in range(position)]
        or value == index or any(not re.fullmatch(r'[A-Za-z_$][\w$]*', p) or p in reserved
                             for p in (value, index))):
        return None
    suffix = f'{variable}.forEach(({value},{index})=>text({{{index},...{value}}}));'
    expected = [m.group() for m in v4.base._TOKEN.finditer(suffix) if not m.group().isspace()]
    return suffix if remaining == expected else None


def _static_namespace():
    """Copy the guarded recognizer; append only the exact new logging ending."""
    dependencies(); namespace = v4._namespace()
    tree = ast.parse(Path(v4.base.__file__).read_bytes()); classes = [n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == '_StaticExec']
    if len(classes) != 1:
        raise ClockEvidenceError('Exactly one frozen static recognizer is required')
    counts = {'reset': 0, 'literal_array': 0, 'ending': 0}
    class DisplayOnly(ast.NodeTransformer):
        def visit_If(self, node):
            node = self.generic_visit(node)
            condition = ast.unparse(node.test)
            if condition == "self.peek('const')":
                node.body[:0] = ast.parse('self._v5_literal_array = False').body; counts['reset'] += 1
            elif condition == "self.peek('Promise')":
                node.body[:0] = ast.parse('self._v5_literal_array = True').body; counts['literal_array'] += 1
            return node
        def visit_Assign(self, node):
            if [ast.unparse(t) for t in node.targets] != ['endings']:
                return self.generic_visit(node)
            if not isinstance(node.value, ast.List) or len(node.value.elts) != 4:
                raise ClockEvidenceError('The frozen four logging endings changed')
            counts['ending'] += 1
            return [node, *ast.parse('if self._v5_literal_array:\n extra = _v5_display_suffix(self.tokens, self.at, variable)\n if extra is not None: endings.append(extra)').body]
    adapted = DisplayOnly().visit(classes[0])
    if counts != {'reset': 1, 'literal_array': 1, 'ending': 1}:
        raise ClockEvidenceError('The narrow display-ending adaptation changed: '+str(counts))
    namespace['_v5_display_suffix'] = _display_suffix
    exec(compile(ast.fix_missing_locations(ast.Module(body=[adapted], type_ignores=[])), __file__, 'exec'), namespace)
    # v4._namespace already bound this function to this private dictionary.
    if namespace['_native'].__globals__ is not namespace:
        raise ClockEvidenceError('Native recognizer globals escaped isolation')
    return namespace


def static_calls(code):
    return _static_namespace()['_StaticExec'](code).parse()


def _algorithm_namespace():
    dependencies(); namespace = dict(vars(v4))
    for name, function in list(namespace.items()):
        if isinstance(function, FunctionType) and function.__globals__ is vars(v4):
            if function.__closure__ is not None:
                raise ClockEvidenceError('An unhandled clock closure cannot be isolated')
            copied = FunctionType(function.__code__, namespace, function.__name__, function.__defaults__)
            copied.__kwdefaults__ = deepcopy(function.__kwdefaults__); namespace[name] = copied
    namespace.update(_namespace=_static_namespace, dependencies=dependencies, METHOD=METHOD, __file__=__file__)
    return namespace


def account_complete_clock_overlap(result_file, *, budget_seconds=1800):
    """Run the complete unchanged envelope/ownership/credit algorithm privately."""
    receipt = _algorithm_namespace()['account_complete_clock_overlap'](result_file, budget_seconds=budget_seconds)
    receipt.update(version=5, policy_version=5, prospective_result_display_adapter=v4.base._read(__file__)[1],
        frozen_v4_algorithm=v4.base._read(v4.__file__)[1], historical_result_modified=False, qualification_claimed=False)
    if receipt.get('complete'):
        receipt['uncredited_conservative_upper_ns'] = receipt['primitive_upper_sum_ns']+receipt['wrapper_upper_sum_ns']
    return receipt


def account_trial_tool_time_v5(result_file, *, stop_receipt_file=None, budget_seconds=1800):
    """Keep known exact failures; incomplete/straddling evidence stays unknown."""
    dependencies()
    old = _prior_account(result_file, stop_receipt_file=stop_receipt_file, budget_seconds=budget_seconds)
    if old['state'] != 'unknown':
        return {**old, 'policy_version': 5, 'method': POLICY_V5['measurement'],
            'measurement_branch': 'unchanged_v4_exact_or_bound', 'base_policy_v4_receipt': old,
            'prospective_result_display_adapter': v4.base._read(__file__)[1]}
    bound = account_complete_clock_overlap(result_file, budget_seconds=budget_seconds)
    answer = {**bound, 'method': POLICY_V5['measurement'], 'measurement_branch': 'complete_literal_result_display_v5',
        'base_policy_v4_receipt': old, 'complete_literal_display_receipt': bound}
    if (bound.get('complete') is True and type(bound.get('cumulative_lower_bound_ns')) is int
        and bound['cumulative_lower_bound_ns'] >= Decimal(str(budget_seconds))*NS):
        answer.update(state='verified_tool_budget_lower_bound', passed=False,
            measurement_branch='complete_literal_display_lower_bound_exhausted')
    return answer
