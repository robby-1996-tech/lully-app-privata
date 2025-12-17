# calendar.py
# Calendario Lullyland (slot + area 1/2) integrabile con bookings

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import sqlite3


# -------------------------
# Config slot
# -------------------------

# Slot keys
SLOT_MATTINA = "mattina"
SLOT_SERA = "sera"

# Orari (solo testo, utile per UI)
SLOT_LABELS = {
    SLOT_MATTINA: "09:30–12:30",
    SLOT_SERA: "17:00–20:00",
}

# Regola: Lun–Dom -> sera sempre
# Sab+Dom -> anche mattina
def slots_for_date(d: date) -> List[str]:
    # weekday(): Mon=0 ... Sun=6
    if d.weekday() in (5, 6):  # Saturday=5, Sunday=6
        return [SLOT_MATTINA, SLOT_SERA]
    return [SLOT_SERA]


# -------------------------
# DB helpers (per app.py)
# -------------------------

def ensure_calendar_columns(conn: sqlite3.Connection) -> None:
    """
    Aggiunge colonne a 'bookings' se non esistono:
    - slot_key: 'mattina'/'sera'
    - area_num: 1/2
    """
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(bookings)").fetchall()]
    if "slot_key" not in cols:
        conn.execute("ALTER TABLE bookings ADD COLUMN slot_key TEXT")
    if "area_num" not in cols:
        conn.execute("ALTER TABLE bookings ADD COLUMN area_num INTEGER")
    conn.commit()


def parse_iso_date(s: str) -> Optional[date]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


# -------------------------
# Assegnazione automatica Area 1 / Area 2
# -------------------------

def _get_used_areas(conn: sqlite3.Connection, data_evento: str, slot_key: str) -> List[int]:
    rows = conn.execute(
        """
        SELECT area_num
        FROM bookings
        WHERE data_evento = ?
          AND slot_key = ?
          AND area_num IS NOT NULL
        """,
        (data_evento, slot_key),
    ).fetchall()
    used = []
    for r in rows:
        try:
            used.append(int(r["area_num"]))
        except Exception:
            pass
    return used


def find_first_available_area(conn: sqlite3.Connection, data_evento: str, slot_key: str) -> Optional[int]:
    used = set(_get_used_areas(conn, data_evento, slot_key))
    for a in (1, 2):
        if a not in used:
            return a
    return None


def auto_assign_slot_and_area(
    conn: sqlite3.Connection,
    data_evento: str,
    preferred_slot: Optional[str] = None,
) -> Tuple[str, int]:
    """
    Regole:
    - Se preferred_slot è passato e valido per quel giorno, prova quello
    - Altrimenti prova gli slot validi in ordine (mattina poi sera nel weekend, solo sera nei feriali)
    - Dentro lo slot: assegna Area 1 alla prima festa, Area 2 alla seconda
    - Se pieno -> ValueError
    """
    d = parse_iso_date(data_evento)
    if not d:
        raise ValueError("Data evento non valida (serve YYYY-MM-DD).")

    valid_slots = slots_for_date(d)

    # 1) Se l'utente fornisce uno slot preferito (in futuro), proviamolo
    if preferred_slot and preferred_slot in valid_slots:
        area = find_first_available_area(conn, data_evento, preferred_slot)
        if area is not None:
            return preferred_slot, area

    # 2) Altrimenti scegliamo il primo slot disponibile
    for slot in valid_slots:
        area = find_first_available_area(conn, data_evento, slot)
        if area is not None:
            return slot, area

    # 3) Tutto pieno
    raise ValueError("Giornata piena: non ci sono slot/aree disponibili.")


# -------------------------
# Lettura eventi per calendario
# -------------------------

@dataclass
class CalendarEvent:
    id: int
    data_evento: str
    slot_key: str
    area_num: int
    nome_festeggiato: str
    eta_festeggiato: Optional[int]
    invitati_bambini: int
    invitati_adulti: int
    pacchetto: str
    tema_evento: str


def _row_to_event(r: sqlite3.Row) -> CalendarEvent:
    return CalendarEvent(
        id=int(r["id"]),
        data_evento=(r["data_evento"] or ""),
        slot_key=(r["slot_key"] or ""),
        area_num=int(r["area_num"] or 0),
        nome_festeggiato=(r["nome_festeggiato"] or ""),
        eta_festeggiato=int(r["eta_festeggiato"]) if r["eta_festeggiato"] not in (None, "") else None,
        invitati_bambini=int(r["invitati_bambini"] or 0),
        invitati_adulti=int(r["invitati_adulti"] or 0),
        pacchetto=(r["pacchetto"] or ""),
        tema_evento=(r["tema_evento"] or ""),
    )


def get_events_between(
    conn: sqlite3.Connection,
    start_date: date,
    end_date_inclusive: date,
) -> List[CalendarEvent]:
    """
    Ritorna tutte le prenotazioni tra start_date e end_date_inclusive.
    """
    start_s = start_date.strftime("%Y-%m-%d")
    end_s = end_date_inclusive.strftime("%Y-%m-%d")

    rows = conn.execute(
        """
        SELECT id, data_evento, slot_key, area_num,
               nome_festeggiato, eta_festeggiato,
               invitati_bambini, invitati_adulti,
               pacchetto, tema_evento
        FROM bookings
        WHERE data_evento >= ?
          AND data_evento <= ?
        ORDER BY data_evento ASC, slot_key ASC, area_num ASC, id ASC
        """,
        (start_s, end_s),
    ).fetchall()

    return [_row_to_event(r) for r in rows]


def build_calendar_index(
    events: List[CalendarEvent],
) -> Dict[str, Dict[str, Dict[int, CalendarEvent]]]:
    """
    Struttura:
    index[data_evento][slot_key][area_num] = event
    """
    idx: Dict[str, Dict[str, Dict[int, CalendarEvent]]] = {}
    for e in events:
        idx.setdefault(e.data_evento, {}).setdefault(e.slot_key, {})[e.area_num] = e
    return idx


# -------------------------
# Griglie mese/settimana
# -------------------------

def month_grid(year: int, month: int) -> List[List[Optional[date]]]:
    """
    Ritorna una griglia 6x7 (settimane x giorni) stile calendario.
    Lunedì come primo giorno.
    Celle fuori mese = None.
    """
    first = date(year, month, 1)
    # weekday: Mon=0..Sun=6
    start_offset = first.weekday()
    grid_start = first - timedelta(days=start_offset)

    weeks: List[List[Optional[date]]] = []
    cur = grid_start
    for _ in range(6):
        week = []
        for _ in range(7):
            if cur.month == month:
                week.append(cur)
            else:
                week.append(None)
            cur += timedelta(days=1)
        weeks.append(week)
    return weeks


def week_range(containing: date) -> Tuple[date, date]:
    """
    Ritorna (lun, dom) della settimana che contiene 'containing'.
    """
    start = containing - timedelta(days=containing.weekday())
    end = start + timedelta(days=6)
    return start, end


# -------------------------
# Etichette utili per UI
# -------------------------

def short_event_text(e: CalendarEvent) -> str:
    # esempio: "Marco (5) • A1 • 20b/20a • Experience"
    eta = f"{e.eta_festeggiato}" if e.eta_festeggiato is not None else "-"
    return f"{e.nome_festeggiato} ({eta}) • A{e.area_num} • {e.invitati_bambini}b/{e.invitati_adulti}a • {e.pacchetto}"


def slot_title(slot_key: str) -> str:
    return f"{slot_key.capitalize()} {SLOT_LABELS.get(slot_key, '')}".strip()
