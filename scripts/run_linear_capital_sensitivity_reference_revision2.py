#!/usr/bin/env python3
"""Explicit preparation and execution of the fixed ninth-case continuation."""
import argparse
import json
from pathlib import Path
from sheets_factory.workbook.linear_capital_sensitivity import reference_revision2 as producer


def main(argv=None):
    parser=argparse.ArgumentParser(__doc__);sub=parser.add_subparsers(dest='command',required=True)
    prepare=sub.add_parser('prepare');prepare.add_argument('--original-preparation',required=True,type=Path)
    prepare.add_argument('--observation',required=True,type=Path);prepare.add_argument('--output',required=True,type=Path)
    for name in ('validate','run'):
        command=sub.add_parser(name);command.add_argument('--prepared',required=True,type=Path)
        if name=='run':command.add_argument('--port',type=int,default=0)
    completed=sub.add_parser('validate-completed');completed.add_argument('--receipt',required=True,type=Path)
    args=parser.parse_args(argv)
    if args.command=='prepare':answer=producer.prepare(args.original_preparation,args.observation,args.output)
    elif args.command=='validate':producer.validate_prepared(args.prepared);answer={'passed':True,'preparation':producer.reference(args.prepared/'preparation.json')}
    elif args.command=='run':answer=producer.execute_prepared(args.prepared,port=args.port)
    else:answer=producer.validate_completed(args.receipt)
    print(json.dumps(answer,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
