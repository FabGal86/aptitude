import os
import re
import io
import json
import base64
import tempfile
import pandas as pd
import streamlit as st
from PyPDF2 import PdfReader
from docx import Document
from difflib import SequenceMatcher
from urllib.parse import quote, quote_plus
from groq import Groq

# ===================== OCR / CONVERSIONE =====================
try:
    from pdf2image import convert_from_bytes
except ImportError:
    convert_from_bytes = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from docx2pdf import convert as docx2pdf_convert
except ImportError:
    docx2pdf_convert = None

# Configurazione opzionale percorso Tesseract (es. per Windows)
if pytesseract is not None:
    tess_cmd = os.getenv("TESSERACT_CMD", "").strip()
    if tess_cmd:
        pytesseract.pytesseract.tesseract_cmd = tess_cmd

OCR_AVAILABLE = convert_from_bytes is not None and pytesseract is not None

# ===================== CONFIGURAZIONE PAGINA =====================
st.set_page_config(page_title="APTITUDE", layout="centered")

# ===================== MODERN CSS – RESPONSIVE + SFONDO GRIGIO =====================
st.markdown("""
<style>

/* SFONDO GRIGIO UNIFORME */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > .main {
    background-color: #202020 !important;
}

/* CONTAINER PRINCIPALE */
[data-testid="stAppViewContainer"] > .main .block-container {
    max-width: 1200px;
    padding-top: 1.5rem;
    padding-bottom: 4rem;
    padding-left: 1.5rem;
    padding-right: 1.5rem;
}

/* TABLET / LAPTOP RIDOTTO */
@media (max-width: 992px) {
    [data-testid="stAppViewContainer"] > .main .block-container {
        max-width: 100%;
        padding-left: 1.2rem;
        padding-right: 1.2rem;
        padding-top: 1.2rem;
    }

    #custom-title {
        font-size: 32px;
        white-space: normal;
        line-height: 1.2;
    }

    #subtitle {
        font-size: 16px;
    }
}

/* SMARTPHONE */
@media (max-width: 600px) {
    [data-testid="stAppViewContainer"] > .main .block-container {
        max-width: 100%;
        padding-left: 0.8rem;
        padding-right: 0.8rem;
        padding-top: 1rem;
        padding-bottom: 4rem;
    }

    #custom-title {
        font-size: 22px;
        margin-top: 6px;
        white-space: normal;
        line-height: 1.25;
    }

    #subtitle {
        font-size: 13px;
        margin-top: 2px;
    }

    [data-testid="stFileUploader"] {
        padding: 10px;
    }

    button {
        font-size: 13px !important;
        padding: 6px 14px !important;
    }

    .footer {
        position: static;
        font-size: 9px;
        padding: 6px;
    }
}

/* TITOLO */
#custom-title {
    color: #00ff00 !important;
    font-size: 40px;
    font-weight: 900;
    text-align: center;
    margin-top: 16px;
    font-family: 'Montserrat', sans-serif;
    letter-spacing: 0.03em;
}

/* SOTTOTITOLO */
#subtitle {
    color: #a0ffb0 !important;
    font-size: 16px;
    font-style: italic;
    text-align: center;
    margin-top: 3px;
    font-family: 'Montserrat', sans-serif;
    opacity: 0.9;
}

/* UPLOADER BOX */
[data-testid="stFileUploader"] {
    background: rgba(40,40,40,0.95);
    border: 1px solid rgba(0,255,0,0.25);
    border-radius: 12px;
    padding: 14px;
    box-shadow: 0px 0px 8px rgba(0,255,0,0.18);
}
[data-testid="stFileUploader"] section {
    background: transparent;
}

/* BUTTON – verde generico */
button {
    background-color: #198754 !important;
    color: #f0f0f0 !important;
    border: 1px solid #198754 !important;
    border-radius: 8px !important;
    padding: 8px 22px !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    transition: 0.2s ease-in-out !important;
}
button:hover {
    background-color: #157347 !important;
    border-color: #146c43 !important;
}

/* FOOTER (desktop/tablet) */
.footer {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 8px;
    text-align: center;
    color: #b4ffbe;
    background: rgba(20,20,20,0.9);
    border-top: 1px solid rgba(0,255,0,0.25);
    font-size: 11px;
    font-family: 'Montserrat', sans-serif;
}

/* Rende la tabella un po' più compatta ma ben visibile */
[data-testid="stDataFrame"] table {
    font-size: 13px;
}
@media (max-width: 600px) {
    [data-testid="stDataFrame"] table {
        font-size: 11px;
    }
}

</style>
""", unsafe_allow_html=True)

# ===================== HEADER =====================
st.markdown('<div id="custom-title">TLK Aptitude Screener</div>', unsafe_allow_html=True)
st.markdown('<div id="subtitle">AI-Assisted</div>', unsafe_allow_html=True)

# ===================== AVVISO OCR =====================
if not OCR_AVAILABLE:
    st.warning(
        "OCR non disponibile: per leggere PDF scannerizzati installa le librerie "
        "'pdf2image', 'pytesseract' e i programmi Tesseract OCR + Poppler. "
        "Opzionale: imposta la variabile d'ambiente TESSERACT_CMD con il percorso "
        "di tesseract.exe su Windows."
    )

# ===================== CONFIG GROQ =====================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# ===================== PREFISSI TEL. =====================
ALLOWED_PREFIXES = ["+39", "+44", "+353"]

# ===================== KEYWORDS (fallback locale) =====================
PHONE_KW = [
    "call center", "call-center", "callcentre",
    "contact center", "contact centre",
    "customer contact center", "customer contact centre",
    "operatore call center", "operatrice call center",
    "operatore di call center", "operatrice di call center",
    "addetto call center", "addetta call center",
    "agente call center",
    "impiegato call center", "impiegata call center",
    "servizi di call center", "servizi di contact center",
    "call center agent", "call centre agent",
    "call center representative", "call centre representative",
    "call center rep", "call centre rep",
    "call center operator", "call centre operator",
    "call center associate", "call centre associate",
    "call center specialist", "call centre specialist",
    "call center advisor", "call centre advisor",
    "call center consultant", "call centre consultant",
    "contact center agent", "contact centre agent",
    "contact center representative", "contact centre representative",
    "contact center specialist", "contact centre specialist",
    "contact center advisor", "contact centre advisor",
    "contact center consultant", "contact centre consultant",
    "contact center operator", "contact centre operator",
    "inbound call center", "outbound call center",
    "inbound calls", "outbound calls",
    "gestione chiamate", "gestione telefonate",
    "gestione chiamate in entrata", "gestione chiamate in uscita",
    "chiamate in entrata", "chiamate in uscita",
    "phone calls handling", "call handling",
    "servizio clienti", "servizi clienti",
    "servizio al cliente", "servizi al cliente",
    "servizio assistenza clienti", "assistenza clienti",
    "assistenza al cliente", "assistenza alla clientela",
    "assistenza post vendita telefonica",
    "assistenza post-vendita telefonica",
    "assistenza tecnica telefonica",
    "supporto clienti", "supporto al cliente",
    "supporto alla clientela",
    "assistenza telefonica clienti",
    "operatore servizio clienti", "operatrice servizio clienti",
    "addetto servizio clienti", "addetta servizio clienti",
    "impiegato servizio clienti", "impiegata servizio clienti",
    "reparto customer service", "ufficio customer service",
    "ufficio assistenza clienti",
    "servizio di help desk", "servizio help desk telefonico",
    "customer service telefonico", "customer care telefonico",
    "customer service", "customer care", "customer support",
    "client support", "client services",
    "customer experience agent", "customer experience associate",
    "customer experience specialist",
    "customer success associate", "customer success agent",
    "customer success representative",
    "customer service representative", "customer service rep",
    "customer support representative", "customer support rep",
    "customer care representative", "customer care rep",
    "client service representative", "client service rep",
    "customer operations specialist",
    "customer operations representative",
    "customer operations agent",
    "cx agent", "cx associate",
    "support agent", "support representative", "support specialist",
    "service desk agent", "service desk analyst",
    "help desk", "helpdesk", "help-desk",
    "operatore help desk", "operatrice help desk",
    "addetto help desk", "addetta help desk",
    "supporto tecnico telefonico",
    "assistenza tecnica telefonica",
    "assistenza tecnica clienti",
    "technical support", "technical support specialist",
    "technical support representative", "technical support agent",
    "it support", "it help desk",
    "service desk", "service desk technician",
    "technical help desk",
    "telemarketing", "tele-marketing",
    "operatore telemarketing", "operatrice telemarketing",
    "addetto telemarketing", "addetta telemarketing",
    "telemarketing specialist",
    "telemarketing agent", "telemarketing representative",
    "telemarketing rep",
    "telefonate commerciali", "telefonate di vendita",
    "contatto telefonico con i clienti",
    "contatti telefonici con i clienti",
    "contatti telefonici con potenziali clienti",
    "attività di telemarketing",
    "telemarketing outbound", "telemarketing inbound",
    "telesales", "tele-sales",
    "telesales agent", "telesales representative",
    "telesales rep", "telesales consultant", "telesales executive",
    "teleselling", "tele-selling",
    "operatore teleselling", "operatrice teleselling",
    "vendita telefonica", "vendite telefoniche",
    "operatore di vendita telefonica", "operatrice di vendita telefonica",
    "addetto alle vendite telefoniche", "addetta alle vendite telefoniche",
    "inside sales (phone)", "inside sales (telefonico)",
    "inside sales representative (phone)",
    "inside sales rep (phone)",
    "phone sales", "telephone sales",
    "sales via phone", "telephonic sales",
    "outbound sales calls", "cold calling",
    "attività di recall", "recall telefonico",
    "campagne di recall telefonico",
    "richiamo clienti", "richiamata clienti",
    "recupero crediti telefonico",
    "operatore recupero crediti telefonico",
    "phone collections",
    "collection agent (phone)",
    "collection representative (phone)",
    "retention telefonica clienti",
    "customer retention specialist (phone)",
    "customer retention agent (phone)",
    "loyalty call center",
    "numero verde",
    "operatore numero verde", "operatrice numero verde",
    "servizio numero verde clienti",
    "hotline", "hot line",
    "customer hotline", "support hotline",
    "help line", "phone hotline",
    "contact center multicanale",
    "contact center omnicanale",
    "operatore chat clienti",
    "chat agent", "live chat agent",
    "live chat support", "web chat agent",
    "online chat agent",
    "chat support representative",
    "customer support via chat",
    "customer support via email",
    "email support", "email support agent",
    "tirocinio call center", "stage call center",
    "tirocinante call center", "stagista call center",
    "tirocinio customer service telefonico",
    "stage customer service telefonico",
    "tirocinio in contact center", "stage in contact center",
    "apprendista operatore call center",
    "apprendista operatore telefonico",
    "internship in call center",
    "call center intern",
    "customer service internship (phone)",
    "customer support internship (phone)",
    "operatore telefonico", "operatrice telefonica",
    "operatori telefonici",
    "operatore di servizi telefonici",
    "operatore telefonico inbound", "operatore telefonico outbound",
    "operatrice telefonica inbound", "operatrice telefonica outbound",
    "addetto operatore telefonico", "addetta operatore telefonico",
    "impiegato operatore telefonico", "impiegata operatore telefonico"
]

FUZZY_PHONE_KW = [
    "cutomer service",
    "custmer service",
    "costumer service",
    "custumer service",
    "customer servce",
    "custemer service"
]

PUBLIC_KW = [
    "vendita", "vendita al pubblico", "assistenza alla vendita",
    "addetto vendite", "addetta vendite",
    "commesso", "commessa",
    "reparto vendite",
    "punto vendita", "negozio",
    "consulente alle vendite", "consulente di vendita",
    "consulente commerciale",
    "agente commerciale", "agente di commercio",
    "commerciale interno", "commerciale esterno",
    "sales", "sales assistant", "sales associate",
    "sales representative", "sales rep", "sales consultant",
    "shop assistant", "store assistant",
    "store clerk",
    "store manager", "assistant store manager",
    "retail", "retail assistant", "retail sales",
    "key account manager", "account manager",
    "relazione con il pubblico", "relazioni con il pubblico",
    "contatto con il pubblico", "contatto con i clienti",
    "gestione clienti", "gestione della clientela",
    "gestione reclami",
    "assistenza al pubblico",
    "assistenza clienti in presenza",
    "assistenza alla clientela",
    "customer facing", "client facing", "public facing",
    "customer relations", "customer relationship",
    "customer relationship management",
    "customer oriented", "customer focused",
    "orientamento al cliente", "orientato al cliente",
    "orientamento alla clientela",
    "ascolto attivo", "capacità di ascolto",
    "attenzione al cliente",
    "gestione delle obiezioni",
    "problem solving con il cliente",
    "cassa", "cassiere", "cassiera",
    "gestione cassa", "operazioni di cassa",
    "pagamenti clienti", "incasso pagamenti",
    "cashier",
    "front office", "front-office",
    "back office clienti", "back-office clienti",
    "segreteria", "segretaria", "segretario",
    "segreteria commerciale", "segreteria organizzativa",
    "reception", "receptionist",
    "accoglienza clienti", "accoglienza ospiti",
    "accoglienza al pubblico",
    "info point", "info-point", "info desk",
    "sportello", "operatore di sportello",
    "addetto allo sportello", "addetta allo sportello",
    "desk informazioni",
    "promoter", "promozione", "attività promozionale",
    "brand ambassador",
    "hostess", "steward",
    "hostess di sala", "hostess congressuale",
    "public relations", "relazioni pubbliche",
    "volantinaggio", "flyer distribution",
    "accoglienza eventi", "accoglienza clienti eventi",
    "cameriere", "cameriera",
    "commis di sala", "chef de rang",
    "responsabile di sala", "addetto sala", "addetta sala",
    "servizio ai tavoli", "servizio in sala",
    "banconiere", "banconista",
    "addetto al banco", "addetta al banco",
    "barista", "barman", "barmaid", "bartender",
    "responsabile di bar",
    "addetto ristorazione", "addetta ristorazione",
    "fast food crew", "crew member",
    "responsabile di sala bar",
    "sommelier",
    "addetto al front office alberghiero",
    "addetta al front office alberghiero",
    "reception hotel", "front desk agent",
    "guest relation", "guest relations",
    "guest service", "guest services",
    "concierge",
    "tour guide", "guida turistica",
    "accompagnatore turistico", "accompagnatrice turistica",
    "commesso di farmacia", "commessa di farmacia",
    "addetto vendita farmacia", "addetta vendita farmacia",
    "beauty consultant", "beauty advisor",
    "consulente di bellezza",
    "consulente di vendita auto", "venditore auto",
    "vendita auto", "showroom assistant",
    "showroom consultant",
    "assistenza clienti in store",
    "assistenza clienti in negozio",
    "customer care in store",
    "customer care in shop",
    "customer experience in store",
    "customer service", "customer care",
    "servizio clienti", "assistenza clienti"
]

PHONE_KW = [k.lower() for k in PHONE_KW]
FUZZY_PHONE_KW = [k.lower() for k in FUZZY_PHONE_KW]
PUBLIC_KW = [k.lower() for k in PUBLIC_KW]


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def phrase_in_text(phrase: str, text: str) -> bool:
    token = (phrase or "").strip()
    if not token:
        return False
    if len(token.replace(" ", "")) <= 2:
        return False
    words = token.split()
    pattern = r"\b" + r"\s+".join(re.escape(w) for w in words) + r"\b"
    return re.search(pattern, text) is not None


def text_has_phone(t: str) -> bool:
    text = t.lower()
    if any(phrase_in_text(k, text) for k in PHONE_KW):
        return True
    if any(k in text for k in FUZZY_PHONE_KW):
        return True
    tokens = re.findall(r"[a-zà-ù]+", text)
    for i in range(len(tokens) - 1):
        w1, w2 = tokens[i], tokens[i + 1]
        if _similar(w1, "customer") >= 0.8 and _similar(w2, "service") >= 0.8:
            return True
        if _similar(w1, "servizio") >= 0.8 and _similar(w2, "clienti") >= 0.8:
            return True
    return False


def text_has_public(t: str) -> bool:
    text = t.lower()
    return any(phrase_in_text(k, text) for k in PUBLIC_KW)


# ===================== LETTURA FILE + OCR =====================
def ocr_pdf_bytes(data: bytes) -> str:
    if not OCR_AVAILABLE or not data:
        return ""
    try:
        images = convert_from_bytes(data)
        texts = []
        for img in images:
            txt = pytesseract.image_to_string(img)
            if txt:
                texts.append(txt)
        return "\n".join(texts)
    except Exception:
        return ""


def extract_text(file, original_bytes: bytes = None) -> str:
    ext = file.name.split(".")[-1].lower()
    if original_bytes is None:
        try:
            original_bytes = file.getvalue()
        except Exception:
            original_bytes = None
    try:
        if ext == "pdf":
            text = ""
            if original_bytes is not None:
                reader = PdfReader(io.BytesIO(original_bytes))
            else:
                file.seek(0)
                reader = PdfReader(file)
            pages_text = []
            for p in reader.pages:
                t = p.extract_text() or ""
                pages_text.append(t)
            text = "\n".join(pages_text)
            if text.strip():
                return text
            if original_bytes is not None:
                return ocr_pdf_bytes(original_bytes)
            return ""
        if ext == "docx":
            file.seek(0)
            return "\n".join(p.text for p in Document(file).paragraphs)
        file.seek(0)
        return file.read().decode("utf-8", "ignore")
    except Exception:
        if ext == "pdf" and original_bytes:
            return ocr_pdf_bytes(original_bytes)
        return ""


# ===================== EMAIL / TEL (fallback) =====================
def extract_email(text: str) -> str:
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return m.group(0) if m else ""


def extract_phones(text: str):
    raw = re.findall(r"(\+\d[0-9\s().-]{7,18}\d)", text)
    res, seen = [], set()
    for c in raw:
        norm = re.sub(r"[^\d+]", "", c)
        if not any(norm.startswith(p) for p in ALLOWED_PREFIXES):
            continue
        d = re.sub(r"[^\d]", "", norm)
        if 8 <= len(d) <= 15:
            if norm not in seen:
                seen.add(norm)
                res.append(norm)
    return res


# ===================== NAME EXTRACTION (fallback) =====================
def extract_name(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    bad_tokens = [
        "work experience", "esperienza lavorativa", "esperienze lavorative",
        "esperienza professionale", "professional experience",
        "informazioni personali", "dati personali", "personal information",
        "curriculum vitae", "curriculum", "profile", "profilo",
        "education", "istruzione", "formazione"
    ]
    for l in lines[:25]:
        low = l.lower()
        if any(b in low for b in bad_tokens):
            continue
        if any(ch.isdigit() for ch in l):
            continue
        parts = l.split()
        if 2 <= len(parts) <= 4:
            return l
    return ""


def guess_from_email(email: str) -> str:
    if not email:
        return ""
    nick = re.sub(r"[\d_.-]+", " ", email.split("@")[0])
    p = [x for x in nick.split() if len(x) > 1]
    return f"{p[0].capitalize()} {p[1].capitalize()}" if len(p) >= 2 else ""


def clean_name(n: str) -> str:
    p = [
        re.sub(r"\d", "", x)
        for x in n.split()
        if x.lower() not in {"cv", "profilo", "profile", "mr", "sig", "sig.", "dr", "dott", "dott."}
    ]
    return " ".join(x.capitalize() for x in p[:3]) if len(p) >= 2 else ""


def resolve_name(ai_n: str, ai_s: str, text: str, email: str) -> str:
    for v in [
        clean_name(f"{ai_n} {ai_s}".strip()),
        clean_name(extract_name(text)),
        clean_name(guess_from_email(email))
    ]:
        if v:
            return v
    return ""


# ===================== GROQ – PROMPT =====================
FULL_SYS = """
Sei un sistema che estrae dati strutturati da CV in italiano, inglese, spagnolo o tedesco
e valuta l'adeguatezza per ruoli di call center / contact center / customer service telefonico.

ATTENZIONE AI CONTATTI:
Nel 99% dei casi Nome e Cognome, Numero di telefono cellulare ed E-mail
sono riportati nella PRIMA PAGINA del CV, di solito nella PRIMA META'
(intestazione o riquadro dati personali). Usa questa informazione per
identificarli in modo affidabile.

Devi restituire SOLO un oggetto JSON valido, SENZA testo aggiuntivo, nel formato:

{
  "name": "",
  "surname": "",
  "email": "",
  "phones": [],
  "has_public_contact": false,
  "has_phone_contact": false,
  "public_roles": [],
  "phone_roles": [],
  "has_basic_it_skills": false,
  "it_skills": [],
  "profile_keywords": [],
  "ai_summary": "",
  "suitability_label": "",
  "ai_support": ""
}

Significato campi principali:

- "name", "surname": nome e cognome reali del candidato, recuperati dai dati iniziali del CV.
- "email": email principale del candidato (preferisci quella indicata nei dati personali in alto).
- "phones": array di stringhe con i numeri di telefono, dando priorità al NUMERO DI CELLULARE.

- "has_public_contact": true se ci sono ruoli con contatto diretto col pubblico/cliente
  in presenza (retail, ristorazione, bar, hospitality, eventi, showroom, sportello, reception, ecc.).
- "has_phone_contact": true se ci sono esperienze dove una parte centrale del lavoro
  sono chiamate telefoniche strutturate verso/da clienti:
  call center, contact center, customer service telefonico, help desk telefonico,
  telemarketing, telesales, phone collections, inbound/outbound calls, ecc.
  NON considerare come esperienza telefonica strutturata l'uso solo occasionale del telefono.

- "public_roles": fino a 5 stringhe brevi (max 4 parole) che riassumono ruoli a contatto col pubblico,
  usando la lingua del CV.
- "phone_roles": fino a 5 stringhe brevi (max 4 parole) che riassumono ruoli telefonici strutturati,
  usando la lingua del CV.

- "has_basic_it_skills": true se sono presenti competenze informatiche da ufficio:
  pacchetto Office (Word, Excel, PowerPoint, Outlook), Google Suite/Workspace (Docs, Sheets, Slides),
  strumenti di videoconferenza (Meet, Zoom, Teams), posta elettronica, CRM o software gestionali/ticketing.
- "it_skills": fino a 5 stringhe brevi che riassumono strumenti digitali rilevanti.

- "profile_keywords": esattamente 4 stringhe brevi che rappresentano il profilo,
  usando keyword o hashtag (es. "#CustomerService", "#Retail", "#OfficeSkills", "#CallCenterExperience").

- "ai_summary": riassunto sintetico delle esperienze lavorative, in ITALIANO,
  composto da ESATTAMENTE 4 RIGHE separate da "\\n".
  Ogni riga massimo 120 caratteri, focalizzata su attività lavorative e contatto con clienti.

- "suitability_label": valutazione complessiva di idoneità, deve essere
  ESATTAMENTE una di queste stringhe:
  - "Adatto"
  - "Parzialmente adatto"
  - "Non adatto"

  Applica SEMPRE queste regole:

  1) "Non adatto" se NON ci sono competenze informatiche da ufficio
     (has_basic_it_skills = false) E NON ci sono esperienze telefoniche strutturate
     di call center/contact center/telemarketing/altre attività telefoniche con clienti
     (has_phone_contact = false).

  2) "Adatto" SOLO se ci sono SIA competenze informatiche da ufficio
     (has_basic_it_skills = true) SIA esperienze telefoniche strutturate con clienti
     (has_phone_contact = true).

  3) "Parzialmente adatto" se è presente SOLO UNA delle due variabili:
     - competenze informatiche da ufficio
     - oppure esperienze telefoniche strutturate
     MA a condizione che nel CV esista comunque esperienza di contatto, supporto
     o servizio al pubblico/cliente (has_public_contact = true).

  4) In tutti gli altri casi, considera "Non adatto".

- "ai_support": breve commento in ITALIANO (2-3 frasi) che spiega perché
  hai scelto quel valore in "suitability_label", citando:
  - presenza/assenza di esperienza telefonica strutturata,
  - presenza/assenza di lavoro a contatto col pubblico,
  - presenza/assenza di competenze informatiche da ufficio.

Escludi da "public_roles" e "phone_roles" ruoli artistici/spettacolo (attore, attrice, figurante,
ballerino, cantante, ecc.) e ruoli sanitari/pure assistenziali, a meno che non siano descritti
esplicitamente come customer service in contesto business.
"""


def groq_full_analyze(text: str) -> dict:
    empty = {
        "name": "",
        "surname": "",
        "email": "",
        "phones": [],
        "has_public_contact": False,
        "has_phone_contact": False,
        "public_roles": [],
        "phone_roles": [],
        "has_basic_it_skills": False,
        "it_skills": [],
        "profile_keywords": [],
        "ai_summary": "",
        "suitability_label": "",
        "ai_support": "",
    }
    if not text or not text.strip():
        return empty
    if groq_client is None:
        return empty
    try:
        snippet = text[:12000]
        chat_completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": FULL_SYS},
                {
                    "role": "user",
                    "content": (
                        "Analizza il seguente CV e compila TUTTI i campi del JSON richiesto:\n"
                        f"\"\"\"{snippet}\"\"\""
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=800,
        )
        content = (chat_completion.choices[0].message.content or "").strip()
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return empty
        js = content[start:end + 1]
        data = json.loads(js)
    except Exception:
        return empty
    for k in empty.keys():
        data.setdefault(k, empty[k])
    return data


# ===================== NORMALIZZAZIONE TERMINOLOGIA KEYWORDS =====================
def normalize_role_label(role: str, kind: str):
    low = (role or "").strip().lower()
    if not low:
        return None
    if any(w in low for w in ["figurante", "attore", "attrice", "teatro", "teatrale",
                              "dancer", "ballerino", "ballerina", "cantante", "actor", "actress"]):
        return None
    if "nutrice" in low:
        return "Caregiver"
    if kind == "phone":
        if "call center" in low or "contact center" in low:
            return "Call Center Agent"
        if "telesales" in low or "telemarketing" in low:
            return "Telesales Agent"
        if "help desk" in low or "service desk" in low:
            return "Help Desk Agent"
        if ("customer service" in low or "customer care" in low or
                "servizio clienti" in low or "assistenza clienti" in low):
            return "Customer Service Agent"
        if ("phone" in low or "telefonic" in low or "telefonico" in low or
                "telefonica" in low or "telefoniche" in low):
            return "Phone Support"
    if "assistant store manager" in low:
        return "Assistant Store Manager"
    if "store manager" in low:
        return "Store Manager"
    if "sales consultant" in low or "sales advisor" in low:
        return "Sales Consultant"
    if ("sales assistant" in low or "shop assistant" in low or "store assistant" in low or
            "sales associate" in low or "retail sales" in low or
            "addetto vendite" in low or "addetta vendite" in low or "commess" in low):
        return "Sales Assistant"
    if ("customer service" in low or "customer care" in low or
            "servizio clienti" in low or "assistenza clienti" in low):
        return "Customer Service"
    if ("receptionist" in low or "reception" in low or
            "front desk" in low or "front office" in low):
        return "Receptionist"
    if "cameriere" in low or "cameriera" in low or "waiter" in low or "waitress" in low:
        return "Waiter"
    if "banconier" in low or "banconist" in low or ("counter" in low and ("bar" in low or "shop" in low or "store" in low)):
        return "Counter Assistant"
    if "barista" in low or "barman" in low or "bartender" in low or "barmaid" in low:
        return "Bartender"
    if "cashier" in low or "cassiere" in low or "cassiera" in low:
        return "Cashier"
    if ("promoter" in low or "brand ambassador" in low or
            "hostess" in low or "steward" in low or "promozione" in low):
        return "Promoter"
    if "tour guide" in low or "guida turistica" in low:
        return "Tour Guide"
    if "concierge" in low:
        return "Concierge"
    if "beauty consultant" in low or "beauty advisor" in low or "consulente di bellezza" in low:
        return "Beauty Consultant"
    if "guest relation" in low or "guest relations" in low or "guest service" in low:
        return "Guest Relations"
    if kind == "phone":
        return "Customer Service Agent"
    if kind == "public":
        return "Customer-facing Role"
    return None


def build_keywords_string(raw: str, screen_info: dict) -> str:
    labels = []
    for r in screen_info.get("phone_roles", []):
        lab = normalize_role_label(str(r), "phone")
        if not lab:
            continue
        if lab not in labels:
            labels.append(lab)
        if len(labels) >= 5:
            break
    if len(labels) < 5:
        for r in screen_info.get("public_roles", []):
            lab = normalize_role_label(str(r), "public")
            if not lab:
                continue
            if lab not in labels:
                labels.append(lab)
            if len(labels) >= 5:
                break
    if not labels:
        text_low = raw.lower()
        patterns = [
            ("Call Center Agent", ["call center", "contact center"]),
            ("Telesales Agent", ["telesales", "telemarketing"]),
            ("Customer Service Agent", ["customer service", "customer care", "servizio clienti", "assistenza clienti"]),
            ("Sales Assistant", ["sales assistant", "shop assistant", "store assistant",
                                 "sales associate", "addetto vendite", "addetta vendite", "commess"]),
            ("Sales Consultant", ["sales consultant", "sales advisor", "consulente alle vendite", "consulente di vendita"]),
            ("Assistant Store Manager", ["assistant store manager"]),
            ("Store Manager", ["store manager"]),
            ("Waiter", ["cameriere", "cameriera", "waiter", "waitress"]),
            ("Bartender", ["barista", "barman", "bartender", "barmaid"]),
            ("Cashier", ["cashier", "cassiere", "cassiera"]),
            ("Receptionist", ["receptionist", "front desk", "front office", "reception"]),
            ("Promoter", ["promoter", "brand ambassador", "hostess", "steward"]),
        ]
        for name, pats in patterns:
            if any(p in text_low for p in pats):
                if name not in labels:
                    labels.append(name)
                if len(labels) >= 5:
                    break
    return ", ".join(labels) if labels else "-"


def classify_label(text: str, screen_info: dict) -> str:
    has_phone = bool(screen_info.get("has_phone_contact"))
    has_public = bool(screen_info.get("has_public_contact"))
    has_it = bool(screen_info.get("has_basic_it_skills"))

    if not has_phone:
        has_phone = text_has_phone(text)
    if not has_public:
        has_public = text_has_public(text)

    cs_like = text_has_phone(text) or text_has_public(text)

    if has_it and has_phone:
        return "Adatto"
    if cs_like or has_public or has_phone:
        return "Parzialmente adatto"
    return "Non adatto"


def label_to_score(label: str) -> int:
    if label == "Adatto":
        return 100
    if label == "Parzialmente adatto":
        return 50
    return 0


def normalize(ai: dict, raw: str, fname: str) -> dict:
    email_ai = (ai.get("email") or "").strip()
    email = email_ai or extract_email(raw)

    phones_ai_raw = ai.get("phones") or []
    phones_ai_clean = []
    iterable = phones_ai_raw if isinstance(phones_ai_raw, list) else [phones_ai_raw]
    for item in iterable:
        if isinstance(item, (dict, list)):
            continue
        s = str(item).strip()
        if s:
            phones_ai_clean.append(s)
    phones_regex = extract_phones(raw)
    all_phones, seen = [], set()
    for p in phones_ai_clean + phones_regex:
        s = str(p).strip()
        if not s:
            continue
        if s not in seen:
            seen.add(s)
            all_phones.append(s)

    fullname = resolve_name(ai.get("name", ""), ai.get("surname", ""), raw, email)

    screen_info = {
        "has_public_contact": bool(ai.get("has_public_contact")),
        "has_phone_contact": bool(ai.get("has_phone_contact")),
        "public_roles": ai.get("public_roles") or [],
        "phone_roles": ai.get("phone_roles") or [],
        "has_basic_it_skills": bool(ai.get("has_basic_it_skills")),
        "it_skills": ai.get("it_skills") or [],
    }

    pk_raw = ai.get("profile_keywords") or []
    if isinstance(pk_raw, list):
        pk_clean = [str(x).strip() for x in pk_raw if str(x).strip()]
    else:
        pk_clean = [str(pk_raw).strip()] if str(pk_raw).strip() else []
    if pk_clean:
        keywords_str = ", ".join(pk_clean[:4])
    else:
        keywords_str = build_keywords_string(raw, screen_info)

    label = classify_label(raw, screen_info)
    score = label_to_score(label)

    ai_summary_text = (ai.get("ai_summary") or "").strip()
    if ai_summary_text:
        lines = [l.strip() for l in ai_summary_text.splitlines() if l.strip()]
        ai_summary_text = "\n".join(lines[:4])

    ai_support_text = (ai.get("ai_support") or "").strip()
    ai_support_text = re.sub(r"\s+", " ", ai_support_text)

    return {
        "Nome file": fname,
        "Nome e Cognome": fullname,
        "Valutazione di adeguatezza": score,
        "Classe adeguatezza": label,
        "Keywords": keywords_str,
        "AI Assisted": ai_summary_text,
        "AI Screening": ai_support_text,
        "E-Mail": email,
        "Numero/Numeri telefono": " | ".join(all_phones),
    }


# ===================== CONVERSIONE A PDF + DATA URI =====================
def to_pdf_bytes(original_bytes: bytes, ext: str) -> bytes:
    ext = (ext or "").lower()
    if ext == "pdf":
        return original_bytes
    if ext == "docx" and docx2pdf_convert is not None:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                in_path = os.path.join(tmpdir, "input.docx")
                out_path = os.path.join(tmpdir, "output.pdf")
                with open(in_path, "wb") as f_in:
                    f_in.write(original_bytes)
                docx2pdf_convert(in_path, out_path)
                with open(out_path, "rb") as f_out:
                    return f_out.read()
        except Exception:
            return original_bytes
    return original_bytes


def build_pdf_data_uri(filename: str, original_bytes: bytes) -> str:
    ext = filename.split(".")[-1].lower()
    pdf_bytes = to_pdf_bytes(original_bytes, ext)
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    return f"data:application/pdf;base64,{b64}"


# ===================== STATO AVVISO NON LETTURA =====================
if "hide_unreadable_info" not in st.session_state:
    st.session_state["hide_unreadable_info"] = False

# ===================== UPLOADER =====================
uploaded_files = st.file_uploader(
    "Import CV",
    accept_multiple_files=True,
    type=["pdf", "doc", "docx", "odt", "txt", "rtf"],
    label_visibility="collapsed"
)

# ===================== MESSAGGI STANDARD =====================
standard_message = (
    "Buongiorno,\n"
    "abbiamo ricevuto il tuo CV in merito alla posizione di operatore telefonico. "
    "Quando preferisci essere contattato?\n"
    "Grazie e buona giornata"
)

email_subject = "Selezione per attività operatore telefonico"

# ===================== AVVISO MANCANZA API KEY =====================
if uploaded_files and groq_client is None:
    st.error(
        "GROQ_API_KEY non impostata nei secrets/variabili d'ambiente. "
        "Imposta la chiave Groq e riavvia l'app."
    )

# ===================== ANALISI AUTOMATICA =====================
if uploaded_files and groq_client is not None:
    status_box = st.empty()
    status_box.info("Analisi in corso sui CV caricati...")

    rows = []
    unreadable_files = []

    for f in uploaded_files:
        original_bytes = f.getvalue()
        text_cv = extract_text(f, original_bytes)

        if not text_cv or not text_cv.strip():
            unreadable_files.append(f.name)
            continue

        ai_full = groq_full_analyze(text_cv)
        base_row = normalize(ai_full, text_cv, f.name)

        pdf_data_uri = build_pdf_data_uri(f.name, original_bytes)

        label = base_row["Classe adeguatezza"]
        whatsapp_url = ""
        if label in ("Adatto", "Parzialmente adatto"):
            phones_str = base_row.get("Numero/Numeri telefono", "")
            first_phone = phones_str.split(" | ")[0].strip() if phones_str else ""
            if first_phone:
                # normalizza numero: solo cifre, incluso prefisso internazionale (es. 39...)
                phone_digits = re.sub(r"[^\d]", "", first_phone)
                if phone_digits:
                    # utilizzo endpoint ufficiale HTTPS compatibile con Android, iOS, desktop
                    # https://api.whatsapp.com/send?phone=<NUM>&text=<TEXTPERCENTENCODED>
                    encoded_text = quote(standard_message)
                    whatsapp_url = f"https://api.whatsapp.com/send?phone={phone_digits}&text={encoded_text}"

        base_row["Read"] = pdf_data_uri
        base_row["Whatsapp"] = whatsapp_url
        rows.append(base_row)

    status_box.empty()
    st.success("Analisi completata.")

    # INFO CV non letti
    if unreadable_files and not st.session_state["hide_unreadable_info"]:
        with st.container():
            st.markdown(
                """
                <div style="border:1px solid #ff4b4b;padding:12px;border-radius:8px;background:rgba(80,0,0,0.4);">
                  <div style="color:#ffdddd;font-size:12px;margin-bottom:6px;">
                    Attenzione: alcuni CV non sono stati letti correttamente
                    (PDF solo immagini o formati non supportati) e non sono stati analizzati.
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.write(", ".join(unreadable_files))
            if st.button("OK", key="close_unreadable_info"):
                st.session_state["hide_unreadable_info"] = True

    if rows:
        df = pd.DataFrame(rows)

        # costruttore mailto universale
        if "E-Mail" in df.columns:
            def make_mailto(x: str) -> str:
                if isinstance(x, str) and x.strip():
                    subject_enc = quote_plus(email_subject)
                    body_enc = quote(standard_message)
                    # mailto: compatibile con tutti i sistemi che hanno un client e-mail associato
                    return (
                        f"mailto:{x}"
                        f"?subject={subject_enc}"
                        f"&body={body_enc}"
                    )
                return ""
            df["E-Mail"] = df["E-Mail"].apply(make_mailto)

        desired_cols = [
            "Nome file",
            "Nome e Cognome",
            "Valutazione di adeguatezza",
            "Classe adeguatezza",
            "Keywords",
            "AI Assisted",
            "AI Screening",
            "Read",
            "Numero/Numeri telefono",
            "Whatsapp",
            "E-Mail",
        ]
        df = df[[c for c in desired_cols if c in df.columns]]

        n_rows = len(df)
        header_h = 40
        row_h = 32
        padding = 24
        table_height = min(600, header_h + n_rows * row_h + padding)

        st.data_editor(
            df,
            hide_index=True,
            use_container_width=True,
            height=table_height,
            num_rows="fixed",
            column_config={
                "Valutazione di adeguatezza": st.column_config.ProgressColumn(
                    "Valutazione (%)",
                    min_value=0,
                    max_value=100,
                    format="%d%%",
                    help="0 = Non adatto, 50 = Parzialmente, 100 = Adatto",
                ),
                "Read": st.column_config.LinkColumn(
                    "PDF",
                    display_text="PDF",
                    help="Apri il curriculum in formato PDF"
                ),
                "Whatsapp": st.column_config.LinkColumn(
                    "WhatsApp",
                    display_text="WhatsApp",
                    help="Invia un messaggio WhatsApp precompilato"
                ),
                "E-Mail": st.column_config.LinkColumn(
                    "E-mail",
                    display_text="E-mail",
                    help="Invia una e-mail precompilata"
                ),
            },
        )

# ===================== FOOTER =====================
st.markdown(
    '''
    <div class="footer">
        Tool developed by Fabio Galli using Vibe Coding, powered by Groq LLM API.
    </div>
    ''',
    unsafe_allow_html=True
)






