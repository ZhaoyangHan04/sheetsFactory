"""Real cohort identities over the frozen, unchanged report vocabulary."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace

ROOT=Path(__file__).resolve().parents[4]
CONTRACT=ROOT/'config/operating_reports_financial_cohort_v1.json'
CONTRACT_SHA256='a31cf82e6273c17c287dbb842f84904cdffa35a5b0a9835e0b4821ec1ef2c4e4'
KIND='hypothetical_operating_reports_financial_cohort_specification'
RESULT_KIND='hypothetical_operating_reports_financial_cohort_values'
VERSION=1
ALLOWED_SEEDS=tuple(range(202711201,202711210))


def reference(path):
    path=Path(path).resolve();raw=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def contract():
    raw=CONTRACT.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=CONTRACT_SHA256:
        raise ValueError('The complete predeclared financial cohort contract changed')
    return json.loads(raw)


def checked_source(name):
    row=contract()['frozen_ancestors'][name]
    if reference(row['path'])!=row:
        raise ValueError('A complete frozen cohort ancestor changed: '+name)
    return Path(row['path'])


_BASE={'__file__':str(checked_source('schema')),'__name__':'_cohort_original_shape_schema'}
exec(compile(ast.parse(Path(_BASE['__file__']).read_bytes()),_BASE['__file__'],'exec'),_BASE)
for _key,_value in _BASE.items():
    if _key.isupper() and _key not in ('KIND','RESULT_KIND','SEED'):
        globals()[_key]=deepcopy(_value)
BASE_KIND,BASE_RESULT_KIND,BASE_SEED=_BASE['KIND'],_BASE['RESULT_KIND'],_BASE['SEED']


def canonical_sha256(value):
    return _BASE['canonical_sha256'](value)


def candidate(identity):
    rows=contract()['entries'][1:]
    matches=[row for row in rows if row['candidate_id']==identity or type(identity)is int and row['seed']==identity]
    if len(matches)!=1 or matches[0]['seed'] not in ALLOWED_SEEDS:
        raise ValueError('Only one of the nine fixed new candidates is permitted')
    return deepcopy(matches[0])


def shape_projection(public):
    """Return only the old identity view; never use it as financial input."""
    if type(public)is not dict or public.get('kind')!=KIND or type(public.get('seed'))is not int or public['seed'] not in ALLOWED_SEEDS:
        raise ValueError('Unknown real financial cohort specification identity')
    projected=deepcopy(public);projected['kind']=BASE_KIND;projected['seed']=BASE_SEED
    _BASE['validate_spec'](projected)
    return projected


def validate_spec(public):
    shape_projection(public)
    return public


def groups(public):
    return _BASE['groups'](public)


def points(public):
    yield from _BASE['points'](public)


def validate_result(public,result):
    validate_spec(public)
    namespace={**_BASE,'RESULT_KIND':RESULT_KIND}
    return FunctionType(_BASE['validate_result'].__code__,namespace)(public,result)


def for_seed(seed):
    """A separate schema-only facade; never project business facts or results."""
    candidate(seed)
    def checked(public):
        validate_spec(public)
        if public['seed']!=seed:raise ValueError('A private case namespace received another candidate')
        return public
    def checked_result(public,result):
        checked(public);return validate_result(public,result)
    values={key:deepcopy(value) for key,value in globals().items() if key.isupper() and not key.startswith('_')}
    values.update(SEED=seed,validate_spec=checked,validate_result=checked_result,
        canonical_sha256=canonical_sha256,groups=groups,points=points)
    return SimpleNamespace(**values)


def recipes():
    paths={str(CONTRACT),*(row['path'] for row in contract()['frozen_ancestors'].values())}
    paths.update(str(Path(__file__).with_name(name)) for name in ('__init__.py','schema.py','raw.py','oracles.py'))
    return {path:reference(path) for path in sorted(paths)}
