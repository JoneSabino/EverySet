"""Generate HTML benchmark dashboard from results."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path


def _make_heatmap(results: list[dict]) -> str:
    """Returns base64-encoded PNG of accuracy heatmap."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        profiles = sorted({r.get("profile", "?") for r in results if "error" not in r})
        docs = sorted({r.get("document", "?") for r in results if "error" not in r})

        matrix = np.zeros((len(profiles), len(docs)))
        for r in results:
            if "error" in r:
                continue
            pi = profiles.index(r.get("profile", "?"))
            di = docs.index(r.get("document", "?"))
            matrix[pi, di] = r.get("row_recall", 0.0)

        fig, ax = plt.subplots(figsize=(max(6, len(docs) * 1.5), max(4, len(profiles) * 1.2)))
        im = ax.imshow(matrix, vmin=0, vmax=1, cmap="RdYlGn", aspect="auto")
        ax.set_xticks(range(len(docs)))
        ax.set_xticklabels([d[:20] for d in docs], rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(len(profiles)))
        ax.set_yticklabels(profiles, fontsize=9)
        ax.set_title("Row Recall by Profile × Document")
        plt.colorbar(im, ax=ax, label="Recall")
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100)
        plt.close()
        return base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        return ""


def generate_report(results: list[dict], output_path: str) -> None:
    heatmap_b64 = _make_heatmap(results)

    profile_summary: dict[str, dict] = {}
    for r in results:
        if "error" in r:
            continue
        p = r.get("profile", "?")
        if p not in profile_summary:
            profile_summary[p] = {"recall_sum": 0.0, "count": 0, "rows": 0, "elapsed": 0.0}
        profile_summary[p]["recall_sum"] += r.get("row_recall", 0.0)
        profile_summary[p]["count"] += 1
        profile_summary[p]["rows"] += r.get("rows_extracted", 0)
        profile_summary[p]["elapsed"] += r.get("elapsed_s", 0.0)

    summary_rows = ""
    for p, s in sorted(profile_summary.items()):
        avg_recall = s["recall_sum"] / s["count"] if s["count"] else 0.0
        summary_rows += f"""
        <tr>
          <td>{p}</td>
          <td>{avg_recall:.1%}</td>
          <td>{s['rows']}</td>
          <td>{s['elapsed']:.1f}s</td>
        </tr>"""

    heatmap_html = (
        f'<img src="data:image/png;base64,{heatmap_b64}" style="max-width:100%"/>'
        if heatmap_b64 else "<p>(matplotlib not available for heatmap)</p>"
    )

    results_json = json.dumps(results, indent=2)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Skins Extractor — Benchmark Dashboard</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #222; }}
  h1 {{ color: #1a1a2e; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #f0f0f0; }}
  tr:hover {{ background: #f9f9f9; }}
  pre {{ background: #f5f5f5; padding: 1rem; overflow-x: auto; font-size: 12px; }}
  .section {{ margin: 2rem 0; }}
</style>
</head>
<body>
<h1>Skins Extractor — Benchmark Dashboard</h1>

<div class="section">
  <h2>Profile Summary</h2>
  <table>
    <thead><tr><th>Profile</th><th>Avg Recall</th><th>Rows Extracted</th><th>Total Time</th></tr></thead>
    <tbody>{summary_rows}</tbody>
  </table>
</div>

<div class="section">
  <h2>Accuracy Heatmap (Row Recall)</h2>
  {heatmap_html}
</div>

<div class="section">
  <h2>Raw Results</h2>
  <pre>{results_json}</pre>
</div>
</body>
</html>"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
