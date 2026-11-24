# KazEOSat-1 public specification reference

This file separates public KazEOSat-1 plaque/spec values from implemented
simulator parameters and future-only metadata. Public values provide transparent
reference points; they do not validate this simulator as real KazEOSat-1
operations, official software, or a physical digital twin.

| Public value | Value | Current simulator use | Future use / limitation |
|---|---:|---|---|
| Size | 2.10 m x 3.70 m | Metadata only | May inform future geometry, drag, thermal, or fuel documentation; no physical dynamics currently use it. |
| Power | 1200 W | Configuration reference metadata for V3.6A | Sanity-check reference only; it does not calibrate proxy generation, loads, SOC, or a real power balance. |
| Data transmission rate | 270 Mbit/s in X-band | V3 used a rounded 2.0 GB/min payload-downlink proxy; V5.5 uses the source-backed nominal rate in pure contact-capacity arithmetic | Not a radio link budget, recorder-write rate, measured operational delivery rate, or housekeeping/command packet rate; it does not calibrate V3.8 packet KB sizes or delivery stress. |
| Orbit | Sun-synchronous orbit | Motivates the simplified reference orbit | No TLE/SGP4, perturbation, or orbit-determination implementation. |
| Altitude | H = 750 km | Implemented as the reference circular-orbit altitude | Public/spec-inspired proxy, not operational ephemeris. |
| Inclination | 98.5 degrees | Implemented as the reference inclination | Public/spec-inspired proxy, not a propagated orbital element. |
| Satellite transmission modulation | QPSK | Metadata only | V3.8A/V3.8B do not simulate modulation, packet protocols, or a physical command link. V3.8B delivery is only a synthetic deterministic stress proxy, not real link reliability. |
| Mass | 820 kg | Metadata only | May inform future dynamics/fuel documentation; not currently used in physical dynamics. |
| Spatial resolution | 1 m | V3.7A reference metadata only | Not used to calculate payload data or observation quality. |
| Imagery mode | Panchromatic, multispectral | Labels deterministic V3.7A synthetic scenes | Not a real instrument-mode or spectral scheduling model. |
| Scene size | 20 km x 20 km | Sets the default synthetic V3.7A scene-area reference | Not real observation geometry or calibrated payload output. |
| Revisit rate | From 3 to 5 days | V3.7A reference metadata only | Does not set the synthetic opportunity period or predict coverage. |
| Productivity | 220,000 km^2/day | V3.7A reference metadata only | Does not force or calibrate simulated daily area. |

V3.7B's deterministic pointing-quality, off-nadir, and slew proxy assumptions
are not calibrated from any of these public values and do not implement real
observation geometry or ADCS performance.

V3.8A housekeeping, command, and daily-plan packet sizes are transparent
KB-scale diagnostic assumptions. They are not calibrated from the public
270 Mbit/s X-band payload rate or QPSK metadata.
V3.8B's packet drop fraction and deterministic delivery draws are likewise
synthetic stress assumptions, not measured or estimated KazEOSat-1 link
reliability, BER, FER, RF propagation, or network performance.

## Implemented directly or approximately

- Altitude is implemented directly as a 750 km circular-orbit proxy.
- Inclination is implemented as the 98.5 degree public reference.
- Historical V3 uses 2.0 GB/min as a rounded payload-downlink proxy. V5.5
  Level-1 instead retains the source-backed nominal X-band link rate and
  derives capacity directly from duration: `270_000_000 × 60 =
  16_200_000_000 bits = 2.025 decimal GB`. The 2.025 GB result is exact
  rate-times-duration evidence for a 60-second externally supplied serviceable
  contact. This arithmetic was historically summarized as 2.025 GB/min, but
  V5.5 does not treat it as measured operational delivered throughput or a
  recorder write rate.

## Recorded as metadata / future work

The 1200 W power value is retained by V3.6A as reference metadata only; its
separate proxy generation and load assumptions are not calibrated from that
value. The 820 kg mass and
2.10 m x 3.70 m size may support future geometry, drag, thermal, or fuel
documentation. QPSK remains metadata only; V3.8A/V3.8B do not implement
modulation or a real radio/packet protocol. V3.7A uses
panchromatic/multispectral labels and the 20 x 20 km scene area only in its
deterministic synthetic scene proxy. The 1 m resolution, 3 to 5 day revisit,
and 220,000 km^2/day productivity remain metadata for later validation or
sanity-check work and do not calibrate the proxy.

Recording these public values does not claim that the current model reproduces
real KazEOSat-1 performance or operations.
