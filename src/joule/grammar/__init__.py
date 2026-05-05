from importlib import resources

from parsimonious import Grammar


def load_grammar(name: str):
    grammar_file = resources.files("joule.grammar").joinpath(name)
    return Grammar(grammar_file.read_text())
