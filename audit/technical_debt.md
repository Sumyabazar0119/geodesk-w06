# Technical Debt: TODO/FIXME to GitLab Issues (US-6.4)

Bhatti et al. (Ch. 4, p. 79) warn that comments rot into "lying comments" once
nobody owns them. Every lingering TODO/FIXME is therefore either fixed or turned
into a GitLab Issue, and the comment keeps only a pointer: `# TODO(#n): …`.

## Inventory

A scan of both repositories (`grep -rnE "TODO|FIXME|XXX|HACK"`, 2026-10-10) found:

- **work05 (OpenAPI repo):** 0 debt comments, so nothing to migrate.
- **work06 (`src/geodesk`):** 3 known limitations of the new contour generator. They were
  found while writing it and recorded as issues straight away, never as bare `# TODO`:

| Limitation | Why it is not fixed this sprint | Comment in code |
|---|---|---|
| Saddle cells always pair NW/SE edges | Needs a test DEM with real ridges | `# TODO(#1): Resolve saddle cells with the cell-centre average …` |
| Whole DEM is held in memory | Block reading belongs to B5.2.2 / rasterio windows | `# TODO(#2): Read the DEM in row blocks (B5.2.2) …` |
| GeoJSON keeps UTM coordinates | Needs `pyproj`, a new dependency | `# TODO(#3): Reproject coordinates to EPSG:4326 as RFC 7946 requires.` |

There was no backlog of untracked comments to clean up. The sprint work was making sure none can appear.

## GitLab Issues

| Issue | Title | Labels | Code location |
|---|---|---|---|
| #1 | Resolve marching-squares saddle cells with the cell-centre average | terrain, FR-09 | `ContourGenerator._cell_segments` |
| #2 | Read large DEMs in row blocks instead of loading them into memory | terrain, performance, NFR-01 | `ContourGenerator._check_dem` |
| #3 | Reproject GeoJSON export to EPSG:4326 | export, FR-12 | `ContourLayer.to_geojson` |

`audit/gitlab_issues.csv` contains the full descriptions with acceptance criteria. Import it in
GitLab via **Issues → Import CSV** on a new project, and the issues get IDs #1–#3 in this order.

## Enforcement

`tests/test_todo_tracking.py` fails the CI pipeline if any `TODO`/`FIXME` in `src/` lacks the
`(#n)` issue reference, so new debt cannot be added silently.
