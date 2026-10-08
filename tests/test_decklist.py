"""Parser de listas (Moxfield / Archidekt / MTGA / texto plano) y partners."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decklist
from cards import creature, land
from engine import Game, Player, C, G, U
from policy import Policy


def _fill(n, name="Forest"):
    return "\n".join(f"1 {name} {i}" for i in range(n))


def test_commander_header_then_blank_line_keeps_commander():
    p = decklist.parse_decklist("Commander\n1 Kang\n\n1 Command Tower\n1 Sol Ring")
    assert p["commander"] == "Kang"
    assert (1, "Command Tower") in p["cards"] and (1, "Sol Ring") in p["cards"]


def test_moxfield_flags_and_set_numbers_are_stripped():
    txt = ("1 Sol Ring (C21) 263 *F*\n1 Arcane Signet (ELD) 331 *E*\n"
           "1 Lightning Bolt (2X2) 117★ *F*\n\n1 Kang (MOM) 2 *F*")
    p = decklist.parse_decklist(txt)
    names = [n for _q, n in p["cards"]]
    assert names == ["Sol Ring", "Arcane Signet", "Lightning Bolt"]
    assert p["commander"] == "Kang"


def test_archidekt_categories_and_commander():
    txt = ("1x Atraxa, Praetors' Voice (2x2) 190 [Commander{top}]\n"
           "1x Sol Ring (c21) 263 [Ramp]\n"
           "1x Cultivate (m21) 177 [Ramp,Land Search] ^Have,#37d67a^\n"
           "1x Doubling Season (2x2) 120 [Maybeboard{noDeck}{noPrice}]\n"
           "1x Swords to Plowshares (sta) 10 [Sideboard]\n")
    p = decklist.parse_decklist(txt)
    assert p["commander"] == "Atraxa, Praetors' Voice"
    assert [n for _q, n in p["cards"]] == ["Sol Ring", "Cultivate"]


def test_moxfield_raw_tail_commander_with_sideboard_after():
    txt = _fill(99) + "\n\n1 Kang\n\nSIDEBOARD:\n1 Counterspell\n1 Brainstorm"
    p = decklist.parse_decklist(txt)
    assert p["commander"] == "Kang"
    assert len(p["cards"]) == 99 and all(n != "Counterspell" for _q, n in p["cards"])


def test_partners_in_commander_section():
    txt = "Commander\n1 Tymna the Weaver\n1 Thrasios, Triton Hero\n\nDeck\n" + _fill(98)
    p = decklist.parse_decklist(txt)
    assert p["commanders"] == ["Tymna the Weaver", "Thrasios, Triton Hero"]
    assert len(p["cards"]) == 98


def test_partners_raw_tail_two_cards():
    p = decklist.parse_decklist(_fill(98) + "\n\n1 Tymna the Weaver\n1 Thrasios, Triton Hero")
    assert p["commanders"] == ["Tymna the Weaver", "Thrasios, Triton Hero"]
    assert len(p["cards"]) == 98


def test_two_card_tail_without_partner_count_is_not_commander():
    p = decklist.parse_decklist(_fill(40) + "\n\n1 Sol Ring\n1 Mana Crypt")
    assert p["commanders"] == []


def test_mtga_format():
    txt = "Commander\n1 Kang (MOM) 2\n\nDeck\n1 Sol Ring (C21) 263\n1 Island (MOM) 280"
    p = decklist.parse_decklist(txt)
    assert p["commander"] == "Kang"
    assert [n for _q, n in p["cards"]] == ["Sol Ring", "Island"]


def _fetch(cards):
    def f(name):
        return cards.get(name)
    return f


def test_build_deck_partner_identity_and_98():
    import cardsdb
    a = {"name": "Alpha", "mana_cost": "{1}{U}", "type_line": "Legendary Creature — Elf",
         "oracle_text": "Partner", "power": "2", "toughness": "2", "color_identity": ["U"]}
    b = {"name": "Beta", "mana_cost": "{1}{G}", "type_line": "Legendary Creature — Elf",
         "oracle_text": "Partner", "power": "2", "toughness": "2", "color_identity": ["G"]}
    fetch = _fetch({"Alpha": a, "Beta": b})
    deck, cmd, rep = decklist.build_deck({"commander": "Alpha", "commanders": ["Alpha", "Beta"],
                                          "cards": []}, fetch=fetch)
    assert len(deck) == 98
    names = {c.name for c in deck}
    assert names == {"Island", "Forest"}
    pl = Player("p", deck, cmd, policy=Policy())
    assert [c.name for c in pl.commanders] == ["Alpha", "Beta"]
    assert pl.identity() == {U, G}
    assert len(pl.command) == 2


def test_colorless_commander_fills_with_wastes():
    k = {"name": "Kozilek", "mana_cost": "{10}", "type_line": "Legendary Creature — Eldrazi",
         "oracle_text": "", "power": "12", "toughness": "12", "color_identity": []}
    deck, cmd, rep = decklist.build_deck({"commander": "Kozilek", "cards": []},
                                         fetch=_fetch({"Kozilek": k}))
    assert {c.name for c in deck} == {"Wastes"}


def test_partner_tax_and_damage_are_per_commander():
    a = creature("Alpha", "1U", 3, 3, legendary=True)
    b = creature("Beta", "1G", 3, 3, legendary=True)
    me = Player("me", [land("Forest", [G], basic=True) for _ in range(40)], a,
                policy=Policy(), partner=b)
    op = Player("op", [land("Forest", [G], basic=True) for _ in range(40)],
                creature("O", "2B", 2, 2, legendary=True), policy=Policy())
    g = Game([me, op], seed=1)
    for _ in range(4):
        g.move_to_battlefield(land("L", [U, G], basic=False), me)
    assert g.cast(me, a, from_command=True)
    g.resolve_stack()
    assert me.tax_for(a) == 2 and me.tax_for(b) == 0
    assert g.cast(me, b, from_command=True)      # Beta sin impuesto: 2 maná
    g.resolve_stack()
    pa = next(pm for pm in me.battlefield if pm.card is a)
    pb = next(pm for pm in me.battlefield if pm.card is b)
    g.deal_damage(pa, op, 3, combat=True)
    g.deal_damage(pb, op, 3, combat=True)
    assert op.cmdr_damage == {"Alpha": 3, "Beta": 3}
    g.to_graveyard(pb, "test")
    g.sba()
    assert any(c is b for c in me.command), "el partner vuelve a la zona de mando"


def test_presets_are_legal_and_use_only_real_cards():
    """Todos los mazos de ejemplo: 99 cartas, singleton, en identidad, y TODA carta
    no-tierra existe en el snapshot real de Scryfall (nada inventado)."""
    import decks
    snap = decks.snapshot()
    basics = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}
    for key in decks.DECKS:
        deck, cmd = decks.build(key)
        assert decks.validate(deck, cmd) == [], (key, decks.validate(deck, cmd))
        assert cmd.name in snap, (key, cmd.name)
        for c in deck:
            if c.is_land() or c.name in basics:
                continue
            assert c.name in snap, (key, c.name)


def test_preset_cards_match_real_stats():
    """Coste y P/T de las cartas de los presets = los de Scryfall."""
    import re
    import decks
    snap = decks.snapshot()
    for key in ("lorehold", "tricky", "kang", "marvel"):
        deck, cmd = decks.build(key)
        for c in [cmd] + deck:
            r = snap.get(c.name)
            if r is None or c.is_land():
                continue
            mc = (r.get("mana_cost") or "").split(" // ")[0]
            if "/" not in mc and "X" not in mc and c.cost is not None:
                g = sum(int(x) for x in re.findall(r"\{(\d+)\}", mc))
                pips = sorted(re.findall(r"\{([WUBRGC])\}", mc))
                assert (c.cost.generic, sorted(c.cost.pips)) == (g, pips), (c.name, c.cost, mc)
            if c.is_creature() and str(r.get("power", "")).isdigit():
                assert (c.power, c.toughness) == (int(r["power"]), int(r["toughness"])), c.name
