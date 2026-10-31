"""Fixed larger raw-input extensions, without financial or search execution."""
from copy import deepcopy
from decimal import localcontext
import hashlib
import json
from pathlib import Path
import random

from ..capital_allocation_scaled import constrained_catalog as parent
from . import spec

ROOT=Path(__file__).resolve().parents[4]
DEFAULT_CATALOG=ROOT/'config/capital_allocation_sparse_catalog_v1.json'
ORDER=('40-J01','48-J01','56-J01',*(f'40-C{i:02}' for i in range(1,11)))
PARENT_SHA='923c6ee7dfbe65fbacff066042e68e809025ba20f6821687f2340ec5eb439d99'
PARENT_CONFIG_SHA='6b0814db9b2a74daf5ca7ceeae533813fabb9fdf3df556113b91cf7c98146f31'
FIELDS={'kind','version','profile_order','first_development_profile','candidate_order','parent_catalog',
        'parent_catalog_sha256','extension_policy','selection_uses_new_model_outcomes','confirmation_frozen',
        'financial_feasibility_or_optimum_claimed','model_difficulty_claimed','profiles'}
PROFILE_FIELDS={'id','project_count','parent_profile','extension_seed','role','root_money_scale_numerator',
                'root_money_scale_denominator','money_quantum_pence'}
MONEY_FIELDS=('opening_cash_pence','minimum_cash_pence','lp_commitment_pence','facility_limit_pence')


def assert_parent():
    for path,sha in ((Path(parent.__file__),PARENT_SHA),(parent.DEFAULT_CATALOG,PARENT_CONFIG_SHA)):
        spec.require(hashlib.sha256(path.read_bytes()).hexdigest()==sha,'The frozen parent primitive catalog changed')
    parent.assert_upstream()


def _unique(pairs):
    value={}
    for key,child in pairs:
        spec.require(key not in value,'Duplicate sparse catalog field');value[key]=child
    return value


def load_catalog(value=DEFAULT_CATALOG):
    assert_parent()
    c=json.loads(Path(value).read_text(),object_pairs_hook=_unique) if isinstance(value,(str,Path)) else deepcopy(value)
    spec.require(isinstance(c,dict) and set(c)==FIELDS and c['kind']=='prospective_sparse_capital_primitive_extension_catalog'
        and type(c['version']) is int and c['version']==1,'The complete sparse catalog schema is required')
    spec.require(c['profile_order']==list(ORDER) and c['first_development_profile']=='40-J01'
        and c['candidate_order']==list(ORDER[3:]) and c['parent_catalog']=='config/capital_allocation_constrained_catalog_v1.json'
        and c['parent_catalog_sha256']==PARENT_CONFIG_SHA,'Fixed profile order or parent identity changed')
    spec.require(all(c[key] is False for key in ('selection_uses_new_model_outcomes','confirmation_frozen',
        'financial_feasibility_or_optimum_claimed','model_difficulty_claimed')) and type(c['extension_policy']) is str
        and bool(c['extension_policy']),'Prospective unknown states must not be relabelled as results')
    spec.require(isinstance(c['profiles'],list) and [p.get('id') for p in c['profiles']]==list(ORDER),
                 'Every fixed development, engineering and candidate profile is required')
    for index,p in enumerate(c['profiles']):
        n=int(ORDER[index][:2]);expected_parent='30-D02' if index<3 else f'30-H{index-2:02}'
        role='first_development' if index==0 else 'engineering_only' if index<3 else 'unconfirmed_candidate'
        spec.require(set(p)==PROFILE_FIELDS and p['project_count']==n and type(p['project_count']) is int
            and p['parent_profile']==expected_parent and p['role']==role,'A complete fixed sparse profile differs')
        spec.require(type(p['extension_seed']) is int and p['extension_seed']==40261031+index*7919,
                     'The prospective extension seed changed')
        spec.require(p['root_money_scale_numerator']==n and p['root_money_scale_denominator']==30
            and p['money_quantum_pence']==1000000 and all(type(p[k]) is int for k in ('root_money_scale_numerator',
            'root_money_scale_denominator','money_quantum_pence')),'The declared cash/capacity scaling changed')
    return c


def _quantized(value,numerator,denominator,quantum):
    # Exact positive half-away rounding at the explicitly declared money quantum.
    den=denominator*quantum
    return ((value*numerator*2+den)//(2*den))*quantum


def build_spec(profile_id,catalog=DEFAULT_CATALOG):
    config=load_catalog(catalog)
    spec.require(profile_id in ORDER,'Unknown prospective sparse profile')
    profile=next(p for p in config['profiles'] if p['id']==profile_id)
    pc=parent.load_catalog();pp=next(p for p in pc['profiles'] if p['id']==profile['parent_profile'])
    public=parent.build_spec(profile['parent_profile'],pc)
    rng=random.Random(profile['extension_seed']);policies={c['id']:c for c in pc['cohorts']}
    pair_costs=[rng.randint(300,500)*1000000 for _ in range(5)]
    with localcontext() as context:
        context.prec=70
        for index in range(30,profile['project_count']):
            extra=index-30;cohort=parent.COHORTS[extra%len(parent.COHORTS)];ordinal=(extra//len(parent.COHORTS))%5
            public['projects'].append(parent._project(f'P{index+1:02}',policies[cohort],ordinal,pp,rng,pair_costs,pc))
    for key in MONEY_FIELDS:
        public[key]=_quantized(public[key],profile['root_money_scale_numerator'],
                              profile['root_money_scale_denominator'],profile['money_quantum_pence'])
    return spec.load_spec(public)


def describe_profile(profile_id,catalog=DEFAULT_CATALOG):
    config=load_catalog(catalog);public=build_spec(profile_id,config)
    profile=next(p for p in config['profiles'] if p['id']==profile_id)
    return {'profile':profile,'public_spec_sha256':spec.canonical_sha(public),'complete_plan_count':spec.plan_space_count_string(public),
        'preserved_parent_projects':'30','added_projects':str(profile['project_count']-30),
        'parent_primitive_implementation_sha256':PARENT_SHA,'parent_catalog_sha256':PARENT_CONFIG_SHA,
        'source_original_ancestors':'2','actual_searches':'0','actual_workbooks':'0','actual_LO_calls':'0','actual_model_calls':'0',
        'confirmation_frozen':False,'financial_feasibility_or_optimum_certified':False,'source_quality_or_difficulty_certified':False}
