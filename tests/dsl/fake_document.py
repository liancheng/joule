from itertools import accumulate, chain

import lsprotocol.types as L
import tree_sitter as T
from rich.text import Text

from joule import ast as A
from joule.maybe import must
from joule.model import ScopeResolver
from joule.parsing import parse_jsonnet

from .marked_range import parse_marked_locations


class FakeDocument:
    def __init__(self, source: str, uri: str = "file:///tmp/test.jsonnet") -> None:
        self.uri = uri
        self.source, self.locations = parse_marked_locations(source, uri)
        self.cst = parse_jsonnet(self.source)
        self.ast = ScopeResolver().resolve(A.Document.from_cst(self.uri, self.cst))
        self.body = self.ast.body
        self.lines = self.source.splitlines(keepends=True)

        # When the source ends with a newline, `str.splitlines` does not preserve the
        # last empty line.
        if source.endswith("\n"):
            self.lines.append("")

        # Computes the character offset of the first character in each line, used for
        # converting 2D positions to 1D offsets.
        self.line_offsets: list[int] = list(
            accumulate(chain([0], map(len, self.lines)))
        )

    @property
    def location(self) -> L.Location:
        return self.body.location

    def __matmul__(self, mark: int) -> A.AST:
        return self.node_at(mark)

    def at(self, mark: int) -> L.Location:
        return self.locations[mark]

    def start_of(self, mark: int) -> L.Position:
        return self.at(mark).range.start

    def end_of(self, mark: int) -> L.Position:
        return self.at(mark).range.end

    def query_one(self, query: T.Query, capture: str) -> A.AST:
        node = T.QueryCursor(query).captures(self.cst)[capture][0]
        return A.AST.from_cst(self.uri, node)

    def node_at(self, target: int | L.Position | L.Range) -> A.AST:
        if isinstance(target, int):
            target = self.at(target).range
        return must(self.body.node_at(target))

    def offset_of(self, pos: L.Position) -> int:
        return self.line_offsets[pos.line] + pos.character

    def highlight(
        self, ranges: tuple[L.Range, str] | list[tuple[L.Range, str]]
    ) -> Text:
        """Renders the Jsonnet document with given text ranges highlighted.

        The document is rendered with its URI, a top ruler, an optional bottom ruler
        for long documents, and a line number gutter:

        ```plaintext
        file:///tmp/test.jsonnet    <-- Document URI
           0    5   10   15         <-- Top ruler
          '|''''|''''|''''|'''
        0 |local x = { f: 1 };
        1 |local y = x.f;
        2 |y + 1
        ^^
          Line number gutter
        ```

        NOTE: To be consistent with LSP, both line and column numbers are 0 based.
        """
        if isinstance(ranges, tuple):
            ranges = [ranges]

        styled = Text.styled
        rendered = []

        uri_line = styled(self.uri, "grey50")
        rendered.append(uri_line)

        # Renders the ranges.
        rendered_source = styled(self.source, "default")
        for span, style in ranges:
            rendered_source.stylize(
                style,
                start=self.offset_of(span.start),
                end=self.offset_of(span.end),
            )

        raw_lines = self.source.splitlines()
        width = max(map(len, raw_lines))
        height = len(raw_lines)

        # The width of the line number gutter equals to the max width of the line
        # numbers plus one (for a padding space).
        line_no_width = len(str(height))
        gutter_width = line_no_width + 1

        def render_ruler(width: int, left_padding: int) -> list[Text]:
            # Assuming that the document has 10 lines with a max line width of 18, to
            # render a ruler, produces a sequence with step 5 first:
            #
            #   [0, 5, 10, 15]
            #
            every_5_chars = range(0, (width - 1) // 5 * 5 + 1, 5)

            # Prints each number with a width of 5, right aligned ("." for space):
            #
            #   ["....0", "....5", "...10", "...15"]
            #
            header_segs = [f"{i:>5}" for i in every_5_chars]

            # Joins the segments and chops off the leading spaces, producing:
            #
            #   ".0....5...10...15"
            #
            # The leading space is due to column numbers being 0 based.
            header_line = styled("".join(header_segs)[3:], "grey50")

            # Produces the guide line according to the max line width, e.g.:
            #
            #   "'|''''|''''|''''|''"
            #
            # Again, the leading "'" is due to column numbers being 0 based.
            guide_line = styled(("'|'''" * (width // 5 + 1))[: width + 1], "grey50")

            # Adds left padding for the line number gutter. For a document with 10
            # lines, the gutter width is 3:
            #
            #   "....0....5...10...15"
            #   "...'|''''|''''|''''|'''"
            #
            header_line.pad_left(left_padding)
            guide_line.pad_left(left_padding)

            return [header_line, guide_line]

        # Renders a top horizontal ruler.
        ruler_lines = render_ruler(width, gutter_width)
        rendered.extend(ruler_lines)

        # Renders source lines with line numbers.
        for i, line in enumerate(rendered_source.split()):
            line_no = styled(f"{i:>{line_no_width}} |", "grey50")
            rendered.append(line_no + line)

        # Renders a bottom horizontal ruler for long documents.
        if height > 5:
            rendered.extend(ruler_lines)

        return Text("\n").join(rendered)

    def var(self, *, at: int, name: str) -> A.Id.Var:
        return A.Id.Var(self.at(at), name)

    def var_ref(self, *, at: int, name: str) -> A.Id.VarRef:
        return A.Id.VarRef(self.at(at), name)

    def field_ref(self, *, at: int, name: str) -> A.Id.FieldRef:
        return A.Id.FieldRef(self.at(at), name)

    def param_ref(self, *, at: int, name: str) -> A.Id.ParamRef:
        return A.Id.ParamRef(self.at(at), name)

    def fixed_key(self, *, at: int, name: str) -> A.FixedKey:
        return A.FixedKey(self.at(at), A.Id.Field(self.at(at), name))

    def num(self, *, at: int, value: float | int) -> A.Num:
        return A.Num(self.at(at), float(value))

    def true(self, *, at: int) -> A.Bool:
        return A.Bool(self.at(at), True)

    def false(self, *, at: int) -> A.Bool:
        return A.Bool(self.at(at), False)

    def string(self, *, at: int, value: str) -> A.Str:
        return A.Str(self.at(at), value)

    def importee(self, *, at: int, value: str) -> A.Importee:
        return A.Importee(self.at(at), value)

    def computed_key(self, *, at: int, expr: A.Expr) -> A.ComputedKey:
        return A.ComputedKey(self.at(at), expr)

    def fn(self, *, at: int, params: list[A.Param], body: A.Expr) -> A.Fn:
        return A.Fn(self.at(at), params, body)

    def call(self, *, at: int, fn: A.Expr, args: list[A.Arg]) -> A.Call:
        return A.Call(self.at(at), fn, args)

    def array(self, *, at: int, values: list[A.Expr]) -> A.Array:
        return A.Array(self.at(at), values)

    def object(
        self,
        *,
        at: int,
        members: list[A.Bind | A.Assert | A.Field] = [],
    ) -> A.Object:
        binds = []
        asserts = []
        fields = []

        for ast in members:
            match ast:
                case A.Bind():
                    binds.append(ast)
                case A.Assert():
                    asserts.append(ast)
                case A.Field():
                    fields.append(ast)

        return A.Object(self.at(at), binds, asserts, fields)

    def if_(self, *, at: int, condition: A.Expr) -> A.IfSpec:
        return A.IfSpec(self.at(at), condition)

    def for_(self, *, at: int, id: A.Id.Var, source: A.Expr) -> A.ForSpec:
        return A.ForSpec(self.at(at), id, source)

    def assert_(
        self, *, at: int, condition: A.Expr, message: A.Expr | None = None
    ) -> A.Assert:
        return A.Assert(self.at(at), condition, message)

    def local(self, *, at: int, binds: list[A.Bind], body: A.Expr) -> A.Local:
        return A.Local(self.at(at), binds, body)

    def import_(self, *, at: int, path: A.Importee) -> A.Import:
        return A.Import(self.at(at), A.ImportType.Default, path)

    def importbin(self, *, at: int, path: A.Importee) -> A.Import:
        return A.Import(self.at(at), A.ImportType.Bin, path)

    def importstr(self, *, at: int, path: A.Importee) -> A.Import:
        return A.Import(self.at(at), A.ImportType.Str, path)

    def list_comp(
        self,
        *,
        at: int,
        expr: A.Expr,
        for_spec: A.ForSpec,
        comp_spec: A.CompSpec = [],
    ) -> A.ListComp:
        return A.ListComp(self.at(at), expr, for_spec, comp_spec)

    def slice(
        self,
        *,
        at: int,
        expr: A.Expr,
        begin: A.Expr,
        end: A.Expr | None = None,
        step: A.Expr | None = None,
    ) -> A.Slice:
        return A.Slice(self.at(at), expr, begin, end, step)

    def element_at(
        self,
        *,
        at: int,
        collection: A.Expr,
        key: A.Expr,
    ) -> A.Slice:
        return A.Slice(self.at(at), collection, key)

    def dollar(self, *, at: int) -> A.Dollar:
        return A.Dollar(self.at(at))
