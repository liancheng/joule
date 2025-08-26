#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "pygls",
#   "tree-sitter",
#   "tree-sitter-language-pack",
# ]
# ///

import logging
from textwrap import dedent

import lsprotocol.types as L
import tree_sitter as T
from pygls.server import LanguageServer
from tree_sitter_language_pack import get_language, get_parser

logging.basicConfig(
    filename="pygls.log",
    filemode="w",
    level=logging.DEBUG,
)


server = LanguageServer("pj", "v0.1")


def document_root(uri: str) -> T.Node:
    source = server.workspace.get_document(uri).source
    return get_parser("jsonnet").parse(source.encode("utf-8")).root_node


@server.feature(L.TEXT_DOCUMENT_COMPLETION)
def completions(params: L.CompletionParams):
    root_node = document_root(params.text_document.uri)
    query = T.Query(
        get_language("jsonnet"),
        dedent(
            """\
            (local_bind
              (bind (id) @local-bind.function
                    (params)))

            (local_bind
              (bind (id) @local-bind.variable
                    !params))

            (field
              (fieldname (id) @field.function)
              (params))

            (field
              (fieldname (id) @field)
              !params)
            """,
        ),
    )

    captures = T.QueryCursor(query).captures(root_node)

    def completion_items():
        patterns = {
            "local-bind.variable": L.CompletionItemKind.Variable,
            "local-bind.function": L.CompletionItemKind.Function,
            "field.function": L.CompletionItemKind.Method,
            "field": L.CompletionItemKind.Field,
        }

        for capture, kind in patterns.items():
            for node in captures.get(capture, []):
                if node.text is not None:
                    text = node.text.decode("utf-8")
                    yield L.CompletionItem(label=text, kind=kind)

    return L.CompletionList(
        is_incomplete=False,
        items=list(completion_items()),
    )


server.start_io()

# vim:ft=python tw=88
