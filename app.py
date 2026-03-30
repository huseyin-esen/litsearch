#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║      Academic Literature Scanner — GUI v2.0                 ║
║      Arayüzlü Akademik Dergi Tarama Programı                ║
╚══════════════════════════════════════════════════════════════╝

Çalıştırmak için:
    python app.py

Gereksinimler:
    pip install requests
    (tkinter Python ile birlikte gelir — ayrıca kurulum gerekmez)
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import queue
import requests
import re
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import SENDER_EMAIL, SENDER_PASSWORD, SENDER_NAME


# ══════════════════════════════════════════════════════════════
#  YAYINCI LİSTESİ
# ══════════════════════════════════════════════════════════════

PUBLISHERS = [
    {"name": "ACS Publications",          "short": "ACS",      "doi_prefix": "10.1021", "url": "https://pubs.acs.org/",                    "color": "#1a5276"},
    {"name": "Wiley Online Library",      "short": "Wiley",    "doi_prefix": "10.1002", "url": "https://onlinelibrary.wiley.com/",          "color": "#7d3c98"},
    {"name": "Royal Society of Chemistry","short": "RSC",      "doi_prefix": "10.1039", "url": "https://pubs.rsc.org/",                    "color": "#c0392b"},
    {"name": "ScienceDirect (Elsevier)",  "short": "Elsevier", "doi_prefix": "10.1016", "url": "https://www.sciencedirect.com/",            "color": "#e67e00"},
    {"name": "Springer",                  "short": "Springer", "doi_prefix": "10.1007", "url": "https://link.springer.com/",               "color": "#1e8449"},
    {"name": "Taylor & Francis",          "short": "T&F",      "doi_prefix": "10.1080", "url": "https://taylorandfrancis.com/journals/",   "color": "#154360"},
    {"name": "SAGE Journals",             "short": "SAGE",     "doi_prefix": "10.1177", "url": "https://journals.sagepub.com/",            "color": "#00838f"},
    {"name": "Nature Portfolio",          "short": "Nature",   "doi_prefix": "10.1038", "url": "https://www.nature.com/",                  "color": "#b71c1c"},
    {"name": "Science (AAAS)",            "short": "Science",  "doi_prefix": "10.1126", "url": "https://www.science.org/journals",         "color": "#0277bd"},
    {"name": "Palgrave Macmillan",        "short": "Palgrave", "doi_prefix": "10.1057", "url": "https://www.palgrave.com/journals",        "color": "#4a148c"},
]

DEFAULTS = {
    "keyword_mode": "OR",
    "days_back":    "7",
    "max_results":  "100",
}

# CrossRef type değerleri → görünen etiket
ARTICLE_TYPES = {
    "journal-article": "Research Article",
    "review-article":  "Review",
    "book-chapter":    "Book Section",
}


# ══════════════════════════════════════════════════════════════
#  ARAMA FONKSİYONLARI
# ══════════════════════════════════════════════════════════════

def _clean(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def format_article(article):
    title   = _clean(" ".join(article.get("title", ["Başlık yok"])))
    journal = ", ".join(article.get("container-title", ["Dergi bilinmiyor"]))
    doi     = article.get("DOI", "")
    url     = f"https://doi.org/{doi}" if doi else article.get("URL", "")

    raw_authors = article.get("author", [])
    names = [f"{a.get('given','')} {a.get('family','')}".strip()
             for a in raw_authors[:5] if a.get("family")]
    if len(raw_authors) > 5:
        names.append("et al.")
    authors = ", ".join(names) if names else "Yazar bilinmiyor"

    parts    = article.get("published", {}).get("date-parts", [[]])
    date_str = "-".join(str(p) for p in (parts[0] if parts else []) if p)

    vol, issue, page = article.get("volume",""), article.get("issue",""), article.get("page","")
    citation = ""
    if vol:   citation += f"Vol. {vol}"
    if issue: citation += f", No. {issue}"
    if page:  citation += f", pp. {page}"

    abstract = _clean(article.get("abstract", ""))
    if len(abstract) > 300:
        abstract = abstract[:297] + "…"

    pub         = article.get("_publisher", {})
    article_type= ARTICLE_TYPES.get(article.get("type", ""), "")
    return {
        "title": title, "authors": authors, "journal": journal,
        "date": date_str or "—", "url": url, "doi": doi,
        "citation": citation, "abstract": abstract,
        "article_type": article_type,
        "publisher_color": pub.get("color", "#1a5276"),
    }


def search_publisher(publisher, keywords, days_back, max_results, keyword_mode,
                     contact_email, article_types, log_fn):
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    log_fn(f"  [{publisher['short']}] Aranıyor…")

    params = {
        "query":  " ".join(keywords),
        "filter": f"prefix:{publisher['doi_prefix']},from-pub-date:{start_date}",
        "rows":   max_results,
        "sort":   "published",
        "order":  "desc",
        "select": "DOI,title,author,published,abstract,URL,container-title,volume,issue,page,type",
    }
    headers = {"User-Agent": f"LiteratureScanner/2.0 (mailto:{contact_email})"}

    try:
        r = requests.get("https://api.crossref.org/works",
                         params=params, headers=headers, timeout=30)
        r.raise_for_status()
        items = r.json().get("message", {}).get("items", [])
    except requests.RequestException as e:
        log_fn(f"  HATA [{publisher['short']}]: {e}")
        return []

    for item in items:
        item["_publisher"] = publisher

    # Makale türü filtresi
    if article_types and len(article_types) < len(ARTICLE_TYPES):
        items = [it for it in items if it.get("type") in article_types]

    if keyword_mode == "AND":
        filtered = [
            it for it in items
            if all(kw.lower() in (" ".join(it.get("title",[])) + " " +
                                  it.get("abstract","")).lower()
                   for kw in keywords)
        ]
        log_fn(f"  [{publisher['short']}] {len(filtered)} makale (AND + tür filtresi)")
        return filtered

    log_fn(f"  [{publisher['short']}] {len(items)} makale bulundu")
    return items


# ══════════════════════════════════════════════════════════════
#  E-POSTA FONKSİYONLARI (BREVO API)
# ══════════════════════════════════════════════════════════════

def build_html(articles, cfg, active_pubs):
    keywords  = cfg["keywords"]
    days_back = cfg["days_back"]
    now       = datetime.now().strftime("%d %B %Y")

    kw_badges = "".join(
        f'<span style="background:#1a5276;color:#fff;padding:2px 9px;'
        f'border-radius:12px;font-size:12px;margin-right:4px;">{k.strip()}</span>'
        for k in keywords
    )
    pub_counts = {}
    for art in articles:
        pname = art.get("_publisher", {}).get("name", "Diğer")
        pub_counts[pname] = pub_counts.get(pname, 0) + 1
    pub_summary = " | ".join(
        f"<strong>{n}</strong> {pname}" for pname, n in pub_counts.items()
    ) or "0 makale"

    groups = {}
    for art in articles:
        key = art.get("_publisher", {}).get("name", "Diğer")
        groups.setdefault(key, []).append(art)

    sections = ""
    for pub in active_pubs:
        color        = pub.get("color", "#1a5276")
        pub_articles = groups.get(pub["name"], [])
        rows = ""
        if not pub_articles:
            rows = "<p style='color:#888;font-style:italic;font-size:13px;'>Bu dönem için eşleşen makale bulunamadı.</p>"
        else:
            for i, art in enumerate(pub_articles, 1):
                f = format_article(art)
                abstract_block = (
                    f"<div style='font-size:13px;color:#555;margin-top:6px;'>"
                    f"<em>{f['abstract']}</em></div>"
                    if f["abstract"] else ""
                )
                type_badge = (
                    f'<span style="background:#eaf2ff;color:#1a5276;font-size:11px;'
                    f'padding:1px 7px;border-radius:10px;margin-left:8px;'
                    f'font-weight:normal;">{f["article_type"]}</span>'
                    if f["article_type"] else ""
                )
                rows += f"""
                <div style="background:#f8f9fa;border-left:4px solid {color};
                             margin:12px 0;padding:13px 16px;border-radius:4px;">
                  <div style="font-size:15px;font-weight:bold;color:{color};">
                    {i}. <a href="{f['url']}" style="color:{color};text-decoration:none;"
                            target="_blank">{f['title']}</a>{type_badge}
                  </div>
                  <div style="font-size:13px;color:#555;margin-top:4px;">
                    <strong>Authors:</strong> {f['authors']}
                  </div>
                  <div style="font-size:13px;color:#555;margin-top:2px;">
                    <strong>Journal:</strong> <em>{f['journal']}</em>
                    {('&nbsp;' + f['citation']) if f['citation'] else ''}
                  </div>
                  <div style="font-size:13px;color:#555;margin-top:2px;">
                    <strong>Published:</strong> {f['date']} &nbsp;|&nbsp;
                    <strong>DOI:</strong>
                    <a href="{f['url']}" style="color:#2874a6;">{f['doi']}</a>
                  </div>
                  {abstract_block}
                </div>"""

        sections += f"""
        <h2 style="color:{color};border-bottom:2px solid {color};
                   padding-bottom:6px;margin-top:28px;">
          {pub['name']}
          <span style="font-size:13px;font-weight:normal;color:#777;">
            &nbsp;({len(pub_articles)} makale)
          </span>
          <a href="{pub['url']}" style="font-size:12px;color:{color};
             text-decoration:none;font-weight:normal;float:right;margin-top:4px;">
            {pub['url']} ↗
          </a>
        </h2>
        {rows}"""

    return f"""<!DOCTYPE html>
<html lang="tr">
<head><meta charset="UTF-8"><title>Literature Scan</title></head>
<body style="font-family:Arial,sans-serif;max-width:860px;margin:0 auto;color:#333;">
  <h1 style="color:#1a5276;border-bottom:3px solid #1a5276;padding-bottom:10px;">
    Literature Scan — {len(active_pubs)} Yayıncı
  </h1>
  <p style="color:#555;">Tarama tarihi: {now}</p>
  <div style="background:#eaf2ff;padding:12px 18px;border-radius:5px;
               margin:12px 0;font-size:14px;line-height:1.9;">
    <strong>Anahtar Kelimeler:</strong> {kw_badges}<br>
    <strong>Mod:</strong> {cfg['keyword_mode']}<br>
    <strong>Yayıncılar ({len(active_pubs)}):</strong>
      {'  ·  '.join(p['name'] for p in active_pubs)}<br>
    <strong>Dönem:</strong> Son {days_back} gün<br>
    <strong>Toplam sonuç:</strong> {len(articles)} makale &nbsp;—&nbsp; {pub_summary}
  </div>
  {sections}
  <hr style="margin-top:35px;border:none;border-top:1px solid #ddd;">
  <p style="font-size:11px;color:#aaa;">Academic Literature Scanner v2.0 (CrossRef API)</p>
</body></html>"""


def send_email_smtp(articles, cfg, active_pubs, log_fn):
    recipient = cfg["recipient_email"].strip()
    date_tag  = datetime.now().strftime("%Y-%m-%d")
    n         = len(articles)

    subject = (
        f"Literature Scan [{date_tag}] — {n} makale "
        f"| {len(active_pubs)} yayıncı | {', '.join(cfg['keywords'])}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"]      = recipient
    msg.attach(MIMEText(build_html(articles, cfg, active_pubs), "html", "utf-8"))

    log_fn("\n  Gmail üzerinden e-posta gönderiliyor…")
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, recipient, msg.as_string())
        server.quit()
        log_fn(f"  ✓ E-posta gönderildi → {recipient}")
        return True
    except smtplib.SMTPAuthenticationError:
        log_fn("  HATA: Gmail kimlik doğrulaması başarısız.")
        return False
    except Exception as e:
        log_fn(f"  HATA: {e}")
        return False


# ══════════════════════════════════════════════════════════════
#  ANA ARAYÜZ SINIFI
# ══════════════════════════════════════════════════════════════

class LiteratureScannerApp:

    BG       = "#f4f6f8"
    HEADER   = "#1a5276"
    BTN_RUN  = "#1e8449"
    BTN_STOP = "#7f8c8d"
    FONT     = "Segoe UI" if __import__("sys").platform == "win32" else "Helvetica"

    def __init__(self, root):
        self.root               = root
        self.log_queue          = queue.Queue()
        self.running            = False
        self.pub_vars           = {p["short"]: tk.BooleanVar(value=True) for p in PUBLISHERS}
        self._sched_interval_last = None   # interval modunda son çalışma zamanı
        self._sched_daily_last    = None   # günlük modunda son çalışma tarihi

        self.root.title("Academic Literature Scanner  v2.0")
        self.root.geometry("820x720")
        self.root.minsize(700, 620)
        self.root.configure(bg=self.BG)

        self._build_ui()
        self._poll_log()

    # ── UI ─────────────────────────────────────────────────────

    def _build_ui(self):
        self._header()
        content = tk.Frame(self.root, bg=self.BG, padx=16, pady=10)
        content.pack(fill="both", expand=True)

        top = tk.Frame(content, bg=self.BG)
        top.pack(fill="x")
        self._email_scheduler_section(top)
        self._search_section(top)
        self._publisher_section(content)
        self._action_bar(content)
        self._log_section(content)

    def _header(self):
        hdr = tk.Frame(self.root, bg=self.HEADER, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Academic Literature Scanner",
                 font=(self.FONT, 17, "bold"),
                 bg=self.HEADER, fg="white").pack()
        tk.Label(hdr, text="10 Yayıncı  ·  CrossRef API  ·  E-Posta",
                 font=(self.FONT, 9),
                 bg=self.HEADER, fg="#aed6f1").pack()

    def _email_scheduler_section(self, parent):
        frm = ttk.LabelFrame(parent, text="  E-Posta ve Otomatik Tarama", padding=12)
        frm.pack(side="left", fill="both", expand=True, padx=(0, 8))

        # Alıcı e-posta
        tk.Label(frm, text="Sonuçların gönderileceği e-posta:",
                 font=(self.FONT, 9), anchor="w").pack(fill="x", pady=(0, 4))
        self.v_recipient = tk.StringVar()
        tk.Entry(frm, textvariable=self.v_recipient,
                 font=(self.FONT, 11), relief="solid", bd=1,
                 bg="white").pack(fill="x", ipady=6)

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(12, 8))

        # Otomatik tarama
        self.v_sched_active = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Otomatik taramayı etkinleştir",
                        variable=self.v_sched_active,
                        command=self._scheduler_toggle).pack(anchor="w")

        inner = tk.Frame(frm)
        inner.pack(fill="x", pady=(8, 0))

        self.v_sched_mode = tk.StringVar(value="interval")

        # Seçenek 1: Her N saatte bir
        row1 = tk.Frame(inner)
        row1.pack(fill="x", pady=(0, 4))
        tk.Radiobutton(row1, text="Her", variable=self.v_sched_mode,
                       value="interval", font=(self.FONT, 9),
                       command=self._update_next_run).pack(side="left")
        self.v_interval = tk.StringVar(value="24")
        tk.Spinbox(row1, textvariable=self.v_interval, from_=1, to=168,
                   width=5, font=(self.FONT, 9), relief="solid", bd=1,
                   command=self._update_next_run).pack(side="left", padx=4)
        tk.Label(row1, text="saatte bir", font=(self.FONT, 9)).pack(side="left")

        # Seçenek 2: Her gün belirli saatte
        row2 = tk.Frame(inner)
        row2.pack(fill="x")
        tk.Radiobutton(row2, text="Her gün saat", variable=self.v_sched_mode,
                       value="daily", font=(self.FONT, 9),
                       command=self._update_next_run).pack(side="left")
        self.v_sched_hour = tk.StringVar(value="09")
        self.v_sched_min  = tk.StringVar(value="00")
        tk.Spinbox(row2, textvariable=self.v_sched_hour, from_=0, to=23,
                   width=3, font=(self.FONT, 9), relief="solid", bd=1, format="%02.0f",
                   command=self._update_next_run).pack(side="left", padx=(4, 2))
        tk.Label(row2, text=":", font=(self.FONT, 9, "bold")).pack(side="left")
        tk.Spinbox(row2, textvariable=self.v_sched_min, from_=0, to=59,
                   width=3, font=(self.FONT, 9), relief="solid", bd=1, format="%02.0f",
                   command=self._update_next_run).pack(side="left", padx=(2, 0))

        # Sonraki tarama etiketi
        self.lbl_next_run = tk.Label(frm, text="",
                                     font=(self.FONT, 8, "italic"), fg="#1e8449")
        self.lbl_next_run.pack(anchor="w", pady=(8, 0))

    def _scheduler_toggle(self):
        if self.v_sched_active.get():
            self._sched_interval_last = datetime.now()  # interval hemen tetiklenmesin
            self._sched_daily_last    = None             # günlük bugün tetiklenebilir
            self._update_next_run()
            self._scheduler_tick()
        else:
            self.lbl_next_run.config(text="")

    def _update_next_run(self, *_):
        if not self.v_sched_active.get():
            return
        now  = datetime.now()
        mode = self.v_sched_mode.get()
        if mode == "interval":
            try:   hours = int(self.v_interval.get())
            except ValueError: hours = 24
            base     = self._sched_interval_last or now
            next_run = base + timedelta(hours=hours)
        else:
            try:
                h = int(self.v_sched_hour.get())
                m = int(self.v_sched_min.get())
            except ValueError:
                return
            next_run = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
        self.lbl_next_run.config(
            text=f"Sonraki tarama: {next_run.strftime('%d %b %Y  %H:%M')}")

    def _scheduler_tick(self):
        if not self.v_sched_active.get():
            return
        now  = datetime.now()
        mode = self.v_sched_mode.get()
        fire = False

        if mode == "interval":
            try:   hours = int(self.v_interval.get())
            except ValueError: hours = 24
            elapsed = (now - self._sched_interval_last).total_seconds()
            if elapsed >= hours * 3600:
                fire = True
        else:
            try:
                h = int(self.v_sched_hour.get())
                m = int(self.v_sched_min.get())
            except ValueError:
                pass
            else:
                same_minute = (now.hour == h and now.minute == m)
                not_today   = (self._sched_daily_last != now.date())
                if same_minute and not_today:
                    fire = True

        if fire and not self.running:
            cfg = self._collect_silent()
            if cfg:
                if mode == "interval":
                    self._sched_interval_last = now
                else:
                    self._sched_daily_last = now.date()
                self._update_next_run()
                self._log(f"\n  ⏰ Otomatik tarama — {now.strftime('%d %b %Y  %H:%M')}")
                self._execute_scan(cfg)

        self.root.after(30000, self._scheduler_tick)   # 30 saniyede bir kontrol

    def _search_section(self, parent):
        frm = ttk.LabelFrame(parent, text="  Arama Ayarları", padding=12)
        frm.pack(side="left", fill="both", expand=True)

        tk.Label(frm, text="Anahtar Kelimeler (virgülle ayırın):",
                 font=(self.FONT, 9), anchor="w").pack(fill="x", pady=(0, 1))
        self.v_keywords = tk.StringVar()
        tk.Entry(frm, textvariable=self.v_keywords,
                 font=(self.FONT, 10), relief="solid", bd=1,
                 bg="white").pack(fill="x", ipady=5)

        tk.Label(frm, text="Arama Modu:", font=(self.FONT, 9),
                 anchor="w").pack(fill="x", pady=(12, 2))
        mode_frm = tk.Frame(frm)
        mode_frm.pack(anchor="w")
        self.v_mode = tk.StringVar(value=DEFAULTS["keyword_mode"])
        for text, val in [("OR  — herhangi bir kelime", "OR"),
                           ("AND — tüm kelimeler", "AND")]:
            tk.Radiobutton(mode_frm, text=text, variable=self.v_mode,
                           value=val, font=(self.FONT, 9)).pack(side="left", padx=(0, 14))

        num_row = tk.Frame(frm)
        num_row.pack(fill="x", pady=(12, 0))
        for label, var_name, default in [
            ("Son kaç gün:",          "v_days", DEFAULTS["days_back"]),
            ("Maks sonuç / yayıncı:", "v_max",  DEFAULTS["max_results"]),
        ]:
            cell = tk.Frame(num_row)
            cell.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(cell, text=label, font=(self.FONT, 9)).pack(anchor="w")
            var = tk.StringVar(value=default)
            setattr(self, var_name, var)
            tk.Spinbox(cell, textvariable=var, from_=1, to=500, increment=1,
                       width=8, font=(self.FONT, 10), relief="solid", bd=1,
                       bg="white").pack(anchor="w", ipady=4)

        # Makale türü
        tk.Label(frm, text="Makale Türü:", font=(self.FONT, 9),
                 anchor="w").pack(fill="x", pady=(12, 2))
        type_row = tk.Frame(frm)
        type_row.pack(anchor="w")
        self.type_vars = {}
        labels = {"journal-article": "Research Article",
                  "review-article":  "Review",
                  "book-chapter":    "Book Section"}
        for key, label in labels.items():
            v = tk.BooleanVar(value=True)
            self.type_vars[key] = v
            ttk.Checkbutton(type_row, text=label, variable=v).pack(
                side="left", padx=(0, 12))

    def _publisher_section(self, parent):
        frm = ttk.LabelFrame(parent, text="  Yayıncılar — Taranacakları İşaretleyin",
                              padding=10)
        frm.pack(fill="x", pady=(10, 0))

        cols = 5
        for i, pub in enumerate(PUBLISHERS):
            ttk.Checkbutton(frm, text=pub["short"],
                            variable=self.pub_vars[pub["short"]]).grid(
                row=i // cols, column=i % cols, sticky="w", padx=10, pady=3)

        btn_row = tk.Frame(frm)
        btn_row.grid(row=(len(PUBLISHERS) - 1) // cols + 1,
                     column=0, columnspan=cols, sticky="w", pady=(8, 2))
        for text, cmd, bg in [("Tümünü Seç",    self._sel_all,   "#d5e8d4"),
                               ("Tümünü Kaldır", self._desel_all, "#f8cecc")]:
            tk.Button(btn_row, text=text, command=cmd, relief="flat",
                      bg=bg, font=(self.FONT, 8), padx=8, pady=3,
                      cursor="hand2").pack(side="left", padx=(0, 6))

    def _sel_all(self):
        for v in self.pub_vars.values(): v.set(True)

    def _desel_all(self):
        for v in self.pub_vars.values(): v.set(False)

    def _action_bar(self, parent):
        bar = tk.Frame(parent, bg=self.BG, pady=10)
        bar.pack(fill="x")
        self.btn_start = tk.Button(
            bar, text="▶   TARAMAYI BAŞLAT",
            font=(self.FONT, 12, "bold"),
            bg=self.BTN_RUN, fg="white",
            activebackground="#145a32", activeforeground="white",
            relief="flat", pady=10, cursor="hand2",
            command=self._start_scan
        )
        self.btn_start.pack(fill="x")

    def _log_section(self, parent):
        frm = ttk.LabelFrame(parent, text="  İşlem Kaydı", padding=6)
        frm.pack(fill="both", expand=True, pady=(4, 0))
        self.log_box = scrolledtext.ScrolledText(
            frm, height=8,
            font=("Courier New" if __import__("sys").platform == "win32" else "Courier", 9),
            bg="#1c2333", fg="#a8d8a8",
            insertbackground="white", relief="flat", state="disabled"
        )
        self.log_box.pack(fill="both", expand=True)
        self._log("Hazır.  E-posta adresinizi girin ve 'Taramayı Başlat'a tıklayın.")

    # ── Log ────────────────────────────────────────────────────

    def _log(self, msg):
        self.log_queue.put(msg)

    def _poll_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert("end", msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    # ── Validation & Scan ──────────────────────────────────────

    def _collect_silent(self):
        """_collect gibi ama hata dialog göstermez — zamanlayıcı için."""
        recipient     = self.v_recipient.get().strip()
        kw_raw        = self.v_keywords.get().strip()
        keywords      = [k.strip() for k in kw_raw.split(",") if k.strip()]
        active        = [p for p in PUBLISHERS if self.pub_vars[p["short"]].get()]
        article_types = [k for k, v in self.type_vars.items() if v.get()]
        if not recipient or not keywords or not active or not article_types:
            self._log("  ⚠ Otomatik tarama: eksik bilgi, atlandı.")
            return None
        try:   days = max(1, int(self.v_days.get()))
        except ValueError: days = 7
        try:   maxr = max(1, int(self.v_max.get()))
        except ValueError: maxr = 100
        return {
            "recipient_email": recipient,
            "keywords":        keywords,
            "keyword_mode":    self.v_mode.get(),
            "days_back":       days,
            "max_results":     maxr,
            "active_pubs":     active,
            "article_types":   article_types,
        }

    def _collect(self):
        recipient = self.v_recipient.get().strip()
        kw_raw    = self.v_keywords.get().strip()
        keywords  = [k.strip() for k in kw_raw.split(",") if k.strip()]
        active    = [p for p in PUBLISHERS if self.pub_vars[p["short"]].get()]

        article_types = [k for k, v in self.type_vars.items() if v.get()]

        errors = []
        if not recipient:      errors.append("• Alıcı e-posta boş olamaz.")
        if not keywords:       errors.append("• En az bir anahtar kelime girin.")
        if not active:         errors.append("• En az bir yayıncı seçin.")
        if not article_types:  errors.append("• En az bir makale türü seçin.")

        try:
            days = int(self.v_days.get())
            if days < 1: errors.append("• Gün sayısı en az 1 olmalı.")
        except ValueError:
            errors.append("• Geçerli bir gün sayısı girin.")
            days = 7

        try:
            maxr = int(self.v_max.get())
            if maxr < 1: errors.append("• Maks sonuç en az 1 olmalı.")
        except ValueError:
            errors.append("• Geçerli bir maks sonuç sayısı girin.")
            maxr = 100

        if errors:
            messagebox.showerror("Eksik veya Hatalı Bilgi", "\n".join(errors))
            return None

        return {
            "recipient_email": recipient,
            "keywords":        keywords,
            "keyword_mode":    self.v_mode.get(),
            "days_back":       days,
            "max_results":     maxr,
            "active_pubs":     active,
            "article_types":   article_types,
        }

    def _start_scan(self):
        if self.running:
            return
        cfg = self._collect()
        if not cfg:
            return
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._execute_scan(cfg)

    def _execute_scan(self, cfg):
        self.running = True
        self.btn_start.configure(state="disabled", text="⏳   Taranıyor…",
                                 bg=self.BTN_STOP)
        threading.Thread(target=self._run_scan, args=(cfg,), daemon=True).start()

    def _run_scan(self, cfg):
        try:
            self._log("══════════════════════════════════════════")
            self._log(f"  Tarih     : {datetime.now().strftime('%d %B %Y  %H:%M')}")
            self._log(f"  Keywords  : {', '.join(cfg['keywords'])}  [{cfg['keyword_mode']}]")
            self._log(f"  Dönem     : son {cfg['days_back']} gün")
            self._log(f"  Yayıncılar: {len(cfg['active_pubs'])} seçili")
            self._log("══════════════════════════════════════════")

            all_articles = []
            for pub in cfg["active_pubs"]:
                results = search_publisher(
                    publisher=pub,
                    keywords=cfg["keywords"],
                    days_back=cfg["days_back"],
                    max_results=cfg["max_results"],
                    keyword_mode=cfg["keyword_mode"],
                    contact_email=cfg["recipient_email"],
                    article_types=cfg["article_types"],
                    log_fn=self._log,
                )
                all_articles.extend(results)

            seen, unique = set(), []
            for art in all_articles:
                doi = art.get("DOI", id(art))
                if doi not in seen:
                    seen.add(doi)
                    unique.append(art)

            self._log(f"\n  ── Toplam: {len(unique)} makale bulundu ──")

            success = send_email_smtp(
                articles    = unique,
                cfg         = cfg,
                active_pubs = cfg["active_pubs"],
                log_fn      = self._log,
            )

            self._log("")
            if success:
                self._log(f"  ✓ Bitti!  {cfg['recipient_email']} adresini kontrol edin.")
                self.root.after(0, lambda: messagebox.showinfo(
                    "Tarama Tamamlandı ✓",
                    f"{len(unique)} makale bulundu.\n\n"
                    f"Sonuçlar şu adrese gönderildi:\n{cfg['recipient_email']}"
                ))
            else:
                self._log("  ✗ E-posta gönderilemedi. Yukarıdaki hatalara bakın.")

        except Exception as e:
            self._log(f"\n  Beklenmeyen hata: {e}")
        finally:
            self.running = False
            self.root.after(0, lambda: self.btn_start.configure(
                state="normal",
                text="▶   TARAMAYI BAŞLAT",
                bg=self.BTN_RUN
            ))


# ══════════════════════════════════════════════════════════════
#  BAŞLANGIÇ NOKTASI
# ══════════════════════════════════════════════════════════════

def main():
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.2)
    except Exception:
        pass
    app = LiteratureScannerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
