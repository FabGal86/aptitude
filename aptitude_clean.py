# TLK Aptitude Screener v2 (con legenda esplicita)
# - Pipeline a 2 passaggi: EXTRACT (evidence-based) -> SCORE (3 ruoli: inbound/outbound/appointment)
# - Evidenze testuali auditabili
# - IT skills estese (Office + CRM + Ticketing + Contact Center)
# - Telefono: strutturato vs occasionale + inbound/outbound/mixed
# - Estrazione contatti migliorata (numeri con/senza prefisso, normalizzazione)
# - UI: legenda chiara, filtri, export CSV, colonne evidenze e confidence
#
# Requisiti:
#   pip install streamlit pandas PyPDF2 python-docx groq pdf2image pytesseract docx2pdf

import os
import re
import io
import json
import base64
import tempfile
from typing import Dict, Any, List, Optional, Tuple

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
st.set_page_config(page_title="APTITUDE v2", layout="wide")

# ===================== MODERN CSS – RESPONSIVE + SFONDO GRIGIO =====================
st.markdown(
    """
<style>
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > .main { background-color: #202020 !important; }

[data-testid="stAppViewContainer"] > .main .block-container {
    max-width: 1500px;
    padding-top: 1.0rem;
    padding-bottom: 4rem;
    padding-left: 1.2rem;
    padding-right: 1.2rem;
}

#custom-title {
    color: #00ff00 !important;
    font-size: 38px;
    font-weight: 900;
    text-align: center;
    margin-top: 8px;
    font-family: 'Montserrat', sans-serif;
    letter-spacing: 0.03em;
}
#subtitle {
    color: #a0ffb0 !important;
    font-size: 15px;
    font-style: italic;
    text-align: center;
    margin-top: 3px;
    font-family: 'Montserrat', sans-serif;
    opacity: 0.9;
}

[data-testid="stFileUploader"] {
    background: rgba(40,40,40,0.95);
    border: 1px solid rgba(0,255,0,0.25);
    border-radius: 12px;
    padding: 14px;
    box-shadow: 0px 0px 8px rgba(0,255,0,0.18);
}
[data-testid="stFileUploader"] section { background: transparent; }

button {
    background-color: #198754 !important;
    color: #f0f0f0 !important;
    border: 1px solid #198754 !important;
    border-radius: 8px !important;
    padding: 8px 18px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    transition: 0.2s ease-in-out !important;
}
button:hover { background-color: #157347 !important; border-color: #146c43 !important; }

.footer {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    padding: 8px;
    text-align: center;
    color: #b4ffbe;
    background: rgba(20,20,20,0.9);
    border-top: 1px solid rgba(0,255,0,0.25);
    font-size: 11px;
    font-family: 'Montserrat', sans-serif;
}

.small-note { color: #b4ffbe; opacity: 0.9; font-size: 12px; }
</style>
""",
    unsafe_allow_html=True,
)

# ===================== HEADER =====================
st.markdown('<div id="custom-title">TLK Aptitude Screener</div>', unsafe_allow_html=True)
st.markdown('<div id="subtitle">AI-Assisted • v2 (Extract → Score)</div>', unsafe_allow_html=True)

# ===================== CONFIG GROQ =====================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL_EXTRACT = os.getenv("GROQ_MODEL_EXTRACT", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
GROQ_MODEL_SCORE = os.getenv("GROQ_MODEL_SCORE", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# ===================== CONFIG APP (SIDEBAR) =====================
with st.sidebar:
    st.markdown("### Impostazioni")
    default_cc = st.checkbox(
        "Preferisci +39 se mancante",
        value=True,
        help="Se un numero sembra italiano e non ha prefisso, aggiunge +39 (euristica).",
    )
    allowed_prefixes_str = st.text_input(
        "Prefissi accettati (comma-separated, opzionale)",
        value="+39,+44,+353",
        help="Lascia vuoto per accettare tutti i prefissi. Esempio: +39,+41,+33",
    )
    min_extract_conf = st.slider("Soglia Confidence estrazione", 0.0, 1.0, 0.35, 0.05)
    st.markdown("---")
    show_legend_expanded = st.checkbox("Legenda: apri automaticamente", value=False)
    show_debug = st.checkbox("Mostra debug JSON (per file)", value=False)

    st.markdown("---")
    st.markdown("### Legenda (sintesi)")
    st.markdown("- **Alta** ≥ 75\n- **Media** 45–74\n- **Bassa** ≤ 44")
    st.markdown("**Phone structured**: esperienze con inbound/outbound/call center/dialer/script/KPI.")
    st.markdown("**Confidence estrazione**: affidabilità lettura (PDF testo vs OCR).")

ALLOWED_PREFIXES = [p.strip() for p in allowed_prefixes_str.split(",") if p.strip()]
ACCEPT_ALL_PREFIXES = len(ALLOWED_PREFIXES) == 0

# ===================== UTIL =====================
def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def safe_json_loads_maybe(content: str) -> Optional[dict]:
    """Estrae un JSON da testo (gestisce backticks e testo extra)."""
    if not content:
        return None
    s = content.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s.strip(), flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s.strip())
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    js = s[start : end + 1]
    js = js.replace("\t", " ")
    js = re.sub(r",\s*([}\]])", r"\1", js)
    try:
        return json.loads(js)
    except Exception:
        return None

def detect_language_hint(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in ["esperienza", "formazione", "competenze", "lavoro"]):
        return "it"
    if any(w in t for w in ["experience", "skills", "education"]):
        return "en"
    if any(w in t for w in ["experiencia", "habilidades", "educación"]):
        return "es"
    if any(w in t for w in ["erfahrung", "kenntnisse", "ausbildung"]):
        return "de"
    return "auto"

# ===================== LEGENDA (UI) =====================
def render_legend(expanded: bool = False):
    st.markdown("### Legenda valutazione")
    st.info(
        "L’app produce **3 valutazioni separate** (Inbound, Outbound, Presa Appuntamenti). "
        "Ogni valutazione usa **evidenze testuali** estratte dal CV."
    )

    with st.expander("Mostra criteri completi (Score, Label, Phone structured, Confidence)", expanded=expanded):
        st.markdown(
            """
**Output per ciascun ruolo**
- **Score (0–100)**: punteggio complessivo.
- **Label**:
  - **Alta** = score ≥ 75
  - **Media** = 45–74
  - **Bassa** = ≤ 44
- **Reasons**: max 3 motivi sintetici in italiano.
- **Evidence**: max 3 estratti del CV a supporto (auditabili).

**Phone structured**
- Conta quante esperienze risultano **telefoniche strutturate** (non uso occasionale del telefono).
- È “strutturato” se nel CV compaiono segnali come: **inbound/outbound**, call center/contact center, campagne, dialer, script, presa appuntamenti, KPI/target, volumi chiamate.

**Phone type**
- **inbound**: chiamate in entrata / assistenza
- **outbound**: chiamate in uscita / vendita / appuntamenti
- **mixed**: entrambe
- **none**: non emerge telefonico strutturato

**Confidence estrazione (0–1)**
- **≥ 0.75**: estrazione affidabile (PDF testuale / testo chiaro)
- **0.45–0.74**: estrazione discreta (formati strani / OCR parziale)
- **< 0.45**: rischio alto errori (PDF immagine / OCR debole) → verificare manualmente
"""
        )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.success("**Alta**: ≥ 75\n\nProfilo forte per il ruolo selezionato.")
    with c2:
        st.warning("**Media**: 45–74\n\nProfilo coerente ma con elementi da verificare.")
    with c3:
        st.error("**Bassa**: ≤ 44\n\nPoche evidenze o competenze non allineate al ruolo.")

# Mostra legenda centrale (esplicita)
render_legend(expanded=show_legend_expanded)

# ===================== LETTURA FILE + OCR =====================
def ocr_pdf_bytes(data: bytes, max_pages: int = 8) -> Tuple[str, float]:
    """OCR per PDF immagine. Ritorna (testo, confidence approx)."""
    if not OCR_AVAILABLE or not data:
        return "", 0.0
    try:
        images = convert_from_bytes(data, first_page=1, last_page=max_pages)
        texts = []
        nonempty = 0
        for img in images:
            txt = pytesseract.image_to_string(img)
            txt = (txt or "").strip()
            if txt:
                nonempty += 1
                texts.append(txt)
        if not texts:
            return "", 0.0
        conf = min(1.0, 0.25 + 0.1 * nonempty)  # euristica
        return "\n".join(texts), conf
    except Exception:
        return "", 0.0

def extract_text(file, original_bytes: bytes = None) -> Tuple[str, float, str]:
    """
    Ritorna (text, confidence, reason).
    confidence: 1.0 se estrazione testuale ok, 0.4-0.8 se OCR, 0 se fallisce.
    """
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
            text = "\n".join(pages_text).strip()
            if text:
                return text, 1.0, "pdf_text"
            if original_bytes is not None:
                ocr_text, ocr_conf = ocr_pdf_bytes(original_bytes)
                return ocr_text.strip(), ocr_conf, "pdf_ocr" if ocr_text.strip() else "pdf_unreadable"
            return "", 0.0, "pdf_unreadable"

        if ext == "docx":
            file.seek(0)
            txt = "\n".join(p.text for p in Document(file).paragraphs).strip()
            return txt, (1.0 if txt else 0.0), "docx_text" if txt else "docx_unreadable"

        # DOC/ODT/RTF/TXT: best-effort
        file.seek(0)
        raw = file.read()
        try:
            txt = raw.decode("utf-8", "ignore").strip()
        except Exception:
            txt = ""
        if len(txt) < 200 and ext in ("doc", "odt", "rtf"):
            return "", 0.0, f"{ext}_unsupported"
        return txt, (1.0 if txt else 0.0), f"{ext}_text" if txt else f"{ext}_unreadable"
    except Exception:
        if ext == "pdf" and original_bytes:
            ocr_text, ocr_conf = ocr_pdf_bytes(original_bytes)
            return ocr_text.strip(), ocr_conf, "pdf_ocr" if ocr_text.strip() else "pdf_unreadable"
        return "", 0.0, "extract_error"

# ===================== EMAIL / TELEFONI =====================
def extract_email(text: str) -> str:
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text or "")
    return m.group(0) if m else ""

def normalize_phone_candidate(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"[^\d+]", "", s)
    s = re.sub(r"^\+{2,}", "+", s)
    return s

def looks_like_italian_national(num_digits: str) -> bool:
    return len(num_digits) == 10 and num_digits.startswith("3")

def extract_phones(text: str, prefer_cc39_if_missing: bool = True) -> List[str]:
    t = text or ""
    found: List[str] = []
    seen = set()

    # 1) numeri con +
    for m in re.findall(r"(\+\d[0-9\s().-]{7,20}\d)", t):
        cand = normalize_phone_candidate(m)
        digits = re.sub(r"\D", "", cand)
        if not digits:
            continue
        if 8 <= len(digits) <= 15:
            if not ACCEPT_ALL_PREFIXES and not any(cand.startswith(p) for p in ALLOWED_PREFIXES):
                continue
            if cand not in seen:
                seen.add(cand)
                found.append(cand)

    # 2) numeri senza + (euristiche)
    for m in re.findall(r"(?<!\+)(?:\b\d[\d\s().-]{7,20}\d\b)", t):
        cand = re.sub(r"[^\d]", "", m)
        if not cand or len(cand) < 9 or len(cand) > 12:
            continue
        if len(cand) == 8 and cand.startswith(("19", "20")):
            continue

        if prefer_cc39_if_missing and looks_like_italian_national(cand):
            out = "+39" + cand
        else:
            out = cand

        if out.startswith("+") and (not ACCEPT_ALL_PREFIXES) and (not any(out.startswith(p) for p in ALLOWED_PREFIXES)):
            continue

        if out not in seen:
            seen.add(out)
            found.append(out)

    return found

# ===================== NAME EXTRACTION (fallback) =====================
def extract_name_fallback(text: str) -> str:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    bad_tokens = [
        "work experience", "esperienza lavorativa", "esperienze lavorative",
        "esperienza professionale", "professional experience",
        "informazioni personali", "dati personali", "personal information",
        "curriculum vitae", "curriculum", "profile", "profilo",
        "education", "istruzione", "formazione",
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
        for x in (n or "").split()
        if x.lower() not in {"cv", "profilo", "profile", "mr", "sig", "sig.", "dr", "dott", "dott."}
    ]
    return " ".join(x.capitalize() for x in p[:3]) if len(p) >= 2 else ""

def resolve_fullname(name: str, surname: str, text: str, email: str) -> str:
    for v in [
        clean_name(f"{name} {surname}".strip()),
        clean_name(extract_name_fallback(text)),
        clean_name(guess_from_email(email)),
    ]:
        if v:
            return v
    return ""

# ===================== KEYWORDS / SIGNALS (deterministici) =====================
CRM_KW = ["Salesforce", "HubSpot", "Dynamics", "Zoho", "Pipedrive", "SAP CRM", "Oracle CRM", "CRM"]
TICKETING_KW = ["Zendesk", "Freshdesk", "Jira Service", "ServiceNow", "OTRS", "Ticketing", "Ticket"]
CC_TOOLS_KW = ["Genesys", "Avaya", "Five9", "Talkdesk", "NICE", "Twilio Flex", "Dialer", "CTI", "VoIP"]
OFFICE_KW = ["Microsoft Office", "MS Office", "Office 365", "Excel", "Word", "PowerPoint", "Outlook", "Google Sheets", "Google Docs", "Google Workspace", "Teams", "Zoom", "Meet"]

INBOUND_KW = ["inbound", "incoming calls", "chiamate in entrata", "assistenza", "supporto", "help desk", "service desk", "customer care"]
OUTBOUND_KW = ["outbound", "cold calling", "chiamate in uscita", "telemarketing", "telesales", "vendita telefonica", "recall", "presa appuntamenti", "lead qualification"]
KPI_KW = ["kpi", "target", "obiettivi", "quota", "conversion", "conversione", "chiusure", "appointments", "appuntamenti", "calls/day", "chiamate al giorno"]

def find_snippets(text: str, keywords: List[str], max_snippets: int = 3, window: int = 140) -> List[str]:
    if not text:
        return []
    low = text.lower()
    snippets: List[str] = []
    for kw in keywords:
        k = kw.lower()
        idx = low.find(k)
        if idx == -1:
            continue
        start = max(0, idx - window)
        end = min(len(text), idx + len(kw) + window)
        snip = text[start:end].strip().replace("\n", " ")
        snip = re.sub(r"\s+", " ", snip)
        if snip and snip not in snippets:
            snippets.append(snip[:220])
        if len(snippets) >= max_snippets:
            break
    return snippets

# ===================== GROQ PROMPTS =====================
EXTRACT_SYS = """
Sei un sistema di ESTRAZIONE dati da CV (italiano/inglese/spagnolo/tedesco).
Devi estrarre SOLO informazioni che sono SUPPORTATE dal testo del CV.

Regole:
- Restituisci SOLO un oggetto JSON valido, SENZA testo extra.
- Se un dato non è presente nel CV, usa stringa vuota, lista vuota o false.
- Per ogni affermazione importante (telefono strutturato, strumenti, KPI, vincoli) includi EVIDENZE:
  brevi estratti dal CV (max 220 caratteri).
- Non inventare aziende, date, numeri, KPI, strumenti.

Schema JSON:

{
  "schema_version": "2.0",
  "candidate": {"name": "", "surname": "", "email": "", "phones": []},
  "extraction": {"language_hint": "it|en|es|de|auto", "confidence": 0.0, "notes": ""},
  "experience": [
    {
      "role": "",
      "company": "",
      "start": "",
      "end": "",
      "description": "",
      "is_phone_structured": false,
      "phone_type": "inbound|outbound|mixed|none",
      "channels": ["phone","email","chat"],
      "tools": [],
      "kpi_signals": [],
      "evidence": []
    }
  ],
  "skills": {
    "office_tools": [],
    "crm_tools": [],
    "ticketing_tools": [],
    "contact_center_tools": [],
    "languages": [],
    "other": []
  },
  "constraints": [{"type": "", "evidence": ""}]
}

Vincoli:
- "experience" max 8 voci (più recenti o rilevanti).
- "is_phone_structured"=true SOLO se segnali chiari: inbound/outbound, call center, campagne, dialer, script, KPI, presa appuntamenti, volumi.
  Se è solo "contatti telefonici" generico/occasionale, lascialo false.
"""

SCORE_SYS = """
Sei un sistema di SCORING per ruoli telefonici basato SU JSON estratto (non usare info esterne).
Produci SOLO JSON valido:

{
  "schema_version": "2.0",
  "scores": {
    "inbound_call_center": {
      "score": 0,
      "label": "Alta|Media|Bassa",
      "dimensions": {
        "customer_orientation": 0,
        "process_discipline": 0,
        "stress_kpi_environment": 0,
        "digital_fluency": 0,
        "communication_clarity": 0
      },
      "reasons": [],
      "evidence": []
    },
    "outbound_telemarketing": {
      "score": 0,
      "label": "Alta|Media|Bassa",
      "dimensions": {
        "sales_drive": 0,
        "objection_handling": 0,
        "kpi_results": 0,
        "process_discipline": 0,
        "digital_fluency": 0
      },
      "reasons": [],
      "evidence": []
    },
    "appointment_setting": {
      "score": 0,
      "label": "Alta|Media|Bassa",
      "dimensions": {
        "lead_qualification": 0,
        "script_process": 0,
        "kpi_volumes": 0,
        "crm_usage": 0,
        "communication_clarity": 0
      },
      "reasons": [],
      "evidence": []
    }
  }
}

Regole:
- Ogni dimensione è 0-5 (intero).
- Score 0-100 deriva da media pesata delle dimensioni.
- Label: Alta >=75; Media 45-74; Bassa <=44.
- reasons max 3 frasi brevi in italiano.
- evidence max 3 estratti, scelti SOLO tra evidenze già presenti nel JSON estratto.
"""

def groq_extract(cv_text: str, read_conf: float, read_reason: str) -> Dict[str, Any]:
    empty = {
        "schema_version": "2.0",
        "candidate": {"name": "", "surname": "", "email": "", "phones": []},
        "extraction": {"language_hint": "auto", "confidence": 0.0, "notes": ""},
        "experience": [],
        "skills": {
            "office_tools": [], "crm_tools": [], "ticketing_tools": [],
            "contact_center_tools": [], "languages": [], "other": []
        },
        "constraints": []
    }
    if not cv_text or not cv_text.strip() or groq_client is None:
        return empty

    snippet = cv_text[:16000]
    lang_hint = detect_language_hint(cv_text)

    user_payload = {
        "text": snippet,
        "reading": {"method_confidence": read_conf, "method_reason": read_reason, "language_hint": lang_hint},
    }

    try:
        resp = groq_client.chat.completions.create(
            model=GROQ_MODEL_EXTRACT,
            messages=[
                {"role": "system", "content": EXTRACT_SYS},
                {"role": "user", "content": "Estrai i dati dal CV (testo + meta-lettura):\n" + json.dumps(user_payload, ensure_ascii=False)},
            ],
            temperature=0.05,
            max_tokens=1400,
        )
        content = (resp.choices[0].message.content or "").strip()
        data = safe_json_loads_maybe(content) or {}
    except Exception:
        data = {}

    out = empty
    if isinstance(data, dict):
        out["schema_version"] = str(data.get("schema_version", "2.0"))
        out["candidate"] = data.get("candidate", out["candidate"]) if isinstance(data.get("candidate"), dict) else out["candidate"]
        out["extraction"] = data.get("extraction", out["extraction"]) if isinstance(data.get("extraction"), dict) else out["extraction"]
        out["experience"] = data.get("experience", out["experience"]) if isinstance(data.get("experience"), list) else out["experience"]
        out["skills"] = data.get("skills", out["skills"]) if isinstance(data.get("skills"), dict) else out["skills"]
        out["constraints"] = data.get("constraints", out["constraints"]) if isinstance(data.get("constraints"), list) else out["constraints"]

    if isinstance(out["experience"], list) and len(out["experience"]) > 8:
        out["experience"] = out["experience"][:8]

    try:
        c = float(out["extraction"].get("confidence", 0.0))
        out["extraction"]["confidence"] = max(0.0, min(1.0, c))
    except Exception:
        out["extraction"]["confidence"] = 0.0

    return out

def groq_score(extracted: Dict[str, Any]) -> Dict[str, Any]:
    empty = {
        "schema_version": "2.0",
        "scores": {
            "inbound_call_center": {"score": 0, "label": "Bassa", "dimensions": {}, "reasons": [], "evidence": []},
            "outbound_telemarketing": {"score": 0, "label": "Bassa", "dimensions": {}, "reasons": [], "evidence": []},
            "appointment_setting": {"score": 0, "label": "Bassa", "dimensions": {}, "reasons": [], "evidence": []},
        },
    }
    if groq_client is None:
        return empty
    try:
        resp = groq_client.chat.completions.create(
            model=GROQ_MODEL_SCORE,
            messages=[
                {"role": "system", "content": SCORE_SYS},
                {"role": "user", "content": "Esegui scoring usando SOLO questo JSON estratto:\n" + json.dumps(extracted, ensure_ascii=False)},
            ],
            temperature=0.05,
            max_tokens=900,
        )
        content = (resp.choices[0].message.content or "").strip()
        data = safe_json_loads_maybe(content) or {}
        if not isinstance(data, dict) or "scores" not in data:
            return empty
        return data
    except Exception:
        return empty

# ===================== FALLBACK/ENRICH (deterministico) =====================
def deterministic_enrich(extracted: Dict[str, Any], raw_text: str, email_fallback: str, phones_fallback: List[str]) -> Dict[str, Any]:
    out = extracted if isinstance(extracted, dict) else {}

    cand = out.get("candidate", {}) if isinstance(out.get("candidate"), dict) else {}
    if not cand.get("email"):
        cand["email"] = email_fallback

    phones_ai = cand.get("phones", [])
    if not isinstance(phones_ai, list):
        phones_ai = []
    merged = []
    seen = set()
    for p in phones_ai + phones_fallback:
        s = str(p).strip()
        if not s:
            continue
        if s not in seen:
            seen.add(s)
            merged.append(s)
    cand["phones"] = merged
    out["candidate"] = cand

    skills = out.get("skills", {}) if isinstance(out.get("skills"), dict) else {}
    txt = raw_text or ""
    low = txt.lower()

    def fill_if_empty(field: str, kw_list: List[str]):
        arr = skills.get(field, [])
        if not isinstance(arr, list):
            arr = []
        if arr:
            return
        hits = []
        for k in kw_list:
            if k.lower() in low:
                hits.append(k)
        skills[field] = list(dict.fromkeys(hits))[:8] if hits else []

    fill_if_empty("office_tools", OFFICE_KW)
    fill_if_empty("crm_tools", CRM_KW)
    fill_if_empty("ticketing_tools", TICKETING_KW)
    fill_if_empty("contact_center_tools", CC_TOOLS_KW)
    out["skills"] = skills

    exp = out.get("experience", [])
    if not isinstance(exp, list):
        exp = []
    for e in exp:
        if not isinstance(e, dict):
            continue
        ev = e.get("evidence", [])
        if not isinstance(ev, list):
            ev = []

        desc = (e.get("description") or "")
        block = (str(e.get("role", "")) + " " + str(desc)).lower()
        is_struct = bool(e.get("is_phone_structured", False))

        if not is_struct:
            strong = any(k in block for k in ["call center", "contact center", "telemarketing", "telesales", "dialer", "cold calling"])
            strong = strong or (any(k in block for k in OUTBOUND_KW) and any(k in block for k in ["kpi", "target", "obiettiv", "conversion", "appunt"]))
            if strong:
                e["is_phone_structured"] = True
                if any(k in block for k in OUTBOUND_KW) and any(k in block for k in INBOUND_KW):
                    e["phone_type"] = "mixed"
                elif any(k in block for k in OUTBOUND_KW):
                    e["phone_type"] = "outbound"
                elif any(k in block for k in INBOUND_KW):
                    e["phone_type"] = "inbound"
                else:
                    e["phone_type"] = "mixed"
                if not ev:
                    ev = find_snippets(
                        txt,
                        ["call center", "contact center", "telemarketing", "telesales", "chiamate in uscita", "chiamate in entrata", "presa appuntamenti", "dialer", "kpi", "target"],
                        2,
                    )

        if not ev:
            ev2 = find_snippets(txt, ["crm", "salesforce", "hubspot", "zendesk", "kpi", "target", "appuntamenti"], 1)
            ev = ev2

        e["evidence"] = ev[:3]
    out["experience"] = exp

    ex = out.get("extraction", {}) if isinstance(out.get("extraction"), dict) else {}
    try:
        c = float(ex.get("confidence", 0.0))
    except Exception:
        c = 0.0
    ex["confidence"] = max(0.0, min(1.0, c))
    out["extraction"] = ex
    return out

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

# ===================== MESSAGGI STANDARD =====================
standard_message = (
    "Buongiorno,\n"
    "abbiamo ricevuto il tuo CV in merito alla posizione di operatore telefonico. "
    "Quando preferisci essere contattato?\n"
    "Grazie e buona giornata"
)
email_subject = "Selezione per attività operatore telefonico"

# ===================== UI UPLOADER =====================
uploaded_files = st.file_uploader(
    "Import CV",
    accept_multiple_files=True,
    type=["pdf", "docx", "txt", "doc", "odt", "rtf"],
    label_visibility="collapsed",
)

if uploaded_files and groq_client is None:
    st.error("GROQ_API_KEY non impostata. Imposta la chiave Groq e riavvia l'app.")

# ===================== ANALISI =====================
if uploaded_files and groq_client is not None:
    status_box = st.empty()
    status_box.info("Analisi in corso sui CV caricati...")

    rows = []
    unreadable = []

    for f in uploaded_files:
        original_bytes = f.getvalue()
        raw_text, read_conf, read_reason = extract_text(f, original_bytes)

        if not raw_text or not raw_text.strip():
            unreadable.append(f"{f.name} ({read_reason})")
            continue

        email_fb = extract_email(raw_text)
        phones_fb = extract_phones(raw_text, prefer_cc39_if_missing=default_cc)

        extracted = groq_extract(raw_text, read_conf, read_reason)
        extracted = deterministic_enrich(extracted, raw_text, email_fb, phones_fb)

        cand = extracted.get("candidate", {}) if isinstance(extracted.get("candidate"), dict) else {}
        fullname = resolve_fullname(cand.get("name", ""), cand.get("surname", ""), raw_text, cand.get("email", ""))

        llm_conf = 0.0
        try:
            llm_conf = float(extracted.get("extraction", {}).get("confidence", 0.0))
        except Exception:
            llm_conf = 0.0
        extraction_confidence = max(0.0, min(1.0, 0.55 * read_conf + 0.45 * llm_conf))

        scored = groq_score(extracted)

        scores = scored.get("scores", {}) if isinstance(scored.get("scores"), dict) else {}
        inbound = scores.get("inbound_call_center", {}) if isinstance(scores.get("inbound_call_center"), dict) else {}
        outbound = scores.get("outbound_telemarketing", {}) if isinstance(scores.get("outbound_telemarketing"), dict) else {}
        appoint = scores.get("appointment_setting", {}) if isinstance(scores.get("appointment_setting"), dict) else {}

        def pick_score(d: dict) -> Tuple[int, str, str, str]:
            sc = int(d.get("score", 0) or 0)
            lab = str(d.get("label", "Bassa") or "Bassa")
            reasons = d.get("reasons", [])
            if not isinstance(reasons, list):
                reasons = []
            evid = d.get("evidence", [])
            if not isinstance(evid, list):
                evid = []
            return sc, lab, " • ".join([str(x) for x in reasons[:3]]), "\n".join([str(x) for x in evid[:3]])

        sc_in, lab_in, rs_in, ev_in = pick_score(inbound)
        sc_out, lab_out, rs_out, ev_out = pick_score(outbound)
        sc_ap, lab_ap, rs_ap, ev_ap = pick_score(appoint)

        skills = extracted.get("skills", {}) if isinstance(extracted.get("skills"), dict) else {}
        office_tools = skills.get("office_tools", [])
        crm_tools = skills.get("crm_tools", [])
        ticket_tools = skills.get("ticketing_tools", [])
        cc_tools = skills.get("contact_center_tools", [])

        def short_list(x, n=6):
            if not isinstance(x, list):
                return ""
            y = [str(i).strip() for i in x if str(i).strip()]
            return ", ".join(list(dict.fromkeys(y))[:n])

        tools_str = " | ".join(
            [s for s in [short_list(office_tools, 4), short_list(crm_tools, 4), short_list(ticket_tools, 3), short_list(cc_tools, 3)] if s]
        )

        exp = extracted.get("experience", [])
        phone_struct = 0
        phone_types = []
        evid_phone = []
        if isinstance(exp, list):
            for e in exp:
                if not isinstance(e, dict):
                    continue
                if bool(e.get("is_phone_structured", False)):
                    phone_struct += 1
                    pt = str(e.get("phone_type", "none"))
                    if pt and pt not in phone_types:
                        phone_types.append(pt)
                    ev = e.get("evidence", [])
                    if isinstance(ev, list):
                        for s in ev[:1]:
                            if s and s not in evid_phone:
                                evid_phone.append(str(s))
        phone_type_str = ", ".join(phone_types) if phone_types else "none"
        evid_phone_str = "\n".join(evid_phone[:3])

        pdf_data_uri = build_pdf_data_uri(f.name, original_bytes)

        best_score = max(sc_in, sc_out, sc_ap)
        label_best = "Alta" if best_score >= 75 else "Media" if best_score >= 45 else "Bassa"

        whatsapp_url = ""
        phones = cand.get("phones", [])
        first_phone = ""
        if isinstance(phones, list) and phones:
            first_phone = str(phones[0]).strip()
        if label_best in ("Alta", "Media") and first_phone:
            phone_digits = re.sub(r"[^\d]", "", first_phone)
            if phone_digits:
                encoded_text = quote(standard_message)
                whatsapp_url = f"https://api.whatsapp.com/send?phone={phone_digits}&text={encoded_text}"

        email = cand.get("email", "") or email_fb
        mailto = ""
        if isinstance(email, str) and email.strip():
            subject_enc = quote_plus(email_subject)
            body_enc = quote(standard_message)
            mailto = f"mailto:{email}?subject={subject_enc}&body={body_enc}"

        row = {
            "Nome file": f.name,
            "Nome e Cognome": fullname,
            "Confidence estrazione": round(extraction_confidence, 2),
            "Metodo lettura": read_reason,
            "Tools/Stack": tools_str if tools_str else "-",
            "Phone structured (#exp)": phone_struct,
            "Phone type": phone_type_str,
            "Evidenze phone": evid_phone_str,
            "Inbound score": sc_in,
            "Inbound label": lab_in,
            "Inbound reasons": rs_in,
            "Inbound evidence": ev_in,
            "Outbound score": sc_out,
            "Outbound label": lab_out,
            "Outbound reasons": rs_out,
            "Outbound evidence": ev_out,
            "Appoint score": sc_ap,
            "Appoint label": lab_ap,
            "Appoint reasons": rs_ap,
            "Appoint evidence": ev_ap,
            "Best score": best_score,
            "Best label": label_best,
            "Read": pdf_data_uri,
            "Numero/Numeri telefono": " | ".join([str(p) for p in phones]) if isinstance(phones, list) else "",
            "Whatsapp": whatsapp_url,
            "E-Mail": mailto,
        }

        if show_debug:
            row["_debug_extract_json"] = json.dumps(extracted, ensure_ascii=False)
            row["_debug_score_json"] = json.dumps(scored, ensure_ascii=False)

        if extraction_confidence >= min_extract_conf:
            rows.append(row)

    status_box.empty()
    st.success("Analisi completata.")

    if unreadable:
        st.warning("Alcuni CV non sono stati letti correttamente e non sono stati analizzati.")
        st.write(", ".join(unreadable))

    if rows:
        df = pd.DataFrame(rows)

        # ======= FILTRI UI =======
        st.markdown("### Risultati")
        c1, c2, c3, c4 = st.columns([1, 1, 1.2, 1.2])
        with c1:
            role_filter = st.selectbox(
                "Vista ruolo",
                ["Best", "Inbound", "Outbound", "Appoint"],
                index=0,
                help=(
                    "Best=mostra il punteggio migliore. "
                    "Inbound=assistenza. Outbound=telemarketing/vendita. Appoint=presa appuntamenti."
                ),
            )
        with c2:
            min_score = st.slider("Score minimo", 0, 100, 0, 5)
        with c3:
            label_filter = st.multiselect("Label", ["Alta", "Media", "Bassa"], default=["Alta", "Media", "Bassa"])
        with c4:
            name_query = st.text_input("Cerca (nome/file)", value="")

        role_help = {
            "Best": "Mostra il punteggio migliore tra Inbound/Outbound/Appuntamenti.",
            "Inbound": "Assistenza (in entrata). Pesa customer orientation + processi + digital.",
            "Outbound": "Chiamate in uscita. Pesa vendita + KPI + obiezioni + processi.",
            "Appoint": "Presa appuntamenti/qualifica lead. Pesa CRM + volumi + script/processo + comunicazione.",
        }
        st.caption(f"**Criteri vista {role_filter}:** {role_help.get(role_filter, '')}")

        def role_cols(role: str) -> Tuple[str, str, str, str]:
            if role == "Inbound":
                return "Inbound score", "Inbound label", "Inbound reasons", "Inbound evidence"
            if role == "Outbound":
                return "Outbound score", "Outbound label", "Outbound reasons", "Outbound evidence"
            if role == "Appoint":
                return "Appoint score", "Appoint label", "Appoint reasons", "Appoint evidence"
            return "Best score", "Best label", "Inbound reasons", "Inbound evidence"

        score_col, label_col, reasons_col, evidence_col = role_cols(role_filter)

        view = df.copy()
        view = view[view[label_col].isin(label_filter)]
        view = view[view[score_col] >= min_score]

        if name_query.strip():
            q = name_query.strip().lower()
            view = view[
                view["Nome e Cognome"].fillna("").str.lower().str.contains(q)
                | view["Nome file"].fillna("").str.lower().str.contains(q)
            ]

        base_cols = [
            "Nome file",
            "Nome e Cognome",
            "Confidence estrazione",
            "Metodo lettura",
            "Tools/Stack",
            "Phone structured (#exp)",
            "Phone type",
            "Evidenze phone",
            score_col,
            label_col,
            reasons_col,
            evidence_col,
            "Read",
            "Numero/Numeri telefono",
            "Whatsapp",
            "E-Mail",
        ]
        base_cols = [c for c in base_cols if c in view.columns]
        view = view[base_cols].sort_values(by=score_col, ascending=False)

        st.download_button(
            "Export CSV (vista corrente)",
            data=view.to_csv(index=False).encode("utf-8"),
            file_name="screening_export.csv",
            mime="text/csv",
        )

        n_rows = len(view)
        table_height = min(760, 44 + n_rows * 32)

        st.data_editor(
            view,
            hide_index=True,
            use_container_width=True,
            height=table_height,
            num_rows="fixed",
            disabled=True,
            column_config={
                score_col: st.column_config.ProgressColumn(score_col, min_value=0, max_value=100, format="%d"),
                "Read": st.column_config.LinkColumn("PDF", display_text="PDF"),
                "Whatsapp": st.column_config.LinkColumn("WhatsApp", display_text="WhatsApp"),
                "E-Mail": st.column_config.LinkColumn("E-mail", display_text="E-mail"),
            },
        )
    else:
        st.info("Nessun CV supera la soglia di Confidence estrazione selezionata.")

# ===================== FOOTER =====================
st.markdown(
    """
<div class="footer">
    Tool developed by Fabio Galli using Vibe Coding, powered by Groq LLM API. • v2
</div>
""",
    unsafe_allow_html=True,
)






