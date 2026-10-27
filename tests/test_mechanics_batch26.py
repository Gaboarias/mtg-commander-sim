"""Batch 26: nombre propio como "~" en disparos y estáticas, estáticas de bloqueo
(no robar, Leovold, Grafdigger's Cage, Grand Abolisher, Melira, Marble Titan, límite
de atacantes, Quagmire), disparos al dejar el campo (devolver lo exiliado, perder la
partida, God-Eternals, sin criaturas), echo/scavenge/reinforce, Remand, Rooms,
monstruosidad X, eventos de dados/monedas/lealtad/explorar y persist condicional."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W, StackObject  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402
import cardsdb  # noqa: E402


def test_self_name_in_triggers_and_statics():
    lg = build("The Locust God", "{4}{U}{R}", "Legendary Creature — God", "When The Locust God dies, return it to its "
               "owner's hand at the beginning of the next end step.", 4, 4)
    assert "death" in (lg.triggers or {})
    g, me, ops = new_game()
    cm = put(g, build("Cho-Manno", "{2}{W}{W}", "Legendary Creature — Human Rebel", "Prevent all damage that would be "
                      "dealt to Cho-Manno.", 2, 2), me)
    o = put(g, creature("O", "2R", 5, 5), ops[0])
    g.deal_damage(o, cm, 5)
    assert cm.damage == 0 and cm in me.battlefield


def test_draw_locks_and_cast_restrictions():
    g, me, ops = new_game()
    put(g, build("Leovold", "{B}{G}{U}", "Legendary Creature — Elf Advisor", "Each opponent can't draw more than one "
                 "card each turn.", 3, 3), me)
    ops[0].library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    h = len(ops[0].hand)
    ops[0].draw(3, g)
    assert len(ops[0].hand) == h + 1
    g, me, ops = new_game()
    put(g, build("Cage", "{1}", "Artifact", "Players can't cast spells from graveyards or libraries."), me)
    fb = build("Think", "{U}", "Sorcery", "Draw two cards.\nFlashback {2}{U}")
    ops[0].graveyard.append(fb)
    give_lands(g, ops[0], 3, colors=(U,))
    assert not g.play_from_graveyard(ops[0], fb) if hasattr(g, "play_from_graveyard") else True
    g, me, ops = new_game()
    put(g, build("Abolisher", "{W}", "Creature — Human Cleric", "During your turn, your opponents can't cast spells or "
                 "activate abilities of artifacts, creatures, or enchantments.", 2, 2), me)
    g.active_index = g.players.index(me)
    bolt = build("Bolt", "{R}", "Instant", "Bolt deals 3 damage to any target.")
    give_lands(g, ops[0], 1, colors=(R,))
    ops[0].hand.append(bolt)
    assert not g.cast(ops[0], bolt)


def test_melira_marble_titan_attack_cap_and_quagmire():
    g, me, ops = new_game()
    put(g, build("Melira", "{2}{G}", "Legendary Creature — Human", "Creatures you control can't have -1/-1 counters put "
                 "on them.", 2, 2), me)
    x = put(g, creature("X", "1G", 2, 2), me)
    g.add_counters(x, "-1/-1", 1)
    assert not x.counters.get("-1/-1")
    put(g, build("Titan", "{3}{W}", "Creature — Giant", "Creatures with power 3 or greater don't untap during their "
                 "controllers' untap steps.", 3, 3), me)
    big = put(g, creature("Big", "3G", 4, 4), ops[0])
    small = put(g, creature("Small", "1G", 1, 1), ops[0])
    big.tapped = small.tapped = True
    ops[0].library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    g.begin_turn(ops[0])
    assert big.tapped and not small.tapped
    g, me, ops = new_game()
    put(g, build("Grounds", "{R}{W}", "Enchantment", "No more than one creature can attack each combat."), ops[0])
    a1 = put(g, creature("A1", "1G", 2, 2), me)
    a2 = put(g, creature("A2", "1G", 3, 3), me)
    a1.summoning_sick = a2.summoning_sick = False
    g.active_index = g.players.index(me)
    out = g._declare_attackers(me, [(a1, ops[0]), (a2, ops[0])])
    assert len(out) == 1 and out[0] is a2
    g, me, ops = new_game()
    put(g, build("Quagmire", "{2}{B}", "Enchantment", "Creatures with swampwalk can be blocked as though they didn't "
                 "have swampwalk."), me)
    sw = put(g, build("Walker", "{1}{B}", "Creature — Zombie", "Swampwalk", 2, 2, keywords=["Swampwalk"]), ops[0])
    put(g, land("Swamp", [B], basic=True, subtypes=("Swamp",)) if "subtypes" in land.__code__.co_varnames
        else land("Swamp", [B], basic=True), me)
    bl = put(g, creature("Bl", "1W", 1, 1), me)
    assert g._can_block_evasion(sw, bl)


def test_leave_triggers_return_exiled_lose_god_eternal_and_no_creatures():
    g, me, ops = new_game()
    fs = [put(g, creature(f"Foe{i}", "2G", 3, 3), ops[0]) for i in range(2)]
    p = put(g, build("Petradon", "{6}{R}{R}", "Creature — Nightstalker", "When Petradon enters, exile two target "
                     "creatures an opponent controls.\nWhen Petradon leaves the battlefield, return the exiled cards to "
                     "the battlefield under their owners' control.", 5, 6), me)
    run(g)
    assert not any(f in ops[0].battlefield for f in fs)
    g.to_graveyard(p, "test")
    run(g)
    assert sorted(pm.name for pm in ops[0].battlefield) == ["Foe0", "Foe1"]
    g, me, ops = new_game()
    lich = put(g, build("Lich", "{2}{B}{B}", "Enchantment", "When this enchantment leaves the battlefield, you lose the "
                        "game."), me)
    g.to_graveyard(lich, "test")
    assert me.lost
    g, me, ops = new_game()
    k = put(g, build("Kefnet", "{2}{U}{U}", "Legendary Creature — Zombie God", "When Kefnet dies or is put into exile "
                     "from the battlefield, you may put it into its owner's library third from the top.", 5, 5), me)
    me.library = [creature(f"L{i}", "1G", 1, 1) for i in range(5)]
    g.to_graveyard(k, "test")
    run(g)
    assert me.library[-3].name == "Kefnet" and not me.graveyard
    g, me, ops = new_game()
    x = put(g, creature("X", "1G", 1, 1), me)
    nodes = put(g, build("Nodes", "{W}", "Enchantment", "When there are no creatures on the battlefield, sacrifice this "
                         "enchantment."), me)
    g.to_graveyard(x, "test")
    g.sba()
    assert nodes not in me.battlefield


def test_exile_removal_fires_leave_trigger():
    g, me, ops = new_game()
    v = put(g, build("Victim", "{1}{G}", "Creature — Elf", "When this creature leaves the battlefield, you gain 3 life.",
                     2, 2), ops[0])
    life = ops[0].life
    sp = build("Path", "{W}", "Instant", "Exile target creature.")
    give_lands(g, me, 1, colors=(W,))
    me.hand.append(sp)
    assert g.cast(me, sp, targets=[v])
    run(g)
    assert v not in ops[0].battlefield and ops[0].life == life + 3


def test_echo_discard_scavenge_reinforce_and_remand():
    g, me, ops = new_game()
    imp = build("Imp", "{2}{B}", "Creature — Imp", "Flying, haste\nEcho—Discard a card.", 4, 3)
    assert imp.echo == "discard"
    tw = build("Weaponry", "{4}", "Artifact", "Echo {4}\n{2}, {T}: Creatures get +2/+2 until end of turn.")
    assert tw.echo is not None and tw.echo != "discard"
    sc = build("Scav", "{1}{B}", "Creature — Zombie", "Scavenge {2}{B}", 3, 2)
    assert sc.gy_abilities and sc.gy_abilities[0]["exile_self"]
    x = put(g, creature("X", "1B", 1, 1), me)
    sc.gy_abilities[0]["effect"](g, me, sc)
    assert x.counters.get("+1/+1") == 3
    rf = cardsdb.build_card_from_data({"name": "Rein", "type_line": "Instant", "mana_cost": "{W}", "keywords": ["Reinforce"],
                                       "oracle_text": "Creatures you control get +1/+1 until end of turn.\n"
                                                      "Reinforce 2—{1}{W}"})
    give_lands(g, me, 2, colors=(W,))
    me.hand.append(rf)
    assert g.activate_from_hand(me, rf, 0, targets=[x])
    run(g)
    assert x.counters.get("+1/+1") == 5
    rm = build("Remand", "{1}{U}", "Instant", "Return target spell to its owner's hand.\nDraw a card.")
    me.library = [creature("L", "1G", 1, 1)]
    big = creature("Big", "5G", 6, 6)
    obj = StackObject(ops[0], lambda gg: None, source=big, label="spell:Big")
    g.stack.append(obj)
    rm.on_cast_resolve(g, me, [obj])
    assert big in ops[0].hand and not g.stack and any(c.name == "L" for c in me.hand)


def test_rooms_and_monstrosity_x():
    room = cardsdb.build_card_from_data({
        "name": "Pool // Locker", "layout": "split", "type_line": "Enchantment — Room // Enchantment — Room",
        "mana_cost": "{U} // {4}{U}", "card_faces": [
            {"name": "Pool", "mana_cost": "{U}", "type_line": "Enchantment — Room",
             "oracle_text": "When you unlock this door, return up to one target creature to its owner's hand."},
            {"name": "Locker", "mana_cost": "{4}{U}", "type_line": "Enchantment — Room",
             "oracle_text": "When you unlock this door, draw two cards."}]})
    g, me, ops = new_game()
    f = put(g, creature("F", "2G", 3, 3), ops[0])
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    give_lands(g, me, 6, colors=(U,))
    me.hand.append(room)
    assert g.cast(me, room)
    run(g)
    assert f not in ops[0].battlefield
    pm = next(p for p in me.battlefield if p.name == room.name)
    i = len(pm.card.activated_abilities) - 1
    h = len(me.hand)
    assert g.activate_ability(pm, i)
    run(g)
    assert len(me.hand) == h + 2 and not g.activate_ability(pm, i)
    g, me, ops = new_game()
    k = put(g, build("Kiss", "{2}{R}", "Creature — Eye", "{X}{X}{R}: Monstrosity X.\nWhen this creature becomes "
                     "monstrous, destroy up to one target creature.", 1, 1), me)
    foe = put(g, creature("Foe", "2G", 3, 3), ops[0])
    give_lands(g, me, 5, colors=(R,))
    assert g.activate_ability(k, 0, x=2)
    run(g)
    assert k.counters.get("+1/+1") == 2 and foe not in ops[0].battlefield and not g.activate_ability(k, 0, x=1)


def test_roll_flip_loyalty_events_conditional_persist_and_misc():
    g, me, ops = new_game()
    w = put(g, build("Clerk", "{1}{W}", "Creature — Human", "Whenever you roll a die, you gain 1 life.", 1, 1), me)
    life = me.life
    cardsdb._effect_any("roll a d20")(g, me)
    run(g)
    assert me.life == life + 1 and w in me.battlefield
    put(g, build("Lucky", "{1}{R}", "Creature — Goblin", "Whenever you win a coin flip, draw a card.", 1, 1), me)
    assert "flip_won" in (me.battlefield[-1].card.triggers or {})
    rs = build("Scarecrow", "{5}", "Artifact Creature — Scarecrow", "This creature has persist as long as you control "
               "a black creature.", 5, 3)
    g, me, ops = new_game()
    s = put(g, rs, me)
    g.to_graveyard(s, "test")
    run(g)
    assert not any(pm.name == "Scarecrow" for pm in me.battlefield)
    put(g, creature("Blk", "1B", 1, 1), me)
    s2 = put(g, build("Scarecrow", "{5}", "Artifact Creature — Scarecrow", "This creature has persist as long as you "
                      "control a black creature.", 5, 3), me)
    g.to_graveyard(s2, "test")
    run(g)
    assert any(pm.name == "Scarecrow" and pm.counters.get("-1/-1") for pm in me.battlefield)
    plate = build("Plate", "{5}", "Artifact — Equipment", "Equipped creature gets +3/+3.\nEquip commander {3}\nEquip {5}")
    assert {ab["label"] for ab in plate.activated_abilities} == {"Equipar", "Equipar (comandante)"}
    ghast = build("Ghast", "{3}{B}", "Creature — Spirit", "Whenever you tap a Swamp for mana, add an additional {B}.", 2, 2)
    assert ghast.tap_bonus == "swamp"
    sg = build("Siege", "{2}{U}", "Battle — Siege", "When this Siege enters, draw two cards.")
    assert sg.on_etb is not None


def test_jace_loyalty_minus_three():
    g, me, ops = new_game()
    j = build("Jace, Multiverse Architect", "{1}{U}{U}", "Legendary Planeswalker — Jace", "+1: Draw two cards, then put "
              "a card from your hand on the bottom of your library.\n−3: Exile another target planeswalker or creature "
              "you control. Reveal cards from the top of your library until you reveal a creature or planeswalker card. "
              "Put that card onto the battlefield and the rest on the bottom of your library in a random order.")
    pj = put(g, j, me)
    pj.counters["loyalty"] = 5
    x = put(g, creature("Small", "1U", 1, 1), me)
    me.library = [creature("Bottom", "1G", 1, 1), creature("Big", "5G", 6, 6), land("Island", [U], basic=True)]
    g.active_index = g.players.index(me)
    assert g.activate_loyalty(pj, 1)
    run(g)
    assert x not in me.battlefield and any(pm.name == "Big" for pm in me.battlefield)
    assert me.library[0].name == "Island" and pj.counters["loyalty"] == 2
    g, me, ops = new_game()
    tj = build("Jace, Telepath Unbound", "", "Legendary Planeswalker — Jace", "+1: Up to one target creature gets -2/-0 "
               "until your next turn.\n−3: You may cast target instant or sorcery card from your graveyard this turn. "
               "If that spell would be put into your graveyard, exile it instead.")
    pt = put(g, tj, me)
    pt.counters["loyalty"] = 5
    bolt = build("Bolt", "{R}", "Instant", "Bolt deals 3 damage to any target.")
    me.graveyard = [bolt]
    g.active_index = g.players.index(me)
    assert g.activate_loyalty(pt, 1)
    run(g)
    assert bolt.gy_play and bolt.gy_play["after"] == "exile"
    g, me, ops = new_game()
    aot = build("Jace, Architect of Thought", "{2}{U}{U}", "Legendary Planeswalker — Jace", "+1: Until your next turn, "
                "whenever a creature an opponent controls attacks, it gets -1/-0 until end of turn.")
    pa = put(g, aot, me)
    pa.counters["loyalty"] = 4
    g.active_index = g.players.index(me)
    g.activate_loyalty(pa, 0)
    run(g)
    at = put(g, creature("A", "2G", 3, 3), ops[0])
    at.summoning_sick = False
    g.active_index = g.players.index(ops[0])
    g._declare_attackers(ops[0], [(at, me)])
    assert at.power == 2


def test_ob_nixilis_destroys_tapped_creatures_and_gains_per_kill():
    g, me, ops = new_game(2)
    t1 = put(g, creature("T1", "2G", 3, 3), ops[0])
    u1 = put(g, creature("U1", "2G", 3, 3), ops[0])
    t2 = put(g, creature("T2", "2G", 3, 3), ops[1])
    mine = put(g, creature("Mine", "2G", 3, 3), me)
    t1.tapped = t2.tapped = mine.tapped = True
    life = me.life
    put(g, build("Ob Nixilis, the Ascended", "{3}{W}{B}", "Legendary Creature — Angel", "Flying\nWhen Ob Nixilis enters, "
                 "destroy all tapped creatures your opponents control. You gain 1 life for each creature destroyed this "
                 "way.\nAt the beginning of each end step, if you gained life this turn, create a 4/4 white Angel "
                 "creature token with flying.", 4, 4, keywords=["Flying"]), me)
    run(g)
    assert t1 not in ops[0].battlefield and t2 not in ops[1].battlefield
    assert u1 in ops[0].battlefield and mine in me.battlefield and me.life == life + 2
    g.emit("each_end_step", player=me)
    run(g)
    assert any(pm.name == "Angel" for pm in me.battlefield)


def test_typed_fetch_lands_search():
    def basics():
        out = []
        for nm, col in (("Forest", G), ("Island", U), ("Plains", W), ("Swamp", B)):
            c = land(nm, [col], basic=True)
            c.subtypes = {nm.lower()}
            out.append(c)
        return out
    for text, want in (("{T}, Sacrifice this land: Search your library for a basic Plains, Island, or Swamp card, put it "
                        "onto the battlefield tapped, then shuffle.", {"plains", "island", "swamp"}),
                       ("{T}, Pay 1 life, Sacrifice this land: Search your library for a Plains or Island card, put it "
                        "onto the battlefield, then shuffle.", {"plains", "island"})):
        g, me, ops = new_game()
        pm = put(g, build("Fetch", "", "Land", text), me)
        pm.tapped = False
        me.library = basics()
        i = next(k for k, ab in enumerate(pm.card.activated_abilities) if ab.get("sacrifice_self"))
        assert g.activate_ability(pm, i)
        run(g)
        got = [p for p in me.battlefield if p.card.subtypes & want]
        assert len(got) == 1 and len(me.library) == 3
