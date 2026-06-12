"""Tests for the loader module."""

import json

import pytest
import yaml

from promptdiff.loader import load_prompt, load_test_cases


class TestLoadPrompt:
    def test_load_text_file(self, tmp_path):
        p = tmp_path / "prompt.txt"
        p.write_text("You are a helpful assistant.\n\nBe concise.\n")
        result = load_prompt(str(p))
        assert result == "You are a helpful assistant.\n\nBe concise."

    def test_strips_whitespace(self, tmp_path):
        p = tmp_path / "prompt.txt"
        p.write_text("  hello  \n\n")
        assert load_prompt(str(p)) == "hello"


class TestLoadTestCases:
    def test_load_txt(self, tmp_path):
        p = tmp_path / "cases.txt"
        p.write_text("What is 2+2?\nWho wrote Hamlet?\n\nWhat is Python?\n")
        cases = load_test_cases(str(p))
        assert len(cases) == 3
        assert cases[0] == "What is 2+2?"

    def test_load_jsonl(self, tmp_path):
        p = tmp_path / "cases.jsonl"
        lines = [
            json.dumps({"input": "question 1"}),
            json.dumps({"input": "question 2"}),
        ]
        p.write_text("\n".join(lines))
        cases = load_test_cases(str(p))
        assert cases == ["question 1", "question 2"]

    def test_load_jsonl_strings(self, tmp_path):
        p = tmp_path / "cases.jsonl"
        p.write_text(json.dumps("plain question") + "\n")

        assert load_test_cases(str(p)) == ["plain question"]

    def test_bad_jsonl_points_to_line(self, tmp_path):
        p = tmp_path / "cases.jsonl"
        p.write_text('{"input": "ok"}\n{"missing": "input"}\n')

        with pytest.raises(ValueError, match=r"cases\.jsonl:2"):
            load_test_cases(str(p))

    def test_load_json_strings(self, tmp_path):
        p = tmp_path / "cases.json"
        p.write_text(json.dumps(["q1", "q2", "q3"]))
        cases = load_test_cases(str(p))
        assert cases == ["q1", "q2", "q3"]

    def test_load_json_objects(self, tmp_path):
        p = tmp_path / "cases.json"
        p.write_text(json.dumps([{"input": "a"}, {"input": "b"}]))
        cases = load_test_cases(str(p))
        assert cases == ["a", "b"]

    def test_load_yaml(self, tmp_path):
        p = tmp_path / "cases.yaml"
        data = ["What is AI?", "Explain quantum computing."]
        p.write_text(yaml.dump(data))
        cases = load_test_cases(str(p))
        assert len(cases) == 2

    def test_load_yaml_objects(self, tmp_path):
        p = tmp_path / "cases.yml"
        data = [{"input": "x"}, {"input": "y"}]
        p.write_text(yaml.dump(data))
        cases = load_test_cases(str(p))
        assert cases == ["x", "y"]

    def test_empty_lines_skipped(self, tmp_path):
        p = tmp_path / "cases.txt"
        p.write_text("hello\n\n\nworld\n")
        cases = load_test_cases(str(p))
        assert cases == ["hello", "world"]

    def test_json_root_must_be_list(self, tmp_path):
        p = tmp_path / "cases.json"
        p.write_text(json.dumps({"input": "not a list"}))

        with pytest.raises(ValueError, match="expected a list"):
            load_test_cases(str(p))
