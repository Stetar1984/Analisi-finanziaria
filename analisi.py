# -*- coding: utf-8 -*-
"""
Applicazione Streamlit per l'analisi di bilancio da un file Excel.
L'app legge un file con colonne 'VOCE', 'IMPORTO', 'SEZIONE' ed esegue
un'analisi calcolando i principali indici e margini di bilancio.
"""

import streamlit as st
import pandas as pd
from io import BytesIO

# --- Funzioni di Analisi (con logica di riclassificazione) ---

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
    Calcola gli indicatori di bilancio (KPI) partendo da un DataFrame strutturato,
    eseguendo una riclassificazione del bilancio.
    """
    # --- 1. Preparazione dei Dati ---
    df['IMPORTO'] = df['IMPORTO'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
    df['IMPORTO'] = pd.to_numeric(df['IMPORTO'], errors='coerce').fillna(0)
    # Colonna helper per confronti non case-sensitive
    df['VOCE_LOWER'] = df['VOCE'].str.lower()

    # --- 2. Suddivisione del DataFrame per Sezioni ---
    df_attivo = df[df['SEZIONE'].str.upper() == "ATTIVITA'"].copy()
    df_passivo_netto = df[df['SEZIONE'].str.upper() == "PASSIVITA'"].copy()
    df_ce = df[df['SEZIONE'].str.upper() == "CONTO ECONOMICO"].copy()

    # --- 3. Riclassificazione e Calcolo Aggregati Stato Patrimoniale ---
    totale_attivo_grezzo = df_attivo['IMPORTO'].sum()

    # Separazione delle componenti dal lato "PASSIVITA'" del file originale
    fondi_ammortamento = df_passivo_netto[df_passivo_netto['VOCE_LOWER'].str.contains("f.do amm.|fondo amm")].IMPORTO.sum()
    patrimonio_netto = df_passivo_netto[df_passivo_netto['VOCE_LOWER'].str.contains("capitale sociale|riserva|utile|perdita")].IMPORTO.sum()
    
    # I debiti sono ciò che rimane nella sezione PASSIVITA' dopo aver tolto PN e Fondi Amm.
    filtro_debiti = ~df_passivo_netto['VOCE_LOWER'].str.contains("f.do amm.|fondo amm|capitale sociale|riserva|utile|perdita")
    df_debiti = df_passivo_netto[filtro_debiti]
    debiti_totali = df_debiti.IMPORTO.sum()

    totale_passivo_e_netto = debiti_totali + patrimonio_netto + fondi_ammortamento
    
    # Calcolo aggregati dell'Attivo
    attivo_corrente = df_attivo[df_attivo['VOCE'].apply(is_attivo_corrente)].IMPORTO.sum()
    immobilizzazioni_lorde = totale_attivo_grezzo - attivo_corrente
    immobilizzazioni_nette = immobilizzazioni_lorde - fondi_ammortamento
    totale_attivo_riclassificato = immobilizzazioni_nette + attivo_corrente

    # Dettagli dell'Attivo Corrente
    liquidita_immediate = df_attivo[df_attivo['VOCE_LOWER'].str.contains("depositi bancari|cassa")].IMPORTO.sum()
    rimanenze = df_attivo[df_attivo['VOCE_LOWER'].str.contains("rimanenze")].IMPORTO.sum()

    # Calcolo aggregati del Passivo
    passivo_corrente = df_debiti[df_debiti['VOCE'].apply(is_passivo_corrente)].IMPORTO.sum()
    passivita_consolidate = debiti_totali - passivo_corrente

    # --- 4. Riclassificazione Conto Economico a Valore Aggiunto ---
    valore_produzione = df_ce[df_ce['VOCE_LOWER'].str.contains("ricavi|contributi|variazione rimanenze")].IMPORTO.sum()
    costi_esterni = df_ce[df_ce['VOCE_LOWER'].str.contains("costi mat|acquisto di materie|costi per servizi|godimento beni")].IMPORTO.sum()
    valore_aggiunto = valore_produzione - costi_esterni
    costi_personale = df_ce[df_ce['VOCE_LOWER'].str.contains("personale|salari|stipendi|oneri sociali")].IMPORTO.sum()
    ebitda = valore_aggiunto - costi_personale
    ammortamenti = df_ce[df_ce['VOCE_LOWER'].str.contains("ammortamenti")].IMPORTO.sum()
    oneri_diversi_gestione = df_ce[df_ce['VOCE_LOWER'].str.contains("oneri diversi|perdite su crediti|sopravvenienze passive|imposte e tasse")].IMPORTO.sum()
    ebit = ebitda - ammortamenti - oneri_diversi_gestione

    # --- 5. Calcolo Indici, Margini e Controlli ---
    ccn = attivo_corrente - passivo_corrente
    margine_tesoreria = (attivo_corrente - rimanenze) - passivo_corrente
    current_ratio = (attivo_corrente / passivo_corrente) if passivo_corrente else 0
    quick_ratio = ((attivo_corrente - rimanenze) / passivo_corrente) if passivo_corrente else 0
    ebitda_margin = (ebitda / valore_produzione) if valore_produzione else 0
    check_quadratura = totale_attivo_grezzo - totale_passivo_e_netto

    # --- 6. Creazione del DataFrame di Output ---
    summary = {
        "Controllo Quadratura (Attivo - Passivo e Netto)": check_quadratura,
        "--- Stato Patrimoniale Riclassificato ---": "",
        "Immobilizzazioni Nette": immobilizzazioni_nette,
        "Attivo Corrente": attivo_corrente,
        "   di cui Liquidità Immediate": liquidita_immediate,
        "   di cui Rimanenze": rimanenze,
        "TOTALE ATTIVO RICLASSIFICATO": totale_attivo_riclassificato,
        "Patrimonio Netto": patrimonio_netto,
        "Passività Consolidate (M/L Termine)": passivita_consolidate,
        "Passivo Corrente (Breve Termine)": passivo_corrente,
        "TOTALE PASSIVO E NETTO": patrimonio_netto + debiti_totali,
        "--- Conto Economico a Valore Aggiunto ---": "",
        "Valore della Produzione": valore_produzione,
        "Costi Esterni": costi_esterni,
        "Valore Aggiunto": valore_aggiunto,
        "Costo del Personale": costi_personale,
        "EBITDA (Margine Operativo Lordo)": ebitda,
        "Ammortamenti e Altri Oneri": ammortamenti + oneri_diversi_gestione,
        "EBIT (Risultato Operativo)": ebit,
        "--- Indici e Margini ---": "",
        "Capitale Circolante Netto (CCN)": ccn,
        "Margine di Tesoreria": margine_tesoreria,
        "Current Ratio": f"{current_ratio:.2f}",
        "Quick Ratio (Acid Test)": f"{quick_ratio:.2f}",
        "EBITDA Margin": f"{ebitda_margin:.2%}",
    }
    
    kpis_df = pd.DataFrame(summary.items(), columns=['Indicatore', 'Valore'])
    return kpis_df


# --- Interfaccia Streamlit ---
# (Il resto del codice rimane invariato)

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
            try:
                df = pd.read_csv(uploaded_file, sep=';')
            except Exception:
                df = pd.read_csv(uploaded_file, sep=',')
        else:
            df = pd.read_excel(uploaded_file)

        # Assicura che la colonna VOCE sia di tipo stringa per evitare errori
        if 'VOCE' in df.columns:
            df['VOCE'] = df['VOCE'].astype(str).fillna('')

        # Validazione delle colonne necessarie
        required_columns = ['VOCE', 'IMPORTO', 'SEZIONE']
        if not all(col in df.columns for col in required_columns):
            st.error(f"Errore: Il file deve contenere le seguenti colonne: {', '.join(required_columns)}")
        else:
            with st.spinner('Elaborazione in corso...'):
                kpis_df = calculate_kpis(df)

                st.success("Analisi completata!")

                st.subheader("Indicatori e Margini di Bilancio (KPIs)")
                
                # Formattazione per la visualizzazione
                formatted_kpis = kpis_df.copy()
                
                def format_value(row):
                    # Formatta solo se il valore è un numero (int o float)
                    if isinstance(row['Valore'], (int, float)):
                         # Usa la virgola come separatore delle migliaia e il punto per i decimali, con 2 cifre decimali
                        return f"€ {row['Valore']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    return row['Valore']

                formatted_kpis['Valore'] = formatted_kpis.apply(format_value, axis=1)
                
                # Rimuovi le righe che fungono da separatori/titoli di sezione
                formatted_kpis = formatted_kpis[formatted_kpis['Valore'] != '']
                
                st.dataframe(
                    formatted_kpis, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={"Indicatore": st.column_config.TextColumn(width="large")}
                )

                st.subheader("Dati originali caricati")
                st.dataframe(df.drop(columns=['VOCE_LOWER']), use_container_width=True, hide_index=True)

                # Funzionalità di download
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df.drop(columns=['VOCE_LOWER']).to_excel(writer, sheet_name='Dati Originali', index=False)
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

