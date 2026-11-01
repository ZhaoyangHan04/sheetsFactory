"""Complete declared report-currency scales without changing economic scoring."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from . import business_failure_evidence as base

BASE_SHA = 'eeb67c32873930857bc713c1cd3892b9c1da7ea2b70964b91ad13a212f18c54b'
UNITS = {'GBP': 1, 'GBP_thousands': 1000, 'GBP_millions': 1000000}


def _require(value, message):
    if not value: raise ValueError(message)


def verify_dependencies():
    _require(base.reference(Path(base.__file__))['sha256'] == BASE_SHA,
             'The frozen economic evidence implementation changed')


def complete_money_scales(bindings, entity_money_scales):
    """Add only explicitly GBP-denominated division and portfolio prefixes.

    Entity scales remain the supplied public-spec scales. Every financial
    binding under a prefix must state the same report currency, including
    nonmonetary presentation cells, so no missing unit becomes an assumption.
    """
    verify_dependencies()
    _require(isinstance(entity_money_scales, dict) and entity_money_scales, 'Provide the public entity money scales')
    result = {}
    for identity, scale in entity_money_scales.items():
        _require(isinstance(identity, str) and identity and not identity.startswith('DIV_') and identity != 'PORTFOLIO',
                 'Aggregate prefixes cannot be asserted as public entities')
        try:
            value = Decimal(str(scale)) if type(scale) in (int, str, Decimal) else None
        except InvalidOperation:
            value = None
        _require(value is not None and value.is_finite()
            and value in (Decimal(1), Decimal(1000), Decimal(1000000)), 'An entity scale is unsupported')
        result[identity] = int(value)
    scope = bindings.get('financial', bindings)
    _require(isinstance(scope, dict) and scope, 'Provide complete financial semantic bindings')
    units = {}
    for semantic, binding in scope.items():
        _require(isinstance(semantic, str) and '/' in semantic and isinstance(binding, dict), 'Invalid financial semantic binding')
        prefix = semantic.split('/', 1)[0]
        unit = binding.get('money_unit')
        _require(unit in UNITS, 'Every financial binding needs its explicit supported money unit')
        units.setdefault(prefix, set()).add(unit)
    for prefix, declared in units.items():
        _require(len(declared) == 1, 'A report prefix has conflicting money units')
        unit, = declared
        if prefix in result:
            _require(UNITS[unit] == result[prefix], 'A report binding conflicts with its public entity scale')
        else:
            _require(prefix == 'PORTFOLIO' or re.fullmatch(r'DIV_[A-Z][A-Z_]*', prefix),
                     'An undeclared entity cannot inherit an aggregate currency scale')
            _require(unit == 'GBP', 'Division and portfolio reports must explicitly declare GBP')
            result[prefix] = 1
    return result
