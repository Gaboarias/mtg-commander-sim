"""Batch 24: "you may <efecto>" genérico, castigo ("may sacrifice… If they don't"),
"unless you pay", revelar/exiliar hasta encontrar un tipo, Enduring, aturdir,
bombeos de grupo filtrados, Archetypes, keywords por tipo, condiciones nuevas,
activadas solo en el mantenimiento y equipar con coste no de maná."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_generic_you_may_and_unless_pay():
    import cardsdb
    assert cardsdb._effect_any("you may sacrifice it. if you do, proliferate") is not None
    g, me, ops = new_game()
    e = cardsdb._effect_any("sacrifice this creature unless you pay {2}")
    cr = put(g, creature("Hellion", "1R", 4, 4), me)
    e(g, me, cr)
    assert cr not in me.battlefield                      # sin maná: se sacrifica
    cr2 = put(g, creature("Hellion2", "1R", 4, 4), me)
    give_lands(g, me, 2, colors=(R,))
    e(g, me, cr2)
    assert cr2 in me.battlefield


def test_punisher_choice():
    import cardsdb
    g, me, ops = new_game()
    e = cardsdb._effect_any("target opponent may sacrifice a creature. if they don't, they lose 3 life")
    life = ops[0].life
    e(g, me)
    assert life - ops[0].life == 3                       # sin criaturas: pierde vida
    tok = put(g, creature("Tok", "", 1, 1), ops[0])
    tok.is_token = True
    e(g, me)
    assert tok not in ops[0].battlefield and life - ops[0].life == 3


def test_reveal_until_kind_and_enduring():
    import cardsdb
    g, me, ops = new_game()
    me.library = [creature("Bottom", "1G", 1, 1), creature("Big", "3G", 3, 3), land("F", [G], basic=True)]
    cardsdb._effect_any("reveal cards from the top of your library until you reveal a creature card. put that card "
                        "onto the battlefield and the rest on the bottom of your library in a random order.")(g, me)
    run(g)
    assert any(pm.name == "Big" for pm in me.battlefield) and me.library[0].name == "F"
    en = put(g, build("Enduring", "{2}{G}", "Enchantment Creature — Bear", "When this creature dies, if it was a "
                      "creature, return it to the battlefield under its owner's control. It's an enchantment.", 3, 3), me)
    g.to_graveyard(en, "test")
    run(g)
    back = [pm for pm in me.battlefield if pm.name == "Enduring"]
    assert back and not back[0].is_creature() and "enchantment" in back[0].card.types


def test_stun_and_group_pumps_and_untap():
    import cardsdb
    g, me, ops = new_game()
    foe = put(g, creature("Foe", "1G", 2, 2), ops[0])
    cardsdb._effect_any("tap up to one target creature. put a stun counter on it.")(g, me)
    assert foe.tapped and foe.counters.get("stun") == 1
    ops[0].library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    g.begin_turn(ops[0])
    assert foe.tapped and not foe.counters.get("stun")
    w = put(g, creature("War", "1R", 2, 2, subtypes=("Warrior",)), me)
    k = put(g, creature("Elf", "1G", 2, 2), me)
    w.attacking = k.attacking = ops[0]
    cardsdb._effect_any("attacking warriors get +1/+0 until end of turn")(g, me)
    assert w.power == 3 and k.power == 2
    w.tapped = k.tapped = True
    cardsdb._effect_any("untap each creature you control")(g, me)
    assert not w.tapped and not k.tapped


def test_archetype_kind_grants_and_planeswalker_anthem():
    g, me, ops = new_game()
    bird = put(g, build("Bird", "{1}{W}", "Creature — Bird", "Flying", 1, 1, keywords=["Flying"]), ops[0])
    put(g, build("Arch", "{4}{U}{U}", "Enchantment Creature — Human", "Creatures your opponents control lose flying "
                 "and can't have or gain flying.", 3, 2), me)
    assert not bird.has("flying")
    e1 = put(g, build("E1", "{1}", "Enchantment", ""), me)
    put(g, build("Aura", "{1}", "Enchantment", "Other enchantments you control have shroud."), me)
    assert e1.has("shroud")
    cl = put(g, creature("Cl", "1W", 1, 1, subtypes=("Cleric",)), me)
    put(g, build("Dev", "{1}", "Enchantment", "Cleric creatures have vigilance."), me)
    assert cl.has("vigilance")
    pw = build("Walker", "{2}{W}", "Legendary Planeswalker — Ajani", "Creatures you control have vigilance.\n"
               "+1: You gain 2 life.")
    assert pw.anthem_keywords and "vigilance" in pw.anthem_keywords


def test_new_conditions_batch24():
    import cardsdb
    for c in ("a phyrexian died under your control this turn", "a player discarded a card this turn",
              "you control 2 or fewer lands", "an opponent controls 2 or more creatures", "you don't control a food",
              "all nonland permanents you control are white", "your devotion to white and black is 2 or greater",
              "it was the second spell you cast this turn", "you cycled 2 or more cards this turn",
              "2 or more artifacts entered the battlefield under your control this turn", "its spectacle cost was paid"):
        assert cardsdb._cond_gc(c) is not None, c
    g, me, ops = new_game()
    f = cardsdb._cond_gc("you control 2 or fewer lands")
    give_lands(g, me, 2)
    assert f(g, me)
    give_lands(g, me, 1)
    assert not f(g, me)


def test_upkeep_only_activation_and_equip_sacrifice():
    g, me, ops = new_game()
    au = put(g, build("Augur", "{W}", "Creature — Human Cleric", "Sacrifice this creature: You gain 3 life. Activate "
                      "only during your upkeep.", 1, 3), me)
    assert not g.activate_ability(au, 0)                 # fuera del mantenimiento
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    life = me.life
    g.begin_turn(me)
    run(g)
    assert me.life == life + 3 and au not in me.battlefield
    eq = build("Hauberk", "{4}", "Artifact — Equipment", "Equipped creature gets +4/+2.\nEquip—Sacrifice a creature.")
    ab = next(a for a in eq.activated_abilities if a["label"] == "Equipar")
    assert ab["sacrifice_other"] == {"count": 1, "type": "creature"} and ab["cost"].cmc == 0
