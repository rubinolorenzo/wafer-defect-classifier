"""Pattern -> process hypotheses, as data the code can use.

Mirrors docs/root_causes.md. These are starting hypotheses for a root-cause
investigation, to be confirmed with tool history and inline metrology.
"""

ROOT_CAUSES = {
    "Center": {
        "hypotheses": "Centre-weighted non-uniformity: spin-coat or deposition thickness, CMP removal rate at the centre, plasma density in etch.",
        "check": "Thickness / CD maps of the same lots; which chamber or polisher processed them.",
    },
    "Donut": {
        "hypotheses": "Mid-radius non-uniformity: CMP pressure zones, gas distribution in deposition or etch, thermal non-uniformity in anneal / RTP.",
        "check": "Radial metrology profiles; recent maintenance on the tool.",
    },
    "Edge-Ring": {
        "hypotheses": "Edge effects: film thickness at the edge, edge bead removal, etch rate at the edge, thermal gradient near the edge.",
        "check": "Edge exclusion settings; edge thickness profiles; edge ring wear in etch chambers.",
    },
    "Edge-Loc": {
        "hypotheses": "Contact or shadowing on one side: clamps, handling contacts, notch alignment, edge chipping.",
        "check": "Position relative to the notch; robot / clamp contact points; repetition across lots.",
    },
    "Loc": {
        "hypotheses": "Local event: particle or contamination, local litho focus issue, local damage.",
        "check": "Defect inspection images at those coordinates; repetition on other wafers.",
    },
    "Scratch": {
        "hypotheses": "Mechanical damage: CMP scratches (slurry agglomerates, pad debris) or wafer handling.",
        "check": "Scratch direction; CMP consumables and slurry filtration; handling steps between inspections.",
    },
    "Random": {
        "hypotheses": "Diffuse contamination or a parametric shift affecting all dies.",
        "check": "Particle counts; parametric test data; whether the whole lot is affected.",
    },
    "Near-full": {
        "hypotheses": "Gross failure: wrong or aborted recipe, skipped step, severe equipment fault, test set-up problem.",
        "check": "Lot history for aborts or reworks; retest on a known-good tester.",
    },
    "none": {
        "hypotheses": "No systematic pattern: baseline random yield loss.",
        "check": "-",
    },
}
