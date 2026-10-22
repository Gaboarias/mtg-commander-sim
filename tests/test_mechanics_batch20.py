"""Batch 20: long tail grande — estáticas con nombre corto, evasión, reglas
globales, costes adicionales nuevos, escape con contadores, Sculler, atomics de
zona/combate y la cobertura honesta de la auditoría (tierras de maná, keywords)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_short_name_conditional_keyword_and_per_card_buff():
    g, me, ops = new_game()
    col = put(g, build("Colossus, Steel Stalwart", "{4}", "Legendary Creature — Mutant",
                       "During your turn, Colossus has indestructible.", 5, 5), me)
    g.active_index = g.players.index(me)
    assert col.has("indestructible")
    g.active_index = g.players.index(ops[0])
    assert not col.has("indestructible")
    slag = put(g, build("Slag", "{3}{B}{R}", "Creature — Horror",
                        "This creature gets -1/-1 for each card in your hand.", 8, 8), me)
    me.hand = [creature(f"H{k}", "1G", 1, 1) for k in range(3)]
    assert slag.power == 5


def test_counter_grant_plural_and_attached_count():
    g, me, ops = new_game()
    put(g, build("Grantor", "{2}{G}", "Creature — Elf",
                 "Creatures you control with +1/+1 counters on them have trample.", 2, 2), me)
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    assert not bear.has("trample")
    bear.counters["+1/+1"] = 1
    assert bear.has("trample")
    vo = put(g, build("Voltron", "{2}{W}", "Creature — Human",
                      "This creature gets +1/+1 for each Aura and Equipment attached to it.", 1, 1), me)
    aura = put(g, build("Wrap", "{W}", "Enchantment — Aura", "Enchant creature"), me)
    aura.enchanting = vo
    assert vo.power == 2


def test_evasion_statics():
    g, me, ops = new_game()
    a = put(g, build("Sneaky", "{1}{U}", "Creature — Rogue",
                     "This creature can't be blocked by creatures with flying.", 2, 2), me)
    flyer = put(g, build("Bird", "{1}{W}", "Creature — Bird", "Flying", 1, 1, keywords=["Flying"]), ops[0])
    ground = put(g, creature("Wall", "1W", 0, 4), ops[0])
    assert not g._can_block_evasion(a, flyer)
    assert g._can_block_evasion(a, ground)
    picky = put(g, build("Picky", "{1}{R}", "Creature — Goblin",
                         "This creature can't block creatures with power 2 or less.", 3, 3), ops[0])
    assert not g._can_block_evasion(a, picky)


def test_global_rules_lands_legend_and_uncounterable():
    g, me, ops = new_game()
    assert g.land_limit(me) == 1
    stax = put(g, build("No Lands", "{3}", "Artifact", "Players can't play lands."), ops[0])
    assert g.land_limit(me) == 0
    g.to_graveyard(stax, "test")
    put(g, build("Mirror Box", "{3}", "Artifact",
                 'The "legend rule" doesn\'t apply to permanents you control.'), me)
    put(g, creature("Twin", "2G", 2, 2, legendary=True), me)
    put(g, creature("Twin", "2G", 2, 2, legendary=True), me)
    assert sum(1 for pm in me.battlefield if pm.name == "Twin") == 2
    put(g, build("Gaddock", "{G}{W}", "Creature — Elf", "Creature spells can't be countered.", 2, 2), me)
    big = creature("Big", "4G", 5, 5)
    assert g._uncounterable(None, big)


def test_additional_costs_bounce_and_sacrifice_lands():
    g, me, ops = new_game()
    give_lands(g, me, 3, colors=(U,))
    sp = build("Bounce Cost", "{U}", "Instant", "As an additional cost to cast this spell, return a land "
               "you control to its owner's hand.\nDraw two cards.")
    assert sp.additional_cost.get("bounce_own") == "land"
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    me.hand.append(sp)
    n_lands = sum(1 for pm in me.battlefield if pm.card.is_land())
    assert g.cast(me, sp)
    run(g)
    assert sum(1 for pm in me.battlefield if pm.card.is_land()) == n_lands - 1
    sp2 = build("Land Sac", "{R}", "Sorcery", "As an additional cost to cast this spell, sacrifice two "
                "lands.\nThis spell deals 5 damage to any target.")
    assert sp2.additional_cost.get("sacrifice_nk") == (2, "land")


def test_escape_with_counters_and_sac_unless_escaped():
    g, me, ops = new_game()
    give_lands(g, me, 6, colors=(B, R))
    kx = build("Kroxish", "{B}{R}", "Legendary Creature — Elder Giant",
               "When this creature enters, sacrifice it unless it escaped.\n"
               "This creature escapes with two +1/+1 counters on it.\n"
               "Escape—{B}{B}{R}{R}, Exile two other cards from your graveyard.", 6, 6)
    assert kx.escape_counters == 2
    me.graveyard = [kx, creature("A", "1G", 1, 1), creature("B", "1G", 1, 1)]
    assert g.play_from_graveyard(me, kx)
    run(g)
    pm = next(p for p in me.battlefield if p.name == "Kroxish")
    assert pm.counters.get("+1/+1") == 2


def test_sculler_returns_card_when_it_leaves():
    g, me, ops = new_game()
    ops[0].hand = [creature("Bomb", "6G", 7, 7), land("Forest", [G], basic=True)]
    sc = put(g, build("Sculler", "{W}{B}", "Artifact Creature — Zombie",
                      "When this creature enters, target opponent reveals their hand and you choose a "
                      "nonland card from it. Exile that card.\nWhen this creature leaves the battlefield, "
                      "return the exiled card to its owner's hand.", 2, 2), me)
    run(g)
    assert all(c.name != "Bomb" for c in ops[0].hand)
    g.to_graveyard(sc, "test")
    run(g)
    assert any(c.name == "Bomb" for c in ops[0].hand)


def test_zone_and_combat_atomics():
    g, me, ops = new_game()
    from cardsdb import _effect_any
    fl = put(g, land("Field", [W], basic=False), ops[0])
    _effect_any("put target land on top of its owner's library")(g, me)
    assert fl not in ops[0].battlefield and ops[0].library[-1].name == "Field"
    art = put(g, build("Relic", "{3}", "Artifact", ""), ops[0])
    _effect_any("choose target artifact or enchantment. its owner shuffles it into their library")(g, me)
    assert art not in ops[0].battlefield and any(c.name == "Relic" for c in ops[0].library)
    mine = [put(g, creature(f"M{k}", "1G", 2, 2), me) for k in range(3)]
    _effect_any("up to two target creatures each get +2/+0 and gain first strike until end of turn")(g, me)
    assert sum(1 for pm in mine if pm.power == 4 and pm.has("first_strike")) == 2
    lands = [put(g, land(f"L{k}", [G], basic=False), ops[0]) for k in range(3)]
    _effect_any("destroy two target lands")(g, me)
    assert sum(1 for pm in lands if pm in ops[0].battlefield) == 1


def test_scavenge_and_outlast_rewrites():
    sc = build("Scav", "{1}{G}", "Creature — Ooze", "Scavenge {3}{G}{G}", 3, 2)
    assert any("graveyard" in str(ab.get("label", "")).lower() or ab.get("from_graveyard")
               for ab in (sc.activated_abilities or ())) or getattr(sc, "gy_abilities", None)
    ol = build("Outl", "{1}{W}", "Creature — Human", "Outlast {1}{W}", 1, 2)
    assert any(ab.get("tap") and ab.get("sorcery_speed") for ab in ol.activated_abilities)


def test_audit_counts_real_mana_lines_and_wired_keywords():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    import audit_coverage as a
    row = {"name": "Bog", "type_line": "Land", "oracle_text": "This land enters tapped.\n{T}: Add {B}.",
           "produced_mana": ["B"], "color_identity": ["B"]}
    assert a._mana_line_ok("{T}: Add {B}.", row)
    assert not a._mana_line_ok("{T}: Add {G}.", row)
