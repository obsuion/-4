# C4 Satellite Operations Simulator TI-64

I wrote this simulator with the assistance of Codex. The idea came from my internship at Kazakhstan Gharysh Sapary, where I worked with satellite imagery and a simplified spacecraft model. I wanted to follow one imaging request from the ground to the spacecraft and back, and see what could stop it along the way.

C4 brings orbit, pointing, power, temperature, imaging and radio communication into one simulation. I used it to compare two spacecraft designs over 90 simulated days each. [Run a short example](examples/README.md) or [see the results](docs/findings.md).

This is version 1. The project is incomplete: the operator can miss a good time to take an image, and the radio model can cut a transmission short. I plan to fix both. I haven't written a full explanation of the code yet because its structure is likely to change substantially in version 2.
