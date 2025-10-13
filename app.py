from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import io
import pandas as pd
import requests

app = Flask(__name__)
app.secret_key = "replace-me"

CROSSREF_API_URL = "https://api.crossref.org/works"
LATEST_RESULTS_KEY = "latest_results"

# Simple in-memory cache for the latest search results per sessionless app process.
_latest_results_df: pd.DataFrame | None = None
_latest_query: str | None = None


def fetch_crossref_results(keyword: str, rows: int) -> pd.DataFrame:
    """Fetch search results from Crossref and return a DataFrame."""
    params = {
        "query": keyword,
        "filter": "from-pub-date:2015",
        "rows": rows,
    }
    response = requests.get(CROSSREF_API_URL, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()
    items = data.get("message", {}).get("items", [])

    records = []
    for item in items:
        title_list = item.get("title") or []
        title = title_list[0] if title_list else "Untitled"
        doi = item.get("DOI", "")
        published = item.get("published-print") or item.get("published-online") or {}
        date_parts = published.get("date-parts") or [[]]
        year = date_parts[0][0] if date_parts and date_parts[0] else "—"

        authors = item.get("author", [])
        author_names = []
        for author in authors:
            given = author.get("given", "").strip()
            family = author.get("family", "").strip()
            full_name = " ".join(part for part in [given, family] if part)
            if full_name:
                author_names.append(full_name)
        author_str = "; ".join(author_names) if author_names else "Unknown"

        records.append({
            "Title": title,
            "DOI": doi,
            "Year": year,
            "Authors": author_str,
        })

    return pd.DataFrame.from_records(records)


@app.route("/", methods=["GET", "POST"])
def index():
    global _latest_results_df, _latest_query

    results_df = None
    keyword = ""
    rows = 10

    if request.method == "POST":
        keyword = (request.form.get("keyword") or "").strip()
        rows_raw = request.form.get("rows") or "10"
        try:
            rows = max(1, min(100, int(rows_raw)))
        except ValueError:
            rows = 10

        if not keyword:
            flash("Please enter a research topic keyword.")
            return redirect(url_for("index"))

        try:
            results_df = fetch_crossref_results(keyword, rows)
        except requests.HTTPError as exc:
            flash(f"Crossref API error: {exc.response.status_code}")
            return redirect(url_for("index"))
        except requests.RequestException:
            flash("Unable to reach Crossref API. Please try again later.")
            return redirect(url_for("index"))

        if results_df.empty:
            flash("No results found for that query after 2015.")
        else:
            _latest_results_df = results_df
            _latest_query = keyword

    return render_template(
        "index.html",
        results=results_df if results_df is not None else _latest_results_df,
        keyword=keyword or (_latest_query or ""),
        rows=rows,
    )


@app.route("/download")
def download_csv():
    if _latest_results_df is None or _latest_results_df.empty:
        flash("No search results to download yet.")
        return redirect(url_for("index"))

    csv_buffer = io.StringIO()
    _latest_results_df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)

    return send_file(
        io.BytesIO(csv_buffer.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="crossref_results.csv",
    )


if __name__ == "__main__":
    app.run(debug=True)
