"""Trusted deterministic operators for the existing investigation executor.

HTTP plans select registered names and validated data. They never import code.
Descriptors describe execution mechanics, not semantic accuracy.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Callable

from .schema import InputError, dumps

VERSION = 'analysis-operator-registry/1'


@dataclass(frozen=True)
class Parameters:
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    validators: tuple[tuple[str, Callable], ...] = ()
    comparison: bool = False

    def validate(self, params):
        if (not isinstance(params, dict) or not set(self.required) <= set(params)
                or set(params) - set(self.required + self.optional)):
            raise InputError('Explicit analysis source binding or comparison parameters required')
        if any(not isinstance(params[k], str) or not params[k] for k in self.identifiers):
            raise InputError('Analysis identifiers must be nonempty strings')
        for name, validator in self.validators:
            if name in params:
                validator(deepcopy(params[name]))
        if self.comparison:
            if not all(isinstance(params[k], list) and all(isinstance(i, str) for i in params[k])
                       and len(set(params[k])) == len(params[k]) for k in ('focus', 'reference')):
                raise InputError('Explicit comparison populations required')
            if set(params['focus']) & set(params['reference']):
                raise InputError('Comparison populations overlap')
            if 'width' in params and (type(params['width']) is not int or not 2 <= params['width'] <= 20):
                raise InputError('Flow width must be an integer from 2 to 20')

    def describe(self):
        return dict(required=list(self.required), optional=list(self.optional),
                    identifiers=list(self.identifiers),
                    validated_fields=[name for name, _ in self.validators],
                    comparison=self.comparison)


@dataclass(frozen=True)
class Dependency:
    operation: str
    name: str


@dataclass(frozen=True)
class Dependencies:
    required: tuple[Dependency, ...] = ()
    variadic: str | None = None

    def validate(self, inputs, preceding):
        if len(inputs) < len(self.required) or (self.variadic is None and len(inputs) != len(self.required)):
            raise InputError('Analysis dependency count mismatch')
        for i, name in enumerate(inputs):
            expected = self.required[i].operation if i < len(self.required) else self.variadic
            if preceding[name] != expected:
                raise InputError('Analysis dependency type mismatch')

    def describe(self):
        return dict(required=[dict(operation=d.operation, name=d.name) for d in self.required],
                    variadic_operation=self.variadic)


@dataclass(frozen=True)
class Binding:
    # params: explicit run/hash; dependency: inherit a verified upstream run;
    # population: compare bound runs, with no single rollout/source graph.
    mode: str = 'params'
    source_input: int | None = None
    complete_population: bool = False


@dataclass(frozen=True)
class Context:
    store: object
    params: dict
    inputs: list
    run: dict | None
    graph: dict | None


@dataclass(frozen=True)
class Operation:
    name: str
    version: str
    contract: dict
    parameters: Parameters
    execute: Callable
    dependencies: Dependencies = field(default_factory=Dependencies)
    binding: Binding = field(default_factory=Binding)

    def describe(self):
        return dict(schema=VERSION, parameters=self.parameters.describe(),
                    dependencies=self.dependencies.describe(),
                    binding=dict(mode=self.binding.mode, source_input=self.binding.source_input,
                                 complete_population=self.binding.complete_population),
                    execution='deterministic', new_model_calls=0)


class Registry:
    def __init__(self):
        self._operators = {}
        # Compatibility view consumed by existing version-pinned measurements.
        # Registration owns additions; changing semantics requires a new version.
        self.versions = {}

    def register(self, operation):
        if not isinstance(operation, Operation):
            raise TypeError('Register an Operation descriptor')
        if not operation.name or not isinstance(operation.name, str) or operation.name in self._operators:
            raise ValueError('Operation name must be new and nonempty')
        if not isinstance(operation.version, str) or not operation.version or not callable(operation.execute):
            raise ValueError('Operation requires a version and executor')
        p, d, b = operation.parameters, operation.dependencies, operation.binding
        if not isinstance(p, Parameters) or not isinstance(d, Dependencies) or not isinstance(b, Binding):
            raise ValueError('Operation requires typed parameters, dependencies and binding')
        fields = p.required + p.optional
        if len(set(fields)) != len(fields) or any(not isinstance(k, str) or not k for k in fields):
            raise ValueError('Parameter names must be unique nonempty strings')
        if not set(p.identifiers) <= set(p.required) or any(name not in fields or not callable(fn) for name, fn in p.validators):
            raise ValueError('Parameter checks must refer to declared fields')
        if b.mode not in {'params', 'dependency', 'population'}:
            raise ValueError('Unsupported source binding mode')
        if b.mode == 'params' and not {'run_id', 'source_hash'} <= set(p.required):
            raise ValueError('A source operator needs explicit run and hash parameters')
        if b.mode == 'dependency':
            if type(b.source_input) is not int or not 0 <= b.source_input < len(d.required):
                raise ValueError('Inherited source must name a required dependency')
        elif b.source_input is not None:
            raise ValueError('Only inherited source bindings take source_input')
        if b.mode == 'population' and (not p.comparison or not d.variadic or d.required):
            raise ValueError('Population operators require homogeneous variadic dependencies and comparison parameters')
        if p.comparison and (b.mode != 'population' or not {'focus', 'reference'} <= set(p.required)):
            raise ValueError('Comparison parameters require a population binding')
        names = [slot.name for slot in d.required]
        if len(set(names)) != len(names) or any(not isinstance(n, str) or not n for n in names):
            raise ValueError('Dependency slots need unique names')
        dependency_ops = [slot.operation for slot in d.required] + ([d.variadic] if d.variadic else [])
        if any(name not in self._operators for name in dependency_ops):
            raise ValueError('Register dependencies before their consumer')
        if any(self._operators[name].binding.mode == 'population' for name in dependency_ops):
            raise ValueError('Dependencies must retain an individual rollout binding')
        required = {'label', 'question', 'grain', 'boundary', 'validation', 'input_kind',
                    'evidence_needs', 'new_model_calls', 'observer_input'}
        contract = operation.contract
        if (not isinstance(contract, dict) or not required <= set(contract)
                or type(contract['new_model_calls']) is not int or contract['new_model_calls'] != 0):
            raise ValueError('Declare the deterministic operation meaning, evidence and observer contract')
        if not isinstance(contract['evidence_needs'], list) or any(not isinstance(x, str) for x in contract['evidence_needs']):
            raise ValueError('Evidence needs must be named capabilities')
        observer = contract['observer_input']
        if (not isinstance(observer, dict) or set(observer) != {'accepted', 'preferred', 'guidance'}
                or not isinstance(observer['accepted'], list) or not observer['accepted']
                or any(x not in {'source', 'observed'} for x in observer['accepted'])
                or observer['preferred'] not in observer['accepted']
                or not isinstance(observer['guidance'], str) or not observer['guidance']):
            raise ValueError('Declare accepted and preferred observer inputs and guidance')
        dumps(contract)
        # Retain neither caller-owned mutable contract data nor serialization hooks.
        from dataclasses import replace
        self._operators[operation.name] = replace(operation, contract=deepcopy(contract))
        self.versions[operation.name] = operation.version

    def __contains__(self, name):
        return name in self._operators

    def get(self, name):
        try:
            return self._operators[name]
        except KeyError as exc:
            raise InputError('Unregistered analysis operation') from exc

    def contracts(self):
        return {name: deepcopy(op.contract) for name, op in self._operators.items()}

    def catalog(self, schema):
        return {'schema': schema, 'operator_schema': VERSION, 'operations': [
            dict(id=name, implementation_version=self.versions[name],
                 **deepcopy(op.contract), operator=op.describe())
            for name, op in self._operators.items()],
            'scope': 'Registered deterministic operations over saved evidence. No implicit inference, semantic accuracy certification or automatic framework compatibility.'}

    def projection_plan(self, operation, supplied, *, schema, name='observation'):
        """Expand registered dependency slots using one explicit source binding."""
        nodes = []
        def visit(op_name, node_name, path):
            op = self.get(op_name)
            if op.binding.mode == 'population' or op.dependencies.variadic:
                raise InputError('Population operations need explicit comparison inputs')
            inputs = []
            for slot in op.dependencies.required:
                child = path + slot.name
                visit(slot.operation, child, child + '/')
                inputs.append(child)
            params = {key: deepcopy(supplied[key]) for key in op.parameters.required + op.parameters.optional if key in supplied}
            op.parameters.validate(params)
            nodes.append(dict(name=node_name, op=op_name, inputs=inputs, params=params))
        visit(operation, name, '')
        if len({n['name'] for n in nodes}) != len(nodes):
            raise InputError('Dependency expansion has colliding node names')
        return {'schema': schema, 'nodes': nodes}
