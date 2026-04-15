"""
Few-shot examples: CRAFTING
============================
Pattern:
    inspect_inventory()  →  craft_item()  →  inspect_inventory() [verify]

Crafting is purely inventory-based — no entities needed.
Always verify you have the required inputs first, then verify the output.

Key recipes (Factorio 1.1):
  iron-gear-wheel    : 2 × iron-plate
  copper-cable       : 1 × copper-plate → 2 copper-cable
  electronic-circuit : 3 × copper-cable + 1 × iron-plate
  automation-science-pack : 1 × copper-plate + 1 × iron-gear-wheel
"""

# ─── Example 1: Craft Iron Gear Wheels ───────────────────────────────────────
CRAFT_IRON_GEAR_WHEELS = """
# Goal: craft 10 iron gear wheels.
# Recipe: 2 iron-plate → 1 iron-gear-wheel  (0.5 s each)

from factorio_learning_environment.entities import Prototype

inv = inspect_inventory()
iron_plates = inv.get('iron-plate', 0)
print(f"Iron-plate available: {iron_plates} (need {10 * 2} for 10 gears)")

if iron_plates < 20:
    print(f"ERROR: not enough iron-plate.  Have {iron_plates}, need 20.")
else:
    craft_item(Prototype.IronGearWheel, quantity=10)
    inv = inspect_inventory()
    gears = inv.get('iron-gear-wheel', 0)
    print(f"Iron gear wheels crafted: {gears}")
"""

# ─── Example 2: Craft Copper Cable ───────────────────────────────────────────
CRAFT_COPPER_CABLE = """
# Goal: craft 20 copper cables.
# Recipe: 1 copper-plate → 2 copper-cable  (so 10 plates yield 20 cables)

from factorio_learning_environment.entities import Prototype

inv = inspect_inventory()
copper_plates = inv.get('copper-plate', 0)
cables_needed = 20
plates_needed = cables_needed // 2  # 10 plates → 20 cables
print(f"Copper-plate: {copper_plates} (need {plates_needed})")

if copper_plates < plates_needed:
    print(f"ERROR: need {plates_needed} copper-plate, have {copper_plates}.")
else:
    craft_item(Prototype.CopperCable, quantity=cables_needed)
    inv = inspect_inventory()
    print(f"Copper cable in inventory: {inv.get('copper-cable', 0)}")
"""

# ─── Example 3: Craft Electronic Circuits (Green Circuits) ───────────────────
CRAFT_ELECTRONIC_CIRCUITS = """
# Goal: craft 10 electronic circuits (green circuits).
# Recipe: 3 × copper-cable + 1 × iron-plate → 1 × electronic-circuit  (0.5 s each)
# Copper-cable can be sub-crafted automatically if we have enough copper-plate.

from factorio_learning_environment.entities import Prototype

inv = inspect_inventory()
iron_plates = inv.get('iron-plate', 0)
copper_cables = inv.get('copper-cable', 0)
copper_plates = inv.get('copper-plate', 0)

circuits_wanted = 10
cables_needed = circuits_wanted * 3         # 30 copper-cable
plates_needed_for_cables = cables_needed // 2  # 15 copper-plate (each plate → 2 cables)

print(f"iron-plate:    {iron_plates}  (need {circuits_wanted})")
print(f"copper-cable:  {copper_cables} (need {cables_needed})")
print(f"copper-plate:  {copper_plates} (need {plates_needed_for_cables} if crafting cables)")

# Craft cables first if needed
if copper_cables < cables_needed:
    shortfall = cables_needed - copper_cables
    plates_to_use = (shortfall + 1) // 2
    if copper_plates >= plates_to_use:
        craft_item(Prototype.CopperCable, quantity=shortfall)
    else:
        print(f"ERROR: not enough copper-plate or copper-cable.")

# Craft circuits
inv = inspect_inventory()
if inv.get('iron-plate', 0) >= circuits_wanted and inv.get('copper-cable', 0) >= cables_needed:
    craft_item(Prototype.ElectronicCircuit, quantity=circuits_wanted)
    inv = inspect_inventory()
    print(f"Electronic circuits: {inv.get('electronic-circuit', 0)}")
else:
    print(f"ERROR: still missing materials.  inv={inv}")
"""

ALL_EXAMPLES = {
    "craft_iron_gear_wheels": CRAFT_IRON_GEAR_WHEELS,
    "craft_copper_cable": CRAFT_COPPER_CABLE,
    "craft_electronic_circuits": CRAFT_ELECTRONIC_CIRCUITS,
}
