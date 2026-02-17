from typing import Iterable

import lsprotocol.types as L

from joule.ast import (
    AST,
    AnalysisPhase,
    Arg,
    Call,
    Document,
    Dollar,
    Expr,
    Field,
    FieldAccess,
    FieldBinding,
    FieldScope,
    Fn,
    Id,
    Import,
    ImportType,
    Object,
    VarBinding,
)
from joule.maybe import Maybe, maybe
from joule.model.document_loader import DocumentLoader


class DefinitionProvider:
    def __init__(self, loader: DocumentLoader) -> None:
        self.document_loader = loader

    def serve(self, tree: Document, pos: L.Position) -> list[L.Location]:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved

        return [
            location
            for node in maybe(tree.node_at(pos))
            for location in self.find_definition(node)
        ]

    def find_definition(self, node: AST) -> Iterable[L.Location]:
        match node:
            case Id.VarRef() as ref:
                return (b.id.location for b in self.find_var_binding(ref))
            case Id.FieldRef() as ref:
                return (b.id.location for b in self.find_field_binding(ref))
            case Id.ParamRef() as ref:
                return (b.id.location for b in self.find_param_binding(ref))
            case _:
                return ()

    def find_var_binding(self, ref: Id.VarRef) -> Iterable[VarBinding]:
        return (binding for var in maybe(ref.var) for binding in maybe(var.binding))

    def find_field_binding(self, ref: Id.FieldRef) -> Iterable[FieldBinding]:
        return (
            binding
            for parent in maybe(ref.parent)
            if (field_access := parent.to(FieldAccess))
            for scope in self.find_field_scope(field_access.obj)
            for binding in maybe(scope.get(ref.name))
        )

    def find_param_binding(self, ref: Id.ParamRef) -> Iterable[VarBinding]:
        # Given a function parameter reference in a named function call argument, this
        # function finds the binding where the function parameter is defined.
        #
        # The following example helps explain the process:
        #
        #   local func(p) = p + 1;
        #         ^1   ^2
        #   func(p = 1)
        #   ^3   ^4
        #
        # Given `ref` pointing to the parameter reference `p` at location 4, the goal is
        # to find the function parameter `p` at location 2:
        #
        # 1. Find the parent of `ref`, `arg`, an `Arg` node pointing to `p = 1`.
        # 2. Find the parent of `arg`, `call`, a `Call` node pointing to `func(p = 1)`.
        #    Now `call.fn` points to `func` at location 3, which references a function.
        # 3. Find the `Fn` definition of `func` at location 1.
        # 4. Find parameter `p` at location 2 from the parameter list of the `Fn` node.

        def find_call(ref: Id.ParamRef) -> Iterable[Call]:
            return (
                call
                for ref_parent in maybe(ref.parent)
                if (arg := ref_parent.to(Arg))
                for arg_parent in maybe(arg.parent)
                if (call := arg_parent.to(Call))
            )

        def find_fn(node: AST) -> Iterable[Fn]:
            match node:
                case Fn():
                    return maybe(node)
                case Id.VarRef():
                    return (
                        fn
                        for binding in self.find_var_binding(node)
                        for fn in find_fn(binding.target)
                    )
                case Id.FieldRef():
                    return (
                        fn
                        for binding in self.find_field_binding(node)
                        for fn in find_fn(binding.target)
                    )
                case Field(_, _, Fn() as fn, _):
                    return [fn]
                case FieldAccess():
                    return find_fn(node.field)
                case _:
                    return ()

        def find_param(fn: Fn, name: str) -> Iterable[Id.Var]:
            return (param.id for param in fn.params if param.id.name == name)

        return (
            binding
            for call in find_call(ref)
            for fn in find_fn(call.fn)
            for param in find_param(fn, ref.name)
            for binding in maybe(param.binding)
        )

    def load_importee(self, node: Import) -> Maybe[AST]:
        assert node.type == ImportType.Default
        return maybe(
            self.document_loader.load_importee(
                node.location.uri,
                node.path.value,
                raise_on_failure=False,
            )
        )

    def find_field_scope(self, node: AST) -> Iterable[FieldScope]:
        match node:
            case Dollar():

                def outer_most_object(
                    node: AST | None, so_far: Object | None = None
                ) -> Object | None:
                    match node:
                        case None:
                            return so_far
                        case Object():
                            return outer_most_object(node.parent, node)
                        case _:
                            return outer_most_object(node.parent, so_far)

                return (
                    scope
                    for obj in maybe(outer_most_object(node))
                    for scope in maybe(obj.field_scope)
                )

            case FieldAccess():
                return (
                    scope
                    for binding in self.find_field_binding(node.field)
                    if (field_value := binding.target.to(Field).value)
                    for scope in self.find_field_scope(field_value)
                )

            case Id.FieldRef():
                return (
                    scope
                    for parent in maybe(node.parent)
                    if (field_access := parent.to(FieldAccess))
                    for scope in self.find_field_scope(field_access)
                )

            case Id.VarRef():
                return (
                    scope
                    for binding in self.find_var_binding(node)
                    for scope in self.find_field_scope(binding.target)
                )

            case Import() if node.type == ImportType.Default:
                return (
                    scope
                    for importee in self.load_importee(node)
                    for scope in self.find_field_scope(importee)
                )

            case Object():
                return (scope for scope in maybe(node.field_scope))

            case Expr():
                return (
                    scope
                    for tail in node.tails
                    for scope in self.find_field_scope(tail)
                )

            case _:
                return ()
