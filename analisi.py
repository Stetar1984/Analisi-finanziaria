# -*- coding: utf-8 -*-
"""
Estrazione dati di bilancio da PDF 'situazione contabile' e analisi per indici/margini.
Compatibile con PDF testuali dove le righe hanno: CODICE - DESCRIZIONE DARE AVERE SALDO [D/A].
"""

import re
from pathlib import Path
from typing import Optional, Dict, List

import pandas as pd

try:
    import PyPDF2  # per estrazione veloce testo
except Exception:
    PyPDF2 = None

try:
    from pdfminer.high_level import extract_text  # fallback robusto
except Exception:
    extract_text = None


def _read_pdf_text(path: Path) -> str:
    if PyPDF2 is not None:
        try:
            reader = PyPDF2.PdfReader(str(path))
            pages = [p.extract_text() or "" for p in reader.pages]
            txt = "\n".join(pages)
            if len(txt.strip()) > 100:
                return txt
        except Exception:
            pass
    if extract_text is not None:
        return extract_text(str(path)) or ""
    raise RuntimeError("Installa almeno uno tra PyPDF2 o pdfminer.six per leggere il PDF.")


def _normalize_space(s: str) -> str:
    import re
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s


def _itonum(token: str) -> Optional[float]:
    import re
    t = token.strip()
    if not t:
        return None
    t = re.sub(r"[_]+", "", t)
    t = re.sub(r"[^\d\.\,\-]", "", t)
    if t == "":
        return None
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except Exception:
        return None


LINE_RE = re.compile(
    r"(?P<code>\d{5,6}\s*\d{0,3})\s*-\s*(?P<descr>.+?)\s+"
    r"(?P<dare>\d{1,3}(?:\.\d{3})*(?:,\d{2})?|0,00|0,0|0)\s+"
    r"(?P<avere>\d{1,3}(?:\.\d{3})*(?:,\d{2})?|0,00|0,0|0)\s+"
    r"(?P<saldo>\d{1,3}(?:\.\d{3})*(?:,\d{2})?|0,00|0,0|0)"
    r"(?:\s+(?P<segn>[^ \n\r]+))?",
    re.IGNORECASE,
)


def _classify_row(descr: str, code: str) -> str:
    s = descr.lower()
    if "ricavi delle vendite" in s or "altri ricavi" in s or "contributi in conto esercizio" in s:
        return "CE_RICAVI"
    if s.startswith("costi "):
        return "CE_COSTI"
    if any(k in s for k in ["costi per servizi", "godimento beni di terzi", "personale", "ammortamenti", "oneri"]):
        return "CE_COSTI"
    if any(k in s for k in ["crediti", "depositi bancari", "cassa", "rimanenze", "ratei e risconti attivi"]):
        return "SP_ATTIVITA"
    if any(k in s for k in ["capitale", "riserva", "tfr", "debiti", "ratei e risconti passivi"]):
        return "SP_PASSIVITA"
    if code.startswith(("1", "15", "17")):
        return "SP_ATTIVITA"
    if code.startswith(("3", "37", "39")):
        return "SP_PASSIVITA"
    if code.startswith("7"):
        return "CONTO_ECONOMICO"
    return "ALTRO"


def parse_pdf_to_df(pdf_path: str) -> pd.DataFrame:
    txt = _read_pdf_text(Path(pdf_path))
    text = _normalize_space(txt)

    rows: List[Dict] = []
    for m in LINE_RE.finditer(text):
        d = m.groupdict()
        code = re.sub(r"\s+", "", d["code"])
        descr = d["descr"].strip()
        dare = _itonum(d["dare"])
        avere = _itonum(d["avere"])
        saldo = _itonum(d["saldo"])
        segno = (d.get("segn") or "").strip().upper()
        if segno not in {"D", "A"}:
            segno = "D" if (dare or 0) >= (avere or 0) else "A"
        rows.append(
            {"codice": code, "descrizione": descr, "dare": dare, "avere": avere, "saldo": saldo, "segno": segno}
        )

    df = pd.DataFrame(rows).drop_duplicates()
    if df.empty:
        raise ValueError("Nessuna riga riconosciuta. Verifica il layout del PDF.")
    df["sezione"] = df.apply(lambda r: _classify_row(r["descrizione"], r["codice"]), axis=1)
    return df


def _sum_saldo(dfsec: pd.DataFrame, prefer_credit: str) -> float:
    vals = []
    for _, r in dfsec.iterrows():
        v = r["saldo"] or 0.0
        if r["segno"] == "A" and prefer_credit == "A":
            vals.append(v)
        elif r["segno"] == "D" and prefer_credit == "D":
            vals.append(v)
        else:
            vals.append(-v)
    return float(sum(vals))


def _is_current_asset(descr: str) -> bool:
    s = descr.lower()
    return any(k in s for k in [
        "crediti v/clienti", "crediti tributari", "crediti v/altri",
        "depositi bancari", "cassa", "rimanenze", "ratei e risconti attivi"
    ])


def _is_current_liability(descr: str) -> bool:
    s = descr.lower()
    return any(k in s for k in [
        "debiti verso fornitori", "debiti tributari", "debiti v/istit.",
        "altri debiti", "ratei e risconti passivi"
    ])


def compute_kpis(df: pd.DataFrame) -> pd.DataFrame:
    attivita = _sum_saldo(df[df["sezione"] == "SP_ATTIVITA"], prefer_credit="D")
    passivita = _sum_saldo(df[df["sezione"] == "SP_PASSIVITA"], prefer_credit="A")

    attivo_corrente = sum(
        (r["saldo"] or 0.0) * (1 if r["segno"] == "D" else -1)
        for _, r in df[df["sezione"] == "SP_ATTIVITA"].iterrows()
        if _is_current_asset(r["descrizione"])
    )

    passivo_corrente = sum(
        (r["saldo"] or 0.0) * (1 if r["segno"] == "A" else -1)
        for _, r in df[df["sezione"] == "SP_PASSIVITA"].iterrows()
        if _is_current_liability(r["descrizione"])
    )

    liq_immediate = df[
        (df["sezione"] == "SP_ATTIVITA")
        & df["descrizione"].str.lower().str.contains("depositi bancari|cassa contanti|carta credito|denaro e valori", regex=True)
    ]
    liquidita = sum((r["saldo"] or 0.0) * (1 if r["segno"] == "D" else -1) for _, r in liq_immediate.iterrows())

    rimanenze = df[
        (df["sezione"] == "SP_ATTIVITA")
        & df["descrizione"].str.lower().str.contains("rimanenze|rim. mat", regex=True)
    ]
    rimanenze_val = sum((r["saldo"] or 0.0) * (1 if r["segno"] == "D" else -1) for _, r in rimanenze.iterrows())

    ricavi = sum(
        (r["saldo"] or 0.0) * (1 if r["segno"] == "A" else -1)
        for _, r in df[df["descrizione"].str.lower().str.contains("ricavi delle vendite|altri ricavi|contributi in conto esercizio")].iterrows()
    )

    def sum_block(mask_regex: str) -> float:
        block = df[df["descrizione"].str.lower().str.contains(mask_regex, regex=True)]
        return float(sum((r["saldo"] or 0.0) * (1 if r["segno"] == "D" else -1) for _, r in block.iterrows()))

    val_materie = sum_block("costi mat\\.prime|acquisto di materie prime")
    val_servizi = sum_block("costi per servizi")
    val_godimento = sum_block("costi per godimento beni di terzi")
    val_altri = sum_block("indumenti di lavoro|utenze|assicurazioni|gestione autocarri|elaborazione dati|consulenza")

    ebitda_approx = ricavi - (val_materie + val_servizi + val_godimento + val_altri)
    current = (attivo_corrente / passivo_corrente) if passivo_corrente else None
    quick = ((attivo_corrente - rimanenze_val) / passivo_corrente) if passivo_corrente else None
    ccn = attivo_corrente - passivo_corrente
    margine_tesoreria = (attivo_corrente - rimanenze_val) - passivo_corrente
    margine_struttura = (attivita - attivo_corrente) - (passivita - passivo_corrente)
    ebitda_margin = (ebitda_approx / ricavi) if ricavi else None

    summary = {
        "Attività (stima)": attivita,
        "Passività (stima)": passivita,
        "Attivo corrente (stima)": attivo_corrente,
        "Passivo corrente (stima)": passivo_corrente,
        "Liquidità immediate (stima)": liquidita,
        "Rimanenze (stima)": rimanenze_val,
        "CCN": ccn,
        "Current ratio": current,
        "Quick ratio": quick,
        "Margine di tesoreria": margine_tesoreria,
        "Margine di struttura (eur.)": margine_struttura,
        "Ricavi (stima)": ricavi,
        "Costi materie": val_materie,
        "Costi servizi": val_servizi,
        "Costi godimento beni terzi": val_godimento,
        "Altri costi caratteristici (euristico)": val_altri,
        "EBITDA stimato": ebitda_approx,
        "EBITDA margin": ebitda_margin,
    }
    return pd.DataFrame([summary])


def analyze_pdf(pdf_path: str, out_csv: Optional[str] = None, out_xlsx: Optional[str] = None):
    df = parse_pdf_to_df(pdf_path)
    kpis = compute_kpis(df)
    if out_csv:
        df.to_csv(out_csv, index=False, encoding="utf-8")
    if out_xlsx:
        with pd.ExcelWriter(out_xlsx, engine="xlsxwriter") as xw:
            df.to_excel(xw, sheet_name="righe_estratte", index=False)
            kpis.to_excel(xw, sheet_name="indici_margini", index=False)
    return df, kpis


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Estrai righe contabili e KPI da un PDF.")
    p.add_argument("pdf", help="Percorso PDF.")
    p.add_argument("--csv", help="Salva righe estratte in CSV.")
    p.add_argument("--xlsx", help="Salva analisi in Excel.")
    args = p.parse_args()

    df, kpis = analyze_pdf(args.pdf, args.csv, args.xlsx)
    print("\n== RIGHE ESTRATTE ==")
    print(df.head(20).to_string(index=False))
    print("\n== INDICI E MARGINI ==")
    print(kpis.to_string(index=False))
app_streamlit.py
python
# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from io import BytesIO
from bilancio_extractor import parse_pdf_to_df, compute_kpis

st.set_page_config(page_title="Analisi Bilancio da PDF", layout="wide")

st.title("Analisi di bilancio da PDF")
st.caption("Carica un PDF 'situazione contabile'. Il parser usa euristiche su descrizioni e colonne DARE/AVERE/SALDO.")

uploaded = st.file_uploader("Seleziona PDF", type=["pdf"])

if uploaded is not None:
    tmp = f"/tmp/_bil_{uploaded.name}"
    with open(tmp, "wb") as f:
        f.write(uploaded.read())

    try:
        df = parse_pdf_to_df(tmp)
        kpis = compute_kpis(df)

        st.subheader("Righe estratte")
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.subheader("Indici e margini")
        st.dataframe(kpis, use_container_width=True, hide_index=True)

        # Download CSV
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button("Scarica CSV righe", data=csv_bytes, file_name="righe_estratte.csv", mime="text/csv")

        # Download Excel
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as xw:
            df.to_excel(xw, sheet_name="righe_estratte", index=False)
            kpis.to_excel(xw, sheet_name="indici_margini", index=False)
        st.download_button("Scarica Excel analisi", data=output.getvalue(),
                           file_name="analisi_bilancio.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        st.error(f"Errore parsing: {e}")
        st.info("Controlla che il PDF sia testuale e che le colonne DARE/AVERE/SALDO siano allineate.")
else:
    st.info("Carica un PDF per iniziare.")
