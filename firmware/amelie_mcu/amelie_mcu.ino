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
 * tolto, e con lui la parte più fragile del montaggio: due Pixels nascono
 * entrambi a 0x36, quindi il secondo andava riprogrammato una volta per sempre,
 * e da fuori i due moduli sono identici. L'etichetta si illumina lo stesso —
 * l'anello sale a bianco per la durata della raffica.
 *
 * ── I MODULI SI CERCANO SOLO ALL'ACCENSIONE ──────────────────────────────────
 *
 * Il dispositivo si monta una volta e non si tocca più: i Modulino sono avvitati
 * dentro la scocca. Cercarli anche dopo, per poterli attaccare a caldo, non
 * serve a niente e costa carissimo — vedi il vincolo 1 qui sotto.
 *
 * ── TRE VINCOLI CHE FANNO FALLIRE IN SILENZIO ────────────────────────────────
 *
 * 1. IL DRIVER DEL SENSORE NON HA VIA D'USCITA. In `platform.cpp` della
 *    libreria VL53L4CD:
 *
 *        do { ...trasferimento I2C... } while (status != 0);
 *
 *    Un ciclo di ritentativi senza uscita, e la sola scappatoia prevista è
 *    chiusa in `#ifdef ARDUINO_ARCH_STM32`, che sul core Zephyr della UNO Q non
 *    è definito. La libreria Modulino lo sa — "the library contains a
 *    while(true) on begin()", c'è scritto nel suo sorgente — e si difende
 *    scandendo l'indirizzo prima di `begin()`. NON BASTA: un chip appena
 *    alimentato riconosce il proprio indirizzo parecchio prima di saper servire
 *    un registro.
 *
 *    È successo al banco, ed è un guasto totale: il `loop()` non gira più,
 *    quindi il Bridge non risponde a NIENTE — nemmeno a `versione()` — e da
 *    Linux il dispositivo sembra senza firmware. Peggio: il sensore resta mezzo
 *    configurato, e da quello stato non si esce riavviando il microcontrollore.
 *    Si esce solo togliendo corrente al modulo.
 *
 *    Difesa: si legge il registro d'identità con una transazione NOSTRA, che al
 *    massimo fallisce, e il chip si consegna al driver solo quando risponde
 *    0xEBAA. E non lo si consegna mai più dopo l'accensione.
 *
 * 2. Chiamare Bridge.call() o Monitor.print() DENTRO un gestore registrato con
 *    provide() manda in stallo il canale. È documentato. Per questo i gestori
 *    qui sotto non fanno altro che scrivere in una variabile, e ogni accesso a
 *    Wire1 avviene nel loop().
 *
 * 3. Un .ino non è un .cpp: Arduino gli genera i prototipi e li infila subito
 *    PRIMA della prima definizione di funzione. Un tipo dichiarato dopo quel
 *    punto non esiste ancora quando il prototipo lo nomina, e si prende un
 *    "has not been declared" su una riga che sta sotto la dichiarazione e
 *    sembra corretta. Per questo qui tutti i tipi e le variabili stanno in cima.
 *
 * ── LA MISURA ────────────────────────────────────────────────────────────────
 *
 * Il tetto dei 131.072 byte che App Lab impone caricando in SRAM riguarda
 * un'altra via di caricamento, non `arduino-cli --upload`. E la dimensione
 * dipende dalla catena: ~33.000 byte compilando sulla board (core 0.52.0),
 * ~116.000 compilando su PC (core 1.0.0), su tetti diversi. Si misura, non si
 * ricorda: vedi la tabella in README.md.
 */

#include <Arduino_RouterBridge.h>
#include <Modulino.h>

/* ─── tutto ciò che si dichiara, prima di qualsiasi funzione (vincolo 3) ────── */

/* Versione del PROTOCOLLO fra questo firmware e Linux. Si alza quando cambia il
 * SIGNIFICATO di qualcosa, non il codice.
 *
 * Alla 2 il secondo Pixels è stato tolto, e il bit 2 di moduli() è passato da
 * "flash" a "sensore" mentre il sensore lasciava il bit 4. Un Linux nuovo che
 * interroga un MCU alla versione 1 leggerebbe "sensore presente" quando c'è il
 * flash, e "sensore assente" con il sensore collegato: il guasto peggiore che
 * si possa avere montando, perché è silenzioso e dice il contrario del vero. */
static const int PROTOCOLLO = 2;

/* Indirizzi a 7 bit. Il datasheet chiama 0x6C l'indirizzo "Modulino" e 0x36
 * quello "Hardware": qui va quello hardware. Passare 0x6C fallisce in SILENZIO,
 * perché begin() ritorna comunque true. Un solo Pixels, quindi l'indirizzo di
 * fabbrica va bene com'è: non c'è niente da riprogrammare prima di montare. */
static const uint8_t IND_ANELLO   = 0x36;
static const uint8_t IND_DISTANZA = 0x29;   /* VL53L4CD, fisso */
static const uint8_t N_LED = 8;

/* Il registro d'identità del VL53L4CD e il valore che deve contenere: è il
 * lasciapassare del vincolo 1. */
static const uint16_t REG_IDENTITA = 0x010F;
static const uint16_t IDENTITA_TOF = 0xEBAA;

/* Quanto si aspetta, all'accensione, che i moduli si presentino. Il
 * microcontrollore parte in millisecondi, il sensore ha bisogno di più tempo, e
 * qui non c'è fretta: Linux ci mette comunque una cinquantina di secondi ad
 * arrivare alla sua schermata. Scaduta l'attesa si va avanti lo stesso — un
 * dispositivo che racconta senza vedere la bottiglia è meglio di uno fermo. */
static const uint32_t ATTESA_MODULI_MS = 8000;
static const uint32_t PASSO_RICERCA_MS = 100;

/* Quante letture buone di fila servono prima di consegnare il sensore al
 * driver. UNA NON BASTA, ed è costato un pomeriggio scoprirlo: collegando il
 * cavetto a dispositivo acceso il guardiano passava — il chip rispondeva
 * 0xEBAA — e `begin()` si bloccava lo stesso. Un connettore che entra rimbalza,
 * e il chip alimentato a singhiozzo risponde a una lettura e alla successiva
 * no. Tre letture a un decimo di secondo l'una dicono che il bus è stabile, non
 * che è stato fortunato una volta. */
static const uint8_t LETTURE_BUONE = 3;

/* Il respiro dell'accensione. Dà segno di vita mentre Linux si avvia: il
 * microcontrollore è pronto in millisecondi, lo schermo ci mette una
 * cinquantina di secondi, e in mezzo l'anello sarebbe spento — un dispositivo
 * appena acceso che non fa niente sembra rotto.
 *
 * Si spegne da solo al primo comando che arriva da Linux: da quel momento il
 * colore dell'anello lo decide la macchina a stati, e due padroni sullo stesso
 * anello si vedrebbero come un tremolio. */
static const uint8_t  RESPIRO_MIN = 3;
static const uint8_t  RESPIRO_MAX = 26;
static const uint32_t RESPIRO_MS = 50;      /* 20 aggiornamenti al secondo */
static const uint8_t  RESPIRO_PASSO = 4;    /* 256/4 x 50 ms = 3,2 s a ciclo */

ModulinoPixels anello(IND_ANELLO);
ModulinoDistance tof;

static bool c_anello = false, c_tof = false;
static bool ricerca_finita = false;
static uint32_t ultima_ricerca = 0;
static uint8_t buone = 0;

/* Il sensore è sparito dal bus? Ci vogliono più fallimenti di fila: uno solo può
 * essere un disturbo, e perdere il sensore per un disturbo significa un
 * dispositivo che non vede più le bottiglie fino al prossimo spegnimento. */
static const uint8_t ASSENZE_PER_RINUNCIARE = 5;
static uint8_t assenze = 0;
static uint32_t ultima_presenza = 0;

static bool respiro = true;
static uint8_t fase = 0;
static uint32_t ultimo_respiro = 0;

/* Stato richiesto da Linux. I gestori scrivono qui e basta: l'accesso a Wire1
 * avviene solo nel loop, mai dentro un handler del Bridge (vincolo 2). */
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

/* Il sensore risponde all'indirizzo E sa servire i registri? Vedi il vincolo 1:
 * è questa lettura, non la scansione dell'indirizzo, a dire che il chip ha
 * finito di avviarsi e che il driver non girerà a vuoto per sempre. */
static bool tof_pronto() {
  Wire1.beginTransmission(IND_DISTANZA);
  Wire1.write((uint8_t)(REG_IDENTITA >> 8));
  Wire1.write((uint8_t)(REG_IDENTITA & 0xFF));
  if (Wire1.endTransmission() != 0) return false;
  if (Wire1.requestFrom((int)IND_DISTANZA, 2) != 2) return false;
  uint16_t id = ((uint16_t)Wire1.read() << 8);
  id |= (uint16_t)Wire1.read();
  return id == IDENTITA_TOF;
}

/* ─── gestori esposti a Linux ──────────────────────────────────────────────── */

bool set_anello(int r, int g, int b, int lum) {
  rich_anello = {(uint8_t)r, (uint8_t)g, (uint8_t)b, (uint8_t)lum, true};
  respiro = false;          /* Linux ha preso il comando: basta respirare */
  return true;
}

/* Ultima misura valida in millimetri, -1 se il sensore non sa rispondere.
 * Il "non so" è già un buon segnale di "non c'è niente sopra": il VL53L4CD
 * dichiara la misura non valida quando il segnale di ritorno è troppo debole,
 * ed è esattamente ciò che succede con il piatto vuoto. */
int distanza() { return ultima_mm; }

/* La versione del protocollo, non del firmware: vedi PROTOCOLLO in cima. */
int versione() { return PROTOCOLLO; }

/* Quali moduli il microcontrollore vede, come somma di bit: 1 anello,
 * 2 sensore. Serve a montare — si collega un pezzo per volta e si chiede al
 * dispositivo se lo vede — e a capire un guasto senza smontare niente. */
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

/* Un respiro, non una rampa lineare: la luminosità cresce col quadrato, così
 * indugia in basso e sale piena verso il colmo, che è come respira una cosa
 * viva. Tutto in interi — qui non serve virgola mobile per venti passi. */
static void respira() {
  uint8_t x = (fase < 128) ? (uint8_t)(fase * 2) : (uint8_t)((255 - fase) * 2);
  uint16_t curva = ((uint16_t)x * x) >> 8;                     /* 0..254 */
  uint8_t lum = RESPIRO_MIN +
                (uint8_t)(((uint32_t)curva * (RESPIRO_MAX - RESPIRO_MIN)) / 254);
  for (uint8_t i = 0; i < N_LED; i++) anello.set(i, 255, 150, 40, lum);
  anello.show();
  fase += RESPIRO_PASSO;
}

void setup() {
  Bridge.begin();

  /* I METODI SI DICHIARANO PRIMA DI TOCCARE L'I2C.
   *
   * Se un Modulino non risponde, begin() può non tornare, e allora setup() non
   * finisce e Linux non vede MAI i metodi. Il sintomo è identico a un firmware
   * non caricato: il router risponde e ogni chiamata dice "method not
   * available". È successo, e ci si perde un'ora a cercare nel posto sbagliato.
   */
  Bridge.provide("set_anello", set_anello);
  Bridge.provide("distanza", distanza);
  Bridge.provide("moduli", moduli);
  Bridge.provide("versione", versione);

  /* Su UNO Q i Modulino stanno su Wire1. Qui si apre il bus e basta: la ricerca
   * si fa nel loop, così il ponte comincia a rispondere subito e l'anello può
   * respirare mentre si aspetta che il sensore finisca di avviarsi. */
  Wire1.begin();
}

void loop() {
  /* Il solo include di Arduino_RouterBridge limita il loop a circa 1 kHz anche
   * senza chiamate: il ponte si aggancia al loop per sincronizzarsi. */
  uint32_t ora_ms = millis();

  /* ── la ricerca, solo nella finestra d'accensione ─────────────────────── */
  if (!ricerca_finita && ora_ms - ultima_ricerca >= PASSO_RICERCA_MS) {
    ultima_ricerca = ora_ms;
    if (!c_anello && risponde(IND_ANELLO)) c_anello = anello.begin();
    /* Il sensore si consegna al driver solo dopo LETTURE_BUONE letture del
     * registro d'identità di fila: vedi il commento sulla costante. */
    if (!c_tof) {
      if (tof_pronto()) {
        if (++buone >= LETTURE_BUONE) c_tof = tof.begin();
      } else {
        buone = 0;
      }
    }
    if ((c_anello && c_tof) || ora_ms > ATTESA_MODULI_MS) ricerca_finita = true;
  }

  /* ── il respiro dell'accensione, finché Linux non prende il comando ───── */
  if (respiro && c_anello && ora_ms - ultimo_respiro >= RESPIRO_MS) {
    ultimo_respiro = ora_ms;
    respira();
  }

  /* ── il sensore ───────────────────────────────────────────────────────── */

  /* Prima di entrare nel driver, si controlla che il sensore ci sia ancora. Se
   * un cavetto cede in servizio, la prima lettura fallita manderebbe il driver
   * nel suo ciclo senza uscita (vincolo 1) e il dispositivo si fermerebbe del
   * tutto. Meglio una transazione in più ogni due decimi di secondo su un bus
   * altrimenti fermo. Un solo indirizzo, non l'identità: la lettura del
   * registro disturberebbe una misura in corso.
   *
   * Perso il sensore, NON lo si reinizializza: rientrare nel driver è
   * esattamente il rischio che si sta evitando. Il dispositivo resta acceso e
   * racconta, semplicemente non vede più arrivare le bottiglie — e `moduli()`
   * lo dice. Si recupera togliendo corrente. */
  if (c_tof && ora_ms - ultima_presenza >= 200) {
    ultima_presenza = ora_ms;
    if (risponde(IND_DISTANZA)) {
      assenze = 0;
    } else if (++assenze >= ASSENZE_PER_RINUNCIARE) {
      c_tof = false;
      ultima_mm = -1;
    }
  }

  if (c_tof && tof.available()) {
    ultima_mm = (int)tof.get();
  } else if (!c_tof) {
    ultima_mm = -1;
  }

  /* Notifica solo i cambiamenti, e non più di dieci volte al secondo: il
   * trasporto è una seriale a 115200 baud condivisa con tutto il resto. */
  bool ora = (ultima_mm >= 0 && ultima_mm < 40);
  if (ora != presente && (ora_ms - ultimo_invio) > 100) {
    presente = ora;
    ultimo_invio = ora_ms;
    Bridge.notify("bottiglia", presente, ultima_mm);
  }

  if (c_anello && !respiro) applica(anello, rich_anello);

  delay(20);
}
