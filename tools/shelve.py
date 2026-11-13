"""Shelve books onto the Shelf.

    python tools/shelve.py            take in everything in inbox/, then rebuild every book and the shelf
    python tools/shelve.py --check    report what would change, write nothing

A "book" is one self-contained HTML file. The tool never edits what you drop in: the file is moved to
originals/ and kept as it arrived. What ships is books/<id>.html, the same file with the Shelf frame added:

    head   the Shelf favicon, a theme colour, "<title> · Shelf"
    body   the Shelf bar: the mark, a link back to the shelf, the book's number, a reading-status button and
           previous / next. It lives in a shadow root, so the book's CSS cannot touch it and it cannot touch
           the book. It takes its colours from the book (the page background, the text colour, one accent),
           so every book keeps its own look and still carries the same strip.

catalog.json is the list of books and is yours to edit (title, author, tags, blurb, cover colours, emblem).
A new book gets an entry guessed from the file; anything the tool could not work out is listed at the end.
Standard library only.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX, ORIGINALS, BOOKS = ROOT / "inbox", ROOT / "originals", ROOT / "books"
CATALOG, INDEX = ROOT / "catalog.json", ROOT / "index.html"
STORE_KEY = "library.v1"

# The mark: an S that is also a bookcase, books standing on its two shelves. 24 x 24, drawn in currentColor.
MARK = ('<path d="M5 2H22V4.6H4.6V10.7H19a3 3 0 0 1 3 3V19a3 3 0 0 1-3 3H2V19.4H19.4V13.3H5a3 3 0 0 1-3-3V5a3 3 0 0 1 3-3z"/>'
        '<path d="M6 6h2.2v5H6zM9.3 7h2v4h-2zM12.9 11.2L11.8 6.9l1.95-.5 1.1 4.3zM15.8 14.7h2.2v5h-2.2zM12.7 15.7h2v4h-2zM11.1 19.9l1.1-4.3-1.95-.5-1.1 4.3z"/>')
ACCENT_VARS = ["--a", "--accent", "--gold", "--red", "--rose", "--seal", "--l1", "--now", "--ww1"]


# ---------------------------------------------------------------------------------------------------------------
# Reading a book file
# ---------------------------------------------------------------------------------------------------------------
def root_vars(src: str) -> dict[str, str]:
    m = re.search(r":root\s*\{([^}]*)\}", src)
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1))) if m else {}


def resolve(expr: str | None, vars_: dict[str, str]) -> str | None:
    """A CSS value down to a hex colour, following var() once or twice. None when it is not a plain colour."""
    for _ in range(4):
        if not expr:
            return None
        expr = expr.strip()
        m = re.fullmatch(r"var\(\s*(--[\w-]+)\s*(?:,[^)]*)?\)", expr)
        if not m:
            break
        expr = vars_.get(m.group(1))
    if expr and re.fullmatch(r"#[0-9a-fA-F]{3,8}", expr):
        h = expr[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        return "#" + h[:6].lower()
    return None


def body_rule(src: str) -> dict[str, str]:
    """Every declaration that applies to <body> in the book's first <style>, later rules winning."""
    css = re.search(r"<style[^>]*>(.*?)</style>", src, re.S)
    css = re.sub(r"/\*.*?\*/", "", css.group(1), flags=re.S) if css else ""
    out: dict[str, str] = {}
    for sel, decl in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        if any(part.strip() == "body" for part in sel.split(",")):
            out.update({k.strip(): v.strip() for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+)", decl)})
    return out


def luminance(hex_: str) -> float:
    ch = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_of(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def read_book(src: str, filename: str) -> tuple[dict, list[str]]:
    """Everything the catalogue wants to know, guessed from the file. Returns (entry, things to check)."""
    todo = []
    vars_ = root_vars(src)
    body = body_rule(src)
    m = re.search(r"<h1[^>]*>(.*?)</h1>", src, re.S)
    t = re.search(r"<title[^>]*>(.*?)</title>", src, re.S)
    title = text_of(m.group(1)) if m else re.sub(r"\s+Guide$", "", text_of(t.group(1))) if t else ""
    if not title:
        title = Path(filename).stem.replace("-", " ").title()
        todo.append("title (none found in the file)")
    by = re.search(r'class="by"[^>]*>(.*?)<', src, re.S)
    byline = text_of(by.group(1)) if by else ""
    author, year = "", None
    m = re.search(r"\bby ((?:[A-Z][\w.'’-]*\s?){1,4})\((\d{4})\)", src)
    if m:
        author, year = m.group(1).strip(), int(m.group(2))
    else:
        m = re.search(r"((?:[A-Z][\w.'’-]*\s){1,3}[A-Z][\w.’-]*)['’]s (?:\d{4} )?(?:book|novel|play|essay)", byline)
        if m:
            author = m.group(1).strip()
        y = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", byline)
        year = int(y.group(1)) if y else None
    if not author:
        todo.append("author")
    if not year:
        todo.append("year")
    bg_expr, fg_expr = body.get("background") or body.get("background-color"), body.get("color")
    bg, fg = resolve(bg_expr, vars_) or "#f4f1ea", resolve(fg_expr, vars_) or "#23201c"
    accent_var = next((v for v in ACCENT_VARS if resolve(vars_.get(v), vars_)), None)
    accent = resolve(vars_.get(accent_var), vars_) if accent_var else fg
    if not resolve(bg_expr, vars_):
        todo.append("page background (the bar and cover fall back to paper)")
    stem = re.sub(r"-guide$", "", Path(filename).stem.lower())
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    entry = {
        "id": stem, "no": 0, "title": title, "author": author or "Unknown", "year": year, "kind": "Guide",
        "tags": [], "blurb": byline, "source": filename, "added": dt.date.today().isoformat(),
        "cover": {"bg": bg, "fg": fg, "line": accent if contrast(accent, bg) >= 1.6 else fg},
        "bar": {"bg": bg_expr if resolve(bg_expr, vars_) else "", "accent": f"var({accent_var})" if accent_var else ""},
        "emblem": "",
    }
    todo.append("tags (none yet)")
    return entry, todo


# ---------------------------------------------------------------------------------------------------------------
# The frame
# ---------------------------------------------------------------------------------------------------------------
BAR_CSS = """
:host{display:block;flex:none;position:relative;font:500 12.5px/1 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:inherit;background:var(--lib-bg,transparent);-webkit-text-size-adjust:100%}
:host(.lib-sticky){position:sticky;top:0;z-index:50}
*{box-sizing:border-box}
.bar{display:flex;align-items:center;gap:4px;height:38px;padding:0 8px 0 6px;max-width:100%;
  border-bottom:1px solid color-mix(in srgb,currentColor 16%,transparent)}
a,button{color:inherit;font:inherit;text-decoration:none;background:none;border:0;cursor:pointer;border-radius:6px;
  display:inline-flex;align-items:center;gap:7px;height:30px;padding:0 8px;-webkit-tap-highlight-color:transparent}
a:hover,button:hover{background:color-mix(in srgb,currentColor 9%,transparent)}
:focus-visible{outline:2px solid var(--lib-accent,currentColor);outline-offset:1px}
.home svg{width:18px;height:18px;fill:var(--lib-accent,currentColor);flex:none}
.home b{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-size:13px;letter-spacing:.2em;text-transform:uppercase}
.no{opacity:.62;font-variant-numeric:tabular-nums;white-space:nowrap;padding-left:9px;margin-left:1px;
  border-left:1px solid color-mix(in srgb,currentColor 22%,transparent);line-height:16px}
.sp{flex:1}
.status i{width:11px;height:11px;border-radius:50%;border:1.6px solid currentColor;flex:none;opacity:.75}
.status[data-s="reading"] i{background:linear-gradient(90deg,var(--lib-accent,currentColor) 50%,transparent 50%);border-color:var(--lib-accent,currentColor);opacity:1}
.status[data-s="finished"] i{background:var(--lib-accent,currentColor);border-color:var(--lib-accent,currentColor);opacity:1}
.step{width:30px;padding:0;justify-content:center;font-size:17px;line-height:1}
.step[aria-disabled="true"]{opacity:.28;pointer-events:none}
@media (max-width:400px){.no span{display:none}.home b{letter-spacing:.14em}}
@media (max-width:330px){.status span{display:none}}
"""

BAR_JS = """
(function(){
  var B=__DATA__, host=document.getElementById("library-bar"); if(!host) return;
  var root=host.shadowRoot; if(!root){var t=host.querySelector("template"); root=host.attachShadow({mode:"open"}); if(t){root.appendChild(t.content); t.remove();}}
  var KEY="__KEY__", LAB={none:"To read",reading:"Reading",finished:"Finished"}, NEXT={none:"reading",reading:"finished",finished:"none"};
  function load(){try{var s=JSON.parse(localStorage.getItem(KEY)); if(s&&s.books) return s;}catch(e){} return {books:{}};}
  function save(s){try{localStorage.setItem(KEY,JSON.stringify(s));}catch(e){}}
  var btn=root.querySelector(".status");
  function draw(){var st=(load().books[B.id]||{}).status||"none"; btn.dataset.s=st; btn.querySelector("span").textContent=LAB[st];
    btn.setAttribute("aria-label","Reading status: "+LAB[st]+". Press to change.");}
  var s=load(), me=s.books[B.id]||(s.books[B.id]={}); me.opened=Date.now(); save(s); draw();
  btn.addEventListener("click",function(){var s=load(), me=s.books[B.id]||(s.books[B.id]={}); me.status=NEXT[me.status||"none"]; me.opened=Date.now(); save(s); draw();});
  addEventListener("storage",function(e){if(e.key===KEY) draw();});
})();
"""


def bar_html(e: dict, prev: dict | None, nxt: dict | None, total: int, sticky: bool) -> str:
    esc = html.escape
    style_vars = "".join(f"--lib-{k}:{v};" for k, v in (("bg", e["bar"].get("bg")), ("accent", e["bar"].get("accent"))) if v)

    def step(b, ch, word):
        if not b:
            return f'<a class="step" aria-disabled="true" aria-label="No {word} book">{ch}</a>'
        return f'<a class="step" href="{esc(b["id"])}.html" title="{word.capitalize()}: {esc(b["title"])}" aria-label="{word.capitalize()} book: {esc(b["title"])}">{ch}</a>'

    data = json.dumps({"id": e["id"]}, ensure_ascii=False)
    return (
        "<!-- library:bar — added by tools/shelve.py; the original file is in originals/ -->\n"
        f'<div id="library-bar" role="navigation" aria-label="Shelf" class="{"lib-sticky" if sticky else ""}" '
        f'style="display:block;flex:none;{style_vars}">'
        '<template shadowrootmode="open">'
        f"<style>{BAR_CSS.strip()}</style>"
        '<div class="bar">'
        f'<a class="home" href="../index.html#{esc(e["id"])}" title="Back to the shelf">'
        f'<svg viewBox="0 0 24 24" aria-hidden="true">{MARK}</svg><b>Shelf</b></a>'
        f'<span class="no" title="Book {e["no"]} of {total}">No. {e["no"]}<span> of {total}</span></span>'
        '<span class="sp"></span>'
        '<button class="status" type="button" data-s="none"><i></i><span>To read</span></button>'
        f'{step(prev, "‹", "previous")}{step(nxt, "›", "next")}'
        "</div></template></div>\n"
        f"<script>{BAR_JS.strip().replace('__DATA__', data).replace('__KEY__', STORE_KEY)}</script>\n"
        "<!-- /library:bar -->\n"
    )


def favicon(bg: str, fg: str) -> str:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="{bg}"/>'
           f'<g fill="{fg}" transform="translate(4 4)">{MARK}</g></svg>')
    from urllib.parse import quote
    return "data:image/svg+xml," + quote(svg, safe="/:=' ")


def frame(src: str, e: dict, prev, nxt, total: int) -> str:
    body = body_rule(src)
    sticky = "hidden" not in (body.get("overflow", "") + body.get("overflow-y", ""))
    c = e["cover"]
    head = ("<!-- library:head -->\n"
            f'<link rel="icon" href="{html.escape(favicon(c["bg"], c["line"]))}">\n'
            f'<meta name="theme-color" content="{c["bg"]}">\n'
            f'<meta name="library:id" content="{html.escape(e["id"])}">\n'
            "<!-- /library:head -->\n")
    out, n = re.subn(r"<title[^>]*>.*?</title>", lambda m: f"<title>{html.escape(e['title'])} · Shelf</title>\n{head}", src, count=1, flags=re.S)
    if not n:
        out, n = re.subn(r"</head>", lambda m: f"<title>{html.escape(e['title'])} · Shelf</title>\n{head}</head>", src, count=1, flags=re.I)
    out, n2 = re.subn(r"(<body[^>]*>)\s*", lambda m: m.group(1) + "\n" + bar_html(e, prev, nxt, total, sticky), out, count=1, flags=re.I)
    if not n2:
        raise ValueError("no <body> tag")
    return out


# ---------------------------------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------------------------------
def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    check = "--check" in sys.argv
    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() else {"books": []}
    books = catalog["books"]
    notes: list[str] = []
    for d in (INBOX, ORIGINALS, BOOKS):
        d.mkdir(exist_ok=True)

    # 1. take in new files
    for f in sorted(INBOX.glob("*.htm*")):
        src = f.read_text(encoding="utf-8", errors="replace")
        known = next((b for b in books if b["source"] == f.name), None)
        if known:
            notes.append(f"updated   {known['title']}: new copy of {f.name} replaces the one in originals/")
        else:
            entry, todo = read_book(src, f.name)
            ids = {b["id"] for b in books}
            base, k = entry["id"], 2
            while entry["id"] in ids:
                entry["id"] = f"{base}-{k}"; k += 1
            entry["no"] = max((b["no"] for b in books), default=0) + 1
            books.append(entry)
            notes.append(f"added     No. {entry['no']}  {entry['title']} — {entry['author']}" + (f"   (check in catalog.json: {', '.join(todo)})" if todo else ""))
        if not check:
            shutil.move(str(f), str(ORIGINALS / f.name))

    # 2. rebuild every book from its original
    books.sort(key=lambda b: b["no"])
    built = 0
    for i, e in enumerate(books):
        src_path = ORIGINALS / e["source"]
        if not src_path.exists():
            src_path = INBOX / e["source"] if check else src_path
        if not src_path.exists():
            notes.append(f"MISSING   {e['title']}: originals/{e['source']} is not there; the book was skipped")
            continue
        out = frame(src_path.read_text(encoding="utf-8", errors="replace"), e, books[i - 1] if i else None,
                    books[i + 1] if i + 1 < len(books) else None, len(books))
        target = BOOKS / f"{e['id']}.html"
        if not check and (not target.exists() or target.read_text(encoding="utf-8") != out):
            target.write_text(out, encoding="utf-8", newline="\n")
        built += 1
    if not check:
        keep = {f"{e['id']}.html" for e in books}
        for stray in BOOKS.glob("*.html"):
            if stray.name not in keep:
                notes.append(f"note      books/{stray.name} is not in the catalogue (left alone)")

    # 3. the catalogue, and its copy inside the shelf page
    if not check:
        CATALOG.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        if INDEX.exists():
            page = INDEX.read_text(encoding="utf-8")
            data = json.dumps(books, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
            page, n = re.subn(r'(<script id="catalog" type="application/json">).*?(</script>)', lambda m: m.group(1) + data + m.group(2), page, count=1, flags=re.S)
            if n:
                INDEX.write_text(page, encoding="utf-8", newline="\n")
            else:
                notes.append("WARNING   index.html has no <script id=\"catalog\"> block; the shelf was not updated")
    for n in notes:
        print(n)
    print(f"{'would build' if check else 'built'} {built} of {len(books)} books" + ("" if check else " · catalog.json and index.html updated"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
