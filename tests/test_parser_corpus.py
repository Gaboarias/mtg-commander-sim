"""Corpus de regresión del parser de oráculo (cardsdb.build_card_from_data).

Cada test construye una carta REAL con su texto de Oracle (formato Scryfall) y
verifica comportamiento correcto de Magic. Regla 5 de CLAUDE.md: una carta mal
implementada es peor que una vainilla. Donde el efecto completo es complejo, el
test sólo exige que NO ocurra un efecto incorrecto ("# vanilla aceptable").

    python3 -m pytest tests/test_parser_corpus.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import cardsdb
import cards
from engine import Game, Player, Card, parse_cost, W, U, B, R, G, C
from cards import creature, land
from policy import Policy


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def build(name, mana_cost, type_line, oracle, p=None, t=None, ci=(), keywords=(),
          **extra):
    """Carta desde un dict estilo Scryfall."""
    d = {"name": name, "mana_cost": mana_cost, "type_line": type_line,
         "oracle_text": oracle, "color_identity": list(ci),
         "keywords": list(keywords)}
    if p is not None:
        d["power"] = str(p)
        d["toughness"] = str(t)
    d.update(extra)
    return cardsdb.build_card_from_data(d)


def new_game(n_opp=1):
    """Partida de 1 + n_opp jugadores, bibliotecas de 40 tierras básicas."""
    me = Player("me", [], creature("cmdr", "2G", 3, 3, legendary=True), policy=Policy())
    ops = [Player(f"op{i}", [], creature(f"ocmd{i}", "2B", 2, 2, legendary=True),
                  policy=Policy()) for i in range(n_opp)]
    g = Game([me] + ops, seed=1)
    g.interactive_human = None
    for pl in [me] + ops:
        pl.library = [land("Forest", [G], basic=True) for _ in range(40)]
        pl.hand = []
    return g, me, ops


def run(g):
    g.resolve_stack()
    g.sba()


def put(g, card, pl):
    pm = g.move_to_battlefield(card, pl)
    run(g)
    return pm


def give_lands(g, pl, n, colors=(G,), name="Land"):
    for _ in range(n):
        g.move_to_battlefield(land(name, list(colors), basic=False), pl)
    run(g)


def artifact(name="Trinket"):
    return Card(name=name, types={"artifact"}, cost=parse_cost("2"))


def enchantment(name="Glyph"):
    return Card(name=name, types={"enchantment"}, cost=parse_cost("2"))


def bot_cast(g, pl, card):
    """Lanza como lo haría el bot: objetivos elegidos por Policy."""
    pl.hand.append(card)
    targets = Policy().choose_targets(g, pl, card)
    ok = g.cast(pl, card, targets=targets)
    run(g)
    return ok


def tokens(pl, name=None):
    return [p for p in pl.battlefield if p.is_token and (name is None or p.name == name)]


def on_bf(pl, perm_or_name):
    if isinstance(perm_or_name, str):
        return any(p.name == perm_or_name for p in pl.battlefield)
    return perm_or_name in pl.battlefield


def nobody_lost(g):
    return not any(p.lost for p in g.players)


def scry_logged(g, start):
    return any("scry" in ln.lower() for ln in g.log_lines[start:])


# --------------------------------------------------------------------------- #
# 1. Habilidades {T} no son ETB
# --------------------------------------------------------------------------- #

MIND_STONE_TEXTS = [
    "{T}: Add {C}.\n{1}, {T}, Sacrifice Mind Stone: Draw a card.",
    "{T}: Add {C}.\n{1}, {T}, Sacrifice this artifact: Draw a card.",
]


@pytest.mark.parametrize("txt", MIND_STONE_TEXTS, ids=["name", "this"])
def test_corpus_mind_stone(txt):
    c = build("Mind Stone", "{2}", "Artifact", txt, produced_mana=["C"])
    g, me, ops = new_game()
    h0 = len(me.hand)
    put(g, c, me)
    assert len(me.hand) == h0, "Mind Stone no debe robar al entrar"


def test_corpus_royal_assassin():
    c = build("Royal Assassin", "{1}{B}{B}", "Creature — Human Assassin",
              "{T}: Destroy target tapped creature.", 1, 1, ci=("B",))
    g, me, ops = new_game()
    untapped = put(g, creature("OppUntapped", "5", 5, 5), ops[0])
    tapped = put(g, creature("OppTapped", "3", 3, 3), ops[0])
    tapped.tapped = True
    put(g, c, me)
    assert on_bf(ops[0], untapped) and on_bf(ops[0], tapped), \
        "Royal Assassin no destruye nada al entrar"


DISK_TEXTS = [
    "Nevinyrral's Disk enters tapped.\n{1}, {T}: Destroy all artifacts, creatures, and enchantments.",
    "This artifact enters tapped.\n{1}, {T}: Destroy all artifacts, creatures, and enchantments.",
]


@pytest.mark.parametrize("txt", DISK_TEXTS, ids=["name", "this"])
def test_corpus_nevinyrrals_disk(txt):
    c = build("Nevinyrral's Disk", "{4}", "Artifact", txt)
    g, me, ops = new_game()
    give_lands(g, me, 2)
    victims = [put(g, creature("m0", "2", 2, 2), me), put(g, artifact("mA"), me),
               put(g, enchantment("mE"), me),
               put(g, creature("o0", "2", 2, 2), ops[0]), put(g, artifact("oA"), ops[0]),
               put(g, enchantment("oE"), ops[0])]
    disk = put(g, c, me)
    # entrar no destruye nada
    assert all(v.controller.battlefield.count(v) == 1 for v in victims), \
        "Nevinyrral's Disk destruyó permanentes al entrar"
    assert disk.tapped, "Nevinyrral's Disk entra girado"
    # activar: destruye artefactos, criaturas Y encantamientos (o nada: vainilla)
    disk.tapped = False
    idx = next((i for i, a in enumerate(c.activated_abilities)
                if a.get("tap") and a.get("cost") is not None and a["cost"].cmc == 1), None)
    if idx is None:
        return  # vanilla aceptable: sin habilidad, no destruye nada
    assert g.activate_ability(disk, idx)
    run(g)
    survivors = [v.name for v in victims if v in v.controller.battlefield]
    assert survivors == [], f"Disk debe destruir art/criaturas/encantamientos; quedan {survivors}"


# --------------------------------------------------------------------------- #
# 2. "target creature card from a graveyard" nunca toca el campo
# --------------------------------------------------------------------------- #

def test_corpus_disentomb():
    c = build("Disentomb", "{B}", "Sorcery",
              "Return target creature card from your graveyard to your hand.", ci=("B",))
    g, me, ops = new_game()
    give_lands(g, me, 1, (B,))
    x = put(g, creature("OppBeast", "3", 5, 5), ops[0])
    dead = creature("MyDead", "2", 2, 2)
    me.graveyard.append(dead)
    bot_cast(g, me, c)
    assert on_bf(ops[0], x) and x.card not in ops[0].hand, \
        "Disentomb no puede tocar el campo del rival"
    # (correct) devuelve la criatura del cementerio propio a la mano
    assert dead in me.hand and dead not in me.graveyard


DEATHRITE = ("{T}: Exile target land card from a graveyard. Add one mana of any color.\n"
             "{B}, {T}: Exile target instant or sorcery card from a graveyard. Each opponent loses 2 life.\n"
             "{G}, {T}: Exile target creature card from a graveyard. You gain 2 life.")


def test_corpus_deathrite_shaman():
    c = build("Deathrite Shaman", "{B/G}", "Creature — Elf Shaman", DEATHRITE, 1, 2,
              ci=("B", "G"), produced_mana=["B", "G", "R", "U", "W"])
    for i, ab in enumerate(c.activated_abilities):
        g, me, ops = new_game()
        give_lands(g, me, 2, (B, G))
        x = put(g, creature("OppDragon", "6", 6, 6), ops[0])
        ops[0].graveyard.append(creature("OppDead", "2", 2, 2))
        pm = put(g, c, me)
        pm.summoning_sick = False
        spec = ab.get("target_spec")
        tg = Policy()._spec_targets(g, me, spec, ab.get("target_count", 1)) if spec else []
        g.activate_ability(pm, i, targets=tg)
        run(g)
        assert on_bf(ops[0], x), \
            f"Deathrite «{ab.get('label')}» no puede exiliar una criatura en el campo"


KOLAGHAN = ("Choose two —\n"
            "• Return target creature card from your graveyard to your hand.\n"
            "• Target player discards a card.\n"
            "• Destroy target artifact.\n"
            "• Kolaghan's Command deals 2 damage to any target.")


def test_corpus_kolaghans_command():
    c = build("Kolaghan's Command", "{1}{B}{R}", "Instant", KOLAGHAN, ci=("B", "R"))
    for m in c.modes:
        if "graveyard" not in m.get("label", "").lower() and \
                "return" not in m.get("label", "").lower():
            continue
        g, me, ops = new_game()
        x = put(g, creature("OppBeast", "3", 5, 5), ops[0])
        me.graveyard.append(creature("MyDead", "2", 2, 2))
        spec = m.get("target_spec")
        tg = Policy()._spec_targets(g, me, spec, 1) if spec else []
        m["effect"](g, me, tg)
        run(g)
        assert on_bf(ops[0], x) and x.card not in ops[0].hand, \
            "Kolaghan's Command (modo cementerio) no puede sacar una criatura del campo rival"


# --------------------------------------------------------------------------- #
# 3. Bloodghast
# --------------------------------------------------------------------------- #

BLOODGHAST_TEXTS = [
    "Bloodghast can't block.\nBloodghast has haste as long as an opponent has 10 or less life.\n"
    "Landfall — Whenever a land you control enters, you may return Bloodghast from your graveyard to the battlefield.",
    "This creature can't block.\nThis creature has haste as long as an opponent has 10 or less life.\n"
    "Landfall — Whenever a land you control enters, you may return this card from your graveyard to the battlefield.",
]


@pytest.mark.parametrize("txt", BLOODGHAST_TEXTS, ids=["name", "this"])
def test_corpus_bloodghast(txt):
    mk = lambda: build("Bloodghast", "{B}{B}", "Creature — Vampire Spirit", txt, 2, 1,
                       ci=("B",))
    # (a) entrar no reanima a otras criaturas
    g, me, ops = new_game()
    big = creature("BigDead", "6", 8, 8)
    me.graveyard.append(big)
    put(g, mk(), me)
    assert big in me.graveyard and not on_bf(me, "BigDead")
    # (b) landfall con Bloodghast EN EL CAMPO no reanima nada
    g.play_land(me, land("Forest", [G], basic=True))
    run(g)
    assert big in me.graveyard and not on_bf(me, "BigDead"), \
        "landfall de Bloodghast reanimó otra criatura"
    # (c) Bloodghast en el cementerio + tierra -> vuelve Bloodghast (o nada), nunca otra
    g, me, ops = new_game()
    bg = mk()
    big = creature("BigDead", "6", 8, 8)
    me.graveyard.extend([big, bg])
    forest = land("Forest", [G], basic=True)
    me.hand.append(forest)
    g.play_land(me, forest)
    run(g)
    assert big in me.graveyard and not on_bf(me, "BigDead"), \
        "landfall reanimó a otra criatura en vez de Bloodghast"
    # (correct) Bloodghast vuelve al campo
    assert on_bf(me, "Bloodghast") and bg not in me.graveyard, \
        "Bloodghast debe volver del cementerio con landfall"


# --------------------------------------------------------------------------- #
# 4. Anthems condicionales / temporales
# --------------------------------------------------------------------------- #

def test_corpus_beastmaster_ascension():
    c = build("Beastmaster Ascension", "{2}{G}", "Enchantment",
              "Whenever a creature you control attacks, you may put a quest counter on Beastmaster Ascension.\n"
              "As long as Beastmaster Ascension has seven or more quest counters on it, creatures you control get +5/+5.",
              ci=("G",))
    g, me, ops = new_game()
    put(g, c, me)
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    assert (bear.power, bear.toughness) == (2, 2), "sin 7 contadores no hay +5/+5"


PURPHOROS = ("Indestructible\n"
             "As long as your devotion to red is less than five, Purphoros isn't a creature.\n"
             "Whenever another creature you control enters, Purphoros deals 2 damage to each opponent.\n"
             "{2}{R}: Creatures you control get +1/+0 until end of turn.")


def _purphoros():
    return build("Purphoros, God of the Forge", "{3}{R}",
                 "Legendary Enchantment Creature — God", PURPHOROS, 6, 5, ci=("R",),
                 keywords=["Indestructible"])


def test_corpus_purphoros_no_static_anthem():
    g, me, ops = new_game()
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    put(g, _purphoros(), me)
    assert bear.power == 2, "Purphoros sin activar no da +1/+0 permanente"


def test_corpus_goblin_bushwhacker():
    c = build("Goblin Bushwhacker", "{R}", "Creature — Goblin Warrior",
              "Kicker {R} (You may pay an additional {R} as you cast this spell.)\n"
              "When Goblin Bushwhacker enters, if it was kicked, creatures you control get +1/+0 and gain haste until end of turn.",
              1, 1, ci=("R",), keywords=["Kicker"])
    g, me, ops = new_game()
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    put(g, c, me)
    assert bear.power == 2 and not bear.has("haste"), "Bushwhacker sin kicker no da anthem"


def test_corpus_gideon_ally_of_zendikar():
    c = build("Gideon, Ally of Zendikar", "{2}{W}{W}", "Legendary Planeswalker — Gideon",
              "+1: Until end of turn, Gideon, Ally of Zendikar becomes a 5/5 Human Soldier Ally "
              "creature with indestructible that's still a planeswalker. Prevent all damage that "
              "would be dealt to him this turn.\n"
              "0: Create a 2/2 white Knight Ally creature token.\n"
              "−4: You get an emblem with \"Creatures you control get +1/+1.\"",
              ci=("W",), loyalty="4")
    g, me, ops = new_game()
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    put(g, c, me)
    assert (bear.power, bear.toughness) == (2, 2), "Gideon en el campo no da anthem"


def test_corpus_elspeth_suns_champion():
    c = build("Elspeth, Sun's Champion", "{4}{W}{W}", "Legendary Planeswalker — Elspeth",
              "+1: Create three 1/1 white Soldier creature tokens.\n"
              "−3: Destroy all creatures with power 4 or greater.\n"
              "−7: You get an emblem with \"Creatures you control get +2/+2 and have flying.\"",
              ci=("W",), loyalty="4")
    g, me, ops = new_game()
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    put(g, c, me)
    assert (bear.power, bear.toughness) == (2, 2) and not bear.has("flying"), \
        "Elspeth en el campo no da +2/+2 ni vuelo"


# --------------------------------------------------------------------------- #
# 5. Dragonmaster Outcast
# --------------------------------------------------------------------------- #

def test_corpus_dragonmaster_outcast():
    c = build("Dragonmaster Outcast", "{R}", "Creature — Human Shaman",
              "At the beginning of your upkeep, if you control six or more lands, "
              "create a 5/5 red Dragon creature token with flying.", 1, 1, ci=("R",))
    g, me, ops = new_game()
    put(g, c, me)
    for n in range(6):
        g.emit("upkeep", player=me)
        run(g)
        assert tokens(me) == [], f"con {n} tierras no crea Dragón"
        give_lands(g, me, 1)
    # 6 tierras: crea el Dragón 5/5 volador (vanilla aceptable: nada)
    g.emit("upkeep", player=me)
    run(g)
    toks = tokens(me)
    assert len(toks) <= 1
    for t in toks:
        assert (t.power, t.toughness) == (5, 5) and t.has("flying")


# --------------------------------------------------------------------------- #
# 6. Barridas "you don't control"
# --------------------------------------------------------------------------- #

def _board():
    g, me, ops = new_game()
    mine = [put(g, creature(f"m{i}", cmc, p, p), me) for i, (cmc, p) in enumerate([("1", 1), ("5", 5)])]
    theirs = [put(g, creature(f"o{i}", cmc, p, p), ops[0]) for i, (cmc, p) in enumerate([("1", 1), ("5", 5)])]
    return g, me, ops, mine, theirs


def test_corpus_plague_wind():
    c = build("Plague Wind", "{7}{B}{B}", "Sorcery",
              "Destroy all creatures you don't control. They can't be regenerated.", ci=("B",))
    g, me, ops, mine, theirs = _board()
    c.on_cast_resolve(g, me, [])
    run(g)
    assert all(on_bf(me, p) for p in mine), "Plague Wind no destruye las criaturas propias"
    assert not any(on_bf(ops[0], p) for p in theirs), "Plague Wind destruye las del rival"


def test_corpus_in_garruks_wake():
    c = build("In Garruk's Wake", "{7}{B}{B}", "Sorcery",
              "Destroy all creatures you don't control and all planeswalkers you don't control.",
              ci=("B",))
    g, me, ops, mine, theirs = _board()
    my_pw = put(g, cards.planeswalker("MyPW", "3", 3, (), ["W"]), me)
    op_pw = put(g, cards.planeswalker("OpPW", "3", 3, (), ["B"]), ops[0])
    c.on_cast_resolve(g, me, [])
    run(g)
    assert all(on_bf(me, p) for p in mine) and on_bf(me, my_pw), \
        "In Garruk's Wake no destruye lo propio"
    assert not any(on_bf(ops[0], p) for p in theirs) and not on_bf(ops[0], op_pw), \
        "In Garruk's Wake destruye criaturas y planeswalkers rivales"


def test_corpus_austere_command():
    c = build("Austere Command", "{4}{W}{W}", "Sorcery",
              "Choose two —\n• Destroy all artifacts.\n• Destroy all enchantments.\n"
              "• Destroy all creatures with mana value 3 or less.\n"
              "• Destroy all creatures with mana value 4 or greater.", ci=("W",))
    for m in c.modes:
        lab = m.get("label", "").lower()
        if "3 or less" in lab:
            g, me, ops, mine, theirs = _board()
            m["effect"](g, me, [])
            run(g)
            # vanilla aceptable, pero nunca destruir MV 5
            assert on_bf(me, mine[1]) and on_bf(ops[0], theirs[1]), \
                "modo 'MV 3 or less' destruyó una criatura de MV 5"
        if "4 or greater" in lab:
            g, me, ops, mine, theirs = _board()
            m["effect"](g, me, [])
            run(g)
            assert on_bf(me, mine[0]) and on_bf(ops[0], theirs[0]), \
                "modo 'MV 4 or greater' destruyó una criatura de MV 1"


# --------------------------------------------------------------------------- #
# 7. Ganar / perder la partida
# --------------------------------------------------------------------------- #

THASSA = ("When Thassa's Oracle enters, look at the top X cards of your library, where X is "
          "your devotion to blue. Put up to one of them on top of your library and the rest on "
          "the bottom of your library in any order. If X is greater than or equal to the number "
          "of cards in your library, you win the game. (Each {U} in the costs of permanents you "
          "control counts toward your devotion to blue.)")


def test_corpus_thassas_oracle():
    c = build("Thassa's Oracle", "{U}{U}", "Creature — Merfolk Wizard", THASSA, 1, 3, ci=("U",))
    g, me, ops = new_game()
    put(g, c, me)
    assert len(me.library) == 40
    assert nobody_lost(g), "Thassa's Oracle con 40 cartas en la biblioteca no gana"


def test_corpus_happily_ever_after():
    c = build("Happily Ever After", "{2}{W}", "Enchantment",
              "When Happily Ever After enters, each player gains 5 life and draws a card.\n"
              "At the beginning of your upkeep, if there are five colors among permanents you "
              "control, there are six or more card types among permanents you control and/or "
              "cards in your graveyard, and your life total is greater than or equal to your "
              "starting life total, you win the game.", ci=("W",))
    g, me, ops = new_game()
    put(g, c, me)
    assert nobody_lost(g), "Happily Ever After no gana al entrar"
    g.emit("upkeep", player=me)
    run(g)
    assert nobody_lost(g), "Happily Ever After sin 5 colores / 6 tipos no gana"


def test_corpus_approach_of_the_second_sun():
    c = build("Approach of the Second Sun", "{6}{W}", "Sorcery",
              "If this spell was cast from your hand and you've cast another spell named "
              "Approach of the Second Sun this game, you win the game. Otherwise, put Approach "
              "of the Second Sun into its owner's library seventh from the top and you gain 7 life.",
              ci=("W",))
    g, me, ops = new_game()
    c.on_cast_resolve(g, me, [])
    run(g)
    assert nobody_lost(g), "Approach lanzado una sola vez no gana"


def test_corpus_summoners_pact():
    c = build("Summoner's Pact", "{0}", "Instant",
              "Search your library for a green creature card, reveal it, put it into your hand, "
              "then shuffle.\nAt the beginning of your next upkeep, pay {G}{G}. If you don't, "
              "you lose the game.", ci=("G",))
    g, me, ops = new_game()
    me.library.insert(0, creature("GreenGuy", "2G", 3, 3))
    c.on_cast_resolve(g, me, [])
    run(g)
    assert not me.lost, "Summoner's Pact no hace perder al resolver"


def test_corpus_pact_of_the_titan():
    c = build("Pact of the Titan", "{0}", "Instant",
              "Create a 4/4 red Giant creature token.\nAt the beginning of your next upkeep, "
              "pay {4}{R}. If you don't, you lose the game.", ci=("R",))
    g, me, ops = new_game()
    c.on_cast_resolve(g, me, [])
    run(g)
    assert not me.lost, "Pact of the Titan no hace perder al resolver"


# --------------------------------------------------------------------------- #
# 8. Westvale Abbey
# --------------------------------------------------------------------------- #

def _westvale():
    d = {"name": "Westvale Abbey // Ormendahl, Profane Prince", "layout": "transform",
         "type_line": "Land // Legendary Creature — Demon", "mana_cost": "",
         "color_identity": [], "produced_mana": ["C"],
         "keywords": ["Flying", "Lifelink", "Indestructible", "Haste", "Transform"],
         "card_faces": [
             {"name": "Westvale Abbey", "type_line": "Land", "mana_cost": "",
              "oracle_text": "{T}: Add {C}.\n{5}, {T}, Pay 1 life: Create a 1/1 white and "
                             "black Human Cleric creature token.\n{5}, {T}, Sacrifice five "
                             "creatures: Transform Westvale Abbey, then untap it."},
             {"name": "Ormendahl, Profane Prince", "type_line": "Legendary Creature — Demon",
              "mana_cost": "", "oracle_text": "Flying, lifelink, indestructible, haste",
              "power": "9", "toughness": "7"}]}
    return cardsdb.build_card_from_data(d)


@pytest.mark.parametrize("n_creatures", [0, 2])
def test_corpus_westvale_abbey(n_creatures):
    c = _westvale()
    for i in range(len(c.activated_abilities)):
        g, me, ops = new_game()
        give_lands(g, me, 10, (C,))
        for k in range(n_creatures):
            put(g, creature(f"c{k}", "1", 1, 1), me)
        pm = put(g, c, me)
        g.activate_ability(pm, i)
        run(g)
        big = [p for p in me.battlefield if p.is_creature() and p.power >= 9]
        assert not big and pm.name != "Ormendahl, Profane Prince", \
            f"Westvale se transformó con {n_creatures} criaturas (habilidad {i})"


# --------------------------------------------------------------------------- #
# 9. Robo + pérdida de vida / tesoros
# --------------------------------------------------------------------------- #

def _resolve_spell(c, setup=None):
    g, me, ops = new_game()
    if setup:
        setup(g, me, ops)
    h0 = len(me.hand)
    c.on_cast_resolve(g, me, [])
    run(g)
    return g, me, ops, h0


def test_corpus_nights_whisper():
    c = build("Night's Whisper", "{1}{B}", "Sorcery",
              "You draw two cards and you lose 2 life.", ci=("B",))
    g, me, ops, h0 = _resolve_spell(c)
    assert len(me.hand) == h0 + 2 and me.life == 38


def test_corpus_read_the_bones():
    c = build("Read the Bones", "{2}{B}", "Sorcery",
              "Scry 2, then draw two cards. You lose 2 life.", ci=("B",))
    g, me, ops, h0 = _resolve_spell(c)
    assert len(me.hand) == h0 + 2 and me.life == 38


def test_corpus_vampiric_tutor():
    c = build("Vampiric Tutor", "{B}", "Instant",
              "Search your library for a card, then shuffle and put that card on top. "
              "You lose 2 life.", ci=("B",))

    def setup(g, me, ops):
        me.library.insert(0, creature("Bomb", "5G", 8, 8))   # al fondo
    g, me, ops, h0 = _resolve_spell(c, setup)
    assert me.life == 38
    assert len(me.hand) == h0, "Vampiric Tutor no pone la carta en la mano"
    assert me.library and me.library[-1].name == "Bomb", \
        "Vampiric Tutor debe buscar una carta y ponerla en el tope"


def test_corpus_unexpected_windfall():
    c = build("Unexpected Windfall", "{2}{R}{R}", "Instant",
              "As an additional cost to cast this spell, discard a card.\n"
              "Draw two cards and create two Treasure tokens.", ci=("R",))
    g, me, ops, h0 = _resolve_spell(c)
    assert len(me.hand) == h0 + 2
    assert len(tokens(me, "Treasure")) == 2


def test_corpus_deadly_dispute():
    c = build("Deadly Dispute", "{1}{B}", "Instant",
              "As an additional cost to cast this spell, sacrifice an artifact or creature.\n"
              "Draw two cards and create a Treasure token.", ci=("B",))
    g, me, ops, h0 = _resolve_spell(c)
    assert len(me.hand) == h0 + 2
    assert len(tokens(me, "Treasure")) == 1


# --------------------------------------------------------------------------- #
# 10. Kicker
# --------------------------------------------------------------------------- #

JOSU = ("Kicker {5}{B} (You may pay an additional {5}{B} as you cast this spell.)\n"
        "Menace (This creature can't be blocked except by two or more creatures.)\n"
        "When Josu Vess, Lich Knight enters, if it was kicked, create eight 2/2 black Zombie "
        "Knight creature tokens with menace.")


def test_corpus_josu_vess_lich_knight():
    mk = lambda: build("Josu Vess, Lich Knight", "{2}{B}{B}",
                       "Legendary Creature — Zombie Knight", JOSU, 4, 5, ci=("B",),
                       keywords=["Kicker", "Menace"])
    # entra sin kicker (directo)
    g, me, ops = new_game()
    put(g, mk(), me)
    assert tokens(me) == [], "Josu sin kicker no crea Zombies"
    # lanzado con maná justo (kicker impagable)
    g, me, ops = new_game()
    give_lands(g, me, 4, (B,))
    assert bot_cast(g, me, mk())
    assert on_bf(me, "Josu Vess, Lich Knight")
    assert tokens(me) == [], "Josu lanzado sin kicker no crea Zombies"


def test_corpus_goblin_ruinblaster():
    c = build("Goblin Ruinblaster", "{2}{R}", "Creature — Goblin Shaman",
              "Kicker {R} (You may pay an additional {R} as you cast this spell.)\nHaste\n"
              "When Goblin Ruinblaster enters, if it was kicked, destroy target nonbasic land.",
              4, 1, ci=("R",), keywords=["Kicker", "Haste"])
    g, me, ops = new_game()
    nb = put(g, land("Volcanic Island", [U, R]), ops[0])
    put(g, c, me)
    assert on_bf(ops[0], nb), "Ruinblaster sin kicker no destruye tierras"


# --------------------------------------------------------------------------- #
# 11. Maná / rituales
# --------------------------------------------------------------------------- #

def test_corpus_cabal_ritual():
    c = build("Cabal Ritual", "{1}{B}", "Instant",
              "Add {B}{B}{B}.\nThreshold — Add {B}{B}{B}{B}{B} instead if seven or more cards "
              "are in your graveyard.", ci=("B",))
    g, me, ops = new_game()
    c.on_cast_resolve(g, me, [])
    run(g)
    assert me.mana_pool == 3, f"Cabal Ritual sin threshold agrega 3 (agregó {me.mana_pool})"
    # con threshold: 5 (vanilla aceptable: 3), nunca la suma de ambas
    g, me, ops = new_game()
    me.graveyard = [land("Forest", [G], basic=True) for _ in range(7)]
    c.on_cast_resolve(g, me, [])
    run(g)
    assert me.mana_pool in (3, 5), f"Cabal Ritual con threshold agregó {me.mana_pool}"


DOCKSIDE_TEXTS = [
    "When Dockside Extortionist enters, create X Treasure tokens, where X is the number of "
    "artifacts and enchantments your opponents control. (Treasure tokens are artifacts with "
    "\"{T}, Sacrifice this artifact: Add one mana of any color.\")",
    "When this creature enters, create X Treasure tokens, where X is the number of artifacts "
    "and enchantments your opponents control. (Treasure tokens are artifacts with \"{T}, "
    "Sacrifice this token: Add one mana of any color.\")",
]


@pytest.mark.parametrize("txt", DOCKSIDE_TEXTS, ids=["name", "this"])
def test_corpus_dockside_extortionist(txt):
    c = build("Dockside Extortionist", "{1}{R}", "Creature — Goblin Pirate", txt, 1, 2,
              ci=("R",))
    g, me, ops = new_game()
    put(g, artifact("A1"), ops[0])
    put(g, artifact("A2"), ops[0])
    put(g, c, me)
    assert len(tokens(me, "Treasure")) == 2
    assert me.mana_pool == 0, "Dockside no agrega maná flotante"


def test_corpus_llanowar_visionary():
    c = build("Llanowar Visionary", "{2}{G}", "Creature — Elf Druid",
              "When Llanowar Visionary enters, draw a card.\n{T}: Add {G}.", 2, 2, ci=("G",),
              produced_mana=["G"])
    g, me, ops = new_game()
    h0 = len(me.hand)
    put(g, c, me)
    assert len(me.hand) == h0 + 1
    assert me.mana_pool == 0, "Llanowar Visionary no agrega maná flotante al entrar"


def test_corpus_gilded_goose():
    c = build("Gilded Goose", "{G}", "Creature — Bird",
              "Flying\nWhen Gilded Goose enters, create a Food token. (It's an artifact with "
              "\"{2}, {T}, Sacrifice this artifact: You gain 3 life.\")\n"
              "{1}{G}, {T}: Create a Food token.\n{T}, Sacrifice a Food: Add one mana of any color.",
              0, 2, ci=("G",), keywords=["Flying"], produced_mana=["B", "G", "R", "U", "W"])
    g, me, ops = new_game()
    put(g, c, me)
    assert me.mana_pool == 0, "Gilded Goose no agrega maná flotante al entrar"
    assert len(tokens(me, "Food")) <= 1   # vanilla aceptable: 0 Food


# --------------------------------------------------------------------------- #
# 12. "another creature" / "an opponent controls"
# --------------------------------------------------------------------------- #

def test_corpus_soul_warden():
    c = build("Soul Warden", "{W}", "Creature — Human Cleric",
              "Whenever another creature enters, you gain 1 life.", 1, 1, ci=("W",))
    g, me, ops = new_game()
    put(g, c, me)
    assert me.life == 40, "Soul Warden no se cuenta a sí misma"
    put(g, creature("Bear", "1G", 2, 2), me)
    assert me.life == 41


def test_corpus_purphoros_alone():
    g, me, ops = new_game()
    put(g, _purphoros(), me)
    assert ops[0].life == 40, "Purphoros entrando solo no hace daño"


def test_corpus_authority_of_the_consuls():
    c = build("Authority of the Consuls", "{W}", "Enchantment",
              "Creatures your opponents control enter tapped.\n"
              "Whenever a creature an opponent controls enters, you gain 1 life.", ci=("W",))
    g, me, ops = new_game()
    put(g, c, me)
    put(g, creature("Mine", "2", 2, 2), me)
    assert me.life == 40, "Authority no da vida por criaturas propias"


# --------------------------------------------------------------------------- #
# 13. Daño a criaturas (no a jugadores / no a la propia)
# --------------------------------------------------------------------------- #

CHANDRA = ("+1: Exile the top card of your library. You may cast that card. If you don't, "
           "Chandra, Torch of Defiance deals 2 damage to each opponent.\n"
           "+1: Add {R}{R}.\n"
           "−3: Chandra, Torch of Defiance deals 4 damage to target creature.\n"
           "−7: You get an emblem with \"Whenever you cast a spell, this emblem deals 5 damage "
           "to any target.\"")


def test_corpus_chandra_torch_of_defiance_minus3():
    c = build("Chandra, Torch of Defiance", "{2}{R}{R}", "Legendary Planeswalker — Chandra",
              CHANDRA, ci=("R",), loyalty="4")
    g, me, ops = new_game()
    x = put(g, creature("OppBeast", "4", 5, 4), ops[0])
    pm = put(g, c, me)
    idx = next((i for i, (cost, _e) in enumerate(c.loyalty_abilities) if cost == -3), None)
    if idx is not None:
        g.activate_loyalty(pm, idx)
        run(g)
        assert not on_bf(ops[0], x), "−3 hace 4 de daño a la criatura (5/4 muere)"
    assert me.life == 40 and ops[0].life == 40, "−3 no hace perder vida a ningún jugador"


def test_corpus_rabid_bite():
    c = build("Rabid Bite", "{1}{G}", "Sorcery",
              "Target creature you control deals damage equal to its power to target creature "
              "or planeswalker you don't control.", ci=("G",))
    g, me, ops = new_game()
    give_lands(g, me, 2, (G,))
    mine = put(g, creature("MyBear", "2", 3, 3), me)
    put(g, creature("OppOgre", "3", 3, 4), ops[0])
    bot_cast(g, me, c)
    assert on_bf(me, mine) and mine.damage == 0, "Rabid Bite no daña a tu criatura"


# --------------------------------------------------------------------------- #
# 14. Filtros de disparos
# --------------------------------------------------------------------------- #

def test_corpus_grim_haruspex():
    c = build("Grim Haruspex", "{2}{B}", "Creature — Human Wizard",
              "Morph {B} (You may cast this card face down as a 2/2 creature for {3}. Turn it "
              "face up any time for its morph cost.)\nWhenever another nontoken creature you "
              "control dies, draw a card.", 3, 2, ci=("B",), keywords=["Morph"])
    g, me, ops = new_game()
    put(g, c, me)
    tok = cards.make_token(g, me, "Zombie", 2, 2)
    run(g)
    h0 = len(me.hand)
    g.destroy(tok)
    run(g)
    assert len(me.hand) == h0, "una ficha que muere no roba"
    v = put(g, creature("Vic", "1", 1, 1), me)
    g.destroy(v)
    run(g)
    assert len(me.hand) == h0 + 1, "una criatura no-ficha que muere roba 1"


def test_corpus_mystic_remora():
    c = build("Mystic Remora", "{U}", "Enchantment",
              "Cumulative upkeep {1} (At the beginning of your upkeep, put an age counter on "
              "this permanent, then sacrifice it unless you pay its upkeep cost for each age "
              "counter on it.)\nWhenever an opponent casts a noncreature spell, you may draw a "
              "card unless that player pays {4}.", ci=("U",), keywords=["Cumulative upkeep"])
    g, me, ops = new_game()
    put(g, c, me)
    give_lands(g, ops[0], 2, (G,))
    h0 = len(me.hand)
    bot_cast(g, ops[0], creature("Bear", "1G", 2, 2))
    assert on_bf(ops[0], "Bear")
    assert len(me.hand) == h0, "Remora no roba por un hechizo de criatura"


def test_corpus_lys_alana_huntmaster():
    c = build("Lys Alana Huntmaster", "{2}{G}{G}", "Creature — Elf Warrior",
              "Whenever you cast an Elf spell, you may create a 1/1 green Elf Warrior creature token.",
              3, 3, ci=("G",))
    g, me, ops = new_game()
    put(g, c, me)
    give_lands(g, me, 2, (G,))
    bot_cast(g, me, creature("Bear", "1G", 2, 2, subtypes=("Bear",)))
    assert on_bf(me, "Bear")
    assert tokens(me) == [], "un hechizo no-Elfo no crea fichas"


def test_corpus_alandra_sky_dreamer():
    c = build("Alandra, Sky Dreamer", "{2}{U}{U}", "Legendary Creature — Merfolk Wizard",
              "Whenever you draw your second card each turn, create a 2/2 blue Drake creature "
              "token with flying.\nWhenever you draw your fifth card each turn, Drakes you "
              "control and Alandra, Sky Dreamer each get +X/+X until end of turn, where X is "
              "the number of cards in your hand.", 2, 4, ci=("U",))
    g, me, ops = new_game()
    put(g, c, me)
    me.draws_this_turn = 0
    me.draw(1, g)
    run(g)
    assert tokens(me) == [], "el primer robo del turno no crea Drake"


# --------------------------------------------------------------------------- #
# 15. Persist / undying falsos
# --------------------------------------------------------------------------- #

def test_corpus_persistent_petitioners():
    c = build("Persistent Petitioners", "{1}{U}", "Creature — Human Advisor",
              "{1}, {T}: Target player mills a card.\nTap four untapped Advisors you control: "
              "Target player mills twelve cards.\nA deck can have any number of cards named "
              "Persistent Petitioners.", 1, 3, ci=("U",))
    g, me, ops = new_game()
    pm = put(g, c, me)
    g.destroy(pm)
    run(g)
    assert not on_bf(me, "Persistent Petitioners") and c in me.graveyard, \
        "Persistent Petitioners no tiene persist"


def test_corpus_mikaeus_the_unhallowed():
    c = build("Mikaeus, the Unhallowed", "{3}{B}{B}{B}", "Legendary Creature — Zombie Cleric",
              "Intimidate\nWhenever a Human deals damage to you, destroy it.\nOther non-Human "
              "creatures you control get +1/+1 and have undying. (When this creature dies, if it "
              "had no +1/+1 counters on it, return it to the battlefield under its owner's "
              "control with a +1/+1 counter on it.)", 5, 5, ci=("B",), keywords=["Intimidate"])
    g, me, ops = new_game()
    pm = put(g, c, me)
    g.destroy(pm)
    run(g)
    assert not on_bf(me, "Mikaeus, the Unhallowed") and c in me.graveyard, \
        "Mikaeus no tiene undying él mismo"


# --------------------------------------------------------------------------- #
# 16. Costes / P/T variables
# --------------------------------------------------------------------------- #

def test_corpus_thought_knot_seer():
    c = build("Thought-Knot Seer", "{3}{C}", "Creature — Eldrazi",
              "When Thought-Knot Seer enters, target opponent reveals their hand. You choose a "
              "nonland card from it and exile that card.\nWhen Thought-Knot Seer leaves the "
              "battlefield, target opponent draws a card.", 4, 4)
    assert c.cost.cmc == 4
    assert c.cost.generic == 3 and "C" in c.cost.pips, f"coste mal parseado: {c.cost}"


def test_corpus_tarmogoyf():
    c = build("Tarmogoyf", "{1}{G}", "Creature — Lhurgoyf",
              "Tarmogoyf's power is equal to the number of card types among cards in all "
              "graveyards and its toughness is equal to that number plus 1.", "*", "1+*",
              ci=("G",))
    g, me, ops = new_game()
    put(g, c, me)
    assert on_bf(me, "Tarmogoyf"), "Tarmogoyf (0/1) no muere con cementerios vacíos"


# --------------------------------------------------------------------------- #
# 17. ETB que crean / devuelven
# --------------------------------------------------------------------------- #

GRAVE_TITAN_TEXTS = [
    "Deathtouch\nWhenever Grave Titan enters or attacks, create two 2/2 black Zombie creature tokens.",
    "Deathtouch\nWhenever this creature enters or attacks, create two 2/2 black Zombie creature tokens.",
]


@pytest.mark.parametrize("txt", GRAVE_TITAN_TEXTS, ids=["name", "this"])
def test_corpus_grave_titan(txt):
    c = build("Grave Titan", "{4}{B}{B}", "Creature — Giant", txt, 6, 6, ci=("B",),
              keywords=["Deathtouch"])
    g, me, ops = new_game()
    put(g, c, me)
    assert len(tokens(me)) == 2, f"Grave Titan crea 2 Zombies (creó {len(tokens(me))})"


def test_corpus_sun_titan():
    c = build("Sun Titan", "{4}{W}{W}", "Creature — Giant",
              "Vigilance\nWhenever Sun Titan enters or attacks, you may return target permanent "
              "card with mana value 3 or less from your graveyard to the battlefield.", 6, 6,
              ci=("W",), keywords=["Vigilance"])
    g, me, ops = new_game()
    me.graveyard = [creature("Bear", "1G", 2, 2), creature("Bear2", "1G", 2, 2)]
    put(g, c, me)
    returned = [p for p in me.battlefield if p.name in ("Bear", "Bear2")]
    assert len(returned) <= 1, "Sun Titan devuelve como mucho 1 carta"


def test_corpus_scute_swarm():
    c = build("Scute Swarm", "{2}{G}", "Creature — Insect",
              "Landfall — Whenever a land you control enters, create a 1/1 green Insect creature "
              "token. If you control six or more lands, create a token that's a copy of Scute "
              "Swarm instead.", 1, 1, ci=("G",))
    g, me, ops = new_game()
    put(g, c, me)
    assert tokens(me) == [], "Scute Swarm entrando no crea fichas"


BALLISTA_TEXTS = [
    "Walking Ballista enters with X +1/+1 counters on it.\n{4}: Put a +1/+1 counter on Walking "
    "Ballista.\nRemove a +1/+1 counter from Walking Ballista: It deals 1 damage to any target.",
    "This creature enters with X +1/+1 counters on it.\n{4}: Put a +1/+1 counter on this "
    "creature.\nRemove a +1/+1 counter from this creature: It deals 1 damage to any target.",
]


@pytest.mark.parametrize("txt", BALLISTA_TEXTS, ids=["name", "this"])
def test_corpus_walking_ballista(txt):
    c = build("Walking Ballista", "{X}{X}", "Artifact Creature — Construct", txt, 0, 0)
    g, me, ops = new_game()
    v = put(g, creature("OppElf", "1", 1, 1), ops[0])
    g.spell_x = 0
    put(g, c, me)
    assert me.life == 40 and ops[0].life == 40, "Ballista X=0 no hace daño"
    assert on_bf(ops[0], v) and v.damage == 0


# --------------------------------------------------------------------------- #
# 18. Modificadores de coste
# --------------------------------------------------------------------------- #

def test_corpus_goblin_warchief():
    c = build("Goblin Warchief", "{1}{R}{R}", "Creature — Goblin Warrior",
              "Goblin spells you cast cost {1} less to cast.\nGoblins you control have haste.",
              2, 2, ci=("R",))
    g, me, ops = new_game()
    put(g, c, me)
    elf = creature("Big Elf", "5G", 5, 5, subtypes=("Elf",))
    opt = build("Opt", "{U}", "Instant", "Scry 1.\nDraw a card.", ci=("U",))
    assert g._static_cost_reduction(me, elf) == 0, "Warchief no abarata no-Goblins"
    assert g._static_cost_reduction(me, opt) == 0


def test_corpus_aura_of_silence():
    c = build("Aura of Silence", "{1}{W}{W}", "Enchantment",
              "Artifact and enchantment spells your opponents cast cost {2} more to cast.\n"
              "Sacrifice Aura of Silence: Destroy target artifact or enchantment.", ci=("W",))
    g, me, ops = new_game()
    put(g, c, me)
    bear = creature("Bear", "1G", 2, 2)
    bolt = build("Lightning Bolt", "{R}", "Instant",
                 "Lightning Bolt deals 3 damage to any target.", ci=("R",))
    assert g._static_cost_increase(ops[0], bear) == 0, "Aura no encarece criaturas"
    assert g._static_cost_increase(ops[0], bolt) == 0, "Aura no encarece instantáneos"


# --------------------------------------------------------------------------- #
# 19. Varios
# --------------------------------------------------------------------------- #

def test_corpus_anafenza_the_foremost():
    c = build("Anafenza, the Foremost", "{W}{B}{G}", "Legendary Creature — Human Soldier",
              "Whenever Anafenza, the Foremost attacks, put a +1/+1 counter on another target "
              "tapped creature you control.\nIf a nontoken creature an opponent owns would die "
              "or a creature card not on the battlefield would be put into an opponent's "
              "graveyard, exile that card instead.", 4, 4, ci=("W", "B", "G"))
    g, me, ops = new_game()
    put(g, c, me)
    v = put(g, creature("MyGuy", "2", 2, 2), me)
    g.destroy(v)
    run(g)
    assert v.card in me.graveyard and v.card not in me.exile, \
        "Anafenza no exilia tus propias criaturas"


def test_corpus_glimpse_the_unthinkable():
    c = build("Glimpse the Unthinkable", "{U}{B}", "Sorcery", "Target player mills ten cards.",
              ci=("U", "B"))
    g, me, ops = new_game()
    give_lands(g, me, 2, (U, B))
    bot_cast(g, me, c)
    assert len(me.library) == 40, "Glimpse no muele al lanzador"
    assert len(ops[0].library) in (30, 40)   # vanilla aceptable: no muele a nadie


def test_corpus_thought_scour():
    c = build("Thought Scour", "{U}", "Instant", "Target player mills two cards.\nDraw a card.",
              ci=("U",))
    g, me, ops, h0 = _resolve_spell(c)
    assert len(me.hand) == h0 + 1


def test_corpus_vampire_spawn():
    for txt in ("When Vampire Spawn enters, each opponent loses 2 life and you gain 2 life.",
                "When this creature enters, each opponent loses 2 life and you gain 2 life."):
        c = build("Vampire Spawn", "{2}{B}", "Creature — Vampire", txt, 2, 3, ci=("B",))
        g, me, ops = new_game(3)
        put(g, c, me)
        assert me.life == 42, f"Vampire Spawn gana exactamente 2 (vida {me.life})"
        assert [o.life for o in ops] == [38, 38, 38]


# --------------------------------------------------------------------------- #
# 20. Sower of Temptation
# --------------------------------------------------------------------------- #

def test_corpus_sower_of_temptation():
    c = build("Sower of Temptation", "{2}{U}{U}", "Creature — Faerie Wizard",
              "Flying\nWhen Sower of Temptation enters, gain control of target creature for as "
              "long as Sower of Temptation remains on the battlefield.", 2, 2, ci=("U",),
              keywords=["Flying"])
    g, me, ops = new_game()
    big = put(g, creature("Big", "3G", 5, 5), ops[0])
    big.tapped = True
    big.summoning_sick = True
    sower = put(g, c, me)
    assert big.tapped, "robar el control no endereza"
    assert not big.has("haste"), "robar el control no da prisa"
    g.destroy(sower)
    run(g)
    assert big.controller is ops[0] and big in ops[0].battlefield \
        and big not in me.battlefield, "al irse Sower, la criatura vuelve a su dueño"


# --------------------------------------------------------------------------- #
# 21. Mecánicas por subcadena
# --------------------------------------------------------------------------- #

YIDRIS_TEXTS = [
    "Trample\nWhenever Yidris, Maelstrom Wielder deals combat damage to a player, until end of "
    "turn, spells you cast from your hand have cascade. (When you cast the spell, exile cards "
    "from the top of your library until you exile a nonland card that costs less. You may cast "
    "it without paying its mana cost. Put the exiled cards on the bottom of your library in a "
    "random order.)",
    "Trample\nWhenever Yidris, Maelstrom Wielder deals combat damage to a player, until end of "
    "turn, whenever you cast a spell from your hand, it gains cascade until end of turn. (When "
    "you cast the spell, exile cards from the top of your library until you exile a nonland card "
    "that costs less. You may cast it without paying its mana cost. Put the exiled cards on the "
    "bottom of your library in a random order.)",
]


@pytest.mark.parametrize("txt", YIDRIS_TEXTS, ids=["have", "gains"])
def test_corpus_yidris_maelstrom_wielder(txt):
    mk = lambda: build("Yidris, Maelstrom Wielder", "{U}{B}{R}{G}",
                       "Legendary Creature — Ogre Wizard", txt, 5, 5, ci=("U", "B", "R", "G"),
                       keywords=["Trample"])

    def lib():
        return ([land("Forest", [G], basic=True) for _ in range(5)]
                + [creature("Cheap", "2G", 3, 3)]
                + [land("Forest", [G], basic=True) for _ in range(2)])
    # entrar
    g, me, ops = new_game()
    me.library = lib()
    put(g, mk(), me)
    assert not on_bf(me, "Cheap") and len(me.library) == 8, "Yidris entrando no hace cascade"
    # lanzado desde la mano
    g, me, ops = new_game()
    give_lands(g, me, 4, (W, U, B, R, G))
    me.library = lib()
    bot_cast(g, me, mk())
    assert on_bf(me, "Yidris, Maelstrom Wielder")
    assert not on_bf(me, "Cheap") and len(me.library) == 8, "Yidris no tiene cascade él mismo"


def test_corpus_lightning_storm():
    c = build("Lightning Storm", "{1}{R}{R}", "Instant",
              "Lightning Storm deals X damage to any target, where X is 3 plus the number of "
              "charge counters on it.\nDiscard a land card: Put two charge counters on Lightning "
              "Storm. You may choose a new target for it. Any player may activate this ability "
              "but only while Lightning Storm is on the stack.", ci=("R",))
    g, me, ops = new_game()
    give_lands(g, me, 3, (R,))
    g.spells_this_turn = 3
    bot_cast(g, me, c)
    assert me.life == 40
    assert ops[0].life == 37, f"Lightning Storm hace 3 (sin storm); rival a {ops[0].life}"


def test_corpus_whirler_rogue():
    c = build("Whirler Rogue", "{2}{U}{U}", "Creature — Human Rogue Artificer",
              "When Whirler Rogue enters, create two 1/1 colorless Thopter artifact creature "
              "tokens with flying.\nTap two untapped artifacts you control: Target creature "
              "can't be blocked this turn.", 2, 2, ci=("U",))
    g, me, ops = new_game()
    pm = put(g, c, me)
    assert "unblockable" not in c.keywords and not pm.has("unblockable"), \
        "Whirler Rogue no es imbloqueable por sí misma"


# --------------------------------------------------------------------------- #
# 22. Fuentes de varios manás
# --------------------------------------------------------------------------- #

def _produces(c):
    g, me, ops = new_game()
    pm = put(g, c, me)
    assert c.produces is not None, f"{c.name} debe producir maná"
    return c.produces(pm, me) or {}


def test_corpus_hedron_archive():
    c = build("Hedron Archive", "{4}", "Artifact",
              "{T}: Add {C}{C}.\n{2}, {T}, Sacrifice Hedron Archive: Draw two cards.",
              produced_mana=["C"])
    assert _produces(c) == {"C": 2}


def test_corpus_thran_dynamo():
    c = build("Thran Dynamo", "{4}", "Artifact", "{T}: Add {C}{C}{C}.", produced_mana=["C"])
    assert _produces(c) == {"C": 3}


def test_corpus_ancient_tomb():
    c = build("Ancient Tomb", "", "Land",
              "{T}: Add {C}{C}. Ancient Tomb deals 2 damage to you.", produced_mana=["C"])
    assert _produces(c) == {"C": 2}


def test_corpus_gilded_lotus():
    c = build("Gilded Lotus", "{5}", "Artifact", "{T}: Add three mana of any one color.",
              produced_mana=["B", "G", "R", "U", "W"])
    opts = _produces(c)
    assert opts and max(opts.values()) == 3, f"Gilded Lotus da 3 maná: {opts}"


# --------------------------------------------------------------------------- #
# 23. "Whenever a creature enters under your control" no se dispara a sí mismo
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("txt", [
    "Whenever a creature enters the battlefield under your control, scry 1.",
    "Whenever a creature you control enters, scry 1.",
], ids=["old", "new"])
def test_corpus_watcher_enchantment_scry(txt):
    # carta de prueba (no real) con el patrón de texto "watcher"
    c = build("Corpus Watcher", "{1}{U}", "Enchantment", txt, ci=("U",))
    g, me, ops = new_game()
    start = len(g.log_lines)
    put(g, c, me)
    assert g.pending_choice is None and not scry_logged(g, start), \
        "un encantamiento entrando no dispara 'whenever a creature enters'"


def test_corpus_primary_research_end_step_condition():
    # condición "if a card left your graveyard this turn": antes se ignoraba (robaba
    # siempre); con el parser nuevo una condición desconocida no se cablea, así que
    # se agregó el soporte para que el disparo siga existiendo y sea fiel
    import cards as _cards
    c = build("Primary Research", "{3}{U}", "Enchantment",
              "When this enchantment enters, return target nonland permanent card with "
              "mana value 3 or less from your graveyard to the battlefield.\nAt the "
              "beginning of your end step, if a card left your graveyard this turn, draw "
              "a card.", ci=("U",))
    g, me, ops = new_game()
    g.turn = 1; g.active_index = 0
    put(g, c, me)
    h = len(me.hand); g.end_turn(me)
    assert len(me.hand) == h                     # nada salió del cementerio
    g.turn = 3
    me.graveyard.append(_cards.creature("Z", "1", 1, 1))
    _cards.reanimate(g, me, me.graveyard[-1]); run(g)
    h = len(me.hand); g.end_turn(me)
    assert len(me.hand) == h + 1


# --------------------------------------------------------------------------- #
# COPIAS de criaturas (clones, fichas copia)
# --------------------------------------------------------------------------- #

CLONE_TXT = "You may have this creature enter as a copy of any creature on the battlefield."
SPARK_TXT = ("You may have this creature enter as a copy of a creature or planeswalker you "
             "control, except it enters with an additional +1/+1 counter on it if it's a "
             "creature, it enters with an additional loyalty counter on it if it's a "
             "planeswalker, and it isn't legendary.")
KIKI_TXT = ("Haste\n{T}: Create a token that's a copy of target nonlegendary creature you "
            "control, except it has haste. Sacrifice it at the beginning of the next end step.")
HELM_TXT = ("At the beginning of combat on your turn, create a token that's a copy of equipped "
            "creature, except the token isn't legendary. That token gains haste.\nEquip {5}")


def _etb_draw_creature(name="Wall of Omens"):
    c = creature(name, "1W", 0, 4)
    c.on_etb = lambda g, ctrl, perm: ctrl.draw(1, g)
    return c


def test_corpus_clone_copies_best_creature_and_its_etb():
    g, me, ops = new_game()
    put(g, creature("Big Beast", "4G", 6, 6), ops[0])
    put(g, _etb_draw_creature(), me)
    pm = put(g, build("Clone", "{3}{U}", "Creature — Shapeshifter", CLONE_TXT, 0, 0), me)
    assert on_bf(me, pm) and pm.name == "Big Beast" and (pm.power, pm.toughness) == (6, 6)
    h0 = len(me.hand)
    g2, me2, ops2 = new_game()
    put(g2, _etb_draw_creature(), me2)
    h0 = len(me2.hand)
    pm2 = put(g2, build("Clone", "{3}{U}", "Creature — Shapeshifter", CLONE_TXT, 0, 0), me2)
    assert pm2.name == "Wall of Omens" and len(me2.hand) == h0 + 1, \
        "el clon resuelve el ETB de lo copiado"


def test_corpus_clone_alone_dies_as_0_0():
    g, me, ops = new_game()
    pm = put(g, build("Clone", "{3}{U}", "Creature — Shapeshifter", CLONE_TXT, 0, 0), me)
    assert not on_bf(me, pm)


def test_corpus_spark_double_own_nonlegendary_plus_counter():
    g, me, ops = new_game()
    put(g, creature("Big Beast", "4G", 6, 6), ops[0])
    leg = put(g, creature("Hero", "2G", 3, 3, legendary=True), me)
    pm = put(g, build("Spark Double", "{3}{U}", "Creature — Illusion", SPARK_TXT, 0, 0), me)
    assert pm.name == "Hero" and (pm.power, pm.toughness) == (4, 4)
    assert "legendary" not in pm.card.supertypes
    assert on_bf(me, leg) and on_bf(me, pm), "no muere por la regla de legendarios"


def test_corpus_kiki_jiki_copy_with_haste_sacrificed_at_end():
    g, me, ops = new_game()
    kiki = put(g, build("Kiki-Jiki, Mirror Breaker", "{2}{R}{R}{R}",
                        "Legendary Creature — Goblin Shaman", KIKI_TXT, 2, 2,
                        keywords=["Haste"]), me)
    kiki.summoning_sick = False
    put(g, _etb_draw_creature("Elf Seer"), me)
    h0 = len(me.hand)
    ab = kiki.card.activated_abilities[0]
    assert ab["target_spec"] == "own_creature"
    assert g.activate_ability(kiki, 0, targets=[kiki])   # objetivo ilegal (legendaria)
    run(g)
    toks = tokens(me, "Elf Seer")
    assert len(toks) == 1 and len(me.hand) == h0 + 1, "copia la no legendaria + su ETB"
    assert not toks[0].summoning_sick and toks[0].has("haste")
    assert not tokens(me, "Kiki-Jiki, Mirror Breaker")
    g.end_turn(me)
    assert not tokens(me, "Elf Seer"), "la ficha se sacrifica al final del turno"


def test_corpus_helm_of_the_host_copies_equipped_each_combat():
    g, me, ops = new_game()
    hero = put(g, creature("Hero", "2G", 3, 3, legendary=True), me)
    helm = put(g, build("Helm of the Host", "{4}", "Legendary Artifact — Equipment", HELM_TXT), me)
    helm.enchanting = hero
    g.emit("begin_combat", player=me)
    run(g)
    toks = tokens(me, "Hero")
    assert len(toks) == 1 and "legendary" not in toks[0].card.supertypes
    assert on_bf(me, hero), "el original sigue (la copia no es legendaria)"


def test_corpus_helm_unattached_does_nothing():
    g, me, ops = new_game()
    put(g, creature("Hero", "2G", 3, 3), me)
    put(g, build("Helm of the Host", "{4}", "Legendary Artifact — Equipment", HELM_TXT), me)
    g.emit("begin_combat", player=me)
    run(g)
    assert not tokens(me)


def test_corpus_copy_trigger_that_creature_nontoken():
    g, me, ops = new_game()
    put(g, build("Mirror Thing", "{3}{U}", "Creature — Shapeshifter",
                 "Whenever another nontoken creature you control enters, create a token "
                 "that's a copy of that creature.", 2, 2), me)
    put(g, creature("Bear", "1G", 2, 2), me)
    assert len(tokens(me, "Bear")) == 1, "copia la que entró y NO se copia la ficha"
    put(g, creature("Orc", "1B", 2, 2), ops[0])
    assert not tokens(me, "Orc") and not tokens(ops[0])


def test_corpus_cackling_counterpart_copies_own_creature():
    g, me, ops = new_game()
    put(g, creature("Big Beast", "4G", 6, 6), ops[0])
    put(g, creature("Bear", "1G", 2, 2), me)
    give_lands(g, me, 3, colors=(U,))
    cc = build("Cackling Counterpart", "{1}{U}{U}", "Instant",
               "Create a token that's a copy of target creature you control.\n"
               "Flashback {5}{U}{U}", ci=("U",))
    assert cc.target_spec == "own_creature"
    assert bot_cast(g, me, cc)
    assert len(tokens(me, "Bear")) == 1 and not tokens(me, "Big Beast")


def test_corpus_clone_human_choice_survives_until_chosen():
    g, me, ops = new_game()
    put(g, creature("Big Beast", "4G", 6, 6), ops[0])
    put(g, creature("Bear", "1G", 2, 2), me)
    g.interactive_human = me
    pm = put(g, build("Clone", "{3}{U}", "Creature — Shapeshifter", CLONE_TXT, 0, 0), me)
    ch = g.pending_choice
    assert ch and on_bf(me, pm), "el clon espera la elección sin morir por SBA"
    idx = next(o["i"] for o in ch["options"] if o["name"].startswith("Bear"))
    g.pending_choice = None
    ch["_apply"](idx)
    run(g)
    assert on_bf(me, pm) and pm.name == "Bear" and (pm.power, pm.toughness) == (2, 2)


def test_corpus_clone_human_declines_dies():
    g, me, ops = new_game()
    put(g, creature("Bear", "1G", 2, 2), me)
    g.interactive_human = me
    pm = put(g, build("Clone", "{3}{U}", "Creature — Shapeshifter", CLONE_TXT, 0, 0), me)
    ch = g.pending_choice
    g.pending_choice = None
    ch["_apply"](None)
    run(g)
    assert not on_bf(me, pm)


def test_corpus_attack_trigger_copy_of_self():
    g, me, ops = new_game()
    c = build("Echo Beast", "{3}{R}", "Creature — Elemental",
              "Whenever this creature attacks, create a token that's a copy of it, "
              "except it isn't legendary.", 3, 3)
    pm = put(g, c, me)
    assert pm.card.triggers.get("attacks") is not None
    pm.summoning_sick = False
    g._declare_attackers(me, [(pm, ops[0])])
    run(g)
    assert len(tokens(me, "Echo Beast")) == 1


def test_corpus_creature_attacks_copy_that_creature():
    g, me, ops = new_game()
    put(g, build("Copy Banner", "{4}", "Artifact",
                 "Whenever a nontoken creature you control attacks, create a token that's a "
                 "copy of that creature."), me)
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    cb = None
    for pm in me.battlefield:
        cb = cb or pm.card.triggers.get("creature_attacks")
    if cb is None:
        pytest.skip("disparo no cableado")   # vanilla aceptable
    bear.summoning_sick = False
    g._declare_attackers(me, [(bear, ops[0])])
    run(g)
    assert len(tokens(me, "Bear")) == 1, "copia la criatura que atacó (no la ficha)"


def test_corpus_myriad_copies_attack_other_opponents():
    g, me, ops = new_game(n_opp=3)
    c = build("Battle Angels of Tyr", "{2}{W}{W}", "Creature — Angel Knight",
              "Flying, myriad\nWhenever this creature deals combat damage to a player, "
              "draw a card.", 4, 4, keywords=["Flying", "Myriad"])
    pm = put(g, c, me)
    pm.summoning_sick = False
    lifes = [o.life for o in ops]
    g._resolve_combat(me, [(pm, ops[0])])
    run(g)
    assert [o.life for o in ops] == [x - 4 for x in lifes], "cada rival recibe 4"
    assert not tokens(me), "las copias se exilian al final del combate"


def test_corpus_modal_choose_one_or_more_splits_targets():
    """Kill! Maim! Burn!: cada modo recibe SOLO su objetivo (antes 'destruí un
    artefacto' destruía también la criatura y apuntaba al jugador)."""
    import cardsdb as _db
    from engine import R
    row = _db.local_card("Kill! Maim! Burn!")
    if row is None:
        pytest.skip("sin base local")
    c = _db.build_card_from_data(row)
    g, me, ops = new_game()
    art = put(g, artifact("Relic"), ops[0])
    bear = put(g, creature("Bear", "1G", 2, 2), ops[0])
    mine = put(g, creature("Mine", "1G", 2, 2), me)
    give_lands(g, me, 4, colors=(R,))
    give_lands(g, me, 4, colors=(B,))
    me.hand.append(c)
    life = ops[0].life
    assert g.cast(me, c, targets=[art, ops[0]], chosen_modes=[0, 2])
    run(g)
    assert not on_bf(ops[0], art) and on_bf(ops[0], bear) and on_bf(me, mine)
    assert ops[0].life == life - 3


# --------------------------------------------------------------------------- #
# Base local de cartas: reglas encontradas por la auditoría / el verificador
# --------------------------------------------------------------------------- #

def _real(name):
    import cardsdb as _db
    row = _db.local_card(name)
    if row is None:
        pytest.skip(f"{name} no está en la base local")
    return _db.build_card_from_data(row)


def test_db_tapped_lands_enter_tapped():
    g, me, ops = new_game()
    pm = put(g, _real("Dismal Backwater"), me)
    assert pm.tapped, "'This land enters tapped' se ignoraba"
    assert me.life == 41


def test_db_checkland_and_fastland_conditions():
    g, me, ops = new_game()
    a = put(g, _real("Glacial Fortress"), me)            # sin Plains/Island -> girada
    assert a.tapped
    put(g, land("Island", [U], basic=True), me)
    b = put(g, _real("Glacial Fortress"), me)
    assert not b.tapped, "con una Island entra sin girar"
    g2, me2, _ = new_game()
    c = put(g2, _real("Blackcleave Cliffs"), me2)        # 0 otras tierras -> sin girar
    assert not c.tapped


def test_db_bounceland_returns_a_land_and_taps_for_two():
    g, me, ops = new_game()
    give_lands(g, me, 2)
    pm = put(g, _real("Azorius Chancery"), me)
    assert len(me.lands()) == 2 and len(me.hand) == 1
    assert max(pm.card.produces(pm, me).values()) == 2


def test_db_monarch_draws_and_moves_on_combat_damage():
    g, me, ops = new_game()
    put(g, _real("Palace Jailer") if False else creature("Bear", "1G", 2, 2), me)
    g.set_monarch(me)
    h = len(me.hand)
    g.end_turn(me)
    assert len(me.hand) == h + 1, "el monarca roba al final de su turno"
    atk = put(g, creature("Orc", "1B", 2, 2), ops[0])
    g.deal_damage(atk, me, 2, combat=True)
    assert g.monarch is ops[0]


def test_db_class_level_two_ability_needs_level():
    g, me, ops = new_game()
    t = put(g, _real("Gourmand's Talent"), me)
    g.gain_life(me, 1)
    run(g)
    assert not tokens(me), "en nivel 1 no crea Raccoons"
    t.counters["level"] = 2
    g.turn += 1
    g.gain_life(me, 1); run(g)
    g.gain_life(me, 1); run(g)
    assert len(tokens(me)) == 1, "nivel 2: una sola vez por turno"


def test_db_if_you_do_requires_the_first_part():
    g, me, ops = new_game()
    u = put(g, _real("Uchuulon"), me)
    g.emit("end_step", player=me); run(g)
    assert not tokens(me), "sin criatura en el cementerio rival no hay copia"
    ops[0].graveyard.append(creature("Dead", "1B", 2, 2))
    g.emit("end_step", player=me); run(g)
    assert len(tokens(me)) == 1 and ops[0].exile
