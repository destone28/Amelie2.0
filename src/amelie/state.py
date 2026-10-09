"""La macchina a stati dell'interazione.

Il requisito guida del progetto è **attrito zero**: nessuna istruzione, nessun
pulsante, nessun verso obbligato oltre quello naturale. Si appoggia la
bottiglia e il dispositivo fa il resto. Tutto quello che succede è quindi
guidato da due soli segnali fisici — la bottiglia c'è o non c'è. Un
riconoscimento dubbio non si chiede all'ospite: si dice il candidato meno
specifico, che e' quello che si puo' sostenere (vedi `Matcher.il_piu_generico`).

Questo modulo non fa I/O. Non parla con la camera, con l'MCU, con l'LLM: riceve
eventi e produce transizioni ed *effetti*, che qualcun altro esegue. È scritto
così perché la logica dell'interazione è la parte che si sbaglia più facilmente
e più costosamente, ed è l'unica che si può collaudare per intero senza
hardware.

Il ciclo normale::

    ATTESA ──bottiglia──► ASSESTAMENTO ──stabile──► SCANSIONE ──letta──►
    RICONOSCIMENTO ──sicuro──► RACCONTO ──finito──► CONCLUSO ──tolta──► ATTESA

e la deviazione che conta::

    SCANSIONE ──illeggibile──► RIPOSIZIONA ──ritenta──► SCANSIONE
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable


class Stato(enum.Enum):
    """Dove si trova l'interazione."""

    ATTESA = "attesa"                  # nessuna bottiglia, anello ambra
    ASSESTAMENTO = "assestamento"      # bottiglia appena posata, si aspetta che smetta di oscillare
    SCANSIONE = "scansione"            # luce, raffica, OCR
    RICONOSCIMENTO = "riconoscimento"  # interrogazione del database
    RACCONTO = "racconto"              # testo a schermo e voce
    CONCLUSO = "concluso"              # racconto finito, bottiglia ancora lì
    RIPOSIZIONA = "riposiziona"        # etichetta illeggibile, si chiede di girarla
    GUASTO = "guasto"                  # errore tecnico, si mostra e si torna in attesa


class Evento(enum.Enum):
    """Cosa può succedere."""

    BOTTIGLIA_PRESENTE = "bottiglia_presente"
    BOTTIGLIA_ASSENTE = "bottiglia_assente"
    SCADENZA = "scadenza"              # il timer dello stato corrente è scaduto
    LETTURA_RIUSCITA = "lettura_riuscita"
    LETTURA_FALLITA = "lettura_fallita"
    MATCH_SICURO = "match_sicuro"
    MATCH_ASSENTE = "match_assente"
    RACCONTO_FINITO = "racconto_finito"
    RIPETI = "ripeti"                  # tocco sullo schermo a racconto concluso
    RINUNCIA = "rinuncia"              # troppi tentativi di lettura falliti
    # Il tocco su «annulla»: l'ospite chiude da se', senza togliere la
    # bottiglia dal piatto. Vedi le tre righe in TRANSIZIONI.
    ANNULLA = "annulla"
    # Mentre si raccontava, sul piatto e' arrivata un'altra bottiglia - letta
    # in anticipo, a racconto ancora in corso, e riconosciuta come DIVERSA da
    # quella che si stava raccontando. Vedi `Amelie._anticipa`.
    CAMBIO_BOTTIGLIA = "cambio_bottiglia"
    # Una correzione e' stata salvata: si racconta la bottiglia com'e' ora,
    # anche se prima non era stata riconosciuta affatto.
    CORREZIONE_SALVATA = "correzione_salvata"
    ERRORE = "errore"


class Effetto(enum.Enum):
    """Cosa deve fare il mondo esterno quando si entra in uno stato.

    L'orchestratore traduce ciascuno in chiamate concrete: l'anello di luce sta
    sull'MCU, la camera e l'OCR su Linux, la voce su Piper.
    """

    # La luce di ciascuno la decide l'orchestratore (`LUCE_ANELLO` in app.py),
    # e resta ferma: il respiro lo fa solo il firmware all'accensione, finche'
    # Linux non prende il comando.
    ANELLO_RESPIRO = "anello_respiro"      # attesa: bianco e giallo, rosso a batteria scarica
    ANELLO_ACCESO = "anello_acceso"        # bottiglia posata, racconto: bianco e giallo
    ANELLO_LAVORO = "anello_lavoro"        # lettura e ricerca: bianco e giallo
    ANELLO_ATTENZIONE = "anello_attenzione"  # un guasto: rosso
    ANELLO_SPENTO = "anello_spento"
    # La luce dello scatto è quella di sempre, già accesa: la raffica non alza
    # niente, e la posa che la camera ha trovato a riposo vale anche qui.
    ILLUMINA_E_SCATTA = "illumina_e_scatta"
    INTERROGA_DATABASE = "interroga_database"
    AVVIA_RACCONTO = "avvia_racconto"
    FERMA_RACCONTO = "ferma_racconto"
    MOSTRA_RIPOSIZIONA = "mostra_riposiziona"
    MOSTRA_GUASTO = "mostra_guasto"
    SCHERMO_ATTESA = "schermo_attesa"


# Quanto si resta in uno stato prima che scatti SCADENZA. `None` = si resta
# finché non arriva un altro evento.
DURATE_S: dict[Stato, float | None] = {
    # Il minimo, non l'attesa: il tempo che serve alla bottiglia per smettere
    # di oscillare non si aspetta a orologio.
    #
    # La camera resta in moto e lo scatto si prende dal flusso, quindi
    # l'assestamento si può GUARDARE invece che aspettare: si tiene il primo
    # fotogramma abbastanza nitido, e chi appoggia la bottiglia piano non paga
    # l'oscillazione che non c'è. Vedi `Camera.al_volo`.
    #
    # Quel che resta qui è il tempo perché la schermata «fammi guardare» non
    # sia un lampo, e perché la mano che ha appoggiato la bottiglia esca
    # dall'inquadratura.
    Stato.ASSESTAMENTO: 0.15,
    # Nessuno stato che dipende da un thread puo' restare senza tetto: se il
    # lavoro non torna, la macchina resterebbe li' per sempre con il calice che
    # gira. Succede davvero, togliendo e rimettendo la bottiglia mentre parla.
    # Cinquanta secondi, ed e' un cane da guardia, non un limite di qualita':
    # deve scattare quando il lavoro NON torna, mai sul lavoro piu' lento che
    # puo' tornare davvero. Il piu' lento e' uno scatto con la luce della sala
    # cambiata, che arriva a otto secondi, seguito da una lettura che trova
    # poco, riprova il fotogramma negli altri tre versi e lo rilegge piu'
    # largo. Il tetto sta largo sopra la somma.
    Stato.SCANSIONE: 50.0,
    Stato.RICONOSCIMENTO: 15.0,
    Stato.RACCONTO: None,
    Stato.RIPOSIZIONA: 4.0,
    Stato.GUASTO: 6.0,
    # Il racconto e' finito. Si resta due secondi sull'ultima schermata - perche'
    # l'ultima frase si posi, e perche' sparire nell'istante in cui la voce tace
    # e' brusco - e poi si torna in attesa.
    #
    # Non `None`: restare li' per sempre, con il riproduttore in vista e tutti
    # i pulsanti inerti finche' qualcuno non toglie la bottiglia, a tavola non
    # dice niente e non fa niente: e' il dispositivo che sembra piantato.
    Stato.CONCLUSO: 2.0,
    Stato.ATTESA: None,
}

EFFETTI_INGRESSO: dict[Stato, tuple[Effetto, ...]] = {
    Stato.ATTESA: (Effetto.ANELLO_RESPIRO, Effetto.SCHERMO_ATTESA),
    Stato.ASSESTAMENTO: (Effetto.ANELLO_ACCESO,),
    Stato.SCANSIONE: (Effetto.ANELLO_LAVORO, Effetto.ILLUMINA_E_SCATTA),
    Stato.RICONOSCIMENTO: (Effetto.ANELLO_LAVORO, Effetto.INTERROGA_DATABASE),
    Stato.RACCONTO: (Effetto.ANELLO_ACCESO, Effetto.AVVIA_RACCONTO),
    Stato.CONCLUSO: (Effetto.ANELLO_ACCESO,),
    # Non e' un guasto, ed e' una lettura: serve la luce per rileggere.
    Stato.RIPOSIZIONA: (Effetto.ANELLO_LAVORO, Effetto.MOSTRA_RIPOSIZIONA),
    Stato.GUASTO: (Effetto.ANELLO_ATTENZIONE, Effetto.MOSTRA_GUASTO),
}

# Effetti da eseguire USCENDO da uno stato. Serve un solo caso, ma è quello
# che conta: se si toglie la bottiglia mentre il dispositivo sta parlando,
# deve zittirsi subito. Senza questo, continuerebbe a raccontare un vino che
# non c'è più.
EFFETTI_USCITA: dict[Stato, tuple[Effetto, ...]] = {
    Stato.RACCONTO: (Effetto.FERMA_RACCONTO,),
}

# Tabella delle transizioni: (stato, evento) -> stato successivo.
TRANSIZIONI: dict[tuple[Stato, Evento], Stato] = {
    (Stato.ATTESA, Evento.BOTTIGLIA_PRESENTE): Stato.ASSESTAMENTO,

    (Stato.ASSESTAMENTO, Evento.SCADENZA): Stato.SCANSIONE,
    (Stato.ASSESTAMENTO, Evento.BOTTIGLIA_ASSENTE): Stato.ATTESA,

    (Stato.SCANSIONE, Evento.LETTURA_RIUSCITA): Stato.RICONOSCIMENTO,
    (Stato.SCANSIONE, Evento.LETTURA_FALLITA): Stato.RIPOSIZIONA,

    (Stato.RICONOSCIMENTO, Evento.MATCH_SICURO): Stato.RACCONTO,
    # Nessun match non è un fallimento: si racconta la denominazione, o il
    # vitigno, o si chiede di girare l'etichetta. Decide il narratore.
    (Stato.RICONOSCIMENTO, Evento.MATCH_ASSENTE): Stato.RACCONTO,
    # Il riconoscimento puo' concludere che non c'e' NULLA da dire: senza questa
    # transizione l'evento cadrebbe nel vuoto e la macchina resterebbe a girare
    # fino allo scadere del tetto, per poi dichiarare guasto.
    (Stato.RICONOSCIMENTO, Evento.LETTURA_FALLITA): Stato.RIPOSIZIONA,

    (Stato.RACCONTO, Evento.RACCONTO_FINITO): Stato.CONCLUSO,

    (Stato.CONCLUSO, Evento.RIPETI): Stato.RACCONTO,
    # Passati i due secondi si torna alla schermata d'invito, anche se la
    # bottiglia e' ancora sul piatto. Non riparte una seconda lettura: quella la
    # governa l'orchestratore, che ricomincia solo quando la bottiglia viene
    # tolta e rimessa.
    (Stato.CONCLUSO, Evento.SCADENZA): Stato.ATTESA,
    # Anche a racconto in corso: succede quando l'ospite cambia lingua mentre
    # il dispositivo sta parlando. Rientrare in RACCONTO rifa' partire gli
    # effetti d'ingresso, e la storia riparte da capo nella lingua nuova.
    (Stato.RACCONTO, Evento.RIPETI): Stato.RACCONTO,

    (Stato.RIPOSIZIONA, Evento.SCADENZA): Stato.SCANSIONE,
    # Dopo qualche tentativo si smette. Senza questa uscita, un oggetto
    # illeggibile lasciato sul piatto - un bicchiere, una bottiglia senza
    # etichetta - fa lampeggiare l'anello e girare l'OCR per tutta la sera.
    (Stato.RIPOSIZIONA, Evento.RINUNCIA): Stato.CONCLUSO,

    # La bottiglia cambiata a racconto in corso. Si va dritti alla lettura:
    # uscendo da RACCONTO la voce tace, e la lettura e' gia' stata fatta in
    # anticipo, quindi SCANSIONE non scatta un'altra foto ma usa quella.
    (Stato.RACCONTO, Evento.CAMBIO_BOTTIGLIA): Stato.SCANSIONE,
    (Stato.CONCLUSO, Evento.CAMBIO_BOTTIGLIA): Stato.SCANSIONE,

    # Una correzione salvata si racconta subito: e' la prova che ha
    # funzionato. Anche dagli stati in cui la bottiglia non era stata
    # riconosciuta - fra un tentativo e l'altro, o a tentativi finiti - dove
    # il pulsante per insegnarla al dispositivo si vede.
    (Stato.RACCONTO, Evento.CORREZIONE_SALVATA): Stato.RACCONTO,
    (Stato.CONCLUSO, Evento.CORREZIONE_SALVATA): Stato.RACCONTO,
    (Stato.RIPOSIZIONA, Evento.CORREZIONE_SALVATA): Stato.RACCONTO,

    # Se il lavoro non torna entro il tetto, si passa da GUASTO, che scade da
    # solo e riporta in attesa.
    (Stato.SCANSIONE, Evento.SCADENZA): Stato.GUASTO,
    (Stato.RICONOSCIMENTO, Evento.SCADENZA): Stato.GUASTO,

    (Stato.GUASTO, Evento.SCADENZA): Stato.ATTESA,

    # ANNULLA — l'unica via d'uscita che non passi da un fatto fisico.
    #
    # Il modo normale di chiudere e' TOGLIERE LA BOTTIGLIA. E' la scelta
    # giusta per il caso comune - attrito zero, nessun pulsante - ma lascia
    # scoperto chi ha appena versato: il vino e' nel bicchiere, la bottiglia
    # sta sul piatto e nessuno vuole risollevarla per far tacere il
    # dispositivo.
    #
    # Solo da questi due stati, e sono esattamente i due in cui c'e' un
    # pulsante a schermo. CONCLUSO c'e' perche' la vista «racconto» resta
    # accesa anche nei due secondi che seguono la fine (VISTA[CONCLUSO] in
    # app.py): li' il pulsante si vede, quindi deve funzionare. Dagli stati di
    # lavoro NO: quelle schermate non hanno pulsanti, e annullare in SCANSIONE
    # lascerebbe l'OCR a girare.
    (Stato.RACCONTO, Evento.ANNULLA): Stato.ATTESA,
    (Stato.CONCLUSO, Evento.ANNULLA): Stato.ATTESA,
}

# Stati da cui togliere la bottiglia riporta sempre in attesa. Vale ovunque
# tranne che in ATTESA (dove ci si è già) e in GUASTO (che si esaurisce da sé).
_TORNA_IN_ATTESA = frozenset(Stato) - {Stato.ATTESA, Stato.GUASTO}


@dataclass
class Transizione:
    """L'esito di un evento."""

    da: Stato
    evento: Evento
    a: Stato
    effetti: tuple[Effetto, ...] = ()
    durata_s: float | None = None

    @property
    def cambia_stato(self) -> bool:
        return self.da != self.a

    @property
    def rientro(self) -> bool:
        """Si e' rientrati nello stesso stato per una regola dichiarata.

        Non e' la stessa cosa di un evento ignorato. Un evento che nello stato
        corrente non significa niente non deve fare nulla; una transizione
        scritta apposta verso lo stesso stato - `(RACCONTO, RIPETI)` - deve
        eseguire uscita e ingresso, altrimenti dichiararla non serve a niente.

        Senza questa distinzione la riga c'e', ma ripetere il racconto o
        cambiare lingua mentre parla non fa assolutamente nulla. Nessun errore,
        nessun messaggio: la storia semplicemente non riparte.
        """
        return not self.cambia_stato and bool(self.effetti)


@dataclass
class Macchina:
    """La macchina a stati. Non fa I/O: si limita a dire cosa deve succedere.

    >>> m = Macchina()
    >>> m.stato
    <Stato.ATTESA: 'attesa'>
    >>> t = m.invia(Evento.BOTTIGLIA_PRESENTE)
    >>> t.a
    <Stato.ASSESTAMENTO: 'assestamento'>
    >>> Effetto.ANELLO_ACCESO in t.effetti
    True
    """

    stato: Stato = Stato.ATTESA
    storia: list[Transizione] = field(default_factory=list, repr=False)
    su_transizione: Callable[[Transizione], None] | None = None

    def invia(self, evento: Evento) -> Transizione:
        """Applica un evento e restituisce la transizione risultante.

        Un evento che non ha senso nello stato corrente non è un errore: viene
        ignorato e la macchina resta dov'è. Nel mondo reale il sensore di
        presenza rimbalza, l'utente tocca lo schermo quando non serve, e una
        macchina che solleva eccezioni per questo è una macchina che si pianta
        in sala.
        """
        destinazione = self._destinazione(evento)

        # Solo l'ASSENZA di una regola lascia la macchina inerte. Una regola che
        # riporta allo stesso stato e' una scelta di chi l'ha scritta, e va
        # eseguita: vedi `Transizione.rientro`.
        if destinazione is None:
            t = Transizione(da=self.stato, evento=evento, a=self.stato)
        else:
            t = Transizione(
                da=self.stato,
                evento=evento,
                a=destinazione,
                effetti=(
                    EFFETTI_USCITA.get(self.stato, ())
                    + EFFETTI_INGRESSO.get(destinazione, ())
                ),
                durata_s=DURATE_S.get(destinazione),
            )
            self.stato = destinazione

        self.storia.append(t)
        if self.su_transizione is not None:
            self.su_transizione(t)
        return t

    def _destinazione(self, evento: Evento) -> Stato | None:
        # Togliere la bottiglia interrompe tutto: ha precedenza su ogni altra
        # transizione, perché è il modo in cui l'utente dice "ho finito".
        if evento is Evento.BOTTIGLIA_ASSENTE and self.stato in _TORNA_IN_ATTESA:
            return Stato.ATTESA
        # Un guasto può arrivare in qualsiasi momento.
        if evento is Evento.ERRORE:
            return Stato.GUASTO
        return TRANSIZIONI.get((self.stato, evento))

    def reimposta(self) -> None:
        self.stato = Stato.ATTESA
        self.storia.clear()

    @property
    def sta_elaborando(self) -> bool:
        """Vero quando la CPU è occupata e non si devono avviare altri lavori."""
        return self.stato in (
            Stato.SCANSIONE,
            Stato.RICONOSCIMENTO,
            Stato.RACCONTO,
        )
