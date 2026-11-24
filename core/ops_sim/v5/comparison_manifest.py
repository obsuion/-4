"""Task 05C public references and explicitly counterfactual hardware vectors.

This study input format is separate from the accepted experiment/checkpoint codec.
It does not certify electrical, mechanical or radiometric compatibility.
"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from math import isfinite


SOURCES = {
    "DMAC-HIRAIS": {
        "title": "Al Dhafri et al., DubaiSat-2 High Resolution Advanced Imaging System (HiRAIS)",
        "revision": "IAC-12.B4.6A.6, 2012", "location": "section 4, final Table 1; MS bands in section 2",
        "url": "https://www.researchgate.net/publication/262805537_DubaiSat-2_High_Resolution_Advanced_Imaging_System_HiRAIS",
        "verified": "Primary author-paper full text inspected 2026-09-23; not flight validation"},
    "JSS56": {"title": "Jena-Optronik JSS 56", "revision": "April 2015",
        "location": "PDF page 2, performance data / power consumption",
        "url": "https://www.jena-optronik.de/products/space-optics-electronics/multi-spectral-imager.html?file=tl_files%2Fpdf%2FData+Sheet+JSS+56.pdf",
        "verified": "Primary datasheet inspected 2026-09-23"},
    "KGS": {"title": "Kazakhstan Gharysh Sapary, KazEOSat-2", "revision": "web page accessed 2026-09-23",
        "location": "KAZEOSAT-2 spacecraft characteristics, X-band rate",
        "url": "https://www.gharysh.kz/infrastruktura/AboutKA_DZZ22_yztp/",
        "verified": "Operator page inspected; 6.5 m native is distinct from 5 m orthophoto"},
    "BP8": {"title": "GomSpace NanoPower BP8 100 Wh", "revision": "DS1069134 rev 1.2.0, 10 April 2026",
        "location": "printed p1 section 1.2; p5 Table 2.2; p11 Table 4.1 (PDF pages 5,9,15)",
        "url": "https://gomspace.com/wp-content/uploads/2025/08/gs-ds-nanopower-bp8-100-Wh-2.pdf",
        "verified": "Primary datasheet inspected 2026-09-23"},
    "TSP": {"title": "GomSpace NanoPower TSP 45W", "revision": "DS1038993 rev 3.3, 24 May 2024",
        "location": "p8 section 2.1.1; p24 section 7, physical characteristics; conflicting summary p9",
        "url": "https://gomspace.com/wp-content/uploads/2025/09/Datasheet-NanoPower-TSP_45W.pdf",
        "verified": "Primary datasheet inspected; detailed 885 g selected, summary 750 g retained as conflict"},
    "P80": {"title": "GomSpace NanoPower P80", "revision": "web page accessed 2026-09-23",
        "location": "Technical insights: Power Supply Module and Power Management Unit",
        "url": "https://gomspace.com/product/nanopower-p80/",
        "verified": "Primary product page inspected; up-to efficiency is not a fixed efficiency"},
}


def fact(value, units, kind, consumer, *, source=None, conditions="Declared Task05C screening experiment",
         transform="identity"):
    return dict(value=value, units=units, kind=kind, source=source,
                location=None if source is None else SOURCES[source]["location"],
                conditions=conditions, transform=transform, consumer=consumer)


def manifest():
    families = {}
    for name, altitude, spacing, swath, bands, bits, storage, rate, power in (
        ("D", 680, 5, 20000, ["B", "G", "R", "NIR"], 8, 32, 30, 53.2),
        ("H", 600, 4, 12000, ["B", "G", "R", "NIR"], 10, 256, 160, 100),
        ("J", 630, 6.5, 77000, ["B", "G", "R", "red-edge", "NIR"], 12, 48, 160, 93)):
        source = "JSS56" if name == "J" else "DMAC-HIRAIS"
        values = dict(altitude_km=(altitude, "km"), native_sampling_m=(spacing, "m"),
            native_swath_m=(swath, "m"), channels=(bands, "channel identities"),
            bits_per_sample=(bits, "bit/sample"), published_storage_gbit=(storage, "Gbit"),
            reference_rate_mbps=(rate, "Mbit/s"), reference_power_w=(power, "W"))
        families[name] = {k: fact(v, u, "SOURCE", "derive_hardware."+k,
            source="KGS" if name == "J" and k == "reference_rate_mbps" else source,
            conditions=("Peak simultaneous imaging/downlink" if name == "J" else "Incoming power")
                if k == "reference_power_w" else "Native reference geometry; published hardware ceiling")
            for k, (v, u) in values.items()}
    technology = {}
    for key, value, unit, source in (
        ("nominal_pack_wh",100,"Wh","BP8"), ("working_pack_wh",86,"Wh","BP8"),
        ("discharge_a",4,"A","BP8"), ("charge_a",3.4,"A","BP8"),
        ("minimum_v",23.6,"V","BP8"), ("pack_mass_kg",.486,"kg","BP8"),
        ("array_w",45,"W","TSP"), ("array_mass_kg",.885,"kg","TSP"),
        ("array_summary_mass_kg",.750,"kg","TSP"), ("common_current_a",12,"A","P80"),
        ("system_envelope_w",300,"W","P80")):
        technology[key] = fact(value,unit,"SOURCE","derive_hardware."+key,source=source,
            conditions="BOL illuminated reference, approximately 45 W; cells at 1367 W/m2, 25 C"
            if key == "array_w" else "Published reference; see source table and unresolved compatibility limitations",
            transform="g / 1000" if "mass_kg" in key else "identity")
    assumptions = {
        "altitude_km": fact(630,"km","ASSUMED","normalized sampling/swath"),
        "charge_efficiency": fact(.9,"1","ASSUMED","eps.battery.charge_efficiency"),
        "discharge_efficiency": fact(.9,"1","ASSUMED","eps.battery.discharge_efficiency"),
        "storage_fraction": fact(1.,"1","ASSUMED","storage.usable_capacity_gb",
            conditions="Optimistic full published storage availability"),
        "net_rate_fraction": fact(1.,"1","ASSUMED","communications.nominal_downlink_data_rate_bps",
            conditions="Optimistic useful rate equals published ceiling; no RF/packet/weather model"),
        "baseline_w": fact(12.,"W","ASSUMED","PowerLoadBreakdown.base_bus_w"),
        "initial_energy_fraction": fact(.5,"1","ASSUMED","initial checkpoint battery energy"),
        "mode_factors": fact([1.,.5],"1","ASSUMED","acquisition_power_w and transmitter.electrical_power_w",
            conditions="Separate mutually exclusive incremental proxies P_ref * factor; neither calibrated nor conservative bound"),
    }
    result = dict(version=1, sources=deepcopy(SOURCES), families=families, technology=technology,
                  assumptions=assumptions, allocations={f"E{i}": {"packs":5-i,"arrays":1+i} for i in range(1,5)})
    validate_manifest(result)
    return result


def _keys(obj, expected):
    if type(obj) is not dict or set(obj) != set(expected):
        raise ValueError("manifest keys do not match the declared format")


def validate_manifest(m):
    """Reject ambiguous JSON/types, missing provenance and inconsistent units/scopes."""
    _keys(m, ("version","sources","families","technology","assumptions","allocations"))
    if type(m["version"]) is not int or m["version"] != 1:
        raise ValueError("unsupported manifest version")
    if m["sources"] != SOURCES:
        raise ValueError("this study requires its verified source ledger")
    _keys(m["families"], "DHJ")
    family_units = dict(altitude_km="km", native_sampling_m="m", native_swath_m="m", channels="channel identities",
        bits_per_sample="bit/sample", published_storage_gbit="Gbit",reference_rate_mbps="Mbit/s",reference_power_w="W")
    technology_units = dict(nominal_pack_wh="Wh",working_pack_wh="Wh",discharge_a="A",charge_a="A",minimum_v="V",
        pack_mass_kg="kg",array_w="W",array_mass_kg="kg",array_summary_mass_kg="kg",common_current_a="A",system_envelope_w="W")
    assumption_units = dict(altitude_km="km",charge_efficiency="1",discharge_efficiency="1",storage_fraction="1",
        net_rate_fraction="1",baseline_w="W",initial_energy_fraction="1",mode_factors="1")
    for block, units, kind in [*( (x,family_units,"SOURCE") for x in m["families"].values()),
                               (m["technology"],technology_units,"SOURCE"),(m["assumptions"],assumption_units,"ASSUMED")]:
        _keys(block, units)
        for key, entry in block.items():
            _keys(entry,("value","units","kind","source","location","conditions","transform","consumer"))
            if entry["units"] != units[key] or entry["kind"] != kind:
                raise ValueError("incorrect manifest units or classification")
            for text in ("conditions","transform","consumer"):
                if type(entry[text]) is not str or not entry[text].strip():
                    raise ValueError("manifest requires explicit field provenance")
            if kind == "SOURCE":
                if entry["source"] not in SOURCES or entry["location"] != SOURCES[entry["source"]]["location"]:
                    raise ValueError("source location is missing or inconsistent")
            elif entry["source"] is not None or entry["location"] is not None:
                raise ValueError("assumption must not masquerade as sourced")
            value = entry["value"]
            if key == "channels":
                if type(value) is not list or value not in (["B","G","R","NIR"],["B","G","R","red-edge","NIR"]):
                    raise ValueError("unsupported spectral mapping")
            elif key == "mode_factors":
                if type(value) is not list or any(type(x) not in (int,float) for x in value) or value != [1.,.5]:
                    raise ValueError("predeclared power sensitivity must be preserved")
            elif type(value) not in (int,float) or not isfinite(value) or value <= 0:
                raise ValueError("manifest quantities must be positive finite built-in numbers")
            if key == "bits_per_sample" and type(value) is not int:
                raise ValueError("integer bit depth required")
    for key in ("charge_efficiency","discharge_efficiency","storage_fraction","net_rate_fraction","initial_energy_fraction"):
        if m["assumptions"][key]["value"] > 1:
            raise ValueError("fraction exceeds one")
    _keys(m["allocations"], ("E1","E2","E3","E4"))
    for i in range(1,5):
        allocation = m["allocations"][f"E{i}"]
        _keys(allocation,("packs","arrays"))
        if any(type(v) is not int for v in allocation.values()) or allocation != dict(packs=5-i,arrays=1+i):
            raise ValueError("the four six-unit allocations are fixed")


def load_manifest(text):
    def pairs(items):
        result = {}
        for k,v in items:
            if k in result: raise ValueError("duplicate manifest key")
            result[k] = v
        return result
    def invalid(value): raise ValueError("nonfinite JSON constant: "+value)
    result = json.loads(text,object_pairs_hook=pairs,parse_constant=invalid)
    validate_manifest(result)
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def derive_hardware(m, identity, mode_factor=1.):
    validate_manifest(m)
    if type(identity) is not str or identity not in [f"{f}-{e}" for f in "DHJ" for e in m["allocations"]]:
        raise ValueError("unknown hardware vector")
    if type(mode_factor) not in (float,int) or mode_factor not in (1.,.5):
        raise ValueError("unsupported mode-power factor")
    f,e = identity.split("-")
    family = {k:v["value"] for k,v in m["families"][f].items()}
    t = {k:v["value"] for k,v in m["technology"].items()}
    a = {k:v["value"] for k,v in m["assumptions"].items()}
    packs, arrays = (m["allocations"][e][k] for k in ("packs","arrays"))
    ratio = Fraction(str(a["altitude_km"]))/Fraction(str(family["altitude_km"]))
    spacing = Fraction(str(family["native_sampling_m"]))*ratio
    swath = Fraction(str(family["native_swath_m"]))*ratio
    # Charge API accepts BUS input BEFORE loss, discharge API supplies BUS AFTER loss.
    charge = min(t["system_envelope_w"], t["minimum_v"]*t["common_current_a"],
                 t["minimum_v"]*min(packs*t["charge_a"],t["common_current_a"])/a["charge_efficiency"])
    discharge = min(t["system_envelope_w"],t["minimum_v"]*min(packs*t["discharge_a"],t["common_current_a"])*a["discharge_efficiency"])
    return dict(identity=identity,packs=packs,arrays=arrays,
        sampling_m=float(spacing),sampling_exact=str(spacing),swath_m=float(swath),swath_exact=str(swath),
        channels=family["channels"],bits_per_sample=family["bits_per_sample"],
        working_energy_wh=packs*t["working_pack_wh"],solar_w=arrays*t["array_w"],
        storage_gb=family["published_storage_gbit"]/8*a["storage_fraction"],
        rate_bps=family["reference_rate_mbps"]*1000000*a["net_rate_fraction"],
        power_reference_w=family["reference_power_w"],mode_power_w=family["reference_power_w"]*mode_factor,
        charge_efficiency=a["charge_efficiency"],discharge_efficiency=a["discharge_efficiency"],
        charge_bus_w=charge,discharge_bus_w=discharge,
        partial_mass_kg=float(packs*Fraction(str(t["pack_mass_kg"]))+arrays*Fraction(str(t["array_mass_kg"]))),
        initial_energy_wh=packs*t["working_pack_wh"]*a["initial_energy_fraction"])


def hardware_ledger(m, identity, mode_factor=1.):
    """Consumer-level derived ledger, kept alongside native source references."""
    h=derive_hardware(m,identity,mode_factor)
    specs={
        "sampling_m":("m","DERIVED","payload.optical_acquisition.multispectral_reference_sample_spacing_m; MSGridSizing.spacing_x_m/spacing_y_m","native sampling * 630/native altitude; exact rational in sampling_exact, one binary64 conversion"),
        "swath_m":("m","DERIVED","payload.optical_acquisition.reference_nadir_swath_width_m","native swath * 630/native altitude; no executor altitude scaling"),
        "working_energy_wh":("Wh","DERIVED","eps.battery.nominal_energy_wh","pack count * 86 Wh recommended working range, once"),
        "solar_w":("W","DERIVED","eps.solar_array.nominal_generation_w","array count * 45 W illuminated reference"),
        "storage_gb":("GB","DERIVED","storage.usable_capacity_gb","published decimal Gbit / 8 * ASSUMED available fraction 1"),
        "rate_bps":("bit/s","DERIVED","communications.nominal_downlink_data_rate_bps","published Mbit/s * 1e6 * ASSUMED useful fraction 1"),
        "mode_power_w":("W","ASSUMED","payload.optical_acquisition.acquisition_power_w; DownlinkTransmitterConfig.electrical_power_w","P_ref * factor for each mutually exclusive mode, not a bound"),
        "charge_bus_w":("W","DERIVED","eps.battery.max_charge_input_power_w","min(300,23.6*12,23.6*min(packs*3.4,12)/eta_charge)"),
        "discharge_bus_w":("W","DERIVED","eps.battery.max_discharge_output_power_w","min(300,23.6*min(packs*4,12)*eta_discharge)"),
        "partial_mass_kg":("kg","DERIVED","report only; no inertia or total spacecraft mass","packs*.486 + arrays*.885; detailed table selected over conflicting .750 summary"),
        "initial_energy_wh":("Wh","DERIVED","schema5 initial spacecraft.battery_energy_wh","working_energy_wh * ASSUMED initial fraction .5"),
    }
    return {k:fact(h[k],units,kind,consumer,transform=transform,
                  conditions="Counterfactual study combination; see native source ledger and explicit assumptions")
            for k,(units,kind,consumer,transform) in specs.items()}
