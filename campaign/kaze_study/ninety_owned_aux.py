"""Public fixture adapter; private DIRECT90D administrative ledgers are not shipped."""
from .errors import Refusal


def effective_spec(state):
    spec = state.study.spec
    if spec.get("ninety_contract", {}).get("direct_main_version") == "DIRECT90D_USER_SCOPE_V1":
        raise Refusal("PRIVATE_DIRECT90D_AUTHORITY_NOT_IN_PUBLIC_DISTRIBUTION")
    return spec
