"""Synthetic fixtures only: deterministic Phase 2 review."""
import copy
import unittest
from legal_nlp import phase2_auto_review as mod


def item(region_id, label, start, end, *, typ="labels"):
    return {"id": region_id, "type": typ,
            "value": {"start": start, "end": end,
                      ("labels" if typ == "labels" else "choices"): [label]},
            "from_name": "label" if typ == "labels" else "confianca_anotacao",
            "to_name": "text"}


def task(project=11, uid=9, doc=100, original=None, review=None):
    base = original if original is not None else [item("r1", "ENT_A", 0, 5)]
    result = review if review is not None else copy.deepcopy(base)
    return {"data": {"idacordao": doc, "acordao": "abcde"}, "project": project,
            "id": doc + project, "annotations": [{"completed_by": uid,
            "result": result, "prediction": {"result": base}}]}


def orig(doc=100, base=None):
    return {"data": {"idacordao": doc, "acordao": "abcde"},
            "annotations": [{"completed_by": 21,
            "result": base if base is not None else [item("r1", "ENT_A", 0, 5)]}]}


class AutoReviewTests(unittest.TestCase):
    def run_case(self, reviewed, source=None):
        baseline = source if source is not None else [item("r1", "ENT_A", 0, 5)]
        return mod.process([orig(base=baseline)],
                           {"11": [task(original=baseline, review=reviewed)]},
                           excluded_user_id=10)

    def test_same_label_offsets(self):
        retained, automatic, issues, _, _ = self.run_case([item("r1", "ENT_A", 0, 5)])
        self.assertEqual(automatic[0]["status"], "correto_automatico")
        self.assertEqual(retained[0]["annotations"][0]["result"][-1]["value"]["choices"],
                         ["correto_automatico"])
        self.assertEqual(issues, [])

    def test_label_change_has_priority(self):
        for start in (0, 1):
            with self.subTest(start=start):
                _, records, _, _, _ = self.run_case([item("r1", "ENT_B", start, 5)])
                self.assertEqual(records[0]["status"], "incorreto_automatico")
                self.assertEqual(records[0]["offset_alterado"], bool(start))

    def test_offset_change_only(self):
        _, records, _, _, _ = self.run_case([item("r1", "ENT_A", 1, 5)])
        self.assertEqual(records[0]["status"], "limite_impreciso_automatico")

    def test_preserves_human_choice(self):
        human = item("r1", "Certo", 0, 5, typ="choices")
        retained, automatic, _, _, summary = self.run_case(
            [item("r1", "ENT_B", 0, 5), human])
        self.assertEqual(automatic, [])
        self.assertEqual(retained[0]["annotations"][0]["result"][1], human)
        self.assertEqual(summary["manual_decisions_preserved"], 1)

    def test_missing_original_and_new_region_remain_pending(self):
        _, records, pending, _, _ = self.run_case([item("r2", "ENT_A", 0, 5)])
        self.assertEqual(records, [])
        self.assertCountEqual([x["motivo"] for x in pending],
            ["regiao_original_ausente_na_avaliacao", "nova_regiao_sem_id_no_original"])

    def test_excludes_reviewer_only_from_derived_dataset(self):
        retained, records, issues, removed, _ = mod.process(
            [orig()], {"11": [task(uid=10)]}, excluded_user_id=10)
        self.assertEqual((len(retained), len(records), len(issues), len(removed)),
                         (0, 0, 0, 1))

    def test_missing_original_fails(self):
        with self.assertRaisesRegex(ValueError, "Original inexistente"):
            mod.process([orig(doc=200)], {"11": [task()]}, excluded_user_id=10)

    def test_embedded_original_mismatch_fails(self):
        source = orig()
        source["annotations"][0]["result"][0]["value"]["start"] = 1
        with self.assertRaisesRegex(ValueError, "Snapshot do original divergente"):
            mod.process([source], {"11": [task()]}, excluded_user_id=10)
