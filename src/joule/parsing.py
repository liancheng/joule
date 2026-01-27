import tree_sitter as T
import tree_sitter_jsonnet as J


LANG_JSONNET = T.Language(J.language())
JSONNET_TS_PARSER = T.Parser(LANG_JSONNET)


def parse_jsonnet(source: str) -> T.Node:
    return JSONNET_TS_PARSER.parse(source.encode()).root_node
