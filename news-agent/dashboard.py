#!/usr/bin/env python3
"""
Web Dashboard — FastAPI app for browsing news articles, analytics, and clusters.
Run: python dashboard.py
"""

import json
from datetime import datetime
from html import unescape
from urllib.parse import quote

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse

import config
import database

app = FastAPI(title="News Intelligence Dashboard")


# ── Helpers ──────────────────────────────────────────────────────────────────

TAG_COLORS = {
    "ai": "#7c3aed", "finance": "#059669", "startups": "#d97706",
    "geopolitics": "#dc2626", "tech": "#2563eb", "security": "#be123c",
    "science": "#0891b2", "india": "#ea580c", "crypto": "#7c3aed",
    "health": "#16a34a", "climate": "#15803d", "legal": "#4338ca",
    "general": "#64748b",
}

TAG_EMOJI = {
    "ai": "&#129302;", "finance": "&#128176;", "startups": "&#128640;",
    "geopolitics": "&#127758;", "tech": "&#128187;", "security": "&#128274;",
    "science": "&#128300;", "india": "&#127470;&#127475;", "crypto": "&#8383;",
    "health": "&#127973;", "climate": "&#127793;", "legal": "&#9878;&#65039;",
    "general": "&#128240;",
}


def _priority_class(p: int) -> str:
    if p >= 70:
        return "high"
    if p >= 50:
        return "medium"
    return "low"


def _priority_label(p: int) -> str:
    if p >= 70:
        return "CRITICAL"
    if p >= 50:
        return "IMPORTANT"
    return "NOTABLE"


# ── HTML Template ────────────────────────────────────────────────────────────

def _render_page(title: str, content: str, active: str = "home") -> HTMLResponse:
    nav_items = [
        ("briefing", "/briefing", "&#9889; Briefing"),
        ("home", "/", "&#128225; Feed"),
        ("analytics", "/analytics", "&#128202; Analytics"),
        ("clusters", "/clusters", "&#128279; Clusters"),
        ("sources", "/sources", "&#128218; Sources"),
    ]
    nav_html = ""
    for key, href, label in nav_items:
        cls = "active" if key == active else ""
        nav_html += f'<a href="{href}" class="nav-link {cls}">{label}</a>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — News Intelligence</title>
<style>
:root {{
  --bg: #0f172a;
  --surface: #1e293b;
  --surface2: #334155;
  --text: #f1f5f9;
  --text2: #94a3b8;
  --text3: #64748b;
  --accent: #3b82f6;
  --red: #ef4444;
  --amber: #f59e0b;
  --green: #22c55e;
  --border: #334155;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; line-height:1.6; }}
a {{ color:var(--accent); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}

/* Nav */
.topbar {{ background:var(--surface); border-bottom:1px solid var(--border); padding:0 24px; position:sticky; top:0; z-index:100; display:flex; align-items:center; gap:8px; }}
.topbar .logo {{ font-size:18px; font-weight:800; color:var(--text); padding:14px 16px 14px 0; border-right:1px solid var(--border); margin-right:8px; }}
.nav-link {{ padding:14px 16px; color:var(--text2); font-size:13px; font-weight:600; letter-spacing:0.3px; transition:color 0.2s; }}
.nav-link:hover {{ color:var(--text); text-decoration:none; }}
.nav-link.active {{ color:var(--accent); border-bottom:2px solid var(--accent); }}

/* Layout */
.container {{ max-width:1100px; margin:0 auto; padding:24px 20px; }}
.grid {{ display:grid; gap:16px; }}
.grid-2 {{ grid-template-columns:1fr 1fr; }}
.grid-3 {{ grid-template-columns:1fr 1fr 1fr; }}
.grid-4 {{ grid-template-columns:1fr 1fr 1fr 1fr; }}
@media(max-width:768px) {{ .grid-2,.grid-3,.grid-4 {{ grid-template-columns:1fr; }} }}

/* Cards */
.card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:20px; }}
.card h2 {{ font-size:14px; color:var(--text2); font-weight:700; text-transform:uppercase; letter-spacing:1px; margin-bottom:16px; }}
.stat-card {{ text-align:center; }}
.stat-card .value {{ font-size:36px; font-weight:800; }}
.stat-card .label {{ font-size:12px; color:var(--text3); text-transform:uppercase; letter-spacing:1px; margin-top:4px; }}
.stat-card.high .value {{ color:var(--red); }}
.stat-card.medium .value {{ color:var(--amber); }}
.stat-card.low .value {{ color:var(--green); }}
.stat-card.total .value {{ color:var(--accent); }}

/* Article cards */
.article {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:18px 20px; margin-bottom:12px; transition:border-color 0.2s; }}
.article:hover {{ border-color:var(--accent); }}
.article.high {{ border-left:4px solid var(--red); }}
.article.medium {{ border-left:4px solid var(--amber); }}
.article.low {{ border-left:4px solid var(--green); }}
.article-meta {{ display:flex; align-items:center; gap:8px; margin-bottom:8px; flex-wrap:wrap; }}
.badge {{ padding:2px 10px; border-radius:6px; font-size:11px; font-weight:700; letter-spacing:0.5px; }}
.badge.high {{ background:#ef444422; color:var(--red); }}
.badge.medium {{ background:#f59e0b22; color:var(--amber); }}
.badge.low {{ background:#22c55e22; color:var(--green); }}
.article-title {{ font-size:15px; font-weight:700; color:var(--text); line-height:1.4; margin-bottom:6px; }}
.article-title a {{ color:var(--text); }}
.article-title a:hover {{ color:var(--accent); }}
.article-summary {{ font-size:13px; color:var(--text2); margin-bottom:10px; }}
.article-source {{ font-size:12px; color:var(--text3); }}
.tag-pill {{ display:inline-block; padding:2px 8px; border-radius:20px; font-size:11px; font-weight:600; margin-right:4px; margin-top:4px; }}
.article-actions {{ margin-top:10px; display:flex; gap:6px; flex-wrap:wrap; }}
.btn {{ display:inline-block; padding:6px 14px; border-radius:8px; font-size:11px; font-weight:700; text-decoration:none; letter-spacing:0.3px; }}
.btn-primary {{ background:var(--accent); color:white; }}
.btn-google {{ background:#1a73e8; color:white; }}
.btn-x {{ background:#000; color:white; border:1px solid var(--border); }}

/* Search */
.search-bar {{ margin-bottom:20px; }}
.search-bar form {{ display:flex; gap:8px; }}
.search-bar input {{ flex:1; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:10px 16px; color:var(--text); font-size:14px; outline:none; }}
.search-bar input:focus {{ border-color:var(--accent); }}
.search-bar button {{ background:var(--accent); color:white; border:none; border-radius:8px; padding:10px 20px; font-size:14px; font-weight:600; cursor:pointer; }}
.search-bar button:hover {{ opacity:0.9; }}

/* Filters */
.filters {{ display:flex; gap:8px; margin-bottom:20px; flex-wrap:wrap; }}
.filter-btn {{ padding:6px 14px; border-radius:20px; font-size:12px; font-weight:600; background:var(--surface); color:var(--text2); border:1px solid var(--border); cursor:pointer; text-decoration:none; }}
.filter-btn:hover, .filter-btn.active {{ background:var(--accent); color:white; border-color:var(--accent); text-decoration:none; }}

/* Table */
.data-table {{ width:100%; border-collapse:collapse; }}
.data-table th {{ text-align:left; padding:10px 12px; font-size:11px; color:var(--text3); text-transform:uppercase; letter-spacing:1px; border-bottom:1px solid var(--border); }}
.data-table td {{ padding:10px 12px; font-size:13px; border-bottom:1px solid var(--border); }}
.data-table tr:hover {{ background:var(--surface2); }}

/* Bar chart */
.bar-row {{ display:flex; align-items:center; gap:12px; margin-bottom:8px; }}
.bar-label {{ width:100px; font-size:12px; color:var(--text2); text-align:right; flex-shrink:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.bar-fill {{ height:24px; border-radius:4px; min-width:2px; transition:width 0.3s; }}
.bar-value {{ font-size:12px; color:var(--text3); min-width:30px; }}

/* Cluster */
.cluster-card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:12px; }}
.cluster-header {{ display:flex; align-items:center; gap:12px; margin-bottom:12px; }}
.cluster-label {{ font-size:16px; font-weight:700; color:var(--text); }}
.cluster-count {{ font-size:12px; color:var(--text3); }}
.cluster-stories {{ list-style:none; }}
.cluster-stories li {{ padding:6px 0; font-size:13px; color:var(--text2); border-bottom:1px solid var(--border); }}
.cluster-stories li:last-child {{ border-bottom:none; }}

/* Chart area */
.chart-container {{ position:relative; height:200px; display:flex; align-items:flex-end; gap:2px; padding-top:20px; }}
.chart-bar {{ flex:1; background:var(--accent); border-radius:3px 3px 0 0; min-height:2px; position:relative; transition:background 0.2s; }}
.chart-bar:hover {{ background:#60a5fa; }}
.chart-bar .tooltip {{ display:none; position:absolute; bottom:100%; left:50%; transform:translateX(-50%); background:var(--surface2); color:var(--text); padding:4px 8px; border-radius:4px; font-size:11px; white-space:nowrap; margin-bottom:4px; }}
.chart-bar:hover .tooltip {{ display:block; }}
.chart-labels {{ display:flex; gap:2px; margin-top:4px; }}
.chart-labels span {{ flex:1; text-align:center; font-size:9px; color:var(--text3); overflow:hidden; text-overflow:ellipsis; }}

.empty {{ text-align:center; padding:40px; color:var(--text3); }}
</style>
</head>
<body>
<div class="topbar">
  <span class="logo">&#128225; News Intel</span>
  {nav_html}
</div>
<div class="container">
{content}
</div>
</body>
</html>"""
    return HTMLResponse(html)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/briefing", response_class=HTMLResponse)
async def briefing():
    """30-second briefing — top 10 stories, zero noise."""
    articles = database.get_recent(limit=100, min_priority=50)

    # Deduplicate by cluster — pick highest-scoring article per cluster
    seen_clusters: dict[str, dict] = {}
    for a in articles:
        cluster = (a.get("cluster_id") or "").strip()
        key = cluster if cluster else a.get("title", "")[:30]
        if key not in seen_clusters or a.get("priority", 0) > seen_clusters[key].get("priority", 0):
            seen_clusters[key] = a
    top = sorted(seen_clusters.values(), key=lambda x: x.get("priority", 0), reverse=True)[:10]

    now = datetime.now()
    greeting = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 17 else "Good evening"
    date_str = now.strftime("%A, %B %d")

    items_html = ""
    for i, a in enumerate(top):
        p = a.get("priority", 0)
        pc = _priority_class(p)
        title = unescape(a.get("title", ""))
        summary = unescape(a.get("summary", ""))
        source = a.get("source", "")
        url = a.get("url", "")
        tags = a.get("tags", "") or ""

        # Pick best display text — summary if different from title
        display = summary if summary and summary.lower()[:30] != title.lower()[:30] else title

        # Color dot
        dot_color = "#ef4444" if p >= 70 else "#f59e0b" if p >= 50 else "#22c55e"

        # Tag pills
        tag_html = ""
        for t in tags.split(",")[:2]:
            t = t.strip()
            if t and t != "general":
                color = TAG_COLORS.get(t, "#64748b")
                tag_html += f'<span style="color:{color};font-size:11px;font-weight:600;margin-left:8px;">{TAG_EMOJI.get(t, "")} {t}</span>'

        # Link
        if url and url.startswith("http"):
            title_link = f'<a href="{url}" target="_blank" style="color:var(--text);text-decoration:none;">{title}</a>'
        else:
            title_link = title

        google_url = f"https://www.google.com/search?q={quote(title[:80])}&tbm=nws"

        items_html += f"""
        <div style="display:flex;gap:16px;align-items:flex-start;padding:16px 0;border-bottom:1px solid var(--border);">
          <div style="flex-shrink:0;width:36px;height:36px;background:{dot_color}18;border:2px solid {dot_color};border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:800;color:{dot_color};">{i+1}</div>
          <div style="flex:1;min-width:0;">
            <div style="font-size:15px;font-weight:700;line-height:1.4;margin-bottom:4px;">{title_link}</div>
            {"<div style='font-size:13px;color:var(--text2);line-height:1.5;margin-bottom:6px;'>" + display[:160] + "</div>" if display.lower()[:30] != title.lower()[:30] else ""}
            <div style="display:flex;align-items:center;gap:4px;">
              <span style="font-size:11px;color:var(--text3);">{source}</span>
              <span style="font-size:11px;color:var(--text3);">&middot; {p}/100</span>
              {tag_html}
              <a href="{google_url}" target="_blank" style="margin-left:auto;font-size:11px;color:var(--accent);">&#128269; More</a>
            </div>
          </div>
        </div>"""

    if not top:
        items_html = '<div class="empty">No high-priority stories yet. Run the agent first.</div>'

    content = f"""
    <div style="max-width:680px;margin:0 auto;">
      <div style="text-align:center;padding:32px 0 24px;">
        <div style="font-size:48px;margin-bottom:8px;">&#9889;</div>
        <h1 style="font-size:24px;font-weight:800;margin-bottom:4px;">{greeting}</h1>
        <p style="color:var(--text2);font-size:14px;">{date_str} &middot; Top {len(top)} stories in 30 seconds</p>
      </div>
      <div class="card" style="padding:4px 20px;">
        {items_html}
      </div>
      <div style="text-align:center;padding:20px;color:var(--text3);font-size:12px;">
        &#128225; Sourced from {len(config.RSS_FEEDS)}+ feeds &middot; Scored by AI + heuristics &middot; Updated every {config.POLL_INTERVAL_SECONDS//60} min
      </div>
    </div>
    """
    return _render_page("Briefing", content, "briefing")


@app.get("/", response_class=HTMLResponse)
async def home(
    q: str = Query("", description="Search query"),
    tag: str = Query("", description="Filter by tag"),
    priority: str = Query("", description="Filter by priority: high/medium/low"),
    limit: int = Query(50, ge=1, le=200),
):
    # Get articles
    if q:
        articles = database.search_articles(q, limit)
    else:
        min_p = 0
        if priority == "high":
            min_p = 70
        elif priority == "medium":
            min_p = 50
        elif priority == "low":
            min_p = 30
        articles = database.get_recent(limit, min_priority=min_p)

    # Filter by tag
    if tag:
        articles = [a for a in articles if tag.lower() in (a.get("tags", "") or "").lower()]

    # Stats
    total = database.get_article_count()
    dist = database.get_priority_distribution()

    # Build stats cards
    stats_html = f"""
    <div class="grid grid-4" style="margin-bottom:20px;">
      <div class="card stat-card total"><div class="value">{total}</div><div class="label">Total Articles</div></div>
      <div class="card stat-card high"><div class="value">{dist.get('high', 0)}</div><div class="label">Critical</div></div>
      <div class="card stat-card medium"><div class="value">{dist.get('medium', 0)}</div><div class="label">Important</div></div>
      <div class="card stat-card low"><div class="value">{dist.get('low', 0) + dist.get('minimal', 0)}</div><div class="label">Notable</div></div>
    </div>
    """

    # Search bar
    search_html = f"""
    <div class="search-bar">
      <form method="get" action="/">
        <input type="text" name="q" value="{q}" placeholder="Search articles...">
        <button type="submit">Search</button>
      </form>
    </div>
    """

    # Tag filters
    tags_data = database.get_tag_distribution()
    filter_html = '<div class="filters">'
    filter_html += f'<a href="/" class="filter-btn {"active" if not tag and not priority else ""}">All</a>'
    filter_html += f'<a href="/?priority=high" class="filter-btn {"active" if priority == "high" else ""}">&#128308; Critical</a>'
    filter_html += f'<a href="/?priority=medium" class="filter-btn {"active" if priority == "medium" else ""}">&#128992; Important</a>'
    for td in tags_data[:10]:
        t = td["tag"]
        emoji = TAG_EMOJI.get(t, "")
        active = "active" if tag == t else ""
        filter_html += f'<a href="/?tag={t}" class="filter-btn {active}">{emoji} {t} ({td["count"]})</a>'
    filter_html += '</div>'

    # Article list
    articles_html = ""
    for a in articles:
        p = a.get("priority", 0)
        pc = _priority_class(p)
        pl = _priority_label(p)
        title = unescape(a.get("title", ""))
        summary = unescape(a.get("summary", ""))
        source = a.get("source", "")
        url = a.get("url", "")
        tags = a.get("tags", "") or ""

        # Title link
        if url and url.startswith("http"):
            title_html = f'<a href="{url}" target="_blank">{title}</a>'
        else:
            title_html = title

        # Tags
        tag_html = ""
        for t in tags.split(","):
            t = t.strip()
            if t:
                color = TAG_COLORS.get(t, "#64748b")
                tag_html += f'<span class="tag-pill" style="background:{color}22;color:{color};border:1px solid {color}44;">{TAG_EMOJI.get(t, "")} {t}</span>'

        # Action buttons
        google_url = f"https://www.google.com/search?q={quote(title[:80])}&tbm=nws"
        x_url = f"https://x.com/search?q={quote(title[:60])}&f=live"
        actions = f'<a href="{google_url}" target="_blank" class="btn btn-google">&#128269; Google</a>'
        actions += f'<a href="{x_url}" target="_blank" class="btn btn-x">&#120143; Search</a>'
        if url and url.startswith("http"):
            actions = f'<a href="{url}" target="_blank" class="btn btn-primary">Read &#8594;</a>' + actions

        articles_html += f"""
        <div class="article {pc}">
          <div class="article-meta">
            <span class="badge {pc}">{p}/100 {pl}</span>
            <span class="article-source">{source}</span>
          </div>
          <div class="article-title">{title_html}</div>
          {"<div class='article-summary'>" + summary + "</div>" if summary and summary.lower()[:30] != title.lower()[:30] else ""}
          <div>{tag_html}</div>
          <div class="article-actions">{actions}</div>
        </div>"""

    if not articles:
        articles_html = '<div class="empty">No articles found. Run the agent first: <code>python main.py --once</code></div>'

    content = stats_html + search_html + filter_html + articles_html
    return _render_page("Feed", content, "home")


@app.get("/analytics", response_class=HTMLResponse)
async def analytics():
    # Timeline
    timeline = database.get_timeline(hours=48, bucket_minutes=60)
    tag_dist = database.get_tag_distribution()
    priority_dist = database.get_priority_distribution()

    # Timeline chart
    max_count = max((t["count"] for t in timeline), default=1)
    bars = ""
    labels = ""
    for t in timeline[-36:]:  # last 36 hours
        height = max(2, int((t["count"] / max(max_count, 1)) * 180))
        hour_label = t["time"].split(" ")[1][:5] if " " in t["time"] else t["time"]
        bars += f'<div class="chart-bar" style="height:{height}px;"><div class="tooltip">{hour_label}: {t["count"]} articles (avg {t["avg_priority"]})</div></div>'
        labels += f'<span>{hour_label}</span>'

    timeline_html = f"""
    <div class="card" style="margin-bottom:16px;">
      <h2>&#128200; Article Volume (Last 48h)</h2>
      <div class="chart-container">{bars}</div>
      <div class="chart-labels">{labels}</div>
    </div>
    """

    # Tag distribution bar chart
    max_tag = max((t["count"] for t in tag_dist), default=1)
    tag_bars = ""
    for t in tag_dist[:15]:
        width = max(2, int((t["count"] / max(max_tag, 1)) * 100))
        color = TAG_COLORS.get(t["tag"], "#64748b")
        emoji = TAG_EMOJI.get(t["tag"], "")
        tag_bars += f"""
        <div class="bar-row">
          <div class="bar-label">{emoji} {t["tag"]}</div>
          <div class="bar-fill" style="width:{width}%;background:{color};"></div>
          <div class="bar-value">{t["count"]}</div>
        </div>"""

    tag_html = f"""
    <div class="card">
      <h2>&#127991;&#65039; Topic Distribution</h2>
      {tag_bars}
    </div>
    """

    # Priority pie (text-based)
    high = priority_dist.get("high", 0) or 0
    med = priority_dist.get("medium", 0) or 0
    low = priority_dist.get("low", 0) or 0
    minimal = priority_dist.get("minimal", 0) or 0
    total = high + med + low + minimal or 1

    priority_html = f"""
    <div class="card">
      <h2>&#127919; Priority Breakdown</h2>
      <div class="bar-row"><div class="bar-label">&#128308; Critical</div><div class="bar-fill" style="width:{high/total*100:.0f}%;background:var(--red);"></div><div class="bar-value">{high} ({high/total*100:.0f}%)</div></div>
      <div class="bar-row"><div class="bar-label">&#128992; Important</div><div class="bar-fill" style="width:{med/total*100:.0f}%;background:var(--amber);"></div><div class="bar-value">{med} ({med/total*100:.0f}%)</div></div>
      <div class="bar-row"><div class="bar-label">&#128994; Notable</div><div class="bar-fill" style="width:{low/total*100:.0f}%;background:var(--green);"></div><div class="bar-value">{low} ({low/total*100:.0f}%)</div></div>
      <div class="bar-row"><div class="bar-label">&#9898; Minimal</div><div class="bar-fill" style="width:{minimal/total*100:.0f}%;background:var(--text3);"></div><div class="bar-value">{minimal} ({minimal/total*100:.0f}%)</div></div>
    </div>
    """

    content = timeline_html + f'<div class="grid grid-2">{tag_html}{priority_html}</div>'
    return _render_page("Analytics", content, "analytics")


@app.get("/clusters", response_class=HTMLResponse)
async def clusters():
    cluster_data = database.get_clusters()

    if not cluster_data:
        content = '<div class="empty">No clusters found yet. Clusters form when multiple related articles are collected.</div>'
        return _render_page("Clusters", content, "clusters")

    content = f'<h2 style="margin-bottom:16px;color:var(--text2);font-size:14px;text-transform:uppercase;letter-spacing:1px;">&#128279; {len(cluster_data)} Story Clusters</h2>'

    for c in cluster_data:
        stories_html = ""
        for title in c["sample_titles"]:
            stories_html += f"<li>{unescape(title)}</li>"

        content += f"""
        <div class="cluster-card">
          <div class="cluster-header">
            <span class="cluster-label">{c['cluster_id']}</span>
            <span class="badge {'high' if c['top_priority'] >= 70 else 'medium' if c['top_priority'] >= 50 else 'low'}">{c['count']} articles &middot; avg {c['avg_priority']}</span>
          </div>
          <ul class="cluster-stories">{stories_html}</ul>
        </div>"""

    return _render_page("Clusters", content, "clusters")


@app.get("/sources", response_class=HTMLResponse)
async def sources():
    source_data = database.get_source_stats()

    if not source_data:
        content = '<div class="empty">No source data yet.</div>'
        return _render_page("Sources", content, "sources")

    table_rows = ""
    for s in source_data:
        p = s.get("avg_priority", 0) or 0
        pc = _priority_class(int(p))
        table_rows += f"""
        <tr>
          <td style="font-weight:600;">{s['source']}</td>
          <td>{s['count']}</td>
          <td><span class="badge {pc}">{p}</span></td>
          <td>{s.get('max_priority', 0)}</td>
        </tr>"""

    content = f"""
    <div class="card">
      <h2>&#128218; Source Performance</h2>
      <table class="data-table">
        <thead><tr><th>Source</th><th>Articles</th><th>Avg Score</th><th>Peak Score</th></tr></thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>
    """

    # Top sources bar chart
    max_count = max((s["count"] for s in source_data), default=1)
    bars = ""
    for s in source_data[:15]:
        width = max(2, int((s["count"] / max(max_count, 1)) * 100))
        bars += f"""
        <div class="bar-row">
          <div class="bar-label">{s['source'][:20]}</div>
          <div class="bar-fill" style="width:{width}%;background:var(--accent);"></div>
          <div class="bar-value">{s['count']}</div>
        </div>"""

    content += f"""
    <div class="card" style="margin-top:16px;">
      <h2>&#128202; Article Volume by Source</h2>
      {bars}
    </div>
    """

    return _render_page("Sources", content, "sources")


# ── JSON API ─────────────────────────────────────────────────────────────────

@app.get("/api/articles")
async def api_articles(limit: int = 50, min_priority: int = 0, q: str = ""):
    if q:
        return database.search_articles(q, limit)
    return database.get_recent(limit, min_priority)


@app.get("/api/analytics")
async def api_analytics():
    return {
        "tags": database.get_tag_distribution(),
        "priority": database.get_priority_distribution(),
        "timeline": database.get_timeline(),
        "sources": database.get_source_stats(),
        "clusters": database.get_clusters(),
    }


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("\n  ╔══════════════════════════════════════╗")
    print("  ║  📡 News Intelligence Dashboard      ║")
    print("  ║  http://localhost:8000                ║")
    print("  ╚══════════════════════════════════════╝\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
