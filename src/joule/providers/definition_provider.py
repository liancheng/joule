import inspect
import logging
from itertools import chain
from pathlib import Path
from typing import Iterable

import lsprotocol.types as L

from joule import ast as A
from joule.ast import (
    AnalysisPhase,
    FieldBinding,
    FieldScope,
    VarBinding,
    enclosing_node,
)
from joule.maybe import maybe
from joule.model import DocumentStore

log = logging.getLogger(__name__)


def log_node(node: A.AST) -> bool:
    caller = next(
        caller
        for frame in maybe(inspect.currentframe())
        for caller in maybe(frame.f_back)
    )

    py_file_name = Path(inspect.getfile(caller)).name
    py_line = caller.f_lineno
    py_src = f"{py_file_name}:{py_line}"

    fn_name = caller.f_code.co_name
    node_class = node.__class__.__qualname__

    jsonnet_file_path = Path.from_uri(node.location.uri)
    jsonnet_line = node.location.range.start.line + 1
    jsonnet_char = node.location.range.start.character + 1
    jsonnet_src = f"{jsonnet_file_path}:{jsonnet_line}:{jsonnet_char}"

    log.debug(f"{py_src} {fn_name} {node_class} {jsonnet_src}")
    return True


class DefinitionProvider:
    def __init__(self, store: DocumentStore) -> None:
        self.store = store
        self.seen_callers: dict[A.LocationKey, list[A.Call]] = {}

    def serve(self, tree: A.Document, pos: L.Position) -> list[L.Location]:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved

        return [
            location
            for node in maybe(tree.node_at(pos))
            for location in self.find_definition(node)
        ]

    def find_definition(self, node: A.AST) -> Iterable[L.Location]:
        log_node(node)
        match node:
            case A.Id.FieldRef() as ref:
                return (b.id.location for b in self.find_field_binding(ref))
            case A.Id.ParamRef() as ref:
                return (b.id.location for b in self.find_param_binding(ref))
            case A.Id.VarRef() as ref:
                return (b.id.location for b in self.find_var_binding(ref))
            case A.Importee():
                return (
                    doc.location
                    for uri in maybe(self.store.resolve_importee(node))
                    for doc in maybe(self.store.get(uri))
                )
            case _:
                return ()

    def find_var_binding(self, ref: A.Id.VarRef) -> Iterable[VarBinding]:
        log_node(ref)
        return (binding for var in maybe(ref.var) for binding in maybe(var.binding))

    def find_param_binding(self, ref: A.Id.ParamRef) -> Iterable[VarBinding]:
        log_node(ref)
        return (
            binding
            for call in maybe(enclosing_node(ref, A.Call, level=2))
            for fn in self.find_fn(call.callee)
            for param in fn.params
            if param.id.name == ref.name
            for binding in maybe(param.id.binding)
        )

    def find_field_binding(self, ref: A.Id.FieldRef) -> Iterable[FieldBinding]:
        log_node(ref)
        return (
            binding
            for field_access in maybe(enclosing_node(ref, A.FieldAccess, level=1))
            for scope in self.find_field_scope(field_access.obj)
            for binding in maybe(scope.get(ref.name))
        )

    def find_field_scope(self, node: A.AST) -> Iterable[FieldScope]:
        """Given an AST node returning an object, finds the field scopes of the object.

        This is the major function that helps find the definition of an object field.
        Note that due to branching, one AST node may track multiple field scopes. See
        the following examples:

         1. Array in list comprehension:

            ```plaintext
            [
                val.f for val in [{ f: 1 }, { f: 2 }]
                ^1  ^2            ^^^^^^^^3 ^^^^^^^^4
            ]
            ```

            `val` at 1 tracks the two field scopes owned by objects at 3 and 4, each
            contributes a definition of field reference `f` at 2.

         2. Conditional branches:

            ```plaintext
            local val = if condition then { f: 1 } else { f: 2 };
                                          ^^^^^^^^1     ^^^^^^^^2
            val.f
            ^3  ^4
            ```

            `val` at 3 tracks the two field scopes owned by objects at 1 and 2, each
            contributes a definition of field reference `f` at 4.
        """
        log_node(node)

        match node:
            case A.Array():
                return (
                    scope
                    for value in node.values
                    for scope in self.find_field_scope(value)
                )

            case A.Binary() if node.op == A.Operator.Plus:
                lhs_scopes = list(self.find_field_scope(node.lhs))
                rhs_scopes = list(self.find_field_scope(node.rhs))

                match lhs_scopes, rhs_scopes:
                    case [], _:
                        return rhs_scopes
                    case _, []:
                        return lhs_scopes
                    case _:
                        return (
                            parent.copy_with_child(child)
                            for parent in lhs_scopes
                            for child in rhs_scopes
                        )

            case A.Call():
                # Example:
                #
                #   local func() =
                #       local v = 1;
                #       { f: v };
                #   func().f
                #          ^1
                #
                # To find the definiton of field `f` at 2:
                #
                # - Finds the definition of `func`.
                # - Finds tail expression of the body of `func`, which is `{ f: v }`.
                # - Returns the field scope of `{ f: v }`, which contains the desired
                #   defintion of field `f`.
                return (
                    scope
                    for fn in self.find_fn(node.callee)
                    for tail in fn.body.tails
                    for scope in self.find_field_scope(tail)
                )

            case A.Dollar():

                def outermost_object(
                    node: A.AST | None, so_far: A.Object | None = None
                ) -> A.Object | None:
                    match node:
                        case None:
                            return so_far
                        case A.Object():
                            return outermost_object(node.parent, node)
                        case _:
                            return outermost_object(node.parent, so_far)

                return (
                    scope
                    for obj in maybe(outermost_object(node))
                    for scope in maybe(obj.field_scope)
                )

            case A.FieldAccess():
                return (
                    scope
                    for binding in self.find_field_binding(node.field)
                    if (field_value := binding.target.to(A.Field).value)
                    for scope in self.find_field_scope(field_value)
                )

            case A.ForSpec():
                return self.find_field_scope(node.source)

            case A.Id.FieldRef():
                return (
                    scope
                    for parent in maybe(node.parent)
                    if (field_access := parent.to(A.FieldAccess))
                    for scope in self.find_field_scope(field_access)
                )

            case A.Id.VarRef():
                return (
                    scope
                    for binding in self.find_var_binding(node)
                    for scope in self.find_field_scope(binding.target)
                )

            case A.Import() if node.type == A.ImportType.Default:
                return (
                    scope
                    for uri in maybe(self.store.resolve_importee(node.importee))
                    for importee in maybe(self.store.get(uri))
                    for scope in self.find_field_scope(importee)
                )

            case A.Object():
                return (scope for scope in maybe(node.field_scope))

            case A.Param():
                call_args = (
                    arg
                    for fn in maybe(enclosing_node(node, A.Fn, level=1))
                    for call in self.find_callers(fn)
                    for arg in maybe(call.arg_of_param(node))
                )

                return (
                    scope
                    for e in chain(maybe(node.default), call_args)
                    for scope in self.find_field_scope(e)
                )

            case A.Self():
                return (
                    scope
                    for obj in maybe(enclosing_node(node, A.Object))
                    for scope in maybe(obj.field_scope)
                )

            case A.Expr():
                return (
                    scope
                    for tail in node.tails
                    if tail is not node
                    for scope in self.find_field_scope(tail)
                )

            case _:
                return ()

    def find_callers(self, fn: A.Fn) -> Iterable[A.Call]:
        log_node(fn)

        def find(fn: A.Fn) -> Iterable[A.Call]:
            log_node(fn)
            return (
                call
                for doc in maybe(enclosing_node(fn, A.Document))
                for uri in chain(
                    self.store.recursive_importers(doc.location.uri),
                    [doc.location.uri],
                )
                for tree in maybe(self.store.get(uri))
                for call in tree.calls
                for callee in self.find_fn(call.callee)
                if callee == fn
            )

        key = A.LocationKey.of(fn.location)

        if key not in self.seen_callers:
            self.seen_callers.setdefault(key, []).extend(find(fn))

        return self.seen_callers[key]

    def find_fn(self, node: A.AST) -> Iterable[A.Fn]:
        """Given a function returning AST node, finds the definition of the function."""
        log_node(node)

        match node:
            case A.Call():
                return (
                    fn
                    for callee in self.find_fn(node.callee)
                    for tail in callee.body.tails
                    for fn in self.find_fn(tail)
                )

            case A.Field() if isinstance(fn := node.value, A.Fn):
                return maybe(fn)

            case A.FieldAccess():
                return self.find_fn(node.field)

            case A.Fn():
                return maybe(node)

            case A.Id.FieldRef():
                return (
                    fn
                    for binding in self.find_field_binding(node)
                    for fn in self.find_fn(binding.target)
                )

            case A.Id.VarRef():
                return (
                    fn
                    for binding in self.find_var_binding(node)
                    for fn in self.find_fn(binding.target)
                )

            case A.Import() if node.type == A.ImportType.Default:
                return (
                    fn
                    for uri in maybe(self.store.resolve_importee(node.importee))
                    for importee in maybe(self.store.get(uri))
                    for fn in self.find_fn(importee)
                )

            case A.Expr() if list(node.tails) != [node]:
                return (fn for tail in node.tails for fn in self.find_fn(tail))

            case _:
                return ()
