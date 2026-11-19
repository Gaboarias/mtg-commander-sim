"""Mazo de Jace (Multiverse Reforged): Martial Coup / White Sun's Twilight (barrida con X>=5),
remociones con su segunda parte (Swords, Path, Stroke), Brainstorm, Teferi's Reproach, Occult
Epiphany, habilidades de lealtad completas (Jace, Elspeth), protección real (Akroma, Serra's
Emissary), maná (painlands, identidad del comandante, Exotic Orchard, Chromatic Lantern) y las
criaturas/encantamientos del mazo."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cardsdb  # noqa: E402
from engine import U, W, R, B, G, Cost, StackObject  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import new_game, run, put, give_lands, artifact  # noqa: E402

_D = {
    'Martial Coup': ('{X}{W}{W}', 'Sorcery', 'Create X 1/1 white Soldier creature tokens. If X is 5 or more, destroy all other creatures.', None, None, None, None, None),
    "White Sun's Twilight": ('{X}{W}{W}', 'Sorcery', 'You gain X life. Create X 1/1 colorless Phyrexian Mite artifact creature tokens with toxic 1 and "This token can\'t block." If X is 5 or more, destroy all other creatures. (Players dealt combat damage by a creature with toxic 1 also get a poison counter.)', None, None, None, None, None),
    'Swords to Plowshares': ('{W}', 'Instant', 'Exile target creature. Its controller gains life equal to its power.', None, None, None, None, None),
    'Path to Exile': ('{W}', 'Instant', 'Exile target creature. Its controller may search their library for a basic land card, put that card onto the battlefield tapped, then shuffle.', None, None, None, None, None),
    'Stroke of Midnight': ('{2}{W}', 'Instant', 'Destroy target nonland permanent. Its controller creates a 1/1 white Human creature token.', None, None, None, None, None),
    'Brainstorm': ('{U}', 'Instant', 'Draw three cards, then put two cards from your hand on top of your library in any order.', None, None, None, None, None),
    "Teferi's Reproach": ('{2}{W}', 'Instant', "Choose target opponent. Until that player's next turn, they gain protection from everything and their life total can't change. All nonland permanents they control phase out. (While they're phased out, they're treated as though they don't exist. They phase in before that player untaps during their next untap step.)\nExile Teferi's Reproach.", None, None, None, None, None),
    'Occult Epiphany': ('{X}{U}', 'Instant', 'Draw X cards, then discard X cards. Create a 1/1 white Spirit creature token with flying for each card type among cards discarded this way.', None, None, None, None, None),
    'Jace, Multiverse Architect': ('{1}{W}{U}{B}{R}', 'Legendary Planeswalker — Jace', "At the beginning of combat on each opponent's turn, they may pay {2}. If they don't, creatures they control can't attack Jaces you control this turn.\n+1: Draw two cards, then put a card from your hand on the bottom of your library.\n−3: Exile another target planeswalker or creature you control. Reveal cards from the top of your library until you reveal a creature or planeswalker card. Put that card onto the battlefield and the rest on the bottom of your library in a random order.\nJace, Multiverse Architect can be your commander.", None, None, '4', None, None),
    "Elspeth, Sun's Champion": ('{4}{W}{W}', 'Legendary Planeswalker — Elspeth', '+1: Create three 1/1 white Soldier creature tokens.\n−3: Destroy all creatures with power 4 or greater.\n−7: You get an emblem with "Creatures you control get +2/+2 and have flying."', None, None, '4', None, None),
    'Nissa, Leyline Tamer': ('{3}{W}{U}{B}{R}', 'Legendary Creature — Elf Wizard', 'Deathtouch, vigilance\nLandfall — Whenever a land you control enters, draw a card. Then if this is the first time this ability has resolved this turn, reveal cards from the top of your library until you reveal a creature card. Put that card onto the battlefield and the rest on the bottom of your library in a random order.', '5', '5', None, ['Vigilance', 'Deathtouch', 'Landfall'], None),
    'Omnath, Locus of the Void': ('{7}', 'Legendary Creature — Elemental', 'Omnath gets +1/+1 for each unspent mana you have.\nIf you would lose unspent mana, that mana becomes colorless instead.\nLandfall — Whenever a land you control enters, add {C}{C}.', '6', '6', None, ['Landfall'], ['C']),
    'Ob Nixilis, the Ascended': ('{5}{W}{W}', 'Legendary Creature — Angel', 'Flying\nWhen Ob Nixilis enters, destroy all tapped creatures your opponents control. You gain 1 life for each creature destroyed this way.\nAt the beginning of each end step, if you gained life this turn, create a 4/4 white Angel creature token with flying.', '4', '4', None, ['Flying'], None),
    'Avacyn, Angel of Horror': ('{5}{B}{B}{B}', 'Legendary Creature — Angel', 'Flying, deathtouch\nWhenever Avacyn or another nontoken creature you control dies, return that card to the battlefield under your control at the beginning of the next end step.', '8', '8', None, ['Deathtouch', 'Flying'], None),
    'Jhoira, Weatherlight Corsair': ('{4}{B}{B}', 'Legendary Creature — Human Pirate', "Whenever Jhoira enters or attacks, target opponent reveals cards from the top of their library until they reveal a historic permanent card. You put that card onto the battlefield under your control and lose life equal to that permanent's mana value. That player puts the rest of the revealed cards on the bottom of their library in a random order. (Artifacts, legendaries, and Sagas are historic.)", '4', '5', None, None, None),
    'Tamiyo, Upriser Crowned': ('{4}{R}{W}', 'Legendary Creature — Moonfolk Warrior', "Flying, double strike, haste\nWhen Tamiyo enters, you become the monarch.\nWhenever one or more creatures deal combat damage to you while you're the monarch, tap those creatures and put a stun counter on each of them.", '3', '5', None, ['Flying', 'Haste', 'Double strike'], None),
    'Ginger, Queen of Sweets': ('{6}', 'Legendary Artifact Creature — Food Noble', 'When Ginger enters, you become the monarch.\n{2}, {T}, Sacrifice Ginger: You gain 6 life.\nAt the beginning of each upkeep, if you\'re the monarch, create a Gingerbrute token. (It\'s a {1} 1/1 Food Golem artifact creature with haste, "{1}: This token can\'t be blocked this turn except by creatures with haste," and "{2}, {T}, Sacrifice this token: You gain 3 life.")', '6', '4', None, None, None),
    'Memnarch, the Warden': ('{10}', 'Legendary Artifact Creature — Wizard', 'Indestructible\nWhen Memnarch enters, create two 1/1 colorless Myr artifact creature tokens.\nWhenever Memnarch attacks, draw a card for each artifact you control.', '8', '9', None, ['Indestructible'], None),
    "Skrelv's Hive": ('{1}{W}', 'Enchantment', 'At the beginning of your upkeep, you lose 1 life and create a 1/1 colorless Phyrexian Mite artifact creature token with toxic 1 and "This token can\'t block."\nCorrupted — As long as an opponent has three or more poison counters, creatures you control with toxic have lifelink.', None, None, None, ['Corrupted'], None),
    'Shark Typhoon': ('{5}{U}', 'Enchantment', "Whenever you cast a noncreature spell, create an X/X blue Shark creature token with flying, where X is that spell's mana value.\nCycling {X}{1}{U} ({X}{1}{U}, Discard this card: Draw a card.)\nWhen you cycle this card, create an X/X blue Shark creature token with flying.", None, None, None, ['Cycling'], None),
    'Archfiend of Despair': ('{6}{B}{B}', 'Creature — Demon', "Flying\nYour opponents can't gain life.\nAt the beginning of each end step, each opponent loses life equal to the life that player lost this turn. (Damage causes loss of life.)", '6', '6', None, ['Flying'], None),
    'Archon of Cruelty': ('{6}{B}{B}', 'Creature — Archon', 'Flying\nWhenever this creature enters or attacks, target opponent sacrifices a creature or planeswalker of their choice, discards a card, and loses 3 life. You draw a card and gain 3 life.', '6', '6', None, ['Flying'], None),
    'Dreadhorde Invasion': ('{1}{B}', 'Enchantment', "At the beginning of your upkeep, you lose 1 life and amass Zombies 1. (Put a +1/+1 counter on an Army you control. It's also a Zombie. If you don't control an Army, create a 0/0 black Zombie Army creature token first.)\nWhenever a Zombie token you control with power 6 or greater attacks, it gains lifelink until end of turn.", None, None, None, ['Amass'], None),
    'Chromatic Lantern': ('{3}', 'Artifact', 'Lands you control have "{T}: Add one mana of any color."\n{T}: Add one mana of any color.', None, None, None, None, ['B', 'G', 'R', 'U', 'W']),
    'Proteus Staff': ('{3}', 'Artifact', "{2}{U}, {T}: Put target creature on the bottom of its owner's library. That creature's controller reveals cards from the top of their library until they reveal a creature card. The player puts that card onto the battlefield and the rest on the bottom of their library in any order. Activate only as a sorcery.", None, None, None, None, None),
    'Plan for All Outcomes': ('{3}{U}', 'Enchantment', 'When this enchantment enters, the owner of up to one other target nonland permanent puts it on their choice of the top or bottom of their library.\nWhenever you cast your first noncreature spell each turn, empower Jace 1. (Put a loyalty counter on a Jace token you control. If you don\'t control one, first create a blue Jace planeswalker token with "[−1]: Surveil 1" and "[−3]: Draw a card.")', None, None, None, ['Surveil', 'Empower Jace'], None),
    'Akroma, Angel of Fury': ('{5}{R}{R}{R}', 'Legendary Creature — Angel', "This spell can't be countered.\nFlying, trample, protection from white and from blue\n{R}: Akroma gets +1/+0 until end of turn.\nMorph {3}{R}{R}{R} (You may cast this card face down as a 2/2 creature for {3}. Turn her face up any time for her morph cost.)", '6', '6', None, ['Flying', 'Morph', 'Protection', 'Trample'], None),
    "Serra's Emissary": ('{4}{W}{W}{W}', 'Creature — Angel', 'Flying\nAs this creature enters, choose a card type.\nYou and creatures you control have protection from the chosen card type.', '7', '7', None, ['Flying'], None),
    'Venser, Fervent Forger': ('{4}{R}{R}', 'Legendary Creature — Human Sorcerer', 'Flash\nWhen Venser enters, choose one —\n• Copy target instant or sorcery spell an opponent controls twice. You may choose new targets for the copies.\n• Create two tokens that are copies of target permanent an opponent controls. They gain haste. At the beginning of the next end step, sacrifice them.', '5', '3', None, ['Flash'], None),
    'Battlefield Forge': (None, 'Land', '{T}: Add {C}.\n{T}: Add {R} or {W}. This land deals 1 damage to you.', None, None, None, None, ['C', 'R', 'W']),
    'Arcane Signet': ('{2}', 'Artifact', "{T}: Add one mana of any color in your commander's color identity.", None, None, None, None, ['B', 'G', 'R', 'U', 'W']),
    'Exotic Orchard': (None, 'Land', '{T}: Add one mana of any color that a land an opponent controls could produce.', None, None, None, None, ['B', 'G', 'R', 'U', 'W']),
    'Restless Spire': (None, 'Land', 'This land enters tapped.\n{T}: Add {U} or {R}.\n{U}{R}: Until end of turn, this land becomes a 2/1 blue and red Elemental creature with "During your turn, this creature has first strike." It\'s still a land.\nWhenever this land attacks, scry 1.', None, None, None, ['Scry'], ['R', 'U']),
    'The Ur-Sphinx': ('{6}{W}{U}{B}', 'Legendary Creature — Sphinx Avatar', 'Eminence — As long as The Ur-Sphinx is in the command zone or on the battlefield, other Sphinx spells you cast cost {1} less to cast.\nFlying\nWhenever one or more Sphinxes you control attack, each player mills that many cards. For each player, you may cast a card that player milled this way without paying its mana cost.', '10', '10', None, ['Flying', 'Eminence', 'Mill'], None),
    'Divination': ('{2}{U}', 'Sorcery', 'Draw two cards.', None, None, None, None, None),
}


def _mk(name):
    mc, tl, ot, p, t, loy, kws, pm = _D[name]
    d = {"name": name, "mana_cost": mc or "", "type_line": tl, "oracle_text": ot, "keywords": list(kws or [])}
    if p is not None:
        d["power"], d["toughness"] = p, t
    if loy is not None:
        d["loyalty"] = loy
    if pm:
        d["produced_mana"] = pm
    return cardsdb.build_card_from_data(d)


def _g():
    g, me, ops = new_game()
    g.active_index = 0
    return g, me, ops


def _cast(g, me, name, x=None, targets=None):
    give_lands(g, me, 12, colors=(W, U, B, R, G))
    c = _mk(name)
    me.hand.append(c)
    ok = g.cast(me, c, x_value=x, targets=targets)
    run(g)
    return ok


def _toks(p, nm):
    return [x for x in p.battlefield if x.name == nm]


def test_martial_coup_small_x_only_tokens():
    g, me, ops = _g()
    put(g, creature("Mine", "G", 2, 2), me)
    put(g, creature("Theirs", "G", 3, 3), ops[0])
    assert _cast(g, me, "Martial Coup", x=3)
    assert len(_toks(me, "Soldier")) == 3 and _toks(me, "Mine") and _toks(ops[0], "Theirs")


def test_martial_coup_x5_destroys_all_other_creatures():
    g, me, ops = _g()
    put(g, creature("Mine", "G", 2, 2), me)
    put(g, creature("Theirs", "G", 3, 3), ops[0])
    assert _cast(g, me, "Martial Coup", x=5)
    assert len(_toks(me, "Soldier")) == 5 and not _toks(me, "Mine") and not ops[0].creatures()


def test_white_suns_twilight():
    g, me, ops = _g()
    put(g, creature("Theirs", "G", 3, 3), ops[0])
    life = me.life
    assert _cast(g, me, "White Sun's Twilight", x=5)
    mites = _toks(me, "Phyrexian Mite")
    assert len(mites) == 5 and me.life == life + 5 and not ops[0].creatures()
    assert mites[0].has("toxic") and mites[0].cant_block and "artifact" in mites[0].card.types


def test_removal_riders():
    g, me, ops = _g()
    t = put(g, creature("T", "G", 3, 3), ops[0])
    life = ops[0].life
    assert _cast(g, me, "Swords to Plowshares", targets=[t])
    assert t not in ops[0].battlefield and ops[0].life == life + 3
    t2 = put(g, creature("T2", "G", 2, 2), ops[0])
    _cast(g, me, "Path to Exile", targets=[t2])
    assert any(x.card.is_land() for x in ops[0].battlefield)
    r = put(g, artifact("Rock"), ops[0])
    _cast(g, me, "Stroke of Midnight", targets=[r])
    assert r not in ops[0].battlefield and _toks(ops[0], "Human")


def test_brainstorm_puts_two_back():
    g, me, _ = _g()
    h = len(me.hand)
    _cast(g, me, "Brainstorm")
    assert len(me.hand) == h + 1


def test_teferis_reproach_phases_and_locks_life():
    g, me, ops = _g()
    t = put(g, creature("T", "G", 3, 3), ops[0])
    life = ops[0].life
    assert _cast(g, me, "Teferi's Reproach", targets=[ops[0]])
    g.deal_damage(None, ops[0], 5)
    ops[0].life -= 2
    assert t not in ops[0].battlefield and ops[0].life == life and ops[0].has_hexproof()
    g._phase_step(ops[0])
    assert t in ops[0].battlefield and not ops[0].has_hexproof()


def test_occult_epiphany_spirits_per_type():
    g, me, _ = _g()
    me.hand += [creature("H", "1G", 1, 1), artifact("A")]
    me.library += [creature("X1", "1G", 1, 1), artifact("X2")]
    _cast(g, me, "Occult Epiphany", x=2)
    assert len(_toks(me, "Spirit")) >= 1 and _toks(me, "Spirit")[0].has("flying")


def test_jace_loyalty_and_combat_tax():
    g, me, ops = _g()
    j = put(g, _mk("Jace, Multiverse Architect"), me)
    h = len(me.hand)
    g.activate_loyalty(j, 0)
    run(g)
    assert len(me.hand) == h + 1 and j.counters["loyalty"] == 5
    a = put(g, creature("A", "G", 3, 3), ops[0])
    a.summoning_sick = False
    g.emit("each_combat", active=ops[0])
    run(g)
    g.active_index = 1
    assert not g._declare_attackers(ops[0], [(a, j)])


def test_elspeth_loyalty_full_effects():
    g, me, ops = _g()
    e = put(g, _mk("Elspeth, Sun's Champion"), me)
    g.activate_loyalty(e, 0)
    run(g)
    assert len(_toks(me, "Soldier")) == 3
    big = put(g, creature("Big", "G", 5, 5), ops[0])
    e.activated_this_turn = False
    g.activate_loyalty(e, 1)
    run(g)
    assert big not in ops[0].battlefield


def test_nissa_first_landfall_reveals_creature():
    g, me, _ = _g()
    put(g, _mk("Nissa, Leyline Tamer"), me)
    me.library += [creature("Fat", "3G", 4, 4), land("L", [G])]
    g.move_to_battlefield(land("Forest", [G], basic=True), me)
    run(g)
    assert _toks(me, "Fat")
    me.library.append(creature("Fat2", "3G", 4, 4))
    g.move_to_battlefield(land("Forest", [G], basic=True), me)
    run(g)
    assert not _toks(me, "Fat2")


def test_omnath_grows_with_mana_and_keeps_it():
    g, me, _ = _g()
    o = put(g, _mk("Omnath, Locus of the Void"), me)
    g.move_to_battlefield(land("Forest", [G], basic=True), me)
    run(g)
    assert me.mana_pool == 2 and o.power == 8


def test_ob_nixilis_and_avacyn():
    g, me, ops = _g()
    t = put(g, creature("T", "G", 2, 2), ops[0])
    t.tapped = True
    put(g, _mk("Ob Nixilis, the Ascended"), me)
    assert t not in ops[0].battlefield
    g.emit("each_end_step", active=me)
    run(g)
    assert _toks(me, "Angel")
    put(g, _mk("Avacyn, Angel of Horror"), me)
    c = put(g, creature("C", "2G", 2, 2), me)
    g.destroy(c)
    run(g)
    for f in list(g.delayed_end):
        f(g)
    assert _toks(me, "C")


def test_jhoira_steals_historic():
    g, me, ops = _g()
    ops[0].library += [artifact("OppArt"), land("L", [G])]
    life = me.life
    put(g, _mk("Jhoira, Weatherlight Corsair"), me)
    assert _toks(me, "OppArt") and me.life == life - 2


def test_tamiyo_stuns_attackers_of_monarch():
    g, me, ops = _g()
    tm = put(g, _mk("Tamiyo, Upriser Crowned"), me)
    tm.tapped = True
    a = put(g, creature("A", "G", 3, 3), ops[0])
    a.summoning_sick = False
    g.active_index = 1
    g._resolve_combat(ops[0], [(a, me)])
    run(g)
    assert a.tapped and a.counters.get("stun") == 1


def test_ginger_memnarch_skrelv_shark():
    g, me, ops = _g()
    put(g, _mk("Ginger, Queen of Sweets"), me)
    g.emit("each_upkeep", active=me)
    run(g)
    gb = _toks(me, "Gingerbrute")
    assert gb and gb[0].has("haste") and "artifact" in gb[0].card.types
    m = put(g, _mk("Memnarch, the Warden"), me)
    myr = _toks(me, "Myr")
    assert len(myr) == 2 and "artifact" in myr[0].card.types
    put(g, _mk("Skrelv's Hive"), me)
    g.emit("upkeep", player=me)
    run(g)
    assert _toks(me, "Phyrexian Mite")
    put(g, _mk("Shark Typhoon"), me)
    g.emit("cast", player=me, card=_mk("Divination"))
    run(g)
    assert _toks(me, "Shark") and _toks(me, "Shark")[0].power == 3
    m.summoning_sick = False
    h = len(me.hand)
    g._declare_attackers(me, [(m, ops[0])])
    run(g)
    assert len(me.hand) - h == sum(1 for x in me.battlefield if "artifact" in x.card.types)


def test_archfiend_archon_dreadhorde():
    g, me, ops = _g()
    put(g, _mk("Archfiend of Despair"), me)
    g.deal_damage(None, ops[0], 5)
    life = ops[0].life
    g.emit("each_end_step", active=me)
    run(g)
    assert ops[0].life == life - 5
    c = put(g, creature("C", "G", 2, 2), ops[0])
    ops[0].hand.append(creature("H", "1G", 1, 1))
    l0, ml = ops[0].life, me.life
    put(g, _mk("Archon of Cruelty"), me)
    assert c not in ops[0].battlefield and not ops[0].hand and ops[0].life == l0 - 3 and me.life == ml + 3
    put(g, _mk("Dreadhorde Invasion"), me)
    g.emit("upkeep", player=me)
    run(g)
    army = [x for x in me.battlefield if x.has_subtype("Army")]
    assert army and army[0].has_subtype("Zombie")


def test_proteus_staff_and_plan_for_all_outcomes():
    g, me, ops = _g()
    ps = put(g, _mk("Proteus Staff"), me)
    give_lands(g, me, 3, colors=(U,))
    t = put(g, creature("T", "G", 3, 3), ops[0])
    ops[0].library += [creature("Rep", "1G", 1, 1), land("L", [G])]
    assert g.activate_ability(ps, 0, targets=[t])
    run(g)
    assert t not in ops[0].battlefield and _toks(ops[0], "Rep")
    put(g, artifact("Theirs"), ops[0])
    n0 = sum(1 for x in ops[0].battlefield if not x.card.is_land())
    lib0 = len(ops[0].library)
    put(g, _mk("Plan for All Outcomes"), me)
    assert sum(1 for x in ops[0].battlefield if not x.card.is_land()) == n0 - 1 and len(ops[0].library) == lib0 + 1


def test_protection_akroma_and_serra():
    g, me, ops = _g()
    ak = put(g, _mk("Akroma, Angel of Fury"), ops[0])
    _cast(g, me, "Swords to Plowshares", targets=[ak])
    assert ak in ops[0].battlefield
    wg = put(g, creature("WhiteGuy", "1W", 2, 2), me)
    g.deal_damage(wg, ak, 5)
    assert ak.damage == 0
    assert not g._can_block_evasion(ak, put(g, creature("BlueGuy", "1U", 1, 1), me))
    assert g._can_block_evasion(ak, put(g, creature("RedGuy", "1R", 1, 1), me))
    g2, me2, ops2 = _g()
    put(g2, _mk("Serra's Emissary"), me2)
    a = put(g2, creature("A", "G", 3, 3), ops2[0])
    life = me2.life
    g2.deal_damage(a, me2, 3)
    assert me2.life == life


def test_venser_modes():
    g, me, ops = _g()
    put(g, creature("Big", "G", 5, 5), ops[0])
    put(g, _mk("Venser, Fervent Forger"), me)
    b = _toks(me, "Big")
    assert len(b) == 2 and b[0].has("haste") and len(getattr(g, "blitz_sac", [])) == 2
    g2, me2, ops2 = _g()
    sp = _mk("Divination")
    g2.stack.append(StackObject(ops2[0], lambda gg, _c=sp: _c.on_cast_resolve(gg, ops2[0], []), source=sp,
                                label="spell:Divination"))
    h = len(me2.hand)
    g2.move_to_battlefield(_mk("Venser, Fervent Forger"), me2)
    run(g2)
    assert len(me2.hand) - h == 4


def test_mana_sources():
    g, me, ops = _g()
    me.commanders = [_mk("Jace, Multiverse Architect")]
    sig = put(g, _mk("Arcane Signet"), me)
    assert sorted(me.produced(sig)) == ["B", "R", "U", "W"]
    put(g, land("Swamp", [B], basic=True), ops[0])
    eo = put(g, _mk("Exotic Orchard"), me)
    assert sorted(me.produced(eo)) == ["B"]
    bf = put(g, _mk("Battlefield Forge"), me)
    sig.tapped = eo.tapped = True
    life = me.life
    assert me.pay(Cost(0, ("R",))) and me.life == life - 1
    put(g, _mk("Chromatic Lantern"), me)
    f = put(g, land("Forest", [G], basic=True), me)
    assert {"W", "U", "B", "R", "G"} <= set(me.produced(f))


def test_restless_spire_and_ur_sphinx():
    g, me, _ = _g()
    rs = put(g, _mk("Restless Spire"), me)
    give_lands(g, me, 3, colors=(U, R))
    rs.tapped = False
    assert g.activate_ability(rs, 1)
    run(g)
    assert rs.is_creature() and rs.power == 2 and rs.toughness == 1 and rs.has("first_strike") and not rs.tapped
    me.command = [_mk("The Ur-Sphinx")]
    sph = cardsdb.build_card_from_data({"name": "Sph", "mana_cost": "{4}{U}", "type_line": "Creature — Sphinx",
                                        "oracle_text": "", "power": "3", "toughness": "3"})
    assert g.effective_cost(me, sph).cmc == 4
