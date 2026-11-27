"""Shared facetMedia-branded HTML OAuth callback page.

Stdlib-only helper rendered by loopback OAuth handlers across publishing
packages so both successful and rejected sign-ins return a clear, styled
HTML5 response instead of a bare text line.
"""

from __future__ import annotations

import html


def render(ok: bool, provider: str, detail: str = "") -> bytes:
    """Render a self-contained UTF-8 HTML5 OAuth callback page."""
    safe_provider = html.escape(provider, quote=True)
    safe_detail = html.escape(detail, quote=True)
    badge = "Signed in" if ok else "Sign-in failed"
    badge_bg = "#E8C547" if ok else "#1A1917"
    badge_fg = "#1A1917" if ok else "#F6F3EC"
    title = f"facetMedia \u2014 {safe_provider} {badge}"
    heading = (
        f"{safe_provider} signed in; return to the terminal"
        if ok
        else f"{safe_provider} sign-in failed"
    )
    hint = (
        "You can close this tab and return to your terminal."
        if ok
        else "Return to the terminal to inspect the error and try again. You can close this tab."
    )
    detail_block = f'<p class="detail">{safe_detail}</p>' if safe_detail else ""
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    min-height: 100vh;
    display: grid;
    place-items: center;
    padding: 24px;
    background: #F6F3EC;
    color: #1A1917;
    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
  }}
  main {{
    width: 100%;
    max-width: 480px;
    background: #FFFFFF;
    border: 1px solid #D9D4C7;
    border-top: 4px solid #E8C547;
    border-radius: 8px;
    padding: 28px;
  }}
  .top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 20px;
  }}
  .wordmark {{
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #1A1917;
  }}
  .badge {{
    display: inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    background: {badge_bg};
    color: {badge_fg};
    font-size: 12px;
    font-weight: 600;
  }}
  h1 {{
    margin: 0 0 10px;
    font-size: 20px;
    line-height: 1.3;
  }}
  .detail {{
    margin: 0 0 14px;
    padding: 10px 12px;
    background: #F6F3EC;
    border: 1px solid #D9D4C7;
    border-radius: 6px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 13px;
    overflow-wrap: anywhere;
  }}
  .hint {{
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
    color: #4A4740;
  }}
</style>
</head>
<body>
  <main>
    <div class="top">
      <span class="wordmark">facetMedia</span>
      <span class="badge">{badge}</span>
    </div>
    <h1>{heading}</h1>
    {detail_block}
    <p class="hint">{hint}</p>
  </main>
</body>
</html>
"""
    return page.encode("utf-8")
