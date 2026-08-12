# Deforestation-baseline fixtures — ground truth

Five plots in `parcels.geojson`, each anchored on a location whose forest / loss
status was **verified against live GEE** in Stage 0 (`probe_datasets.py`) or
Stage 1a (`find_post2020_loss.py`) — not assumed. Coordinates are lon/lat
(GeoJSON order), 6-decimal. Polygons are ~133 m squares (~1.77 ha, smallholder
scale); one plot is a Point + `Area` to exercise the point→buffer path.

Verified encodings (Stage 0 grounding record, `probe_datasets.py`):
- **GFC2020 `Map`** (`JRC/GFC2020/V3`, ~10 m): `1` = forest at the 2020 baseline;
  non-forest is **masked** → the core reads it as `0` via `unmask(0)`.
- **Hansen** (`UMD/hansen/global_forest_change_2025_v1_13`, ~30 m):
  `treecover2000` = canopy % in 2000 (0–100); `lossyear` = `0` none / `N` = year
  2000+N (masked at no-loss → `unmask(0)`).
- **EUDR cutoff** (Reg (EU) 2023/1115, Art. 2): deforestation-free = no loss after
  2020-12-31 → post-cutoff loss = `lossyear >= 21` (2021+).

## The plots

| plot_id | centre (lon, lat) | verified point-truth | source | class | expected determination |
|---|---|---|---|---|---|
| `intact-forest-kakamega` | 34.8650, 0.3500 | tc2000=89, `Map`=1, lossyear=0 | probe | forest at baseline, no loss | **no post-2020 loss → compliant.** Secondary flag: plot is standing 2020 forest (a commodity-on-standing-forest data check, not a deforestation verdict). |
| `deforestation-post2020-mau` | 35.4273, −0.3664 | `Map`=1 AND lossyear=24 (2024), by finder construction | finder | forest at baseline, **cleared 2024** | **post-2020 loss present → DEFORESTATION DETECTED → non-compliant.** The load-bearing case. |
| `savanna-cropland-wau` | 27.9900, 7.7000 | tc2000=1, `Map`=None(0), lossyear=0 | probe | never-forest cropland/savanna | **not forest at baseline, no loss → compliant.** The common legitimate smallholder case (CORWADO theatre). |
| `arid-nonforest-turkana` | 35.9000, 3.5000 | tc2000=0, `Map`=None(0), lossyear=0 | probe | arid non-forest | **not forest at baseline, no loss → compliant.** |
| `deforestation-post2020-mau-point` | 35.4815, −0.5638 | `Map`=1 AND lossyear=23 (2023), by finder construction | finder | post-2020 clearing, **as a Point+Area** | **non-compliant**, and exercises the point→buffer(`Area`)→reduce path. |
| `nonforest-treeloss-wau` | 27.9705, 7.4790 | `Map`=0 (non-forest) AND lossyear=23 (2023), tc=28, by finder construction | finder (`find_nonforest_loss.py`) | **divergence**: non-forest 2020 with post-2020 tree loss (CORWADO theatre) | **COMPLIANT** — all-tree-loss > 0 but forest-loss ≈ 0, so no deforestation of 2020-baseline forest. Proves the Stage-2 intersection stops a cropland tree-removal being mislabelled as EUDR deforestation. |

## Two caveats, resolved when the core runs live (Stage 2)

1. **Point-truth vs. polygon-aggregate.** The probe verified single pixels;
   these plots are ~1.77 ha. The determinations above assume local homogeneity,
   which is safe for the large contiguous cases (Kakamega forest, Turkana desert,
   Wau savanna) and **guaranteed by construction** for the Mau plots (the finder
   only returns pixels that are `forest_2020 AND lossyear>=21`, so any polygon
   containing one has post-2020 loss > 0 → non-compliant regardless of the exact
   fraction). Stage 2 runs the core over these plots and confirms each
   determination against this table before any expected numbers are pinned.

2. **Pre-cutoff clearings are NOT a whole-parcel fixture here.** The obvious
   candidate — the probe's Mau-2007 point (35.55, −0.55, lossyear=7) — sits
   *inside* the frontier box where the finder found 4,889 post-2020-loss pixels,
   so a polygon there would likely include post-cutoff loss and misrepresent the
   "old clearing → compliant" case. That case is really the `lossyear >= 21`
   **boundary**, covered by a Stage 2 unit test on the classifier
   (`lossyear=7 → not counted`, `lossyear=24 → counted`) using the probe's
   already-verified Mau-2007 reading — no invented parcel needed.
