#!/usr/bin/env python3
"""Use the native development protocol with the declared ring-fenced cell limits."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'scripts/run_business_revision_frontier.py'
BASE_SHA='216c12e480dfd33de76e5a53c97838195efcd53d99f74380f6e25eba04b3e603'
PROFILE=ROOT/'config/runtime_profiles/ringfenced_pair_source_v1.yaml'
PROFILE_SHA='20fc02fec3aaf4918ece50d18ef9e315ffee9fccce088863f044ebac301a026a'


def guard():
    for file,wanted in ((BASE,BASE_SHA),(PROFILE,PROFILE_SHA)):
        if hashlib.sha256(file.read_bytes()).hexdigest()!=wanted:
            raise ValueError('The frozen native protocol or ring-fenced resource profile changed')


guard()
loader=importlib.util.spec_from_file_location('_ringfenced_business_native_development',BASE)
protocol=importlib.util.module_from_spec(loader);loader.loader.exec_module(protocol)
protocol.PROFILE=PROFILE
protocol._N['PROFILE']=PROFILE
from sheets_factory.evaluation import ringfenced_frontier_v6 as runner
from sheets_factory.evaluation import ringfenced_resource_harbor as resources
from sheets_factory.evaluation import ringfenced_resource_observer as observer
protocol.runner=runner
protocol._N['runner']=runner
protocol.inspect_resource_export=resources.inspect_resource_export
protocol._N['inspect_resource_export']=resources.inspect_resource_export
protocol._N['resource_observer']=observer
protocol._N['ResourceObserver']=observer.ResourceObserver
protocol._N['validate_observation_receipt']=observer.validate_observation_receipt
_base_recipes=protocol.recipes


def recipes():
    guard()
    return {**_base_recipes(),'ringfenced_development_entry':protocol.ref(__file__),
            'declared_ringfenced_profile':protocol.ref(PROFILE),
            'ringfenced_native_runner':protocol.ref(runner.__file__),
            'ringfenced_export_inspection':protocol.ref(resources.__file__),
            'ringfenced_resource_observation':protocol.ref(observer.__file__),
            'resource_difference':'cell inventory limits only; roles, image, worker cap and tool budget unchanged'}


protocol._N['recipes']=recipes


def prepare(batches,output,*,port=0):
    guard()
    return protocol.prepare(batches,output,port=port)


def run(output,*,concurrency=2,port=0):
    guard()
    return protocol.run(output,concurrency=concurrency,port=port)


def main():
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--batch',required=True,action='append',type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--run',action='store_true');p.add_argument('--concurrency',default=2,type=int)
    p=sub.add_parser('run');p.add_argument('--prepared',required=True,type=Path);p.add_argument('--concurrency',default=2,type=int)
    args=parser.parse_args()
    if args.command=='prepare':
        result=prepare(args.batch,args.output)
        if args.run:result=run(args.output,concurrency=args.concurrency)
    else:result=run(args.prepared,concurrency=args.concurrency)
    print(protocol._N['json'].dumps(result))


if __name__=='__main__':
    main()
