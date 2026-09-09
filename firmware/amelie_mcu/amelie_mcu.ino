/*
 * Amelie 2.0 — firmware del microcontrollore
 *
 * Il connettore Qwiic della UNO Q è cablato sull'I2C4 dello STM32U585, non del
 * processore Linux: l'anello di LED e il sensore di distanza li vede solo
 * questo microcontrollore. Linux ci parla attraverso il router (Bridge).
 *
 * Questa divisione permette l'attesa a consumo bassissimo: qui si fa la guardia
 * sul sensore, e Linux viene svegliato solo quando arriva una bottiglia.
 *
 * ── DUE MODULI, NON TRE ──────────────────────────────────────────────────────
 *
 * C'era un secondo Modulino Pixels che faceva da flash per la camera. È stato
 * tolto, e con lui è sparita la parte più fragile del montaggio: due Pixels
 * nascono entrambi a 0x36, quindi il secondo andava riprogrammato una volta per
 * sempre con uno sketch a parte, e da fuori i due moduli sono identici — chi
 * scambiava i cavetti si ritrovava il flash sotto la bottiglia.
 *
 * L'etichetta si illumina lo stesso: l'anello sale a bianco per la frazione di
 * secondo dello scatto e poi torna al suo colore. E il grosso del segnale non
 * l'hanno mai dato i LED — viene dalla posa lunga a guadagno zero, che questa
 * geometria si può permettere perché bottiglia e camera sono ferme entrambe
 * (vedi `amelie.capture`).
 *
 * ── DUE VINCOLI CHE FANNO FALLIRE IN SILENZIO ────────────────────────────────
 *
 * 1. Chiamare Bridge.call() o Monitor.print() DENTRO un gestore registrato con
 *    provide() manda in stallo il canale di comunicazione. È documentato. Per
 *    questo i gestori qui sotto non fanno altro che scrivere in una variabile,
 *    e ogni accesso a Wire1 avviene nel loop().
 *
 * 2. Un .ino non è un .cpp: prima di compilarlo, Arduino gli genera i prototipi
 *    di tutte le funzioni e li infila subito PRIMA della prima definizione di
 *    funzione del file. Un tipo dichiarato dopo quel punto non esiste ancora
 *    quando il prototipo lo nomina, e si prende un "has not been declared" su
 *    una riga che sta sotto la dichiarazione e sembra corretta. Per questo qui
 *    tutti i tipi e le variabili stanno insieme in cima, e le funzioni dopo.
 *
 * ── LA MISURA ────────────────────────────────────────────────────────────────
 *
 * Il tetto dei 131.072 byte che App Lab impone caricando in SRAM riguarda
 * un'altra via di caricamento, non `arduino-cli --upload`. Ma la dimensione
 * dipende dalla catena di compilazione, e parecchio: 33.000 byte compilando
 * sulla board, 115.864 compilando su PC col core arduino:zephyr 1.0.0 — e
 * cambia anche il tetto dichiarato, 1.966.080 contro 786.432. Il numero si
 * misura, non si ricorda: vedi la tabella in README.md.
 */

#include <Arduino_RouterBridge.h>
#include <Modulino.h>

/* ─── tutto ciò che si dichiara, prima di qualsiasi funzione (vincolo 2) ────── */

/* Indirizzi a 7 bit. Il datasheet chiama 0x6C l'indirizzo "Modulino" e 0x36
 * quello "Hardware": qui va quello hardware. Passare 0x6C fallisce in SILENZIO,
 * perché begin() ritorna comunque true.
 *
 * Un solo Pixels, quindi l'indirizzo di fabbrica va bene com'è: non c'è niente
 * da riprogrammare prima di montare. */
/* Versione del protocollo fra questo firmware e Linux. Si alza ogni volta che
 * cambia il SIGNIFICATO di qualcosa, non il codice.
 *
 * Alla 2 il secondo Pixels e' stato tolto, e il bit 2 di moduli() e' passato da
 * "flash" a "sensore" mentre il sensore lasciava il bit 4. Un Linux nuovo che
 * interroga un MCU alla versione 1 leggerebbe "sensore presente" quando c'e' il
 * flash, e "sensore assente" con il sensore collegato: il guasto peggiore che
 * si possa avere montando, perche' e' silenzioso e dice il contrario del vero.
 * Con questo numero il lato Linux se ne accorge e lo dice. */
static const int PROTOCOLLO = 2;

static const uint8_t IND_ANELLO   = 0x36;
static const uint8_t IND_DISTANZA = 0x29;   /* VL53L4CD, fisso */
static const uint8_t N_LED = 8;

ModulinoPixels anello(IND_ANELLO);
ModulinoDistance tof;

/* Quali moduli hanno risposto. Si cercano invece di darli per presenti: un
 * `begin()` su un indirizzo che non risponde puo' NON TORNARE, e allora setup()
 * non finisce e Linux non vede mai i metodi - sintomo identico a un firmware
 * assente. E' successo montando: con i Modulino ancora scollegati il
 * dispositivo sembrava senza firmware.
 *
 * Si ricercano anche a caldo, ogni due secondi, cosi' durante il montaggio si
 * collega un pezzo per volta e prende vita da solo. */
static bool c_anello = false, c_tof = false;
static uint32_t ultimo_sondaggio = 0;

/* Stato richiesto da Linux. I gestori scrivono qui e basta: l'accesso a Wire1
 * avviene solo nel loop, mai dentro un handler del Bridge. */
struct StatoLed {
  uint8_t r = 0, g = 0, b = 0, lum = 0;
  bool da_applicare = false;
};
static StatoLed rich_anello;

/* Presenza della bottiglia. L'isteresi vera sta su Linux, in amelie.bridge:
 * qui si tiene solo l'ultima misura valida e si notifica il cambiamento, così
 * il microcontrollore resta semplice e la politica si cambia senza riflashare. */
static int ultima_mm = -1;
static bool presente = false;
static uint32_t ultimo_invio = 0;

/* ─── il bus ───────────────────────────────────────────────────────────────── */

static bool risponde(uint8_t indirizzo) {
  Wire1.beginTransmission(indirizzo);
  return Wire1.endTransmission() == 0;
}

static void cerca_moduli() {
  if (!c_anello && risponde(IND_ANELLO))   c_anello = anello.begin();
  if (!c_tof    && risponde(IND_DISTANZA)) c_tof    = tof.begin();
}

/* ─── gestori esposti a Linux ──────────────────────────────────────────────── */

bool set_anello(int r, int g, int b, int lum) {
  rich_anello = {(uint8_t)r, (uint8_t)g, (uint8_t)b, (uint8_t)lum, true};
  return true;
}

/* Ultima misura valida in millimetri, -1 se il sensore non sa rispondere.
 * Il "non so" è già un buon segnale di "non c'è niente sopra": il VL53L4CD
 * dichiara la misura non valida quando il segnale di ritorno è troppo debole,
 * ed è esattamente ciò che succede con il piatto vuoto. */
int distanza() { return ultima_mm; }

/* La versione del protocollo, non del firmware: vedi PROTOCOLLO in cima. */
int versione() { return PROTOCOLLO; }

/* Quali moduli il microcontrollore vede in questo momento, come somma di bit:
 * 1 anello, 2 sensore. Serve a montare - si collega un pezzo per volta e si
 * chiede al dispositivo se lo vede - e a capire un guasto senza smontare
 * niente. */
int moduli() {
  return (c_anello ? 1 : 0) | (c_tof ? 2 : 0);
}

/* ─── ciclo ────────────────────────────────────────────────────────────────── */

static void applica(ModulinoPixels &p, StatoLed &s) {
  if (!s.da_applicare) return;
  for (uint8_t i = 0; i < N_LED; i++) p.set(i, s.r, s.g, s.b, s.lum);
  p.show();
  s.da_applicare = false;
}

void setup() {
  Bridge.begin();

  /* I METODI SI DICHIARANO PRIMA DI TOCCARE L'I2C.
   *
   * Se un Modulino non risponde - non ancora collegato, un cavetto staccato,
   * un indirizzo sbagliato - begin() puo' non tornare, e allora setup() non
   * finisce e Linux non vede MAI i metodi. Il sintomo e' identico a un
   * firmware non caricato: il router risponde e ogni chiamata dice "method not
   * available". E' successo, e ci si perde un'ora a cercare nel posto
   * sbagliato.
   *
   * Dichiarandoli qui, il firmware si puo' verificare PRIMA di collegare
   * qualsiasi cosa - che e' l'ordine in cui si monta un dispositivo - e un
   * modulo guasto costa un anello spento, non un dispositivo muto. */
  Bridge.provide("set_anello", set_anello);
  Bridge.provide("distanza", distanza);
  Bridge.provide("moduli", moduli);
  Bridge.provide("versione", versione);

  /* Su UNO Q i Modulino stanno su Wire1. Si cercano, non si danno per presenti. */
  Wire1.begin();
  cerca_moduli();

  /* Un lampo d'ambra all'accensione: dice che il firmware è vivo prima ancora
   * che Linux abbia finito di avviarsi, che richiede 20-30 secondi. */
  if (c_anello) {
    for (uint8_t i = 0; i < N_LED; i++) anello.set(i, 255, 150, 40, 20);
    anello.show();
  }
}

void loop() {
  /* Il solo include di Arduino_RouterBridge limita il loop a circa 1 kHz anche
   * senza chiamate: il ponte si aggancia al loop per sincronizzarsi. Non ha
   * senso girare più veloci di così. */

  /* Ogni due secondi si guarda se e' comparso qualcosa di nuovo sul bus. */
  uint32_t ora_ms = millis();
  if (ora_ms - ultimo_sondaggio > 2000) {
    ultimo_sondaggio = ora_ms;
    cerca_moduli();
  }

  if (c_tof && tof.available()) {
    ultima_mm = (int)tof.get();
  } else {
    ultima_mm = -1;
  }

  /* Notifica solo i cambiamenti, e non più di dieci volte al secondo: il
   * trasporto è una seriale a 115200 baud condivisa con tutto il resto. */
  bool ora = (ultima_mm >= 0 && ultima_mm < 40);
  uint32_t adesso = millis();
  if (ora != presente && (adesso - ultimo_invio) > 100) {
    presente = ora;
    ultimo_invio = adesso;
    Bridge.notify("bottiglia", presente, ultima_mm);
  }

  if (c_anello) applica(anello, rich_anello);

  delay(20);
}
