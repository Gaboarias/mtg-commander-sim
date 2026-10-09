"""Morph / megamorph / disguise / manifest / cloak, bestow, ninjutsu, madness y
cartas sin coste de maná (suspend)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cardsdb  # noqa: E402
from engine import G, U, B, R, W  # noqa: E402
from cards import creature  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands  # noqa: E402

FD = "Criatura boca abajo"


def _morph(name="Morphling Test", morph="{1}{G}", mega=False, extra=""):
    kw = "Megamorph" if mega else "Morph"
    return build(name, "{4}{G}{G}", "Creature — Beast", f"{kw} {morph}{extra}",
                 5, 5, keywords=[kw])


# ── boca abajo ───────────────────────────────────────────────────────────── #

def test_morph_cast_face_down_for_three_as_2_2():
    g, me, _ = new_game()
    give_lands(g, me, 3)
    c = _morph()
    me.hand = [c]
    assert g.cast_face_down(me, c)
    run(g)
    pm = me.battlefield[-1]
    assert pm.name == FD and (pm.power, pm.toughness) == (2, 2)
    assert pm.card._real is c and c not in me.hand
    assert me.available_mana() == 0


def test_turn_face_up_pays_morph_cost_no_etb_and_megamorph_counter():
    g, me, ops = new_game()
    give_lands(g, me, 6)
    etb = []
    c = _morph(mega=True)
    c.on_etb = lambda *a: etb.append(1)
    me.hand = [c]
    assert g.cast_face_down(me, c)
    run(g)
    pm = next(p for p in me.battlefield if p.name == FD)
    assert g.turn_face_up(me, pm)
    assert pm.card is c and pm.name == "Morphling Test"
    assert (pm.power, pm.toughness) == (6, 6)     # 5/5 + contador de megamorph
    assert not etb, "dar vuelta no es entrar al campo"


def test_turned_face_up_trigger_resolves():
    g, me, ops = new_game()
    give_lands(g, me, 7, colors=(W,))
    big = put(g, creature("Ogre", "4R", 5, 5), ops[0])
    c = build("Hidden Dragonslayer", "{1}{W}", "Creature — Human Knight",
              "Lifelink\nMegamorph {2}{W}\nWhen this creature is turned face up, destroy "
              "target creature with power 4 or greater an opponent controls.", 2, 1,
              keywords=["Lifelink", "Megamorph"])
    me.hand = [c]
    assert g.cast_face_down(me, c)
    run(g)
    pm = next(p for p in me.battlefield if p.name == FD)
    assert g.turn_face_up(me, pm)
    run(g)
    assert big not in ops[0].battlefield


def test_face_down_dies_real_card_goes_to_graveyard():
    g, me, _ = new_game()
    give_lands(g, me, 3)
    c = _morph()
    me.hand = [c]
    g.cast_face_down(me, c)
    run(g)
    pm = next(p for p in me.battlefield if p.name == FD)
    g.destroy(pm)
    g.sba()
    assert c in me.graveyard
    assert all(getattr(x, "_real", None) is None for x in me.graveyard)


def test_disguise_has_ward_two():
    g, me, ops = new_game()
    give_lands(g, me, 3)
    c = build("Disguised Test", "{3}{U}", "Creature — Human", "Disguise {2}{U}", 3, 3,
              keywords=["Disguise"])
    me.hand = [c]
    g.cast_face_down(me, c)
    run(g)
    pm = next(p for p in me.battlefield if p.name == FD)
    assert pm.has("ward") and pm.card.ward["mana"].cmc == 2
    assert g.face_up_cost(pm).cmc == 3


def test_manifest_creature_can_turn_up_for_mana_cost():
    g, me, _ = new_game()
    give_lands(g, me, 3)
    bear = creature("Bear", "1G", 2, 2)
    me.library.insert(0, bear)
    eff = cardsdb._atomic_effect("Manifest the top card of your library.")
    assert eff is not None
    eff(g, me)
    pm = next(p for p in me.battlefield if p.name == FD)
    assert g.face_up_cost(pm).cmc == 2
    assert g.turn_face_up(me, pm) and pm.name == "Bear"


def test_manifest_noncreature_cannot_turn_up():
    g, me, _ = new_game()
    eff = cardsdb._atomic_effect("Manifest the top card of your library.")
    eff(g, me)                              # arriba hay un Forest
    pm = next(p for p in me.battlefield if p.name == FD)
    assert g.face_up_cost(pm) is None


def test_ai_casts_morph_face_down_when_it_cannot_pay_full():
    g, me, ops = new_game()
    give_lands(g, me, 3)
    me.hand = [_morph()]
    me.command = []                       # sin comandante que compita por el maná
    me.policy.main_phase(g, me)
    run(g)
    assert any(p.name == FD for p in me.battlefield)


# ── bestow ───────────────────────────────────────────────────────────────── #

def _satyr():
    return build("Boon Satyr", "{1}{G}{G}", "Enchantment Creature — Satyr",
                 "Flash\nBestow {3}{G}{G}\nEnchanted creature gets +4/+2.", 4, 2,
                 keywords=["Flash", "Bestow"])


def test_bestow_attaches_and_buffs_host_then_becomes_creature():
    g, me, _ = new_game()
    give_lands(g, me, 5)
    host = put(g, creature("Elf", "G", 1, 1), me)
    sat = _satyr()
    me.hand = [sat]
    assert g.cast_bestow(me, sat, host)
    run(g)
    aura = next(p for p in me.battlefield if getattr(p.card, "_bestow", False))
    assert not aura.is_creature() and aura.enchanting is host
    assert (host.power, host.toughness) == (5, 3)
    g.destroy(host)
    g.sba()
    assert aura in me.battlefield and aura.is_creature()
    assert aura.card is sat and (aura.power, aura.toughness) == (4, 2)


def test_bestow_target_gone_enters_as_creature():
    g, me, ops = new_game()
    give_lands(g, me, 5)
    host = put(g, creature("Elf", "G", 1, 1), me)
    sat = _satyr()
    me.hand = [sat]
    # que no resuelva todavía: sacar el huésped antes de resolver la pila
    g.cast_bestow(me, sat, host)
    me.battlefield.remove(host)
    run(g)
    pm = next(p for p in me.battlefield if p.card is sat)
    assert pm.is_creature() and pm.enchanting is None


def test_bestowed_aura_destroyed_goes_to_graveyard_as_card():
    g, me, _ = new_game()
    give_lands(g, me, 5)
    host = put(g, creature("Elf", "G", 1, 1), me)
    sat = _satyr()
    me.hand = [sat]
    g.cast_bestow(me, sat, host)
    run(g)
    aura = next(p for p in me.battlefield if getattr(p.card, "_bestow", False))
    g.to_graveyard(aura)
    g.sba()
    assert sat in me.graveyard and (host.power, host.toughness) == (1, 1)


# ── ninjutsu ─────────────────────────────────────────────────────────────── #

def _ninja():
    return build("Ninja Test", "{3}{U}{B}", "Creature — Human Ninja",
                 "Ninjutsu {U}{B}\nWhenever this creature deals combat damage to a "
                 "player, draw a card.", 3, 2, keywords=["Ninjutsu"])


def test_ninjutsu_swaps_unblocked_attacker():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(U, B))
    rogue = put(g, creature("Rogue", "U", 1, 1), me)
    rogue.summoning_sick = False
    ninja = _ninja()
    me.hand = [ninja]
    declared = g._declare_attackers(me, [(rogue, ops[0])])
    life = ops[0].life
    perm = g.ninjutsu(me, ninja, rogue, declared)
    assert perm is not None and perm.tapped and perm.attacking is ops[0]
    assert rogue.card in me.hand and rogue not in me.battlefield
    hand0 = len(me.hand)
    g._finish_combat(declared)
    run(g)
    assert ops[0].life == life - 3
    assert len(me.hand) == hand0 + 1, "el disparo de daño de combate del ninja"


def test_ninjutsu_needs_unblocked_attacker():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(U, B))
    rogue = put(g, creature("Rogue", "U", 1, 1), me)
    rogue.summoning_sick = False
    wall = put(g, creature("Wall", "1W", 0, 4), ops[0])
    ninja = _ninja()
    me.hand = [ninja]
    declared = g._declare_attackers(me, [(rogue, ops[0])])
    g._apply_block_pairs(declared, [(rogue, wall)])
    assert g.ninjutsu(me, ninja, rogue, declared) is None
    assert ninja in me.hand


def test_ai_uses_ninjutsu_after_blocks():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(U, B))
    rogue = put(g, creature("Rogue", "U", 1, 1), me)
    rogue.summoning_sick = False
    me.hand = [_ninja()]
    g._resolve_combat(me, [(rogue, ops[0])])
    assert any(p.name == "Ninja Test" for p in me.battlefield)
    assert ops[0].life == 40 - 3


def test_commander_ninjutsu_from_command_zone():
    g, me, ops = new_game()
    give_lands(g, me, 2, colors=(U, B))
    yur = build("Yuriko, the Tiger's Shadow", "{1}{U}{B}",
                "Legendary Creature — Human Ninja",
                "Commander ninjutsu {U}{B}", 1, 3, keywords=["Commander ninjutsu"])
    me.command = [yur]
    me.commanders = [yur]
    rogue = put(g, creature("Rogue", "U", 1, 1), me)
    rogue.summoning_sick = False
    declared = g._declare_attackers(me, [(rogue, ops[0])])
    assert g.ninjutsu(me, yur, rogue, declared) is not None
    assert yur not in me.command


# ── madness / sin coste de maná ─────────────────────────────────────────── #

def _mad():
    return build("Mad Bolt", "{3}{R}", "Instant",
                 "Mad Bolt deals 3 damage to any target.\nMadness {R}", keywords=["Madness"])


def test_madness_bot_casts_for_madness_cost():
    g, me, ops = new_game()
    give_lands(g, me, 1, colors=(R,))
    c = _mad()
    g.discard_card(me, c)
    run(g)
    assert c in me.graveyard and me.available_mana() == 0
    assert any("madness" in ln for ln in g.log_lines)


def test_madness_without_mana_goes_to_graveyard():
    g, me, ops = new_game()
    c = _mad()
    g.discard_card(me, c)
    run(g)
    assert c in me.graveyard and c not in me.exile


def test_madness_human_chooses():
    g, me, ops = new_game()
    give_lands(g, me, 1, colors=(R,))
    g.interactive_human = me
    c = _mad()
    g.discard_card(me, c)
    ch = g.pending_choice
    assert ch and "Madness" in ch["prompt"] and c in me.exile
    ch["_apply"](1)                      # al cementerio
    g.pending_choice = None
    assert c in me.graveyard and c not in me.exile


def test_no_mana_cost_card_cannot_be_cast_but_suspends():
    g, me, _ = new_game()
    give_lands(g, me, 1, colors=(U,))
    av = build("Ancestral Vision", "", "Sorcery",
               "Suspend 4—{U}\nTarget player draws three cards.", keywords=["Suspend"])
    assert av.cost is None
    me.hand = [av]
    assert g.suspend_card(me, av)
    hand0 = len(me.hand)
    for _ in range(4):
        g._tick_suspended(me)
    run(g)
    assert len(me.hand) == hand0 + 3


# ── humano en /play ──────────────────────────────────────────────────────── #

def _human(seed=3):
    import interactive, decks
    from cards import land
    defs = [("Tu",) + decks.build("marvel"), ("R",) + decks.build("strixhaven")]
    ig = interactive.InteractiveGame(defs, human_index=0, seed=seed)
    ig.keep([])
    hu = ig.human()
    for pl in ig.players:                  # mesa limpia: sin criaturas que bloqueen
        pl.battlefield = [pm for pm in pl.battlefield if not pm.is_creature()]
    for _ in range(6):
        ig.g.move_to_battlefield(land("Swamp", [U, B, G, W, R], basic=False), hu)
    return ig, hu


def test_human_casts_face_down_and_turns_it_up():
    ig, hu = _human()
    c = _morph()
    hu.hand.append(c)
    opt = next(x for x in ig.legal()["casts"] if x["zone"] == "face_down")
    ig.cast(i=opt["i"], zone="face_down")
    st = ig.state()
    mine = st["players"][0]["battlefield"]
    fd = next(p for p in mine if p.get("face_down") == "Morphling Test")
    assert fd["name"] == FD
    # el rival no ve qué es
    assert "face_down" not in str(st["players"][1]["battlefield"])
    fu = ig.legal()["face_up"]
    assert fu and fu[0]["name"] == "Morphling Test" and fu[0]["playable"]
    ig.face_up(fu[0]["uid"])
    assert any(p.name == "Morphling Test" for p in hu.battlefield)


def test_human_bestow_from_cast_list():
    ig, hu = _human()
    host = ig.g.move_to_battlefield(creature("Elf", "G", 1, 1), hu)
    hu.hand.append(_satyr())
    opt = next(x for x in ig.legal()["casts"] if x["zone"] == "bestow")
    ig.cast(i=opt["i"], zone="bestow", target_uids=[host.uid])
    ig.g.resolve_stack()
    assert (host.power, host.toughness) == (5, 3)


def test_human_ninjutsu_in_damage_window():
    ig, hu = _human()
    rogue = ig.g.move_to_battlefield(creature("Rogue", "U", 1, 1), hu)
    rogue.summoning_sick = False
    hu.hand.append(_ninja())
    ig.attack(uids=[rogue.uid])
    st = ig.state()
    assert st["combat"] and st["combat"]["stage"] == "damage"
    nj = st["combat"]["ninjutsu"]
    assert nj and nj[0]["name"] == "Ninja Test"
    opp = ig.players[1]
    life = opp.life
    ig.ninjutsu(nj[0]["i"], nj[0]["zone"], rogue.uid)
    assert any(p.name == "Ninja Test" for p in hu.battlefield)
    ig.finish_combat()
    assert opp.life == life - 3
    assert any(c.name == "Rogue" for c in hu.hand)


def test_each_opponent_upkeep_trigger_only_on_opponent_turns():
    g, me, ops = new_game()
    c = build("Opp Upkeep Drawer", "{2}{U}", "Creature — Horror",
              "At the beginning of each opponent's upkeep, draw a card.", 2, 2)
    put(g, c, me)
    h0 = len(me.hand)
    g.emit("each_upkeep", active=me)
    run(g)
    assert len(me.hand) == h0
    g.emit("each_upkeep", active=ops[0])
    run(g)
    assert len(me.hand) == h0 + 1


def test_cast_from_hand_trigger_manifests():
    g, me, ops = new_game()
    c = build("Cryptic Pursuit Test", "{B}{G}{U}", "Enchantment",
              "Whenever you cast an instant or sorcery spell from your hand, manifest the "
              "top card of your library.")
    put(g, c, me)
    give_lands(g, me, 1, colors=(R,))
    bolt = build("Shock", "{R}", "Instant", "Shock deals 2 damage to any target.")
    me.hand = [bolt]
    g.cast(me, bolt, targets=[ops[0]])
    run(g)
    assert any(p.name == FD for p in me.battlefield)


def test_equipment_manifest_dread_and_attach():
    g, me, _ = new_game()
    eq = build("Killer's Mask Test", "{2}", "Artifact — Equipment",
               "When this Equipment enters, manifest dread, then attach this Equipment to "
               "that creature.\nEquipped creature has menace.\nEquip {2}")
    pm = put(g, eq, me)
    fd = next(p for p in me.battlefield if p.name == FD)
    assert pm.enchanting is fd
    assert len(me.graveyard) == 1        # la otra carta de manifest dread


def test_wingmantle_chaplain_no_bird_loop():
    g, me, _ = new_game()
    ch = build("Wingmantle Chaplain", "{3}{W}", "Creature — Human Cleric",
               "Defender\nWhen this creature enters, create a 1/1 white Bird creature token "
               "with flying for each creature with defender you control.\nWhenever another "
               "creature you control with defender enters, create a 1/1 white Bird creature "
               "token with flying.", 0, 3, keywords=["Defender"])
    put(g, ch, me)
    birds = [p for p in me.battlefield if p.name == "Bird"]
    assert len(birds) == 1 and not birds[0].has("defender")
    put(g, creature("Wall", "1W", 0, 4, kw=("defender",)), me)
    assert sum(1 for p in me.battlefield if p.name == "Bird") == 2


def test_aboleth_spawn_copies_only_entering_creatures_etb():
    g, me, ops = new_game()
    ab = build("Aboleth Spawn", "{2}{U}", "Creature — Aboleth",
               "Flash\nWard {2}\nProbing Telepathy — Whenever a creature entering under an "
               "opponent's control causes a triggered ability of that creature to trigger, "
               "you may copy that ability. You may choose new targets for the copy.", 2, 3,
               keywords=["Flash", "Ward"])
    put(g, ab, me)
    h = len(me.hand)
    put(g, creature("Bear", "1G", 2, 2), ops[0])          # sin disparo: nada
    assert len(me.hand) == h
    wall = build("Wall of Omens", "{1}{W}", "Creature — Wall",
                 "Defender\nWhen this creature enters, draw a card.", 0, 4,
                 keywords=["Defender"])
    put(g, wall, ops[0])
    assert len(me.hand) == h + 1
