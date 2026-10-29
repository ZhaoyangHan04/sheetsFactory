"""Declarative phase templates and runtime-validated node registration."""
from __future__ import annotations

from abc import ABC, abstractmethod
import importlib
from pathlib import Path

import yaml

from .node import BaseNode


class BasePipeline(ABC):
    def __init__(self, config):
        self.config = config
        self.project_root = Path(config['project_root'])
        registry_path = self.project_root / config.get('pipeline', {}).get('node_registry', 'config/nodes.yaml')
        self.node_registry = yaml.safe_load(registry_path.read_text())['nodes']
        self.templates = {}
        for mode in config['run']['targets']:
            name = config.get('pipeline', {}).get('templates', {}).get(mode, mode)
            path = Path(name)
            if not path.suffix:
                path = Path('src/sheets_factory/pipelines/templates') / (name + '.yaml')
            if not path.is_absolute():
                path = self.project_root / path
            template = yaml.safe_load(path.read_text())
            if template.get('mode') != mode:
                raise ValueError(f'Pipeline template mode mismatch for {mode}')
            phases = template['phases']
            required = {'preparation', 'revision', 'evidence', 'infrastructure_retry', 'repair', 'export'}
            if not required <= phases.keys():
                raise ValueError(f'Missing pipeline phases: {required - phases.keys()}')
            for phase, node_ids in phases.items():
                if not node_ids or len(node_ids) != len(set(node_ids)):
                    raise ValueError(f'Empty or duplicated nodes in phase {phase}')
                for node_id in node_ids:
                    self.load_node(node_id)
            core = ['construct', 'instruction', 'precheck', 'independent_recovery', 'trajectory', 'diagnose']
            if any(node not in phases['revision'] for node in core):
                raise ValueError('Revision template omits a mandatory quality stage')
            indexes = [phases['revision'].index(node) for node in core]
            if indexes != sorted(indexes):
                raise ValueError('Mandatory quality stages are out of order')
            if 'diagnose' not in phases['evidence'] or 'diagnose' not in phases['infrastructure_retry']:
                raise ValueError('Evidence and infrastructure phases must rediagnose')
            self.templates[mode] = template

    def load_node(self, node_id):
        if node_id not in self.node_registry:
            raise ValueError(f'Unregistered pipeline node: {node_id}')
        spec = self.node_registry[node_id]
        location = spec if isinstance(spec, str) else spec['implementation']
        module, separator, attribute = location.partition(':')
        if not separator:
            raise ValueError(f'Invalid node implementation: {location}')
        implementation = getattr(importlib.import_module(module), attribute)
        if not isinstance(implementation, type) or not issubclass(implementation, BaseNode):
            raise ValueError(f'{node_id} does not implement BaseNode')
        return implementation()

    def run_phase(self, context, phase):
        node_ids = self.templates[context.mode]['phases'][phase]
        context.audit.emit('pipeline.phase.started', task_id=context.task_id, revision=context.revision,
                           phase=phase, template=self.templates[context.mode]['id'], node_ids=node_ids)
        for node_id in node_ids:
            self.load_node(node_id).run(context)

    @abstractmethod
    def run(self):
        raise NotImplementedError
