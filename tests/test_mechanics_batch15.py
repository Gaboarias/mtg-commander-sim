"""Batch 15: disparos extra por evento (lanzar hechizo de un color, ciclar, daño a un
rival, atacar con N, entra algo del rival, artefacto al cementerio, criatura dañada
que muere), ETB + boca arriba / deja el campo, tierra que entra enderezada."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_player_casts_colored_spell():
    g, me, ops = new_game()
    put(g, build("Shrine", "{2}", "Artifact", "Whenever a player casts a black spell, you gain 1 "
                 "life."), me)
    life = me.life
    g.emit("any_cast", caster=ops[0], card=creature("Bk", "1B", 1, 1))
    g.emit("any_cast", caster=ops[0], card=creature("Gr", "1G", 1, 1))
    run(g)
    assert me.life == life + 1


def test_cycle_trigger():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(U,))
    put(g, build("Drake", "{2}{U}", "Creature — Drake", "Whenever you cycle a card, you gain 2 "
                 "life.", 2, 2), me)
    cy = build("Cyc", "{3}{U}", "Instant", "Draw a card.\nCycling {2}", keywords=["Cycling"])
    me.hand.append(cy)
    me.library += [creature("X", "1G", 1, 1)]
    life = me.life
    assert g.cycle_card(me, cy)
    run(g)
    assert me.life == life + 2


def test_noncombat_damage_to_opponent_trigger():
    g, me, ops = new_game()
    pyro = put(g, build("Pyro", "{1}{R}", "Creature — Human", "Whenever this creature deals "
                        "damage to an opponent, you gain 2 life.", 1, 1), me)
    life = me.life
    g.deal_damage(pyro, ops[0], 1)
    run(g)
    assert me.life == life + 2
    foe = put(g, creature("Foe", "1G", 2, 3), ops[0])
    g.deal_damage(pyro, foe, 1)
    run(g)
    assert me.life == life + 2


def test_attack_with_n_and_opponent_land_enters():
    g, me, ops = new_game()
    put(g, build("Banner", "{2}", "Artifact", "Whenever you attack with two or more creatures, "
                 "you gain 3 life.\nWhenever a land an opponent controls enters, you gain 1 life."),
        me)
    a = put(g, creature("A", "1G", 1, 1), me)
    b = put(g, creature("B", "1G", 1, 1), me)
    life = me.life
    a.attacking = b.attacking = ops[0]
    g.emit("you_attack", player=me)
    run(g)
    assert me.life == life + 3
    put(g, land("Forest", [G], basic=True), ops[0])
    run(g)
    assert me.life == life + 4
    put(g, land("Forest", [G], basic=True), me)
    run(g)
    assert me.life == life + 4


def test_artifact_to_graveyard_and_damaged_creature_dies():
    g, me, ops = new_game()
    put(g, build("Scrapper", "{1}{R}", "Creature — Goblin", "Whenever an artifact is put into a "
                 "graveyard from the battlefield, you gain 1 life.", 1, 1), me)
    rock = put(g, build("Rock", "{1}", "Artifact", ""), ops[0])
    life = me.life
    g.to_graveyard(rock, "test")
    run(g)
    assert me.life == life + 1
    vamp = put(g, build("Vamp", "{2}{B}", "Creature — Vampire", "Whenever a creature dealt damage "
                        "by this creature this turn dies, put a +1/+1 counter on this creature.",
                        2, 2), me)
    foe = put(g, creature("Foe", "1G", 2, 2), ops[0])
    g.deal_damage(vamp, foe, 2)
    g.sba()
    run(g)
    assert vamp.counters.get("+1/+1") == 1


def test_enters_or_leaves_and_land_enters_untapped():
    g, me, ops = new_game()
    life = me.life
    el = put(g, build("Tidal", "{2}{U}", "Creature — Elemental", "When this creature enters or "
                      "leaves the battlefield, you gain 2 life.", 2, 2), me)
    run(g)
    assert me.life == life + 2
    g.to_graveyard(el, "test")
    run(g)
    assert me.life == life + 4
    import cardsdb
    ld = cardsdb.build_card_from_data({"name": "Spring", "type_line": "Land", "produced_mana": ["G"],
                                       "oracle_text": "{T}: Add {G}.\nWhen this land enters untapped, "
                                                      "you gain 1 life."})
    put(g, ld, me)
    run(g)
    assert me.life == life + 5


def test_evasion_except_flying_and_by_color():
    g, me, ops = new_game()
    sk = put(g, build("Sky", "{1}{U}", "Creature — Spirit", "This creature can't be blocked except "
                      "by creatures with flying.", 2, 2), me)
    ground = put(g, creature("Ground", "1G", 2, 2), ops[0])
    bird = put(g, build("Bird", "{1}{W}", "Creature — Bird", "Flying", 1, 1, keywords=["Flying"]),
               ops[0])
    assert not g._can_block_evasion(sk, ground) and g._can_block_evasion(sk, bird)
    pk = put(g, build("Pal", "{1}{B}", "Creature — Zombie", "This creature can't be blocked by "
                      "white creatures.", 2, 2), me)
    knight = put(g, creature("Knight", "1W", 2, 2), ops[0])
    assert not g._can_block_evasion(pk, knight) and g._can_block_evasion(pk, ground)


def test_hand_size_and_shroud_and_silence():
    g, me, ops = new_game()
    put(g, build("Stunt", "{2}", "Artifact", "Each opponent's maximum hand size is reduced by two."), me)
    assert g.max_hand_size(ops[0]) == 5 and g.max_hand_size(me) == 7
    put(g, build("Veil", "{W}", "Enchantment", "You have shroud."), me)
    assert me.has_hexproof()
    give_lands(g, ops[0], 2, colors=(B,))
    sp = build("Silence", "{W}", "Instant", "Your opponents can't cast spells this turn.")
    sp.on_cast_resolve(g, me, [])
    x = build("Night", "{B}", "Instant", "You gain 1 life.")
    ops[0].hand.append(x)
    assert not g.cast(ops[0], x)


def test_alt_costs_fireblast_and_pay_less():
    g, me, ops = new_game()
    from cards import land as _land
    for _ in range(2):
        put(g, _land("Mountain", [R], basic=True), me)
    me.battlefield[0].tapped = me.battlefield[1].tapped = True
    fb = build("Fireblast", "{4}{R}{R}", "Instant", "You may sacrifice two Mountains rather than pay "
               "this spell's mana cost.\nFireblast deals 4 damage to any target.")
    me.hand.append(fb)
    life = ops[0].life
    assert g.cast(me, fb)
    run(g)
    assert not any(pm.name == "Mountain" for pm in me.battlefield) and ops[0].life == life - 4
    give_lands(g, me, 2, colors=(U,))
    cheap = build("Cheap", "{5}{U}", "Sorcery", "You may pay {1}{U} rather than pay this spell's "
                  "mana cost.\nDraw two cards.")
    assert g.effective_cost(me, cheap).cmc == 2


def test_qualified_anthem_and_extra_land_and_multi_pump():
    g, me, ops = new_game()
    put(g, build("Wind", "{1}{U}", "Enchantment", "Creatures you control with flying get +1/+1."), me)
    fl = put(g, build("Bird", "{1}{W}", "Creature — Bird", "Flying", 1, 1, keywords=["Flying"]), me)
    gr = put(g, creature("Bear", "1G", 2, 2), me)
    assert fl.power == 2 and gr.power == 2
    sp = build("Explore", "{1}{G}", "Sorcery", "You may play an additional land this turn.\nDraw a card.")
    sp.on_cast_resolve(g, me, [])
    assert g.land_limit(me) == 2
    a = put(g, creature("A", "1B", 1, 1), ops[0])
    b = put(g, creature("B", "1B", 1, 1), ops[0])
    pump = build("Shrivel", "{B}", "Instant", "Two target creatures each get -1/-1 until end of turn.")
    pump.on_cast_resolve(g, me, [])
    run(g)
    assert a not in ops[0].battlefield and b not in ops[0].battlefield


def test_cost_less_per_death_and_tuck():
    g, me, ops = new_game()
    sp = build("Gruesome", "{5}{B}", "Sorcery", "This spell costs {1} less to cast for each creature "
               "that died this turn.\nDraw a card.")
    assert g.effective_cost(me, sp).cmc == 6
    for k in range(2):
        v = put(g, creature(f"V{k}", "1G", 1, 1), ops[0])
        g.to_graveyard(v, "test")
    assert g.effective_cost(me, sp).cmc == 4
    big = put(g, creature("Big", "6G", 6, 6), ops[0])
    tuck = build("Tuck", "{1}{W}", "Instant", "Put target creature into its owner's library second "
                 "from the top.")
    tuck.on_cast_resolve(g, me, [])
    assert big not in ops[0].battlefield and ops[0].library[-2].name == "Big"


def test_cast_from_top_and_ui_option():
    import interactive
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(G,))
    put(g, build("Sight", "{2}{U}{U}{U}", "Enchantment", "You may cast creature spells from the top "
                 "of your library."), me)
    me.library.append(creature("TopBear", "1G", 2, 2))
    assert g.castable_from_top(me) is not None
    assert g.cast_from_top(me)
    run(g)
    assert any(pm.name == "TopBear" for pm in me.battlefield)


def test_aura_infect_and_no_damage_and_land_type():
    g, me, ops = new_game()
    bear = put(g, creature("Bear", "1G", 2, 2), me)
    put(g, build("Virulence", "{1}{B}", "Enchantment — Aura", "Enchant creature\nEnchanted creature "
                 "has infect."), me)
    assert bear.has("infect")
    foe = put(g, creature("Foe", "3R", 4, 4), ops[0])
    put(g, build("Pacify", "{W}", "Enchantment — Aura", "Enchant creature\nPrevent all damage that "
                 "would be dealt by enchanted creature."), me)
    life = me.life
    g.deal_damage(foe, me, 4, combat=True)
    assert me.life == life
    from cards import land as _land
    fo = put(g, _land("Forest", [G], basic=True), ops[0])
    put(g, build("Evil Presence", "{B}", "Enchantment — Aura", "Enchant land\nEnchanted land is a "
                 "Swamp."), me)
    assert ops[0].produced(fo) == {"B": 1}


def test_first_creature_spell_discount():
    g, me, ops = new_game()
    put(g, build("Herald", "{2}{G}", "Creature — Elf", "The first creature spell you cast each turn "
                 "costs {1} less to cast.", 2, 2), me)
    bear = creature("Bear2", "2G", 2, 2)
    assert g.effective_cost(me, bear).cmc == 2
    me._cr_cast = (g.turn, 1)
    assert g.effective_cost(me, bear).cmc == 3
