"""Turn phone_notes.md into phone_notes.html, a page sized for reading on a phone.

Usage: python3 make_phone_notes.py   (run from docs/talk)

Only the Markdown that phone_notes.md uses is supported: # / ## / ### headings, "- " bullets,
"> " callouts ("Label: text"), **bold** and [text](#anchor) links.
"""
import html
import re
from pathlib import Path

HERE = Path(__file__).parent

STYLE = """<title>Talk phone notes</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&display=swap">
<style>
/* One column of cards, one per PDF page; a sticky strip of page numbers to jump. */
:root {
  --bg: #f4f6f9; --card: #ffffff; --fg: #15202b; --muted: #5a6876; --line: #dde3ea;
  --accent: #1d5bb8; --ask: #8a5400; --avoid: #b3261e;
  --font: "Atkinson Hyperlegible", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0e1318; --card: #161d24; --fg: #eaeff4; --muted: #9eabb8; --line: #26313c;
  --accent: #82b2ff; --ask: #f2b862; --avoid: #ff8a80; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #0e1318; --card: #161d24; --fg: #eaeff4; --muted: #9eabb8; --line: #26313c;
  --accent: #82b2ff; --ask: #f2b862; --avoid: #ff8a80; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font-family: var(--font); font-size: 19px; line-height: 1.45; }
body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 10; background: var(--bg); }
.nav { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; background: var(--bg);
  border-bottom: 1px solid var(--line); padding-block: 8px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.chips { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
.chips a, .chips button { flex: none; font: 700 15px/1 var(--font); color: var(--fg); text-decoration: none;
  background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 9px 11px; min-width: 40px; text-align: center; cursor: pointer; }
.chips .q { color: var(--accent); }
.chips button[aria-pressed="true"] { background: var(--accent); color: var(--bg); border-color: var(--accent); }
.chips a:focus-visible, .chips button:focus-visible, a:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
main { max-width: 640px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; padding-block: 16px 48px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
h1 { font-size: 1.35rem; line-height: 1.2; margin: 18px 0 0; text-wrap: balance; }
.lede { color: var(--muted); margin: 0; font-size: 0.9rem; }
section { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px;
  scroll-margin-top: calc(env(safe-area-inset-top, 0px) + 70px); min-width: 0; }
h2 { display: flex; align-items: baseline; gap: 10px; font-size: 1.15rem; line-height: 1.25; margin: 0 0 8px; text-wrap: balance; }
h2 .num { flex: none; font-variant-numeric: tabular-nums; color: var(--accent); font-size: 1.5rem; min-width: 1.6em; }
h3 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 14px 0 4px; }
h3:first-of-type { margin-top: 0; }
ul { margin: 0; padding-left: 1.1em; display: flex; flex-direction: column; gap: 6px; }
li::marker { color: var(--muted); }
strong { font-weight: 700; }
a { color: var(--accent); }
.call { margin: 10px 0 0; font-size: 0.95rem; }
.call .lab { display: block; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ask); }
.call.avoid .lab { color: var(--avoid); }
@media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
</style>
"""

SCRIPT = """<script>
(function () {
  var btn = document.getElementById("wake"), lock = null;
  if (!btn) return;
  if (!("wakeLock" in navigator)) { btn.hidden = true; return; }
  async function on() {
    try { lock = await navigator.wakeLock.request("screen"); btn.setAttribute("aria-pressed", "true"); btn.textContent = "Screen on";
      lock.addEventListener("release", function () { btn.setAttribute("aria-pressed", "false"); btn.textContent = "Keep screen on"; });
    } catch (e) { btn.textContent = "Screen lock unavailable"; }
  }
  btn.addEventListener("click", function () { if (lock && !lock.released) { lock.release(); lock = null; } else { on(); } });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && btn.getAttribute("aria-pressed") === "true" && (!lock || lock.released)) on();
  });
})();
</script>
"""


def inline(text):
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\[([^\]]+)\]\((#[\w-]+)\)", r'<a href="\2">\1</a>', t)
    return t


def section_id(title):
    m = re.match(r"(\d+|Q\d+) · ", title)
    if m:
        k = m.group(1)
        return ("s" + k) if k.isdigit() else k.lower(), k
    return ("start" if title.startswith("Before") else title.split()[0].lower()), None


def build(md):
    out, chips = [], []
    in_section = in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def close_section():
        nonlocal in_section
        close_list()
        if in_section:
            out.append("</section>")
            in_section = False

    first_h1 = True
    for line in md.splitlines():
        if line.startswith("# "):
            close_section()
            out.append(f"<h1>{inline(line[2:])}</h1>")
            if first_h1:
                first_h1 = False
            continue
        if line.startswith("## "):
            close_section()
            title = line[3:]
            sid, key = section_id(title)
            label = title.split(" · ", 1)[1] if key else title
            num = f'<span class="num">{key}</span>' if key else ""
            out.append(f'<section id="{sid}"><h2>{num}<span>{inline(label)}</span></h2>')
            chips.append((sid, key or sid.capitalize()))
            in_section = True
            continue
        if line.startswith("### "):
            close_list()
            out.append(f"<h3>{inline(line[4:])}</h3>")
            continue
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if line.startswith("> "):
            close_list()
            body = line[2:]
            lab, _, rest = body.partition(": ")
            cls = "call avoid" if lab.startswith("Avoid") else "call"
            out.append(f'<p class="{cls}"><span class="lab">{inline(lab)}</span>{inline(rest)}</p>')
            continue
        if line.strip():
            close_list()
            out.append(f'<p class="lede">{inline(line)}</p>')
    close_section()

    nav = ['<nav class="nav" aria-label="Jump to slide"><div class="chips">']
    for sid, key in chips:
        cls = ' class="q"' if key.startswith("Q") else ""
        nav.append(f'<a href="#{sid}"{cls}>{key}</a>')
    nav.append('<button id="wake" type="button" aria-pressed="false">Keep screen on</button></div></nav>')
    return STYLE + "\n".join(nav) + "\n<main>\n" + "\n".join(out) + "\n</main>\n" + SCRIPT


if __name__ == "__main__":
    src = (HERE / "phone_notes.md").read_text(encoding="utf-8")
    (HERE / "phone_notes.html").write_text(build(src), encoding="utf-8")
    print("wrote phone_notes.html")
