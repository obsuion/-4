"""Strict opt-in B48 root format. Estimates/diagnoses are output, never inputs."""
from dataclasses import fields
from hashlib import sha256
from .command_estimation import CommandRollingRoot, EstimationPolicy
from .rolling_document import inputs_to_json as reference_to_json,inputs_from_json as reference_from_json,MAX_INPUT
from .long_mission_document import canonical_json
from .experiment_codec import parse_json,object_fields
from .long_mission_continuation import _bounded_tree

FORMAT='M5_COMMAND_ESTIMATION_INPUT_V1'
PACKET='M5_COMMAND_ESTIMATION_PAID_CAUSAL_CONTINUATION_V1'


def inputs_to_json(root,*,input_codec=None):
    if type(root) is not CommandRollingRoot:raise TypeError('exact B48 root')
    root.__post_init__()
    reference=reference_to_json(root.reference)if input_codec is None else reference_to_json(root.reference,input_codec=input_codec)
    data=dict(reference=parse_json(reference),
        estimation={f.name:getattr(root.estimation,f.name) for f in fields(EstimationPolicy)},
        controller_method=root.controller_method,api=root.api)
    document=dict(format=FORMAT,version=1,inputs=data)
    document['digest']=sha256(canonical_json(document).encode()).hexdigest()
    text=canonical_json(document)
    if len(text.encode())>MAX_INPUT:raise ValueError('B48 input byte bound')
    return text


def inputs_from_json(text,*,expected_digest=None,input_codec=None):
    if type(text) is not str or len(text.encode())>MAX_INPUT:raise ValueError('bounded B48 input')
    d=object_fields(parse_json(text),('format','version','inputs','digest'));_bounded_tree(d)
    if type(d['format']) is not str or d['format']!=FORMAT or type(d['version']) is not int or d['version']!=1:raise ValueError('B48 format/version')
    i=object_fields(d['inputs'],('reference','estimation','controller_method','api'))
    policy=object_fields(i['estimation'],tuple(f.name for f in fields(EstimationPolicy)))
    digest=sha256(canonical_json({n:d[n] for n in ('format','version','inputs')}).encode()).hexdigest()
    if type(d['digest']) is not str or digest!=d['digest'] or expected_digest is not None and digest!=expected_digest:raise ValueError('B48 root document binding')
    # No derived state/pose/tensor/callback field is admitted.
    if input_codec is not None:
        from .prepared_input_codec import require_scope
        require_scope(input_codec);input_codec.owner(CommandRollingRoot);input_codec.owner(EstimationPolicy)
    reference=reference_from_json(canonical_json(i['reference']))if input_codec is None else reference_from_json(canonical_json(i['reference']),input_codec=input_codec)
    root=CommandRollingRoot(reference,EstimationPolicy(**policy),i['controller_method'],i['api'])
    if input_codec is not None:input_codec.owner(CommandRollingRoot);input_codec.owner(EstimationPolicy)
    if inputs_to_json(root,input_codec=input_codec)!=canonical_json(d):raise ValueError('noncanonical B48 input')
    return root


def admit_command_reconstruction(root,count,prior):
    """Static separate estimator admission, before provider/compile/replay work."""
    from .rolling_document import admit_reconstruction
    from .command_estimation import CommandWork
    from .rolling_cache import CumulativeWork
    extra={f.name for f in fields(CommandWork)}-{f.name for f in fields(CumulativeWork)}
    data=object_fields(prior,tuple(f.name for f in fields(CommandWork)))
    base={n:v for n,v in data.items() if n not in extra}
    paid,bound=admit_reconstruction(root,count,base)
    values={f.name:getattr(paid,f.name) for f in fields(CumulativeWork)}
    work=CommandWork(**values,**{n:data[n] for n in extra});work.validate(root.quotas)
    branches=bound['forecast_invocations'];commands=branches*root.estimation.maximum_unreceived_intents
    if work.estimator_invocations+branches>root.estimation.maximum_invocations or work.estimator_command_propagations_reserved+commands>root.estimation.maximum_command_propagations:raise ValueError('B48_ESTIMATOR_RECONSTRUCTION_ADMISSION')
    if work.harness_compiles+bound['harness_compiles']+2*commands>root.quotas.max_harness_compiles:raise ValueError('B48_ESTIMATOR_RECONSTRUCTION_HARNESS_ADMISSION')
    extra_control=(commands+branches)*2**20
    if work.control_reserved+bound['control_reserved']+extra_control>root.quotas.max_control_reserved:raise ValueError('B48_ESTIMATOR_RECONSTRUCTION_CONTROL_ADMISSION')
    bound.update(estimator_invocations=branches,estimator_command_propagations=commands,
        estimator_harness_compiles=2*commands,estimator_control_units=extra_control)
    return work,bound
