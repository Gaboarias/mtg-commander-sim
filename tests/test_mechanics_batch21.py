"""Batch 21: condiciones de intervención amplias, energía, 'where X is' / 'equal
to', copiar hechizos disparados, costes extra de activadas, anthems condicionales,
restricciones de ataque/bloqueo, cambios temporales, elecciones al entrar y
prevención estática."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_intervening_if_monarch_and_another_subtype():
    g, me, ops = new_game()
    life = me.life
    put(g, build("Geist", "{1}{W}", "Creature — Spirit",
                 "When this creature enters, if you control another Spirit, you gain 3 life.", 1, 1), me)
    assert me.life == life
    put(g, build("Geist2", "{1}{W}", "Creature — Spirit",
                 "When this creature enters, if you control another Spirit, you gain 3 life.", 1, 1), me)
    assert me.life == life + 3


def test_energy_paid_for_activation_and_optional_trigger():
    g, me, ops = new_game()
    pm = put(g, build("Basker", "{2}{G}", "Creature — Elemental",
                      "Pay {E}: This creature gets +1/+1 until end of turn.", 2, 2), me)
    me.energy = 1
    assert g.activate_ability(pm, 0)
    run(g)
    assert pm.power == 3 and me.energy == 0
    assert not g.activate_ability(pm, 0)


def test_where_x_and_equal_to_amounts():
    import cardsdb
    g, me, ops = new_game()
    for k in range(3):
        put(g, creature(f"C{k}", "1G", 2, 2), me)
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(10)]
    h = len(me.hand)
    cardsdb._effect_any("draw cards equal to the number of creatures you control")(g, me)
    assert len(me.hand) == h + 3
    life = ops[0].life
    cardsdb._effect_any("each opponent loses x life, where x is the number of creatures you control")(g, me)
    assert ops[0].life == life - 3


def test_trigger_copies_the_cast_spell():
    g, me, ops = new_game()
    put(g, build("Echoes", "{4}", "Enchantment", "Whenever you cast an instant or sorcery spell, copy it. "
                 "You may choose new targets for the copy."), me)
    give_lands(g, me, 2, colors=(R,))
    sp = build("Shock", "{R}", "Instant", "Shock deals 2 damage to any target.")
    me.hand.append(sp)
    life = ops[0].life
    assert g.cast(me, sp)
    run(g)
    assert life - ops[0].life == 4


def test_activation_extra_costs_and_compound_restrictions():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(U,))
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    fb = put(g, build("Floodish", "{1}{U}", "Creature — Merfolk",
                      "{1}, Return a land you control to its owner's hand: Draw a card.", 1, 1), me)
    assert fb.card.activated_abilities[0]["extra_cost"][0][0] == "bounce"
    lands = sum(1 for pm in me.battlefield if pm.card.is_land())
    h = len(me.hand)
    assert g.activate_ability(fb, 0)
    run(g)
    assert sum(1 for pm in me.battlefield if pm.card.is_land()) == lands - 1
    tr = build("Trainee", "{2}{R}", "Creature — Human", "{T}: This creature deals 4 damage to target creature. "
               "Activate only if this creature's power is 4 or greater.", 2, 3)
    assert tr.activated_abilities and tr.activated_abilities[0].get("only_if") is not None


def test_conditional_group_anthem_and_source_condition():
    g, me, ops = new_game()
    put(g, build("Haunting", "{3}{W}", "Enchantment", "As long as you control three or more enchantments, "
                 "creatures you control have flying and vigilance."), me)
    b = put(g, creature("Bear", "1G", 2, 2), me)
    assert not b.has("flying")
    put(g, build("E2", "{1}", "Enchantment", ""), me)
    put(g, build("E3", "{1}", "Enchantment", ""), me)
    assert b.has("flying") and b.has("vigilance")
    st = put(g, build("Steelshaper", "{2}{W}", "Creature — Human",
                      "As long as this creature is equipped, other creatures you control get +1/+1.", 2, 2), me)
    assert b.power == 2
    eq = put(g, build("Sword", "{1}", "Artifact — Equipment", "Equip {1}"), me)
    eq.enchanting = st
    assert b.power == 3 and st.power == 2


def test_conditional_attack_restriction_and_no_counters():
    g, me, ops = new_game()
    m = put(g, build("Mouser", "{1}", "Artifact Creature — Cat", "This creature can't attack unless you control "
                     "another artifact.", 2, 2), me)
    m.summoning_sick = False
    assert not m.can_attack()
    put(g, build("Rock", "{1}", "Artifact", ""), me)
    assert m.can_attack()
    k = put(g, build("Keeper", "{4}{G}", "Creature — Human", "This creature can't have counters put on it.", 4, 4), me)
    g.add_counters(k, "+1/+1", 2)
    assert not k.counters.get("+1/+1")


def test_humble_and_lose_flying():
    import cardsdb
    g, me, ops = new_game()
    big = put(g, build("Wurm", "{6}{G}", "Creature — Wurm", "Trample", 7, 7, keywords=["Trample"]), ops[0])
    cardsdb._effect_any("until end of turn, target creature loses all abilities and has base power and toughness 0/1")(g, me)
    assert big.power == 0 and not big.has("trample")
    fl = put(g, build("Bird", "{1}{W}", "Creature — Bird", "Flying", 2, 2, keywords=["Flying"]), ops[0])
    cardsdb._effect_any("target creature loses flying until end of turn")(g, me)
    assert not fl.has("flying")


def test_chosen_name_locks_casting():
    g, me, ops = new_game()
    mm = put(g, build("Mage", "{W}{U}", "Creature — Human Wizard", "As this creature enters, choose a nonland card "
                      "name.\nSpells with the chosen name can't be cast.", 2, 2), me)
    assert getattr(mm, "chosen_name", None) == ops[0].command[0].name
    give_lands(g, ops[0], 5, colors=(B,))
    assert not g.cast(ops[0], ops[0].command[0], from_command=True)


def test_static_prevention_from_opponent_sources():
    g, me, ops = new_game()
    put(g, build("Ward", "{W}", "Enchantment", "If a source an opponent controls would deal damage to you, "
                 "prevent 1 of that damage."), me)
    ogre = put(g, creature("Ogre", "2R", 3, 3), ops[0])
    life = me.life
    g.deal_damage(ogre, me, 3, combat=True)
    assert life - me.life == 2


def test_cast_from_top_by_subtype():
    g, me, ops = new_game()
    put(g, build("Snoop", "{R}{R}", "Creature — Goblin", "You may cast Goblin spells from the top of your library.",
                 2, 2), me)
    me.library = [creature("Elf", "G", 1, 1), creature("Gob", "R", 1, 1, subtypes=("Goblin",))]
    assert g.castable_from_top(me) is not None
    me.library = [creature("Gob", "R", 1, 1, subtypes=("Goblin",)), creature("Elf", "G", 1, 1)]
    assert g.castable_from_top(me) is None


def test_kind_tuck_destroy_any_and_exhume():
    import cardsdb
    g, me, ops = new_game()
    ench = put(g, build("Pact", "{2}", "Enchantment", ""), ops[0])
    cardsdb._effect_any("put target artifact or enchantment on the bottom of its owner's library")(g, me)
    assert ench not in ops[0].battlefield and ops[0].library[0].name == "Pact"
    foes = [put(g, creature(f"F{k}", "1B", 2, 2), ops[0]) for k in range(3)]
    cardsdb._effect_any("destroy any number of target creatures")(g, me)
    assert not any(f in ops[0].battlefield for f in foes)
    me.graveyard.append(creature("Big", "5G", 6, 6))
    cardsdb._effect_any("each player puts a creature card from their graveyard onto the battlefield")(g, me)
    assert any(pm.name == "Big" for pm in me.battlefield)


def test_new_trigger_heads_death_union_and_opponent_land():
    g, me, ops = new_game()
    w = put(g, build("Watcher", "{2}{B}", "Creature — Zombie", "Whenever another creature or artifact you control dies, "
                     "put a +1/+1 counter on this creature.", 2, 2), me)
    x = put(g, creature("X", "1G", 1, 1), me)
    g.to_graveyard(x, "test")
    run(g)
    assert w.counters.get("+1/+1") == 1
    r = put(g, build("Dirt", "{2}{G}", "Creature — Wurm", "Whenever an opponent plays a land, put a +1/+1 counter "
                     "on this creature.", 3, 4), me)
    g.move_to_battlefield(land("Forest", [G], basic=True), ops[0])
    run(g)
    assert r.counters.get("+1/+1") == 1


def test_two_upkeep_triggers_on_one_card_both_fire():
    g, me, ops = new_game()
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    life = me.life
    put(g, build("Twice", "{3}", "Artifact", "At the beginning of your upkeep, you gain 1 life.\n"
                 "At the beginning of your upkeep, draw a card."), me)
    h = len(me.hand)
    g.begin_turn(me)
    run(g)
    assert me.life == life + 1 and len(me.hand) >= h + 1
