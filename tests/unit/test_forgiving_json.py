import pytest

from docent_core.docent.ai_tools.rubric.forgiving_json import forgiving_json_loads


class TestForgivingJsonLoads:
    def test_valid_json(self):
        assert forgiving_json_loads('{"key": "value"}') == {"key": "value"}
        assert forgiving_json_loads("[1, 2, 3]") == [1, 2, 3]
        assert forgiving_json_loads("{}") == {}
        assert forgiving_json_loads("[]") == []

    def test_strip_leading_and_trailing_text(self):
        assert forgiving_json_loads('Here is: {"key": "value"} - end') == {"key": "value"}
        assert forgiving_json_loads("Response: [1, 2] extra") == [1, 2]

    def test_escape_newlines_in_strings(self):
        result = forgiving_json_loads('{"message": "line1\nline2"}')
        assert result == {"message": "line1\nline2"}

    def test_escape_unescaped_quotes(self):
        result = forgiving_json_loads('{"msg": "He said "hello" to me"}')
        assert result == {"msg": 'He said "hello" to me'}

    def test_fix_invalid_escape_sequences(self):
        result = forgiving_json_loads(r'{"path": "C:\xyz\abc.txt"}')
        assert result == {"path": r"C:\xyz\abc.txt"}

    def test_multiple_repairs_combined(self):
        text = 'Result: {"msg": "He said "hello"\nto me", "path": "C:\\xyz\\abc"} - done'
        result = forgiving_json_loads(text)
        assert result == {"msg": 'He said "hello"\nto me', "path": r"C:\xyz\abc"}

    def test_nested_structures(self):
        result = forgiving_json_loads('{"outer": {"inner": [1, 2]}}')
        assert result == {"outer": {"inner": [1, 2]}}

    def test_special_chars_in_strings(self):
        # Colons, brackets, etc. should not confuse the parser
        assert forgiving_json_loads('{"url": "https://example.com"}') == {
            "url": "https://example.com"
        }
        assert forgiving_json_loads('{"code": "{array[0]}"}') == {"code": "{array[0]}"}

    def test_json_types(self):
        result = forgiving_json_loads('{"bool": true, "null": null, "num": 3.14}')
        assert result == {"bool": True, "null": None, "num": 3.14}

    def test_valid_escapes_preserved(self):
        result = forgiving_json_loads(r'{"text": "line\nline\ttab", "emoji": "\u2764"}')
        assert result == {"text": "line\nline\ttab", "emoji": "❤"}

    def test_already_escaped_quotes_preserved(self):
        result = forgiving_json_loads(r'{"msg": "He said \"hello\""}')
        assert result == {"msg": 'He said "hello"'}

    def test_empty_input_raises_error(self):
        with pytest.raises(ValueError):
            forgiving_json_loads("")
        with pytest.raises(ValueError):
            forgiving_json_loads("   \n\t  ")

    def test_no_json_raises_error(self):
        with pytest.raises(ValueError):
            forgiving_json_loads("This is just text with no JSON")

    def test_primitive_values_as_json(self):
        assert forgiving_json_loads("true") is True
        assert forgiving_json_loads("false") is False
        assert forgiving_json_loads("null") is None
        assert forgiving_json_loads("42") == 42
        assert forgiving_json_loads("-3.14") == -3.14
        assert forgiving_json_loads('"hello"') == "hello"

    def test_primitive_values_with_leading_text(self):
        assert forgiving_json_loads("Result: true") is True
        assert forgiving_json_loads("Answer is: false - done") is False
        assert forgiving_json_loads("Value: null") is None
