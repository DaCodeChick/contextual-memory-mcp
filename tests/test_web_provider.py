from providers.web import _ReadableHTMLParser, _SearchResultParser


def test_duckduckgo_result_parser_decodes_redirect() -> None:
    parser = _SearchResultParser()
    parser.feed(
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fcharacter">Character</a>'
    )
    assert len(parser.results) == 1
    assert parser.results[0].title == "Character"
    assert parser.results[0].url == "https://example.com/character"


def test_readable_html_parser_removes_scripts() -> None:
    parser = _ReadableHTMLParser()
    parser.feed(
        "<html><head><title>Example</title><script>bad()</script></head>"
        "<body><h1>Character</h1><p>Useful profile text.</p></body></html>"
    )
    title, text = parser.result("fallback")
    assert title == "Example"
    assert "Useful profile text." in text
    assert "bad()" not in text
