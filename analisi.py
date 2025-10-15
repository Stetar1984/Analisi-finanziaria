# -*- coding: utf-8 -*-
import streamlit as st
import pdfplumber
import io
import re
import pandas as pd
import math

# --- CONFIGURAZIONE DELLA PAGINA ---
st.set_page_config(
    page_title="Analisi di Bilancio Automatizzata",
    page_icon="📊",
    layout="wide"
)

# --- FUNZIONI DI FORMATTAZIONE ---
def format_currency(value):
    if pd.isna(value) or not isinstance(value, (int, float)):
        return "€ 0,00"
    return f"€ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def format_decimal(value):
    if pd.isna(value) or not isinstance(value, (int, float)):
        return "N/A"
    return f"{value:.2f}"

def format_percent(value):
    if pd.isna(value) or not isinstance(value, (int, float)):
        return "N/A"
    return f"{(value * 100):.2f}%"

# --- KEYWORDS E REGEX ---
KEYWORDS = {
    'assets': {
        'current': ['cassa', 'banca', 'crediti', 'clienti', 'rimanenze', 'scorte', 'ratei attivi', 'risconti attivi', 'liquidità', 'depositi bancari', 'denaro e valori'],
        'non_current': ['immobilizzazioni', 'impianti', 'macchinari', 'attrezzature', 'fabbricati', 'terreni', 'brevetti', 'marchi', 'software', 'partecipazioni', 'mobili e arredi', 'macchine d\'ufficio', 'auto', 'autocarri']
    },
    'liabilities': {
        'current': ['debiti', 'fornitori', 'tributari', 'erario', 'inps', 'inail', 'dipendenti', 'ratei passivi', 'risconti passivi', 'banche c/c passivi'],
        'non_current': ['mutui', 'finanziamenti', 'tfr', 'trattamento fine rapporto'],
        'equity': ['capitale', 'riserve', 'utile', 'perdita', 'patrimonio netto']
    },
    'special_negative': ['f.do amm', 'fondo amm', 'fondo ammortamenti', 'ammortamenti'],
    'income': {
        'revenue': ['ricavi', 'vendite', 'fatturato', 'valore della produzione', 'proventi', 'contributi in conto esercizio', 'altri ricavi'],
        'variable': ['materie', 'consumo', 'acquisti', 'sussidiarie', 'lavorazioni', 'costi per materie', 'rim.fin', 'rim.iniz'],
        'fixed': ['salari', 'stipendi', 'personale', 'costi del personale', 'ammortamenti', 'affitti', 'godimento beni terzi', 'interessi', 'oneri finanziari', 'servizi', 'sanzioni', 'multe', 'abbonamenti', 'imposte', 'oneri diversi', 'quote associative', 'quote trattamento']
    }
}

MACRO_REGEX = re.compile(r'^(ATTIVIT|PASSIVIT|PATRIMONIO|CONTO ECONOMICO|RICLASSIFICAZIONE|TOTALE|RIEPILOGO)\b', re.I)
FUND_REGEX = re.compile(r'\b(f(\.|ondo)?\s*amm(?:ortamenti)?|ammortamenti)\b', re.I)

# --- UTILS ---
def clean_and_convert_amount(amount_str):
    if not amount_str:
        return None
    try:
        s = str(amount_str).strip()
        s = s.replace(' ', '')
        s = s.replace('.', '').replace(',', '.')
        return float(s)
    except (ValueError, TypeError):
        return None

# --- PARSER PDF ROBUSTO ---
def extract_data_from_verification_balance(pdf_file):
    """
    Supporta layout:
    - [DESCRIZIONE, DARE, AVERE, SALDO, SEGNO]  es. "1.234,00" + "D"
    - [DESCRIZIONE, DARE, AVERE, SALDO]         es. "1.234,00 D"
    - [DESCRIZIONE, DARE, AVERE, SALDO DARE, SALDO AVERE]
    Ignora solo macro-categorie note.
    """
    assets_data, liabilities_data, income_data = [], [], []

    table_settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 3,
        "join_tolerance": 3,
        "edge_min_length": 20
    }

    pdf_file.seek(0)
    with pdfplumber.open(io.BytesIO(pdf_file.read())) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables(table_settings=table_settings) or []
            for table in tables:
                if not table or len(table[0]) < 3:
                    continue

                headers = [(c or "").strip().lower() for c in table[0]]
                has_header = any(h for h in headers if any(k in h for k in ["descr", "dare", "avere", "saldo"]))
                start_idx = 1 if has_header else 0
                lower_headers = headers if has_header else []

                for row in table[start_idx:]:
                    cells = [(c or "").strip() for c in row]
                    if len(cells) < 2:
                        continue

                    desc = re.sub(r'^\d+[\.\-\s]*', '', cells[0].replace("\n", " ")).strip()
                    if not desc or MACRO_REGEX.search(desc):
                        continue

                    saldo_amount, saldo_side = None, None  # 'D' o 'A'

                    # Caso 1: colonna con "importo segno"
                    for c in cells[1:]:
                        c2 = c.replace(' ', '')
                        m = re.match(r'^([\-]?\d[\d\.]*,\d{2})([DA])$', c2, re.I)
                        if m:
                            saldo_amount = clean_and_convert_amount(m.group(1))
                            saldo_side = m.group(2).upper()
                            break

                    # Caso 2: importo e segno su colonne adiacenti
                    if saldo_amount is None:
                        for i in range(1, len(cells) - 1):
                            imp = clean_and_convert_amount(cells[i])
                            seg = (cells[i + 1] or "").strip().upper()
                            if imp is not None and seg in ("D", "A"):
                                saldo_amount, saldo_side = imp, seg
                                break

                    # Caso 3: SALDO DARE vs SALDO AVERE su colonne dedicate
                    if saldo_amount is None:
                        sd_idx = next((i for i, h in enumerate(lower_headers) if "saldo" in h and "dare" in h), None)
                        sa_idx = next((i for i, h in enumerate(lower_headers) if "saldo" in h and "avere" in h), None)
                        if sd_idx is not None or sa_idx is not None:
                            sd_val = clean_and_convert_amount(cells[sd_idx]) if sd_idx is not None and sd_idx < len(cells) else None
                            sa_val = clean_and_convert_amount(cells[sa_idx]) if sa_idx is not None and sa_idx < len(cells) else None
                            if (sd_val or 0) > 0:
                                saldo_amount, saldo_side = sd_val, 'D'
                            elif (sa_val or 0) > 0:
                                saldo_amount, saldo_side = sa_val, 'A'
                        else:
                            # fallback: ultimo importo numerico trovato
                            numeric_cells = []
                            for i, c in enumerate(cells[1:], start=1):
                                imp = clean_and_convert_amount(c)
                                if imp is not None:
                                    numeric_cells.append((i, imp))
                            if numeric_cells:
                                i_last, val_last = numeric_cells[-1]
                                col_name = lower_headers[i_last] if has_header and i_last < len(lower_headers) else ""
                                if "dare" in col_name:
                                    saldo_amount, saldo_side = val_last, 'D'
                                elif "avere" in col_name:
                                    saldo_amount, saldo_side = val_last, 'A'
                                else:
                                    saldo_amount, saldo_side = abs(val_last), ('A' if val_last < 0 else 'D')

                    if saldo_amount is None or saldo_side not in ("D", "A"):
                        continue

                    item_lower = desc.lower()

                    if saldo_side == 'D':  # Attività o Costi
                        if any(kw in item_lower for kw in KEYWORDS['assets']['current'] + KEYWORDS['assets']['non_current']):
                            assets_data.append(f"{desc},{saldo_amount}")
                        else:
                            ce_type = "Variabile" if any(kw in item_lower for kw in KEYWORDS['income']['variable']) else "Fisso"
                            income_data.append(f"{desc},{saldo_amount},{ce_type}")
                    else:  # 'A' Passività/PN o Ricavi
                        if FUND_REGEX.search(item_lower):
                            liabilities_data.append(f"{desc},{abs(saldo_amount)}")
                        elif any(kw in item_lower for kw in KEYWORDS['liabilities']['current'] + KEYWORDS['liabilities']['non_current'] + KEYWORDS['liabilities']['equity']):
                            liabilities_data.append(f"{desc},{saldo_amount}")
                        else:
                            income_data.append(f"{desc},{saldo_amount},Ricavo")

    return "\n".join(assets_data), "\n".join(liabilities_data), "\n".join(income_data)

# --- PARSER CSV ---
def parse_csv_file(csv_file):
    assets_data, liabilities_data, income_data = [], [], []
    csv_file.seek(0)
    csv_content = csv_file.read()
    df = None
    configs = [
        {'encoding': 'utf-8', 'sep': ','},
        {'encoding': 'utf-8', 'sep': ';'},
        {'encoding': 'latin-1', 'sep': ','},
        {'encoding': 'latin-1', 'sep': ';'}
    ]
    for config in configs:
        try:
            df = pd.read_csv(io.BytesIO(csv_content), encoding=config['encoding'], sep=config['sep'], engine='python')
            cols_norm = [c.lower().strip() for c in df.columns]
            if 'voce' in cols_norm:
                break
            else:
                df = None
        except (UnicodeDecodeError, pd.errors.ParserError):
            csv_file.seek(0)
            csv_content = csv_file.read()
            continue
    if df is None:
        st.error("Errore critico: Impossibile analizzare il file CSV.")
        return "", "", ""
    df.columns = [col.strip().lower() for col in df.columns]
    required_cols = ['voce', 'importo', 'sezione']
    if not all(col in df.columns for col in required_cols):
        found_cols = ', '.join(df.columns)
        st.error(f"Errore nelle colonne del CSV. Richieste: {required_cols}. Trovate: {found_cols}")
        return "", "", ""
    for _, row in df.iterrows():
        voce = str(row['voce']).strip()
        importo = float(row['importo'])
        sezione = str(row['sezione']).lower()
        if 'attivit' in sezione:
            assets_data.append(f"{voce},{importo}")
        elif 'passivit' in sezione or 'pn' in sezione:
            liabilities_data.append(f"{voce},{importo}")
        elif 'conto economico' in sezione:
            tipo = str(row.get('tipo', 'Fisso')).capitalize()
            income_data.append(f"{voce},{importo},{tipo}")
    return "\n".join(assets_data), "\n".join(liabilities_data), "\n".join(income_data)

# --- PARSE TEXTAREA ---
def parse_textarea_data(text):
    data = []
    for line in text.strip().split('\n'):
        if not line:
            continue
        parts = line.split(',')
        try:
            item = parts[0].strip()
            amount = float(parts[1].strip())
            ce_type = parts[2].strip().capitalize() if len(parts) > 2 else None
            data.append({'item': item, 'amount': amount, 'type': ce_type})
        except (ValueError, IndexError):
            pass
    return data

# --- UI ---
st.title("📊 Analisi di Bilancio Automatizzata")
st.markdown("Carica un bilancio in formato **CSV (consigliato)** o PDF, oppure inserisci i dati manualmente.")

if 'assets_text' not in st.session_state:
    st.session_state.assets_text = ""
if 'liabilities_text' not in st.session_state:
    st.session_state.liabilities_text = ""
if 'income_text' not in st.session_state:
    st.session_state.income_text = ""

with st.sidebar:
    st.header("1. Carica il Bilancio")
    uploaded_file = st.file_uploader("Seleziona un file CSV o PDF", type=["csv", "pdf"])

    with st.expander("❓ **Formato CSV Richiesto (IMPORTANTE)**"):
        st.info(
            "Colonne richieste:\n"
            "- **voce**\n- **importo**\n- **sezione**: `Attività`, `Passività`, `PN`, `Conto Economico`\n"
            "- **tipo** (opzionale solo CE): `Ricavo`, `Variabile`, `Fisso`"
        )

    if uploaded_file:
        with st.spinner('Estrazione dati dal file...'):
            ext = uploaded_file.name.split('.')[-1].lower()
            if ext == 'pdf':
                assets, liabilities, income = extract_data_from_verification_balance(uploaded_file)
            elif ext == 'csv':
                assets, liabilities, income = parse_csv_file(uploaded_file)
            else:
                assets = liabilities = income = ""
                st.error("Formato file non supportato.")
            st.session_state.assets_text = assets
            st.session_state.liabilities_text = liabilities
            st.session_state.income_text = income
            if assets or liabilities or income:
                st.success("Dati estratti. Verifica e avvia l'analisi.")

    st.header("2. Dati Finanziari")
    st.markdown("Verifica i dati estratti o inseriscili manualmente.")
    st.text_area("ATTIVITÀ (Voce,Importo)", key="assets_text", height=150)
    st.text_area("PASSIVITÀ E PN (Voce,Importo)", key="liabilities_text", height=150)
    st.text_area("CONTO ECONOMICO (Voce,Importo,Tipo*)", key="income_text", height=150, help="*Tipi: Ricavo, Variabile, Fisso")

    st.header("3. Impostazioni")
    tax_rate = st.number_input("Aliquota Fiscale (%)", value=24.0, min_value=0.0, max_value=100.0, step=0.5) / 100

    analyze_button = st.button("🚀 Elabora Analisi", use_container_width=True)

if not analyze_button:
    st.info("Carica un file o inserisci i dati nella barra laterale e clicca 'Elabora Analisi'.")

if analyze_button:
    assets_data = parse_textarea_data(st.session_state.assets_text)
    liabilities_data = parse_textarea_data(st.session_state.liabilities_text)
    income_data = parse_textarea_data(st.session_state.income_text)

    if not assets_data or not liabilities_data or not income_data:
        st.error("Dati insufficienti. Compila tutti i campi richiesti.")
    else:
        # --- CALCOLI ---
        total_raw_assets = sum(d['amount'] for d in assets_data)

        # fondi ammortamento riconosciuti anche via regex
        amortization_funds = sum(
            d['amount'] for d in liabilities_data
            if FUND_REGEX.search(d['item'].lower()) or any(kw in d['item'].lower() for kw in KEYWORDS['special_negative'])
        )

        net_total_assets = total_raw_assets - amortization_funds

        current_assets_raw = sum(
            d['amount'] for d in assets_data
            if any(kw in d['item'].lower() for kw in KEYWORDS['assets']['current'])
        )
        non_current_assets_raw = sum(
            d['amount'] for d in assets_data
            if any(kw in d['item'].lower() for kw in KEYWORDS['assets']['non_current'])
        )
        net_non_current_assets = non_current_assets_raw - amortization_funds

        liabilities_no_funds = [
            d for d in liabilities_data
            if not (FUND_REGEX.search(d['item'].lower()) or any(kw in d['item'].lower() for kw in KEYWORDS['special_negative']))
        ]

        bs = {
            'current_assets': current_assets_raw,
            'non_current_assets': net_non_current_assets,
            'current_liabilities': sum(d['amount'] for d in liabilities_no_funds if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['current'])),
            'non_current_liabilities': sum(d['amount'] for d in liabilities_no_funds if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['non_current'])),
            'equity': sum(d['amount'] for d in liabilities_no_funds if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['equity'])),
        }

        rimanenze = sum(d['amount'] for d in assets_data if 'rimanenze' in d['item'].lower() or 'scorte' in d['item'].lower())

        utile_from_pdf = sum(d['amount'] for d in income_data if "utile d'esercizio" in d['item'].lower() or d['item'].lower() == "utile")
        if utile_from_pdf > 0:
            bs['equity'] += utile_from_pdf

        total_liabilities_and_equity = bs['current_liabilities'] + bs['non_current_liabilities'] + bs['equity']

        income = {
            'revenues': sum(d['amount'] for d in income_data if d['type'] == 'Ricavo'),
            'variable_costs': sum(d['amount'] for d in income_data if d['type'] == 'Variabile'),
            'fixed_costs': sum(d['amount'] for d in income_data if d['type'] == 'Fisso' and "utile" not in d['item'].lower()),
        }

        contribution_margin = income['revenues'] - income['variable_costs']
        ebit = contribution_margin - income['fixed_costs']
        interest = sum(d['amount'] for d in income_data if 'interessi' in d['item'].lower() or 'oneri finanziari' in d['item'].lower())
        ebt = ebit - interest
        taxes = ebt * tax_rate if ebt > 0 else 0
        net_income = ebt - taxes  # correzione

        ratios = {
            'current_ratio': bs['current_assets'] / bs['current_liabilities'] if bs['current_liabilities'] > 0 else 0,
            'quick_ratio': (bs['current_assets'] - rimanenze) / bs['current_liabilities'] if bs['current_liabilities'] > 0 else 0,
            'debt_to_equity': (bs['current_liabilities'] + bs['non_current_liabilities']) / bs['equity'] if bs['equity'] > 0 else 0,
            'ros': ebit / income['revenues'] if income['revenues'] > 0 else 0,
            'roe': (net_income / bs['equity']) if bs['equity'] > 0 else 0,
            'roi': (ebit / net_total_assets) if net_total_assets > 0 else 0,
            'contribution_margin_ratio': (contribution_margin / income['revenues']) if income['revenues'] > 0 else 0,
            'break_even_point': (income['fixed_costs'] / (contribution_margin / income['revenues'])) if contribution_margin > 0 and income['revenues'] > 0 else 0
        }

        # --- VISUALIZZAZIONE ---
        st.header("Risultati dell'Analisi")
        balance_diff = net_total_assets - total_liabilities_and_equity
        if abs(balance_diff) < 20:
            st.success(f"✅ **Controllo:** Il bilancio quadra (Δ: {format_currency(balance_diff)})")
        else:
            st.warning(f"⚠️ **Attenzione:** Il bilancio non quadra (Δ: {format_currency(balance_diff)})")

        tab1, tab2, tab3 = st.tabs(["📈 Dashboard Indici", "📑 Stato Patrimoniale", "💰 Conto Economico"])

        with tab1:
            st.subheader("Dashboard Indici Principali")
            cols = st.columns(3)
            with cols[0]:
                st.metric("ROE", format_percent(ratios['roe']))
                st.metric("ROI", format_percent(ratios['roi']))
                st.metric("ROS", format_percent(ratios['ros']))
            with cols[1]:
                st.metric("Current Ratio", format_decimal(ratios['current_ratio']))
                st.metric("Quick Ratio", format_decimal(ratios['quick_ratio']))
                st.metric("Debt/Equity", format_decimal(ratios['debt_to_equity']))
            with cols[2]:
                st.metric("Margine di Contribuzione %", format_percent(ratios['contribution_margin_ratio']))
                st.metric("Punto di Pareggio (Fatturato)", format_currency(ratios['break_even_point']))

        with tab2:
            st.subheader("Stato Patrimoniale Riclassificato (Criterio Finanziario)")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### Attività")
                sp_assets_df = pd.DataFrame([
                    {"Voce": "Attivo Corrente", "Importo": bs['current_assets']},
                    {"Voce": "Attivo Non Corrente (al netto dei fondi)", "Importo": bs['non_current_assets']},
                    {"Voce": "**TOTALE ATTIVITÀ**", "Importo": net_total_assets}
                ])
                st.dataframe(sp_assets_df.style.format({"Importo": format_currency}), use_container_width=True)
            with col2:
                st.markdown("#### Passività e Patrimonio Netto")
                sp_liab_df = pd.DataFrame([
                    {"Voce": "Passivo Corrente", "Importo": bs['current_liabilities']},
                    {"Voce": "Passivo Non Corrente (Consolidato)", "Importo": bs['non_current_liabilities']},
                    {"Voce": "**Patrimonio Netto**", "Importo": bs['equity']},
                    {"Voce": "**TOTALE PASSIVITÀ E PN**", "Importo": total_liabilities_and_equity}
                ])
                st.dataframe(sp_liab_df.style.format({"Importo": format_currency}), use_container_width=True)

        with tab3:
            st.subheader("Conto Economico Riclassificato (A Margine di Contribuzione)")
            ce_df = pd.DataFrame([
                {"Voce": "Ricavi delle Vendite e Prestazioni", "Importo": income['revenues']},
                {"Voce": "(-) Costi Variabili", "Importo": -income['variable_costs']},
                {"Voce": "**(=) Margine di Contribuzione**", "Importo": contribution_margin},
                {"Voce": "(-) Costi Fissi", "Importo": -income['fixed_costs']},
                {"Voce": "**(=) Risultato Operativo (EBIT)**", "Importo": ebit},
                {"Voce": "(-) Oneri Finanziari", "Importo": -interest},
                {"Voce": "(=) Risultato Ante Imposte (EBT)", "Importo": ebt},
                {"Voce": "(-) Imposte", "Importo": -taxes},
                {"Voce": "**(=) UTILE/PERDITA NETTO**", "Importo": net_income}
            ])
            st.dataframe(ce_df.style.format({"Importo": format_currency}), use_container_width=True)
