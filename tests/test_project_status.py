import unittest

from loops_app.status import loop_status, project_identity


class ProjectStatusTests(unittest.TestCase):
    def test_project_identity_has_zelvari_loop_values(self):
        identity = project_identity()
        self.assertEqual(identity["company"], "Zelvari")
        self.assertEqual(identity["repo"], "ivanhermes777/loops")
        self.assertEqual(identity["operator"], "Hermes Agent with authenticated OpenAI Codex OAuth")

    def test_loop_status_documents_rocket_merge_gate(self):
        status = loop_status()
        self.assertIn("spec", status["stages"])
        self.assertIn("build", status["stages"])
        self.assertIn("review", status["stages"])
        self.assertIn("rocket_merge", status["stages"])
        self.assertTrue(status["requires_rocket_approval"])
        self.assertEqual(status["allowed_merger"], "ivanhermes777")


if __name__ == "__main__":
    unittest.main()
