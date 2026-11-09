"""Tests use invented identifiers and role labels only."""
import json
import pytest
from legal_nlp.phase2_identity_enrichment import enrich, make_lookup, main

MAPPING = [{"id_acordao":"12345678","anotador":"Annotator A",
"avaliador_projeto_1":"Reviewer B","avaliador_projeto_2":"Reviewer C",
"projeto_1_id_confirmado":"sim","projeto_2_id_confirmado":"nao"}]

def test_preserves_ids():
    data = [{"data":{"idacordao":12345678},"annotated_by":17,"evaluated_by":3,"updated_by":19}]
    result, report = enrich(data, MAPPING)
    assert result[0]["updated_by"] == 19
    assert result[0]["annotated_by"] == 17
    assert result[0]["evaluated_by"] == 3
    assert result[0]["annotator_name_inferred"] == "Annotator A"
    assert report["matched_rows"] == 1

def test_missing_and_unmatched():
    _, report = enrich([{"idacordao":"99999999"},{"data":{}}], MAPPING)
    assert report["unmatched_rows"] == 1
    assert report["missing_document_id_rows"] == 1

def test_duplicates_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        make_lookup(MAPPING + MAPPING)

def test_missing_columns_rejected():
    with pytest.raises(ValueError, match="Missing required"):
        make_lookup([{"id_acordao":"12345678"}])

def test_json_cli(tmp_path):
    source = tmp_path / "in.json"
    mapping = tmp_path / "mapping.json"
    output = tmp_path / "out.json"
    report = tmp_path / "report.json"
    source.write_text(json.dumps([{"idacordao":12345678,"updated_by":7}]))
    mapping.write_text(json.dumps(MAPPING))
    assert main(["--input",str(source),"--crosswalk",str(mapping),
                 "--output",str(output),"--report",str(report),"--strict"]) == 0
    assert json.loads(output.read_text())[0]["updated_by"] == 7

def test_strict_fails_without_output(tmp_path):
    source = tmp_path / "in.json"
    mapping = tmp_path / "mapping.json"
    output = tmp_path / "out.json"
    report = tmp_path / "report.json"
    source.write_text('[{"idacordao":99999}]')
    mapping.write_text(json.dumps(MAPPING))
    with pytest.raises(ValueError, match="incomplete"):
        main(["--input",str(source),"--crosswalk",str(mapping),
              "--output",str(output),"--report",str(report),"--strict"])
    assert not output.exists()
