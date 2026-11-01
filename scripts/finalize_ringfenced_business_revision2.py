#!/usr/bin/env python3
"""Join bounded-review evidence without changing the frozen staging transaction."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import inspect
from pathlib import Path
from types import FunctionType

BASE = Path(__file__).resolve().with_name('publish_ringfenced_business_revision.py')
BASE_SHA = '2d8f5773f19b94938618fd28d73649a46db129b8c10ec00bedeb1d31449537df'
if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
    raise ValueError('The frozen staged publisher changed')
loader = importlib.util.spec_from_file_location('_ring_revision2_frozen_publication', BASE)
base = importlib.util.module_from_spec(loader); loader.loader.exec_module(base)
ref, checked, read, require = base.ref, base.checked, base.read, base.require
OLD_REVIEW_KIND = 'actual_five_ringfenced_pairs_shared_quality_review_v1'
CONTRACT_KIND = 'frozen_ringfenced_bounded_review_contract_v2'


def contract(value):
    binding=checked(value); data=read(binding)
    require(data['kind']==CONTRACT_KIND and data['version']==1
        and data['terminal_kind']!=OLD_REVIEW_KIND and data['driver']!=ref(base.REVIEW),
        'Use a new explicit bounded-review contract, preserving the failed original review')
    checked(data['driver']); old=read(data['failed_review'])
    require(old['kind']==OLD_REVIEW_KIND and old['shared_semantic_passed'] is False
        and len(old['failures'])==len(old['ordinary_review_native_calls'])==4
        and old['usage']['llm_calls']==old['usage']['unknown_usage_calls']==4,
        'The original four incomplete judgments and unknown usage must be retained')
    for record in old['ordinary_review_native_calls']:
        call=read(record)
        require(call['model']=='gpt-6-sol' and call['reasoning_effort']=='high' and call['status']!='completed',
            'A valid completed quality judgment cannot be silently resampled')
    for guard in data.get('packet_guards',[]):checked(guard)
    return binding,data


def quality_validator(profile):
    """Adapt exactly one expected review-kind literal; retain the quality checks."""
    tree=ast.parse(inspect.getsource(base.validate_quality));changes=[]
    class Identity(ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value==OLD_REVIEW_KIND:
                changes.append(True);return ast.copy_location(ast.Constant(profile['terminal_kind']),node)
            return node
    tree=Identity().visit(tree);require(len(changes)==1,'The frozen quality identity seam changed')
    namespace=dict(vars(base));namespace.update(REVIEW=Path(profile['driver']['path']),REVIEW_SHA=profile['driver']['sha256'])
    exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),namespace)
    inherited=namespace['validate_quality']
    def validate(review_ref,prepared):
        review=inherited(review_ref,prepared);dispatch=read(review['dispatch']);packet=read(dispatch['prepared'])
        require(packet['kind']==profile['prepared_kind'] and packet['implementation']==profile['driver'],
            'The bounded packet belongs to another actual reviewed driver')
        require(packet['prior_incomplete_review']==profile['failed_review']
            and packet['incomplete_review_calls_preserved']==4 and packet['previous_valid_judgments_replaced'] is False
            and set(packet['bounded_packets'])=={mode+'/'+role for mode in base.MODES for role in ('public','reference')},
            'Preserve the incomplete original and all four bounded visibility packets')
        old=read(profile['failed_review'])
        require({t['task_id'] for t in old['tasks']}=={t['task_id'] for t in prepared['tasks']},
            'The preserved incomplete review belongs to another cohort')
        for record in packet['workspace_inventory'].values():checked(record)
        for record in packet['bounded_packets'].values():checked(record)
        for guard in profile.get('packet_guards',[]):checked(guard)
        # Bind each reviewed public input, brief and private goal to the same
        # prospective ten; a compressed review view cannot select new material.
        expected={t['task_id']:t for t in prepared['tasks']}
        for task in review['tasks']:
            t=expected[task['task_id']];artifacts=t['harbor_export_binding']['resource_runtime']['source_artifacts']
            require(task['mode']==t['mode'] and all(task[key]['sha256']==artifacts[original]['sha256']
                and task[key]['bytes']==artifacts[original]['bytes'] for key,original in
                (('input','input'),('instruction','instruction'),('goal','goal'))),
                'A bounded review refers to different workbook or brief bytes')
        calls={read(record)['call_id']:read(record) for record in review['ordinary_review_native_calls']}
        observed={read(record)['container_name']:read(record) for record in review['ordinary_review_resources']}
        require(len(calls)==len(observed)==4,'Require the four distinct actual ordinary calls and containers')
        for identity,call in calls.items():
            name='sf-codex-'+identity[:20];resource=observed.get(name)
            require(resource and resource['passed'] is True and resource['observations'],
                'The bounded review has no exact owned actual resource observation')
            image=resource['expected_image_id']
            for row in resource['observations']:
                actual=row['container']
                require(row['passed'] is True and actual['Name']=='/'+name and len(actual['Id'])==64
                    and actual['Image']==image and actual['NanoCpus']==2000000000
                    and actual['Memory']==34359738368 and actual['PidsLimit']==256
                    and datetime.fromisoformat(call['started_at'])<=datetime.fromisoformat(row['at'])<=datetime.fromisoformat(call['finished_at']),
                    'Actual bounded-review identity, limits or observation times differ')
        return review
    return validate


def augment(value,binding,profile):
    result=deepcopy(value);old=read(profile['failed_review']);metrics=old['usage']
    result['version']=2
    result['finalizer_revision2']={'implementation':ref(__file__),'frozen_staged_publisher':ref(BASE),
        'bounded_review_contract':binding,'current_review_driver':profile['driver'],
        'staged_recipe_and_dataset_manifest_unchanged':True,'original_failed_review':profile['failed_review']}
    cost=result['consumption'];cost['failed_original_semantic_review']={
        'terminal':profile['failed_review'],'native_calls':old['ordinary_review_native_calls'],
        'model_calls':metrics['llm_calls'],'unknown_usage_calls':metrics['unknown_usage_calls'],
        'known_reported_total_tokens':metrics['total_tokens'],'zero_known_tokens_does_not_mean_zero_consumption':True}
    cost['known_reported_total_tokens']+=metrics['total_tokens'];cost['model_calls']+=metrics['llm_calls']
    cost['unknown_usage_calls']+=metrics['unknown_usage_calls']
    return result


def finalize(installed,confirmation,review,actual_controls,output,*,review_contract,analyses=(),development=()):
    binding,profile=contract(review_contract);before=ref(BASE);namespace=dict(vars(base))
    namespace['validate_quality']=quality_validator(profile)
    def final_write(path,value):
        require(value['kind']=='qualified_ringfenced_business_revision_release','The thin finalizer writes only its final release receipt')
        require(ref(BASE)==before and ref(__file__)['sha256']==implementation['sha256'],'A frozen finalizer changed during evidence consumption')
        contract(binding)
        return base.write(path,augment(value,binding,profile))
    implementation=ref(__file__);namespace['write']=final_write
    original=base.finalize;adapted=FunctionType(original.__code__,namespace,original.__name__,original.__defaults__,original.__closure__)
    adapted.__kwdefaults__=original.__kwdefaults__
    return adapted(installed,confirmation,review,actual_controls,output,analyses=analyses,development=development)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('installed','confirmation','review','actual-controls','output','review-contract'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--analysis',action='append',type=Path,default=[]);p.add_argument('--development',action='append',type=Path,default=[])
    a=p.parse_args();print(base.json.dumps(finalize(a.installed,a.confirmation,a.review,a.actual_controls,a.output,
        review_contract=a.review_contract,analyses=a.analysis,development=a.development)))


if __name__=='__main__':main()
