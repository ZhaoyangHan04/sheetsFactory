from concurrent.futures import ThreadPoolExecutor
from sheets_factory.core.audit import AuditStore
from sheets_factory.core.node import BaseNode, TaskContext


def test_audit_concurrency_and_conversion(tmp_path):
    audit = AuditStore(tmp_path, {'id': 'run-test', 'target_count': 40})
    def work(i):
        audit.task(str(i), source_id=str(i // 2), status='qualified' if i < 4 else 'rejected', mode='debugging')
        audit.emit('task.result', task_id=str(i))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(work, range(10)))
    snap = audit.export()
    assert snap['metrics']['candidate_conversion'] == 0.4
    assert snap['metrics']['source_conversion'] == 0.4
    assert len(audit.events()) == 10
    assert snap['metrics']['estimated_cost'] is None


def test_node_failure_is_audited(tmp_path):
    audit = AuditStore(tmp_path, {'id': 'test'})
    class Broken(BaseNode):
        node_id = 'broken'
        def execute(self, context):
            raise ValueError('visible cause')
    import pytest
    context = TaskContext('test', 'task', 'debugging', tmp_path, tmp_path, {}, audit, None, None)
    with pytest.raises(ValueError):
        Broken().run(context)
    assert audit.snapshot()['nodes'][0]['status'] == 'failed'
