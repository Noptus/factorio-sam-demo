"""
Few-shot examples: SMELTING
============================
Pattern:
    craft_item(StoneFurnace)  →  place_entity()
    →  insert_item(fuel)  →  insert_item(ore)
    →  sleep()            →  extract_item(plates)

Prerequisites: iron-ore, coal, and 5 stone (for crafting a furnace) in inventory.
Always verify the inventory BEFORE starting so the agent knows what it has.
"""

# ─── Example 1: Smelt Iron Plates ────────────────────────────────────────────
SMELT_IRON_PLATES = """
# Goal: produce 20 iron plates from iron ore using a stone furnace.

from factorio_learning_environment.entities import Prototype, Direction, Position

# 1. Ensure we have required materials
inv = inspect_inventory()
print(f"Before smelting — iron-ore: {inv.get('iron-ore',0)}, coal: {inv.get('coal',0)}, stone: {inv.get('stone',0)}")

# 2. Craft a stone furnace if we don't have one already (costs 5 stone)
if inv.get('stone-furnace', 0) == 0:
    craft_item(Prototype.StoneFurnace, quantity=1)

# 3. Place the furnace 2 tiles east of the player
player_pos = get_position()
furnace_pos = Position(x=player_pos.x + 2, y=player_pos.y)
furnace = place_entity(Prototype.StoneFurnace, furnace_pos, Direction.NORTH)
print(f"Furnace placed at {furnace.position}")

# 4. Fuel it with coal (each coal lasts ~4 smelts at full speed)
insert_item(furnace, Prototype.Coal, quantity=10)

# 5. Load 20 iron ore into the input slot
insert_item(furnace, Prototype.IronOre, quantity=20)

# 6. Wait for smelting (iron ore → iron plate: 3.2 s each at base speed)
sleep(75)  # ~3.5 s * 20 + buffer

# 7. Extract the iron plates
extract_item(furnace, Prototype.IronPlate, quantity=20)
inv = inspect_inventory()
print(f"Iron plates in inventory: {inv.get('iron-plate', 0)}")
"""

# ─── Example 2: Smelt Copper Plates ──────────────────────────────────────────
SMELT_COPPER_PLATES = """
# Goal: produce 20 copper plates.  Same pattern as iron.

from factorio_learning_environment.entities import Prototype, Direction, Position

inv = inspect_inventory()
print(f"Copper-ore: {inv.get('copper-ore',0)}, coal: {inv.get('coal',0)}")

if inv.get('stone-furnace', 0) == 0:
    craft_item(Prototype.StoneFurnace, quantity=1)

player_pos = get_position()
furnace_pos = Position(x=player_pos.x + 2, y=player_pos.y + 2)
furnace = place_entity(Prototype.StoneFurnace, furnace_pos, Direction.NORTH)

insert_item(furnace, Prototype.Coal, quantity=10)
insert_item(furnace, Prototype.CopperOre, quantity=20)

sleep(75)

extract_item(furnace, Prototype.CopperPlate, quantity=20)
inv = inspect_inventory()
print(f"Copper plates: {inv.get('copper-plate', 0)}")
"""

# ─── Example 3: Smelt Steel Plates ───────────────────────────────────────────
SMELT_STEEL = """
# Goal: produce 5 steel plates (each costs 5 iron plates, 17.6 s each).
# NOTE: steel requires iron-plate as input (not iron-ore).

from factorio_learning_environment.entities import Prototype, Direction, Position

inv = inspect_inventory()
iron_plates_needed = 5 * 5  # 5 steel × 5 iron-plates each
print(f"Iron-plates available: {inv.get('iron-plate',0)} (need {iron_plates_needed})")

if inv.get('stone-furnace', 0) == 0:
    craft_item(Prototype.StoneFurnace, quantity=1)

player_pos = get_position()
furnace_pos = Position(x=player_pos.x + 2, y=player_pos.y - 2)
furnace = place_entity(Prototype.StoneFurnace, furnace_pos, Direction.NORTH)

insert_item(furnace, Prototype.Coal, quantity=15)
# Insert iron plates (not ore!) — furnace will detect the steel recipe automatically
insert_item(furnace, Prototype.IronPlate, quantity=25)

sleep(100)  # 17.6 s * 5 + buffer

extract_item(furnace, Prototype.SteelPlate, quantity=5)
inv = inspect_inventory()
print(f"Steel plates: {inv.get('steel-plate', 0)}")
"""

ALL_EXAMPLES = {
    "smelt_iron_plates": SMELT_IRON_PLATES,
    "smelt_copper_plates": SMELT_COPPER_PLATES,
    "smelt_steel": SMELT_STEEL,
}
