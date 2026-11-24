# Task 05E component, layout and electrical source ledger

This ledger belongs only to the new bounded design trade. It does not reinterpret
the accepted Task 05C/05D inputs. Values marked SOURCE are published reference
values, not proof that the combined spacecraft is electrically or mechanically
qualified. DERIVED values follow the stated equations; ASSUMED values remain
uncertain study inputs. All new assumptions are exported by `design_record` and
must be included in the campaign identity and continuation contract.

## Verified primary references

**TSP -- SOURCE.** [GomSpace DS1038993 revision 3.3, 24 May 2024](https://gomspace.com/wp-content/uploads/2025/09/Datasheet-NanoPower-TSP_45W.pdf),
rechecked 24 September 2026. Page 24: 885 g total, comprising 650 g deployed
array, 30 g HDRM, 165 g cover and 40 g closeout. The page 9 summary instead says
750 g; this study selects the detailed breakdown and preserves that conflict.
Page 7 includes three panels, hinges, internal harnesses and SADA-50. Page 15
excludes connect-PCB-to-EPS wiring. Pages 17-18 expose six separate string
positives with a common ground. Page 22 gives loaded 7s/8s voltages 15.82/18.08 V,
open-circuit 18.20/20.80 V, and 0.49/0.50/0.510 A minimum/typical/maximum
string current; headline voltages on page 8 differ. Drawing page 26 shows
207.1 +/- 0.5 by 327.1 +/- 0.5 mm stowed dimensions and 9.60 +/- 0.50 mm
protrusion. Drawing page 27 distinguishes 908 mm panel span from 930 mm at the
mounting reference; its illustrated two-wing span is 1960 mm on the smaller
reference bus. Consumer: complete-array mass, geometry, independent input
circuits and source-side admissibility. No additional internal hinge/harness
mass or internal diode loss is added.

**BP8 -- SOURCE.** [GomSpace DS1069134 revision 1.2.0, 10 April 2026](https://gomspace.com/wp-content/uploads/2025/08/gs-ds-nanopower-bp8-100-Wh-2.pdf),
rechecked 24 September 2026. Printed page 1 lists 100 Wh nominal and 86 Wh in
the recommended range. Printed page 5, Table 2.2, gives 23.6/28.8/32.0 V
recommended minimum/typical/maximum, 4 A discharge and 3.4 A charge. Printed
page 11, Figure 4.1 and Table 4.1, gives 486 g and 94.8 by 95 by 42 mm.
Printed pages 8 and 10 identify VBAT/GND power and return and show two packs
in parallel with enable-loop wiring. Consumer: capacity, current ceilings,
placement and mass. Parallel pack support is not certification of the assumed
backplane, current sharing, regulator or whole spacecraft.

**P80 -- SOURCE.** [GomSpace product page, Technical insights](https://gomspace.com/product/nanopower-p80/),
rechecked 24 September 2026. Published bounds are 300 W, 12 A PMU, 12 one-amp
MPPT boost channels per ACU, 25 V solar input, and 95 by 95 by 38.8-65 mm /
360.8-619.6 g for three-to-five-module configurations. Configurable regulated
outputs extend to 21.8 V, with separate raw battery outputs. The advertised
efficiency is an upper bound, not a constant. Consumer: plausibility bounds.
The model below is a regulator equivalent, not an asserted P80 ordering option.

**JSS56 -- SOURCE.** [Jena-Optronik datasheet, April 2015, page 2](https://www.jena-optronik.de/products/space-optics-electronics/multi-spectral-imager.html?file=tl_files/pdf/Data+Sheet+JSS+56.pdf),
rechecked 24 September 2026. The imager and electronics together weigh 46 kg;
their dimensions are 641 by 385 by 865 mm and 280 by 253 by 232 mm. The 93 W
entry describes peak simultaneous imaging/downlink. Consumer: minimum common
core size/mass and the retained reference product family. It does not identify
separate mode powers or validate products at changing off-nadir attitudes.

**Actuator plausibility -- SOURCE, not an integrated hardware selection.**
[VECTRONIC VRW02 DS3, page 1](https://www.vectronic-aerospace.com/wp-content/uploads/2020/03/VAS-VRW02-DS3.pdf)
lists 20 mNm maximum torque, 0.2 N m s momentum, 1 kg mass, 70 by 70 by
48 mm dimensions and rotor inertia `3.4e-4 kg m2`; its maximum-torque power
entry is below 25 W. The [current manufacturer's VRW-B-02 page](https://www.vectronic-aerospace.com/reaction-wheels/)
instead lists below 45 W at maximum torque and maximum speed. These are
different stated conditions/versions and must not be silently interchanged.
They show that the assumed common torque/momentum class is physically
plausible; they do not calibrate constant maneuver or holding power. If that
rotor inertia is used, wheel kinetic energy must be included in the work
budget: `K_wheel=H^2/(2*I_rotor)` is about 58.82 J at 0.2 N m s. Body kinetic
energy alone is not the wheel's electrical-work requirement.

The TSP/BP8 mechanical drawings were visually inspected from the accepted 05C
source snapshots as well as checking current primary-source text. Their PDF
SHA-256 values are respectively
`5e3efc331a2fdbc8f04986e33a73dc224ebe5fc9e41ce3ed15de814a048b8abe` and
`84455cefcec0025285cba85c6820ae190837e7e37c71f58f09573e1b1c49b20a`.
The JSS56 snapshot SHA-256 is
`999e32d80622e5e468ffbc19617e09eae859459e94ee4175a0ce52258ccb60fa`.

## Closed layout and mass contract

**ASSUMED:** one 70 kg, 0.8 by 0.8 by 1.0 m core contains the sourced 46 kg
imager/electronics plus 24 kg structure, avionics, common actuator and remaining
common equipment. The core excludes the varied packs, complete arrays,
external adaptors, regulator banks and modeled external harnesses. Its
centroidal inertia starts from a uniform cuboid; an explicit uncertainty scale
changes that centroidal inertia without changing mass or moving hardware.
No sourced flight mass distribution is claimed.

Body y is the single maneuver axis. Complete arrays deploy along +/-x from
x = +/-0.4 m; each has locked body normal +z. Two arrays use y=0; four use
y=+/-0.12 m on each mounting face. Each occupies a 0.208 by 0.330 m stowed
footprint, with 0.011 m allowed protrusion. Neighboring footprints leave
0.032 m between their nominal 0.208 m widths. A 0.930 m root-to-tip allowance
gives a 2.660 m deployed span, below the common 2.8 m limit. Six arrays are
rejected because only two complete assemblies per side are provided. This
declared locked state does not assert that the sourced tracking product lacks
a drive. Deployment, launch loads, flexibility, shadows and collision dynamics
are outside this geometric occupancy screen.

**ASSUMED placement:** each 650 g deployed mass is uniform over a 0.908 by
0.208 by 0.003 m box with 0.022 m root offset. Its other 235 g remains at the
root in a 0.011 by 0.208 by 0.330 m envelope. Another 60 g per assembly is an
external core adaptor, not a second catalog hinge/cover. Each battery adds
20 g external installation support, in addition to the catalog pack. Pack
centers have x=+/-0.08 m, y=-0.28 m, and symmetric z rows spaced 0.10 m;
the 42 mm pack dimension is along y. The eight-pack bay measures 0.28 by
0.05 by 0.41 m. This is a defined geometric bay, not volume available by
subtracting aggregate catalog volumes.

The imager occupies a reserved box centered at (0,0.14,0) m. Its electronics
occupy the stated box rotated to 0.280 by 0.232 by 0.253 m, centered at
(0,-0.22,0.355) m. Battery and regulator bays are disjoint from these reserved
boxes. They screen occupancy; the uniform-core inertia is still an explicitly
separate approximation. External wire mass is spread over the declared
projected route, with connector/service-loop mass included. Main harness mass
is distributed over a central 0.30 by 0.30 by 0.20 m box. Those distributions
are approximations, not resolved cable CAD.

**DERIVED:** component centers determine the total center of mass. Inertia
about y through that center is the sum of each box's
`m*(dx^2+dz^2)/12 + m*((x-x_com)^2+(z-z_com)^2)`, with only the common
core centroidal term scaled for its declared uncertainty. Spare mass is
`78 kg - actual total mass`; unused allowance is not ballast or equal cost.
The enumerated space is packs in {2,4,6,8} and arrays in {2,4,6}. All twelve
records are exported, including every rejected constraint. Before operational
outcomes, select minimum and maximum feasible pack count for each array count.

## Electrical and harness contract

**ASSUMED regulator equivalent:** each bank represents twelve independent
input conditioners and associated distribution equipment, weighs 619.6 g and
occupies 95 by 95 by 65 mm. Required banks equal `ceil(6*arrays/12)`.
The input rating is 35 V; this is an assumed interface, not the P80's published
25 V solar input. The common output is 28 V; it is not claimed to be a P80
regulated option. Total bus limits remain 300 W and 12 A. Solar conversion
efficiency is 0.95. Catalog integration, pin derating, radiation and actual
converter operating curves remain unverified.

Each assembly has three 7s and three 8s circuits, conditioned separately.
**ASSUMED:** 45 W at normal incidence is net at the connect PCB and is divided
in proportion to the detailed loaded voltages. Each circuit therefore carries
`45/[3*(15.82+18.08)] A` at that operating point. The internal IV/diode/wiring
budget is unresolved; the chosen net convention prevents subtracting those
losses again. Body attitude rotates the fixed normals; one common Sun direction
and eclipse flag determine incidence. No independent Sun tracking is supplied.

**ASSUMED external wiring:** each string has positive and return conductors
over a 0.6 m one-way route from its connect PCB to its regulator bank. The
route has two straight segments via `(side*0.34,-0.075,bank_z/2)` m before
reaching `(0,-0.16,bank_z)` m. The first segment stays outside the imager's
x envelope; the second stays below its y envelope. The longest route among
accepted designs is approximately 0.555672 m; the balance is service routing.
This is diagonal routing with an explicit bend, not right-angle Manhattan
routing or a straight line through the reserved imager. Route lengths shorter
than their geometric paths are rejected.
Common ground does not eliminate the copper return. The main regulated
load circuit has a 0.8 m one-way route from `(0,-0.16,0)` through
`(0.25,-0.16,0)` to the common load junction `(0.25,-0.075,0.31)` m, sized
for a common 160 W useful load. This two-segment path is approximately
0.5714 m and clears the reserved imager/electronics boxes; shorter installations
are rejected. Subsystem-internal distribution remains in the common core
definition. The simplified cable mass placement described above does not
purport to resolve the exact service-loop mass distribution.
Battery connection is a plug/backplane inside the regulator-equivalent mass
and existing battery efficiency convention; it is not another explicitly
modeled cable or another loss. No wire is added along the deployed wing,
whose catalog primary/secondary harnesses are already included.

Copper resistivity `1.724e-8 ohm m`, density `8960 kg/m3`, maximum current
density `3 A/mm2`, maximum drop 3%, connector resistance 0.01 ohm and mass
0.002 kg per counted connector are **ASSUMED** engineering references here,
not newly verified material/ampacity specifications. Two series connectors
are counted per loop. Insulation adds 30% of copper mass. Select the smallest
admissible area from {0.08,0.14,0.25,0.5,1,1.5,2.5} mm2. String admission uses
the sourced 0.510 A maximum, not a reduced operating-point current. Invalid
current/drop/power combinations are rejected. Resistivity is an explicit
sensitivity parameter; no temperature model is hidden inside it.

**DERIVED:** `R=rho*(2*one_way_length)/area + connector_count*R_connector`;
copper mass is `density*(2*one_way_length)*area`. For constant source voltage
and load power, the physical low-current solution is
`I=2*P/(V+sqrt(V^2-4*R*P))`. The source supplies `P+I^2*R`; a negative
discriminant or violated installation limit is inadmissible. PV power at the
bus is `(net_source_power-external_PV_I2R)*0.95`. Converter heat and external
PV harness heat are separate exports. Main load harness loss is an executed
load, not a later score adjustment.

**DERIVED battery limits:** capacity is `packs*86 Wh`. Charge API power is
bus input before loss, so its limit is
`min(300,23.6*12,23.6*min(packs*3.4,12)/0.9) W`. Discharge is bus output
after loss, limited to `min(300,23.6*min(packs*4,12)*0.9) W`. The retained
0.9 charge/discharge efficiencies are **ASSUMED**, each applied once; they
do not include the separately modeled PV converter or external load harness.
Using 23.6 V for limits is not a prediction of battery voltage versus SOC.

Thermal capacities, boundary forcing, actuator heat and numerical policy must
remain explicit campaign assumptions. This ledger does not claim a panel
thermal network or hardware-specific thermal validation.

## Parametric cost

No verified quotes were obtained. Each design exports its coefficients in
`C_core + n_B*C_BP8 + n_T*C_TSP + n_reg*C_reg + n_B*C_pack_mount +
n_T*C_array_adapter + m_harness*C_harness_per_kg`. Costs remain named unknowns;
pairwise differences can define break-even ratios. Equal mass ceilings imply
neither equal cost nor an economically optimal design.
