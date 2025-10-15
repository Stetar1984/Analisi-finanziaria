# -*- coding: utf-8 -*-
"""
Applicazione Streamlit per l'analisi di bilancio da un file Excel.
L'app legge un file con colonne 'VOCE', 'IMPORTO', 'SEZIONE' ed esegue
un'analisi calcolando i principali indici e margini di bilancio.
"""

import streamlit as st
import pandas as pd
from io import BytesIO

# --- Funzioni di Analisi (adattate dal codice originale) ---

def is_attivo_corrente(descrizione: str) -> bool:
    """Verifica se una voce dell'attivo è da considerarsi corrente."""
    s = descrizione.lower()
    keywords = [
        "crediti v/clienti", "crediti tributari", "crediti v/altri",
        "depositi bancari", "cassa", "rimanenze", "ratei e risconti attivi",
        "liquidità immediate"
    ]
    return any(k in s for k in keywords)

def is_passivo_corrente(descrizione: str) -> bool:
    """Verifica se una voce del passivo è da considerarsi corrente."""
    s = descrizione.lower()
    keywords = [
        "debiti verso fornitori", "debiti tributari", "debiti v/istit.",
        "altri debiti", "ratei e risconti passivi"
    ]
    return any(k in s for k in keywords)

def calculate_kpis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcola gli indicatori di bilancio (KPI) partendo da un DataFrame strutturato.
    """
    # Assicuriamoci che la colonna importo sia numerica, gestendo il formato italiano/europeo
    # Rimuove il '.' per le migliaia e sostituisce ',' con '.' per i decimali.
    if 'IMPORTO' in df.columns:
        df['IMPORTO'] = df['IMPORTO'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df['IMPORTO'] = pd.to_numeric(df['IMPORTO'], errors='coerce').fillna(0)

    # Totali da Stato Patrimoniale
    totale_attivita = df[df['SEZIONE'].str.upper() == "ATTIVITA'"]['IMPORTO'].sum()
    totale_passivita = df[df['SEZIONE'].str.upper() == "PASSIVITA'"]['IMPORTO'].sum()

    # Calcolo Attivo e Passivo Corrente
    df_attivo = df[df['SEZIONE'].str.upper() == "ATTIVITA'"]
    attivo_corrente = df_attivo[df_attivo['VOCE'].apply(is_attivo_corrente)]['IMPORTO'].sum()

    df_passivo = df[df['SEZIONE'].str.upper() == "PASSIVITA'"]
    passivo_corrente = df_passivo[df_passivo['VOCE'].apply(is_passivo_corrente)]['IMPORTO'].sum()
    
    # Dettagli per i calcoli
    liquidita_immediate = df[df['VOCE'].str.lower().str.contains("depositi bancari|cassa|denaro e valori", regex=True)]['IMPORTO'].sum()
    rimanenze = df[df['VOCE'].str.lower().str.contains("rimanenze", regex=True)]['IMPORTO'].sum()

    # Totali da Conto Economico
    df_ce = df[df['SEZIONE'].str.upper() == "CONTO ECONOMICO"]
    
    ricavi = df_ce[df_ce['VOCE'].str.lower().str.contains("ricavi delle vendite|altri ricavi|contributi", regex=True)]['IMPORTO'].sum()
    
    # Funzione di supporto per sommare blocchi di costi
    def sum_block(mask_regex: str) -> float:
        block = df_ce[df_ce['VOCE'].str.lower().str.contains(mask_regex, regex=True)]
        return float(block['IMPORTO'].sum())

    costi_materie = sum_block("costi mat|acquisto di materie")
    costi_servizi = sum_block("costi per servizi")
    costi_godimento = sum_block("costi per godimento beni di terzi")
    costi_personale = sum_block("costi per il personale|salari e stipendi|oneri sociali")
    ammortamenti = sum_block("ammortamenti")
    altri_costi = sum_block("oneri diversi|sopravvenienze passive|imposte e tasse")

    # Calcolo Valore Aggiunto, EBITDA, EBIT
    valore_produzione = ricavi 
    valore_aggiunto = valore_produzione - (costi_materie + costi_servizi + costi_godimento + altri_costi)
    ebitda = valore_aggiunto - costi_personale
    ebit = ebitda - ammortamenti

    # Calcolo Indici e Margini
    current_ratio = (attivo_corrente / passivo_corrente) if passivo_corrente else 0
    quick_ratio = ((attivo_corrente - rimanenze) / passivo_corrente) if passivo_corrente else 0
    ccn = attivo_corrente - passivo_corrente
    margine_tesoreria = (liquidita_immediate + (attivo_corrente - liquidita_immediate - rimanenze)) - passivo_corrente
    ebitda_margin = (ebitda / valore_produzione) if valore_produzione else 0
    
    # Creazione del DataFrame di output
    summary = {
        "Stato Patrimoniale": "",
        "Totale Attività": totale_attivita,
        "Totale Passività": totale_passivita,
        "Attivo Corrente": attivo_corrente,
        "Passivo Corrente": passivo_corrente,
        "Liquidità Immediate": liquidita_immediate,
        "Rimanenze": rimanenze,
        "Conto Economico": "",
        "Valore della Produzione (Ricavi)": valore_produzione,
        "Valore Aggiunto": valore_aggiunto,
        "EBITDA (Margine Operativo Lordo)": ebitda,
        "EBIT (Margine Operativo Netto)": ebit,
        "Indici e Margini": "",
        "Capitale Circolante Netto (CCN)": ccn,
        "Margine di Tesoreria": margine_tesoreria,
        "Current Ratio": f"{current_ratio:.2f}",
        "Quick Ratio (Acid Test)": f"{quick_ratio:.2f}",
        "EBITDA Margin": f"{ebitda_margin:.2%}",
    }
    
    kpis_df = pd.DataFrame(summary.items(), columns=['Indicatore', 'Valore'])
    return kpis_df


# --- Interfaccia Streamlit ---

st.set_page_config(page_title="Analisi di Bilancio", layout="wide", initial_sidebar_state="collapsed")

st.title("📊 Analizzatore di Bilancio da File Excel")
st.caption("Carica un file Excel (.xlsx) o CSV con colonne 'VOCE', 'IMPORTO', 'SEZIONE' per generare un'analisi automatica.")

uploaded_file = st.file_uploader(
    "Seleziona il tuo file di bilancio", 
    type=['xlsx', 'xls', 'csv'],
    help="Il file deve contenere le colonne: VOCE (descrizione), IMPORTO (valore numerico), SEZIONE (es. ATTIVITA', PASSIVITA', CONTO ECONOMICO)"
)

if uploaded_file is not None:
    try:
        # Lettura del file caricato
        if uploaded_file.name.endswith('.csv'):
            # Prova diversi separatori comuni per i CSV italiani
            try:
                df = pd.read_csv(uploaded_file, sep=';')
            except Exception:
                df = pd.read_csv(uploaded_file, sep=',')
        else:
            df = pd.read_excel(uploaded_file)

        # --- FIX: Assicura che la colonna VOCE sia di tipo stringa per evitare errori ---
        # Converte la colonna 'VOCE' in stringa, gestendo valori mancanti (NaN)
        # che altrimenti causerebbero l'errore "'float' object has no attribute 'lower'".
        if 'VOCE' in df.columns:
            df['VOCE'] = df['VOCE'].astype(str).fillna('')


        # Validazione delle colonne necessarie
        required_columns = ['VOCE', 'IMPORTO', 'SEZIONE']
        if not all(col in df.columns for col in required_columns):
            st.error(f"Errore: Il file deve contenere le seguenti colonne: {', '.join(required_columns)}")
        else:
            with st.spinner('Elaborazione in corso...'):
                # Calcolo dei KPI
                kpis_df = calculate_kpis(df)

                st.success("Analisi completata!")

                # Visualizzazione dei risultati
                st.subheader("Indicatori e Margini di Bilancio (KPIs)")
                
                # Formattazione per la visualizzazione
                formatted_kpis = kpis_df.copy()
                
                def format_value(row):
                    if isinstance(row['Valore'], (int, float)):
                        return f"€ {row['Valore']:,.2f}"
                    return row['Valore']

                formatted_kpis['Valore'] = formatted_kpis.apply(format_value, axis=1)

                # Rimuovi le righe che fungono da separatori
                formatted_kpis = formatted_kpis[formatted_kpis['Valore'] != '']
                
                st.dataframe(
                    formatted_kpis, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={"Indicatore": st.column_config.TextColumn(width="large")}
                )

                st.subheader("Dati originali caricati")
                st.dataframe(df, use_container_width=True, hide_index=True)

                # Funzionalità di download
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df.to_excel(writer, sheet_name='Dati Originali', index=False)
                    kpis_df.to_excel(writer, sheet_name='Analisi KPI', index=False)
                
                st.download_button(
                    label="📥 Scarica Analisi Completa (Excel)",
                    data=output.getvalue(),
                    file_name=f"analisi_bilancio_{uploaded_file.name}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

    except Exception as e:
        st.error(f"Si è verificato un errore durante l'elaborazione del file: {e}")
        st.warning("Assicurati che il file sia nel formato corretto e non sia corrotto.")
else:
    st.info("In attesa di un file di bilancio per iniziare l'analisi.")

