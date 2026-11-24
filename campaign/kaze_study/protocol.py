"""Explicit wire families. A typed backend is never a prepared-native alias."""
from dataclasses import dataclass

from .data import fields, identity, integer, relative, sha
from .errors import Refusal


@dataclass(frozen=True)
class Family:
    protocol: str
    plan: str
    result: str
    contract: str
    store_plan: str
    backend_format: str
    backend_method: str


B63 = Family("SERVERCTL_B63_V2", "B63_PREPARED_SERVER_PLAN_V2",
    "B63_READ_ONLY_PREPARED_LIFETIME_RESULT_V2", "B63_PREPARED_LIFETIME_EXECUTION_CONTRACT_V2",
    "B63_ORIGINAL_ROOT_PREPARED_SERIAL_PLAN_V2", "B63_BACKEND_EXECUTION_BINDING_V1", "B63_PREPARED_NATIVE_V1")
B65 = Family("SERVERCTL_B65_V3", "B65_TYPED_SERVER_PLAN_V3",
    "B65_READ_ONLY_TYPED_LIFETIME_RESULT_V4", "B65_TYPED_LIFETIME_EXECUTION_CONTRACT_V4",
    "B65_ORIGINAL_ROOT_TYPED_SERIAL_PLAN_V4", "B65_TYPED_BACKEND_EXECUTION_BINDING_V2", "B65_TYPED_EXECUTION_V2")


def family(protocol):
    for item in (B63, B65):
        if item.protocol == protocol:
            return item
    raise Refusal("UNKNOWN_ENGINE_PROTOCOL_FAMILY", protocol)


def typed_build(receipt, source, runtime, capability_sha256):
    fields(receipt, ("format", "artifact", "runtime", "engine_source", "generated_c", "support_sources",
        "compiler", "cython", "headers", "command", "profile", "execution_domain", "capabilities", "capability_sha256"), "B65 build receipt")
    if receipt["format"] != "B65_NATIVE_BUILD_RECEIPT_V2" or receipt["execution_domain"] != B65.backend_method:
        raise Refusal("B65_BUILD_FAMILY")
    profiles = {"win32": "B65_WINDOWS_AMD64_CPYTHON314_ZIG_V1", "linux": "B65_LINUX_X86_64_CPYTHON314_GCC_V1"}
    br = fields(receipt["runtime"], ("implementation", "python", "cache_tag", "ext_suffix", "platform", "machine"), "B65 ABI")
    if (br["python"] != runtime["python"] or br["platform"] != runtime["platform"] or
            br["implementation"] != "cpython" or br["cache_tag"] != "cpython-314" or
            receipt["profile"] != profiles.get(br["platform"])):
        raise Refusal("B65_BUILD_RUNTIME_PROFILE")
    if type(receipt["support_sources"]) is not dict or not 1 <= len(receipt["support_sources"]) <= 64:
        raise Refusal("B65_SUPPORT_SOURCES")
    for item in (receipt["artifact"], receipt["engine_source"], receipt["generated_c"], *receipt["support_sources"].values()):
        fields(item, ("path", "bytes", "sha256"), "B65 source/artifact")
        relative(item["path"]); integer(item["bytes"], "build bytes", 1, 128 * 2**20); sha(item["sha256"])
        if source.get(item["path"]) != {k: item[k] for k in ("bytes", "sha256")}:
            raise Refusal("B65_BUILD_SOURCE_MEMBER_BINDING", item["path"])
    if not receipt["artifact"]["path"].endswith(br["ext_suffix"]):
        raise Refusal("B65_BINARY_ABI_SUFFIX")
    if identity(receipt["capabilities"]) != sha(receipt["capability_sha256"]) or receipt["capability_sha256"] != capability_sha256:
        raise Refusal("B65_BUILD_CAPABILITY_BINDING")
    caps = receipt["capabilities"]
    if caps.get("method") != B65.backend_method or caps.get("changes_scientific_work") is not False:
        raise Refusal("B65_BUILD_CAPABILITY_DOMAIN")
    fields(caps["limits"], ("branches", "links", "loads", "nodes"), "B65 hardware caps")
    for name, limit in caps["limits"].items():
        integer(limit, name, 1, 65536)
    flags = receipt["compiler"].get("flags")
    if type(flags) is not list or "-fno-fast-math" not in flags or "-ffp-contract=off" not in flags or "-ffast-math" in flags:
        raise Refusal("B65_ORDERED_BUILD_FLAGS")
    return receipt
