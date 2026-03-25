#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║      Academic Literature Scanner — GUI v1.0                 ║
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
import smtplib
import re
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


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

# Varsayılan değerler — kişisel bilgiler boş bırakılmıştır
DEFAULTS = {
    "sender_email":    "",          # Gmail adresiniz
    "recipient_email": "",          # Sonuçların gönderileceği e-posta
    "keywords":        "",          # Örn: biobased, renewable, sustainable
    "keyword_mode":    "OR",
    "days_back":       "7",
    "max_results":     "100",
}


# ══════════════════════════════════════════════════════════════
#  ARAMA VE E-POSTA FONKSİYONLARI
# ══════════════════════════════════════════════════════════════

def _clean(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def format_article(article):
    title    = _clean(" ".join(article.get("title", ["Başlık yok"])))
    journal  = ", ".join(article.get("container-title", ["Dergi bilinmiyor"]))
    doi      = article.get("DOI", "")
    url      = f"https://doi.org/{doi}" if doi else article.get("URL", "")

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

    pub = article.get("_publisher", {})
    return {
        "title": title, "authors": authors, "journal": journal,
        "date": date_str or "—", "url": url, "doi": doi,
        "citation": citation, "abstract": abstract,
        "publisher_name": pub.get("name", ""),
        "publisher_color": pub.get("color", "#1a5276"),
    }


def search_publisher(publisher, keywords, days_back, max_results, keyword_mode, contact_email, log_fn):
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

    if keyword_mode == "AND":
        filtered = [
            it for it in items
            if all(kw.lower() in (" ".join(it.get("title",[])) + " " +
                                  it.get("abstract","")).lower()
                   for kw in keywords)
        ]
        log_fn(f"  [{publisher['short']}] {len(items)} → {len(filtered)} (AND filtre)")
        return filtered

    log_fn(f"  [{publisher['short']}] {len(items)} makale bulundu")
    return items


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
                rows += f"""
                <div style="background:#f8f9fa;border-left:4px solid {color};
                             margin:12px 0;padding:13px 16px;border-radius:4px;">
                  <div style="font-size:15px;font-weight:bold;color:{color};">
                    {i}. <a href="{f['url']}" style="color:{color};text-decoration:none;"
                            target="_blank">{f['title']}</a>
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


def build_plain(articles, cfg, active_pubs):
    lines = [
        f"Academic Literature Scan — {len(active_pubs)} Yayıncı",
        "=" * 60,
        f"Tarih    : {datetime.now().strftime('%d %B %Y')}",
        f"Keywords : {', '.join(cfg['keywords'])}",
        f"Mod      : {cfg['keyword_mode']}",
        f"Dönem    : son {cfg['days_back']} gün",
        f"Toplam   : {len(articles)} makale",
        "",
    ]
    for pub in active_pubs:
        pub_articles = [a for a in articles
                        if a.get("_publisher", {}).get("name") == pub["name"]]
        lines += [f"── {pub['name']} ({len(pub_articles)} makale) ──", ""]
        for i, art in enumerate(pub_articles, 1):
            f = format_article(art)
            lines += [
                f"{i}. {f['title']}",
                f"   Authors  : {f['authors']}",
                f"   Journal  : {f['journal']} {f['citation']}",
                f"   Published: {f['date']}",
                f"   URL      : {f['url']}", "",
            ]
    return "\n".join(lines)


def send_email(articles, cfg, active_pubs, log_fn):
    sender, recipient = cfg["sender_email"], cfg["recipient_email"]
    date_tag = datetime.now().strftime("%Y-%m-%d")
    n = len(articles)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"Literature Scan [{date_tag}] — {n} makale "
        f"| {len(active_pubs)} yayıncı | {', '.join(cfg['keywords'])}"
    )
    msg["From"], msg["To"] = sender, recipient

    msg.attach(MIMEText(build_plain(articles, cfg, active_pubs), "plain", "utf-8"))
    msg.attach(MIMEText(build_html(articles,  cfg, active_pubs), "html",  "utf-8"))

    log_fn("\n  Gmail'e bağlanılıyor (smtp.gmail.com:587)…")
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(sender, cfg["sender_password"])
        server.sendmail(sender, recipient, msg.as_string())
        server.quit()
        log_fn(f"  ✓ E-posta gönderildi → {recipient}")
        return True
    except smtplib.SMTPAuthenticationError:
        log_fn("  HATA: Gmail kimlik doğrulaması başarısız.")
        log_fn("  ‣ 16 haneli App Password girdiğinizden emin olun.")
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
    ACCENT   = "#2874a6"
    BTN_RUN  = "#1e8449"
    BTN_STOP = "#7f8c8d"
    FONT     = "Segoe UI" if __import__("sys").platform == "win32" else "Helvetica"

    def __init__(self, root):
        self.root      = root
        self.log_queue = queue.Queue()
        self.running   = False
        self.pub_vars  = {p["short"]: tk.BooleanVar(value=True) for p in PUBLISHERS}

        self.root.title("Academic Literature Scanner  v2.0")
        self.root.geometry("820x720")
        self.root.minsize(700, 600)
        self.root.configure(bg=self.BG)

        self._build_ui()
        self._poll_log()

    # ── UI construction ────────────────────────────────────────

    def _build_ui(self):
        self._header()
        content = tk.Frame(self.root, bg=self.BG, padx=16, pady=10)
        content.pack(fill="both", expand=True)

        top = tk.Frame(content, bg=self.BG)
        top.pack(fill="x")
        self._email_section(top)
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
        tk.Label(hdr, text="10 Yayıncı  ·  CrossRef API  ·  Gmail",
                 font=(self.FONT, 9),
                 bg=self.HEADER, fg="#aed6f1").pack()

    # Registry of active placeholder entries: {StringVar: placeholder_text}
    _placeholders: dict = {}

    def _bg(self, widget):
        """Safely return a widget's background colour.
        ttk widgets don't support widget['bg'] — fall back to self.BG."""
        for key in ("background", "bg"):
            try:
                return widget.cget(key)
            except tk.TclError:
                pass
        return self.BG

    def _entry(self, parent, label, var, is_password=False, width=None, placeholder=""):
        """Create a labelled Entry, optionally with greyed placeholder text."""
        tk.Label(parent, text=label, font=(self.FONT, 9),
                 bg=self._bg(parent), anchor="w").pack(fill="x", pady=(8, 1))

        entry = tk.Entry(parent, textvariable=var, font=(self.FONT, 10),
                         relief="solid", bd=1, bg="white")
        if width:
            entry.config(width=width)
        entry.pack(fill="x", ipady=5)

        if placeholder:
            LiteratureScannerApp._placeholders[str(var)] = placeholder
            # Show placeholder if field is empty
            if not var.get():
                var.set(placeholder)
                entry.config(fg="#aaaaaa")

            def _focus_in(e, v=var, pw=is_password, ent=entry, ph=placeholder):
                if v.get() == ph:
                    v.set("")
                    ent.config(fg="black", show="●" if pw else "")

            def _focus_out(e, v=var, pw=is_password, ent=entry, ph=placeholder):
                if not v.get():
                    v.set(ph)
                    ent.config(fg="#aaaaaa", show="")

            entry.bind("<FocusIn>",  _focus_in)
            entry.bind("<FocusOut>", _focus_out)
        elif is_password:
            entry.config(show="●")

    def _email_section(self, parent):
        frm = ttk.LabelFrame(parent, text="  E-Posta Ayarları", padding=12)
        frm.pack(side="left", fill="both", expand=True, padx=(0, 8))
        frm.configure(style="Card.TLabelframe")

        self.v_sender   = tk.StringVar(value=DEFAULTS["sender_email"])
        self.v_password = tk.StringVar()
        self.v_recipient= tk.StringVar(value=DEFAULTS["recipient_email"])

        self._entry(frm, "Gönderen e-posta (Gmail):", self.v_sender,
                    placeholder="ornek@gmail.com")
        self._entry(frm, "Gmail App Password:",        self.v_password,
                    is_password=True, placeholder="16 haneli App Password")

        # Show/hide password toggle
        self.show_pwd = tk.BooleanVar(value=False)
        tk.Checkbutton(frm, text="Şifreyi göster", variable=self.show_pwd,
                       bg=self._bg(frm),
                       command=self._toggle_password,
                       font=(self.FONT, 8)).pack(anchor="e")
        self._pwd_entry = None  # will reference via re-build

        self._entry(frm, "Alıcı e-posta:", self.v_recipient,
                    placeholder="sonuclar@kurum.edu.tr")

        # Help text
        tk.Label(frm,
                 text="⚠  Gmail App Password için:\nmyaccount.google.com → Güvenlik → Uygulama Şifreleri",
                 font=(self.FONT, 8), bg=self._bg(frm),
                 fg="#888", justify="left").pack(anchor="w", pady=(10, 0))

    def _toggle_password(self):
        for widget in self.root.winfo_children():
            self._toggle_in(widget)

    def _toggle_in(self, widget):
        if isinstance(widget, tk.Entry):
            try:
                if str(widget.cget("textvariable")) == str(self.v_password):
                    widget.config(show="" if self.show_pwd.get() else "●")
            except Exception:
                pass
        for child in widget.winfo_children():
            self._toggle_in(child)

    def _search_section(self, parent):
        frm = ttk.LabelFrame(parent, text="  Arama Ayarları", padding=12)
        frm.pack(side="left", fill="both", expand=True)

        # Keywords
        self.v_keywords = tk.StringVar(value=DEFAULTS["keywords"])
        self._entry(frm, "Anahtar Kelimeler (virgülle ayırın):", self.v_keywords,
                    placeholder="örn: biobased, renewable, sustainable")

        # Mode
        bg = self._bg(frm)
        tk.Label(frm, text="Arama Modu:", font=(self.FONT, 9),
                 bg=bg, anchor="w").pack(fill="x", pady=(12, 2))
        mode_frm = tk.Frame(frm, bg=bg)
        mode_frm.pack(anchor="w")
        self.v_mode = tk.StringVar(value=DEFAULTS["keyword_mode"])
        for text, val in [("OR  — herhangi bir kelime", "OR"),
                           ("AND — tüm kelimeler", "AND")]:
            tk.Radiobutton(mode_frm, text=text, variable=self.v_mode, value=val,
                           bg=bg, font=(self.FONT, 9),
                           activebackground=bg).pack(side="left", padx=(0, 14))

        # Days & max
        num_row = tk.Frame(frm, bg=bg)
        num_row.pack(fill="x", pady=(12, 0))

        for label, var_name, default, frm_side in [
            ("Son kaç gün:",          "v_days", DEFAULTS["days_back"],    "left"),
            ("Maks sonuç / yayıncı:", "v_max",  DEFAULTS["max_results"],  "left"),
        ]:
            cell = tk.Frame(num_row, bg=bg)
            cell.pack(side=frm_side, fill="x", expand=True, padx=(0, 8))
            tk.Label(cell, text=label, font=(self.FONT, 9),
                     bg=bg).pack(anchor="w")
            var = tk.StringVar(value=default)
            setattr(self, var_name, var)
            tk.Spinbox(cell, textvariable=var, from_=1, to=500, increment=1,
                       width=8, font=(self.FONT, 10), relief="solid", bd=1,
                       bg="white").pack(anchor="w", ipady=4)

    def _publisher_section(self, parent):
        frm = ttk.LabelFrame(parent, text="  Yayıncılar — Taranacakları İşaretleyin",
                              padding=10)
        frm.pack(fill="x", pady=(10, 0))

        cols = 5
        for i, pub in enumerate(PUBLISHERS):
            cb = ttk.Checkbutton(frm, text=pub["short"],
                                 variable=self.pub_vars[pub["short"]])
            cb.grid(row=i // cols, column=i % cols, sticky="w", padx=10, pady=3)

        btn_row = tk.Frame(frm, bg=self._bg(frm))
        btn_row.grid(row=(len(PUBLISHERS) - 1) // cols + 1,
                     column=0, columnspan=cols, sticky="w", pady=(8, 2))
        for text, cmd, bg in [("Tümünü Seç",   self._sel_all,  "#d5e8d4"),
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
        self._log("Hazır.  Bilgileri doldurun ve 'Taramayı Başlat'a tıklayın.")

    # ── Logging ────────────────────────────────────────────────

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

    # ── Validation ─────────────────────────────────────────────

    def _real(self, var):
        """Return the var's value, or '' if it still contains placeholder text."""
        val = var.get().strip()
        ph  = LiteratureScannerApp._placeholders.get(str(var), "")
        return "" if val == ph else val

    def _collect(self):
        sender    = self._real(self.v_sender)
        password  = self._real(self.v_password)
        recipient = self._real(self.v_recipient)
        kw_raw    = self._real(self.v_keywords)
        keywords  = [k.strip() for k in kw_raw.split(",") if k.strip()]
        active    = [p for p in PUBLISHERS if self.pub_vars[p["short"]].get()]

        errors = []
        if not sender:    errors.append("• Gönderen e-posta boş olamaz.")
        if not password:  errors.append("• App Password boş olamaz.")
        if not recipient: errors.append("• Alıcı e-posta boş olamaz.")
        if not keywords:  errors.append("• En az bir anahtar kelime girin.")
        if not active:    errors.append("• En az bir yayıncı seçin.")

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
            "sender_email":    sender,
            "sender_password": password,
            "recipient_email": recipient,
            "keywords":        keywords,
            "keyword_mode":    self.v_mode.get(),
            "days_back":       days,
            "max_results":     maxr,
            "active_pubs":     active,
        }

    # ── Scan ───────────────────────────────────────────────────

    def _start_scan(self):
        if self.running:
            return
        cfg = self._collect()
        if not cfg:
            return

        self.running = True
        self.btn_start.configure(state="disabled", text="⏳   Taranıyor…",
                                 bg=self.BTN_STOP)

        # Clear log
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

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
                    log_fn=self._log,
                )
                all_articles.extend(results)

            # Deduplicate by DOI
            seen, unique = set(), []
            for art in all_articles:
                doi = art.get("DOI", id(art))
                if doi not in seen:
                    seen.add(doi)
                    unique.append(art)

            self._log(f"\n  ── Toplam: {len(unique)} makale bulundu ──")

            success = send_email(
                articles   = unique,
                cfg        = cfg,
                active_pubs= cfg["active_pubs"],
                log_fn     = self._log,
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
