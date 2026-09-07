/*
 * Amelie 2.0 — firmware del microcontrollore
 *
 * Il connettore Qwiic della UNO Q è cablato sull'I2C4 dello STM32U585, non del
 * processore Linux: i due anelli di LED e il sensore di distanza li vede solo
 * questo microcontrollore. Linux ci parla attraverso il router (Bridge).
 *
 * Questa divisione permette l'attesa a consumo bassissimo: qui si fa la guardia
 * sul sensore, e Linux viene svegliato solo quando arriva una bottiglia.
 *
 * ── TRE VINCOLI CHE FANNO FALLIRE IN SILENZIO ────────────────────────────────
 *
 * 1. App Lab carica il binario in SRAM con un tetto di 131.072 byte, e un binario
 *    più grande COMPILA senza errori per poi andare in bus fault al caricamento.
 *    Da qui l'idea di includere solo gli header dei due Modulino che servono,
 *    invece di <Modulino.h> che ne tira dentro sette — due driver ToF completi,
 *    IMU, barometro, umidità, sensore RGB, grafica.
 *
 *    MISURATO, e l'idea era sbagliata due volte. Primo: Arduino_Modulino 0.9.0
 *    NON espone ModulinoPixels.h e ModulinoDistance.h, quindi lo sketch non
 *    compilava affatto. Secondo: caricando con `arduino-cli` per il core
 *    arduino:zephyr, <Modulino.h> compreso, il binario occupa 33.000 byte di
 *    programma su 1.966.080 e 3.772 byte di RAM su 523.624. L'1%. Il tetto dei
 *    131 KB riguarda un'altra via di caricamento, non questa.
 *
 * 2. Chiamare Bridge.call() o Monitor.print() DENTRO un gestore registrato con
 *    provide() manda in stallo il canale di comunicazione. È documentato. Per
 *    questo i gestori qui sotto non fanno altro che scrivere in una variabile,
 *    e ogni accesso a Wire1 avviene nel loop().
 *
 * 3. Un .ino non è un .cpp: prima di compilarlo, Arduino gli genera i prototipi
 *    di tutte le funzioni e li infila subito PRIMA della prima definizione di
 *    funzione del file. Un tipo dichiarato dopo quel punto non esiste ancora
 *    quando il prototipo lo nomina, e si prende un "has not been declared" su
 *    una riga che sta sotto la dichiarazione e sembra corretta. Per questo qui
 *    tutti i tipi e le variabili stanno insieme in cima, e le funzioni dopo.
 *
 * ── I DUE ANELLI ─────────────────────────────────────────────────────────────
 *
 * I Modulino Pixels nascono tutti all'indirizzo 0x36. Il secondo va
 * riprogrammato UNA VOLTA, con un solo modulo collegato, usando lo sketch
 * examples/Utilities/AddressChanger della libreria Arduino_Modulino: comando
 * "36 37" sul monitor seriale, poi togliere e ridare corrente. L'indirizzo
 * resta in memoria. L'auto-discovery non troverà mai il secondo modulo, quindi
 * va costruito con l'indirizzo esplicito, in forma a 7 bit.
 */

#include <Arduino_RouterBridge.h>
#include <Modulino.h>

/* ─── tutto ciò che si dichiara, prima di qualsiasi funzione (vincolo 3) ────── */

/* Indirizzi a 7 bit. Il datasheet chiama 0x6C l'indirizzo "Modulino" e 0x36
 * quello "Hardware": qui va quello hardware. Passare 0x6C fallisce in SILENZIO,
 * perché begin() ritorna comunque true. */
static const uint8_t IND_ANELLO   = 0x36;
static const uint8_t IND_FLASH    = 0x37;
static const uint8_t IND_DISTANZA = 0x29;   /* VL53L4CD, fisso */
static const uint8_t N_LED = 8;

ModulinoPixels anello(IND_ANELLO);
ModulinoPixels flash(IND_FLASH);
ModulinoDistance tof;

/* Quali moduli hanno risposto. Si cercano invece di darli per presenti: un
 * `begin()` su un indirizzo che non risponde puo' NON TORNARE, e allora setup()
 * non finisce e Linux non vede mai i metodi - sintomo identico a un firmware
 * assente. E' successo montando: con i Modulino ancora scollegati il
 * dispositivo sembrava senza firmware.
 *
 * Si ricercano anche a caldo, ogni due secondi, cosi' durante il montaggio si
 * collega un pezzo per volta e prende vita da solo. */
static bool c_anello = false, c_flash = false, c_tof = false;
static uint32_t ultimo_sondaggio = 0;

/* Stato richiesto da Linux. I gestori scrivono qui e basta: l'accesso a Wire1
 * avviene solo nel loop, mai dentro un handler del Bridge. */
struct StatoLed {
  uint8_t r = 0, g = 0, b = 0, lum = 0;
  bool da_applicare = false;
};
static StatoLed rich_anello, rich_flash;

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
  if (!c_flash  && risponde(IND_FLASH))    c_flash  = flash.begin();
  if (!c_tof    && risponde(IND_DISTANZA)) c_tof    = tof.begin();
}

/* ─── gestori esposti a Linux ──────────────────────────────────────────────── */

bool set_anello(int r, int g, int b, int lum) {
  rich_anello = {(uint8_t)r, (uint8_t)g, (uint8_t)b, (uint8_t)lum, true};
  return true;
}

bool set_flash(int r, int g, int b, int lum) {
  rich_flash = {(uint8_t)r, (uint8_t)g, (uint8_t)b, (uint8_t)lum, true};
  return true;
}

/* Ultima misura valida in millimetri, -1 se il sensore non sa rispondere.
 * Il "non so" è già un buon segnale di "non c'è niente sopra": il VL53L4CD
 * dichiara la misura non valida quando il segnale di ritorno è troppo debole,
 * ed è esattamente ciò che succede con il piatto vuoto. */
int distanza() { return ultima_mm; }

/* Quali moduli il microcontrollore vede in questo momento, come somma di bit:
 * 1 anello, 2 flash, 4 sensore. Serve a montare - si collega un pezzo per volta
 * e si chiede al dispositivo se lo vede - e a capire un guasto senza smontare
 * niente. */
int moduli() {
  return (c_anello ? 1 : 0) | (c_flash ? 2 : 0) | (c_tof ? 4 : 0);
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
  Bridge.provide("set_flash", set_flash);
  Bridge.provide("distanza", distanza);
  Bridge.provide("moduli", moduli);

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
  if (c_flash)  applica(flash, rich_flash);

  delay(20);
}
