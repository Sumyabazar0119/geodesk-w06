# Use-Verify-Cite Log: AI hallucination detection (US-6.3)

**Use:** what the AI was asked and what it returned (stored verbatim).
**Verify:** how each claim was checked against the code.
**Cite:** the source of truth for the verdict.

All runs used a fresh model context with no tools, so the model could not read or run the repository. Date: 2026-10-10.

## Runs

| Run | Model | Prompt (summary) | Output file |
|---|---|---|---|
| 1 | Claude Sonnet | "Add complete Google-style docstrings to every public class, method and property … description, Args, Returns, Raises, Example … and a See Also line." Input: `audit/undocumented_terrain.py` | `audit/ai_docstring.py` |
| 2 | Claude Sonnet | "Write the Quickstart section … (1) load a DEM from a GeoTIFF file on disk, (2) generate 1 m contour lines, (3) save the contours to a GeoJSON file. Also add an Error handling example." Input: public signatures only | `audit/ai_runs/run2_sonnet_quickstart.py` |
| 3 | Claude Haiku | Same prompt as run 2 | `audit/ai_runs/run3_haiku_quickstart.py` |

Runs 2 and 3 used a task-oriented prompt on purpose. When a model has to load a GeoTIFF with a library that has no such method, it is tempted to invent one (e.g. `ElevationGrid.from_geotiff`).

## Ghost API scan (reflection)

`tests/test_ai_hallucinations.py` parses every doctest, fenced block, indented `Example:` block and Sphinx role. It then resolves each imported name, attribute, method, return type and keyword argument against the real classes with `importlib` and `inspect`.

| Run | Code snippets parsed | Sphinx roles | GeoDesk names checked | **Invented APIs found** |
|---|---|---|---|---|
| 1 | 19 | 36 | `from_rows`, `shape`, `size_mb`, `nodata_ratio`, `valid_range`, `length_m`, `elevations`, `to_geojson`, `levels`, `generate`, `interval_m`, `source_layer_id`, `MIN_INTERVAL_M`, `geodesk.errors` | **0** |
| 2 | 2 | 0 | `ElevationGrid.from_rows` (+ 5 keywords), `ContourGenerator(interval_m, max_size_mb)`, `generate(output_layer_id)`, `to_geojson`, `size_mb`, `nodata_ratio`, 3 error classes | **0** |
| 3 | 2 | 0 | same as run 2 | **0** |

**Result: none of the 3 runs invented a GeoDesk class, method or parameter.** Runs 2 and 3 both said the module cannot read GeoTIFF files itself, and both used `rasterio` instead of a fake `from_geotiff`. Their `rasterio` calls (`open`, `read(1)`, `transform.a/.c/.e/.f`, `crs.to_string()`, `nodata`) are real rasterio 1.5 API and ran in our test.

A green scan only means something if the scanner can fail. It is proven by three self-tests with planted ghosts: `ElevationGrid.from_geotiff`, `ContourGenerator(smooth=...)` and `ContourLayer.save`, all reported. A fourth test guards against vacuous passes by asserting that each AI file actually produced code to check.

## Hallucinations found: invented behaviour, not invented symbols

| ID | Run | Claim (Use) | Verification (Verify) | Source of truth (Cite) | Verdict |
|---|---|---|---|---|---|
| H1 | 1 | "The `origin` is the north-west corner of the grid" | `_cell_segments` places `elevations[0][0]` exactly at `origin`, so `origin` is a sample point (cell centre), not the raster's outer edge. | `src/geodesk/terrain.py` `_cell_segments`: `x0 = grid.origin[0] + column * grid.cell_size_m` | **Hallucinated contract** |
| H2 | 2, 3 | `origin=(transform.c, transform.f)  # raster's upper-left corner` | Wrote the Zaisan DEM to a real GeoTIFF and ran the AI recipe: the first vertex moved by (−15.0 m, +15.0 m), half a 30 m cell. | rasterio docs: `transform.c/.f` are the outer corner of pixel (0, 0); `tests/test_geotiff_quickstart.py` | **Hallucination with a measurable 15 m error** |
| H3 | 1 | `size_mb`: "Estimated in-memory size of the grid" | The formula is rows × cols × `_BYTES_PER_CELL` (4 bytes = float32 on disk). A Python float alone is 24 bytes. | `src/geodesk/terrain.py` `size_mb`; `sys.getsizeof(1.0) == 24` | **Wrong meaning** |
| H4 | 1 | `ContourLine`: "single contour polyline", "Ordered vertices" | `generate()` creates one `ContourLine` per 2-point cell segment; vertex order follows dict insertion of edges. | `ContourGenerator.generate`, `_cell_segments` | **Overstated guarantee** |

H1 and H2 are the "ghost API" of this sprint: an API **contract** that the code never had. The model even flagged it ("Check that `origin` matches the corner convention…", "Verify both before publishing"), but a user copying the snippet would still get contours 21 m off diagonally. The fix (C1 in the [Bhatti audit](bhatti_audit_table.md)) is documented and tested.

## Note for the lab criterion "at least one invented API"

We did not get an invented symbol, and we did not plant one in the AI output to satisfy the criterion. What the audit found instead is a hallucinated contract (H1/H2), proven with a reproducible 15 m error. The reflection test is in CI, so a future AI-written docstring that invents a symbol fails the pipeline.
