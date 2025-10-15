# -*- coding: utf-8 -*-
import streamlit as st
import PyPDF2
import io
import re
import pandas as pd

# --- CONFIGURAZIONE DELLA PAGINA ---
st.set_page_config(
    page_title="Analisi di Bilancio Automatizzata",
    page_icon="📊",
    layout="wide"
)

# --- FUNZIONI DI FORMATTAZIONE ---
def format_currency(value):
    """Formatta un numero come valuta in Euro."""
    if pd.isna(value):
        return "€ 0,00"
    return f"€ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def format_decimal(value):
    """Formatta un numero con due decimali."""
    if pd.isna(value) or not isinstance(value, (int, float)):
        return "N/A"
    return f"{value:.2f}"

def format_percent(value):
    """Formatta un numero come percentuale."""
    if pd.isna(value) or not isinstance(value, (int, float)):
        return "N/A"
    return f"{(value * 100):.2f}%"

# --- LOGICA DI PARSING ED ESTRAZIONE ---

# Definizioni delle parole chiave per la categorizzazione
KEYWORDS = {
    'assets': {
        'current': ['cassa', 'banca', 'crediti', 'clienti', 'rimanenze', 'scorte', 'ratei attivi', 'risconti attivi', 'liquidità'],
        'non_current': ['immobilizzazioni', 'impianti', 'macchinari', 'attrezzature', 'fabbricati', 'terreni', 'brevetti', 'marchi', 'software', 'partecipazioni']
    },
    'liabilities': {
        'current': ['debiti', 'fornitori', 'tributari', 'erario', 'inps', 'inail', 'dipendenti', 'ratei passivi', 'risconti passivi', 'banche c/c passivi'],
        'non_current': ['mutui', 'finanziamenti', 'tfr', 'trattamento fine rapporto'],
        'equity': ['capitale', 'riserve', 'utile', 'perdita', 'patrimonio netto']
    },
    'income': {
         'revenue': ['ricavi', 'vendite', 'fatturato', 'valore della produzione'],
         'variable': ['materie', 'consumo', 'acquisti', 'sussidiarie', 'lavorazioni', 'costi per materie'],
         'fixed': ['salari', 'stipendi', 'personale', 'costi del personale', 'ammortamenti', 'affitti', 'godimento beni terzi', 'interessi', 'oneri finanziari', 'servizi']
    }
}

def extract_text_from_pdf(pdf_file):
    """Estrae il testo da un file PDF caricato."""
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_file.read()))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        st.error(f"Errore nella lettura del PDF: {e}")
        return ""

def parse_financial_text(text):
    """Analizza il testo estratto per trovare voci e importi finanziari."""
    assets_data, liabilities_data, income_data = "", "", ""
    
    # Regex per trovare una descrizione testuale seguita da un importo numerico
    # Gestisce numeri come 1.234,56 o 1,234.56 o 1234.56
    line_regex = re.compile(r"^(.*?)\s+([\d.,\s]+?[\d])\s*$")

    for line in text.split('\n'):
        line = line.strip()
        match = line_regex.match(line)
        
        if match:
            item_name = match.group(1).strip().lower()
            amount_str = match.group(2).strip()

            # Pulisce l'importo: rimuove spazi, punti (migliaia) e sostituisce la virgola con il punto decimale
            try:
                # Gestisce formati come "1.234,56" -> "1234.56"
                amount = float(amount_str.replace('.', '').replace(',', '.'))
            except ValueError:
                continue # Salta se la conversione fallisce

            if len(item_name) < 4 or amount == 0:
                continue

            # Classificazione basata su keyword
            found = False
            # Stato Patrimoniale - Attività
            if any(kw in item_name for kw in KEYWORDS['assets']['current'] + KEYWORDS['assets']['non_current']):
                assets_data += f"{match.group(1).strip()},{amount}\n"
                found = True
            # Stato Patrimoniale - Passività e PN
            if not found and any(kw in item_name for kw in KEYWORDS['liabilities']['current'] + KEYWORDS['liabilities']['non_current'] + KEYWORDS['liabilities']['equity']):
                liabilities_data += f"{match.group(1).strip()},{amount}\n"
                found = True
            # Conto Economico
            if not found:
                ce_type = "Fisso"
                if any(kw in item_name for kw in KEYWORDS['income']['revenue']):
                    ce_type = "Ricavo"
                elif any(kw in item_name for kw in KEYWORDS['income']['variable']):
                    ce_type = "Variabile"
                
                income_data += f"{match.group(1).strip()},{amount},{ce_type}\n"

    return assets_data, liabilities_data, income_data

def parse_textarea_data(text):
    """Converte il testo delle textarea in una lista di dizionari."""
    data = []
    for line in text.strip().split('\n'):
        if not line: continue
        parts = line.split(',')
        try:
            item = parts[0].strip()
            amount = float(parts[1].strip())
            ce_type = parts[2].strip().capitalize() if len(parts) > 2 else None
            data.append({'item': item, 'amount': amount, 'type': ce_type})
        except (ValueError, IndexError):
            st.warning(f"Riga ignorata per formato non valido: '{line}'")
    return data

# --- INTERFACCIA UTENTE (UI) ---

st.title("📊 Analisi di Bilancio Automatizzata")
st.markdown("Carica un bilancio in formato PDF per estrarre e analizzare i dati automaticamente, oppure inseriscili manualmente.")

# Creazione di session state per mantenere i dati
if 'assets_text' not in st.session_state:
    st.session_state.assets_text = ""
if 'liabilities_text' not in st.session_state:
    st.session_state.liabilities_text = ""
if 'income_text' not in st.session_state:
    st.session_state.income_text = ""

with st.sidebar:
    st.header("1. Carica Bilancio PDF")
    uploaded_file = st.file_uploader(
        "Seleziona un PDF (preferibilmente testuale)",
        type="pdf"
    )

    if uploaded_file:
        with st.spinner('Estrazione dati dal PDF in corso...'):
            raw_text = extract_text_from_pdf(uploaded_file)
            if raw_text:
                assets, liabilities, income = parse_financial_text(raw_text)
                st.session_state.assets_text = assets
                st.session_state.liabilities_text = liabilities
                st.session_state.income_text = income
                st.success("Dati estratti! Controlla i campi e avvia l'analisi.")

    st.header("2. Dati Finanziari")
    st.markdown("Verifica i dati estratti o inseriscili manualmente.")
    
    st.session_state.assets_text = st.text_area(
        "ATTIVITÀ (Voce,Importo)",
        st.session_state.assets_text,
        height=150
    )
    st.session_state.liabilities_text = st.text_area(
        "PASSIVITÀ E PN (Voce,Importo)",
        st.session_state.liabilities_text,
        height=150
    )
    st.session_state.income_text = st.text_area(
        "CONTO ECONOMICO (Voce,Importo,Tipo*)",
        st.session_state.income_text,
        height=150,
        help="*I Tipi sono: Ricavo, Variabile, Fisso"
    )

    st.header("3. Impostazioni")
    tax_rate = st.number_input("Aliquota Fiscale (%)", value=24.0, min_value=0.0, max_value=100.0, step=0.5) / 100

    analyze_button = st.button("🚀 Elabora Analisi", use_container_width=True)

# --- ZONA DI VISUALIZZAZIONE RISULTATI ---
if not analyze_button:
    st.info("Carica un PDF o inserisci i dati nella barra laterale e clicca 'Elabora Analisi' per visualizzare i risultati.")

if analyze_button:
    assets_data = parse_textarea_data(st.session_state.assets_text)
    liabilities_data = parse_textarea_data(st.session_state.liabilities_text)
    income_data = parse_textarea_data(st.session_state.income_text)

    if not assets_data or not liabilities_data or not income_data:
        st.error("Dati insufficienti. Compila tutti i campi richiesti nella barra laterale.")
    else:
        # --- ELABORAZIONE E CALCOLO ---

        # 1. Riclassificazione Stato Patrimoniale
        bs = {
            'current_assets': sum(d['amount'] for d in assets_data if any(kw in d['item'].lower() for kw in KEYWORDS['assets']['current'])),
            'non_current_assets': sum(d['amount'] for d in assets_data if any(kw in d['item'].lower() for kw in KEYWORDS['assets']['non_current'])),
            'current_liabilities': sum(d['amount'] for d in liabilities_data if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['current'])),
            'non_current_liabilities': sum(d['amount'] for d in liabilities_data if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['non_current'])),
            'equity': sum(d['amount'] for d in liabilities_data if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['equity'])),
        }
        total_assets = bs['current_assets'] + bs['non_current_assets']
        total_liabilities = bs['current_liabilities'] + bs['non_current_liabilities']
        total_liabilities_and_equity = total_liabilities + bs['equity']
        rimanenze = sum(d['amount'] for d in assets_data if 'rimanenze' in d['item'].lower() or 'scorte' in d['item'].lower())

        # 2. Riclassificazione Conto Economico
        income = {
            'revenues': sum(d['amount'] for d in income_data if d['type'] == 'Ricavo'),
            'variable_costs': sum(d['amount'] for d in income_data if d['type'] == 'Variabile'),
            'fixed_costs': sum(d['amount'] for d in income_data if d['type'] == 'Fisso'),
        }
        contribution_margin = income['revenues'] - income['variable_costs']
        ebit = contribution_margin - income['fixed_costs']
        interest = sum(d['amount'] for d in income_data if 'interessi' in d['item'].lower() or 'oneri finanziari' in d['item'].lower())
        ebt = ebit - interest
        taxes = ebt * tax_rate if ebt > 0 else 0
        net_income = ebt - taxes

        # 3. Calcolo Indici
        ratios = {
            'current_ratio': bs['current_assets'] / bs['current_liabilities'] if bs['current_liabilities'] > 0 else 0,
            'quick_ratio': (bs['current_assets'] - rimanenze) / bs['current_liabilities'] if bs['current_liabilities'] > 0 else 0,
            'debt_to_equity': total_liabilities / bs['equity'] if bs['equity'] > 0 else 0,
            'ros': ebit / income['revenues'] if income['revenues'] > 0 else 0,
            'roe': net_income / bs['equity'] if bs['equity'] > 0 else 0,
            'roi': ebit / total_assets if total_assets > 0 else 0,
            'contribution_margin_ratio': contribution_margin / income['revenues'] if income['revenues'] > 0 else 0,
            'break_even_point': income['fixed_costs'] / (contribution_margin / income['revenues']) if contribution_margin > 0 else 0
        }

        # --- VISUALIZZAZIONE ---
        st.header("Risultati dell'Analisi")
        
        # Controllo quadratura
        balance_diff = total_assets - total_liabilities_and_equity
        if abs(balance_diff) > 1: # Tolleranza di 1 euro
            st.warning(f"⚠️ **Attenzione:** Il bilancio non quadra! Differenza: {format_currency(balance_diff)}")
        else:
            st.success("✅ **Controllo:** Il bilancio quadra correttamente.")

        tab1, tab2, tab3 = st.tabs(["📈 Dashboard Indici", "📑 Stato Patrimoniale", "💰 Conto Economico"])

        with tab1:
            st.subheader("Dashboard Indici Principali")
            cols = st.columns(3)
            with cols[0]:
                st.metric("ROE (Redditività Capitale Proprio)", format_percent(ratios['roe']))
                st.metric("ROI (Redditività Capitale Investito)", format_percent(ratios['roi']))
                st.metric("ROS (Redditività delle Vendite)", format_percent(ratios['ros']))
            with cols[1]:
                st.metric("Indice di Liquidità (Current Ratio)", format_decimal(ratios['current_ratio']))
                st.metric("Indice di Tesoreria (Quick Ratio)", format_decimal(ratios['quick_ratio']))
                st.metric("Rapporto di Indebitamento (D/E)", format_decimal(ratios['debt_to_equity']))
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
                    {"Voce": "Attivo Non Corrente (Immobilizzato)", "Importo": bs['non_current_assets']},
                    {"Voce": "**TOTALE ATTIVITÀ**", "Importo": total_assets}
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
                {"Voce": "Ricavi delle Vendite", "Importo": income['revenues']},
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
