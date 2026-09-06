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
 * ── DUE VINCOLI CHE FANNO FALLIRE IN SILENZIO ────────────────────────────────
 *
 * 1. App Lab carica il binario in SRAM con un tetto di 131.072 byte. Un binario
 *    più grande COMPILA senza errori e poi va in bus fault al caricamento, senza
 *    diagnostica. Includere <Modulino.h> tira dentro sette librerie — due driver
 *    ToF completi, IMU, barometro, umidità, sensore RGB, grafica — ed è il modo
 *    più rapido per avvicinarsi al limite. Qui si includono SOLO i due header
 *    che servono davvero.
 *
 * 2. Chiamare Bridge.call() o Monitor.print() DENTRO un gestore registrato con
 *    provide() manda in stallo il canale di comunicazione. È documentato. Per
 *    questo i gestori qui sotto non fanno altro che scrivere in una variabile,
 *    e ogni accesso a Wire1 avviene nel loop().
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
#include <ModulinoPixels.h>
#include <ModulinoDistance.h>

/* Indirizzi a 7 bit. Il datasheet chiama 0x6C l'indirizzo "Modulino" e 0x36
 * quello "Hardware": qui va quello hardware. Passare 0x6C fallisce in SILENZIO,
 * perché begin() ritorna comunque true. */
static const uint8_t IND_ANELLO = 0x36;
static const uint8_t IND_FLASH  = 0x37;

ModulinoPixels anello(IND_ANELLO);
ModulinoPixels flash(IND_FLASH);
ModulinoDistance tof;

static const uint8_t N_LED = 8;

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

/* ─── ciclo ────────────────────────────────────────────────────────────────── */

static void applica(ModulinoPixels &p, StatoLed &s) {
  if (!s.da_applicare) return;
  for (uint8_t i = 0; i < N_LED; i++) p.set(i, s.r, s.g, s.b, s.lum);
  p.show();
  s.da_applicare = false;
}

void setup() {
  Bridge.begin();

  /* Su UNO Q i Modulino stanno su Wire1: la libreria lo sceglie da sola. */
  anello.begin();
  flash.begin();
  tof.begin();

  Bridge.provide("set_anello", set_anello);
  Bridge.provide("set_flash", set_flash);
  Bridge.provide("distanza", distanza);

  /* Un lampo d'ambra all'accensione: dice che il firmware è vivo prima ancora
   * che Linux abbia finito di avviarsi, che richiede 20-30 secondi. */
  for (uint8_t i = 0; i < N_LED; i++) anello.set(i, 255, 150, 40, 20);
  anello.show();
}

void loop() {
  /* Il solo include di Arduino_RouterBridge limita il loop a circa 1 kHz anche
   * senza chiamate: il ponte si aggancia al loop per sincronizzarsi. Non ha
   * senso girare più veloci di così. */
  if (tof.available()) {
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

  applica(anello, rich_anello);
  applica(flash, rich_flash);

  delay(20);
}
