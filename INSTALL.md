# WorkBench.g - Guida all'Installazione

## Descrizione

WorkBench.g è un'applicazione web per gestire sessioni tmux locali e remote attraverso un'interfaccia browser moderna. Sviluppata da InsightG.

### Funzionalità principali:

- ✅ Autenticazione PAM (utenti di sistema)
- ✅ Gestione sessioni tmux locali e remote via SSH
- ✅ Host remoti configurabili dall'interfaccia web
- ✅ Terminale web integrato (ttyd)
- ✅ Creazione, rinomina ed eliminazione sessioni con conferma
- ✅ Pulsanti "+" per creare rapidamente nuove sessioni
- ✅ Menu contestuale con tasto destro sulle tab
- ✅ Zoom dei caratteri del terminale (Ctrl +/-)
- ✅ Modalità local (singolo server) e remote (con nginx proxy)
- ✅ Interfaccia moderna con logo InsightG

## Prerequisiti

### Sistema Operativo
- Linux (testato su Ubuntu 22.04)
- Docker e Docker Compose installati

### Installazione Docker (se necessario)

```bash
# Aggiorna i pacchetti
sudo apt-get update

# Installa Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Installa Docker Compose
sudo apt-get install docker-compose-plugin

# Aggiungi utente al gruppo docker (opzionale)
sudo usermod -aG docker $USER
# Logout e login per applicare
```

## Installazione

### 1. Estrazione archivio

```bash
# Estrai l'archivio
tar -xzf workbench-g.tgz

# Entra nella directory
cd workbench-g
```

### 2. Configurazione hostname (IMPORTANTE)

Modifica il file `docker-compose.yml` e imposta l'hostname corretto del tuo server:

```yaml
services:
  tmux-web-manager:
    hostname: IL_TUO_HOSTNAME  # Esempio: "server1" o "production"
```

### 3. Configurazione file /etc/hosts personalizzato (opzionale per host remoti)

Se hai host remoti da configurare, crea `/tmp/custom-hosts`:

```bash
# Crea il file hosts personalizzato
sudo nano /tmp/custom-hosts
```

Contenuto esempio:
```
127.0.0.1 localhost
192.168.1.10 server-prod
192.168.1.20 server-dev
::1 ip6-localhost ip6-loopback
```

**Formato importante:** `IP_ADDRESS HOSTNAME` (non viceversa!)

### 4. Scelta modalità deployment

L'archivio include due modalità:

#### Modalità Local (DEFAULT - consigliata per singolo server)
- Già configurata di default
- Usa `docker-compose.yml` → `docker-compose.local.yml`
- Nessun proxy nginx
- Accesso diretto: `http://HOSTNAME:7777`
- **Templates e static montati come volumi per sviluppo rapido**

#### Modalità Remote (per deployment con proxy esterno)
- Usa nginx come reverse proxy
- Per switchare: `cp docker-compose.remote.yml docker-compose.yml`
- Accesso tramite nginx configurato esternamente

### 5. Build e avvio

```bash
# Build dell'immagine
docker compose build

# Avvio del container
docker compose up -d

# Verifica che sia attivo
docker ps | grep tmux
```

### 6. Verifica installazione

```bash
# Controlla i log
docker compose logs -f

# Dovresti vedere:
# [INIT] Running in LOCAL mode with direct connections
# * Running on all addresses (0.0.0.0)
# * Running on http://127.0.0.1:7777
```

## Primo Accesso

### Accesso Web

Apri il browser e vai su:
```
http://IL_TUO_HOSTNAME:7777
```

### Login

Usa le credenziali di un utente di sistema esistente:
- **Username:** nome utente Linux
- **Password:** password utente Linux

**Nota:** L'applicazione usa PAM per l'autenticazione, quindi funziona con qualsiasi utente del sistema.

## Configurazione Host Remoti

1. Dopo il login, clicca sul pulsante **"Gestisci host remoti"** (icona server nella topbar)
2. Clicca **"Aggiungi Host"**
3. Compila i campi:
   - **Nome:** Nome descrittivo (es: "Server Produzione")
   - **Hostname/IP:** Nome host o indirizzo IP
   - **Porta SSH:** Porta SSH (default 22)
   - **Username SSH:** Username per connessione SSH (lascia vuoto per usare quello corrente)
   - **Host abilitato:** Checkbox per abilitare/disabilitare

4. Salva

**Importante:** L'utente deve avere le chiavi SSH configurate per l'accesso passwordless agli host remoti.

## Configurazione Chiavi SSH

Per connettersi agli host remoti senza password:

```bash
# Genera chiave SSH (se non esiste)
ssh-keygen -t ed25519

# Copia la chiave sull'host remoto
ssh-copy-id username@remote-host

# Testa la connessione
ssh username@remote-host
```

## Utilizzo

### Creare una nuova sessione

1. Clicca sul pulsante **"+"** prima delle tab dell'host desiderato
2. Inserisci il nome della sessione nel dialog
3. La sessione viene creata e aperta automaticamente

### Aprire una sessione esistente

- Clicca sulla tab della sessione per aprirla

### Rinominare una sessione

1. Tasto destro sulla tab della sessione
2. Seleziona **"Rinomina sessione"**
3. Inserisci il nuovo nome nel dialog

### Eliminare una sessione

1. Tasto destro sulla tab della sessione
2. Seleziona **"Elimina sessione"**
3. Leggi attentamente l'avviso
4. Conferma l'eliminazione

**ATTENZIONE:** L'eliminazione è irreversibile e chiude tutti i processi nella sessione!

### Zoom caratteri terminale

- **Aumenta:** `Ctrl` + `+` o pulsante nella topbar
- **Diminuisci:** `Ctrl` + `-` o pulsante nella topbar
- **Reset:** `Ctrl` + `0` o pulsante nella topbar

## Sviluppo

### Modifica rapida senza rebuild

Grazie ai volumi montati in `docker-compose.yml`:

```yaml
volumes:
  - ./static:/app/static        # CSS, JS, immagini
  - ./templates:/app/templates  # HTML
```

Per modificare l'interfaccia:
1. Modifica i file in `static/` o `templates/`
2. Ricarica il browser (F5 o Ctrl+R)
3. **Nessun rebuild necessario!**

### Modifica che richiedono rebuild

Solo per modifiche a:
- `app.py` (logica backend)
- `Dockerfile`
- `requirements.txt`

Dopo le modifiche:
```bash
docker compose down
docker compose up -d --build
```

## Risoluzione Problemi

### Container non si avvia

```bash
# Controlla i log dettagliati
docker compose logs

# Verifica che la porta 7777 sia libera
sudo netstat -tlnp | grep 7777

# Riavvia il container
docker compose restart
```

### Sessioni remote non si caricano

1. Verifica connessione SSH dall'host:
```bash
docker exec tmux-web-manager ssh username@remote-host
```

2. Controlla il file `/tmp/custom-hosts`:
```bash
cat /tmp/custom-hosts
```

3. Verifica i log:
```bash
docker compose logs | grep SSH
```

### Login fallisce

- Verifica che l'utente esista nel sistema
- Verifica che i file `/etc/passwd` e `/etc/shadow` siano montati correttamente
- Controlla i log PAM nel container

### Menu contestuale non si chiude

- Verifica che il JavaScript `app.js` sia caricato correttamente
- Controlla la console del browser per errori
- Hard refresh: `Ctrl` + `Shift` + `R`

## Manutenzione

### Aggiornamento

```bash
# Ferma il container
docker compose down

# Aggiorna i file (sostituisci con nuova versione)
# ...

# Rebuild e riavvio
docker compose build
docker compose up -d
```

### Backup configurazioni host

Le configurazioni host sono salvate in:
```
./data/hosts/USERNAME_hosts.json
```

Backup consigliato:
```bash
# Backup
tar -czf workbench-data-backup-$(date +%Y%m%d).tgz data/

# Restore
tar -xzf workbench-data-backup-YYYYMMDD.tgz
```

### Pulizia

```bash
# Stop e rimozione container
docker compose down

# Rimozione completa (inclusa immagine)
docker compose down --rmi all

# Pulizia volumi (ATTENZIONE: cancella dati)
docker compose down -v
```

## Struttura Directory

```
workbench-g/
├── INSTALL.md                 # Questa guida
├── Dockerfile                 # Configurazione immagine Docker
├── docker-compose.yml         # Configurazione Docker Compose (local mode)
├── docker-compose.local.yml   # Modalità local
├── docker-compose.remote.yml  # Modalità remote
├── app.py                     # Applicazione Flask principale
├── requirements.txt           # Dipendenze Python
├── entrypoint.sh             # Script di avvio
├── nginx.conf                # Configurazione nginx (remote mode)
├── supervisord.conf          # Configurazione supervisor (remote mode)
├── static/                   # File statici
│   ├── css/
│   │   └── style.css        # Stili CSS
│   ├── js/
│   │   └── app.js           # JavaScript frontend
│   └── logo.png             # Logo InsightG
├── templates/                # Template HTML
│   ├── index.html           # Pagina principale
│   └── login.html           # Pagina login
└── data/                     # Dati persistenti
    └── hosts/                # Configurazioni host (JSON per utente)
```

## Porte Utilizzate

- **7777:** Porta principale applicazione web (configurabile in docker-compose.yml)
- **Dynamic:** Porte dinamiche per ttyd (gestite automaticamente dall'applicazione)

## Sicurezza

### Raccomandazioni

1. **Firewall:** Limita l'accesso alla porta 7777 solo da IP fidati
2. **SSH Keys:** Usa chiavi SSH invece di password per host remoti
3. **PAM:** L'autenticazione usa PAM - gli utenti devono esistere nel sistema
4. **HTTPS:** In produzione, usa nginx con SSL davanti all'applicazione
5. **Aggiornamenti:** Mantieni Docker e il sistema operativo aggiornati
6. **Backup:** Esegui backup regolari della directory `data/`

### Modalità Privilegiata

Il container richiede `privileged: true` per:
- Accesso a utenti di sistema (PAM)
- Gestione socket tmux per utente
- Demote dei processi all'utente corretto
- Accesso nsenter per host operations

## Note Tecniche

1. Il container monta `/home` in read-only per accesso alle chiavi SSH
2. I socket tmux sono in `/tmp` montato dal host
3. Le configurazioni host sono persistenti in `./data/hosts/`
4. Ogni utente ha la propria configurazione host separata
5. I template e static sono montati come volumi per sviluppo rapido
6. Il menu contestuale si chiude al click esterno o sul terminale

## Funzionalità Avanzate

### Creazione rapida sessioni

Ogni gruppo di tab (per host) ha un pulsante **"+"** che permette di:
- Creare rapidamente una nuova sessione
- Specificare il nome tramite dialog
- Aprire automaticamente la sessione appena creata

### Menu contestuale

Tasto destro su qualsiasi tab per:
- **Rinomina sessione:** Cambia il nome della sessione tmux
- **Elimina sessione:** Rimuove la sessione (con conferma importante)

### Gestione zoom

Controlla la dimensione dei caratteri del terminale:
- Pulsanti nella topbar
- Shortcut da tastiera (Ctrl +/-)
- Livello zoom visualizzato in percentuale

## Supporto

Per problemi o domande:
- Controlla i log: `docker compose logs -f`
- Verifica configurazione: `docker compose config`
- Debug container: `docker exec -it tmux-web-manager bash`
- Verifica permessi: assicurati che Docker abbia accesso ai mount necessari

## Crediti

**WorkBench.g** - Developed by InsightG
Versione 2.0 - Novembre 2025

---

Buon utilizzo! 🚀
