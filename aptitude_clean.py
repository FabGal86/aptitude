import os
import re
import io
import json
import base64
import pandas as pd
import streamlit as st
from PyPDF2 import PdfReader
from docx import Document
from difflib import SequenceMatcher
from urllib.parse import quote
from groq import Groq

# ===================== CONFIGURAZIONE PAGINA =====================
st.set_page_config(page_title="APTITUDE", layout="centered")

# ===================== MODERN CSS (MIGLIORATA PER SMARTPHONE + SFONDO GRIGIO) =====================
st.markdown("""
<style>

/* SFONDO GRIGIO UNIFORME SU TUTTI I DEVICE */
html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] > .main {
    background-color: #202020 !important;  /* grigio scuro uniforme */
}

/* CONTAINER PRINCIPALE RESPONSIVE */
[data-testid="stAppViewContainer"] > .main .block-container {
    max-width: 1200px;
    padding-top: 1.5rem;
    padding-bottom: 4rem;
    padding-left: 1.5rem;
    padding-right: 1.5rem;
}

/* SCHERMI MEDI (tablet / laptop in restore down) */
@media (max-width: 992px) {
    [data-testid="stAppViewContainer"] > .main .block-container {
        max-width: 100%;
        padding-left: 1.2rem;
        padding-right: 1.2rem;
        padding-top: 1.2rem;
    }

    #custom-title {
        font-size: 32px;
        white-space: normal;           /* consente l'andare a capo */
        line-height: 1.2;
    }

    #subtitle {
        font-size: 16px;
    }
}

/* SMARTPHONE / TABLET PICCOLI (~fino a 5.8") */
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
        white-space: normal;           /* titolo adattabile su più righe */
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
        position: static;              /* niente overlay su schermi piccoli */
        font-size: 9px;
        padding: 6px;
    }
}

/* TITOLO */
#custom-title {
    color: #00ff00 !important;  /* verde fluo */
    font-size: 40px;
    font-weight: 900;
    text-align: center;
    margin-top: 16px;
    font-family: 'Montserrat', sans-serif;
    letter-spacing: 0.03em;
}

/* SOTTITITOLO */
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
    background: rgba(40,40,40,0.95);             /* grigio coerente col resto */
    border: 1px solid rgba(0,255,0,0.25);
    border-radius: 12px;
    padding: 14px;
    box-shadow: 0px 0px 8px rgba(0,255,0,0.18);
}

[data-testid="stFileUploader"] section {
    background: transparent;
}

/* BUTTON NORMALI (Browse ecc.) */
button {
    background-color: #303030 !important;
    color: #f0f0f0 !important;
    border: 1px solid #555 !important;
    border-radius: 8px !important;
    padding: 8px 22px !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    transition: 0.2s ease-in-out !important;
}

button:hover {
    background-color: #454545 !important;
    border-color: #777 !important;
}

/* FOOTER */
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

/* TABELLA / DATA EDITOR: sfondo coerente */
[data-testid="stDataFrame"], [data-testid="stDataFrame"] div {
    background-color: #222222 !important;
}

/* Riduce leggermente la larghezza delle colonne su schermi piccoli */
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

# ===================== CONFIG GROQ =====================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# ===================== PREFISSI TEL. =====================
ALLOWED_PREFIXES = ["+39", "+44", "+353"]

# ===================== KEYWORDS – ATTIVITÀ TELEFONICHE (FALLBACK) =====================
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

# ===================== KEYWORDS – CONTATTO CON IL PUBBLICO / VENDITA (FALLBACK) =====================
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
    pattern = r"\\b" + r"\\s+".join(re.escape(w) for w in words) + r"\\b"
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


# ===================== LETTURA FILE =====================
def extract_text(file) -> str:
    ext = file.name.split(".")[-1].lower()
    try:
        if ext == "pdf":
            file.seek(0)
            pdf = PdfReader(file)
            return "\\n".join([p.extract_text() or "" for p in pdf.pages])
        if ext == "docx":
            file.seek(0)
            return "\\n".join(p.text for p in Document(file).paragraphs)
        file.seek(0)
        return file.read().decode("utf-8", "ignore")
    except Exception:
        return ""


# ===================== EMAIL / TEL =====================
def extract_email(text: str) -> str:
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}", text)
    return m.group(0) if m else ""


def extract_phones(text: str):
    raw = re.findall(r"(\\+\\d[0-9\\s().-]{7,18}\\d)", text)
    res, seen = [], set()
    for c in raw:
        norm = re.sub(r"[^\\d+]", "", c)
        if not any(norm.startswith(p) for p in ALLOWED_PREFIXES):
            continue
        d = re.sub(r"[^\\d]", "", norm)
        if 8 <= len(d) <= 15:
            if norm not in seen:
                seen.add(norm)
                res.append(norm)
    return res


# ===================== NAME EXTRACTION =====================
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
    nick = re.sub(r"[\\d_.-]+", " ", email.split("@")[0])
    p = [x for x in nick.split() if len(x) > 1]
    return f"{p[0].capitalize()} {p[1].capitalize()}" if len(p) >= 2 else ""


def clean_name(n: str) -> str:
    p = [
        re.sub(r"\\d", "", x)
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
e valuta l'adeguatezza per ruoli di call center / contact center / customer service telefonico,
tenendo conto di QUALSIASI esperienza di contatto con il pubblico
e della presenza o assenza di competenze informatiche di base.

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
  "ai_support": ""
}

[... testo del prompt identico alla versione precedente ...]
"""

# (per brevità ho lasciato "[... testo del prompt identico ...]" ma tu nel tuo file
# tieni l'intero FULL_SYS che avevi già, senza modifiche, così l'AI Screening resta uguale)


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
        "ai_support": "",
    }
    if not text or not text.strip():
        return empty
    if groq_client is None:
        return empty
    try:
        chat_completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": FULL_SYS},
                {
                    "role": "user",
                    "content": (
                        "Analizza il seguente CV e compila TUTTI i campi del JSON richiesto:\\n"
                        f"\"\"\"{text[:12000]}\"\"\""
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


def build_keywords_string(raw: str, label: str, screen_info: dict) -> str:
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
    if not has_phone and not has_public:
        has_phone = text_has_phone(text)
        has_public = text_has_public(text)
    if has_phone:
        return "Adeguato"
    if has_public:
        return "Parzialmente adeguato"
    return "Non adeguato"


def normalize(ai: dict, raw: str, fname: str) -> dict:
    email = (ai.get("email") or "").strip() or extract_email(raw)
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
    label = classify_label(raw, screen_info)
    keywords_str = build_keywords_string(raw, label, screen_info)
    ai_support_text = (ai.get("ai_support") or "").strip()
    ai_support_text = re.sub(r"\\s+", " ", ai_support_text)
    if ai_support_text and ai_support_text[-1] not in ".!?":
        ai_support_text += "."
    return {
        "Nome file": fname,
        "Nome e Cognome": fullname,
        "E-Mail": email,
        "Numero/Numeri telefono": " | ".join(all_phones),
        "Valutazione di adeguatezza": label,
        "Keywords": keywords_str,
        "AI Screening": ai_support_text,
    }


MIME_BY_EXT = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "odt": "application/vnd.oasis.opendocument.text",
    "rtf": "application/rtf",
    "txt": "text/plain",
}


def build_data_uri(filename: str, original_bytes: bytes) -> str:
    ext = filename.split(".")[-1].lower()
    mime = MIME_BY_EXT.get(ext, "application/octet-stream")
    b64 = base64.b64encode(original_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"


uploaded_files = st.file_uploader(
    "Import CV",
    accept_multiple_files=True,
    type=["pdf", "doc", "docx", "odt", "txt", "rtf"],
    label_visibility="collapsed"
)

if uploaded_files and groq_client is None:
    st.error(
        "GROQ_API_KEY non impostata nei secrets/variabili d'ambiente. "
        "Imposta la chiave Groq e riavvia l'app."
    )

if uploaded_files and groq_client is not None:
    st.info("Analisi in corso sui CV caricati...")
    rows = []
    standard_message = (
        "Buongiorno,\\n"
        "abbiamo ricevuto il tuo CV in merito alla posizione di operatore telefonico. "
        "Quando preferisci essere contattato?\\n"
        "Grazie e buona giornata"
    )
    for f in uploaded_files:
        text_cv = extract_text(f)
        ai_full = groq_full_analyze(text_cv)
        base_row = normalize(ai_full, text_cv, f.name)
        original_bytes = f.getvalue()
        file_data_uri = build_data_uri(f.name, original_bytes)
        label = base_row["Valutazione di adeguatezza"]
        whatsapp_url = ""
        if label in ("Adeguato", "Parzialmente adeguato"):
            phones_str = base_row.get("Numero/Numeri telefono", "")
            first_phone = phones_str.split(" | ")[0].strip() if phones_str else ""
            if first_phone:
                phone_digits = re.sub(r"[^\\d]", "", first_phone)
                if phone_digits:
                    encoded_text = quote(standard_message)
                    whatsapp_url = f"https://wa.me/{phone_digits}?text={encoded_text}"
        base_row["Read"] = file_data_uri
        base_row["Whatsapp"] = whatsapp_url
        rows.append(base_row)

    if rows:
        df = pd.DataFrame(rows)

        if "E-Mail" in df.columns:
            def make_mailto(x: str) -> str:
                if isinstance(x, str) and x.strip():
                    subject = "Selezione per attività operatore telefonico"
                    return (
                        f"mailto:{x}"
                        f"?subject={quote(subject)}"
                        f"&body={quote(standard_message)}"
                    )
                return ""
            df["E-Mail"] = df["E-Mail"].apply(make_mailto)

        desired_cols = [
            "Nome file",
            "Nome e Cognome",
            "Numero/Numeri telefono",
            "Valutazione di adeguatezza",
            "Keywords",
            "AI Screening",
            "Read",
            "Whatsapp",
            "E-Mail",
        ]
        df = df[[c for c in desired_cols if c in df.columns]]

        st.success("Analisi completata.")

        st.data_editor(
            df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Read": st.column_config.LinkColumn(
                    "Read",
                    display_text="File"
                ),
                "Whatsapp": st.column_config.LinkColumn(
                    "Whatsapp",
                    display_text="WhatsApp"
                ),
                "E-Mail": st.column_config.LinkColumn(
                    "E-Mail",
                    display_text="E-Mail"
                ),
            },
        )

st.markdown(
    '''
    <div class="footer">
        Tool developed by Fabio Galli using Vibe Coding, powered by Groq LLM API.
    </div>
    ''',
    unsafe_allow_html=True
)
