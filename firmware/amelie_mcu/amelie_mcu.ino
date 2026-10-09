/*
 * Amelie 2.0 — firmware del microcontrollore
 *
 * Il connettore Qwiic della UNO Q è cablato sull'I2C4 dello STM32U585, non del
 * processore Linux: l'anello di LED e il sensore di distanza li vede solo
 * questo microcontrollore. Linux ci parla attraverso il router (Bridge).
 *
 * ── SI COLLEGA TUTTO, SI ACCENDE, FUNZIONA ───────────────────────────────────
 *
 * È il requisito, e per rispettarlo qui non si usa la libreria Arduino_Modulino:
 * né per il sensore né per l'anello. Ogni transazione I2C è scritta qui sotto,
 * e ognuna o riesce o fallisce.
 *
 * ── PERCHE': UN PUNTATORE NULLO NASCOSTO NELLA LIBRERIA ──────────────────────
 *
 * Senza `Modulino.begin()`, `Arduino_Modulino` salta a un indirizzo casuale e
 * i suoi valori di ritorno non permettono di accorgersene. È dimostrabile
 * leggendo il binario:
 *
 *   · `ModulinoClass` non ha costruttore. Il suo unico campo, `HardwareI2C*
 *     _wire`, è scritto SOLO da `ModulinoClass::begin()`. L'oggetto globale
 *     `Modulino` finisce quindi in `.bss`, che l'avvio azzera: `_wire == nullptr`
 *     a ogni accensione, garantito, finché qualcuno non chiama
 *     `Modulino.begin()` (tutti gli esempi della libreria lo fanno come prima
 *     riga di `setup()`).
 *   · `Module::write()` — cioè ogni `show()` sull'anello — fa
 *     `Modulino._wire->beginTransmission(...)`, e `HardwareI2C` ha i metodi
 *     tutti virtuali. Nel binario compilato sono tre istruzioni:
 *
 *         ldr.w r0, [r8]     r0 = Modulino._wire, cioè 0
 *         ldr   r3, [r0, #N] la vtable, letta dall'indirizzo 0
 *         blx   r3           si salta lì
 *
 *   · Il variant compila con `CONFIG_ARM_MPU=n`: nessuna trappola sul puntatore
 *     nullo. Sullo STM32U585 l'indirizzo 0 è l'alias di boot della flash, quindi
 *     si legge il valore iniziale dello stack pointer e lo si usa come vtable.
 *     Si salta a un indirizzo che cambia di istante in istante: a volte torna, e
 *     prima o poi è un hard fault. Il gestore fatale di Zephyr ferma tutto, il
 *     thread del Bridge compreso: da Linux vanno in timeout TUTTI i metodi,
 *     `versione()` compreso, e ci si riprende solo togliendo corrente.
 *
 * Il sintomo somiglia a quello di un altro difetto, che pure esiste: il driver
 * del VL53L4CD, in `platform.cpp`, ritenta i trasferimenti I2C con un
 * `do {...} while (status)` senza uscita. Anche per questo il sensore è scritto
 * qui sotto a mano, con ogni attesa limitata.
 *
 * Due dettagli della libreria nascondono il guasto invece di segnalarlo:
 *
 *   · `Module::begin()` con un indirizzo esplicito ritorna `true` SENZA toccare
 *     il bus. Quindi `moduli()` risponderebbe «anello presente» a un anello mai
 *     scritto una sola volta.
 *   · `Module::write()` ritorna `true` sempre, comunque vada.
 *
 * Per questo qui sotto l'anello si scrive a mano e `c_anello` diventa vero solo
 * dopo una scrittura ANDATA A BUON FINE: una cosa presente è una cosa che ha
 * risposto, non una che non ha protestato.
 *
 * ── DUE MODULI ───────────────────────────────────────────────────────────────
 *
 * L'anello e il sensore. L'anello è il Modulino Pixels nella torre: illumina
 * l'etichetta attraverso la finestra traslucida, e sale a bianco per la durata
 * della raffica. Il sensore è il Modulino Distance sotto il disco su cui sta la
 * bottiglia.
 *
 * ── DUE VINCOLI CHE FANNO FALLIRE IN SILENZIO ────────────────────────────────
 *
 * 1. Chiamare Bridge.call() o Monitor.print() DENTRO un gestore registrato con
 *    provide() manda in stallo il canale. È documentato. Per questo i gestori
 *    qui sotto non chiamano mai il ponte e non stampano: scrivono in una
 *    variabile che applica il loop(), o al più leggono il bus sotto
 *    `lucchetto_bus`.
 *
 * 2. Un .ino non è un .cpp: Arduino gli genera i prototipi e li infila subito
 *    PRIMA della prima definizione di funzione. Un tipo dichiarato dopo quel
 *    punto non esiste ancora quando il prototipo lo nomina, e si prende un
 *    "has not been declared" su una riga che sta sotto la dichiarazione e
 *    sembra corretta. Per questo qui tutti i tipi e le variabili stanno in cima.
 */

#include <Arduino_RouterBridge.h>
#include <Wire.h>
#include <zephyr/device.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/kernel.h>

/* ─── tutto ciò che si dichiara, prima di qualsiasi funzione (vincolo 2) ────── */

/* Versione del PROTOCOLLO fra questo firmware e Linux, non del firmware: deve
 * valere quanto PROTOCOLLO_ATTESO in amelie.bridge. Si alza quando cambia il
 * SIGNIFICATO di qualcosa, per esempio dei bit di moduli(), o quando Linux
 * comincia a chiedere un metodo che le versioni prima non hanno, come
 * `set_luce`: non a ogni modifica del codice. */
static const int PROTOCOLLO = 3;

static const uint8_t IND_ANELLO   = 0x36;   /* indirizzo hardware, non 0x6C */
static const uint8_t IND_TOF      = 0x29;   /* VL53L4CD, fisso */
static const uint8_t N_LED = 8;

/* Sotto questa distanza c'e' qualcosa sul piatto. Dieci centimetri: la
 * decisione vera la prende Linux con la sua isteresi, questa serve solo alla
 * notifica del cambiamento. */
static const int VICINO_MM = 100;

/* Registri del VL53L4CD che servono qui. Sono a 16 bit. */
static const uint16_t R_IDENTITA        = 0x010F;   /* deve valere 0xEBAA */
static const uint16_t R_STATO_FIRMWARE  = 0x00E5;   /* 0x03 = avviato */
static const uint16_t R_MUX_GPIO        = 0x0030;
static const uint16_t R_STATO_GPIO      = 0x0031;
static const uint16_t R_VHV_LOOP_BOUND  = 0x0008;
static const uint16_t R_RANGE_A         = 0x005E;
static const uint16_t R_RANGE_B         = 0x0061;
static const uint16_t R_INTERMISURA     = 0x006C;
static const uint16_t R_AZZERA_INT      = 0x0086;
static const uint16_t R_AVVIO           = 0x0087;
static const uint16_t R_STATO_MISURA    = 0x0089;
static const uint16_t R_SPAD            = 0x008C;
static const uint16_t R_DISTANZA        = 0x0096;

/* La configurazione di fabbrica, registri da 0x2D a 0x87. Copiata pari pari
 * dalla libreria: sono valori del costruttore, non c'è niente da capire e
 * niente da migliorare. */
static const uint8_t CONFIG_TOF[] = {
  0x12, 0x00, 0x00, 0x11, 0x02, 0x00, 0x02, 0x08, 0x00, 0x08, 0x10, 0x01, 0x01,
  0x00, 0x00, 0x00, 0x00, 0xff, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x20,
  0x0b, 0x00, 0x00, 0x02, 0x14, 0x21, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x00,
  0xc8, 0x00, 0x00, 0x38, 0xff, 0x01, 0x00, 0x08, 0x00, 0x00, 0x01, 0xcc, 0x07,
  0x01, 0xf1, 0x05, 0x00, 0xa0, 0x00, 0x80, 0x08, 0x38, 0x00, 0x00, 0x00, 0x00,
  0x0f, 0x89, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x07, 0x05, 0x06,
  0x06, 0x00, 0x00, 0x02, 0xc7, 0xff, 0x9b, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00
};

/* Quanto si aspetta, all'accensione, che i moduli si presentino. Il
 * microcontrollore parte in millisecondi, il sensore ha bisogno di più tempo, e
 * qui non c'è fretta: Linux ci mette comunque una cinquantina di secondi ad
 * arrivare alla sua schermata. Scaduta l'attesa si va avanti lo stesso — un
 * dispositivo che racconta senza vedere la bottiglia è meglio di uno fermo. */
static const uint32_t ATTESA_MODULI_MS = 10000;
static const uint32_t PASSO_RICERCA_MS = 200;

/* La luce di Amelie: i LED pari bianchi, i dispari gialli, al massimo. Sono
 * gli stessi due colori che manda Linux (`LUCE` in amelie.bridge); qui servono
 * al respiro dell'accensione, che arriva prima di Linux. */
static const uint8_t BIANCO_R = 255, BIANCO_G = 255, BIANCO_B = 255;
static const uint8_t GIALLO_R = 255, GIALLO_G = 200, GIALLO_B = 0;

/* Il respiro dell'accensione: dà segno di vita mentre Linux si avvia. Il
 * microcontrollore è pronto in millisecondi, lo schermo ci mette una
 * cinquantina di secondi, e in mezzo l'anello sarebbe spento — un dispositivo
 * appena acceso che non fa niente sembra rotto.
 *
 * Si spegne da solo al primo comando da Linux: da lì il colore lo decide la
 * macchina a stati, e la luce resta fissa. */
/* La luminosità resta ferma e si modula il colore: vedi `respira()`. Al
 * massimo, come la luce fissa che gli succede: il colmo del respiro e la luce
 * di sempre hanno la stessa intensità. */
static const uint8_t  RESPIRO_LUM = 31;
static const uint8_t  RESPIRO_FONDO = 26;   /* il minimo, su 255: mai spento */
static const uint32_t RESPIRO_MS = 25;      /* 40 aggiornamenti al secondo */
static const uint8_t  RESPIRO_PASSO = 2;    /* 256/2 x 25 ms = 3,2 s a ciclo */

static bool c_anello = false, c_tof = false;
static bool ricerca_finita = false;
static uint32_t ultima_ricerca = 0;

/* Dove si e' fermato l'avvio del sensore. 0 = riuscito, -1 = mai tentato,
 * altrimenti il numero del passo che non e' andato. Senza questo, un sensore che
 * non parte dice solo "non ci sono", e per capire perche' bisognerebbe
 * ricaricare il firmware con delle stampe. */
static int passo_tof = -1;

/* Il respiro gira su un filo suo finche' il ponte non e' pronto: vedi
 * `filo_respiro()` per il perche'. */
static K_THREAD_STACK_DEFINE(pila_respiro, 1024);
static struct k_thread dati_respiro;
static volatile bool anima = false;

static bool respiro = true;
static uint8_t fase = 0;
static uint32_t ultimo_respiro = 0;

/* Stato richiesto da Linux. I gestori scrivono qui e basta (vincolo 1). */
/* Due colori: i LED pari prendono il primo, i dispari il secondo. Con un colore
 * solo i due sono uguali. */
struct StatoLed {
  uint8_t r = 0, g = 0, b = 0;
  uint8_t r2 = 0, g2 = 0, b2 = 0;
  uint8_t lum = 0;
  bool da_applicare = false;
};
static StatoLed rich_anello;

/* Presenza della bottiglia. L'isteresi vera sta su Linux, in amelie.bridge:
 * qui si tiene solo l'ultima misura valida e si notifica il cambiamento. */
static int ultima_mm = -1;
static bool presente = false;
static uint32_t ultimo_invio = 0;

/* ─── il bus: transazioni che finiscono sempre, e non si accavallano ──────── */

/* UN SOLO PADRONE PER VOLTA SUL BUS.
 *
 * I gestori registrati con `Bridge.provide()` NON girano nel `loop()`: la
 * libreria crea un thread suo, chiamato "bridge", ed e' li' che vengono
 * chiamati. Un gestore che scrive soltanto in una variabile non tocca il bus;
 * ma `scansiona()` e `registro_tof()` lo LEGGONO, e allora due thread ci
 * parlano insieme.
 *
 * Senza lucchetto il risultato si vede nei dati: le letture tornano con i byte
 * di un ALTRO registro. 2313 e' 0x0909, cioe' il byte di stato ripetuto; 4354
 * e' 0x1102, un byte del registro della polarita' seguito da un altro. Non sono
 * misure sbagliate: sono risposte di una transazione arrivate a chi ne aveva
 * chiesta un'altra.
 *
 * Da qui in giu' ogni transazione prende questo lucchetto. Il mutex di Zephyr
 * e' ricorsivo per chi lo possiede gia', quindi annidarli e' sicuro. */
static K_MUTEX_DEFINE(lucchetto_bus);


/* Sblocca il bus, se qualcuno lo sta tenendo fermo.
 *
 * ── PERCHE' SERVE ────────────────────────────────────────────────────────────
 *
 * L'I2C ha un modo di rompersi che nessun timeout risolve: se un dispositivo
 * viene resettato a meta' di un byte, resta convinto di stare trasmettendo e
 * tiene SDA a zero. Il bus e' occupato per sempre, e ogni transazione - anche
 * verso un ALTRO dispositivo - non parte nemmeno.
 *
 * Il sintomo inganna: dopo un blocco del sensore non si accende PIU' NEMMENO
 * l'anello. Non e' rotto l'anello, e' il bus. Il microcontrollore si ferma
 * sulla primissima transazione, prima ancora di poter far respirare la luce, e
 * da Linux il dispositivo sembra senza firmware. Ricaricare il firmware non
 * basta: resetta il microcontrollore, non il sensore che tiene giu' la linea.
 * Senza la manovra qui sotto serve togliere corrente a tutto.
 *
 * `i2c_recover_bus()` fa la manovra prevista dallo standard: batte SCL finche'
 * lo schiavo finisce il byte che crede di star mandando e rilascia SDA, poi
 * manda uno STOP. E' la sola via d'uscita che non richieda una mano umana.
 *
 * Si fa PRIMA di qualunque altra cosa, a ogni accensione: costa un millisecondo
 * quando non serve, e quando serve e' la differenza fra un dispositivo che si
 * riprende da solo e uno da riavviare staccando la spina. */
static void libera_il_bus() {
  const struct device *bus = DEVICE_DT_GET(DT_NODELABEL(i2c4));
  if (device_is_ready(bus)) {
    i2c_recover_bus(bus);
  }
}

static bool risponde(uint8_t indirizzo) {
  k_mutex_lock(&lucchetto_bus, K_FOREVER);
  Wire1.beginTransmission(indirizzo);
  bool ok = Wire1.endTransmission() == 0;
  k_mutex_unlock(&lucchetto_bus);
  return ok;
}

/* Lettura e scrittura di registri a 16 bit. Ognuna riesce o fallisce: è tutta
 * la differenza con la libreria, ed è il motivo per cui questo codice esiste. */
static bool tof_leggi(uint16_t reg, uint8_t *fuori, uint8_t quanti) {
  k_mutex_lock(&lucchetto_bus, K_FOREVER);
  bool ok = false;
  Wire1.beginTransmission(IND_TOF);
  Wire1.write((uint8_t)(reg >> 8));
  Wire1.write((uint8_t)(reg & 0xFF));
  if (Wire1.endTransmission() == 0 &&
      (int)Wire1.requestFrom((int)IND_TOF, (int)quanti) == (int)quanti) {
    for (uint8_t i = 0; i < quanti; i++) fuori[i] = (uint8_t)Wire1.read();
    ok = true;
  }
  k_mutex_unlock(&lucchetto_bus);
  return ok;
}

static bool tof_leggi8(uint16_t reg, uint8_t *v) {
  return tof_leggi(reg, v, 1);
}

static bool tof_leggi16(uint16_t reg, uint16_t *v) {
  uint8_t b[2];
  if (!tof_leggi(reg, b, 2)) return false;
  *v = ((uint16_t)b[0] << 8) | b[1];
  return true;
}

static bool tof_scrivi(uint16_t reg, const uint8_t *dati, uint8_t quanti) {
  k_mutex_lock(&lucchetto_bus, K_FOREVER);
  Wire1.beginTransmission(IND_TOF);
  Wire1.write((uint8_t)(reg >> 8));
  Wire1.write((uint8_t)(reg & 0xFF));
  for (uint8_t i = 0; i < quanti; i++) Wire1.write(dati[i]);
  bool ok = Wire1.endTransmission() == 0;
  k_mutex_unlock(&lucchetto_bus);
  return ok;
}

static bool tof_scrivi8(uint16_t reg, uint8_t v) {
  return tof_scrivi(reg, &v, 1);
}

static bool tof_scrivi16(uint16_t reg, uint16_t v) {
  uint8_t b[2] = { (uint8_t)(v >> 8), (uint8_t)(v & 0xFF) };
  return tof_scrivi(reg, b, 2);
}

static bool tof_scrivi32(uint16_t reg, uint32_t v) {
  uint8_t b[4] = { (uint8_t)(v >> 24), (uint8_t)(v >> 16),
                   (uint8_t)(v >> 8),  (uint8_t)(v & 0xFF) };
  return tof_scrivi(reg, b, 4);
}

/* C'è una misura pronta? Si guarda la polarità dell'interrupt e poi lo stato,
 * come fa la libreria. */
static bool tof_misura_pronta(bool *pronta) {
  uint8_t t;
  k_mutex_lock(&lucchetto_bus, K_FOREVER);
  bool ok = tof_leggi8(R_MUX_GPIO, &t);
  uint8_t polarita = ((t & 0x10) >> 4) == 1 ? 0 : 1;
  ok = ok && tof_leggi8(R_STATO_GPIO, &t);
  k_mutex_unlock(&lucchetto_bus);
  if (!ok) return false;
  *pronta = ((t & 0x01) == polarita);
  return true;
}

/* La sequenza d'avvio del costruttore, con ogni attesa limitata.
 * Restituisce false invece di non tornare: è tutto il punto. */
static bool tof_avvia() {
  uint8_t t;
  uint16_t v16;
  passo_tof = 1;

  /* 1. Il chip ha finito di avviarsi? Fino a 200 ms, non "per sempre". */
  for (uint16_t i = 0; ; i++) {
    if (!tof_leggi8(R_STATO_FIRMWARE, &t)) return false;
    if (t == 0x03) break;
    if (i >= 200) { passo_tof = 2; return false; }
    delay(1);
  }

  /* 2. La configurazione di fabbrica, un registro per volta. */
  passo_tof = 3;
  for (uint8_t i = 0; i < sizeof(CONFIG_TOF); i++) {
    if (!tof_scrivi8((uint16_t)(0x2D + i), CONFIG_TOF[i])) return false;
  }

  /* 3. La calibrazione VHV: si avvia, si aspetta la prima misura, si azzera. */
  passo_tof = 4;
  if (!tof_scrivi8(R_AVVIO, 0x40)) return false;
  for (uint16_t i = 0; ; i++) {
    bool pronta = false;
    if (!tof_misura_pronta(&pronta)) return false;
    if (pronta) break;
    if (i >= 1000) return false;
    delay(1);
  }
  if (!tof_scrivi8(R_AZZERA_INT, 0x01)) return false;
  if (!tof_scrivi8(R_AVVIO, 0x00)) return false;
  if (!tof_scrivi8(R_VHV_LOOP_BOUND, 0x09)) return false;
  if (!tof_scrivi8(0x000B, 0x00)) return false;
  if (!tof_scrivi16(0x0024, 0x0500)) return false;

  /* 4. Tempo di misura: 50 ms per misura, in continua. Il conto e' quello del
   *    costruttore, ricopiato passo per passo: il periodo di macro si ricava
   *    dalla frequenza dell'oscillatore, e i due registri di intervallo vogliono
   *    un valore in virgola mobile ridotto a mantissa piu' esponente. Non c'e'
   *    niente da capire e niente da migliorare — c'e' solo da non sbagliarlo. */
  passo_tof = 5;
  if (!tof_leggi16(0x0006, &v16)) return false;      /* frequenza oscillatore */
  if (v16 == 0) return false;
  {
    uint32_t macro = (uint32_t)(((uint32_t)2304 *
                                 ((uint32_t)0x40000000 / (uint32_t)v16)) >> 6);
    /* Misura continua: nessuna pausa fra una e l'altra. */
    if (!tof_scrivi32(R_INTERMISURA, 0)) return false;
    uint32_t budget = 50U * 1000U - 2500U;
    budget <<= 12;

    for (uint8_t quale = 0; quale < 2; quale++) {
      uint32_t tmp = macro * (quale == 0 ? 16U : 12U);
      uint32_t basso = ((budget + ((tmp >> 6) >> 1)) / (tmp >> 6)) - 1U;
      uint16_t alto = 0;
      while ((basso & 0xFFFFFF00U) > 0U) { basso >>= 1; alto++; }
      uint16_t reg = (uint16_t)((alto << 8) + (uint16_t)(basso & 0xFFU));
      if (!tof_scrivi16(quale == 0 ? R_RANGE_A : R_RANGE_B, reg)) return false;
    }
  }

  /* 5. Via alla misura continua, e si aspetta la prima per lasciare il sensore
   *    in uno stato pulito. */
  passo_tof = 6;
  if (!tof_scrivi8(R_AVVIO, 0x21)) return false;
  for (uint16_t i = 0; ; i++) {
    bool pronta = false;
    if (!tof_misura_pronta(&pronta)) return false;
    if (pronta) break;
    if (i >= 1000) return false;
    delay(1);
  }
  if (!tof_scrivi8(R_AZZERA_INT, 0x01)) return false;
  passo_tof = 0;                       /* 0 = tutto riuscito */
  return true;
}

/* L'ultima misura, se ce n'è una nuova. -1 quando non c'è niente da leggere o
 * quando il sensore dichiara la misura non valida — che con il piatto vuoto è
 * la risposta normale, non un guasto. */
static int tof_misura() {
  bool pronta = false;
  if (!tof_misura_pronta(&pronta)) return -2;   /* il sensore non risponde */
  if (!pronta) return -3;                       /* nessuna misura nuova */

  /* L'interrupt si azzera PRIMA di leggere il risultato. E' l'ordine che usa la
   * libreria Modulino, che funziona; leggendo prima e azzerando dopo si legge
   * un risultato che il sensore non ha ancora finito di preparare. */
  /* Le quattro transazioni di una misura si tengono INSIEME: fra lo stato e la
   * distanza non deve infilarsi la lettura di qualcun altro, o si mettono
   * insieme pezzi di due misure diverse. */
  uint8_t stato;
  uint16_t spad, mm;
  k_mutex_lock(&lucchetto_bus, K_FOREVER);
  tof_scrivi8(R_AZZERA_INT, 0x01);
  bool ok = tof_leggi8(R_STATO_MISURA, &stato)
         && tof_leggi16(R_SPAD, &spad)
         && tof_leggi16(R_DISTANZA, &mm);
  k_mutex_unlock(&lucchetto_bus);
  if (!ok) return -2;

  /* Lo stato 9 e' "misura buona": la libreria rimappa i codici, e 9 e' quello
   * che diventa "valida". */
  if ((stato & 0x1F) != 0x09 || spad == 0) return -1;

  /* E ZERO NON E' UNA DISTANZA: e' il modo in cui questo sensore dice "non c'e'
   * niente davanti".
   *
   * Lo dicono i dati, raccolti al banco con la mano che entra ed esce dal cono:
   *
   *     niente davanti    distanza 0     SPAD 52368, sempre lo stesso
   *     mano davanti      25..176 mm     SPAD 392..51528, variabili
   *
   * Lo stato resta 9 in tutti e due i casi e gli SPAD non sono mai zero, quindi
   * nessuno dei due controlli qui sopra se ne accorge. E fisicamente uno zero
   * non puo' essere vero: il VL53L4CD non misura sotto il centimetro, e un
   * oggetto appoggiato sulla finestrella darebbe qualche millimetro e uno stato
   * di errore, non zero con stato buono.
   *
   * Prenderlo per buono ha una conseguenza che sembra un guasto diverso: zero
   * e' sotto la soglia del vicino, quindi per Linux c'e' SEMPRE una bottiglia.
   * Non la vede mai arrivare - manca il fronte di salita - e dopo il primo
   * racconto resta in attesa che venga tolta, cosa che non succede mai. Un
   * solo numero mal interpretato, due sintomi. */
  if (mm == 0) return -1;

  return (int)mm;
}

/* ─── gestori esposti a Linux ──────────────────────────────────────────────── */

bool set_anello(int r, int g, int b, int lum) {
  rich_anello = {(uint8_t)r, (uint8_t)g, (uint8_t)b,
                 (uint8_t)r, (uint8_t)g, (uint8_t)b, (uint8_t)lum, true};
  respiro = false;          /* Linux ha preso il comando: basta respirare */
  return true;
}

/* Due colori alternati, ciascuno in un intero 0xRRGGBB: i LED pari prendono il
 * primo, i dispari il secondo. Tre parametri invece di sette: il ponte scambia
 * interi, e un colore sta tutto in uno. */
bool set_luce(int pari, int dispari, int lum) {
  rich_anello = {(uint8_t)(pari >> 16), (uint8_t)(pari >> 8), (uint8_t)pari,
                 (uint8_t)(dispari >> 16), (uint8_t)(dispari >> 8),
                 (uint8_t)dispari, (uint8_t)lum, true};
  respiro = false;
  return true;
}

int distanza() { return ultima_mm; }

int versione() { return PROTOCOLLO; }

/* Dove si e' fermato l'avvio del sensore: 0 riuscito, -1 mai tentato, 2 il chip
 * non ha finito di avviarsi, 3 la configurazione, 4 la calibrazione, 5 i tempi
 * di misura, 6 l'avvio della misura continua. */
int stato_tof() { return passo_tof; }

/* I registri del sensore, grezzi, uno per chiamata.
 *
 * `distanza()` dice quanti millimetri; quando quel numero non torna - zero
 * fisso, per esempio - non dice PERCHE'. Questo apre il sensore e mostra cosa
 * risponde davvero, senza ricaricare il firmware con delle stampe dentro.
 *
 *   0 misura pronta (0/1)      3 distanza in mm
 *   1 stato della misura       4 registro della polarita' dell'interrupt
 *   2 numero di SPAD attivi    5 stato del piedino di interrupt
 *
 * -1 vuol dire che il sensore non ha risposto alla lettura. */
int registro_tof(int quale) {
  if (!c_tof) return -2;
  uint8_t b8; uint16_t b16;
  switch (quale) {
    case 0: { bool p = false; return tof_misura_pronta(&p) ? (p ? 1 : 0) : -1; }
    case 1: return tof_leggi8(R_STATO_MISURA, &b8) ? (int)b8 : -1;
    case 2: return tof_leggi16(R_SPAD, &b16) ? (int)b16 : -1;
    case 3: return tof_leggi16(R_DISTANZA, &b16) ? (int)b16 : -1;
    case 4: return tof_leggi8(R_MUX_GPIO, &b8) ? (int)b8 : -1;
    case 5: return tof_leggi8(R_STATO_GPIO, &b8) ? (int)b8 : -1;
  }
  return -3;
}

/* Quali moduli si vedono, come somma di bit: 1 anello, 2 sensore. */
int moduli() {
  return (c_anello ? 1 : 0) | (c_tof ? 2 : 0);
}

/* CHE COSA C'E' DAVVERO SUL BUS, indirizzo per indirizzo.
 *
 * `moduli()` risponde a "vedi i due che mi aspetto?", e quando dice di no non
 * dice PERCHE'. Questo risponde alla domanda che viene dopo, ed e' quella che
 * conta con i cavetti in mano: cosa c'e' attaccato? Un modulo scambiato, uno a
 * un indirizzo inatteso, o proprio niente sono tre guasti diversi che da fuori
 * si somigliano tutti - e distinguerli a occhio, guardando due schede blu quasi
 * identiche, e' il modo piu' rapido di sbagliarsi.
 *
 * Un blocco di 32 indirizzi per chiamata, perche' il ponte scambia interi: con
 * quattro chiamate si copre tutto lo spazio a 7 bit. */
int scansiona(int blocco) {
  if (blocco < 0 || blocco > 3) return 0;
  uint32_t trovati = 0;
  for (uint8_t i = 0; i < 32; i++) {
    uint8_t indirizzo = (uint8_t)(blocco * 32 + i);
    if (indirizzo < 0x08 || indirizzo > 0x77) continue;   /* riservati */
    if (risponde(indirizzo)) trovati |= ((uint32_t)1 << i);
  }
  return (int)trovati;
}

/* ─── ciclo ────────────────────────────────────────────────────────────────── */

/* Gli otto LED, scritti a mano. Il formato è quello del modulo: quattro byte per
 * LED, nell'ordine 0xE0|luminosità, blu, verde, rosso — la luminosità è a
 * cinque bit, cioè 0-31. I LED pari prendono il primo colore, i dispari il
 * secondo.
 *
 * Restituisce se il trasferimento è riuscito. `Module::write()` della libreria
 * ritorna `true` sempre, e con quel `true` il dispositivo direbbe di vedere un
 * anello che non ha mai acceso. */
static bool anello_grezzo(uint8_t r, uint8_t g, uint8_t b,
                          uint8_t r2, uint8_t g2, uint8_t b2, uint8_t l5) {
  if (l5 > 31) l5 = 31;
  k_mutex_lock(&lucchetto_bus, K_FOREVER);
  Wire1.beginTransmission(IND_ANELLO);
  for (uint8_t i = 0; i < N_LED; i++) {
    bool dispari = i % 2;
    Wire1.write((uint8_t)(0xE0 | l5));
    Wire1.write(dispari ? b2 : b);
    Wire1.write(dispari ? g2 : g);
    Wire1.write(dispari ? r2 : r);
  }
  bool ok = Wire1.endTransmission() == 0;
  k_mutex_unlock(&lucchetto_bus);
  return ok;
}

/* Tutto spento: serve anche a sapere se l'anello c'è, scrivendogli davvero. */
static bool anello_spento() {
  return anello_grezzo(0, 0, 0, 0, 0, 0, 0);
}

/* Con la luminosità in centesimi, come la manda Linux. */
static void applica(StatoLed &s) {
  if (!s.da_applicare) return;
  uint8_t l5 = (uint8_t)((uint16_t)s.lum * 31U / 100U);
  if (anello_grezzo(s.r, s.g, s.b, s.r2, s.g2, s.b2, l5)) s.da_applicare = false;
}

/* Un respiro, e si modula il COLORE, non la luminosità.
 *
 * Il registro di luminosità del modulo è a CINQUE BIT: da 0 a 31. Facendo
 * respirare quello, fra il minimo e il massimo di un'attesa discreta — 3 e 26
 * su cento — restano **nove gradini in tutto**, e a venti aggiornamenti al
 * secondo si vedono uno per uno: la luce non respira, scatta.
 *
 * I canali di colore sono invece a otto bit. Tenendo la luminosità ferma e
 * scalando i due colori su 0-255 si hanno 256 passi al posto di nove, e il
 * respiro torna continuo. I colori non cambiano: i canali scendono e salgono
 * insieme e in proporzione, quindi restano lo stesso bianco e lo stesso
 * giallo, più o meno accesi.
 *
 * La curva è quadratica: indugia in basso e sale piena verso il colmo, che è
 * come respira una cosa viva. Tutto in interi — qui non serve virgola mobile. */
static void respira() {
  uint8_t x = (fase < 128) ? (uint8_t)(fase * 2) : (uint8_t)((255 - fase) * 2);
  uint16_t curva = ((uint16_t)x * x) >> 8;                     /* 0..254 */
  /* Un fondo che non si spegne mai del tutto: a zero l'anello sparirebbe, e
   * "sparito" e "guasto" a colpo d'occhio sono la stessa cosa. */
  uint16_t q = RESPIRO_FONDO + (uint16_t)(((uint32_t)curva *
                                           (255 - RESPIRO_FONDO)) / 254);
  anello_grezzo((uint8_t)((BIANCO_R * q) / 255U), (uint8_t)((BIANCO_G * q) / 255U),
                (uint8_t)((BIANCO_B * q) / 255U), (uint8_t)((GIALLO_R * q) / 255U),
                (uint8_t)((GIALLO_G * q) / 255U), (uint8_t)((GIALLO_B * q) / 255U),
                RESPIRO_LUM);
  fase += RESPIRO_PASSO;
}

/* Il respiro, su un filo a parte, finche' Linux non e' in piedi.
 *
 * ── PERCHE' UN FILO ─────────────────────────────────────────────────────────
 *
 * `Bridge.begin()` contiene, nella sua libreria:
 *
 *     serial_ptr->begin(baud);
 *     while (!*serial_ptr) { k_yield(); }
 *
 * cioe' ASPETTA CHE LINUX APRA LA SERIALE, che succede quando parte
 * `arduino-router`: una quarantina di secondi dopo l'accensione. Finche' quella
 * riga non passa, `setup()` non finisce e `loop()` non gira - e senza un filo a
 * parte l'anello resterebbe spento fino a tre o quattro secondi prima dello
 * schermo, mentre la matrice di LED della board mostra il logo Arduino da
 * subito.
 *
 * Il microcontrollore, invece, e' pronto in millisecondi. Qui l'anello si
 * accende PRIMA di chiamare il ponte, e lo fa respirare un filo separato mentre
 * quell'attesa scorre. Quando il ponte e' pronto il filo esce, e il respiro
 * prosegue dal `loop()`: mai due padroni sullo stesso bus insieme.
 */
static void filo_respiro(void *a, void *b, void *c) {
  ARG_UNUSED(a); ARG_UNUSED(b); ARG_UNUSED(c);
  while (anima) {
    if (c_anello) respira();
    k_msleep(RESPIRO_MS);
  }
}

void setup() {
  /* PRIMA la luce, poi il ponte. In quest'ordine e non nell'altro. */
  libera_il_bus();
  Wire1.begin();
  /* 100 kHz: e' cio' che imposta `ModulinoClass::begin()`, e i Modulino sono
   * tarati su quello. Senza la libreria, il clock va impostato a mano. */
  Wire1.setClock(100000);

  /* L'anello subito: e' l'unica cosa che dice "sono vivo" nei quaranta secondi
   * in cui lo schermo e' ancora nero. Presente = ha risposto a una scrittura,
   * non = non ha protestato. */
  for (uint8_t i = 0; i < 10 && !c_anello; i++) {
    if (risponde(IND_ANELLO)) c_anello = anello_spento();
    if (!c_anello) k_msleep(20);
  }

  anima = true;
  k_thread_create(&dati_respiro, pila_respiro, K_THREAD_STACK_SIZEOF(pila_respiro),
                  filo_respiro, NULL, NULL, NULL, 7, 0, K_NO_WAIT);

  /* Qui si aspetta Linux, e puo' volerci mezzo minuto. L'anello intanto
   * respira. */
  Bridge.begin();

  /* Il ponte c'e': il filo ha finito e si ritira, prima che il `loop()`
   * cominci a scrivere sullo stesso bus. */
  anima = false;
  k_thread_join(&dati_respiro, K_MSEC(500));

  /* I metodi si dichiarano appena il ponte e' pronto: ogni transazione I2C e'
   * limitata, quindi un modulo che non risponde non puo' impedire a `setup()`
   * di arrivare fin qui, e comunque `Bridge.begin()` non ritorna finche' Linux
   * non c'e'. */
  Bridge.provide("set_anello", set_anello);
  Bridge.provide("set_luce", set_luce);
  Bridge.provide("distanza", distanza);
  Bridge.provide("moduli", moduli);
  Bridge.provide("versione", versione);
  Bridge.provide("scansiona", scansiona);
  Bridge.provide("stato_tof", stato_tof);
  Bridge.provide("registro_tof", registro_tof);
}

void loop() {
  uint32_t ora_ms = millis();

  /* ── la ricerca, solo nella finestra d'accensione ─────────────────────── */
  if (!ricerca_finita && ora_ms - ultima_ricerca >= PASSO_RICERCA_MS) {
    ultima_ricerca = ora_ms;
    /* Presente = ha risposto a una scrittura vera, non = non ha protestato. */
    if (!c_anello && risponde(IND_ANELLO)) c_anello = anello_spento();
    if (!c_tof && risponde(IND_TOF)) {
      uint16_t id = 0;
      if (tof_leggi16(R_IDENTITA, &id) && id == 0xEBAA) c_tof = tof_avvia();
    }
    if ((c_anello && c_tof) || ora_ms > ATTESA_MODULI_MS) ricerca_finita = true;
  }

  /* ── il respiro, finché Linux non prende il comando ───────────────────── */
  if (respiro && c_anello && ora_ms - ultimo_respiro >= RESPIRO_MS) {
    ultimo_respiro = ora_ms;
    respira();
  }

  /* ── la misura ────────────────────────────────────────────────────────── */
  if (c_tof) {
    int m = tof_misura();
    if (m >= 0) ultima_mm = m;
    else if (m == -1) ultima_mm = -1;        /* misura non valida: piatto vuoto */
    else if (m == -2) { c_tof = false; ultima_mm = -1; }   /* sensore sparito */
    /* -3: nessuna misura nuova, si tiene l'ultima */
  }

  /* Notifica solo i cambiamenti, e non più di dieci volte al secondo: il
   * trasporto è una seriale a 115200 baud condivisa con tutto il resto. */
  bool ora = (ultima_mm >= 0 && ultima_mm < VICINO_MM);
  if (ora != presente && (ora_ms - ultimo_invio) > 100) {
    presente = ora;
    ultimo_invio = ora_ms;
    Bridge.notify("bottiglia", presente, ultima_mm);
  }

  if (c_anello && !respiro) applica(rich_anello);

  delay(20);
}
