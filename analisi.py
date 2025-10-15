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
        'current': ['cassa', 'banca', 'crediti', 'clienti', 'rimanenze', 'scorte', 'ratei attivi', 'risconti attivi', 'liquidità', 'depositi bancari'],
        'non_current': ['immobilizzazioni', 'impianti', 'macchinari', 'attrezzature', 'fabbricati', 'terreni', 'brevetti', 'marchi', 'software', 'partecipazioni', 'mobili e arredi', 'macchine d\'ufficio', 'auto']
    },
    'liabilities': {
        'current': ['debiti', 'fornitori', 'tributari', 'erario', 'inps', 'inail', 'dipendenti', 'ratei passivi', 'risconti passivi', 'banche c/c passivi'],
        'non_current': ['mutui', 'finanziamenti', 'tfr', 'trattamento fine rapporto'],
        'equity': ['capitale', 'riserve', 'utile', 'perdita', 'patrimonio netto']
    },
    'special_negative': ['f.do amm', 'fondo amm'], # Voci che sono rettificative dell'attivo
    'income': {
         'revenue': ['ricavi', 'vendite', 'fatturato', 'valore della produzione', 'proventi'],
         'variable': ['materie', 'consumo', 'acquisti', 'sussidiarie', 'lavorazioni', 'costi per materie'],
         'fixed': ['salari', 'stipendi', 'personale', 'costi del personale', 'ammortamenti', 'affitti', 'godimento beni terzi', 'interessi', 'oneri finanziari', 'servizi', 'sanzioni', 'multe', 'abbonamenti', 'imposte']
    }
}

def extract_text_from_pdf(pdf_file):
    """Estrae il testo da un file PDF caricato."""
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_file.read()))
        text = ""
        for page in pdf_reader.pages:
            # Aggiunge uno spazio per evitare che parole di pagine diverse si uniscano
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        st.error(f"Errore nella lettura del PDF: {e}")
        return ""

# --- SEZIONE MODIFICATA: Parsing Migliorato ---
def parse_financial_text(text):
    """
    Analizza il testo estratto per trovare tutte le coppie voce-importo,
    anche quando sono multiple sulla stessa riga, e gestisce la logica contabile.
    """
    assets_data, liabilities_data, income_data = [], [], []
    
    # Regex per trovare una descrizione (anche con numeri, ma non all'inizio) seguita da un importo.
    pattern = re.compile(r"([a-zA-Z][a-zA-Z\s.,()'-/]+?)\s+([\d.,]+[\d])")

    # Rimuove header e footer comuni per ridurre il "rumore"
    clean_text = re.sub(r'SITUAZIONE.*?\n|Pag\..*?\n|Utente:.*?\n|Data:.*?\n', '', text, flags=re.IGNORECASE)

    for line in clean_text.split('\n'):
        # Rimuove codici conto iniziali (es. '13090000 - ')
        cleaned_line = re.sub(r'^\d+\s*-\s*', '', line.strip())
        
        matches = pattern.findall(cleaned_line)
        
        for match in matches:
            item_name = match[0].strip()
            amount_str = match[1].strip()

            try:
                # Gestisce formattazione europea (1.234,56) e americana (1,234.56)
                if ',' in amount_str and '.' in amount_str:
                    if amount_str.rfind('.') > amount_str.rfind(','):
                        # Formato americano: 1,234.56 -> 1234.56
                        amount = float(amount_str.replace(',', ''))
                    else:
                        # Formato europeo: 1.234,56 -> 1234.56
                        amount = float(amount_str.replace('.', '').replace(',', '.'))
                else:
                     amount = float(amount_str.replace(',', '.'))

            except ValueError:
                continue

            # Ignora voci irrilevanti
            if len(item_name) < 4 or item_name.lower() in ['dal', 'al']:
                continue

            item_name_lower = item_name.lower()
            
            # Logica contabile per Fondi Ammortamento
            if any(kw in item_name_lower for kw in KEYWORDS['special_negative']):
                # Questi sono fondi rettificativi dell'attivo. Vengono memorizzati come passività
                # con valore positivo per la visualizzazione, ma la logica di calcolo li sottrarrà.
                entry = f"{item_name},{abs(amount)}"
                liabilities_data.append(entry)
                continue

            entry = f"{item_name},{amount}"
            
            # Classificazione basata su keyword
            found = False
            if any(kw in item_name_lower for kw in KEYWORDS['assets']['current'] + KEYWORDS['assets']['non_current']):
                assets_data.append(entry)
                found = True
            elif any(kw in item_name_lower for kw in KEYWORDS['liabilities']['current'] + KEYWORDS['liabilities']['non_current'] + KEYWORDS['liabilities']['equity']):
                liabilities_data.append(entry)
                found = True
            
            if not found:
                ce_type = "Fisso"
                if any(kw in item_name_lower for kw in KEYWORDS['income']['revenue']):
                    ce_type = "Ricavo"
                elif any(kw in item_name_lower for kw in KEYWORDS['income']['variable']):
                    ce_type = "Variabile"
                income_data.append(f"{entry},{ce_type}")

    return "\n".join(assets_data), "\n".join(liabilities_data), "\n".join(income_data)
# --- FINE SEZIONE MODIFICATA ---

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
            pass
    return data

# --- INTERFACCIA UTENTE (UI) ---
st.title("📊 Analisi di Bilancio Automatizzata")
st.markdown("Carica un bilancio in formato PDF per estrarre e analizzare i dati automaticamente, oppure inseriscili manualmente.")

if 'assets_text' not in st.session_state:
    st.session_state.assets_text = ""
if 'liabilities_text' not in st.session_state:
    st.session_state.liabilities_text = ""
if 'income_text' not in st.session_state:
    st.session_state.income_text = ""

with st.sidebar:
    st.header("1. Carica Bilancio PDF")
    uploaded_file = st.file_uploader("Seleziona un PDF", type="pdf")

    if uploaded_file:
        with st.spinner('Estrazione dati dal PDF in corso...'):
            raw_text = extract_text_from_pdf(uploaded_file)
            if raw_text:
                assets, liabilities, income = parse_financial_text(raw_text)
                st.session_state.assets_text = assets
                st.session_state.liabilities_text = liabilities
                st.session_state.income_text = income
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
    st.info("Carica un PDF o inserisci i dati nella barra laterale e clicca 'Elabora Analisi' per visualizzare i risultati.")

if analyze_button:
    assets_data = parse_textarea_data(st.session_state.assets_text)
    liabilities_data = parse_textarea_data(st.session_state.liabilities_text)
    income_data = parse_textarea_data(st.session_state.income_text)

    if not assets_data or not liabilities_data or not income_data:
        st.error("Dati insufficienti. Compila tutti i campi richiesti nella barra laterale.")
    else:
        # --- CALCOLO CON LOGICA CONTABILE CORRETTA ---
        
        # 1. Calcolo Attività al netto dei fondi rettificativi
        total_raw_assets = sum(d['amount'] for d in assets_data)
        amortization_funds = sum(d['amount'] for d in liabilities_data if any(kw in d['item'].lower() for kw in KEYWORDS['special_negative']))
        
        # L'attivo netto è il totale attivo lordo meno i fondi ammortamento
        net_total_assets = total_raw_assets - amortization_funds
        
        # Riclassificazione Attivo
        current_assets_raw = sum(d['amount'] for d in assets_data if any(kw in d['item'].lower() for kw in KEYWORDS['assets']['current']))
        non_current_assets_raw = sum(d['amount'] for d in assets_data if any(kw in d['item'].lower() for kw in KEYWORDS['assets']['non_current']))
        
        # Si assume che i fondi ammortamento rettifichino l'attivo non corrente
        net_non_current_assets = non_current_assets_raw - amortization_funds

        # 2. Riclassificazione Passività e PN (escludendo i fondi ammortamento)
        liabilities_no_funds = [d for d in liabilities_data if not any(kw in d['item'].lower() for kw in KEYWORDS['special_negative'])]
        
        bs = {
            'current_assets': current_assets_raw,
            'non_current_assets': net_non_current_assets,
            'current_liabilities': sum(d['amount'] for d in liabilities_no_funds if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['current'])),
            'non_current_liabilities': sum(d['amount'] for d in liabilities_no_funds if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['non_current'])),
            'equity': sum(d['amount'] for d in liabilities_no_funds if any(kw in d['item'].lower() for kw in KEYWORDS['liabilities']['equity'])),
        }
        
        rimanenze = sum(d['amount'] for d in assets_data if 'rimanenze' in d['item'].lower() or 'scorte' in d['item'].lower())
        
        total_liabilities_and_equity = bs['current_liabilities'] + bs['non_current_liabilities'] + bs['equity']
        
        # 3. Conto Economico
        income = {
            'revenues': sum(d['amount'] for d in income_data if d['type'] == 'Ricavo'),
            'variable_costs': sum(d['amount'] for d in income_data if d['type'] == 'Variabile'),
            'fixed_costs': sum(d['amount'] for d in income_data if d['type'] == 'Fisso'),
        }
        # Aggiungiamo l'utile/perdita dal PDF al patrimonio netto per la quadratura
        utile_from_pdf = sum(d['amount'] for d in income_data if 'utile' in d['item'].lower())
        bs['equity'] += utile_from_pdf
        total_liabilities_and_equity += utile_from_pdf

        contribution_margin = income['revenues'] - income['variable_costs']
        ebit = contribution_margin - income['fixed_costs']
        interest = sum(d['amount'] for d in income_data if 'interessi' in d['item'].lower() or 'oneri finanziari' in d['item'].lower())
        ebt = ebit - interest
        taxes = ebt * tax_rate if ebt > 0 else 0
        net_income = ebt - taxes

        # 4. Calcolo Indici
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
        if abs(balance_diff) > 1:
            st.warning(f"⚠️ **Attenzione:** Il bilancio non quadra! Differenza: {format_currency(balance_diff)}")
        else:
            st.success("✅ **Controllo:** Il bilancio quadra correttamente.")

        tab1, tab2, tab3 = st.tabs(["📈 Dashboard Indici", "📑 Stato Patrimoniale", "💰 Conto Economico"])
        
        with tab1:
            # ... (UI invariata) ...
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
            # ... (UI invariata) ...
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

