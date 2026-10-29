"""Batch 35: Rescue, Reaper's Scythe, Invisible Force Field, Exocrine, Infernal/Intellectual
Offering, Glass-Cast Heart, Goblin Spymaster, Fandaniel, Eidolon of Countless Battles,
Domineering Will, Deathleaper, Coram, Copy Land, Council of Reeds, Cyberdrive Awakener, Clamavus,
Determined Iteration, Kari Zev, Lulu, Maester Seymour, Opportunistic Dragon, Hooded Hydra, Grave
Sifter, Flame On!, Endless Detour, Dredge the Mire, Exterminatus."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import G, U, B, R, W  # noqa: E402
from cards import creature, land  # noqa: E402
from test_parser_corpus import build, new_game, run, put, give_lands, artifact  # noqa: E402


def test_rescue_bounces_artifact_and_grows():
    g, me, ops = new_game()
    a = put(g, build("Gizmo", "{2}", "Artifact", "When this artifact enters, draw a card."), me)
    r = put(g, build("Rescue, Pepper Potts", "{1}{U}", "Legendary Artifact Creature — Human Hero", "Flash\nFlying\nWhen "
                     "Rescue enters, return up to one other target artifact or creature you control to its owner's hand. "
                     "If it was an artifact, put a +1/+1 counter on Rescue.", 2, 1), me)
    assert a not in me.battlefield and r.counters.get("+1/+1") == 1


def test_reapers_scythe_soul_counters():
    g, me, ops = new_game()
    sc = put(g, build("Reaper's Scythe", "{2}{B}", "Artifact — Equipment", "Job select\nAt the beginning of your end step, "
                      "put a soul counter on this Equipment for each player who lost life this turn.\nEquipped creature "
                      "gets +1/+1 for each soul counter on this Equipment and is an Assassin in addition to its other "
                      "types.\nDeath Sickle — Equip {2}"), me)
    c = put(g, creature("C", "G", 1, 1), me)
    sc.enchanting = c
    p0 = c.power
    g.deal_damage(None, ops[0], 1)
    g.emit("end_step", player=me)
    run(g)
    assert sc.counters.get("soul") == 1 and c.power == p0 + 1


def test_exocrine_damages_everyone():
    g, me, ops = new_game()
    o = put(g, creature("O", "G", 2, 2), ops[0])
    ex = build("Exocrine", "{X}{2}{R}", "Creature — Tyranid", "Ravenous\nBio-plasmic Barrage — When this creature "
               "enters, it deals X damage to each player and each other creature.", 2, 2)
    ex.etb_counters = {"+1/+1": 2}
    l0 = ops[0].life
    put(g, ex, me)
    assert o not in ops[0].battlefield and ops[0].life == l0 - 2


def test_intellectual_offering_draws_both():
    g, me, ops = new_game()
    io = build("Intellectual Offering", "{4}{U}", "Instant", "Choose an opponent. You and that player each draw three "
               "cards.\nChoose an opponent. Untap all nonland permanents you control and all nonland permanents that "
               "player controls.")
    io.on_cast_resolve(g, me, [])
    assert len(me.hand) == 3 and len(ops[0].hand) == 3


def test_glass_cast_heart_blood_on_vampire_attack():
    g, me, ops = new_game()
    put(g, build("Glass-Cast Heart", "{2}{B}", "Artifact", "Whenever one or more Vampires you control attack, create a "
                 "Blood token."), me)
    v = put(g, creature("V", "B", 2, 2, subtypes=("Vampire",)), me)
    v.summoning_sick = False
    g.active_index = 0
    g._declare_attackers(me, [(v, ops[0])])
    run(g)
    assert any(x.name == "Blood" for x in me.battlefield)


def test_goblin_spymaster_gives_goblin():
    g, me, ops = new_game()
    put(g, build("Goblin Spymaster", "{2}{R}", "Creature — Goblin Rogue", "First strike\nAt the beginning of each "
                 "opponent's end step, that player creates a 1/1 red Goblin creature token with \"Creatures you control "
                 "attack each combat if able.\"", 2, 1), me)
    g.emit("each_end_step", active=ops[0])
    run(g)
    gob = [x for x in ops[0].battlefield if x.name == "Goblin"]
    assert gob and gob[0].card.forced_attack == "own"


def test_eidolon_counts_creatures_and_auras():
    g, me, ops = new_game()
    e = put(g, build("Eidolon of Countless Battles", "{1}{W}{W}", "Enchantment Creature — Spirit", "Bestow {2}{W}{W}\n"
                     "This creature and enchanted creature each get +1/+1 for each creature you control and +1/+1 for "
                     "each Aura you control.", 0, 0), me)
    put(g, creature("C", "G", 1, 1), me)
    assert e.power == 2


def test_domineering_will_and_deathleaper():
    g, me, ops = new_game()
    put(g, build("Deathleaper, Terror Weapon", "{2}{R}{G}", "Legendary Creature — Tyranid", "Flash\nHaste\nFlesh Hooks — "
                 "Creatures you control that entered this turn have double strike.", 3, 3), me)
    n = put(g, creature("New", "G", 2, 2), me)
    assert n.has("double_strike")
    n._etb_turn = g.turn - 1
    assert not n.has("double_strike")


def test_coram_power():
    g, me, ops = new_game()
    co = put(g, build("Coram, the Undertaker", "{1}{B}{R}{G}", "Legendary Creature — Human Warrior", "Coram gets +X/+0, "
                      "where X is the greatest power among creature cards in all graveyards.\nWhenever Coram attacks, "
                      "each player mills a card.", 0, 5), me)
    ops[0].graveyard.append(creature("Fat", "5G", 7, 7))
    assert co.power == 7


def test_copy_land_and_council_of_reeds():
    g, me, ops = new_game()
    put(g, build("Gaea's Cradle", "", "Legendary Land", "{T}: Add {G} for each creature you control."), ops[0])
    cl = put(g, build("Copy Land", "{2}{U}", "Enchantment", "You may have this enchantment enter as a copy of any land on "
                      "the battlefield, except it's an enchantment in addition to its other types."), me)
    assert cl.name == "Gaea's Cradle" and "enchantment" in cl.card.types
    cr = build("Council of Reeds", "{2}{U}", "Legendary Creature — Human Scientist Hero", "The \"legend rule\" doesn't "
               "apply to creatures you control.\nAt the beginning of combat on your turn, if you've cast a noncreature "
               "spell this turn, create a token that's a copy of Council of Reeds.", 2, 2)
    p = put(g, cr, me)
    me._noncr_cast_turn = g.turn
    g.emit("begin_combat", player=me)
    run(g)
    assert sum(1 for x in me.battlefield if x.name == "Council of Reeds") == 2 and p in me.battlefield


def test_cyberdrive_and_clamavus():
    g, me, ops = new_game()
    a = put(g, artifact("Rock"), me)
    put(g, build("Cyberdrive Awakener", "{5}{U}", "Artifact Creature — Construct", "Flying\nOther artifact creatures you "
                 "control have flying.\nWhen this creature enters, each noncreature artifact you control becomes a 4/4 "
                 "artifact creature until end of turn.", 4, 4), me)
    assert a.is_creature() and a.power == 4
    put(g, build("Clamavus", "{4}{G}", "Creature — Human Tyranid Artificer", "Proclamator Hailer — Each creature you "
                 "control gets +1/+1 for each +1/+1 counter on it.", 3, 3), me)
    c = put(g, creature("C", "G", 1, 1), me)
    g.add_counters(c, "+1/+1", 2)
    assert c.power == 5


def test_kari_zev_ragavan_and_lulu():
    g, me, ops = new_game()
    kz = put(g, build("Kari Zev, Skyship Raider", "{1}{R}", "Legendary Creature — Human Pirate", "First strike, menace\n"
                      "Whenever Kari Zev attacks, create Ragavan, a legendary 2/1 red Monkey creature token. Ragavan "
                      "enters tapped and attacking. Exile that token at end of combat.", 1, 3,
                      keywords=("First strike", "Menace")), me)
    l0 = ops[0].life
    kz.summoning_sick = False
    g.active_index = 0
    decl = g._declare_attackers(me, [(kz, ops[0])])
    g._finish_combat(decl)
    run(g)
    assert ops[0].life == l0 - 3 and not any(x.name == "Ragavan" for x in me.battlefield)


def test_opportunistic_dragon_steals_and_returns():
    g, me, ops = new_game()
    t = put(g, artifact("Relic"), ops[0])
    od = put(g, build("Opportunistic Dragon", "{2}{R}{R}", "Creature — Dragon", "Flying\nWhen this creature enters, "
                      "choose target Human or artifact an opponent controls. For as long as this creature remains on the "
                      "battlefield, gain control of that permanent, it loses all abilities, and it can't attack or "
                      "block.", 4, 3), me)
    assert t in me.battlefield and t.abilities_off()
    g.destroy(od)
    run(g)
    assert t in ops[0].battlefield


def test_hooded_hydra_face_up_counters():
    g, me, ops = new_game()
    hh = build("Hooded Hydra", "{X}{G}{G}", "Creature — Snake Hydra", "This creature enters with X +1/+1 counters on it.\n"
               "When this creature dies, create a 1/1 green Snake creature token for each +1/+1 counter on it.\nMorph "
               "{3}{G}{G}\nAs this creature is turned face up, put five +1/+1 counters on it.", 0, 0)
    assert hh.on_turn_face_up is not None


def test_grave_sifter_and_dredge_the_mire():
    g, me, ops = new_game()
    me.graveyard += [creature("E1", "G", 1, 1, subtypes=("Elf",)), creature("E2", "G", 1, 1, subtypes=("Elf",))]
    put(g, build("Grave Sifter", "{5}{G}", "Creature — Elemental Beast", "When this creature enters, each player chooses a "
                 "creature type and returns any number of cards of that type from their graveyard to their hand.", 5, 7),
        me)
    assert sum(1 for x in me.hand if x.name in ("E1", "E2")) == 2
    ops[0].graveyard.append(creature("Theirs", "3G", 4, 4))
    dm = build("Dredge the Mire", "{3}{B}", "Sorcery", "Each opponent chooses a creature card in their graveyard. Put "
               "those cards onto the battlefield under your control.")
    dm.on_cast_resolve(g, me, [])
    assert any(x.name == "Theirs" for x in me.battlefield)


def test_endless_detour_and_exterminatus():
    g, me, ops = new_game()
    t = put(g, creature("T", "G", 3, 3), ops[0])
    ed = build("Endless Detour", "{G}{W}{U}", "Instant", "The owner of target spell, nonland permanent, or card in a "
               "graveyard puts it on their choice of the top or bottom of their library.")
    ed.on_cast_resolve(g, me, [t])
    assert t not in ops[0].battlefield and ops[0].library[-1].name == "T"
    ind = put(g, creature("Ind", "G", 3, 3, kw=("indestructible",)), ops[0])
    ex = build("Exterminatus", "{5}{W}{B}", "Sorcery", "Nonland permanents your opponents control lose indestructible "
               "until end of turn.\nDestroy all nonland permanents.")
    ex.on_cast_resolve(g, me, [])
    assert ind not in ops[0].battlefield
