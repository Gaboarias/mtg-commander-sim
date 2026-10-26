"""Batch 23: disparos desde el cementerio, "return this card from your graveyard",
condiciones de intervención nuevas, mirar/revelar el tope según el tipo, tablas de
dado, tierras de almacenamiento, maná flotante con costes sin {T}, strive, read
ahead, exert, empower Jace, daño dividido generalizado y behold."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402


def test_graveyard_upkeep_trigger_returns_itself_not_best_creature():
    g, me, ops = new_game()
    gr = build("Remains", "{B}{B}{B}", "Creature — Horror", "At the beginning of your upkeep, if this card is in your "
               "graveyard, you may pay {B}{B}{B}. If you do, return it to your hand.", 1, 1)
    assert "upkeep" in gr.gy_perm_triggers
    big = creature("Big", "5G", 6, 6)
    me.graveyard = [big, gr]
    give_lands(g, me, 3, colors=(B,))
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    g.begin_turn(me)
    run(g)
    assert gr in me.hand and big in me.graveyard


def test_graveyard_landfall_and_death_triggers():
    g, me, ops = new_game()
    fb = build("Firebird", "{2}{R}{R}", "Creature — Phoenix", "Landfall — Whenever a land you control enters, you may "
               "pay {1}. If you do, return this card from your graveyard to the battlefield.", 3, 3)
    me.graveyard = [creature("Big", "5G", 6, 6), fb]
    give_lands(g, me, 2, colors=(R,))
    g.move_to_battlefield(land("Mountain", [R], basic=True), me)
    run(g)
    assert any(pm.name == "Firebird" for pm in me.battlefield)
    assert all(pm.name != "Big" for pm in me.battlefield)
    g, me, ops = new_game()
    ff = build("Forebear", "{1}{W}", "Creature — Spirit", "Whenever a creature you control dies while this card is in "
               "your graveyard, you may pay {1}{W}. If you do, return this card from your graveyard to your hand.", 3, 1)
    me.graveyard = [ff]
    give_lands(g, me, 2, colors=(W,))
    x = put(g, creature("X", "1G", 1, 1), me)
    g.to_graveyard(x, "test")
    run(g)
    assert ff in me.hand


def test_new_intervening_conditions():
    g, me, ops = new_game()
    c = build("Weird", "{R}{R}", "Creature — Weird", "When this creature enters, if {R}{R} was spent to cast it, it "
              "deals 2 damage to each opponent.", 1, 1)
    give_lands(g, me, 2, colors=(R,))
    me.hand.append(c)
    life = ops[0].life
    assert g.cast(me, c)
    run(g)
    assert life - ops[0].life == 2
    tok = put(g, build("Ruler", "{2}{W}", "Creature — Human", "At the beginning of your end step, if a creature died "
                       "under your control this turn, create a 1/1 white Human Soldier creature token.", 2, 2), me)
    x = put(g, creature("X", "1G", 1, 1), me)
    g.to_graveyard(x, "test")
    n = len(me.battlefield)
    g.emit("end_step", player=me)
    run(g)
    assert len(me.battlefield) == n + 1 and tok in me.battlefield


def test_top_card_kind_check():
    g, me, ops = new_game()
    sc = put(g, build("Scope", "{1}", "Creature — Elf", "At the beginning of your upkeep, look at the top card of your "
                      "library. If it's a land card, you may put it onto the battlefield.", 1, 1), me)
    me.library = [creature("C", "1G", 1, 1), land("Forest", [G], basic=True)]
    g.emit("upkeep", player=me)
    run(g)
    assert any(pm.name == "Forest" for pm in me.battlefield) and sc in me.battlefield


def test_dice_table_rolls_and_applies_row():
    g, me, ops = new_game()
    cone = build("Cone", "{3}{U}", "Sorcery", "Roll a d20.\n1—9 | Tap all creatures your opponents control.\n"
                 "10—20 | Tap all creatures your opponents control.")
    assert cone.dice_table == ((1, 9, True), (10, 20, True))
    foe = put(g, creature("Foe", "1G", 2, 2), ops[0])
    give_lands(g, me, 4, colors=(U,))
    me.hand.append(cone)
    assert g.cast(me, cone)
    run(g)
    assert foe.tapped and 1 <= me.last_roll <= 20


def test_storage_land_and_spirit_guide_pool_mana():
    g, me, ops = new_game()
    vault = put(g, build("Vault", "", "Land", "{T}, Remove any number of storage counters from this land: Add {B} for "
                         "each storage counter removed this way."), me)
    vault.counters["storage"] = 3
    pool = me.mana_pool
    assert g.activate_ability(vault, 0)
    run(g)
    assert me.mana_pool - pool == 3 and not vault.counters.get("storage")
    esg = build("Guide", "{2}{G}", "Creature — Elf Spirit", "Exile this card from your hand: Add {G}.", 2, 2)
    me.hand.append(esg)
    pool = me.mana_pool
    assert g.activate_from_hand(me, esg, 0)
    run(g)
    assert me.mana_pool == pool + 1 and esg in me.exile
    assert esg.hand_abilities[0].get("mana_ab")


def test_strive_read_ahead_and_exert_watch():
    g, me, ops = new_game()
    sp = build("Strive", "{W}", "Instant", "Strive — This spell costs {1}{W} more to cast for each target beyond the "
               "first.\nAny number of target creatures each get +1/+1 until end of turn.")
    assert sp.strive_cost.cmc == 2
    sg = build("Saga", "{2}{B}", "Enchantment — Saga", "Read ahead\nI — You gain 1 life.\nII — You gain 2 life.\n"
               "III — You gain 3 life.")
    assert sg.read_ahead
    sc = build("Scav", "{1}{B}", "Creature — Jackal", "You may exert this creature as it attacks.", 2, 2)
    assert sc.can_exert
    w = put(g, build("Watcher", "{1}{B}", "Creature — Jackal", "Whenever you exert a creature, you gain 2 life.", 1, 1),
            me)
    a = put(g, sc, me)
    a.summoning_sick = False
    g.active_index = g.players.index(me)
    life = me.life
    g._declare_attackers(me, [(a, ops[0])])
    run(g)
    assert a.exerted and me.life == life + 2 and w in me.battlefield


def test_empower_jace_and_divided_damage_and_behold():
    g, me, ops = new_game()
    put(g, build("Way", "{1}{U}", "Enchantment", "When this enchantment enters, empower Jace 3."), me)
    put(g, build("Way2", "{1}{U}", "Enchantment", "When this enchantment enters, empower Jace 2."), me)
    jaces = [pm for pm in me.battlefield if pm.name == "Jace"]
    assert len(jaces) == 1 and jaces[0].counters["loyalty"] == 5
    foes = [put(g, creature(f"F{k}", "1G", 1, 1), ops[0]) for k in range(3)]
    import cardsdb
    cardsdb._effect_any("~ deals 3 damage divided as you choose among one, two, or three target creatures")(g, me)
    assert not any(f in ops[0].battlefield for f in foes)
    g, me, ops = new_game()
    gob = build("Cursetosser", "{B}", "Creature — Goblin", "As an additional cost to cast this spell, behold a Goblin "
                "or pay {2}.", 1, 1)
    give_lands(g, me, 1, colors=(B,))
    me.hand.append(gob)
    assert not g.cast(me, gob)                   # sin Goblin: necesita {2} más
    me.hand.append(creature("Gob2", "1R", 1, 1, subtypes=("Goblin",)))
    assert g.cast(me, gob) and gob._beheld


def test_global_heads_damage_blocks_gain_life():
    g, me, ops = new_game()
    put(g, build("Aurif", "{2}{W}{W}", "Enchantment", "Whenever a creature deals damage to you, put a gold counter on "
                 "it."), me)
    ogre = put(g, creature("Ogre", "2R", 3, 3), ops[0])
    g.deal_damage(ogre, me, 3, combat=True)
    run(g)
    assert ogre.counters.get("gold") == 1
    put(g, build("Strain", "{1}{R}", "Enchantment", "Whenever a creature blocks, this enchantment deals 1 damage to "
                 "that creature's controller."), me)
    a = put(g, creature("A", "1G", 2, 2), me)
    b = put(g, creature("B", "1G", 2, 2), ops[0])
    a.attacking, a.blocked_by, b.blocking = ops[0], [b], [a]
    life = ops[0].life
    g._combat_block_triggers([a])
    run(g)
    assert life - ops[0].life == 1
    kv = put(g, build("Kavu", "{1}{G}", "Creature — Kavu", "Whenever an opponent gains life, put a +1/+1 counter on "
                      "this creature.", 1, 1), me)
    g.gain_life(ops[0], 2)
    g.gain_life(me, 2)
    run(g)
    assert kv.counters.get("+1/+1") == 1


def test_death_trigger_filters_and_subtype_deaths():
    g, me, ops = new_game()
    me.library = [creature(f"L{k}", "1G", 1, 1) for k in range(5)]
    put(g, build("Cache", "{1}{G}", "Artifact", "Whenever a creature you control with a +1/+1 counter on it dies, "
                 "draw a card."), me)
    plain = put(g, creature("Plain", "1G", 1, 1), me)
    buff = put(g, creature("Buff", "1G", 1, 1), me)
    buff.counters["+1/+1"] = 1
    h = len(me.hand)
    g.to_graveyard(plain, "test")
    run(g)
    assert len(me.hand) == h
    g.to_graveyard(buff, "test")
    run(g)
    assert len(me.hand) == h + 1
    life = me.life
    put(g, build("Bishop", "{2}{W}", "Creature — Human", "Whenever an Angel you control dies, you gain 4 life.", 1, 4), me)
    ang = put(g, creature("Ang", "3W", 3, 3, subtypes=("Angel",)), me)
    g.to_graveyard(ang, "test")
    run(g)
    assert me.life == life + 4


def test_generic_evasion_and_count_statics():
    g, me, ops = new_game()
    a = put(g, build("Seeker", "{2}{B}", "Creature — Kor", "This creature can't be blocked except by artifact creatures "
                     "and/or white creatures.", 3, 2), me)
    green = put(g, creature("G", "1G", 2, 2), ops[0])
    white = put(g, creature("W", "1W", 2, 2), ops[0])
    assert not g._can_block_evasion(a, green) and g._can_block_evasion(a, white)
    gh = put(g, build("Ghost", "{1}{U}", "Creature — Spirit", "This creature can't be blocked by creatures with toughness "
                      "3 or greater.", 2, 2), me)
    wall = put(g, creature("Wall", "1W", 0, 4), ops[0])
    assert not g._can_block_evasion(gh, wall) and g._can_block_evasion(gh, green)
    hg = put(g, build("Guard", "{1}{W}", "Creature — Human", "This creature gets +1/+1 for each legendary creature you "
                      "control.", 1, 1), me)
    put(g, creature("Leg", "1G", 1, 1, legendary=True), me)
    assert hg.power == 2
    ops[0].hand = [creature(f"H{k}", "1G", 1, 1) for k in range(3)]
    en = put(g, build("Enemy", "{4}{U}", "Creature — Djinn", "This creature gets +1/+1 for each card in your opponents' "
                      "hands.", 0, 0), me)
    assert en.power == 3


def test_new_conditions_and_loyalty_fallback():
    import cardsdb
    assert cardsdb._cond_gc("enchanted creature is black") is not None
    assert cardsdb._cond_gc("your opponents control no creatures") is not None
    assert cardsdb._cond_gc("you descended this turn") is not None
    pw = build("Walker", "{2}{U}", "Legendary Planeswalker — Jace", "−1: Surveil 1.\n−3: Draw a card.")
    assert all(e is not None for _c, e in pw.loyalty_abilities)
