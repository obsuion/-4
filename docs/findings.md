# Two spacecraft, the same 90-day imaging task

D1 delivered 36 modeled products and D2 delivered 35. The shared 35 were the **same requests**, delivered at the same model times. The difference is one identifiable event, not a statistical claim that one spacecraft is generally better. Both runs covered model clock 128 through 7,776,128 seconds.

## What counted as a delivery?

Every 900 seconds the scenario released a request to image the **same** site (25° N, 0° E). The four-second exposure had to fit in the first 180 seconds after release. The planned downlink slot was +240 to +360 seconds; delivery was due by +600 seconds. The ground station was at the same latitude and longitude as the target. A credit records timely delivery of the modeled multispectral data product, not a real scene or a calibrated image. All credited products were 12,288 bits.

| Last recorded outcome for a unique request | D1 Balanced | D2 Light |
| --- | ---: | ---: |
| Target below visibility threshold at pointing attempt | 8,027 | 7,898 |
| Requested camera angle exceeded the 45° limit | 372 | 359 |
| No action linked to request; solar operations occupied its acquisition window | 198 | 341 |
| Target not visible at a sample during acquisition | 5 | 5 |
| Acquisition completed but delivery did not | 2 | 2 |
| Credited delivery | 36 | 35 |
| **All requests** | **8,640** | **8,640** |

The first row records an attempted command, not necessarily a lost imaging opportunity. An independent one-second geometry screen found only 538 windows with any target visibility, 86 with a geometrically eligible start for a four-second exposure, and 85 with enough station visibility as well. The 85 do not account for spacecraft pointing, settling, power, command latency, or competing activities. They are diagnostic candidates, not promised deliveries. Individual expiry timestamps were not emitted for every request; recorded expiry totals were 8,604 and 8,605.

## Follow a request through the system

| Request | Observation | What to test next |
| --- | --- | --- |
| 6970 | D1 attempted to point immediately. In an independent check, the spacecraft was below the target's horizon at all 181 integer-second samples. | Suppress a needless command; expect no additional credit. |
| 7622 | D1's capture attempt at +7 s was refused at 68.25° off nadir. From +90 through +167 s the target was visible and the angle was within 45° at each sampled second. | Try scheduling a later exposure with the actual slew, settling, power and downlink constraints. The audit did not execute that alternate plan. |
| 6394 | The only D1-only credit. D1 finished the downlink at +252.288 s. D2 held solar orientation throughout the first 180 s. | Test whether the power policy could safely defer solar hold for this request. |
| 7996 | Both designs delivered 10,000 of 12,288 bits. At 1,000 bit/s the rest required 2.288 s. A check on D1's trajectory found the station visible that long, but below the horizon by the end of the next 4 s integration interval. The radio rejected the whole interval. | Test duration handling at loss of contact using the same checkpoint and different step partitions. No retroactive credit is counted. |

Of the 85 geometry candidates, 48 on D1 and 47 on D2 ended in a camera-angle refusal. These are more informative planning tests than retrying all eight thousand pointing refusals.

## Power and temperature

| Quantity | D1 Balanced | D2 Light |
| --- | ---: | ---: |
| Nominal battery capacity / solar panel power | 100 Wh / 50 W | 50 Wh / 25 W |
| Initial / final battery energy | 80.00 / 98.33 Wh | 40.00 / 43.93 Wh |
| Time holding solar orientation | 53.19 h | 87.80 h |
| Positive charging time during that hold | 37.19 h | 56.24 h |
| Model power service interruptions | 0 | 0 |

D2 was warmer at all 70 matched, non-initial day-end measurements for each of three nodes. Median D2-minus-D1 differences were **+15.21 °C** at the battery, **+7.70 °C** at the spacecraft bus, and **+5.27 °C** at the payload. These are modeled node temperatures at matched instants, not an average over the whole flight. The designs differ in multiple electrical, mechanical and thermal inputs; the comparison does not isolate the effect of battery capacity alone.

[Data dictionary and verification commands](../results/README.md)
