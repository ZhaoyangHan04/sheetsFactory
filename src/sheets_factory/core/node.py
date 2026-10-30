"""Typed context and uniformly instrumented node inheritance."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
import time


class TaskRejected(Exception):
    pass


class CooperativeCancelled(BaseException):
    """Explicit stop control flow; business/infra Exception handlers must not swallow it."""


@dataclass
class TaskContext:
    run_id: str
    task_id: str
    mode: str
    source: Path
    directory: Path
    config: dict
    audit: object
    llm: object
    engine: object
    revision: int = 0
    data: dict = field(default_factory=dict)

    @property
    def revision_dir(self):
        return self.directory / 'revisions' / f'{self.revision:03d}'

    def save(self, name, data, private=True):
        import json
        path = self.revision_dir / ('private' if private else 'public') / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return path


class BaseNode(ABC):
    node_id = 'base'

    def run(self, context: TaskContext):
        started = time.monotonic()
        from .audit import utcnow
        stamp = utcnow()
        context.audit.emit('node.started', task_id=context.task_id, node=self.node_id, revision=context.revision)
        context.audit.task(context.task_id, node=self.node_id, revision=context.revision, status='running')
        record_id = context.audit.record('nodes', {'task_id': context.task_id, 'node': self.node_id,
            'node_id': self.node_id, 'revision': context.revision, 'started_at': stamp, 'status': 'running'})
        status, error = 'completed', None
        try:
            result = self.execute(context)
            if result:
                context.data.update(result)
            return result
        except CooperativeCancelled:
            status, error = 'cancelled', 'Cooperative stop requested before further work'
            raise
        except Exception as exc:
            status, error = 'failed', str(exc)
            raise
        finally:
            record = {'task_id': context.task_id, 'node': self.node_id, 'revision': context.revision,
                      'started_at': stamp, 'duration_ms': round((time.monotonic() - started) * 1000),
                      'status': status, 'error': error}
            context.audit.update_record('nodes', record_id, record)
            context.audit.emit('node.' + status, **record)

    @abstractmethod
    def execute(self, context: TaskContext) -> dict:
        """Return newly produced fields; controller owns transitions and budgets."""
