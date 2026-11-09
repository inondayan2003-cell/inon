"""Build the one-file preview of Nails (no server needed).

The real app files (static/) plus demo/mock-api.js, which answers the /api/ calls
inside the browser and keeps data in localStorage.

Usage:  python demo/build.py [output.html]     (default: demo/nails-preview.html)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "demo" / "nails-preview.html"

index = (STATIC / "index.html").read_text()
css = (STATIC / "style.css").read_text()
app = (STATIC / "content.js").read_text() + "\n" + (STATIC / "app.js").read_text()
mock = (ROOT / "demo" / "mock-api.js").read_text()

# Page body: everything between <body> and the first <script>.
body = index.split("<body", 1)[1].split(">", 1)[1].split("<script", 1)[0]
body = body.replace('<div class="boot">💅</div>', "")

# Dark theme: follow both the system setting and an explicit data-theme choice.
m = re.search(r"@media \(prefers-color-scheme: dark\) \{\n  :root \{(.*?)\n  \}\n\}", css, re.S)
assert m, "dark token block not found"
tokens = m.group(1)
css = css.replace(m.group(0), (
    "@media (prefers-color-scheme: dark) {\n  :root:not([data-theme=\"light\"]) {" + tokens +
    "\n    color-scheme: dark;\n  }\n}\n:root[data-theme=\"dark\"] {" + tokens + "\n  color-scheme: dark;\n}"))

# Smaller photos in the preview: they are stored in the browser.
app = app.replace("maxSide = 1600, quality = 0.85", "maxSide = 900, quality = 0.75")
assert "maxSide = 900" in app

html = f"""<title>Nails</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700;800&display=swap" rel="stylesheet">
<style>
html, body {{ direction: rtl; }}
{css}
</style>
<div dir="rtl" lang="he">
{body}
</div>
<script>
document.documentElement.lang = "he";
document.documentElement.dir = "rtl";
document.body.classList.add("signed-out");
{mock}
</script>
<script>
{app}
</script>
"""
out.write_text(html)
print(f"wrote {out} ({len(html) // 1024} KB)")
