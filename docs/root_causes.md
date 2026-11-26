# From defect pattern to process hypothesis

A classifier gives a label; a fab needs to know which step to look at. The table below maps each WM-811K pattern to the process causes most often proposed for it. These are **starting hypotheses for root-cause analysis**: a real investigation confirms them against the tool history, lot genealogy and inline metrology of the affected wafers.

| Pattern | What it looks like | Typical hypotheses | What to check first |
|---|---|---|---|
| **Center** | Failing dies clustered around the wafer centre | Radial non-uniformity of a process that is centre-weighted: film thickness from spin coating or deposition, CMP removal rate in the centre, plasma density in etch | Thickness / CD maps of the same lots; which chamber or polisher processed them |
| **Donut** | Ring of failures at mid-radius | Mid-radius non-uniformity, e.g. CMP pad or carrier pressure zones, gas distribution in deposition or etch, thermal non-uniformity in annealing / RTP | Radial profiles from metrology; recent maintenance on the relevant tool |
| **Edge-Ring** | Continuous ring of failures at the edge | Edge effects common to many steps: thinner or thicker films at the edge, edge bead removal, etch rate at the edge, temperature gradient near the edge | Edge exclusion settings; edge thickness profiles; edge ring wear in etch chambers |
| **Edge-Loc** | Failures in one sector of the edge | Something that touches or shadows one side of the wafer: clamps, handling contacts, wafer notch alignment, local edge chipping | Orientation relative to the notch; robot / clamp contact points; whether position repeats across lots |
| **Loc** | Compact cluster away from the edge | Local defect: particle or contamination event, local lithography focus problem, localised damage | Defect inspection images for those coordinates; same location repeating on several wafers? |
| **Scratch** | Thin line or arc of failures | Mechanical damage: CMP scratches from slurry agglomerates or pad debris, handling by robots or tweezers | Scratch direction; CMP consumables and slurry filtration; handling steps between inspections |
| **Random** | Failures spread across the wafer | Diffuse contamination or a parametric shift affecting all dies, e.g. particles, a slightly off-target recipe, a marginal design / test limit | Particle counts; parametric test data; whether the whole lot is affected |
| **Near-full** | Almost every die fails | Gross failure: wrong or aborted recipe, a skipped step, severe equipment fault, test set-up problem | Lot history for aborts or reworks; retest on a known-good tester |
| **none** | No systematic pattern | Only the baseline random yield loss | - |

## Why this matters for the model

* **Rotation does not change the class, position along the radius does.** That is why training uses 90° rotations and flips as augmentation, but never scaling or translation.
* **Edge-Loc and Loc are the classes most often confused** in published results. The physical difference (contact at the edge vs. a local event inside the wafer) is useful when deciding which error matters more.
* **Grad-CAM is a sanity check, not decoration.** If the model calls a wafer "Edge-Ring" while the heat map lights up the centre, the prediction should not be trusted, whatever the accuracy figure.
