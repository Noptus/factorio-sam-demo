"""
Few-shot examples: ENTITY PLACEMENT
=====================================
Pattern:
    get_resource_patches() / get_position()  →  calculate_placement()
    →  place_entity(prototype, position, direction)  →  verify_placement()

KEY RULES:
 1. Always check for space before placing: use get_entities() to see what's nearby.
 2. Electric mining drills need clear space (3×3) aligned with the ore patch.
 3. Burner mining drills are 2×2.
 4. Stone furnaces are 2×2.
 5. Place entities on valid tiles — not on water, cliffs, or other entities.
 6. Direction controls which way output/input faces, not the entity rotation.
"""

# ─── Example 1: Place a Burner Mining Drill on Iron Ore ──────────────────────
PLACE_BURNER_DRILL = """
# Goal: place a burner mining drill on the nearest iron-ore patch.
# Burner drill is 2×2.  Output direction (Direction.NORTH) means output
# is on the NORTH side of the drill.

from factorio_learning_environment.entities import Prototype, Direction, Position

inv = inspect_inventory()
if inv.get('burner-mining-drill', 0) == 0:
    # Stone furnace costs 3 iron-plate; burner drill costs 3 iron-plate + 3 iron-gear-wheel + 1 stone-furnace
    craft_item(Prototype.BurnerMiningDrill, quantity=1)

iron_patches = get_resource_patches('iron-ore', radius=50)
if not iron_patches:
    print("ERROR: no iron-ore within 50 tiles.")
else:
    # Place the drill at the patch centre; FLE will snap to a valid tile
    patch = min(iron_patches, key=lambda p: p.position.distance(get_position()))
    drill_pos = patch.position

    # Ensure no entity is already here
    existing = get_entities(Prototype.BurnerMiningDrill, position=drill_pos, radius=2)
    if existing:
        print(f"Drill already present at {drill_pos}, skipping placement.")
    else:
        drill = place_entity(Prototype.BurnerMiningDrill, drill_pos, Direction.NORTH)
        print(f"Burner drill placed at {drill.position}")

        # Fuel it so it starts immediately
        insert_item(drill, Prototype.Coal, quantity=10)
        print("Drill fuelled with 10 coal.")
"""

# ─── Example 2: Place an Assembling Machine ──────────────────────────────────
PLACE_ASSEMBLER = """
# Goal: place an assembling machine (3×3) near the player and set its recipe.

from factorio_learning_environment.entities import Prototype, Direction, Position

inv = inspect_inventory()
if inv.get('assembling-machine-1', 0) == 0:
    craft_item(Prototype.AssemblingMachine1, quantity=1)

player_pos = get_position()
# Place 4 tiles east of the player to leave room
asm_pos = Position(x=player_pos.x + 4, y=player_pos.y)

asm = place_entity(Prototype.AssemblingMachine1, asm_pos, Direction.NORTH)
print(f"Assembling machine placed at {asm.position}")

# Set the recipe BEFORE inserting materials
set_entity_recipe(asm, 'iron-gear-wheel')
print("Recipe set to: iron-gear-wheel")

# Inserting raw materials will now work
insert_item(asm, Prototype.IronPlate, quantity=20)
print("Inserted 20 iron-plate into assembler.")
"""

# ─── Example 3: Place Electric Poles for Power ───────────────────────────────
PLACE_ELECTRIC_POLES = """
# Goal: lay a chain of small electric poles to carry power from a steam engine.
# Small electric poles cover 5 tiles and connect within 7.5 tiles of each other.

from factorio_learning_environment.entities import Prototype, Direction, Position

inv = inspect_inventory()
poles_needed = 4
if inv.get('small-electric-pole', 0) < poles_needed:
    craft_item(Prototype.SmallElectricPole, quantity=poles_needed)

player_pos = get_position()
placed_poles = []

# Place 4 poles in a row every 7 tiles east of the player
for i in range(poles_needed):
    pole_pos = Position(x=player_pos.x + (i * 7), y=player_pos.y - 2)
    try:
        pole = place_entity(Prototype.SmallElectricPole, pole_pos, Direction.NORTH)
        placed_poles.append(pole)
        print(f"Pole {i+1} placed at {pole.position}")
    except Exception as e:
        print(f"Could not place pole {i+1}: {e}")

print(f"Placed {len(placed_poles)} / {poles_needed} poles.")
"""

ALL_EXAMPLES = {
    "place_burner_drill": PLACE_BURNER_DRILL,
    "place_assembler": PLACE_ASSEMBLER,
    "place_electric_poles": PLACE_ELECTRIC_POLES,
}
