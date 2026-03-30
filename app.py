#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║      Academic Literature Scanner — GUI v3.0                 ║
║      Çoklu Profil · Zamanlayıcı · CrossRef API              ║
╚══════════════════════════════════════════════════════════════╝
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
import threading
import queue
import requests
import re
import json
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import SENDER_EMAIL, SENDER_PASSWORD, SENDER_NAME

PROFILES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles.json")

# ══════════════════════════════════════════════════════════════
#  SABİTLER
# ══════════════════════════════════════════════════════════════

PUBLISHERS = [
    {"name": "ACS Publications",          "short": "ACS",      "doi_prefix": "10.1021", "url": "https://pubs.acs.org/",                  "color": "#1a5276"},
    {"name": "Wiley Online Library",      "short": "Wiley",    "doi_prefix": "10.1002", "url": "https://onlinelibrary.wiley.com/",        "color": "#7d3c98"},
    {"name": "Royal Society of Chemistry","short": "RSC",      "doi_prefix": "10.1039", "url": "https://pubs.rsc.org/",                  "color": "#c0392b"},
    {"name": "ScienceDirect (Elsevier)",  "short": "Elsevier", "doi_prefix": "10.1016", "url": "https://www.sciencedirect.com/",          "color": "#e67e00"},
    {"name": "Springer",                  "short": "Springer", "doi_prefix": "10.1007", "url": "https://link.springer.com/",             "color": "#1e8449"},
    {"name": "Taylor & Francis",          "short": "T&F",      "doi_prefix": "10.1080", "url": "https://taylorandfrancis.com/journals/", "color": "#154360"},
    {"name": "SAGE Journals",             "short": "SAGE",     "doi_prefix": "10.1177", "url": "https://journals.sagepub.com/",          "color": "#00838f"},
    {"name": "Nature Portfolio",          "short": "Nature",   "doi_prefix": "10.1038", "url": "https://www.nature.com/",                "color": "#b71c1c"},
    {"name": "Science (AAAS)",            "short": "Science",  "doi_prefix": "10.1126", "url": "https://www.science.org/journals",       "color": "#0277bd"},
    {"name": "Palgrave Macmillan",        "short": "Palgrave", "doi_prefix": "10.1057", "url": "https://www.palgrave.com/journals",      "color": "#4a148c"},
]

ARTICLE_TYPES = {
    "journal-article": "Research Article",
    "review-article":  "Review",
    "book-chapter":    "Book Section",
}

FONT = "Segoe UI" if __import__("sys").platform == "win32" else "Helvetica"


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

    pub          = article.get("_publisher", {})
    article_type = ARTICLE_TYPES.get(article.get("type", ""), "")
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
        "rows":   max_results, "sort": "published", "order": "desc",
        "select": "DOI,title,author,published,abstract,URL,container-title,volume,issue,page,type",
    }
    headers = {"User-Agent": f"LiteratureScanner/3.0 (mailto:{contact_email})"}
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
    if article_types and len(article_types) < len(ARTICLE_TYPES):
        items = [it for it in items if it.get("type") in article_types]
    if keyword_mode == "AND":
        items = [it for it in items
                 if all(kw.lower() in (" ".join(it.get("title",[])) + " " +
                                       it.get("abstract","")).lower()
                        for kw in keywords)]
    log_fn(f"  [{publisher['short']}] {len(items)} makale bulundu")
    return items


def build_html(articles, cfg, active_pubs):
    now = datetime.now().strftime("%d %B %Y")
    kw_badges = "".join(
        f'<span style="background:#1a5276;color:#fff;padding:2px 9px;'
        f'border-radius:12px;font-size:12px;margin-right:4px;">{k.strip()}</span>'
        for k in cfg["keywords"]
    )
    pub_counts = {}
    for art in articles:
        pname = art.get("_publisher", {}).get("name", "Diğer")
        pub_counts[pname] = pub_counts.get(pname, 0) + 1
    pub_summary = " | ".join(f"<strong>{n}</strong> {p}" for p, n in pub_counts.items()) or "0 makale"
    groups = {}
    for art in articles:
        groups.setdefault(art.get("_publisher", {}).get("name", "Diğer"), []).append(art)
    sections = ""
    for pub in active_pubs:
        color = pub.get("color", "#1a5276")
        pub_articles = groups.get(pub["name"], [])
        rows = "<p style='color:#888;font-style:italic;font-size:13px;'>Bu dönem için eşleşen makale bulunamadı.</p>"
        if pub_articles:
            rows = ""
            for i, art in enumerate(pub_articles, 1):
                f = format_article(art)
                abstract_block = (f"<div style='font-size:13px;color:#555;margin-top:6px;'><em>{f['abstract']}</em></div>" if f["abstract"] else "")
                type_badge = (f'<span style="background:#eaf2ff;color:#1a5276;font-size:11px;padding:1px 7px;border-radius:10px;margin-left:8px;font-weight:normal;">{f["article_type"]}</span>' if f["article_type"] else "")
                rows += f"""<div style="background:#f8f9fa;border-left:4px solid {color};margin:12px 0;padding:13px 16px;border-radius:4px;">
  <div style="font-size:15px;font-weight:bold;color:{color};">{i}. <a href="{f['url']}" style="color:{color};text-decoration:none;" target="_blank">{f['title']}</a>{type_badge}</div>
  <div style="font-size:13px;color:#555;margin-top:4px;"><strong>Authors:</strong> {f['authors']}</div>
  <div style="font-size:13px;color:#555;margin-top:2px;"><strong>Journal:</strong> <em>{f['journal']}</em> {('&nbsp;' + f['citation']) if f['citation'] else ''}</div>
  <div style="font-size:13px;color:#555;margin-top:2px;"><strong>Published:</strong> {f['date']} &nbsp;|&nbsp; <strong>DOI:</strong> <a href="{f['url']}" style="color:#2874a6;">{f['doi']}</a></div>
  {abstract_block}</div>"""
        sections += f"""<h2 style="color:{color};border-bottom:2px solid {color};padding-bottom:6px;margin-top:28px;">{pub['name']} <span style="font-size:13px;font-weight:normal;color:#777;">&nbsp;({len(pub_articles)} makale)</span><a href="{pub['url']}" style="font-size:12px;color:{color};text-decoration:none;font-weight:normal;float:right;margin-top:4px;">{pub['url']} ↗</a></h2>{rows}"""
    return f"""<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8"><title>Literature Scan</title></head>
<body style="font-family:Arial,sans-serif;max-width:860px;margin:0 auto;color:#333;">
<h1 style="color:#1a5276;border-bottom:3px solid #1a5276;padding-bottom:10px;">Literature Scan — {cfg.get('profile_name','')}</h1>
<p style="color:#555;">Tarama tarihi: {now}</p>
<div style="background:#eaf2ff;padding:12px 18px;border-radius:5px;margin:12px 0;font-size:14px;line-height:1.9;">
<strong>Anahtar Kelimeler:</strong> {kw_badges}<br>
<strong>Mod:</strong> {cfg['keyword_mode']}<br>
<strong>Yayıncılar ({len(active_pubs)}):</strong> {'  ·  '.join(p['name'] for p in active_pubs)}<br>
<strong>Dönem:</strong> Son {cfg['days_back']} gün<br>
<strong>Toplam sonuç:</strong> {len(articles)} makale &nbsp;—&nbsp; {pub_summary}
</div>{sections}
<hr style="margin-top:35px;border:none;border-top:1px solid #ddd;">
<p style="font-size:11px;color:#aaa;">Academic Literature Scanner v3.0 (CrossRef API)</p>
</body></html>"""


def send_email_smtp(articles, cfg, active_pubs, log_fn):
    recipient = cfg["recipient_email"].strip()
    date_tag  = datetime.now().strftime("%Y-%m-%d")
    subject   = (f"Literature Scan [{date_tag}] — {len(articles)} makale "
                 f"| {cfg.get('profile_name','')} | {', '.join(cfg['keywords'])}")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"]      = recipient
    msg.attach(MIMEText(build_html(articles, cfg, active_pubs), "html", "utf-8"))
    log_fn("\n  Gmail üzerinden e-posta gönderiliyor…")
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
        server.ehlo(); server.starttls(); server.ehlo()
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
#  PROFİL FRAME — her sekme için bağımsız ayarlar
# ══════════════════════════════════════════════════════════════

class ProfileFrame(tk.Frame):

    BG       = "#f4f6f8"
    BTN_RUN  = "#1e8449"
    BTN_STOP = "#7f8c8d"

    def __init__(self, parent, name, log_fn, data=None):
        super().__init__(parent, bg=self.BG)
        self.log_fn  = log_fn
        self.running = False
        self._sched_interval_last = None
        self._sched_daily_last    = None

        d = data or {}
        self.v_name      = tk.StringVar(value=name)
        self.v_recipient = tk.StringVar(value=d.get("recipient", ""))
        self.v_keywords  = tk.StringVar(value=d.get("keywords", ""))
        self.v_mode      = tk.StringVar(value=d.get("keyword_mode", "OR"))
        self.v_days      = tk.StringVar(value=str(d.get("days_back", 7)))
        self.v_max       = tk.StringVar(value=str(d.get("max_results", 100)))
        self.pub_vars    = {p["short"]: tk.BooleanVar(value=p["short"] in d.get("publishers", [pub["short"] for pub in PUBLISHERS]))
                            for p in PUBLISHERS}
        self.type_vars   = {k: tk.BooleanVar(value=k in d.get("article_types", list(ARTICLE_TYPES.keys())))
                            for k in ARTICLE_TYPES}
        self.v_sched_active = tk.BooleanVar(value=d.get("sched_active", False))
        self.v_sched_mode   = tk.StringVar(value=d.get("sched_mode", "interval"))
        self.v_interval     = tk.StringVar(value=str(d.get("sched_interval", 24)))
        self.v_sched_hour   = tk.StringVar(value=d.get("sched_hour", "09"))
        self.v_sched_min    = tk.StringVar(value=d.get("sched_min", "00"))

        self._build()

        if self.v_sched_active.get():
            self._sched_interval_last = datetime.now()
            self._sched_daily_last    = None
            self._update_next_run()
            self.after(1000, self._scheduler_tick)

    # ── UI ─────────────────────────────────────────────────────

    def _build(self):
        top = tk.Frame(self, bg=self.BG, padx=12, pady=8)
        top.pack(fill="x")
        self._email_scheduler_section(top)
        self._search_section(top)
        self._publisher_section(self)
        self._action_bar(self)

    def _email_scheduler_section(self, parent):
        frm = ttk.LabelFrame(parent, text="  E-Posta ve Otomatik Tarama", padding=12)
        frm.pack(side="left", fill="both", expand=True, padx=(0, 8))

        tk.Label(frm, text="Sonuçların gönderileceği e-posta:",
                 font=(FONT, 9), anchor="w").pack(fill="x", pady=(0, 4))
        tk.Entry(frm, textvariable=self.v_recipient,
                 font=(FONT, 11), relief="solid", bd=1, bg="white").pack(fill="x", ipady=6)

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=(10, 8))

        ttk.Checkbutton(frm, text="Otomatik taramayı etkinleştir",
                        variable=self.v_sched_active,
                        command=self._scheduler_toggle).pack(anchor="w")

        inner = tk.Frame(frm, bg=self.BG)
        inner.pack(fill="x", pady=(8, 0))

        row1 = tk.Frame(inner, bg=self.BG)
        row1.pack(fill="x", pady=(0, 4))
        tk.Radiobutton(row1, text="Her", variable=self.v_sched_mode,
                       value="interval", font=(FONT, 9), bg=self.BG,
                       command=self._update_next_run).pack(side="left")
        tk.Spinbox(row1, textvariable=self.v_interval, from_=1, to=168, width=5,
                   font=(FONT, 9), relief="solid", bd=1,
                   command=self._update_next_run).pack(side="left", padx=4)
        tk.Label(row1, text="saatte bir", font=(FONT, 9), bg=self.BG).pack(side="left")

        row2 = tk.Frame(inner, bg=self.BG)
        row2.pack(fill="x")
        tk.Radiobutton(row2, text="Her gün saat", variable=self.v_sched_mode,
                       value="daily", font=(FONT, 9), bg=self.BG,
                       command=self._update_next_run).pack(side="left")
        tk.Spinbox(row2, textvariable=self.v_sched_hour, from_=0, to=23, width=3,
                   font=(FONT, 9), relief="solid", bd=1, format="%02.0f",
                   command=self._update_next_run).pack(side="left", padx=(4, 2))
        tk.Label(row2, text=":", font=(FONT, 9, "bold"), bg=self.BG).pack(side="left")
        tk.Spinbox(row2, textvariable=self.v_sched_min, from_=0, to=59, width=3,
                   font=(FONT, 9), relief="solid", bd=1, format="%02.0f",
                   command=self._update_next_run).pack(side="left", padx=(2, 0))

        self.lbl_next_run = tk.Label(frm, text="", font=(FONT, 8, "italic"),
                                     fg="#1e8449", bg=self.BG)
        self.lbl_next_run.pack(anchor="w", pady=(8, 0))

    def _search_section(self, parent):
        frm = ttk.LabelFrame(parent, text="  Arama Ayarları", padding=12)
        frm.pack(side="left", fill="both", expand=True)

        tk.Label(frm, text="Anahtar Kelimeler (virgülle ayırın):",
                 font=(FONT, 9), anchor="w").pack(fill="x", pady=(0, 1))
        tk.Entry(frm, textvariable=self.v_keywords,
                 font=(FONT, 10), relief="solid", bd=1, bg="white").pack(fill="x", ipady=5)

        tk.Label(frm, text="Arama Modu:", font=(FONT, 9),
                 anchor="w").pack(fill="x", pady=(10, 2))
        mode_frm = tk.Frame(frm)
        mode_frm.pack(anchor="w")
        for text, val in [("OR  — herhangi", "OR"), ("AND — tümü", "AND")]:
            tk.Radiobutton(mode_frm, text=text, variable=self.v_mode,
                           value=val, font=(FONT, 9)).pack(side="left", padx=(0, 10))

        num_row = tk.Frame(frm)
        num_row.pack(fill="x", pady=(10, 0))
        for label, var, side in [("Son kaç gün:", self.v_days, "left"),
                                  ("Maks sonuç:", self.v_max, "left")]:
            cell = tk.Frame(num_row)
            cell.pack(side=side, fill="x", expand=True, padx=(0, 6))
            tk.Label(cell, text=label, font=(FONT, 9)).pack(anchor="w")
            tk.Spinbox(cell, textvariable=var, from_=1, to=500, width=7,
                       font=(FONT, 10), relief="solid", bd=1, bg="white").pack(anchor="w", ipady=4)

        tk.Label(frm, text="Makale Türü:", font=(FONT, 9),
                 anchor="w").pack(fill="x", pady=(10, 2))
        type_row = tk.Frame(frm)
        type_row.pack(anchor="w")
        for key, label in ARTICLE_TYPES.items():
            ttk.Checkbutton(type_row, text=label,
                            variable=self.type_vars[key]).pack(side="left", padx=(0, 10))

    def _publisher_section(self, parent):
        frm = ttk.LabelFrame(parent, text="  Yayıncılar", padding=8)
        frm.pack(fill="x", padx=12, pady=(0, 4))
        cols = 5
        for i, pub in enumerate(PUBLISHERS):
            ttk.Checkbutton(frm, text=pub["short"],
                            variable=self.pub_vars[pub["short"]]).grid(
                row=i // cols, column=i % cols, sticky="w", padx=8, pady=2)
        btn_row = tk.Frame(frm)
        btn_row.grid(row=(len(PUBLISHERS)-1)//cols+1, column=0,
                     columnspan=cols, sticky="w", pady=(6, 2))
        tk.Button(btn_row, text="Tümünü Seç", command=self._sel_all,
                  relief="flat", bg="#d5e8d4", font=(FONT, 8),
                  padx=8, pady=2, cursor="hand2").pack(side="left", padx=(0, 4))
        tk.Button(btn_row, text="Tümünü Kaldır", command=self._desel_all,
                  relief="flat", bg="#f8cecc", font=(FONT, 8),
                  padx=8, pady=2, cursor="hand2").pack(side="left")

    def _action_bar(self, parent):
        bar = tk.Frame(parent, bg=self.BG, padx=12, pady=6)
        bar.pack(fill="x")
        self.btn_start = tk.Button(
            bar, text="▶   TARAMAYI BAŞLAT",
            font=(FONT, 11, "bold"), bg=self.BTN_RUN, fg="white",
            activebackground="#145a32", activeforeground="white",
            relief="flat", pady=8, cursor="hand2", command=self._start_scan)
        self.btn_start.pack(fill="x")

    def _sel_all(self):
        for v in self.pub_vars.values(): v.set(True)

    def _desel_all(self):
        for v in self.pub_vars.values(): v.set(False)

    # ── Scheduler ──────────────────────────────────────────────

    def _scheduler_toggle(self):
        if self.v_sched_active.get():
            self._sched_interval_last = datetime.now()
            self._sched_daily_last    = None
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
            text=f"Sonraki: {next_run.strftime('%d %b %Y  %H:%M')}")

    def _scheduler_tick(self):
        if not self.v_sched_active.get():
            return
        now  = datetime.now()
        mode = self.v_sched_mode.get()
        fire = False
        if mode == "interval":
            try:   hours = int(self.v_interval.get())
            except ValueError: hours = 24
            if (now - (self._sched_interval_last or now)).total_seconds() >= hours * 3600:
                fire = True
        else:
            try:
                h, m = int(self.v_sched_hour.get()), int(self.v_sched_min.get())
            except ValueError:
                pass
            else:
                if now.hour == h and now.minute == m and self._sched_daily_last != now.date():
                    fire = True
        if fire and not self.running:
            cfg = self._get_config(silent=True)
            if cfg:
                if mode == "interval":
                    self._sched_interval_last = now
                else:
                    self._sched_daily_last = now.date()
                self._update_next_run()
                self.log_fn(f"\n  ⏰ [{self.v_name.get()}] Otomatik tarama — {now.strftime('%H:%M')}")
                self._execute_scan(cfg)
        self.after(30000, self._scheduler_tick)

    # ── Scan ───────────────────────────────────────────────────

    def _get_config(self, silent=False):
        recipient     = self.v_recipient.get().strip()
        kw_raw        = self.v_keywords.get().strip()
        keywords      = [k.strip() for k in kw_raw.split(",") if k.strip()]
        active        = [p for p in PUBLISHERS if self.pub_vars[p["short"]].get()]
        article_types = [k for k, v in self.type_vars.items() if v.get()]
        try:   days = max(1, int(self.v_days.get()))
        except ValueError: days = 7
        try:   maxr = max(1, int(self.v_max.get()))
        except ValueError: maxr = 100

        errors = []
        if not recipient:     errors.append("• Alıcı e-posta boş olamaz.")
        if not keywords:      errors.append("• En az bir anahtar kelime girin.")
        if not active:        errors.append("• En az bir yayıncı seçin.")
        if not article_types: errors.append("• En az bir makale türü seçin.")
        if errors:
            if not silent:
                messagebox.showerror("Eksik Bilgi", "\n".join(errors))
            else:
                self.log_fn(f"  ⚠ [{self.v_name.get()}] Eksik bilgi, atlandı.")
            return None

        return {
            "profile_name":    self.v_name.get(),
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
        cfg = self._get_config()
        if not cfg:
            return
        self._execute_scan(cfg)

    def _execute_scan(self, cfg):
        self.running = True
        self.btn_start.configure(state="disabled", text="⏳  Taranıyor…", bg=self.BTN_STOP)
        threading.Thread(target=self._run_scan, args=(cfg,), daemon=True).start()

    def _run_scan(self, cfg):
        try:
            self.log_fn(f"══ [{cfg['profile_name']}] ══════════════════════════")
            self.log_fn(f"  Tarih     : {datetime.now().strftime('%d %B %Y  %H:%M')}")
            self.log_fn(f"  Keywords  : {', '.join(cfg['keywords'])}  [{cfg['keyword_mode']}]")
            self.log_fn(f"  Dönem     : son {cfg['days_back']} gün")
            self.log_fn(f"  Yayıncılar: {len(cfg['active_pubs'])} seçili")
            all_articles = []
            for pub in cfg["active_pubs"]:
                results = search_publisher(
                    publisher=pub, keywords=cfg["keywords"],
                    days_back=cfg["days_back"], max_results=cfg["max_results"],
                    keyword_mode=cfg["keyword_mode"],
                    contact_email=cfg["recipient_email"],
                    article_types=cfg["article_types"], log_fn=self.log_fn)
                all_articles.extend(results)
            seen, unique = set(), []
            for art in all_articles:
                doi = art.get("DOI", id(art))
                if doi not in seen:
                    seen.add(doi); unique.append(art)
            self.log_fn(f"\n  ── Toplam: {len(unique)} makale ──")
            success = send_email_smtp(unique, cfg, cfg["active_pubs"], self.log_fn)
            if success:
                self.log_fn(f"  ✓ Bitti! {cfg['recipient_email']} adresini kontrol edin.")
                self.winfo_toplevel().after(0, lambda: messagebox.showinfo(
                    f"Tamamlandı — {cfg['profile_name']}",
                    f"{len(unique)} makale bulundu.\nGönderildi → {cfg['recipient_email']}"))
            else:
                self.log_fn("  ✗ E-posta gönderilemedi.")
        except Exception as e:
            self.log_fn(f"\n  Beklenmeyen hata: {e}")
        finally:
            self.running = False
            self.winfo_toplevel().after(0, lambda: self.btn_start.configure(
                state="normal", text="▶   TARAMAYI BAŞLAT", bg=self.BTN_RUN))

    # ── Serialize ──────────────────────────────────────────────

    def to_dict(self):
        return {
            "name":          self.v_name.get(),
            "recipient":     self.v_recipient.get(),
            "keywords":      self.v_keywords.get(),
            "keyword_mode":  self.v_mode.get(),
            "days_back":     self.v_days.get(),
            "max_results":   self.v_max.get(),
            "publishers":    [s for s, v in self.pub_vars.items() if v.get()],
            "article_types": [k for k, v in self.type_vars.items() if v.get()],
            "sched_active":  self.v_sched_active.get(),
            "sched_mode":    self.v_sched_mode.get(),
            "sched_interval":self.v_interval.get(),
            "sched_hour":    self.v_sched_hour.get(),
            "sched_min":     self.v_sched_min.get(),
        }


# ══════════════════════════════════════════════════════════════
#  ANA UYGULAMA
# ══════════════════════════════════════════════════════════════

class LiteratureScannerApp:

    HEADER = "#1a5276"
    BG     = "#f4f6f8"

    def __init__(self, root):
        self.root      = root
        self.log_queue = queue.Queue()
        self.profiles  = []

        self.root.title("Academic Literature Scanner  v3.0")
        self.root.geometry("880x760")
        self.root.minsize(750, 650)
        self.root.configure(bg=self.BG)

        self._build_ui()
        self._poll_log()
        self._load_profiles()

    def _build_ui(self):
        # Başlık
        hdr = tk.Frame(self.root, bg=self.HEADER, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Academic Literature Scanner",
                 font=(FONT, 16, "bold"), bg=self.HEADER, fg="white").pack()
        tk.Label(hdr, text="10 Yayıncı  ·  CrossRef API  ·  Çoklu Profil",
                 font=(FONT, 9), bg=self.HEADER, fg="#aed6f1").pack()

        # Profil araç çubuğu
        bar = tk.Frame(self.root, bg=self.BG, padx=10, pady=6)
        bar.pack(fill="x")
        for text, cmd, bg in [
            ("＋ Yeni Profil",   self._add_profile,    "#d5e8d4"),
            ("✎ Yeniden Adlandır", self._rename_profile, "#dae8fc"),
            ("✕ Profili Sil",   self._remove_profile, "#f8cecc"),
            ("💾 Kaydet",        self._save_profiles,  "#fff2cc"),
        ]:
            tk.Button(bar, text=text, command=cmd, relief="flat", bg=bg,
                      font=(FONT, 9), padx=10, pady=4,
                      cursor="hand2").pack(side="left", padx=(0, 6))

        # Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # Log
        log_frm = ttk.LabelFrame(self.root, text="  İşlem Kaydı", padding=4)
        log_frm.pack(fill="x", padx=8, pady=(0, 6))
        self.log_box = scrolledtext.ScrolledText(
            log_frm, height=6,
            font=("Courier New" if __import__("sys").platform == "win32" else "Courier", 9),
            bg="#1c2333", fg="#a8d8a8", insertbackground="white",
            relief="flat", state="disabled")
        self.log_box.pack(fill="both")
        self._log("Hazır.")

    # ── Profil yönetimi ────────────────────────────────────────

    def _add_profile(self, data=None):
        name = data.get("name", f"Profil {len(self.profiles)+1}") if data else f"Profil {len(self.profiles)+1}"
        frame = ProfileFrame(self.notebook, name, self._log, data)
        self.notebook.add(frame, text=f"  {name}  ")
        self.profiles.append(frame)
        self.notebook.select(frame)

    def _rename_profile(self):
        idx = self.notebook.index(self.notebook.select())
        if idx < 0 or idx >= len(self.profiles):
            return
        profile = self.profiles[idx]
        new_name = simpledialog.askstring(
            "Yeniden Adlandır", "Yeni profil adı:",
            initialvalue=profile.v_name.get(), parent=self.root)
        if new_name and new_name.strip():
            new_name = new_name.strip()
            profile.v_name.set(new_name)
            self.notebook.tab(idx, text=f"  {new_name}  ")

    def _remove_profile(self):
        if len(self.profiles) <= 1:
            messagebox.showwarning("Uyarı", "En az bir profil olmalıdır.")
            return
        idx = self.notebook.index(self.notebook.select())
        name = self.profiles[idx].v_name.get()
        if not messagebox.askyesno("Profili Sil", f'"{name}" profilini silmek istiyor musunuz?'):
            return
        self.notebook.forget(idx)
        self.profiles.pop(idx)

    def _save_profiles(self):
        data = [p.to_dict() for p in self.profiles]
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._log(f"  ✓ {len(data)} profil kaydedildi.")
        messagebox.showinfo("Kaydedildi", f"{len(data)} profil kaydedildi.")

    def _load_profiles(self):
        if os.path.exists(PROFILES_FILE):
            try:
                with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for d in data:
                    self._add_profile(d)
                self._log(f"  ✓ {len(data)} profil yüklendi.")
                return
            except Exception:
                pass
        self._add_profile()  # varsayılan boş profil

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


# ══════════════════════════════════════════════════════════════
#  BAŞLANGIÇ
# ══════════════════════════════════════════════════════════════

def main():
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.2)
    except Exception:
        pass
    LiteratureScannerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
