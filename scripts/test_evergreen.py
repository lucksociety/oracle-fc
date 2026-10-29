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
