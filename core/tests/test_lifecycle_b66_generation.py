"""CR03: true admitted job/callback boundaries, not an AST/stub reproducer.

These metadata/control checks establish neither new science nor Linux/LONG
qualification. The native test consumes the current, genuinely bound build.
"""
import pytest

from lifetime_support import root_for
from ops_sim.v5.lifecycle_document import dumps_root
from ops_sim.v5.lifecycle_job_prepared import admit_job_root, prepare_job_runtime
from ops_sim.v5 import lifecycle_generation as generation


def admitted_job():
    root, admission = admit_job_root(dumps_root(root_for(600)), 'b' * 64,
        build_binding={'synthetic': 'B66 generation control only'})
    return prepare_job_runtime(admission, root)


@pytest.mark.parametrize('tamper', ('replace', 'code', 'defaults', 'closure'))
def test_callback_cannot_replace_closed_predicate_and_then_mutate_graph(tamper):
    job = admitted_job()
    generation.enable(job, lambda: None)
    root = job.external_root
    old_duration = root.duration_seconds
    original = generation._Generation.closed
    code, defaults = original.__code__, original.__defaults__
    calls = []
    published = []

    def always_closed(self, transaction=None):
        return True

    def closed_closure(value):
        def replacement(self, transaction=None):
            return value
        return replacement

    def external():
        calls.append('foreign')
        if tamper == 'replace':
            generation._Generation.closed = always_closed
        elif tamper == 'code':
            original.__code__ = always_closed.__code__
        elif tamper == 'defaults':
            original.__defaults__ = (object(),)
        else:
            generation._Generation.closed = closed_closure(True)
        object.__setattr__(root, 'duration_seconds', old_duration + 1)

    try:
        with pytest.raises(ValueError, match='generation .*drift'):
            with job.transaction() as transaction:
                transaction.callback(external)
                published.append('subsequent work/publication')
        assert calls == ['foreign']
        assert published == []
        assert transaction._phase == 'FAILED'
        assert job._active is None
        assert job._work['transaction_completed'] == 0
    finally:
        generation._Generation.closed = original
        original.__code__ = code
        original.__defaults__ = defaults
        object.__setattr__(root, 'duration_seconds', old_duration)


@pytest.mark.parametrize('name', ('cheap', 'activate', 'boundary', 'callback_begin',
    'callback_end', 'verify_boundary', 'finish', 'snapshot', '__init__'))
def test_generation_dispatch_methods_are_sealed_before_trusted_dispatch(name):
    job = admitted_job()
    generation.enable(job, lambda: None)
    original = getattr(generation._Generation, name)
    try:
        setattr(generation._Generation, name, lambda *args, **kwargs: True)
        with pytest.raises(ValueError, match='generation .*drift'):
            job._guard_identity()
    finally:
        setattr(generation._Generation, name, original)


@pytest.mark.parametrize('tamper', ('replace', 'code', 'class'))
def test_generation_factory_and_class_are_sealed(tamper):
    job = admitted_job()
    generation.enable(job, lambda: None)
    original, owner = generation.enable, generation._Generation
    code = original.__code__

    def replacement(job, hook):
        return None

    try:
        if tamper == 'replace': generation.enable = replacement
        elif tamper == 'code': original.__code__ = replacement.__code__
        else: generation._Generation = type('ForeignGeneration', (), {})
        with pytest.raises(ValueError, match='generation .*drift'):
            job._full_guard()
    finally:
        generation.enable = original
        original.__code__ = code
        generation._Generation = owner


def test_foreign_owner_cannot_supply_its_own_cheap_dispatch():
    job = admitted_job()
    generation.enable(job, lambda: None)
    calls = []

    class Foreign:
        def cheap(self, *args): calls.append('untrusted dispatch')

    job._validation = job._validation_pin = Foreign()
    with pytest.raises(ValueError, match='foreign generation owner before dispatch'):
        job._guard_identity()
    assert calls == []


def test_ordinary_callback_graph_mutation_is_refused_before_more_work():
    job = admitted_job()
    validation = generation.enable(job, lambda: None)
    root = job.external_root
    duration = root.duration_seconds
    published = []
    try:
        with pytest.raises(ValueError):
            with job.transaction() as transaction:
                transaction.callback(lambda: object.__setattr__(root,
                    'duration_seconds', duration + 1))
                published.append('subsequent work/publication')
        assert published == []
        assert transaction._phase == 'FAILED'
        assert validation._phase == 'IDLE'
    finally:
        object.__setattr__(root, 'duration_seconds', duration)


def test_outer_exit_calls_full_static_hook_at_boundary_and_numeric_path_is_cheap():
    job = admitted_job()
    phases = []
    validation = generation.enable(job,
        lambda: phases.append(job._validation._phase))
    with job.transaction() as outer:
        before = validation.snapshot()
        for _ in range(5): job._full_guard(outer)
        with job.transaction() as nested:
            job._full_guard(nested)
        assert phases == []
        during = validation.snapshot()
        assert during['full_requests'] == before['full_requests']
        assert during['closed_requests'] >= before['closed_requests'] + 6
    assert phases == ['BOUNDARY']
    assert validation.snapshot()['phase'] == 'IDLE'
    assert outer._phase == 'CLOSED'


def test_exit_full_guard_sees_graph_changes_even_without_callback():
    job = admitted_job()
    generation.enable(job, lambda: None)
    root, duration = job.external_root, job.external_root.duration_seconds
    try:
        with pytest.raises(ValueError):
            with job.transaction() as transaction:
                object.__setattr__(root, 'duration_seconds', duration + 1)
        assert transaction._phase == 'FAILED'
    finally:
        object.__setattr__(root, 'duration_seconds', duration)


def test_callback_original_exception_remains_primary_after_generation_drift():
    job = admitted_job()
    generation.enable(job, lambda: None)
    original = generation._Generation.closed
    primary = RuntimeError('original foreign callback failure')

    def external():
        generation._Generation.closed = lambda *args, **kwargs: True
        raise primary

    try:
        with pytest.raises(RuntimeError) as caught:
            with job.transaction() as transaction:
                transaction.callback(external)
        assert caught.value is primary
        assert transaction._phase == 'FAILED'
        assert job._secondary_errors
    finally:
        generation._Generation.closed = original


def test_native_outer_exit_checks_bound_typed_build_before_publication():
    # Current native admission is required; no fake context/build is substituted.
    from test_lifecycle_b65 import started_pair
    state, _ = started_pair()
    context = state.backend_context
    command = context.build['command']
    published = []
    try:
        with pytest.raises(ValueError, match='changed typed build'):
            with context.transaction():
                command.append('B66 unauthorized drift')
            published.append('published after unchecked typed boundary')
        assert published == []
        assert context.job._active is None
    finally:
        command.pop()
