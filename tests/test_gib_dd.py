import json, os, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gib_dd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = json.load(open(os.path.join(ROOT, "samples", "scan-sample.json")))

class T(unittest.TestCase):
    def test_questions_cover_flags(self):
        qs = gib_dd.questions_from(SCAN)
        self.assertTrue(any("LP" in q for q in qs)); self.assertTrue(any("Token-2022" in q for q in qs))
    def test_task_shape(self):
        t, qs = gib_dd.build_task(SCAN, 10, 2, 5)
        self.assertEqual(t["payment"]["amount"], "10.00"); self.assertIn(SCAN["mint"], t["content"])
        self.assertTrue(t["deadline"].endswith("Z"))
    def test_spend_cap_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run([sys.executable, os.path.join(ROOT, "gib_dd.py"), "scan", "--from-scan",
                                os.path.join(ROOT, "samples", "scan-sample.json"), "--reward", "50", "--max-usdc", "10", "--out", d],
                               capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0); self.assertIn("refused", p.stderr)
    def test_post_is_dry_run_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            t, qs = gib_dd.build_task(SCAN, 5, 1, 3); gib_dd.write_kit(SCAN, t, qs, d)
            p = subprocess.run([sys.executable, os.path.join(ROOT, "gib_dd.py"), "post", d], capture_output=True, text=True,
                               env={**os.environ, "GIBWORK_BIN": "false"})
            self.assertEqual(p.returncode, 0); self.assertIn("DRY-RUN", p.stdout)
    def test_review_ranks(self):
        subs = json.load(open(os.path.join(ROOT, "samples", "submissions-sample.json")))["data"]["results"]
        n = len(gib_dd.questions_from(SCAN))
        r = [gib_dd.score(s, SCAN["mint"], n) for s in subs]
        self.assertEqual(r[0]["verdict"], "APPROVE?"); self.assertIn("no_promo", r[1]["missing"]); self.assertEqual(r[2]["verdict"], "REJECT?")

if __name__ == "__main__":
    unittest.main()
