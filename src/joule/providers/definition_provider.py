from typing import Iterable

import lsprotocol.types as L

from joule.ast import (
    AST,
    AnalysisPhase,
    Arg,
    Binding,
    Call,
    Document,
    Dollar,
    Field,
    FieldAccess,
    Fn,
    Id,
    If,
    Object,
    Scope,
)
from joule.util import maybe


class DefinitionProvider:
    def __init__(self, tree: Document) -> None:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        self.tree = tree

    def serve(self, pos: L.Position) -> list[L.Location]:
        return [
            binding.id.location
            for node in maybe(self.tree.node_at(pos))
            for binding in self.find_bindings(node)
        ]

    def find_bindings(self, node: AST) -> Iterable[Binding]:
        match node:
            case Id.VarRef() as ref:
                return self.find_var_binding(ref)
            case Id.FieldRef() as ref:
                return self.find_field_binding(ref)
            case Id.ParamRef() as ref:
                return self.find_param_binding(ref)
            case _:
                return ()

    def find_var_binding(self, ref: Id.VarRef) -> Iterable[Binding]:
        return (binding for var in maybe(ref.var) for binding in maybe(var.binding))

    def find_field_binding(self, ref: Id.FieldRef) -> Iterable[Binding]:
        return (
            binding
            for parent in maybe(ref.parent)
            for scope in self.find_field_scope(parent.to(FieldAccess).obj)
            for binding in maybe(scope.get(ref.name))
        )

    def find_param_binding(self, ref: Id.ParamRef) -> Iterable[Binding]:
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
                        for binding in self.find_bindings(node)
                        if isinstance((fn := binding.target), Fn)
                    )
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

    def find_field_scope(self, node: AST) -> Iterable[Scope]:
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
                    for scope in self.find_field_scope(binding.target.to(Field).value)
                )

            case Id.VarRef():
                return (
                    scope
                    for binding in self.find_var_binding(node)
                    for scope in self.find_field_scope(binding.target)
                )

            case If():
                return (
                    scope for e in node.branches for scope in self.find_field_scope(e)
                )

            case Object():
                return (scope for scope in maybe(node.field_scope))

            case _:
                return ()
