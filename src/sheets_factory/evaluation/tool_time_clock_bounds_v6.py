"""Prospective literal metadata/output displays; frozen clock arithmetic unchanged.

This recognises a finite JavaScript grammar without executing it.  It changes no
historical result, runner, reward or selection.  Unknown tool kinds stay unknown.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import re

from . import tool_time_clock_bounds_v5 as v5

V5_SHA256 = 'f0f8bfeb68c778128a16cfa4753430b76819c963e36106e3735d55c6f56333b2'
METHOD = 'complete_dual_clock_envelope_with_literal_metadata_and_output_v6'
ClockEvidenceError = v5.ClockEvidenceError
NS = v5.NS
MAX_LITERAL_SLICE = 2**53-1
POLICY_V6 = {**deepcopy(v5.POLICY_V5), 'version': 6,
    'measurement': 'native_exact_or_complete_owned_overlap_literal_metadata_output_v6',
    'complete_clock_measurement': METHOD,
    'complete_clock_metadata_display': {
        'properties': ['name + space + description', 'description + space + name'],
        'regex_flags': ['', 'i'], 'map': 'unchanged name/description literal projection',
        'outer_slice': 'optional slice(0,nonnegative safe integer)',
        'maximum_literal_slice': MAX_LITERAL_SLICE,
        'metadata_only': 'whole validated read-only metadata program; wrapper wall fully counted'},
    'complete_clock_output_display': ['const r=await literal_tool(...);text(r.output);',
                                      'text((await literal_tool(...)).output);']}
_prior_account = v5.account_trial_tool_time_v5

_IDENTIFIER = r'[A-Za-z_$][\w$]*'
_META_V6 = re.compile(
    r'text\s*\(\s*ALL_TOOLS\s*\.\s*filter\s*\(\s*(?P<f>'+_IDENTIFIER+r')\s*=>\s*'
    r'/[A-Za-z0-9_| -]+/(?P<flag>i?)\s*\.\s*test\s*\(\s*(?P=f)\s*\.\s*'
    r'(?P<first>name|description)\s*\+\s*(?:" "|\' \')\s*\+\s*(?P=f)\s*\.\s*'
    r'(?P<second>name|description)\s*\)\s*\)'
    r'(?:\s*\.\s*map\s*\(\s*(?P<m>'+_IDENTIFIER+r')\s*=>\s*\(\s*\{\s*'
    r'name\s*:\s*(?P=m)\s*\.\s*name\s*,\s*description\s*:\s*(?P=m)\s*\.\s*'
    r'description\s*\.\s*slice\s*\(\s*0\s*,\s*(?P<description_limit>\d+)\s*\)\s*\}\s*\)\s*\))?'
    r'(?:\s*\.\s*slice\s*\(\s*0\s*,\s*(?P<outer_limit>\d+)\s*\))?\s*\)\s*;?')
_RESERVED = {'text','tools','Promise','ALL_TOOLS','eval', *('await break case catch class const continue debugger default delete do else enum export extends false finally for function if implements import in instanceof interface let new null package private protected public return static super switch this throw true try typeof var void while with yield'.split())}


def dependencies():
    reference = v5.v4.base._read(v5.__file__)[1]
    if reference['sha256'] != V5_SHA256:
        raise ClockEvidenceError('The frozen v5 clock algorithm changed')
    return [reference, *v5.dependencies()]


def _preprocess(code):
    """Remove only complete top-level metadata statements, never string/comment text."""
    if not isinstance(code, str):
        raise ClockEvidenceError('exec input must be code text')
    tokens = list(v5.v4.base._TOKEN.finditer(code))
    stack, spans, at = [], [], 0
    pairs = {')':'(',']':'[','}':'{'}
    while at < len(tokens):
        item = tokens[at]; token = item.group()
        if token.isspace() or token.startswith(('//','/*')):
            at += 1; continue
        if token.startswith(('"',"'")):
            if len(token) < 2 or token[-1] != token[0]:
                raise ClockEvidenceError('Unterminated literal string')
            at += 1; continue
        if code[item.start():item.start()+2] == '/*':
            raise ClockEvidenceError('Unterminated comment')
        if token == '`':
            raise ClockEvidenceError('Template-string programs are unsupported')
        if not stack and token == 'text':
            match = _META_V6.match(code, item.start())
            if match is not None:
                if match['first'] == match['second']:
                    raise ClockEvidenceError('Metadata must display name and description once each')
                if any(match[name] is not None and int(match[name]) > MAX_LITERAL_SLICE
                       for name in ('description_limit','outer_limit')):
                    raise ClockEvidenceError('Metadata slice must be a bounded safe integer')
                if any(match[name] in _RESERVED for name in ('f','m') if match[name] is not None):
                    raise ClockEvidenceError('Metadata callback bindings must not shadow reserved names')
                spans.append((item.start(), match.end()))
                while at < len(tokens) and tokens[at].start() < match.end(): at += 1
                continue
        if token in ('(', '[', '{'): stack.append(token)
        elif token in pairs:
            if not stack or stack.pop() != pairs[token]:
                raise ClockEvidenceError('Unbalanced static program delimiters')
        at += 1
    if stack:
        raise ClockEvidenceError('Truncated static program delimiters')
    pieces, offset = [], 0
    for left, right in spans:
        pieces.extend((code[offset:left], ' '*(right-left))); offset = right
    pieces.append(code[offset:])
    return ''.join(pieces), len(spans)


def _projection_suffix(variable):
    return f'text({variable}.output);' if variable not in _RESERVED else None


def _static_namespace():
    dependencies(); namespace = v5._static_namespace()
    tree = ast.parse(Path(v5.v4.base.__file__).read_bytes())
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == '_StaticExec']
    if len(classes) != 1:
        raise ClockEvidenceError('Exactly one frozen static recognizer is required')
    counts = {'preprocess':0,'text_projection':0,'reset':0,'literal_array':0,'ending':0,'metadata_only':0}
    class Displays(ast.NodeTransformer):
        def visit_Assign(self, node):
            target = [ast.unparse(t) for t in node.targets]
            if target == ['code'] and ast.unparse(node.value) == "_META.sub('', code)":
                counts['preprocess'] += 1
                return ast.parse('code, self._v6_metadata_count = _v6_preprocess(code)').body[0]
            if target == ['endings']:
                if not isinstance(node.value, ast.List) or len(node.value.elts) != 4:
                    raise ClockEvidenceError('The frozen four logging endings changed')
                counts['ending'] += 1
                extra = ('if self._v5_literal_array:\n'
                         ' extra = _v5_display_suffix(self.tokens,self.at,variable)\n'
                         'else:\n extra = _v6_projection_suffix(variable)\n'
                         'if extra is not None: endings.append(extra)')
                return [node, *ast.parse(extra).body]
            return self.generic_visit(node)
        def visit_If(self, node):
            node = self.generic_visit(node); condition = ast.unparse(node.test)
            if condition == "self.peek('text')":
                original = node.body
                direct = ast.parse("if self.tokens[self.at:self.at+3] == ['text','(','(']:\n"
                    " self.take('text'); self.take('('); self.take('('); self.take('await'); self.tool(); self.take(')'); self.take('.'); self.take('output'); self.take(')')\n"
                    "else:\n pass").body[0]
                direct.orelse = original; node.body = [direct]; counts['text_projection'] += 1
            elif condition == "self.peek('const')":
                node.body[:0] = ast.parse('self._v5_literal_array = False').body; counts['reset'] += 1
            elif condition == "self.peek('Promise')":
                node.body[:0] = ast.parse('self._v5_literal_array = True').body; counts['literal_array'] += 1
            return node
        def visit_Call(self, node):
            node = self.generic_visit(node)
            if ast.unparse(node) == "_require(self.calls, 'Exec wrapper contains no supported tool calls')":
                node.args[0] = ast.parse('self.calls or (self._v6_metadata_count > 0 and all(t == \';\' for t in self.tokens))', mode='eval').body
                counts['metadata_only'] += 1
            return node
    adapted = Displays().visit(classes[0])
    if counts != {name:1 for name in counts}:
        raise ClockEvidenceError('The exact v6 display-only substitutions changed: '+str(counts))
    namespace.update(_v6_preprocess=_preprocess, _v6_projection_suffix=_projection_suffix)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[adapted],type_ignores=[])),__file__,'exec'),namespace)
    if namespace['_native'].__globals__ is not namespace:
        raise ClockEvidenceError('Native recognizer globals escaped isolation')
    return namespace


def static_calls(code):
    return _static_namespace()['_StaticExec'](code).parse()


def _algorithm_namespace():
    namespace = v5._algorithm_namespace()
    namespace.update(_namespace=_static_namespace,dependencies=dependencies,METHOD=METHOD,__file__=__file__)
    return namespace


def account_complete_clock_overlap(result_file, *, budget_seconds=1800):
    """Run the unchanged full-census,ownership,SUM and overlap-credit algorithm."""
    receipt = _algorithm_namespace()['account_complete_clock_overlap'](result_file,budget_seconds=budget_seconds)
    receipt.update(version=6,policy_version=6,prospective_metadata_output_adapter=v5.v4.base._read(__file__)[1],
        frozen_v5_algorithm=v5.v4.base._read(v5.__file__)[1],historical_result_modified=False,qualification_claimed=False)
    if receipt.get('complete'):
        receipt['uncredited_conservative_upper_ns'] = receipt['primitive_upper_sum_ns']+receipt['wrapper_upper_sum_ns']
    return receipt


def account_trial_tool_time_v6(result_file, *, stop_receipt_file=None, budget_seconds=1800):
    """Preserve all known v5 results; unknown evidence alone uses the new grammar."""
    dependencies()
    old = _prior_account(result_file,stop_receipt_file=stop_receipt_file,budget_seconds=budget_seconds)
    if old['state'] != 'unknown':
        return {**old,'policy_version':6,'method':POLICY_V6['measurement'],
            'measurement_branch':'unchanged_v5_exact_or_bound','base_policy_v5_receipt':old,
            'prospective_metadata_output_adapter':v5.v4.base._read(__file__)[1]}
    bound = account_complete_clock_overlap(result_file,budget_seconds=budget_seconds)
    answer = {**bound,'method':POLICY_V6['measurement'],'measurement_branch':'complete_literal_metadata_output_v6',
              'base_policy_v5_receipt':old,'complete_literal_metadata_output_receipt':bound}
    if (bound.get('complete') is True and type(bound.get('cumulative_lower_bound_ns')) is int
        and bound['cumulative_lower_bound_ns'] >= Decimal(str(budget_seconds))*NS):
        answer.update(state='verified_tool_budget_lower_bound',passed=False,
                      measurement_branch='complete_literal_metadata_output_lower_bound_exhausted')
    return answer
