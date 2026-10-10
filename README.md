# GeoDesk GIS — Code Documentation & AI Audit (Sprint 06)

Software Project Documentation, Week 06. Гүйцэтгэсэн: С.Сумъяабазар (21B1NUM0119)

GeoDesk-ийн Geo Processing Engine-ийн **B5.2 Contour Generator** (FR-09, W05 API `POST /terrain/contours`)
модулийг Google-style docstring-оор баримтжуулж, Sphinx-ээр API reference үүсгэн GitLab Pages-д нийтэлнэ.

| Deliverable (UE-6) | File |
|---|---|
| (a) Manual docstrings | `audit/manual_docstring.py` |
| (b) AI docstrings + Bhatti audit | `audit/ai_docstring.py`, `audit/ai_runs/`, `audit/bhatti_audit_table.md` |
| Diff manual vs AI | `audit/manual_vs_ai.diff` (`python audit/make_docstring_diff.py`) |
| Use-Verify-Cite log | `audit/use_verify_cite_log.md` |
| (c) Merged docstrings + Sphinx | `src/geodesk/`, `docs/source/` |
| (d) Hallucination test (bonus) | `tests/test_ai_hallucinations.py` |
| TODO → GitLab Issues | `audit/technical_debt.md`, `audit/gitlab_issues.csv` |

## Run locally

```sh
pip install -r requirements.txt
python -m pytest -v                                          # unit + doctest + coverage + hallucination + TODO tests
sphinx-build -W --keep-going -b html docs/source public      # zero-warning HTML build
python -m http.server -d public 8000                         # http://localhost:8000
```

## GitLab setup (one time)

1. Create an empty GitLab project, e.g. `geodesk-docs`, then push this repo:
   `git remote add origin https://gitlab.com/<user>/geodesk-docs.git && git push -u origin main`
2. **Issues → Import CSV** → `audit/gitlab_issues.csv` (creates #1–#3, referenced by the `TODO(#n)` comments).
3. The `pages` job publishes to `https://<user>.gitlab.io/geodesk-docs/`.
   For a public URL, set **Settings → General → Visibility → Pages: Everyone**.
