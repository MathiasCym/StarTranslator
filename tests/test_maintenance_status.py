import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.server import app
from backend import workflow


class MaintenanceStatusTests(unittest.TestCase):
    def test_guard_reads_actual_background_jobs_without_changing_them(self):
        client = app.test_client()
        with workflow.LOCK:
            previous = dict(workflow.JOBS)
            workflow.JOBS.clear()
        try:
            response = client.get('/api/maintenance/status')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {'busy': False})
            with workflow.LOCK:
                workflow.JOBS['synthetic'] = {'status': 'running'}
            self.assertEqual(client.get('/api/maintenance/status').json, {'busy': True})
            with workflow.LOCK:
                self.assertEqual(workflow.JOBS['synthetic']['status'], 'running')
                workflow.JOBS['synthetic']['status'] = 'complete'
            self.assertEqual(client.get('/api/maintenance/status').json, {'busy': False})
        finally:
            with workflow.LOCK:
                workflow.JOBS.clear()
                workflow.JOBS.update(previous)


if __name__ == '__main__':
    unittest.main()
