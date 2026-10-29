import importlib.util,json,pathlib,tempfile,unittest,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class ArchiveTests(unittest.TestCase):
    def test_captures_are_market_free(self):
        m=module(ROOT/'scripts/model_learning.py','learning_test')
        rows,_=m.collect_local(ROOT,json.loads((ROOT/'learning/config.json').read_text())['project'])
        for row in rows:
            self.assertEqual(set(row),{'event_id','start','frozen_at','model','probabilities','labels','source','cutoff','key','schema_version','expected_scores'})
            self.assertLess(m.timestamp(row['frozen_at']),m.timestamp(row['start']))

class ReconciliationTests(unittest.TestCase):
    def test_unresolved_history_is_retried(self):
        from datetime import date
        m=module(ROOT/'scripts/grade_pending.py','soccer_grade_pending')
        with tempfile.TemporaryDirectory() as d:
            r=pathlib.Path(d)
            for day in ['2026-01-01','2026-01-02','2026-10-28','2026-11-01']:(r/'data/forecasts'/day).mkdir(parents=True)
            (r/'data/results').mkdir()
            (r/'data/results/2026-01-01.json').write_text(json.dumps({'games':[{'status':'final'}]}))
            self.assertEqual(m.pending_dates(r,date(2026,10,29)),['2026-01-02','2026-10-28'])

class SchedulerTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux'), 'GitHub runner uses GNU date')
    def test_rearm_preserves_queued_refresh(self):
        import os,subprocess
        with tempfile.TemporaryDirectory() as d:
            shim=pathlib.Path(d)/'gh'
            shim.write_text("#!/usr/bin/env python3\nimport os,sys,datetime\nargs=' '.join(sys.argv[1:])\nif 'workflow run' in args:\n    with open(os.environ['CALLS'],'a') as f:f.write(args+'\\n')\nelif 'createdAt' in args:print(datetime.datetime.now(datetime.timezone.utc).isoformat())\nelse:print(os.environ['PENDING'])\n")
            shim.chmod(0o755)
            calls=pathlib.Path(d)/'calls'
            env={**os.environ,'PATH':d+os.pathsep+os.environ['PATH'],'GH_TOKEN':'test','GH_REPO':'test/test','RUN_ID':'123','LINEUPS_EVERY_MIN':'0','PIPELINE_EVERY_MIN':'999999','CALLS':str(calls)}
            subprocess.run(['bash',str(ROOT/'scripts/rearm.sh')],env={**env,'PENDING':'1'},check=True)
            self.assertFalse(calls.exists())
            subprocess.run(['bash',str(ROOT/'scripts/rearm.sh')],env={**env,'PENDING':'0'},check=True)
            self.assertEqual(calls.read_text().count('workflow run lineups.yml'),1)
