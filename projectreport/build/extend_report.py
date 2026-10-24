"""Extend the author's edited report to 50 A4 pages and restore its page borders.

The input is the author's edited copy of SecuLayer_Project_Report.docx (by default
build/out/edited.docx, git-ignored; read only). Google Docs drops page borders, section
page-number formats and page breaks on export, so this script puts them back: a thick dark
double border on the cover, a thin grey border on every other page, lower-case roman numbers
for the front matter, and the Contents and Abstract each on a new page. It then adds the
wording in extend_content.py, six restored rows of Table 6.3 and two appendices (offline
screening tables and full-size screenshots), sizes the figures so that no page ends with an
empty band, and rebuilds the page numbers of the contents and the lists of figures and tables
from a LibreOffice render (two passes).

  uv run --no-project --with python-docx --with pillow \
      python projectreport/build/extend_report.py [edited.docx]
"""
from __future__ import annotations

import copy
import re
import shutil
import sys
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.shared import Inches

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import extend_content as X  # noqa: E402
from content_ch6_8 import _screen_rows  # noqa: E402
from finalize_report import (  # noqa: E402
    border, format_table, label, page_texts, ppr_of, pprop, render, rewrite, size_image, text_of, w,
)

ROOT = HERE.parent
SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / 'out' / 'edited.docx'
WORK = HERE / 'out' / 'extend'
TARGET = ROOT / 'SecuLayer_Project_Report.docx'
PDF = ROOT / 'SecuLayer_Project_Report.pdf'
FIGS = ROOT / 'figures'
TEXT_W = 9026  # A4 width less two 1-inch margins, in twentieths of a point

# Figure heights in inches, tuned so that each page ends within a line of its bottom margin.
FIGURE_H = {'Figure 4.1:': 3.2, 'Figure 4.2:': 2.6, 'Figure 4.3:': 2.3, 'Figure 4.4:': 2.8,
            'Figure 4.9:': 2.6, 'Figure 7.1:': 1.95}
FIGURE_C_H = (7.9, 8.9)
# Rows of Table 6.3 restored from the long draft (by the first words of their test column).
TEST_ROWS = {'Tag characters decoded'}
# Appendix B tables: font size in points and cell padding (before and after) in twentieths of a point.
TABLE_B_PT, TABLE_B_PAD = 9.5, 60


# ---------------------------------------------------------------- finding and making paragraphs

def body_items(body):
    return [el for el in body.iterchildren() if el.tag in (w('p'), w('tbl'))]


def find(body, prefix, tag='p', exact=False, front=False):
    """The one paragraph whose text starts with (or equals) prefix; outside the front matter unless front."""
    kids = list(body.iterchildren())
    if not front:
        kids = kids[next(i for i, el in enumerate(kids) if text_of(el).strip() == 'Chapter 1: Introduction'):]
    hits = [el for el in kids if el.tag == w(tag) and
            (text_of(el).strip() == prefix if exact else text_of(el).strip().startswith(prefix))]
    assert len(hits) == 1, (prefix, len(hits))
    return hits[0]


def next_table(el):
    nxt = el.getnext()
    while nxt is not None and nxt.tag != w('tbl'):
        nxt = nxt.getnext()
    return nxt


def set_text(p, text):
    """Replace a paragraph's text, keeping the formatting of its first text run."""
    runs = [r for r in p.findall(w('r')) if r.find(w('t')) is not None]
    first = runs[0]
    for r in p.findall(w('r')):
        if r is not first:
            p.remove(r)
    for t in first.findall(w('t'))[1:]:
        first.remove(t)
    for tab in first.findall(w('tab')):
        first.remove(tab)
    first.find(w('t')).text = text
    first.find(w('t')).set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    return first


def two_sided(p, left, right):
    """'left<right tab>right' on one line, like the signature lines of the certificate."""
    r = set_text(p, left)
    tab = OxmlElement('w:tab')
    r.append(tab)
    t = copy.deepcopy(r.find(w('t')))
    t.text = right
    r.append(t)
    tabs = pprop(ppr_of(p), 'tabs')
    for old in list(tabs):
        tabs.remove(old)
    stop = OxmlElement('w:tab')
    stop.set(w('val'), 'right')
    stop.set(w('pos'), str(TEXT_W))
    tabs.append(stop)


def set_caption(p, label_text, rest):
    runs = [r for r in p.findall(w('r')) if r.find(w('t')) is not None]
    runs[0].find(w('t')).text = label_text + ': '
    runs[1].find(w('t')).text = rest
    for r in runs[2:]:
        p.remove(r)


def set_cell(tc, text):
    paras = tc.findall(w('p'))
    for extra in paras[1:]:
        tc.remove(extra)
    set_text(paras[0], text)


def set_row(tr, values):
    for tc, value in zip(tr.findall(w('tc')), values):
        set_cell(tc, value)


# ---------------------------------------------------------------- sections and front matter

def sect_fix(sectpr, dark, fmt, start=None):
    for old in sectpr.findall(w('pgBorders')) + sectpr.findall(w('pgNumType')):
        sectpr.remove(old)
    sectpr.find(w('pgMar')).set(w('gutter'), '0')
    sectpr.find(w('pgMar')).addnext(border('000000', 24, 'thinThickSmallGap') if dark else border('8C8C8C', 8))
    num = OxmlElement('w:pgNumType')
    num.set(w('fmt'), fmt)
    if start is not None:
        num.set(w('start'), str(start))
    sectpr.find(w('pgBorders')).addnext(num)


def fix_sections(body):
    sects = [s for s in body.iter(w('sectPr'))]
    assert len(sects) == 4, len(sects)
    cover, cert, front, chapters = sects
    sect_fix(cover, True, 'lowerRoman', 1)
    sect_fix(cert, False, 'lowerRoman')
    sect_fix(front, False, 'lowerRoman')
    sect_fix(chapters, False, 'decimal', 1)


# ---------------------------------------------------------------- the build

def lists(body):
    """Entry paragraphs of the contents, the list of figures and the list of tables."""
    kids = list(body.iterchildren())
    idx = {text_of(el).strip(): i for i, el in enumerate(kids) if el.tag == w('p')}
    toc = kids[idx['Contents'] + 1:idx['Abstract']]
    lof = kids[idx['List of Figures'] + 1:idx['List of Tables']]
    lot = kids[idx['List of Tables'] + 1:idx['Chapter 1: Introduction']]
    keep = lambda ps: [p for p in ps if p.tag == w('p') and any(t.getparent().tag == w('r') for t in p.iter(w('tab')))]  # noqa: E731
    return keep(toc), keep(lof), keep(lot)


def entry_title(p):
    ts = [t.text or '' for t in p.iter(w('t'))]
    return ts[0].strip()


def clone_entry(after, title):
    p = copy.deepcopy(after)
    ppr = p.find(w('pPr'))
    if ppr is not None and ppr.find(w('sectPr')) is not None:
        ppr.remove(ppr.find(w('sectPr')))
    p.iter(w('t')).__next__().text = title
    after.addnext(p)
    return p


def build(pages):
    doc = Document(SOURCE)
    body = doc.element.body

    fix_sections(body)
    # Accept the one tracked formatting change (LibreOffice draws change bars on the cover).
    for tag in ('pPrChange', 'rPrChange'):
        for el in list(body.iter(w(tag))):
            el.getparent().remove(el)
    # The empty paragraph between the two lists pushed the list of tables onto a page of its own.
    lt = find(body, 'List of Tables', exact=True, front=True)
    if lt.getprevious().tag == w('p') and not text_of(lt.getprevious()).strip():
        body.remove(lt.getprevious())
    for title in ('Contents', 'Abstract'):
        pprop(ppr_of(find(body, title, exact=True, front=True)), 'pageBreakBefore', val=1)

    # Acknowledgement signatures: one name or roll number on each side of the line.
    sigs = [p for p in body.iterchildren(w('p')) if re.match(r'\S.*\S {3,}\S', text_of(p))]
    names = [re.split(r' {3,}', text_of(p).strip()) for p in sigs]
    rolls = {'Akash Chaudhari': '202301128055', 'Somesh Padsalge': '202301128057',
             'Abhay Kale': '202401128704', 'Ayush Shinde': '202301128023'}
    for i, (p, parts) in enumerate(zip(sigs, names)):
        if parts[0] in rolls:
            two_sided(p, *parts)
            two_sided(sigs[i + 1], rolls[parts[0]], rolls[parts[1]])

    for prefix, markup in X.REWRITE.items():
        rewrite(find(body, prefix), markup)

    para_tpl = find(body, 'Large language models (LLMs) now power')
    bullet_tpl = find(body, 'Public deployment, user accounts')
    for prefix, kind, markup in X.INSERT:
        anchor = find(body, prefix)
        if prefix.startswith(('Table ', 'Figure ')):
            anchor = next_table(anchor)
        new = copy.deepcopy({'p': para_tpl, 'bullet': bullet_tpl}[kind])
        rewrite(new, markup)
        anchor.addnext(new)

    code_tpl = copy.deepcopy(find(body, '$ env -u OPENAI_API_KEY'))
    anchor = find(body, 'The source code, data, recordings and tests are at')
    for line in X.COMMANDS:
        new = copy.deepcopy(code_tpl)
        set_text(new, line)
        anchor.addnext(new)
        anchor = new

    # Table 6.3: restore six representative cases and renumber.
    tc_table = next_table(find(body, 'Table 6.3:'))
    old_ids = {text_of(tr.findall(w('tc'))[1]): text_of(tr.findall(w('tc'))[0])
               for tr in tc_table.findall(w('tr'))[1:]}
    for after, values in [r for r in X.TEST_ROWS if r[1][0].split(' (')[0] in TEST_ROWS]:
        row = next(tr for tr in tc_table.findall(w('tr')) if after in text_of(tr))
        new = copy.deepcopy(row)
        set_row(new, ['TC-00'] + values)
        row.addnext(new)
    renumber = {}
    for n, tr in enumerate(tc_table.findall(w('tr'))[1:], 1):
        cells = tr.findall(w('tc'))
        new_id = 'TC-%02d' % n
        old = old_ids.get(text_of(cells[1]))
        if old:
            renumber[old] = new_id
        set_cell(cells[0], new_id)
    for p in body.iterchildren(w('p')):
        for t in p.iter(w('t')):
            if t.text and 'TC-' in t.text:
                t.text = re.sub(r'TC-\d\d', lambda m: renumber.get(m.group(0), m.group(0)), t.text)

    # Figures sized so that pages end full.
    for prefix, height in FIGURE_H.items():
        size_image(find(body, prefix).getprevious(), height)

    # Appendices B (data tables) and C (screenshots).
    last_table = next_table(find(body, 'Table A.1:'))
    heading_tpl = find(body, 'Appendix A: Source Code', exact=True)
    caption_tpl = find(body, 'Table A.1:')
    fig_caption_tpl = find(body, 'Figure 4.1:')
    img_tpl = fig_caption_tpl.getprevious()
    # An empty paragraph after the last table spilled onto a blank page.
    while last_table.getnext() is not None and last_table.getnext().tag == w('p') and \
            not text_of(last_table.getnext()).strip() and last_table.getnext().find('.//' + w('sectPr')) is None:
        body.remove(last_table.getnext())
    spacer = None

    def heading(title):
        h = copy.deepcopy(heading_tpl)
        set_text(h, title)
        pprop(ppr_of(h), 'pageBreakBefore', val=1)
        pprop(ppr_of(h), 'spacing', before=0)
        return h

    def paragraph(markup):
        p = copy.deepcopy(para_tpl)
        rewrite(p, markup)
        return p

    def caption(tpl, text):
        c = copy.deepcopy(tpl)
        lab, _, rest = text.partition(': ')
        set_caption(c, lab, rest)
        return c

    def table(rows):
        t = copy.deepcopy(tc_table)
        trs = t.findall(w('tr'))
        for tr in trs[2:]:
            t.remove(tr)
        set_row(trs[0], ['Case', 'Rules matched', 'Classifier', 'Cleaner on', 'Cleaner off'])
        trpr = trs[0].find(w('trPr'))
        if trpr is None:
            trpr = OxmlElement('w:trPr')
            trs[0].insert(0, trpr)
        if trpr.find(w('tblHeader')) is None:
            trpr.append(OxmlElement('w:tblHeader'))
        tpl = trs[1]
        t.remove(tpl)
        for values in rows:
            tr = copy.deepcopy(tpl)
            set_row(tr, values)
            t.append(tr)
        format_table(t, [0.34, 0.27, 0.11, 0.14, 0.14], TABLE_B_PT)
        for p in t.iter(w('p')):
            pprop(ppr_of(p), 'spacing', before=TABLE_B_PAD, after=TABLE_B_PAD)
        return t

    def figure(file, height):
        p = doc.add_paragraph()
        p.add_run().add_picture(str(FIGS / file), height=Inches(height))
        el = p._p
        el.remove(el.find(w('pPr'))) if el.find(w('pPr')) is not None else None
        el.insert(0, copy.deepcopy(img_tpl.find(w('pPr'))))
        size_image(el, height)
        return el

    new = [heading(X.APPENDIX_B_TITLE), paragraph(X.APPENDIX_B_TEXT),
           caption(caption_tpl, X.TABLE_B1), table(_screen_rows('attack'))]
    if spacer is not None:
        new.append(copy.deepcopy(spacer))
    new += [caption(caption_tpl, X.TABLE_B2), table(_screen_rows('normal')),
            heading(X.APPENDIX_C_TITLE), paragraph(X.APPENDIX_C_TEXT),
            figure(X.FIGURE_C1[0], FIGURE_C_H[0]), caption(fig_caption_tpl, X.FIGURE_C1[1]),
            figure(X.FIGURE_C2[0], FIGURE_C_H[1]), caption(fig_caption_tpl, X.FIGURE_C2[1])]
    anchor = last_table if spacer is None else last_table.getnext()
    for el in new:
        anchor.addnext(el)
        anchor = el

    # Contents and lists: new entries, dot leaders and page numbers.
    toc, lof, lot = lists(body)
    a = next(p for p in toc if entry_title(p).startswith('Appendix A'))
    b = clone_entry(a, X.APPENDIX_B_TITLE)
    clone_entry(b, X.APPENDIX_C_TITLE)
    f = clone_entry(lof[-1], X.FIGURE_C1[1].rstrip('.'))
    clone_entry(f, X.FIGURE_C2[1].rstrip('.'))
    sect = lot[-1].find(w('pPr')).find(w('sectPr'))
    t1 = clone_entry(lot[-1], X.TABLE_B1)
    t2 = clone_entry(t1, X.TABLE_B2)
    lot[-1].find(w('pPr')).remove(sect)
    t2.find(w('pPr')).append(sect)

    toc, lof, lot = lists(body)
    for p in lof + lot:
        pprop(ppr_of(p), 'spacing', after=2)
    for p in toc + lof + lot:
        for tab in p.iter(w('tab')):
            if tab.get(w('val')) == 'right':
                tab.set(w('leader'), 'dot')
        title = entry_title(p)
        key = title.split(':')[0] + ':' if p in lof + lot else title
        p_ts = list(p.iter(w('t')))
        p_ts[-1].text = pages.get(key, '00')

    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / 'SecuLayer_Project_Report.docx'
    doc.save(out)
    return out, [entry_title(p) for p in toc]


def locate(pdf, toc_titles):
    texts = page_texts(pdf)
    labels = [label(t) for t in texts]
    body_start = next(i for i, t in enumerate(texts)
                      if re.search(r'^\s*Chapter 1: Introduction\s*$', t, re.M) and labels[i] == '1')
    pages = {}
    contents_page = next(i for i, t in enumerate(texts) if re.search(r'^\s*Contents\s*$', t, re.M))
    cursor = 1
    for title in toc_titles:
        pat = re.compile(r'^\s*%s\s*$' % re.escape(title), re.M)
        lo = body_start if title.startswith(('Chapter', 'References', 'Appendix')) or re.match(r'\d', title) else 1
        for i in range(max(cursor, lo), len(texts)):
            if i == contents_page:
                continue
            if pat.search(texts[i]):
                pages[title] = labels[i]
                cursor = i
                break
        else:
            print('heading not found:', title)
    for i in range(body_start, len(texts)):
        for m in re.finditer(r'((?:Figure|Table) [0-9A-C]+\.\d+:)', texts[i]):
            pages.setdefault(m.group(1), labels[i])
    return pages, len(texts)


def main():
    out, toc = build({})
    pdf = render(out)
    pages, n = locate(pdf, toc)
    out, toc = build(pages)
    pdf = render(out)
    pages2, n2 = locate(pdf, toc)
    if pages2 != pages:
        print('page numbers moved after filling the lists:',
              {k: (pages.get(k), v) for k, v in pages2.items() if pages.get(k) != v})
    shutil.copyfile(out, TARGET)
    shutil.copyfile(pdf, PDF)
    print(f'{n2} pages -> {TARGET.name}, {PDF.name}')


if __name__ == '__main__':
    main()
