# Vision

Take a real parcel of land -- ideally one that is actually for sale -- and find out what could fit
on it: houses, a shared courtyard, driveways, views. Do it with real boundaries and real terrain,
in 3D, and keep it playful.

This is a hobby and speculative-design sandbox. It is not professional architecture, civil
engineering, surveying, or permit work, and it does not produce construction documents.

## The idea in one line

Browse land listings, find a compelling property, and turn it into a convincing, explorable
"dream compound" with as little custom software as reasonably possible.

## What it borrows from

| Inspiration | What it contributes |
| --- | --- |
| The Sims | Fast, intuitive house and interior layout |
| Parametric CAD | Real dimensions, configurable geometry |
| GIS | Real parcels, terrain, and geographic constraints |
| A game engine | Walking around the result at human scale |

## Two motivating examples

**A. A small lot (about 3 acres), several households.** An irregular parcel with three private
residences around a shared courtyard. Each household gets its own entrance and reasonable visual
and acoustic separation, with easy access to shared outdoor space. Configurations to compare:

- Three detached houses around a common courtyard.
- One U-shaped building with three independent wings.
- A cluster of smaller buildings joined by gardens or paths.
- One larger multifamily building with distinct private and shared areas.

**B. A large rural parcel (about 150 acres).** Wooded, hilly, a creek, limited road access. The
question becomes *where* to build. Things to compare between candidate sites:

- Views and visibility.
- Distance to the creek, subject to flood and environmental constraints.
- Slope and construction difficulty.
- Solar orientation.
- Road access and driveway length.
- Privacy and separation between structures.
- Room for shared amenities and outdoor recreation.

The workflow should scale from the first case to the second without changing tools.

## Design principles

1. **Reuse existing software first.** Established tools, add-ons, and repositories beat bespoke
   code. No custom floor-plan editor, CAD app, GIS renderer, or procedural generator unless a real
   gap remains after evaluating what exists.
2. **Real-world scale.** Meters everywhere, consistent units, no rescaling.
3. **Interactive creativity.** It should feel like a sandbox, not a documentation process.
4. **Don't overengineer.** No construction drawings, exhaustive BIM metadata, or
   engineering-grade grading calculations.
5. **Keep editable sources.** A render or exported mesh is never the only copy of a design.
6. **Allow iteration.** Moving a house, resizing a courtyard, or switching parcels should not mean
   rebuilding everything.
7. **Be honest about data quality.** Say when data are approximate, generalized, or unverified.
8. **Feasibility is not legality.** Setbacks, zoning, lot coverage, multifamily occupancy,
   septic, water rights, floodplains, and road access all need jurisdiction-specific checks.
   A creek can be the most attractive spot on a lot and also unbuildable.
9. **Keep costs low.** Free and open-source tools and public data wherever possible.
10. **Prioritize visual progress.** A working 3D prototype beats an elaborate architecture that
    displays nothing.

## Non-goals (for now)

- Automatic generation of dozens of layouts.
- AI floor-plan generators.
- A custom application or automation framework.
- Construction-ready plans or permit determinations.
