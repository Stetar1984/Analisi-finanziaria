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

# --- LOGICA DI PARSING ED ESTRAZIONE ---

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
    'special_negative': ['f.do amm', 'fondo amm'],
    'income': {
         'revenue': ['ricavi', 'vendite', 'fatturato', 'valore della produzione', 'proventi', 'contributi in conto esercizio', 'altri ricavi'],
         'variable': ['materie', 'consumo', 'acquisti', 'sussidiarie', 'lavorazioni', 'costi per materie', 'rim.fin', 'rim.iniz'],
         'fixed': ['salari', 'stipendi', 'personale', 'costi del personale', 'ammortamenti', 'affitti', 'godimento beni terzi', 'interessi', 'oneri finanziari', 'servizi', 'sanzioni', 'multe', 'abbonamenti', 'imposte', 'oneri diversi', 'quote associative', 'quote trattamento']
    }
}

def clean_and_convert_amount(amount_str):
    if not amount_str: return None
    try:
        cleaned_str = str(amount_str).strip()
        if '.' in cleaned_str and ',' in cleaned_str:
            if cleaned_str.rfind('.') > cleaned_str.rfind(','):
                return float(cleaned_str.replace(',', ''))
            else:
                return float(cleaned_str.replace('.', '').replace(',', '.'))
        return float(cleaned_str.replace(',', '.'))
    except (ValueError, TypeError):
        return None

# --- MOTORE DI ESTRAZIONE CHE RICONOSCE IL GRASSETTO (CON CORREZIONE ERRORE) ---
def extract_data_with_formatting(pdf_file):
    """
    Estrae dati da un PDF analizzando la formattazione (grassetto) per
    distinguere le macro-categorie (totali) dalle voci di dettaglio.
    """
    all_assets, all_liabilities, all_costs, all_revenues = [], [], [], []

    with pdfplumber.open(io.BytesIO(pdf_file.read())) as pdf:
        is_ce_section = False
        for page in pdf.pages:
            # Rileva se la pagina appartiene al Conto Economico
            page_text_for_section_check = page.extract_text()
            if page_text_for_section_check and "CONTO ECONOMICO" in page_text_for_section_check:
                is_ce_section = True

            mid_point = page.width / 2
            # Bbox per colonna sinistra e destra
            left_bbox = (0, 0, mid_point, page.height)
            right_bbox = (mid_point, 0, page.width, page.height)

            def process_column(column_bbox, target_list):
                words = page.crop(column_bbox).extract_words(x_tolerance=2, y_tolerance=2)
                if not words: return

                lines = {}
                for word in words:
                    top = round(word['top'])
                    if top not in lines:
                        lines[top] = []
                    lines[top].append(word)

                for top in sorted(lines.keys()):
                    line_words = sorted(lines[top], key=lambda w: w['x0'])
                    line_text = " ".join(w['text'] for w in line_words)
                    
                    # --- CORREZIONE ERRORE ---
                    # Controlla in modo sicuro se 'fontname' esiste prima di accedervi.
                    is_bold = any("Bold" in w.get('fontname', '') for w in line_words)
                    
                    pattern = re.compile(r"(.+?)\s+([\d.,]+[\d])\s*$")
                    match = pattern.search(line_text)
                    
                    if match:
                        item_name = re.sub(r'^\d+\s*[-\s]*', '', match.group(1).strip())
                        amount = clean_and_convert_amount(match.group(2))
                        if amount is not None and len(item_name) > 3 and not item_name.lower().startswith('totale'):
                            # Aggiunge solo le voci NON in grassetto
                            if not is_bold:
                                target_list.append({'name': item_name, 'amount': amount})

            if is_ce_section:
                process_column(left_bbox, all_costs)
                process_column(right_bbox, all_revenues)
            else:
                process_column(left_bbox, all_assets)
                process_column(right_bbox, all_liabilities)

    income_details = all_costs + all_revenues
    final_assets, final_liabilities, final_income = [], [], []
    
    for entry in all_assets: final_assets.append(f"{entry['name']},{entry['amount']}")
    for entry in all_liabilities: final_liabilities.append(f"{entry['name']},{entry['amount']}")
    for entry in income_details:
        item_name_lower = entry['name'].lower()
        ce_type = "Fisso"
        is_revenue = any(kw in item_name_lower for kw in KEYWORDS['income']['revenue'])
        if is_revenue or entry in all_revenues:
            ce_type = "Ricavo"
        elif any(kw in item_name_lower for kw in KEYWORDS['income']['variable']):
            ce_type = "Variabile"
        final_income.append(f"{entry['name']},{entry['amount']},{ce_type}")

    return "\n".join(final_assets), "\n".join(final_liabilities), "\n".join(final_income)

# --- FUNZIONE PER PARSING CSV ---
def parse_csv_file(csv_file):
    assets_data, liabilities_data, income_data = [], [], []
    csv_content = csv_file.read()
    df = None
    configs = [{'encoding': 'utf-8', 'sep': ','}, {'encoding': 'utf-8', 'sep': ';'}, {'encoding': 'latin-1', 'sep': ','}, {'encoding': 'latin-1', 'sep': ';'}]
    for config in configs:
        try:
            df = pd.read_csv(io.BytesIO(csv_content), encoding=config['encoding'], sep=config['sep'], engine='python')
            if 'voce' in [c.lower().strip() for c in df.columns]:
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
        voce, importo, sezione = row['voce'], row['importo'], row['sezione'].lower()
        if 'attivit' in sezione: assets_data.append(f"{voce},{importo}")
        elif 'passivit' in sezione or 'pn' in sezione: liabilities_data.append(f"{voce},{importo}")
        elif 'conto economico' in sezione:
            tipo = row.get('tipo', 'Fisso')
            income_data.append(f"{voce},{importo},{tipo}")
    return "\n".join(assets_data), "\n".join(liabilities_data), "\n".join(income_data)

def parse_textarea_data(text):
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
            pass
    return data

# --- INTERFACCIA UTENTE (UI) ---
st.title("📊 Analisi di Bilancio Automatizzata")
st.markdown("Carica un bilancio in formato PDF o CSV, oppure inserisci i dati manualmente.")

if 'assets_text' not in st.session_state: st.session_state.assets_text = ""
if 'liabilities_text' not in st.session_state: st.session_state.liabilities_text = ""
if 'income_text' not in st.session_state: st.session_state.income_text = ""

with st.sidebar:
    st.header("1. Carica il Bilancio")
    uploaded_file = st.file_uploader("Seleziona un file PDF o CSV", type=["pdf", "csv"])

    with st.expander("❓ Formato CSV richiesto"):
        st.info("""
        Il file CSV deve avere le seguenti colonne:
        - **voce**: La descrizione della voce di bilancio.
        - **importo**: L'importo numerico.
        - **sezione**: Valori: `Attività`, `Passività`, `PN`, `Conto Economico`.
        - **tipo** (Opzionale, solo per CE): Valori: `Ricavo`, `Variabile`, `Fisso`.
        """)

    if uploaded_file:
        with st.spinner('Estrazione dati dal file...'):
            file_type = uploaded_file.name.split('.')[-1].lower()
            if file_type == 'pdf':
                assets, liabilities, income = extract_data_with_formatting(uploaded_file)
            elif file_type == 'csv':
                assets, liabilities, income = parse_csv_file(uploaded_file)
            else:
                assets, liabilities, income = "", "", ""
                st.error("Formato file non supportato.")
            st.session_state.assets_text = assets
            st.session_state.liabilities_text = liabilities
            st.session_state.income_text = income
            if assets or liabilities or income:
                st.success("Dati estratti! Controlla e avvia l'analisi.")

    st.header("2. Dati Finanziari")
    st.markdown("Verifica i dati estratti o inseriscili manualmente.")
    
    st.session_state.assets_text = st.text_area("ATTIVITÀ (Voce,Importo)", st.session_state.assets_text, height=150)
    st.session_state.liabilities_text = st.text_area("PASSIVITÀ E PN (Voce,Importo)", st.session_state.liabilities_text, height=150)
    st.session_state.income_text = st.text_area("CONTO ECONOMICO (Voce,Importo,Tipo*)", st.session_state.income_text, height=150, help="*Tipi: Ricavo, Variabile, Fisso")

    st.header("3. Impostazioni")
    tax_rate = st.number_input("Aliquota Fiscale (%)", value=24.0, min_value=0.0, max_value=100.0, step=0.5) / 100

    analyze_button = st.button("🚀 Elabora Analisi", use_container_width=True)

if not analyze_button:
    st.info("Carica un file o inserisci i dati nella barra laterale e clicca 'Elabora Analisi' per visualizzare i risultati.")

if analyze_button:
    assets_data = parse_textarea_data(st.session_state.assets_text)
    liabilities_data = parse_textarea_data(st.session_state.liabilities_text)
    income_data = parse_textarea_data(st.session_state.income_text)

    if not assets_data or not liabilities_data or not income_data:
        st.error("Dati insufficienti. Compila tutti i campi richiesti nella barra laterale.")
    else:
        # --- CALCOLO CON LOGICA CONTABILE CORRETTA ---
        total_raw_assets = sum(d['amount'] for d in assets_data)
        amortization_funds = sum(d['amount'] for d in liabilities_data if any(kw in d['item'].lower() for kw in KEYWORDS['special_negative']))
        
        net_total_assets = total_raw_assets - amortization_funds
        
        current_assets_raw = sum(d['amount'] for d in assets_data if any(kw in d['item'].lower() for kw in KEYWORDS['assets']['current']))
        non_current_assets_raw = sum(d['amount'] for d in assets_data if any(kw in d['item'].lower() for kw in KEYWORDS['assets']['non_current']))
        
        net_non_current_assets = non_current_assets_raw - amortization_funds

        liabilities_no_funds = [d for d in liabilities_data if not any(kw in d['item'].lower() for kw in KEYWORDS['special_negative'])]
        
        bs = {
            'current_assets': current_assets_raw,
            'non_current_assets': net_non_current_assets,
            'current_liabilities': sum(d['amount'] for d in liabilities_no_funds if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['current'])),
            'non_current_liabilities': sum(d['amount'] for d in liabilities_no_funds if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['non_current'])),
            'equity': sum(d['amount'] for d in liabilities_no_funds if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['equity'])),
        }
        
        rimanenze = sum(d['amount'] for d in assets_data if 'rimanenze' in d['item'].lower() or 'scorte' in d['item'].lower())
        
        utile_from_pdf = sum(d['amount'] for d in income_data if "utile d'esercizio" in d['item'].lower())
        if utile_from_pdf > 0:
            bs['equity'] += utile_from_pdf

        total_liabilities_and_equity = bs['current_liabilities'] + bs['non_current_liabilities'] + bs['equity']

        income = {
            'revenues': sum(d['amount'] for d in income_data if d['type'] == 'Ricavo'),
            'variable_costs': sum(d['amount'] for d in income_data if d['type'] == 'Variabile'),
            'fixed_costs': sum(d['amount'] for d in income_data if d['type'] == 'Fisso' and "utile d'esercizio" not in d['item'].lower()),
        }

        contribution_margin = income['revenues'] - income['variable_costs']
        ebit = contribution_margin - income['fixed_costs']
        interest = sum(d['amount'] for d in income_data if 'interessi' in d['item'].lower() or 'oneri finanziari' in d['item'].lower())
        ebt = ebit - interest
        taxes = ebt * tax_rate if ebt > 0 else 0
        net_income = ebt - interest

        ratios = {
            'current_ratio': bs['current_assets'] / bs['current_liabilities'] if bs['current_liabilities'] > 0 else 0,
            'quick_ratio': (bs['current_assets'] - rimanenze) / bs['current_liabilities'] if bs['current_liabilities'] > 0 else 0,
            'debt_to_equity': (bs['current_liabilities'] + bs['non_current_liabilities']) / bs['equity'] if bs['equity'] > 0 else 0,
            'ros': ebit / income['revenues'] if income['revenues'] > 0 else 0,
            'roe': net_income / bs['equity'] if bs['equity'] > 0 else 0,
            'roi': ebit / net_total_assets if net_total_assets > 0 else 0,
            'contribution_margin_ratio': contribution_margin / income['revenues'] if income['revenues'] > 0 else 0,
            'break_even_point': income['fixed_costs'] / (contribution_margin / income['revenues']) if contribution_margin > 0 else 0
        }

        # --- VISUALIZZAZIONE ---
        st.header("Risultati dell'Analisi")
        
        balance_diff = net_total_assets - total_liabilities_and_equity
        if abs(balance_diff) < 20: # Tolleranza per arrotondamenti
            st.success(f"✅ **Controllo:** Il bilancio quadra correttamente! (Differenza: {format_currency(balance_diff)})")
        else:
            st.warning(f"⚠️ **Attenzione:** Il bilancio non quadra! Differenza: {format_currency(balance_diff)}")

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

