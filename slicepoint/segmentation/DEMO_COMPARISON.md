# Built-in PNG comparison demonstration

The hosted Base44 comparison demo has separate in-app pickers for a synthetic
`demo-ct.png` and `demo-vendor-segmentation.png`. Comparing the built-in pair shows
an illustrative overlay and a fixed Dice of **0.94 (94%)**, labelled **High
agreement (demo)**. A visible banner states: **Demo only — preset score; no model
was run.** Changing a selection clears the result; compare stays disabled until
both images are selected. This demo does not upload patient data or call an API.

This document records the demo contract. The integration component in this
package demonstrates the optional real NIfTI API workflow, not the hosted PNG
demo source. The segmentation package itself calculates real volumetric scores.
