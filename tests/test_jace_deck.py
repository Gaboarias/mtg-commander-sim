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


def test_quintorius_plus_one_discard_draw_two_mill_one():
    q = cardsdb.build_card_from_data({
        "name": "Quintorius, History Chaser", "mana_cost": "{3}{R}{W}", "type_line": "Legendary Planeswalker — Quintorius",
        "loyalty": "5", "oracle_text": "Whenever one or more cards leave your graveyard, create a 3/2 red and white Spirit "
                                       "creature token.\n+1: You may discard a card. If you do, draw two cards, then mill a "
                                       "card.\n−4: Spirits you control gain double strike and vigilance until end of turn."})
    g, me, _ = _g()
    pm = put(g, q, me)
    me.hand += [creature("H1", "5G", 1, 1), creature("H2", "1G", 1, 1)]
    g.activate_loyalty(pm, 0)
    run(g)
    assert len(me.hand) == 3 and len(me.graveyard) == 2


def test_wipe_death_trigger_choice_names_its_source_and_spirit_colors():
    """Ceaseless Conflict mata a Atsushi: el modo de su disparo de muerte se pide
    atribuido a Atsushi (no parece parte del hechizo), y las fichas son rojo-blancas."""
    cc = cardsdb.build_card_from_data({
        "name": "Ceaseless Conflict", "mana_cost": "{3}{W}{W}", "type_line": "Sorcery",
        "oracle_text": "Destroy all creatures. Then create a 3/2 red and white Spirit creature token for "
                       "each nontoken creature you controlled that was destroyed this way."})
    at = cardsdb.build_card_from_data({
        "name": "Atsushi, the Blazing Sky", "mana_cost": "{2}{R}{R}", "type_line": "Legendary Creature — Dragon Spirit",
        "power": "4", "toughness": "4", "keywords": ["Flying", "Trample"],
        "oracle_text": "Flying, trample\nWhen Atsushi dies, choose one —\n• Exile the top two cards of your library. "
                       "Until the end of your next turn, you may play those cards.\n• Create three Treasure tokens."})
    g, me, _ = _g()
    g.interactive_human = me
    put(g, at, me)
    cc.on_cast_resolve(g, me, None)
    pc = g.pending_choice
    assert pc is not None and pc.get("card") == "Atsushi, the Blazing Sky"
    spirits = [p for p in me.battlefield if p.name == "Spirit"]
    assert len(spirits) == 1
    assert set(getattr(spirits[0].card, "colors", ()) or ()) >= {"R", "W"}


def _prep(name, face0, spell):
    return cardsdb.build_card_from_data({
        "name": name, "layout": "prepare", "mana_cost": face0[0], "type_line": face0[1],
        "card_faces": [
            {"name": name.split(" // ")[0], "mana_cost": face0[0], "type_line": face0[1], "oracle_text": face0[2],
             "power": "2", "toughness": "2"},
            {"name": name.split(" // ")[1], "mana_cost": spell[0], "type_line": spell[1], "oracle_text": spell[2]}],
        "power": "2", "toughness": "2"})


def test_prepared_state_exposed_and_only_enters_prepared_when_stated():
    eater = _prep("Adventurous Eater // Have a Bite",
                  ("{2}{B}", "Creature — Human Warlock",
                   "This creature enters prepared. (While it's prepared, you may cast a copy of its spell. Doing so unprepares it.)"),
                  ("{B}", "Sorcery", "Put a +1/+1 counter on target creature. You gain 1 life."))
    abig = _prep("Abigale, Poet Laureate // Heroic Stanza",
                 ("{1}{W}{B}", "Legendary Creature — Bird Bard",
                  "Flying\nWhenever you cast a creature spell, Abigale becomes prepared. (While it's prepared, you may cast a copy of its spell. Doing so unprepares it.)"),
                 ("{1}{W/B}", "Sorcery", "Put a +1/+1 counter on target creature."))
    g, me, _ = _g()
    pe = put(g, eater, me)
    pa = put(g, abig, me)
    run(g)
    se, sa = g._perm_state(pe), g._perm_state(pa)
    assert se["prepared"]["name"] == "Have a Bite" and se["prepared"]["ready"] is True
    assert "+1/+1 counter" in se["prepared"]["text"]
    assert sa["prepared"]["name"] == "Heroic Stanza" and sa["prepared"]["ready"] is False


def _prep_ready(name, f0_type, f0_text, sp_cost, sp_type, sp_text, lands=6, cols=(W, U, B, R, G)):
    c = _prep(name, ("{2}{G}", f0_type, f0_text), (sp_cost, sp_type, sp_text))
    g, me, ops = _g()
    pm = put(g, c, me)
    run(g)
    give_lands(g, me, lands, colors=cols)
    pm._prepared = True
    i = next(k for k, ab in enumerate(c.activated_abilities) if ab.get("prepared"))
    return g, me, ops, pm, i, c.activated_abilities[i]


_ENTERS = "This creature enters prepared. (While it's prepared, you may cast a copy of its spell. Doing so unprepares it.)"


def test_prepared_soul_tether_heartwood_token_rg_mana():
    g, me, _, pm, i, ab = _prep_ready("Heartwood Crafter // Soul Tether", "Creature — Elf Artificer", _ENTERS,
                                      "{2}{R/G}", "Sorcery", "Create a Heartwood token.")
    assert ab["sorcery_speed"] and g.activate_ability(pm, i)
    run(g)
    hw = [p for p in me.battlefield if p.name == "Heartwood"]
    assert len(hw) == 1 and me.produced(hw[0]) == {"R": 1, "G": 1} and not pm._prepared


def test_prepared_x_spells_stream_of_life_and_exsanguinate():
    g, me, _, pm, i, ab = _prep_ready("Infirmary Healer // Stream of Life", "Creature — Cat Cleric", _ENTERS,
                                      "{X}{G}", "Sorcery", "Target player gains X life.")
    assert ab["x_cost"]
    l0 = me.life
    g.activate_ability(pm, i, x=4)
    run(g)
    assert me.life == l0 + 4
    g, me, ops, pm, i, ab = _prep_ready("Stensian Sanguinist // Exsanguinate", "Creature — Vampire Cleric", _ENTERS,
                                        "{X}{B}{B}", "Sorcery",
                                        "Each opponent loses X life. You gain life equal to the life lost this way.")
    l0, o0 = me.life, ops[0].life
    g.activate_ability(pm, i, x=3)
    run(g)
    assert ops[0].life == o0 - 3 and me.life == l0 + 3


def test_prepared_all_aboard_flickers_non_pilot():
    g, me, _, pm, i, ab = _prep_ready("Skycoach Conductor // All Aboard", "Creature — Bird Pilot", _ENTERS,
                                      "{U}", "Instant", "Exile target non-Pilot creature you control, then return "
                                      "that card to the battlefield under its owner's control.")
    assert ab["target_spec"] == "own_nonpilot" and not ab["sorcery_speed"]
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    run(g)
    g.activate_ability(pm, i, targets=[bear])
    run(g)
    assert bear not in me.battlefield and any(p.name == "Bear" for p in me.battlefield)


def test_prepared_channel_pays_generic_with_life_this_turn_only():
    g, me, _, pm, i, ab = _prep_ready("Yavimaya Bloomsage // Channel", "Creature — Dryad Druid", _ENTERS, "{G}{G}",
                                      "Sorcery", "Until end of turn, any time you could activate a mana ability, you "
                                      "may pay 1 life. If you do, add {C}.", lands=2, cols=(G,))
    g.activate_ability(pm, i)
    run(g)
    big = creature("Big", "7", 7, 7)
    l0 = me.life
    assert me.can_pay(big.cost) and me.pay(big.cost)
    assert me.life == l0 - 7
    g.turn += 1
    assert not me.can_pay(big.cost)


def test_prepared_striking_palette_copies_next_instant_or_sorcery():
    g, me, _, pm, i, ab = _prep_ready("Pigment Wrangler // Striking Palette", "Creature — Orc Sorcerer", _ENTERS,
                                      "{R}", "Sorcery", "When you next cast an instant or sorcery spell this turn, "
                                      "copy that spell. You may choose new targets for the copy.")
    g.activate_ability(pm, i)
    run(g)
    assert getattr(me, "_copy_next", None) == (g.turn, "instant or sorcery")


def test_primary_research_reanimates_and_draws_when_card_left_graveyard():
    """Primary Research: su ETB saca una carta del cementerio y eso cuenta para
    'if a card left your graveyard this turn' (antes el reanimar no lo registraba)."""
    pr = cardsdb.build_card_from_data({
        "name": "Primary Research", "mana_cost": "{4}{W}", "type_line": "Enchantment",
        "oracle_text": "When this enchantment enters, return target nonland permanent card with mana value 3 or less "
                       "from your graveyard to the battlefield.\nAt the beginning of your end step, if a card left "
                       "your graveyard this turn, draw a card."})
    g, me, _ = _g()
    me.library = [creature(f"L{i}", "1", 1, 1) for i in range(5)]
    bear = creature("Bear", "1G", 2, 2)
    me.graveyard.append(bear)
    put(g, pr, me)
    run(g)
    assert any(p.name == "Bear" for p in me.battlefield) and bear not in me.graveyard
    assert getattr(me, "gy_left_turn", None) == g.turn
    h0 = len(me.hand)
    g.emit("end_step", player=me)
    run(g)
    assert len(me.hand) == h0 + 1


def test_any_graveyard_removal_counts_as_leaving():
    """Cualquier salida del cementerio (aunque el efecto no lo avise) dispara
    'whenever one or more cards leave your graveyard' una vez por tanda."""
    g, me, _ = _g()
    a, b = creature("A", "1", 1, 1), creature("B", "1", 1, 1)
    me.graveyard.extend([a, b])
    me.graveyard.remove(a)
    me.graveyard.remove(b)
    seen = []
    orig = g.emit

    def spy(ev, **kw):
        if ev == "leaves_graveyard":
            seen.append(kw.get("cards"))
        return orig(ev, **kw)
    g.emit = spy
    g.sba()
    assert len(seen) == 1 and len(seen[0]) == 2 and me.gy_left_turn == g.turn


def test_emblems_static_trigger_and_for_opponents():
    """Emblemas: anthem (Elspeth −7), disparo en el mantenimiento rival (Chandra +2)
    y que no son permanentes (no se destruyen ni cuentan como encantamiento)."""
    el = _mk("Elspeth, Sun's Champion")
    g, me, ops = _g()
    pm = put(g, el, me)
    run(g)
    pm.counters["loyalty"] = 8
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    run(g)
    g.activate_loyalty(pm, 2)
    run(g)
    assert len(me.emblems) == 1 and bear.power == 4 and bear.toughness == 4 and bear.has("flying")
    assert all(e not in me.battlefield for e in me.emblems) and "enchantment" not in me.emblems[0].card.types
    ch = cardsdb.build_card_from_data({
        "name": "Chandra, Awakened Inferno", "mana_cost": "{4}{R}{R}", "type_line": "Legendary Planeswalker — Chandra",
        "loyalty": "6", "oracle_text": "This spell can't be countered.\n+2: Each opponent gets an emblem with \"At the "
        "beginning of your upkeep, this emblem deals 1 damage to you.\"\n−3: Chandra, Awakened Inferno deals 3 damage "
        "to each non-Elemental creature.\n−X: Chandra, Awakened Inferno deals X damage to target creature or "
        "planeswalker. If a permanent dealt damage this way would die this turn, exile it instead."})
    g, me, ops = _g()
    pc = put(g, ch, me)
    run(g)
    g.activate_loyalty(pc, 0)
    run(g)
    assert len(ops[0].emblems) == 1 and not me.emblems
    l0 = ops[0].life
    g.emit("upkeep", player=ops[0])
    run(g)
    assert ops[0].life == l0 - 1


def test_loyalty_lock_until_next_turn_and_extra_turns():
    kaito = cardsdb.build_card_from_data({
        "name": "Kaito, Dancing Shadow", "mana_cost": "{2}{U}{B}", "type_line": "Legendary Planeswalker — Kaito",
        "loyalty": "3", "oracle_text": "+1: Up to one target creature can't attack or block until your next turn."})
    g, me, ops = _g()
    pk = put(g, kaito, me)
    ob = put(g, creature("OBear", "1G", 3, 3), ops[0])
    run(g)
    ob.summoning_sick = False
    g.activate_loyalty(pk, 0)
    run(g)
    assert not ob.can_attack()
    tef = cardsdb.build_card_from_data({
        "name": "Teferi, Master of Time", "mana_cost": "{2}{U}{U}", "type_line": "Legendary Planeswalker — Teferi",
        "loyalty": "3", "oracle_text": "−10: Take two extra turns after this one."})
    g, me, ops = _g()
    pt = put(g, tef, me)
    run(g)
    pt.counters["loyalty"] = 10
    g.activate_loyalty(pt, 0)
    run(g)
    assert g.extra_turns == [me, me]


def test_all_loyalty_abilities_have_effects_sample():
    """Muestra de las habilidades de lealtad agregadas una por una."""
    from engine import Cost
    import cards as _cards
    # Treasure / Black Lotus se sacrifican al dar maná; una fuente de 3 paga {R}{R}{R}
    g, me, _ = _g()
    _cards.make_resource_token(g, me, "treasure")
    me.pay(Cost(1, ()))
    assert not any(p.name == "Treasure" for p in me.battlefield)
    lotus = cardsdb._mana_rock_token
    g, me, _ = _g()
    lotus(g, me, "Black Lotus", {c: 3 for c in "WUBRG"})
    assert me.pay(Cost(0, ("R", "R", "R"))) and not any(p.name == "Black Lotus" for p in me.battlefield)
    # Kaya −2 dobla fichas solo ese turno (antes las doblaba siempre)
    kaya = cardsdb.build_card_from_data({
        "name": "Kaya, Geist Hunter", "mana_cost": "{1}{W}{B}", "type_line": "Legendary Planeswalker — Kaya",
        "loyalty": "3", "oracle_text": "+1: Creatures you control gain deathtouch until end of turn. Put a +1/+1 "
        "counter on up to one target creature token you control.\n−2: Until end of turn, if one or more tokens would "
        "be created under your control, twice that many of those tokens are created instead.\n−6: Exile all cards "
        "from all graveyards, then create a 1/1 white Spirit creature token with flying for each card exiled this way."})
    g, me, _ = _g()
    pk = put(g, kaya, me)
    run(g)
    assert g.token_multiplier(me) == 1
    g.activate_loyalty(pk, 1)
    run(g)
    assert g.token_multiplier(me) == 2
    g.turn += 1
    assert g.token_multiplier(me) == 1


def test_jeska_triple_and_ral_skip_turns():
    jeska = cardsdb.build_card_from_data({
        "name": "Jeska, Thrice Reborn", "mana_cost": "{2}{R}", "type_line": "Legendary Planeswalker — Jeska",
        "loyalty": "0", "oracle_text": "0: Choose target creature. Until your next turn, if that creature would deal "
        "combat damage to one of your opponents, it deals triple that damage to that player instead."})
    g, me, ops = _g()
    big = put(g, creature("Big", "3", 4, 4), me)
    pj = put(g, jeska, me)
    run(g)
    g.activate_loyalty(pj, 0)
    run(g)
    l0 = ops[0].life
    g.deal_damage(big, ops[0], 4, combat=True)
    assert l0 - ops[0].life == 12
    g, me, ops = _g()
    ops[0].__dict__["_skip_turns"] = 2
    assert g.skip_turn_check(ops[0]) and g.skip_turn_check(ops[0]) and not g.skip_turn_check(ops[0])


def test_sorin_control_and_controlled_policy():
    """Sorin Markov −7: un bot que controla el turno de otro no le hace jugar a su
    favor; el turno controlado por el humano cambia quién es 'el humano' y vuelve."""
    import interactive
    import decks
    defs = [("Yo",) + decks.build("lorehold"), ("Bot1",) + decks.build("strixhaven"), ("Bot2",) + decks.build("kang")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=4)
    ig.keep([])
    me, b1 = ig.human(), ig.g.players[1]
    b1.__dict__["_mindslaved_by"] = me
    st = ig.end_turn()
    k = 0
    while st["phase"] == "choose" and k < 20:
        st = ig.resolve_choice(0)
        k += 1
    assert st["controlling"] == {"player": "Bot1", "by": "Yo"} and st["human_index"] == 1
    st = ig.end_turn()
    while st["phase"] == "choose" and k < 40:
        st = ig.resolve_choice(0)
        k += 1
    assert st["controlling"] is None and st["human_index"] == 0


def test_space_beleren_sectors_assigned_and_sweep():
    from test_parser_corpus import new_game
    g, me, ops = new_game()
    g.active_index = 0
    for i in range(3):
        put(g, creature(f"B{i}", "2", 2, 2), ops[0])
    sb = cardsdb.build_card_from_data({
        "name": "Space Beleren", "mana_cost": "{2}{U}{U}", "type_line": "Legendary Planeswalker — Beleren",
        "loyalty": "4", "oracle_text": "Space sculptor (Space Beleren divides the battlefield into alpha, beta, and "
        "gamma sectors. If a creature isn't assigned to a sector, its controller assigns it to one. Opponents assign "
        "first.)\n+1: Creatures in each sector can be blocked this turn only by creatures in the same sector.\n−1: Put "
        "a +1/+1 counter on each creature in the sector of your choice.\n−5: Destroy all creatures in the sector of "
        "your choice."})
    pb = put(g, sb, me)
    run(g)
    g.sba()
    assert sorted(g.sector_of(pm) for pm in ops[0].creatures()) == [0, 1, 2]
    pb.counters["loyalty"] = 10
    g.activate_loyalty(pb, 2)
    run(g)
    assert len(ops[0].creatures()) == 2


def test_onakke_oathkeeper_tax_stacks_and_only_for_planeswalkers():
    from engine import C
    import cards as _cards
    onk = {"name": "Onakke Oathkeeper", "mana_cost": "{1}{W}", "type_line": "Creature — Ogre Spirit", "power": "1",
           "toughness": "1", "oracle_text": "Creatures can't attack planeswalkers you control unless their controller "
           "pays {1} for each creature they control that's attacking a planeswalker you control."}

    def scen(at_pw, lands):
        g, me, ops = _g()
        on = put(g, cardsdb.build_card_from_data(onk), ops[0])
        run(g)
        _cards.make_copy_token(g, ops[0], on.card)
        pw = put(g, _mk("Elspeth, Sun's Champion"), ops[0])
        run(g)
        give_lands(g, me, lands, colors=(C,))
        atk = [put(g, creature(f"A{i}", "1", 2, 2), me) for i in range(5)]
        run(g)
        for x in atk:
            x.summoning_sick = False
        return len(g._declare_attackers(me, [(x, pw if at_pw else ops[0]) for x in atk]))
    assert scen(False, 0) == 5          # al jugador: Onakke no cobra nada
    assert scen(True, 10) == 5          # al planeswalker: {2} por criatura (dos Onakke)
    assert scen(True, 5) == 2           # con 5 maná solo pagan 2 criaturas


def test_planeswalker_auras_target_planeswalkers():
    """Auras 'Enchant planeswalker' (Talents) van a tu planeswalker y le dan su habilidad;
    las de bloqueo ('… activated abilities can't be activated') anulan la lealtad rival."""
    talent = cardsdb.build_card_from_data({
        "name": "Elspeth's Talent", "mana_cost": "{2}{W}{W}", "type_line": "Enchantment — Aura",
        "oracle_text": "Enchant planeswalker\nEnchanted planeswalker has \"[+1]: Create three 1/1 white Soldier "
        "creature tokens.\"\nWhenever you activate a loyalty ability of enchanted planeswalker, creatures you control "
        "get +2/+2 and gain vigilance until end of turn."})
    binding = cardsdb.build_card_from_data({
        "name": "Nahiri's Binding", "mana_cost": "{1}{W}{W}", "type_line": "Enchantment — Aura",
        "oracle_text": "Enchant creature or planeswalker\nEnchanted permanent can't attack or block, and its "
        "activated abilities can't be activated."})
    g, me, ops = _g()
    mine = put(g, _mk("Elspeth, Sun's Champion"), me)
    theirs = put(g, _mk("Elspeth, Sun's Champion"), ops[0])
    put(g, creature("Bear", "1G", 2, 2), me)
    run(g)
    au = put(g, talent, me)
    run(g)
    assert au.enchanting is mine and len(mine.loyalty_abils()[0]) == 4
    assert g.activate_loyalty(mine, 3)
    run(g)
    assert sum(1 for p in me.battlefield if p.name == "Soldier") == 3
    assert all(p.power >= 3 and p.has("vigilance") for p in me.creatures())
    b = put(g, binding, me)
    run(g)
    assert b.enchanting is theirs and not g.activate_loyalty(theirs, 0)


def test_in_too_deep_on_planeswalker_stops_being_one():
    itd = cardsdb.build_card_from_data({
        "name": "In Too Deep", "mana_cost": "{U}{U}", "type_line": "Enchantment — Aura",
        "oracle_text": "Split second\nEnchant creature, planeswalker, or Clue\nEnchanted permanent is a colorless "
        "Clue artifact with \"{2}, Sacrifice this artifact: Draw a card\" and loses all other abilities. (It's no "
        "longer a creature or planeswalker.)"})
    g, me, ops = _g()
    pw = put(g, _mk("Elspeth, Sun's Champion"), ops[0])
    run(g)
    au = put(g, itd, me)
    run(g)
    assert au.enchanting is pw and not pw.is_planeswalker()
    assert not g.activate_loyalty(pw, 0)
    loy = pw.counters.get("loyalty", 0)
    g.deal_damage(put(g, creature("Hit", "1", 3, 3), me), pw, 3, combat=True)
    assert pw.counters.get("loyalty", 0) == loy          # ya no recibe daño como planeswalker
    pw.counters["loyalty"] = 0
    g.sba()
    assert pw in ops[0].battlefield                      # sin lealtad no muere: no es planeswalker
    assert not g._perm_state(pw)["is_planeswalker"]


def test_stream_of_life_bot_gains_itself():
    sol = cardsdb.build_card_from_data({"name": "Stream of Life", "mana_cost": "{X}{G}", "type_line": "Sorcery",
                                        "oracle_text": "Target player gains X life."})
    g, me, ops = _g()
    g.spell_x = 5
    l0, o0 = me.life, ops[0].life
    sol.on_cast_resolve(g, me, None)
    assert me.life == l0 + 5 and ops[0].life == o0


def test_space_beleren_block_only_same_sector():
    from test_parser_corpus import new_game
    g, me, ops = new_game()
    g.active_index = 0
    a = put(g, creature("Atk", "2", 3, 3), ops[0])
    b1 = put(g, creature("Same", "2", 2, 2), me)
    b2 = put(g, creature("Other", "2", 2, 2), me)
    run(g)
    a._sector, b1._sector, b2._sector = 1, 1, 2
    assert g.can_block_pair(a, b1) and g.can_block_pair(a, b2)
    g._sector_block_turn = g.turn
    assert g.can_block_pair(a, b1) and not g.can_block_pair(a, b2)
