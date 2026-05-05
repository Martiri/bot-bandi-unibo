import requests
from bs4 import BeautifulSoup
import json
import time
import os
import io
import PyPDF2
from urllib.parse import urljoin

# --- CONFIGURAZIONE TELEGRAM TRAMITE GITHUB SECRETS ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- CONFIGURAZIONE RICERCA ---
FILE_MEMORIA = "bandi_trovati.json"


# Il tuo link con i filtri: Fisica, Laurea (Triennale), iscritti dal secondo anno
URL_UNIBO_PREMI = "https://bandi.unibo.it/agevolazioni/opportunita?riservato=iscritti&tipocorso=laurea&corsi=6639%2C9244%2C8007&struttura=&search="

KEYWORDS_MERITO = ["merito", "eccellenza", "premio", "curriculum", "media ponderata", "cfu"]
KEYWORDS_ESCLUDI = ["esclusivamente isee", "solo isee"]


def invia_notifica_telegram(messaggio):
    """Invia un messaggio tramite Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": messaggio,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Errore Telegram: {e}")


def carica_memoria():
    if os.path.exists(FILE_MEMORIA):
        try:
            with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            # Se il file esiste ma è completamente vuoto o corrotto, 
            # Python ignora l'errore e parte con una memoria vuota.
            return []
    return []

def salva_memoria(memoria):
    with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(memoria, f)


def estrai_testo_pdf(url_pdf):
    """Scarica il PDF in memoria ed estrae tutto il testo."""
    print(f"📄 Lettura PDF in corso: {url_pdf}")
    try:
        response = requests.get(url_pdf, stream=True, timeout=15)
        response.raise_for_status()
        
        pdf_file = io.BytesIO(response.content)
        reader = PyPDF2.PdfReader(pdf_file)
        
        testo_completo = ""
        for page in reader.pages:
            testo_estratto = page.extract_text()
            if testo_estratto:
                testo_completo += testo_estratto + " "
                
        return testo_completo.lower()
    except Exception as e:
        print(f"Errore durante l'estrazione del PDF: {e}")
        return ""


def trova_pdf_nel_bando(url_dettaglio_bando):
    """Visita la pagina specifica del bando e cerca link ai file .pdf"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url_dettaglio_bando, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.lower().endswith('.pdf'):
                return urljoin("https://bandi.unibo.it", href)
        return None
    except Exception as e:
        print(f"Errore nella ricerca PDF: {e}")
        return None


def valuta_testo_bando(testo_da_valutare):
    """Valuta il testo combinato e restituisce (Esito, Motivo)."""
    
    # Controllo scarto (ISEE)
    for kw in KEYWORDS_ESCLUDI:
        if kw in testo_da_valutare:
            return False, f"Scartato (Trovato limite: '{kw}')"
            
    # Controllo approvazione (Merito)
    for kw in KEYWORDS_MERITO:
        if kw in testo_da_valutare:
            return True, f"Trovato riferimento a: '{kw}'"
            
    # Default (Nessun limite ISEE esplicito)
    return True, "Nessun limite ISEE restrittivo rilevato"

def controlla_bandi_unibo(memoria):
    print("Controllo sito UniBo in corso...")
    nuovi_bandi_trovati = 0
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(URL_UNIBO_PREMI, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link_tag in soup.find_all('a', href=True):
            href = link_tag['href'].lower()
            
            if href == "/agevolazioni/opportunita" or href == "/agevolazioni/opportunita/" or href == "#":
                continue
            
            if '/bando/' in href or '/agevolazioni/opportunita/' in href:
                link_completo = urljoin("https://bandi.unibo.it", link_tag['href'])
                titolo = link_tag.text.strip()
                
                if len(titolo) < 10 or link_completo in memoria:
                    continue
                
                padre = link_tag.find_parent(['tr', 'li', 'div', 'article'])
                testo_circostante = padre.text.strip().lower() if padre else ""
                
                if "scaduto" in testo_circostante:
                    continue
                
                testo_totale = (titolo + " " + testo_circostante).lower()
                
                url_pdf = trova_pdf_nel_bando(link_completo)
                if url_pdf:
                    testo_pdf = estrai_testo_pdf(url_pdf)
                    testo_totale += " " + testo_pdf
                
                # Ora riceviamo sia l'esito (True/False) sia il motivo
                bando_valido, motivo = valuta_testo_bando(testo_totale)
                
                if bando_valido:
                    nota_pdf = "📄 (PDF Analizzato)" if url_pdf else "🌐 (Solo Testo Web)"
                    
                    # Creiamo un'anteprima pulita del testo circostante (massimo 200 caratteri)
                    testo_pulito = " ".join(testo_circostante.split())
                    if len(testo_pulito) > 200:
                        breve_descrizione = testo_pulito[:200] + "..."
                    else:
                        breve_descrizione = testo_pulito
                        
                    # Se il sito non fornisce testo circostante, mettiamo un avviso
                    if not breve_descrizione or breve_descrizione == titolo.lower():
                        breve_descrizione = "Nessuna descrizione breve disponibile sulla pagina web. Clicca il link per i dettagli."

                    # Nuovo formato del messaggio Telegram
                    messaggio = (
                        f"🎓 <b>Nuovo Bando Trovato!</b> {nota_pdf}\n\n"
                        f"<b>Titolo:</b> {titolo}\n\n"
                        f"✅ <b>Perché te lo segnalo:</b> {motivo}\n"
                        f"ℹ️ <b>Info:</b> <i>{breve_descrizione.capitalize()}</i>\n\n"
                        f"<a href='{link_completo}'>Vai alla pagina del bando</a>"
                    )
                    
                    invia_notifica_telegram(messaggio)
                    print(f"\n🎯 NUOVO BANDO: {titolo}\n💡 MOTIVO: {motivo}\n🔗 LINK: {link_completo}\n")
                    
                    memoria.append(link_completo)
                    nuovi_bandi_trovati += 1
                    time.sleep(3)
                    
    except requests.exceptions.RequestException as e:
        print(f"Errore di connessione a UniBo: {e}")
        
    return nuovi_bandi_trovati

def main():
    print("Avvio script di monitoraggio bandi...")
    memoria_bandi = carica_memoria()
    
    # Se usi PythonAnywhere/Replit, questo codice girerà una volta sola ad ogni avvio programmato
    nuovi = controlla_bandi_unibo(memoria_bandi)
    
    if nuovi > 0:
        salva_memoria(memoria_bandi)
        print(f"Operazione conclusa. Trovati {nuovi} nuovi bandi validi.")
    else:
        print("Operazione conclusa. Nessun bando interessante al momento.")


if __name__ == "__main__":
    main()
