# Shelf

![Shelf](logo.svg)

A shelf for books converted to single HTML files. Every book keeps its own colours and layout; what makes them
one series is the frame around them.

- **The shelf** (`index.html`): every book as a cover in one series layout (the mark, "Shelf", the book's number,
  an emblem, title, author, kind and year) drawn in that book's own colours. Search, filter by reading status or
  tag, sort, and a "pick up where you left off" link.
- **The Shelf bar**: a 38px strip at the top of every book with the mark, a link back to the shelf, the book's
  number, a reading-status button (To read, Reading, Finished) and previous / next. It takes its background, text
  colour and accent from the book it sits in, so it never clashes, and it is the same strip everywhere.

No server and no build step for reading: open `index.html`. Each file in `books/` is still one self-contained page
that opens on its own. Reading status is kept in the browser (`localStorage`), so it is shared between the shelf
and the books when the folder is served over http; opened straight from disk, some browsers keep it per file.

## Adding a book

1. Drop the HTML file in `inbox/`.
2. Run `python tools/shelve.py` (or double-click `Add books.cmd`).
3. Open `catalog.json` and tidy the new entry if needed, then run the tool again.

The tool moves the file to `originals/` untouched, writes the framed copy to `books/<id>.html`, adds an entry to
`catalog.json` and rewrites the list inside `index.html`. It guesses the title (the page's `<h1>`), author and
year ("by Name (1999)" in the text, or "Name's book" in the by-line), and the colours (the page background, text
colour and first accent variable). It prints whatever it could not work out.

To replace a book with a newer conversion, drop a file with the same name in `inbox/` and run the tool.
To remove one, delete its entry from `catalog.json` and its files from `books/` and `originals/`, then run the tool.

## catalog.json

```json
{
 "id": "atomic-habits",            "used for the file name and the shelf link",
 "no": 4,                          "the number on the cover and in the bar; also the shelf order",
 "title": "Atomic Habits", "author": "James Clear", "year": 2018,
 "kind": "Guide",                  "printed on the cover as 'A guide'",
 "tags": ["Habits", "Psychology"],
 "blurb": "One or two sentences for the shelf.",
 "source": "atomic-habits-guide.html",     "the file in originals/",
 "cover": {"bg": "#f4f5f1", "fg": "#1c2a2e", "line": "#0f766e"},
 "bar":   {"bg": "var(--bg)", "accent": "var(--a)"},
 "emblem": "<svg shapes, 48 x 48, drawn as outlines; empty = the Shelf mark>"
}
```

`cover` is three plain colours: the cloth, the lettering, and the frame and emblem. `bar` holds CSS expressions
evaluated inside the book, so `var(--bg)` follows the book's own dark mode if it has one.

## What a book needs

One HTML file with its styles and scripts inline. The bar is inserted as the first thing in `<body>` inside a
shadow root, so the book's CSS cannot restyle it and it cannot restyle the book. Books that fill the screen with
a flex column (as the first four do) get the bar as a fixed-height first row; a book whose page scrolls gets it
stuck to the top.

## Layout

```
index.html        the shelf (the catalogue is the JSON block at the bottom, written by the tool)
catalog.json      the list of books, hand-editable
books/            what you read: one framed, self-contained file per book
originals/        the files exactly as they arrived
inbox/            drop new books here
tools/shelve.py   the tool (Python standard library only)
```
