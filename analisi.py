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
    """Formatta un numero come valuta in Euro."""
    if pd.isna(value) or not isinstance(value, (int, float)):
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
        'current': ['cassa', 'banca', 'crediti', 'clienti', 'rimanenze', 'scorte', 'ratei attivi', 'risconti attivi', 'liquidità', 'depositi bancari', 'denaro e valori'],
        'non_current': ['immobilizzazioni', 'impianti', 'macchinari', 'attrezzature', 'fabbricati', 'terreni', 'brevetti', 'marchi', 'software', 'partecipazioni', 'mobili e arredi', 'macchine d\'ufficio', 'auto', 'autocarri']
    },
    'liabilities': {
        'current': ['debiti', 'fornitori', 'tributari', 'erario', 'inps', 'inail', 'dipendenti', 'ratei passivi', 'risconti passivi', 'banche c/c passivi'],
        'non_current': ['mutui', 'finanziamenti', 'tfr', 'trattamento fine rapporto'],
        'equity': ['capitale', 'riserve', 'utile', 'perdita', 'patrimonio netto']
    },
    'special_negative': ['f.do amm', 'fondo amm'], # Voci che sono rettificative dell'attivo
    'income': {
         'revenue': ['ricavi', 'vendite', 'fatturato', 'valore della produzione', 'proventi', 'contributi in conto esercizio', 'altri ricavi'],
         'variable': ['materie', 'consumo', 'acquisti', 'sussidiarie', 'lavorazioni', 'costi per materie', 'rim.fin', 'rim.iniz'],
         'fixed': ['salari', 'stipendi', 'personale', 'costi del personale', 'ammortamenti', 'affitti', 'godimento beni terzi', 'interessi', 'oneri finanziari', 'servizi', 'sanzioni', 'multe', 'abbonamenti', 'imposte', 'oneri diversi', 'quote associative', 'quote trattamento']
    }
}

def clean_and_convert_amount(amount_str):
    """Pulisce una stringa di importo e la converte in float."""
    if not amount_str: return None
    try:
        # Gestisce formati come "1.234,56" e "1,234.56"
        cleaned_str = amount_str.strip()
        if '.' in cleaned_str and ',' in cleaned_str:
            if cleaned_str.rfind('.') > cleaned_str.rfind(','):
                # Formato americano: 1,234.56
                return float(cleaned_str.replace(',', ''))
            else:
                # Formato europeo: 1.234,56
                return float(cleaned_str.replace('.', '').replace(',', '.'))
        return float(cleaned_str.replace(',', '.'))
    except (ValueError, TypeError):
        return None

# --- NUOVO MOTORE DI ESTRAZIONE CON PDFPLUMBER ---
def extract_and_parse_with_pdfplumber(pdf_file):
    """
    Estrae dati da un PDF usando pdfplumber per mantenere la struttura a colonne.
    """
    assets_data, liabilities_data, income_data = [], [], []
    
    with pdfplumber.open(io.BytesIO(pdf_file.read())) as pdf:
        for page in pdf.pages:
            # Estrae il testo per righe mantenendo un minimo di allineamento
            text = page.extract_text(x_tolerance=2, y_tolerance=2)
            if not text: continue

            for line in text.split('\n'):
                line = line.strip()
                # Salta le righe di intestazione o irrilevanti
                if not line or len(line) < 5 or re.match(r'^(Pag\.|SITUAZIONE|Esercizio|Registrazioni)', line):
                    continue
                
                # Cerca coppie voce-importo
                matches = re.findall(r'([a-zA-Z].*?)\s+(-?[\d.,]+\d)\b', line)
                
                for item_name, amount_str in matches:
                    item_name = re.sub(r'^\d+\s*-\s*', '', item_name.strip())
                    amount = clean_and_convert_amount(amount_str)
                    
                    if amount is None or len(item_name) < 4: continue
                    
                    item_name_lower = item_name.lower()
                    entry_str = f"{item_name},{amount}"

                    # Classificazione
                    if any(kw in item_name_lower for kw in KEYWORDS['special_negative']):
                        liabilities_data.append(f"{item_name},{abs(amount)}")
                        continue

                    found = False
                    if any(kw in item_name_lower for kw in KEYWORDS['assets']['current'] + KEYWORDS['assets']['non_current']):
                        assets_data.append(entry_str)
                        found = True
                    elif any(kw in item_name_lower for kw in KEYWORDS['liabilities']['current'] + KEYWORDS['liabilities']['non_current'] + KEYWORDS['liabilities']['equity']):
                        liabilities_data.append(entry_str)
                        found = True
                    
                    if not found:
                        ce_type = "Fisso"
                        if any(kw in item_name_lower for kw in KEYWORDS['income']['revenue']): ce_type = "Ricavo"
                        elif any(kw in item_name_lower for kw in KEYWORDS['income']['variable']): ce_type = "Variabile"
                        income_data.append(f"{entry_str},{ce_type}")

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
st.markdown("Carica un bilancio in formato PDF per estrarre e analizzare i dati automaticamente, oppure inseriscili manualmente.")

if 'assets_text' not in st.session_state: st.session_state.assets_text = ""
if 'liabilities_text' not in st.session_state: st.session_state.liabilities_text = ""
if 'income_text' not in st.session_state: st.session_state.income_text = ""

with st.sidebar:
    st.header("1. Carica Bilancio PDF")
    uploaded_file = st.file_uploader("Seleziona un PDF", type="pdf")

    if uploaded_file:
        with st.spinner('Estrazione dati dal PDF in corso...'):
            assets, liabilities, income = extract_and_parse_with_pdfplumber(uploaded_file)
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
        net_income = ebt - taxes

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
        if abs(balance_diff) < 10: # Tolleranza per arrotondamenti
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

